import pytest

import github_journal_state as state


@pytest.fixture
def crypto_env(monkeypatch):
    monkeypatch.setenv("ALDI_JOURNAL_KEY", "test-only-journal-key-" + "x" * 32)
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/aldi-watcher")
    monkeypatch.setenv("ALDI_STATE_BRANCH", "test-state")
    monkeypatch.setenv("ALDI_STATE_PATH", ".state/journal.enc")


def test_journal_ciphertext_round_trip_and_hides_plaintext(crypto_env):
    plaintext = b"01500000000|PENDING|private-contract"
    encrypted = state.encrypt_bytes(plaintext)
    assert plaintext not in encrypted
    assert encrypted.startswith(state.MAGIC)
    assert state.decrypt_bytes(encrypted) == plaintext


def test_wrong_key_cannot_decrypt(monkeypatch, crypto_env):
    encrypted = state.encrypt_bytes(b"sensitive")
    monkeypatch.setenv("ALDI_JOURNAL_KEY", "different-test-key-" + "y" * 32)
    with pytest.raises(RuntimeError, match="journal_decryption_failed"):
        state.decrypt_bytes(encrypted)


def test_short_or_missing_key_is_rejected(monkeypatch, crypto_env):
    monkeypatch.setenv("ALDI_JOURNAL_KEY", "short")
    with pytest.raises(RuntimeError, match="journal_key_unavailable"):
        state.encrypt_bytes(b"x")
