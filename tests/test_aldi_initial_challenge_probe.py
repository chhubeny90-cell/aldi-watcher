import aldi_initial_challenge_probe as probe


def test_challenge_flags_detect_pow_and_lock_key():
    shape = {
        "sanitized_text_outputs": [
            "function startProofOfWork(uuid, difficulty, onProofOfWorkSuccess) {}",
            "custom.alditalk.common.error$custom.alditalk.accountLock.accountLockMsg",
        ]
    }
    assert probe._challenge_flags(shape) == {
        "proof_of_work_present": True,
        "account_lock_key_present": True,
        "custom_error_key_present": True,
    }


def test_challenge_flags_stay_false_for_plain_login_challenge():
    shape = {"sanitized_text_outputs": ["Bitte anmelden"]}
    assert probe._challenge_flags(shape) == {
        "proof_of_work_present": False,
        "account_lock_key_present": False,
        "custom_error_key_present": False,
    }
