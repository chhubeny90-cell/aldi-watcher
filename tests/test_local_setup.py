"""Offline installer regression checks; no credentials or external services."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def checkout(tmp_path):
    for name in ('install.sh', '.env.example'):
        shutil.copyfile(ROOT / name, tmp_path / name)
    return tmp_path


def run(checkout, *args):
    return subprocess.run(['bash', str(checkout / 'install.sh'), *args],
                          cwd='/', capture_output=True, text=True)


def test_default_setup_is_private_and_does_not_run_services(checkout):
    result = run(checkout)
    assert result.returncode == 0, result.stderr
    assert (checkout / '.env').read_bytes() == (checkout / '.env.example').read_bytes()
    if os.name == 'posix':
        assert (checkout / '.env').stat().st_mode & 0o777 == 0o600
    assert sorted(p.name for p in checkout.iterdir()) == ['.env', '.env.example', 'install.sh']


def test_repeat_setup_preserves_existing_private_configuration(checkout):
    path = checkout / '.env'
    path.write_text('ALDI_PASS=synthetic-test-value\n')
    path.chmod(0o600)
    before = path.stat()
    for _ in range(2):
        result = run(checkout)
        assert result.returncode == 0
        assert 'synthetic-test-value' not in result.stdout + result.stderr
    assert path.read_text() == 'ALDI_PASS=synthetic-test-value\n'
    assert path.stat().st_mtime_ns == before.st_mtime_ns
    assert path.stat().st_mode == before.st_mode


def test_symlink_does_not_overwrite_target(checkout, tmp_path):
    target = tmp_path / 'private-target'
    target.write_text('keep')
    (checkout / '.env').symlink_to(target)
    assert run(checkout).returncode != 0
    assert target.read_text() == 'keep'


def test_invalid_option_leaves_checkout_untouched(checkout):
    assert run(checkout, '--start').returncode == 2
    assert not (checkout / '.env').exists()


def test_env_directory_is_rejected(checkout):
    (checkout / '.env').mkdir()
    assert run(checkout).returncode != 0
