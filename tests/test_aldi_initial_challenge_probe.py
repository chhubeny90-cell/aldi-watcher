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


def test_structural_metadata_exposes_only_safe_callback_shape():
    challenge = {
        "callbacks": [
            {
                "type": "ConfirmationCallback",
                "input": [{"name": "IDToken5", "value": 0}],
                "output": [
                    {"name": "options", "value": ["sms-login", "login", "reset"]},
                    {"name": "defaultOption", "value": 1},
                ],
            },
            {
                "type": "HiddenValueCallback",
                "input": [{"name": "IDToken6", "value": ""}],
                "output": [
                    {"name": "id", "value": "context"},
                    {"name": "value", "value": "opaque-provider-state"},
                ],
            },
        ]
    }

    metadata = probe._structural_metadata(challenge)
    assert metadata["confirmation_meta"]["count"] == 1
    assert metadata["confirmation_meta"]["default_index"] == 1
    assert len(metadata["confirmation_meta"]["option_categories"]) == 3
    assert metadata["hidden_meta"] == [{
        "id_present": True,
        "id_length": 7,
        "value_type": "str",
        "value_empty": False,
    }]
    assert "opaque-provider-state" not in str(metadata)
