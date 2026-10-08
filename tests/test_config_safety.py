import pytest
from unittest.mock import Mock, patch

from core.config import Config


@pytest.fixture
def config_env(monkeypatch):
    for key in ("DRY_RUN", "AUTO_BOOK_ENABLED", "POLL_INTERVAL_SECONDS",
                "THRESHOLD_ALDI_MB", "THRESHOLD_LIDL_MB", "LIDL_USE_API", "LIDL_REFILL_MODE", "ALDI_PASS_ENC", "LIDL_PASS_ENC"):
        monkeypatch.delenv(key, raising=False)
    with patch("core.config.SecurityManager"), patch("core.config.load_dotenv"):
        yield monkeypatch


@pytest.mark.parametrize("key,value", [("DRY_RUN", "tru"), ("AUTO_BOOK_ENABLED", "yes"),
                                      ("DRY_RUN", ""), ("AUTO_BOOK_ENABLED", "1")])
def test_invalid_flags_cannot_enable_live_mode(config_env, key, value):
    config_env.setenv(key, value)
    with pytest.raises(ValueError, match=key):
        Config()


def test_live_plugins_require_both_flags(config_env):
    config_env.setenv("DRY_RUN", "false")
    with pytest.raises(ValueError, match="AUTO_BOOK_ENABLED"):
        Config()
    config_env.setenv("AUTO_BOOK_ENABLED", "true")
    assert Config().dry_run is False


def test_defaults_are_safe(config_env):
    config = Config()
    assert config.dry_run is True
    assert config.auto_book_enabled is False


@pytest.mark.parametrize("key,value", [("THRESHOLD_ALDI_MB", "nan"),
                                      ("THRESHOLD_LIDL_MB", "-1"),
                                      ("POLL_INTERVAL_SECONDS", "0")])
def test_invalid_operating_values_are_rejected(config_env, key, value):
    config_env.setenv(key, value)
    with pytest.raises(ValueError):
        Config()


def test_decryption_failure_does_not_use_plaintext_fallback(config_env):
    config_env.setenv("ALDI_PASS_ENC", "broken")
    config_env.setenv("ALDI_PASS", "must-not-be-used")
    with patch("core.config.SecurityManager", return_value=Mock(decrypt=Mock(side_effect=ValueError))):
        with pytest.raises(ValueError, match="Cannot decrypt ALDI_PASS_ENC"):
            Config()


def test_lidl_defaults_to_button_availability(config_env):
    config = Config()
    assert config.lidl_use_api is False
    assert config.lidl_refill_mode == 'available'
    config_env.setenv('LIDL_REFILL_MODE', 'typo')
    with pytest.raises(ValueError, match='LIDL_REFILL_MODE'):
        Config()
