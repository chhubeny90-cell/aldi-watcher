"""LITE safety tests using deterministic providers; never contact ALDI."""

import multiprocessing as mp
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.database import Database
from lite import Confirmation, Engine, MailEvent, Offer, Snapshot
from lite.store import AccountBindingError, EventStore, account_lock_path


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


def test_optional_success_guard_inspects_and_retains_mail_for_retry(tmp_path):
    first = run(tmp_path, ProviderFixture(), mail("first"))
    second_provider = ProviderFixture()
    second_event = mail("second")
    second = run(tmp_path, second_provider, second_event, recent_success_guard_seconds=1800)
    assert first.status == "SUCCESS"
    assert (second.status, second.action) == ("BUSY", "RETRY")
    assert second.error_class == "RECENT_SUCCESS"
    assert second_provider.inspections == 1
    assert not second_provider.bookings
    store = EventStore(str(tmp_path / "state.sqlite"))
    assert store.get_event(second_event.event_id)["state"] == "PROCESSING"
    old = (datetime.now(timezone.utc) - timedelta(seconds=1801)).isoformat()
    with sqlite3.connect(tmp_path / "state.sqlite") as db:
        db.execute("UPDATE recharges SET updated_at=? WHERE recharge_id=?", (old, first.recharge_id))
    retried_provider = ProviderFixture()
    retried = run(tmp_path, retried_provider, second_event, recent_success_guard_seconds=1800)
    assert retried.status == "SUCCESS" and len(retried_provider.bookings) == 1
    assert store.get_event(second_event.event_id)["state"] == "COMPLETED"


def test_default_allows_fresh_free_offer_just_after_previous_success(tmp_path):
    first = run(tmp_path, ProviderFixture(), mail("first"))
    provider = ProviderFixture()
    second = run(tmp_path, provider, mail("second"))
    assert first.status == second.status == "SUCCESS"
    assert first.recharge_id != second.recharge_id
    assert provider.inspections == 1 and len(provider.bookings) == 1


def test_recharge_clock_is_utc_and_expired_success_allows_later_refill(tmp_path):
    path = str(tmp_path / "state.sqlite")
    database = Database(path)
    first_id = database.begin_recharge("aldi_talk", ACCOUNT)
    first = database.get_unresolved_recharges("aldi_talk", ACCOUNT)[0]
    assert first.created_at.utcoffset() == timedelta(0)
    assert first.updated_at.utcoffset() == timedelta(0)
    database.set_recharge_status(first_id, "SUCCESS")
    old = (datetime.now(timezone.utc) - timedelta(seconds=1801)).isoformat()
    with sqlite3.connect(path) as db:
        db.execute("UPDATE recharges SET updated_at=? WHERE recharge_id=?", (old, first_id))
    result = run(tmp_path, ProviderFixture(), mail("after-guard"))
    assert result.status == "SUCCESS" and result.recharge_id != first_id
    with sqlite3.connect(path) as db:
        created_at, updated_at = db.execute(
            "SELECT created_at,updated_at FROM recharges WHERE recharge_id=?", (result.recharge_id,)
        ).fetchone()
    assert datetime.fromisoformat(created_at).utcoffset() == timedelta(0)
    assert datetime.fromisoformat(updated_at).utcoffset() == timedelta(0)


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
        recovery_provider = ProviderFixture(recovered=Confirmation("FAILED"))
        recovery = Engine(db_path, recovery_provider, ACCOUNT, dry_run=False).recover_pending()
        assert len(recovery) == 1 and recovery[0].status == "BUSY"
        assert not recovery_provider.reconciliations and not recovery_provider.inspections and not recovery_provider.bookings
    finally:
        release.set()
        child.join(15)
        if child.is_alive():
            child.terminate()
            child.join(5)
    assert child.exitcode == 0
    # Redelivering a BUSY event is safe and it was not lost to deduplication.
    delivered = Engine(db_path, ProviderFixture(snapshot=Snapshot(True, True)), ACCOUNT, dry_run=False).process(other_event)
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
    first = run(tmp_path, ProviderFixture(), event, event_max_age_seconds=3600)
    assert first.status == "REJECTED" and first.error_class == "STALE_EVENT"
    forged = mail(event.event_id)
    provider = ProviderFixture()
    result = run(tmp_path, provider, forged)
    assert result.status == "REJECTED" and result.error_class == "EVENT_ID_COLLISION"
    assert provider.inspections == 0


@pytest.mark.parametrize("snapshot,expected", [
    (Snapshot(True, True, FREE), "SUCCESS"),
    (Snapshot(True, True), "NO_ACTION"),
    (Snapshot(True, True, Offer(1000, 199, True)), "NO_ACTION"),
    (Snapshot(False, True, FREE), "BLOCKED"),
])
def test_delayed_exhaustion_mail_checks_current_provider_and_free_gate(tmp_path, snapshot, expected):
    # A mailbox outage must not discard its only authenticated exhaustion trigger.
    event = mail("delayed-exhaustion", received_at=time.time() - 86400)
    provider = ProviderFixture(snapshot=snapshot)
    result = run(tmp_path, provider, event)
    assert result.status == expected
    assert provider.inspections == 1
    assert len(provider.bookings) == (1 if expected == "SUCCESS" else 0)


def test_explicit_event_age_limit_rejects_delayed_mail_and_future_timestamp(tmp_path):
    delayed = mail("limited-mail", received_at=time.time() - 7200)
    provider = ProviderFixture()
    result = run(tmp_path, provider, delayed, event_max_age_seconds=3600)
    assert result.status == "REJECTED" and result.error_class == "STALE_EVENT"
    assert not provider.inspections and not provider.bookings
    future = mail("future-mail", received_at=time.time() + 600)
    provider = ProviderFixture()
    result = run(tmp_path, provider, future)
    assert result.status == "REJECTED" and result.error_class == "STALE_EVENT"
    assert not provider.inspections and not provider.bookings


@pytest.mark.parametrize("limit", [True, 0, -1, float("inf"), float("nan"), "3600"])
def test_optional_event_age_limit_must_be_finite_positive_number(tmp_path, limit):
    with pytest.raises(ValueError, match="Invalid event age"):
        Engine(tmp_path / "state.sqlite", ProviderFixture(), ACCOUNT, event_max_age_seconds=limit)


def test_account_mismatch_is_rejected(tmp_path):
    event = mail()
    event = MailEvent(event.event_id, event.mailbox, event.mail_id, event.received_at, event.kind, "other")
    provider = ProviderFixture()
    result = run(tmp_path, provider, event)
    assert result.status == "REJECTED" and not provider.bookings


def _alias_race_worker(db_path, account, barrier, results, counter_path):
    event = MailEvent(account, "mailbox-primary", account, time.time(), "exhausted", account)
    barrier.wait(15)
    try:
        provider = DurableCallProvider(counter_path)
        result = Engine(db_path, provider, account, dry_run=False).process(event)
        results.put((account, result.status))
    except AccountBindingError:
        results.put((account, "account_alias_mismatch"))


@pytest.mark.skipif(os.name != "posix", reason="LITE uses the deployment's POSIX flock")
def test_two_aliases_cannot_initialize_or_book_same_database(tmp_path):
    context = mp.get_context("spawn")
    barrier, results = context.Barrier(2), context.Queue()
    path = str(tmp_path / "state.sqlite")
    counter = str(tmp_path / "provider-calls")
    EventStore(path)
    children = [context.Process(target=_alias_race_worker, args=(path, account, barrier, results, counter))
                for account in ("primary", "alternate")]
    for child in children:
        child.start()
    for child in children:
        child.join(15)
        assert child.exitcode == 0
    outcomes = [results.get(timeout=5)[1] for _ in children]
    assert sorted(outcomes) == ["SUCCESS", "account_alias_mismatch"]
    assert len(Path(counter).read_text().splitlines()) == 1
    assert account_lock_path(path, "primary") == account_lock_path(path, "alternate")


@pytest.mark.parametrize("legacy_provider,legacy_account", [("ALDI-TALK", "alternate"), ("UNKNOWN", "old-user")])
def test_reservation_transaction_blocks_legacy_inserted_after_inspection(tmp_path, legacy_provider, legacy_account):
    path = str(tmp_path / "state.sqlite")

    class RacingLegacyProvider(ProviderFixture):
        def inspect(self):
            Database(path).begin_recharge(legacy_provider, legacy_account)
            return super().inspect()

    provider = RacingLegacyProvider()
    result = run(tmp_path, provider)
    assert result.status == "BLOCKED"
    assert result.error_class == "legacy_unresolved_requires_account_mapping"
    assert provider.inspections == 1 and not provider.bookings


@pytest.mark.parametrize("legacy_provider,legacy_user", [
    ("aldi", "01601234567"), ("ALDITalk", "old-account"),
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
    assert result.status == "BLOCKED" and result.error_class == "user_action_required"
    assert not provider.bookings
    assert b"private provider content" not in (tmp_path / "state.sqlite").read_bytes()


class TransientReadProvider(ProviderFixture):
    def __init__(self, error):
        super().__init__()
        self.error = error

    def inspect(self):
        self.inspections += 1
        raise self.error


@pytest.mark.parametrize("error", [TimeoutError("private body"), ConnectionError("private body")])
def test_first_transient_check_redelivers_once_and_then_succeeds(tmp_path, error):
    event = mail("transient-mail")
    first = run(tmp_path, TransientReadProvider(error), event)
    assert (first.status, first.action) == ("BUSY", "RETRY")
    store = EventStore(str(tmp_path / "state.sqlite"))
    assert store.get_event(event.event_id)["state"] == "PROCESSING"
    assert store.get_event(event.event_id)["check_attempts"] == 1
    provider = ProviderFixture()
    second = run(tmp_path, provider, event)
    assert second.status == "SUCCESS" and len(provider.bookings) == 1
    assert store.get_event(event.event_id)["check_attempts"] == 2
    assert b"private body" not in (tmp_path / "state.sqlite").read_bytes()


def test_second_transient_failure_finishes_without_third_provider_attempt(tmp_path):
    event = mail("transient-mail")
    first = run(tmp_path, TransientReadProvider(TimeoutError()), event)
    second = run(tmp_path, TransientReadProvider(ConnectionError()), event)
    provider = ProviderFixture()
    third = run(tmp_path, provider, event)
    assert first.status == "BUSY"
    assert second.status == "FAILED" and second.error_class == "ConnectionError"
    assert third.status == "DUPLICATE"
    assert not provider.inspections and not provider.bookings
    assert EventStore(str(tmp_path / "state.sqlite")).get_event(event.event_id)["check_attempts"] == 2


def test_classified_login_timeout_retries_but_mfa_never_resubmits(tmp_path):
    class LoginNotConfirmed(RuntimeError):
        error_class = "login_not_confirmed"

    login_event = mail("login-mail")
    first = run(tmp_path, TransientReadProvider(LoginNotConfirmed()), login_event)
    assert first.status == "BUSY" and first.error_class == "login_not_confirmed"

    class Challenge(TimeoutError):
        error_class = "user_action_required"

    challenge_event = mail("challenge-mail")
    first = run(tmp_path, TransientReadProvider(Challenge()), challenge_event)
    provider = ProviderFixture()
    replay = run(tmp_path, provider, challenge_event)
    assert (first.status, first.action) == ("BLOCKED", "HUMAN_ACTION_REQUIRED")
    assert replay.status == "DUPLICATE" and not provider.inspections and not provider.bookings


def test_duplicate_unknown_can_reconcile_success_without_new_mail_or_booking(tmp_path):
    event = mail("unknown-mail")
    first = run(tmp_path, ProviderFixture(confirmation=TimeoutError()), event)
    provider = ProviderFixture(recovered=Confirmation("SUCCESS", "independent-proof"))
    replay = run(tmp_path, provider, event)
    assert first.status == "UNKNOWN"
    assert (replay.status, replay.action) == ("SUCCESS", "RECONCILED")
    assert replay.recharge_id == first.recharge_id
    assert provider.reconciliations == [first.recharge_id]
    assert not provider.inspections and not provider.bookings


def test_explicit_recovery_only_reconciles_existing_request(tmp_path):
    event = mail("unknown-mail")
    first = run(tmp_path, ProviderFixture(confirmation=TimeoutError()), event)
    provider = ProviderFixture(recovered=Confirmation("FAILED", error_class="PROVIDER_REJECTED"))
    engine = Engine(tmp_path / "state.sqlite", provider, ACCOUNT, dry_run=False)
    results = engine.recover_pending()
    assert len(results) == 1
    assert results[0].status == "FAILED" and results[0].recharge_id == first.recharge_id
    assert provider.reconciliations == [first.recharge_id]
    assert not provider.inspections and not provider.bookings
    assert engine.store.get_unresolved_recharges("aldi_talk", ACCOUNT) == []
    assert len(engine.store.list_events()) == 1
    with sqlite3.connect(tmp_path / "state.sqlite") as database:
        assert database.execute("SELECT COUNT(*) FROM recharges").fetchone()[0] == 1


def test_event_check_attempts_migration_preserves_existing_journal(tmp_path):
    path = str(tmp_path / "old-state.sqlite")
    with sqlite3.connect(path) as database:
        database.execute("""
            CREATE TABLE lite_events (
                event_id TEXT PRIMARY KEY, mailbox TEXT, mail_id TEXT, received_at REAL,
                kind TEXT, account TEXT, state TEXT, started_at REAL, updated_at REAL,
                status TEXT, action TEXT, recharge_id TEXT, error_class TEXT, booking_id TEXT,
                UNIQUE(mailbox,mail_id)
            )
        """)
        database.execute("""
            INSERT INTO lite_events(event_id,mailbox,mail_id,received_at,kind,account,state,started_at,updated_at,status)
            VALUES ('old-event','mailbox-primary','old-mail',0,'warning80','primary','COMPLETED',0,0,'NO_ACTION')
        """)
    store = EventStore(path)
    assert store.get_event("old-event")["status"] == "NO_ACTION"
    assert store.get_event("old-event")["check_attempts"] == 0
