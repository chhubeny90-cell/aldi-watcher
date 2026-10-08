"""A one-shot mail handler. No provider polling, no persistent browser loop."""

import fcntl
import math
import os
import re
import time
from pathlib import Path

from core.database import RechargeLockedError
from .models import Confirmation, MailEvent, ProcessResult
from .store import EventCollisionError, EventStore, account_lock_path


_ALIAS = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}\Z")
_ERROR = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}\Z")


def _error_class(value, fallback="PROVIDER_ERROR"):
    # Exception messages and arbitrary provider strings can contain credentials.
    return value if isinstance(value, str) and _ERROR.fullmatch(value) else fallback


def _exception_class(exc):
    # Providers may expose a classified code explicitly, never arbitrary messages.
    return _error_class(getattr(exc, "error_class", None), _error_class(type(exc).__name__))


def _transient_check_failure(exc, code):
    return (code == "login_not_confirmed"
            or isinstance(exc, (TimeoutError, ConnectionError))
            or type(exc).__name__ in {"TimeoutException", "TimeoutError", "ConnectionError"})


def _confirmation(value):
    if not isinstance(value, Confirmation) or value.status not in {"SUCCESS", "FAILED", "UNKNOWN"}:
        return Confirmation("UNKNOWN", error_class="INVALID_CONFIRMATION")
    booking_id = value.booking_id
    if booking_id is not None and (not isinstance(booking_id, str) or len(booking_id) > 256):
        booking_id = None
    return Confirmation(value.status, booking_id, _error_class(value.error_class) if value.error_class else None)


class Engine:
    PROVIDER = "aldi_talk"

    def __init__(self, database_path, provider, account, dry_run=True,
                 recent_success_guard_seconds=0, event_max_age_seconds=None):
        if not isinstance(account, str) or not _ALIAS.fullmatch(account):
            raise ValueError("account must be a logical alias, not credentials or a phone number")
        if type(dry_run) is not bool:
            raise ValueError("dry_run must be an explicit boolean")
        if (not math.isfinite(recent_success_guard_seconds) or recent_success_guard_seconds < 0
                or (event_max_age_seconds is not None and (
                    type(event_max_age_seconds) not in (int, float)
                    or not math.isfinite(event_max_age_seconds) or event_max_age_seconds <= 0))):
            raise ValueError("Invalid event age or recent-success guard")
        path = Path(database_path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.store = EventStore(str(path))
        self.store.bind_account(account)
        self.provider = provider
        self.account = account
        self.dry_run = dry_run
        self.guard_seconds = recent_success_guard_seconds
        self.event_max_age_seconds = event_max_age_seconds
        self.lock_path = account_lock_path(path, account)

    def _recover(self):
        """Only authoritative provider evidence may resolve a previous request."""
        results = []
        for record in self.store.get_unresolved_recharges(self.PROVIDER, self.account):
            linked = self.store.event_for_recharge(record.recharge_id)
            if linked:
                self.store.progress(linked["event_id"], "RECOVERY_STARTED")
            try:
                confirmation = _confirmation(self.provider.reconcile(record))
            except Exception as exc:
                confirmation = Confirmation("UNKNOWN", error_class=_exception_class(exc))
            status = self.store.apply_confirmation(record.recharge_id, confirmation)
            result = ProcessResult(status, "RECONCILED", record.recharge_id, confirmation.error_class)
            results.append(result)
            if linked:
                self.store.finish(linked["event_id"], result, confirmation.booking_id)
        return results

    def recover_pending(self):
        """Provider reconciliation only, including when no new mail arrives."""
        lock = None
        try:
            lock = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o600)
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return [ProcessResult("BUSY", "RETRY", error_class="ACCOUNT_BUSY")]
            if self.store.has_unmapped_aldi_recharge(self.PROVIDER, self.account):
                return [ProcessResult("BLOCKED", "PROVIDER_CHECK_REQUIRED",
                                      error_class="legacy_unresolved_requires_account_mapping")]
            return self._recover()
        except Exception as exc:
            return [ProcessResult("FAILED", "PROVIDER_CHECK_REQUIRED", error_class=_exception_class(exc))]
        finally:
            try:
                self.provider.close()
            except Exception:
                pass
            if lock is not None:
                os.close(lock)

    def process(self, event: MailEvent) -> ProcessResult:
        lock = None
        claimed_id = None
        recharge_id = None
        try:
            if (not isinstance(event, MailEvent) or event.account != self.account
                    or event.kind not in {"warning80", "exhausted"}
                    or not all(isinstance(value, str) and 0 < len(value) <= 512
                               for value in (event.event_id, event.mailbox, event.mail_id))
                    or isinstance(event.received_at, bool)
                    or not isinstance(event.received_at, (int, float))
                    or not math.isfinite(event.received_at)):
                return ProcessResult("REJECTED", "IGNORE", error_class="INVALID_EVENT")
            lock = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o600)
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                # Do not deduplicate/acknowledge this event: its owner must redeliver it.
                return ProcessResult("BUSY", "RETRY", error_class="ACCOUNT_BUSY")
            row, completed = self.store.claim_event(event)
            claimed_id = row["event_id"]
            if completed:
                if row["status"] == "UNKNOWN" and row["recharge_id"]:
                    if self.store.has_unmapped_aldi_recharge(self.PROVIDER, self.account):
                        return ProcessResult("BLOCKED", "PROVIDER_CHECK_REQUIRED", row["recharge_id"],
                                             "legacy_unresolved_requires_account_mapping")
                    self._recover()
                    refreshed = self.store.get_event(claimed_id)
                    committed = self.store.recharge_status(row["recharge_id"])
                    status = committed["status"] if committed else refreshed["status"]
                    return ProcessResult(status, "RECONCILED", row["recharge_id"], refreshed["error_class"])
                return ProcessResult("DUPLICATE", "IGNORE", row["recharge_id"])

            if self.store.has_unmapped_aldi_recharge(self.PROVIDER, self.account):
                return self.store.finish(claimed_id, ProcessResult(
                    "BLOCKED", "PROVIDER_CHECK_REQUIRED",
                    error_class="legacy_unresolved_requires_account_mapping"))

            self._recover()
            unresolved = self.store.get_unresolved_recharges(self.PROVIDER, self.account)
            row = self.store.get_event(claimed_id)
            if row["state"] == "COMPLETED":
                return ProcessResult(row["status"], row["action"], row["recharge_id"], row["error_class"])
            if row["recharge_id"]:
                # A crash can occur after committing SUCCESS/FAILED but before
                # finishing its event. Never reserve again for that same mail.
                committed = self.store.recharge_status(row["recharge_id"])
                if committed and committed["status"] in {"SUCCESS", "FAILED"}:
                    return self.store.finish(claimed_id, ProcessResult(
                        committed["status"], "RECONCILED", row["recharge_id"],
                        _error_class(committed["error_message"]) if committed["error_message"] else None))
            if unresolved:
                return self.store.finish(claimed_id, ProcessResult(
                    "BLOCKED", "PROVIDER_CHECK_REQUIRED", unresolved[0].recharge_id, "UNRESOLVED_RECHARGE"))

            age = time.time() - event.received_at
            if ((self.event_max_age_seconds is not None and age > self.event_max_age_seconds)
                    or age < -300):
                return self.store.finish(claimed_id, ProcessResult("REJECTED", "IGNORE", error_class="STALE_EVENT"))
            self.store.start_check(claimed_id)
            try:
                snapshot = self.provider.inspect()
            except Exception as exc:
                code = _exception_class(exc)
                if code == "user_action_required":
                    return self.store.finish(claimed_id, ProcessResult(
                        "BLOCKED", "HUMAN_ACTION_REQUIRED", error_class=code))
                if _transient_check_failure(exc, code) and not self.store.has_check_retry(claimed_id):
                    return self.store.defer(claimed_id, code, "TRANSIENT_CHECK_RETRY")
                return self.store.finish(claimed_id, ProcessResult("FAILED", "CHECK", error_class=code))
            self.store.progress(claimed_id, "PROVIDER_CHECK_COMPLETED")
            if snapshot.account_verified is not True or snapshot.tariff_verified is not True:
                return self.store.finish(claimed_id, ProcessResult("BLOCKED", "IGNORE", error_class="ACCOUNT_OR_TARIFF_UNVERIFIED"))
            if snapshot.pending_booking is not False:
                return self.store.finish(claimed_id, ProcessResult("BLOCKED", "IGNORE", error_class="PROVIDER_BOOKING_PENDING"))
            offer = snapshot.offer
            if offer is None:
                return self.store.finish(claimed_id, ProcessResult("NO_ACTION", "CHECK"))
            # ALDI advertises decimal GB (1 GB = 1000 MB). Booleans are not prices.
            if (type(offer.data_mb) is not int or offer.data_mb != 1000
                    or type(offer.price_cents) is not int or offer.price_cents != 0
                    or offer.free_unlimited is not True):
                return self.store.finish(claimed_id, ProcessResult("NO_ACTION", "IGNORE", error_class="OFFER_NOT_FREE_1GB"))
            if self.store.has_recent_success(self.PROVIDER, self.account, self.guard_seconds):
                return self.store.defer(claimed_id, "RECENT_SUCCESS")
            if self.dry_run:
                return self.store.finish(claimed_id, ProcessResult("DRY_RUN", "WOULD_REFILL"))

            recharge_id = self.store.reserve(claimed_id, self.PROVIDER, self.account, self.guard_seconds)
            try:
                confirmation = _confirmation(self.provider.book(recharge_id, offer))
            except Exception as exc:
                confirmation = Confirmation("UNKNOWN", error_class=_exception_class(exc))
            status = self.store.apply_confirmation(recharge_id, confirmation)
            return self.store.finish(claimed_id, ProcessResult(
                status, "REFILL", recharge_id, confirmation.error_class), confirmation.booking_id)
        except EventCollisionError:
            return ProcessResult("REJECTED", "IGNORE", error_class="EVENT_ID_COLLISION")
        except RechargeLockedError as exc:
            code = _exception_class(exc)
            if code == "RECENT_SUCCESS" and claimed_id:
                return self.store.defer(claimed_id, code)
            result = ProcessResult("BLOCKED", "IGNORE", recharge_id, code)
            return self.store.finish(claimed_id, result) if claimed_id else result
        except Exception as exc:
            error = _exception_class(exc)
            if recharge_id:
                self.store.set_recharge_status(recharge_id, "UNKNOWN", error)
            result = ProcessResult("UNKNOWN" if recharge_id else "FAILED", "PROVIDER_CHECK_REQUIRED" if recharge_id else "CHECK", recharge_id, error)
            return self.store.finish(claimed_id, result) if claimed_id else result
        finally:
            try:
                self.provider.close()
            except Exception:
                pass
            if lock is not None:
                os.close(lock)
