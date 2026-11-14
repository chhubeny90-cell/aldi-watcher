"""Offline-only journal tests: never import or contact a mobile provider."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import os

import pytest

from refill_v2.db import StateStore
from refill_v2.models import Blocked, CompletionProof, OfferProof, Provider, RefillStatus


def _store(tmp_path):
    path = tmp_path / "private" / "journal.sqlite"
    store = StateStore(path)
    store.register_account("aldi_primary", Provider.ALDI)
    store.record_observation("aldi_primary", Decimal("0.5"))
    return store


def _offer(account="aldi_primary"):
    return OfferProof(account, exact_one_gb=True, explicit_zero_price=True,
                      session_account_verified=True, provider_permission_verified=True)


def _receipt(operation_id, account="aldi_primary"):
    return CompletionProof(
        operation_id=operation_id, account_id=account,
        receipt_identifier="official-provider-receipt-001",
        bound_to_operation=True, exact_one_gb=True, explicit_zero_price=True,
        official_provider_confirmation=True,
    )


def test_under_one_gb_reserves_once_and_blocks_restarts(tmp_path):
    store = _store(tmp_path)
    op = store.reserve_refill("aldi_primary", _offer())
    restarted = StateStore(store.path)
    with pytest.raises(Blocked, match="unresolved"):
        restarted.reserve_refill("aldi_primary", _offer())
    restarted.mark_unknown(op)
    with pytest.raises(Blocked, match="unresolved"):
        store.reserve_refill("aldi_primary", _offer())
    assert store.history("aldi_primary")[0].status == RefillStatus.UNKNOWN


def test_concurrent_workers_cannot_duplicate_booking(tmp_path):
    store = _store(tmp_path)

    def reserve():
        try:
            return store.reserve_refill("aldi_primary", _offer())
        except Blocked:
            return None

    with ThreadPoolExecutor(max_workers=8) as executor:
        ids = list(executor.map(lambda _: reserve(), range(8)))
    assert len([x for x in ids if x]) == 1
    assert len(store.history("aldi_primary")) == 1


@pytest.mark.parametrize("remaining", ["1", "1.01", "7"])
def test_one_gb_or_more_is_never_eligible(tmp_path, remaining):
    store = _store(tmp_path)
    store.record_observation("aldi_primary", Decimal(remaining))
    with pytest.raises(Blocked, match="not below"):
        store.reserve_refill("aldi_primary", _offer())


def test_stale_observation_blocked(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(Blocked, match="stale"):
        store.record_observation("aldi_primary", Decimal("0.1"),
                                 at=datetime.now(timezone.utc) - timedelta(minutes=9))


@pytest.mark.parametrize("field", [
    "exact_one_gb", "explicit_zero_price", "session_account_verified",
    "provider_permission_verified",
])
def test_offer_missing_one_proof_blocks(tmp_path, field):
    store = _store(tmp_path)
    data = vars(_offer()).copy()
    data[field] = False
    with pytest.raises(Blocked):
        store.reserve_refill("aldi_primary", OfferProof(**data))


def test_stale_snapshot_blocks_while_database_keeps_pending(tmp_path):
    store = _store(tmp_path)
    earlier = datetime.now(timezone.utc) - timedelta(minutes=5)
    store.record_observation("aldi_primary", Decimal("0.4"),
                             at=datetime.now(timezone.utc))
    with pytest.raises(Blocked, match="stale"):
        store.reserve_refill("aldi_primary", _offer(), at=earlier)


def test_success_requires_official_receipt_and_sets_cooldown(tmp_path):
    store = _store(tmp_path)
    op = store.reserve_refill("aldi_primary", _offer())
    missing = CompletionProof(operation_id=op, account_id="aldi_primary",
                              receipt_identifier="no-valid-evidence")
    with pytest.raises(Blocked):
        store.reconcile_success(missing)
    store.mark_unknown(op)
    store.reconcile_success(_receipt(op))
    state = store.snapshot("aldi_primary")
    assert state.last_refill_at and state.cooldown_until
    assert store.history("aldi_primary")[0].status == RefillStatus.SUCCESS
    assert "official-provider" not in str(store.history("aldi_primary"))
    store.mark_unknown(op)  # late timeout cannot undo success
    assert store.history("aldi_primary")[0].status == RefillStatus.SUCCESS
    with pytest.raises(Blocked, match="cooldown"):
        store.reserve_refill("aldi_primary", _offer())


def test_multi_account_isolated_and_no_raw_telephone_aliases(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(ValueError):
        store.register_account("01500000000", Provider.ALDI)
    store.register_account("lidl_secondary", Provider.LIDL)
    store.record_observation("lidl_secondary", Decimal("0.2"))
    op1 = store.reserve_refill("aldi_primary", _offer())
    op2 = store.reserve_refill("lidl_secondary", _offer("lidl_secondary"))
    assert op1 != op2
    assert store.snapshot("lidl_secondary").provider is Provider.LIDL


def test_log_is_only_sanitized_error_code(tmp_path):
    store = _store(tmp_path)
    store.log_error("aldi_primary", "timeout")
    with pytest.raises(ValueError):
        store.log_error("aldi_primary", "Password=secret and +491234")
    with pytest.raises(ValueError):
        store.log_error("aldi_primary", "traceback\\nfile.py")


def test_db_private_file_permissions(tmp_path):
    store = _store(tmp_path)
    if os.name == "posix":
        assert store.path.stat().st_mode & 0o077 == 0
    assert not (tmp_path / "private" / "journal.sqlite").is_symlink()


def test_no_duplicate_provider_or_invalid_volume(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(ValueError, match="provider mismatch"):
        store.register_account("aldi_primary", Provider.LIDL)
    for value in (Decimal("NaN"), Decimal("-1"), Decimal("Infinity")):
        with pytest.raises(ValueError):
            store.record_observation("aldi_primary", value)
