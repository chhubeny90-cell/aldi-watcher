"""LITE safety tests using deterministic providers; never contact ALDI."""

import multiprocessing as mp
import os
import sqlite3
import time
from pathlib import Path

import pytest

from core.database import Database
from lite import Confirmation, Engine, MailEvent, Offer, Snapshot
from lite.store import EventStore


FREE = Offer(data_mb=1000, price_cents=0, free_unlimited=True, offer_id="free-1gb")
ACCOUNT = "primary"


def mail(identity="mail-1", kind="exhausted", received_at=None):
    return MailEvent(identity, "mailbox-primary", identity,
                     time.time() if received_at is None else received_at, kind, ACCOUNT)


class ProviderFixture:
    def __init__(self, snapshot=None, confirmation=None, recovered=None):
        self.snapshot = snapshot or Snapshot(True, True, FREE)
        self.confirmation = confirmation or Confirmation("SUCCESS", "booking-1")
        self.recovered = recovered or Confirmation("UNKNOWN")
        self.inspections = 0
        self.bookings = []
        self.reconciliations = []
        self.closed = False

    def inspect(self):
        self.inspections += 1
        return self.snapshot

    def book(self, recharge_id, offer):
        self.bookings.append((recharge_id, offer))
        if isinstance(self.confirmation, Exception):
            raise self.confirmation
        return self.confirmation

    def reconcile(self, record):
        self.reconciliations.append(record.recharge_id)
        return self.recovered

    def close(self):
        self.closed = True


def run(tmp_path, provider, event=None, **kwargs):
    options = {"dry_run": False, **kwargs}
    return Engine(tmp_path / "state.sqlite", provider, ACCOUNT, **options).process(event or mail())


def test_warning80_without_offer_exits_once(tmp_path):
    provider = ProviderFixture(snapshot=Snapshot(True, True))
    result = run(tmp_path, provider, mail(kind="warning80"))
    assert (result.status, result.action) == ("NO_ACTION", "CHECK")
    assert provider.inspections == 1
    assert not provider.bookings
    assert provider.closed


def test_exhausted_dry_run_recognizes_free_gb_without_reservation(tmp_path):
    provider = ProviderFixture()
    result = run(tmp_path, provider, dry_run=True)
    assert (result.status, result.action) == ("DRY_RUN", "WOULD_REFILL")
    assert not provider.bookings
    with sqlite3.connect(tmp_path / "state.sqlite") as db:
        assert db.execute("SELECT COUNT(*) FROM recharges").fetchone()[0] == 0


def test_recent_success_blocks_new_mail(tmp_path):
    first = run(tmp_path, ProviderFixture(), mail("first"))
    second_provider = ProviderFixture()
    second = run(tmp_path, second_provider, mail("second"))
    assert first.status == "SUCCESS"
    assert second.status == "NO_ACTION"
    assert second.error_class == "RECENT_SUCCESS"
    assert not second_provider.bookings


def test_request_timeout_is_unknown_across_database_reopen(tmp_path):
    first_provider = ProviderFixture(confirmation=TimeoutError("password=must-not-be-stored"))
    first = run(tmp_path, first_provider, mail("first"))
    assert first.status == "UNKNOWN"
    second_provider = ProviderFixture()
    second = run(tmp_path, second_provider, mail("second"))
    assert second.status == "BLOCKED"
    assert second_provider.reconciliations == [first.recharge_id]
    assert second_provider.inspections == 0
    assert not second_provider.bookings
    assert b"must-not-be-stored" not in (tmp_path / "state.sqlite").read_bytes()


class DurableCallProvider(ProviderFixture):
    def __init__(self, counter_path, started=None, release=None, crash=False):
        super().__init__()
        self.counter_path = counter_path
        self.started = started
        self.release = release
        self.crash = crash

    def book(self, recharge_id, offer):
        with open(self.counter_path, "a", encoding="utf-8") as counter:
            counter.write(recharge_id + "\n")
            counter.flush()
            os.fsync(counter.fileno())
        if self.started:
            self.started.set()
        if self.crash:
            os._exit(23)
        if self.release:
            assert self.release.wait(15)
        return Confirmation("SUCCESS", "booking-after-call")


def _booking_worker(db_path, counter_path, event, started=None, release=None, crash=False):
    provider = DurableCallProvider(counter_path, started, release, crash)
    Engine(db_path, provider, ACCOUNT, dry_run=False).process(event)


def _reserve_crash_worker(db_path, event):
    store = EventStore(db_path)
    store.claim_event(event)
    store.reserve(event.event_id, "aldi_talk", ACCOUNT, 0)
    os._exit(24)


@pytest.mark.skipif(os.name != "posix", reason="LITE uses the deployment's POSIX flock")
def test_crash_restarts_reconstruct_provider_success_without_rebooking(tmp_path):
    context = mp.get_context("spawn")
    event = mail("crashed")
    db_path = str(tmp_path / "state.sqlite")
    counter = str(tmp_path / "provider-calls")
    child = context.Process(target=_booking_worker, args=(db_path, counter, event), kwargs={"crash": True})
    child.start()
    child.join(15)
    assert child.exitcode == 23
    pending = Database(db_path).get_unresolved_recharges("aldi_talk", ACCOUNT)
    assert len(pending) == 1 and pending[0].status == "PENDING"
    store = EventStore(db_path)
    assert store.get_event(event.event_id)["recharge_id"] == pending[0].recharge_id
    provider = ProviderFixture(recovered=Confirmation("SUCCESS", "verified-after-restart"))
    result = Engine(db_path, provider, ACCOUNT, dry_run=False).process(event)
    assert (result.status, result.action) == ("SUCCESS", "RECONCILED")
    assert not provider.bookings
    assert len(Path(counter).read_text().splitlines()) == 1
    assert store.get_event(event.event_id)["booking_id"] == "verified-after-restart"


@pytest.mark.skipif(os.name != "posix", reason="LITE uses the deployment's POSIX flock")
def test_crash_before_request_keeps_atomic_event_link_and_requires_reconciliation(tmp_path):
    context = mp.get_context("spawn")
    event = mail("reserved-before-crash")
    path = str(tmp_path / "state.sqlite")
    child = context.Process(target=_reserve_crash_worker, args=(path, event))
    child.start()
    child.join(15)
    assert child.exitcode == 24
    store = EventStore(path)
    pending = store.get_unresolved_recharges("aldi_talk", ACCOUNT)
    assert len(pending) == 1
    assert store.get_event(event.event_id)["recharge_id"] == pending[0].recharge_id
    provider = ProviderFixture()
    result = Engine(path, provider, ACCOUNT, dry_run=False).process(event)
    assert result.status == "UNKNOWN"
    assert provider.reconciliations == [pending[0].recharge_id]
    assert not provider.inspections and not provider.bookings


@pytest.mark.skipif(os.name != "posix", reason="LITE uses the deployment's POSIX flock")
def test_two_events_and_recovery_are_fenced_while_worker_is_active(tmp_path):
    context = mp.get_context("spawn")
    started, release = context.Event(), context.Event()
    event = mail("worker")
    other_event = mail("other")
    db_path = str(tmp_path / "state.sqlite")
    counter = str(tmp_path / "provider-calls")
    child = context.Process(target=_booking_worker, args=(db_path, counter, event, started, release))
    child.start()
    try:
        assert started.wait(15)
        racing_provider = ProviderFixture(recovered=Confirmation("FAILED"))
        competing = Engine(db_path, racing_provider, ACCOUNT, dry_run=False).process(other_event)
        assert competing.status == "BUSY" and competing.action == "RETRY"
        assert not racing_provider.reconciliations and not racing_provider.bookings
        assert EventStore(db_path).get_event(other_event.event_id) is None
        assert Database(db_path).get_unresolved_recharges("aldi_talk", ACCOUNT)[0].status == "PENDING"
    finally:
        release.set()
        child.join(15)
        if child.is_alive():
            child.terminate()
            child.join(5)
    assert child.exitcode == 0
    # Redelivering a BUSY event is safe and it was not lost to deduplication.
    delivered = Engine(db_path, ProviderFixture(), ACCOUNT, dry_run=False).process(other_event)
    assert delivered.status == "NO_ACTION"
    assert EventStore(db_path).get_event(other_event.event_id)["state"] == "COMPLETED"
    assert len(Path(counter).read_text().splitlines()) == 1


@pytest.mark.parametrize("offer", [
    Offer(1000, 1, True), Offer(1000, -1, True), Offer(500, 0, True),
    Offer(1000, 0, False), Offer(1000, False, True), Offer(1000, "0", True),
])
def test_paid_non1gb_or_ambiguous_offer_never_books(tmp_path, offer):
    provider = ProviderFixture(snapshot=Snapshot(True, True, offer))
    result = run(tmp_path, provider)
    assert result.status == "NO_ACTION"
    assert result.error_class == "OFFER_NOT_FREE_1GB"
    assert not provider.bookings


@pytest.mark.parametrize("snapshot", [
    Snapshot(False, True, FREE), Snapshot(True, False, FREE),
    Snapshot(True, True, FREE, pending_booking=True),
])
def test_account_tariff_and_pending_booking_checks(tmp_path, snapshot):
    provider = ProviderFixture(snapshot=snapshot)
    result = run(tmp_path, provider)
    assert result.status == "BLOCKED"
    assert not provider.bookings


def test_same_email_deduplicates_across_new_engine_and_new_event_id(tmp_path):
    first_event = mail("persistent-mail")
    first = run(tmp_path, ProviderFixture(), first_event)
    replay = MailEvent("different-event-id", first_event.mailbox, first_event.mail_id,
                       first_event.received_at, first_event.kind, first_event.account)
    provider = ProviderFixture()
    second = run(tmp_path, provider, replay, recent_success_guard_seconds=0)
    assert first.status == "SUCCESS"
    assert second.status == "DUPLICATE" and second.recharge_id == first.recharge_id
    assert provider.inspections == 0 and not provider.bookings


def test_event_identity_cannot_be_reassigned_or_stale_mail_replayed(tmp_path):
    event = mail(received_at=time.time() - 4000)
    first = run(tmp_path, ProviderFixture(), event)
    assert first.status == "REJECTED" and first.error_class == "STALE_EVENT"
    forged = mail(event.event_id)
    provider = ProviderFixture()
    result = run(tmp_path, provider, forged)
    assert result.status == "REJECTED" and result.error_class == "EVENT_ID_COLLISION"
    assert provider.inspections == 0


def test_account_mismatch_is_rejected(tmp_path):
    event = mail()
    event = MailEvent(event.event_id, event.mailbox, event.mail_id, event.received_at, event.kind, "other")
    provider = ProviderFixture()
    result = run(tmp_path, provider, event)
    assert result.status == "REJECTED" and not provider.bookings


@pytest.mark.parametrize("legacy_provider,legacy_user", [
    ("aldi", "01632321869"), ("ALDITalk", "old-account"),
    ("UNKNOWN", "old-user"), ("aldi_talk", "another-alias"),
])
def test_unmapped_legacy_recharges_block_without_guessing_ownership(tmp_path, legacy_provider, legacy_user):
    database = Database(str(tmp_path / "state.sqlite"))
    database.begin_recharge(legacy_provider, legacy_user)
    provider = ProviderFixture(recovered=Confirmation("FAILED"))
    result = run(tmp_path, provider)
    assert result.status == "BLOCKED"
    assert result.error_class == "legacy_unresolved_requires_account_mapping"
    assert not provider.inspections and not provider.reconciliations and not provider.bookings


def test_crash_after_success_commit_recovers_terminal_event_without_provider_call(tmp_path):
    path = str(tmp_path / "state.sqlite")
    event = mail()
    store = EventStore(path)
    store.claim_event(event)
    recharge_id = store.reserve(event.event_id, "aldi_talk", ACCOUNT, 0)
    store.set_recharge_status(recharge_id, "SUCCESS")
    provider = ProviderFixture()
    result = Engine(path, provider, ACCOUNT, dry_run=False, recent_success_guard_seconds=0).process(event)
    assert result.status == "SUCCESS" and result.action == "RECONCILED"
    assert result.recharge_id == recharge_id
    assert not provider.inspections and not provider.bookings


def test_authoritative_failure_unlocks_only_a_new_event(tmp_path):
    first = run(tmp_path, ProviderFixture(confirmation=TimeoutError()), mail("failed-first"))
    provider = ProviderFixture(recovered=Confirmation("FAILED", error_class="PROVIDER_REJECTED"))
    result = run(tmp_path, provider, mail("second"))
    assert first.status == "UNKNOWN"
    assert result.status == "SUCCESS"
    assert provider.reconciliations == [first.recharge_id]
    assert len(provider.bookings) == 1


def test_invalid_confirmation_is_unknown_and_not_success(tmp_path):
    provider = ProviderFixture(confirmation={"status": "SUCCESS"})
    result = run(tmp_path, provider)
    assert result.status == "UNKNOWN" and result.error_class == "INVALID_CONFIRMATION"


def test_provider_classified_error_is_preserved_but_messages_are_not(tmp_path):
    class NeedsUserAction(RuntimeError):
        error_class = "user_action_required"

    class ProviderWithChallenge(ProviderFixture):
        def inspect(self):
            raise NeedsUserAction("private provider content")

    provider = ProviderWithChallenge()
    result = run(tmp_path, provider)
    assert result.status == "FAILED" and result.error_class == "user_action_required"
    assert not provider.bookings
    assert b"private provider content" not in (tmp_path / "state.sqlite").read_bytes()
