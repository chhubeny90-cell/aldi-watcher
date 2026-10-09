from monitoring import safe_refill_evidence


def test_aldi_reporting_accepts_only_complete_verified_evidence():
    usage = {
        'refill_eligible': True,
        'refill_type': 'FREE_ONE_GB',
        'refill_reason': 'free_one_gb_offer_available',
        'account_verified': True,
        'reconciliation_status': 'SUCCESS',
        'account_text': 'must-not-leak',
        'offer_text': 'must-not-leak',
    }
    result = safe_refill_evidence('aldi_talk', usage)
    assert result == {
        'refill_eligible': True,
        'refill_type': 'FREE_ONE_GB',
        'refill_reason': 'free_one_gb_offer_available',
        'account_verified': True,
        'reconciliation_status': 'SUCCESS',
    }


def test_aldi_reporting_fails_closed_on_unverified_account():
    usage = {
        'refill_eligible': True,
        'refill_type': 'FREE_ONE_GB',
        'refill_reason': 'free_one_gb_offer_available',
        'account_verified': False,
        'reconciliation_status': 'SUCCESS',
    }
    result = safe_refill_evidence('aldi_talk', usage)
    assert result['refill_eligible'] is False
    assert result['refill_type'] == 'UNKNOWN'
    assert result['account_verified'] is False
    assert result['reconciliation_status'] == 'SUCCESS'


def test_aldi_reporting_rejects_unknown_reason():
    result = safe_refill_evidence('aldi_talk', {
        'refill_eligible': True,
        'refill_type': 'FREE_ONE_GB',
        'refill_reason': 'made_up_success',
        'account_verified': True,
    })
    assert result['refill_eligible'] is False
    assert result['refill_reason'] == 'offer_unverified'
    assert result['account_verified'] is False


def test_aldi_reporting_normalizes_unknown_reconciliation_state():
    result = safe_refill_evidence('aldi_talk', {
        'refill_eligible': False,
        'refill_type': 'UNKNOWN',
        'refill_reason': 'button_disabled',
        'account_verified': True,
        'reconciliation_status': 'PENDING',
    })
    assert result['reconciliation_status'] == 'UNKNOWN'
