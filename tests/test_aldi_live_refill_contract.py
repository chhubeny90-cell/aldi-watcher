import pytest

import aldi_live_refill_contract as contract


def test_main_resets_state_and_restores_process_global_hooks(monkeypatch):
    original_click = contract.live._trusted_click
    original_bound = contract.live._bound_status
    original_set = contract.live.Database.set_recharge_status
    original_limit = contract.live.MAX_REFILLS_PER_RUN

    contract._STATE.update({
        "pre_binding": ("stale", "stale"),
        "post_binding": ("stale", "stale"),
        "exchange": object(),
        "clicks": 9,
        "contract": object(),
    })

    observed = {}

    def fake_live_main():
        observed["limit"] = contract.live.MAX_REFILLS_PER_RUN
        observed["state"] = dict(contract._STATE)
        assert contract.live._trusted_click is not original_click
        assert contract.live._bound_status is not original_bound
        assert contract.live.Database.set_recharge_status is not original_set
        return 0

    monkeypatch.setattr(contract.live, "main", fake_live_main)

    assert contract.main() == 0
    assert observed["limit"] == 1
    assert observed["state"] == {
        "pre_binding": None,
        "post_binding": None,
        "exchange": None,
        "clicks": 0,
        "contract": None,
    }
    assert contract.live._trusted_click is original_click
    assert contract.live._bound_status is original_bound
    assert contract.live.Database.set_recharge_status is original_set
    assert contract.live.MAX_REFILLS_PER_RUN == original_limit


def test_main_restores_hooks_and_limit_when_runner_raises(monkeypatch):
    original_click = contract.live._trusted_click
    original_bound = contract.live._bound_status
    original_set = contract.live.Database.set_recharge_status
    original_limit = contract.live.MAX_REFILLS_PER_RUN

    def explode():
        raise RuntimeError("simulated")

    monkeypatch.setattr(contract.live, "main", explode)

    with pytest.raises(RuntimeError, match="simulated"):
        contract.main()

    assert contract.live._trusted_click is original_click
    assert contract.live._bound_status is original_bound
    assert contract.live.Database.set_recharge_status is original_set
    assert contract.live.MAX_REFILLS_PER_RUN == original_limit
