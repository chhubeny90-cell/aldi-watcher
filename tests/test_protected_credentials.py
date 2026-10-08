import json
import os
from pathlib import Path
from unittest.mock import Mock

import pytest
from cryptography.fernet import Fernet
from core.config import Config
from core.credentials import get_credential, CREDENTIAL_NAMES
from core.protect_config import protect
from core.security import SecurityManager
import monitoring
import watcher
from core.database import Database


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for name in CREDENTIAL_NAMES:
        for suffix in ('', '_ENC', '_FILE'):
            monkeypatch.delenv(name + suffix, raising=False)
    for name in ('CREDENTIAL_ENCRYPTION_KEY', 'CREDENTIAL_KEY_FILE', 'CREDENTIAL_ENV_FILE',
                 'DRY_RUN', 'AUTO_BOOK_ENABLED'):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def encrypted_setup(tmp_path, isolated):
    source, key = tmp_path / '.env', tmp_path / 'private/key'
    source.write_text('ALDI_USER=PRIVATE_NUMBER\nALDI_PASS=PRIVATE_PASSWORD\nDRY_RUN=true\n')
    assert protect(source, source, key) == 2
    isolated.setenv('CREDENTIAL_KEY_FILE', str(key))
    return source, key


def test_encryption_preserves_values_settings_and_key_permissions(isolated, tmp_path):
    source, key = encrypted_setup(tmp_path, isolated)
    assert 'PRIVATE_NUMBER' not in source.read_text()
    assert 'PRIVATE_PASSWORD' not in source.read_text()
    assert 'DRY_RUN=true' in source.read_text()
    assert get_credential('ALDI_USER') == 'PRIVATE_NUMBER'
    assert get_credential('ALDI_PASS') == 'PRIVATE_PASSWORD'
    if os.name == 'posix':
        assert key.stat().st_mode & 0o777 == 0o600
    old_key, old_config = key.read_bytes(), source.read_bytes()
    assert protect(source, source, key) == 2
    assert (key.read_bytes(), source.read_bytes()) == (old_key, old_config)


def test_config_and_selenium_load_same_encrypted_values(isolated, tmp_path):
    encrypted_setup(tmp_path, isolated)
    config = Config()
    assert config.aldi_user == 'PRIVATE_NUMBER'
    assert config.aldi_pass == 'PRIVATE_PASSWORD'
    assert watcher.configure_credentials('ALDI') is True
    assert watcher.ALDI_USER == config.aldi_user
    assert watcher.ALDI_PASS == config.aldi_pass
    assert 'ALDI_USER_ENC' not in os.environ


def test_runtime_secrets_override_encrypted_fallback_even_on_repeated_config(isolated, tmp_path):
    encrypted_setup(tmp_path, isolated)
    isolated.setenv('ALDI_USER', 'RUNTIME_NUMBER')
    isolated.setenv('ALDI_PASS', 'RUNTIME_PASSWORD')
    for _ in range(2):
        assert Config().aldi_user == get_credential('ALDI_USER') == 'RUNTIME_NUMBER'
    assert 'ALDI_USER_ENC' not in os.environ


def test_empty_runtime_secret_uses_ciphertext(isolated, tmp_path):
    encrypted_setup(tmp_path, isolated)
    isolated.setenv('ALDI_USER', '')
    assert get_credential('ALDI_USER') == 'PRIVATE_NUMBER'


@pytest.mark.parametrize('failure', ['missing', 'wrong', 'invalid'])
def test_decryption_failure_never_creates_or_replaces_key(isolated, tmp_path, failure):
    source, key = encrypted_setup(tmp_path, isolated)
    before = key.read_bytes()
    if failure == 'missing':
        key.unlink()
    else:
        isolated.setenv('CREDENTIAL_ENCRYPTION_KEY',
                        Fernet.generate_key().decode() if failure == 'wrong' else 'invalid')
    with pytest.raises(ValueError, match='Cannot decrypt ALDI_USER_ENC'):
        get_credential('ALDI_USER')
    assert key.read_bytes() == before if key.exists() else failure == 'missing'


def test_bad_ciphertext_does_not_fall_back_to_plaintext(isolated):
    isolated.setenv('ALDI_USER_ENC', 'broken')
    isolated.setenv('ALDI_USER', 'PRIVATE_NUMBER')
    with pytest.raises(ValueError, match='Cannot decrypt ALDI_USER_ENC'):
        get_credential('ALDI_USER')


def test_env_key_supports_ephemeral_github_runner(isolated, tmp_path):
    _, key = encrypted_setup(tmp_path, isolated)
    isolated.setenv('CREDENTIAL_ENCRYPTION_KEY', key.read_text())
    key.unlink()
    assert get_credential('ALDI_USER') == 'PRIVATE_NUMBER'
    assert not key.exists()


def test_plain_credentials_do_not_create_a_key(isolated):
    isolated.setenv('ALDI_USER', 'PRIVATE_NUMBER')
    assert get_credential('ALDI_USER') == 'PRIVATE_NUMBER'
    assert not Path('.secret.key').exists()


@pytest.mark.parametrize('encrypted', [False, True])
def test_template_passwords_cannot_start_provider_login(isolated, tmp_path, encrypted):
    Path('.env').write_text('ALDI_USER=PRIVATE_NUMBER\nALDI_PASS=your-aldi-password\n')
    if encrypted:
        key = tmp_path / 'private/key'
        protect('.env', '.env', key)
        isolated.setenv('CREDENTIAL_KEY_FILE', str(key))
    with pytest.raises(ValueError, match='Placeholder credential for ALDI_PASS'):
        get_credential('ALDI_PASS')


def test_private_file_source(isolated, tmp_path):
    secret = tmp_path / 'secret'
    secret.write_text('PRIVATE_NUMBER\n')
    secret.chmod(0o600)
    isolated.setenv('ALDI_USER_FILE', str(secret))
    assert get_credential('ALDI_USER') == 'PRIVATE_NUMBER'


@pytest.mark.parametrize('failure', ['missing', 'relative', 'symlink', 'public', 'empty'])
def test_unsafe_file_source_rejected(isolated, tmp_path, failure):
    secret = tmp_path / 'secret'
    secret.write_text('' if failure == 'empty' else 'PRIVATE_NUMBER')
    secret.chmod(0o600)
    if failure == 'missing':
        secret.unlink()
    elif failure == 'relative':
        secret = Path('secret')
    elif failure == 'symlink':
        link = tmp_path / 'link'
        link.symlink_to(secret)
        secret = link
    elif failure == 'public':
        if os.name != 'posix':
            pytest.skip('POSIX permissions')
        secret.chmod(0o644)
    isolated.setenv('ALDI_USER_FILE', str(secret))
    with pytest.raises(ValueError, match='Cannot read protected ALDI_USER_FILE'):
        get_credential('ALDI_USER')


def test_monitoring_writes_sanitized_failure_without_browser(isolated, tmp_path, capsys):
    encrypted_setup(tmp_path, isolated)
    isolated.delenv('CREDENTIAL_KEY_FILE')
    factory = Mock(side_effect=AssertionError('browser must not start'))
    code = monitoring.run_cli(factory, {'aldi_talk': ('ALDI', Mock(), Mock())},
                              ['--report', 'report.json'], watcher.configure_credentials)
    assert code == 3
    factory.assert_not_called()
    report = json.loads(Path('report.json').read_text())
    assert report['providers'][0]['status'] == 'config_error'
    assert not report['auto_booking']['executed']
    assert 'PRIVATE' not in capsys.readouterr().out + Path('report.json').read_text()


def test_key_cannot_overwrite_configuration(isolated, tmp_path):
    source = tmp_path / '.env'
    source.write_text('ALDI_USER=PRIVATE_NUMBER\n')
    with pytest.raises(ValueError, match='key_path_conflicts'):
        protect(source, source, source)
    assert source.read_text() == 'ALDI_USER=PRIVATE_NUMBER\n'


def test_failed_reencryption_preserves_original_ciphertext(isolated, tmp_path):
    source, _ = encrypted_setup(tmp_path, isolated)
    original = source.read_bytes()
    with pytest.raises(Exception):
        protect(source, source, tmp_path / 'other/key')
    assert source.read_bytes() == original


def test_custom_config_path_is_shared_by_both_entrypoints(isolated, tmp_path):
    source, _ = encrypted_setup(tmp_path, isolated)
    alternate = tmp_path / 'alternate.env'
    source.rename(alternate)
    isolated.setenv('CREDENTIAL_ENV_FILE', str(alternate))
    assert Config().aldi_user == get_credential('ALDI_USER') == 'PRIVATE_NUMBER'


def test_personal_database_is_private(isolated, tmp_path):
    db = Database(str(tmp_path / 'private.sqlite'))
    if os.name == 'posix':
        assert db.db_path.stat().st_mode & 0o777 == 0o600
