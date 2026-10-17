"""Provider-contract entrypoint for one guarded ALDI TALK refill.

This adapts the existing hardened live runner without weakening its fail-closed
journal semantics. It observes the real portal's updateUnlimited exchange after
the already-authorized UI click, evaluates the provider response, persists the
provider binding in the private SQLite journal and only upgrades UNKNOWN to
SUCCESS when all completion gates are satisfied.

Until this path has one controlled real-world acceptance run, it hard-limits the
process to one refill attempt per execution.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

import aldi_live_refill as live
from core.aldi_completion import evaluate_completion
from core.aldi_provider_exchange import clear_performance_log, observe_update_unlimited_exchange


_STATE = {
    "pre_binding": None,
    "post_binding": None,
    "exchange": None,
    "clicks": 0,
    "contract": None,
}


def _reset_state():
    """Never let evidence from a previous in-process invocation leak forward."""
    _STATE.update({
        "pre_binding": None,
        "post_binding": None,
        "exchange": None,
        "clicks": 0,
        "contract": None,
    })


def _utcnow():
    return datetime.now(timezone.utc).isoformat()


def _persist_provider_evidence(db, recharge_id, contract):
    """Store identifiers only in the private local journal, never in reports."""
    if not contract.provider_operation_id or not contract.provider_resource_id:
        return
    with sqlite3.connect(db.db_path, timeout=db.timeout) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS recharge_provider_evidence (
                recharge_id TEXT PRIMARY KEY,
                provider_operation_id TEXT NOT NULL,
                provider_resource_id TEXT NOT NULL,
                provider_status TEXT,
                http_status INTEGER,
                observed_at TEXT NOT NULL,
                FOREIGN KEY(recharge_id) REFERENCES recharges(recharge_id)
            )
        """)
        conn.execute("""
            INSERT INTO recharge_provider_evidence
            (recharge_id, provider_operation_id, provider_resource_id,
             provider_status, http_status, observed_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(recharge_id) DO UPDATE SET
                provider_operation_id = excluded.provider_operation_id,
                provider_resource_id = excluded.provider_resource_id,
                provider_status = excluded.provider_status,
                http_status = excluded.http_status,
                observed_at = excluded.observed_at
        """, (
            recharge_id,
            contract.provider_operation_id,
            contract.provider_resource_id,
            contract.provider_status,
            contract.http_status,
            _utcnow(),
        ))


def _install_hooks():
    """Install temporary observation hooks and return everything needed to restore them."""
    original_click = live._trusted_click
    original_bound_status = live._bound_status
    original_set_status = live.Database.set_recharge_status

    def bound_status(driver, account):
        remaining, binding = original_bound_status(driver, account)
        if _STATE["clicks"] == 0 and _STATE["pre_binding"] is None:
            _STATE["pre_binding"] = binding
        elif _STATE["clicks"] > 0:
            _STATE["post_binding"] = binding
        return remaining, binding

    def trusted_click(driver, control):
        # Clear only cached performance entries. No provider request is emitted.
        clear_performance_log(driver)
        original_click(driver, control)
        _STATE["clicks"] += 1
        exchange = observe_update_unlimited_exchange(driver, timeout=8.0)
        if exchange is not None:
            _STATE["exchange"] = exchange

    def set_recharge_status(db, recharge_id, status, error_message=None):
        if status != "UNKNOWN":
            return original_set_status(db, recharge_id, status, error_message)

        exchange = _STATE.get("exchange")
        pre_binding = _STATE.get("pre_binding")
        post_binding = _STATE.get("post_binding")
        if exchange is None or pre_binding is None or post_binding is None:
            return original_set_status(db, recharge_id, "UNKNOWN", error_message)

        contract = evaluate_completion(
            request_payload=exchange.request_payload,
            response_payload=exchange.response_payload,
            http_status=exchange.http_status,
            account_binding_verified=(post_binding == pre_binding),
            request_was_update_unlimited=exchange.request_was_update_unlimited,
        )
        _STATE["contract"] = contract
        if contract.provider_operation_bound and contract.provider_resource_id:
            _persist_provider_evidence(db, recharge_id, contract)
        if contract.success:
            return original_set_status(db, recharge_id, "SUCCESS", None)
        return original_set_status(db, recharge_id, "UNKNOWN", error_message)

    live._bound_status = bound_status
    live._trusted_click = trusted_click
    live.Database.set_recharge_status = set_recharge_status
    return original_click, original_bound_status, original_set_status


def _restore_hooks(originals):
    """Restore process-global hooks even when the live runner raises."""
    original_click, original_bound_status, original_set_status = originals
    live._trusted_click = original_click
    live._bound_status = original_bound_status
    live.Database.set_recharge_status = original_set_status


def main():
    # Controlled rollout: one provider-changing operation maximum per process.
    _reset_state()
    original_limit = live.MAX_REFILLS_PER_RUN
    live.MAX_REFILLS_PER_RUN = 1
    originals = _install_hooks()
    try:
        code = live.main()
        contract = _STATE.get("contract")
        summary = {
            "completion_contract_observed": contract is not None,
            "completion_result": contract.result if contract is not None else "UNKNOWN",
            "completion_evidence": contract.sanitized() if contract is not None else None,
        }
        print(json.dumps(summary, ensure_ascii=False), flush=True)
        return code
    finally:
        _restore_hooks(originals)
        live.MAX_REFILLS_PER_RUN = original_limit


if __name__ == "__main__":
    raise SystemExit(main())
