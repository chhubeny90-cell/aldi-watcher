import pytest
import portal_probe as probe


def test_probe_refuses_provider_credentials(monkeypatch):
    monkeypatch.setenv('ALDI_PASS', 'private')
    monkeypatch.setattr(probe, 'build_driver', lambda: pytest.fail('browser must not start'))
    with pytest.raises(RuntimeError, match='without provider credentials'):
        probe.main()


def test_console_classification_never_returns_raw_error():
    message = 'TypeError: PRIVATE password at https://example.invalid/?token=PRIVATE'
    assert probe.error_categories(message) == ['type_error']


def test_host_discards_credentials_path_query_and_fragment():
    assert probe.host('https://secret:password@example.invalid/account?token=PRIVATE#PRIVATE') == 'example.invalid'
