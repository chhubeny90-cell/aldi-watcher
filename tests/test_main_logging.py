"""Runner diagnostics must not disclose credentials or hide uncertain bookings."""

import asyncio
from types import SimpleNamespace

import pytest

from core.database import Database, RechargeLockedError
from main import AlDiWatcher, REDACTED_ACCOUNT
from plugins.base_watcher import BaseWatcher, WatcherResult


PRIVATE_ACCOUNT = "private-account-fixture"
PRIVATE_DETAIL = "private-password-fixture private-cookie-fixture"


@pytest.fixture
def runner(tmp_path):
    obj = AlDiWatcher.__new__(AlDiWatcher)
    obj.config = SimpleNamespace(threshold_aldi_mb=500, threshold_lidl_mb=500)
    obj.db = Database(str(tmp_path / "logs.sqlite"))
    obj.watchers = []
    return obj


def result(**kwargs):
    values = dict(
        provider="alditalk", username=PRIVATE_ACCOUNT, success=True,
        data_used_mb=600, data_total_mb=1000,
        should_recharge=True, recharge_triggered=False,
        error_message=PRIVATE_DETAIL,
    )
    values.update(kwargs)
    return WatcherResult(**values)


@pytest.mark.parametrize("booking_status", ["PENDING", "UNKNOWN", "BLOCKED", "FAILED"])
def test_uncertain_or_failed_booking_is_visible_and_persisted_safely(
    runner, capsys, booking_status
):
    recharge_id = runner.db.begin_recharge("alditalk", PRIVATE_ACCOUNT)
    asyncio.run(runner._process_watcher_result(result(
        recharge_id=recharge_id, recharge_status=booking_status
    )))

    output = capsys.readouterr().out
    assert "[WARN]" in output
    assert "[OK]" not in output
    assert f"Recharge status: {booking_status}" in output
    assert f"Recharge ID: {recharge_id}" in output
    assert PRIVATE_ACCOUNT not in output
    assert PRIVATE_DETAIL not in output
    log = runner.db.get_recent_logs()[0]
    assert log.username == REDACTED_ACCOUNT
    assert log.error_message == f"RECHARGE_{booking_status}"

    # Usage-log redaction must not alter the journal's account-specific lock.
    assert runner.db.get_unresolved_recharges("alditalk", PRIVATE_ACCOUNT)
    with pytest.raises(RechargeLockedError):
        runner.db.begin_recharge("alditalk", PRIVATE_ACCOUNT)


def test_provider_error_and_non_journal_id_are_not_disclosed(runner, capsys):
    asyncio.run(runner._process_watcher_result(result(
        success=False, recharge_id=PRIVATE_DETAIL
    )))
    output = capsys.readouterr().out
    assert "[ERROR]" in output
    assert "Recharge ID: unavailable" in output
    assert PRIVATE_ACCOUNT not in output
    assert PRIVATE_DETAIL not in output
    log = runner.db.get_recent_logs()[0]
    assert log.username == REDACTED_ACCOUNT
    assert log.error_message == "PROVIDER_ERROR"


def test_watcher_crash_details_are_not_printed_or_persisted(runner, capsys):
    class CrashingWatcher:
        username = PRIVATE_ACCOUNT

        async def run(self):
            raise RuntimeError(PRIVATE_DETAIL)

    runner.watchers = [CrashingWatcher()]
    asyncio.run(runner.run_once())
    output = capsys.readouterr().out
    assert "RuntimeError" in output
    assert PRIVATE_ACCOUNT not in output
    assert PRIVATE_DETAIL not in output
    log = runner.db.get_recent_logs()[0]
    assert log.username == REDACTED_ACCOUNT
    assert log.error_message == "Watcher crashed: CrashingWatcher: RuntimeError"


def test_shutdown_does_not_print_exception_details(runner, capsys):
    class ClosingWatcher:
        async def close(self):
            raise RuntimeError(PRIVATE_DETAIL)

    runner.watchers = [ClosingWatcher()]
    asyncio.run(runner.shutdown())
    output = capsys.readouterr().out
    assert "RuntimeError" in output
    assert PRIVATE_DETAIL not in output


def test_dry_run_does_not_disclose_account_or_book(capsys):
    class DryRunWatcher(BaseWatcher):
        async def check_usage(self):
            return {"used_mb": 600, "total_mb": 1000}

        async def trigger_recharge(self, recharge_id=None):
            pytest.fail("dry run must never book")

    watcher = DryRunWatcher(PRIVATE_ACCOUNT, PRIVATE_DETAIL, 500, dry_run=True)
    outcome = asyncio.run(watcher.run())
    output = capsys.readouterr().out
    assert "DRY RUN" in output
    assert PRIVATE_ACCOUNT not in output
    assert PRIVATE_DETAIL not in output
    assert outcome.recharge_triggered is False
    assert outcome.recharge_status == "NOT_TRIGGERED"
