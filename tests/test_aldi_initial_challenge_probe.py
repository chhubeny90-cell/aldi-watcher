import aldi_initial_challenge_probe as probe


def _confirmation(default, options):
    return {
        "type": "ConfirmationCallback",
        "input": [{"name": "IDToken5", "value": 0}],
        "output": [
            {"name": "options", "value": options},
            {"name": "defaultOption", "value": default},
        ],
    }


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
            _confirmation(1, ["sms-login", "login", "reset"]),
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
    row = metadata["confirmation_meta"]["callbacks"][0]
    assert row["default_index"] == 1
    assert len(row["option_categories"]) == 3
    assert metadata["hidden_meta"] == [{
        "id_present": True,
        "id_length": 7,
        "value_type": "str",
        "value_empty": False,
    }]
    assert "opaque-provider-state" not in str(metadata)


def test_structural_metadata_counts_every_confirmation_callback():
    challenge = {
        "callbacks": [
            _confirmation(1, ["sms-login", "login", "reset"]),
            _confirmation(0, ["continue", "cancel"]),
        ]
    }

    metadata = probe._structural_metadata(challenge)["confirmation_meta"]
    assert metadata["count"] == 2
    assert len(metadata["callbacks"]) == 2
    assert metadata["callbacks"][0]["default_index"] == 1
    assert metadata["callbacks"][1]["default_index"] == 0
