import json

from aldi_auto_refill import (
    MIN_CONFIRM_DELTA_GB,
    load_state,
    refill_confirmed,
    selector_digest,
    selector_plan,
)


def test_refill_confirmation_requires_nearly_one_gb_increase():
    assert refill_confirmed(0.05, 1.05) is True
    assert refill_confirmed(0.20, 1.09) is False
    assert refill_confirmed(0.20, 1.10) is True
    assert refill_confirmed(None, 1.0) is False
    assert refill_confirmed(0.0, True) is False
    assert MIN_CONFIRM_DELTA_GB == 0.90


def test_selector_plan_requires_unique_safe_candidates_for_every_preclick_role():
    probe = {
        'account': {'unique': '[id="account"]'},
        'active_tariff': {'unique': '[data-testid="tariff"]'},
        'refill_offer': {'unique': '[data-qa="refillOffer"]'},
        'refill_button': {'unique': '[name="refill"]'},
    }
    selectors = selector_plan(probe)
    assert selectors == {
        'account': '[id="account"]',
        'active_tariff': '[data-testid="tariff"]',
        'refill_offer': '[data-qa="refillOffer"]',
        'refill_button': '[name="refill"]',
    }
    assert selector_digest(selectors) == selector_digest(dict(reversed(list(selectors.items()))))

    probe['refill_button']['unique'] = None
    assert selector_plan(probe) is None


def test_persistent_unknown_state_loads_and_remains_explicit(tmp_path):
    path = tmp_path / 'state.json'
    path.write_text(json.dumps({
        'version': 1,
        'initialized': True,
        'status': 'UNKNOWN',
        'attempt_id': 'abc',
        'before_remaining_gb': 0.0,
        'selector_digest': 'hash',
        'prepared_at': None,
        'finished_at': None,
        'last_observed_remaining_gb': None,
        'last_reason': 'post_click_outcome_unknown',
    }), encoding='utf-8')
    state = load_state(path)
    assert state['status'] == 'UNKNOWN'
    assert state['attempt_id'] == 'abc'
