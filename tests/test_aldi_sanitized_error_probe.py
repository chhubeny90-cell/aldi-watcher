import json

import aldi_sanitized_error_probe as probe


def test_sanitize_removes_credentials_and_common_identifiers(monkeypatch):
    monkeypatch.setattr(probe.watcher, "ALDI_USER", "USER_SENTINEL")
    monkeypatch.setattr(probe.watcher, "ALDI_PASS", "PASS_SENTINEL")
    raw = (
        "Login error for USER_SENTINEL / PASS_SENTINEL, contact me@example.org, "
        "open https://example.org/reset and reference "
        "0123456789abcdef0123456789abcdef."
    )
    sanitized = probe._sanitize_text(raw)
    assert "USER_SENTINEL" not in sanitized
    assert "PASS_SENTINEL" not in sanitized
    assert "me@example.org" not in sanitized
    assert "https://" not in sanitized
    assert "0123456789abcdef0123456789abcdef" not in sanitized
    assert "[REDACTED]" in sanitized
    assert "[EMAIL]" in sanitized
    assert "[URL]" in sanitized
    assert "[TOKEN]" in sanitized


def test_text_output_samples_are_bounded_deduplicated_and_safe(monkeypatch):
    monkeypatch.setattr(probe.watcher, "ALDI_USER", "USER_SENTINEL")
    monkeypatch.setattr(probe.watcher, "ALDI_PASS", "PASS_SENTINEL")
    obj = {"callbacks": [
        {"type": "TextOutputCallback", "output": [{"name": "message", "value": "Anmeldung fehlgeschlagen für USER_SENTINEL"}]},
        {"type": "TextOutputCallback", "output": [{"name": "message", "value": "Anmeldung fehlgeschlagen für USER_SENTINEL"}]},
        {"type": "TextOutputCallback", "output": [{"name": "message", "value": "Bitte prüfe deine Eingaben"}]},
        {"type": "NameCallback", "output": [{"name": "prompt", "value": "USER_SENTINEL"}]},
    ]}
    samples = probe._text_output_samples(obj)
    assert samples == ["Anmeldung fehlgeschlagen für [REDACTED]", "Bitte prüfe deine Eingaben"]
    serialized = json.dumps(samples, ensure_ascii=False)
    assert "USER_SENTINEL" not in serialized
    assert "PASS_SENTINEL" not in serialized


def test_shape_extension_does_not_expose_auth_material(monkeypatch):
    monkeypatch.setattr(probe.watcher, "ALDI_USER", "USER_SENTINEL")
    monkeypatch.setattr(probe.watcher, "ALDI_PASS", "PASS_SENTINEL")
    obj = {
        "authId": "0123456789abcdef0123456789abcdef",
        "stage": "stage-loginPage",
        "callbacks": [
            {"type": "TextOutputCallback", "output": [{"name": "message", "value": "Fehler USER_SENTINEL"}]},
        ],
    }
    shape = probe._shape_with_sanitized_text(obj, 200)
    serialized = json.dumps(shape, ensure_ascii=False)
    assert "USER_SENTINEL" not in serialized
    assert "PASS_SENTINEL" not in serialized
    assert "0123456789abcdef0123456789abcdef" not in serialized
    assert shape["sanitized_text_outputs"] == ["Fehler [REDACTED]"]
