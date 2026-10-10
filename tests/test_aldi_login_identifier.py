import watcher


def test_aldi_login_identifier_can_differ_from_account_user(monkeypatch):
    values = {
        'ALDI_LOGIN_USER': 'A-PRIVATE_LOGIN',
        'ALDI_USER': 'PRIVATE_ACCOUNT_NUMBER',
        'ALDI_PASS': 'PRIVATE_PASSWORD',
    }
    monkeypatch.setattr(watcher, 'get_credential', lambda name: values.get(name))

    assert watcher.configure_credentials('ALDI') is True
    assert watcher.ALDI_USER == 'A-PRIVATE_LOGIN'
    assert watcher.ALDI_ACCOUNT_USER == 'PRIVATE_ACCOUNT_NUMBER'
    assert watcher.ALDI_PASS == 'PRIVATE_PASSWORD'


def test_aldi_account_user_remains_backwards_compatible_login_fallback(monkeypatch):
    values = {
        'ALDI_LOGIN_USER': None,
        'ALDI_USER': 'PRIVATE_ACCOUNT_NUMBER',
        'ALDI_PASS': 'PRIVATE_PASSWORD',
    }
    monkeypatch.setattr(watcher, 'get_credential', lambda name: values.get(name))

    assert watcher.configure_credentials('ALDI') is True
    assert watcher.ALDI_USER == 'PRIVATE_ACCOUNT_NUMBER'
    assert watcher.ALDI_ACCOUNT_USER == 'PRIVATE_ACCOUNT_NUMBER'
