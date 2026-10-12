import json

import aldi_sanitized_error_probe as probe


def test_sanitize_removes_credentials_and_common_identifiers(monkeypatch):
    monkeypatch.setattr(probe.watcher, "ALDI_USER", "01701234567")
    monkeypatch.setattr(probe.watcher, "ALDI_PASS", "PRIVATE-PASS!42")
    raw = (
        "Login error for 01701234567 / PRIVATE-PASS!42, contact me@example.org, "
        "open https://example.org/reset?id=secret and reference "
        "0123456789abcdef0123456789abcdef."
    )
    sanitized = probe._sanitize_text(raw)
    assert "01701234567" not in sanitized
    assert "PRIVATE-PASS!42" not in sanitized
    assert "me@example.org" not in sanitized
    assert "https://" not in sanitized
    assert "0123456789abcdef0123456789abcdef" not in sanitized
    assert "[REDACTED]" in sanitized
    assert "[EMAIL]" in sanitized
    assert "[URL]" in sanitized
    assert "[TOKEN]" in sanitized


def test_text_output_samples_are_bounded_deduplicated_and_safe(monkeypatch):
    monkeypatch.setattr(probe.watcher, "ALDI_USER", "01701234567")
    monkeypatch.setattr(probe.watcher, "ALDI_PASS", "PRIVATE-PASS!42")
    obj = {"callbacks": [
        {"type": "TextOutputCallback", "output": [{"name": "message", "value": "Anmeldung fehlgeschlagen für 01701234567"}]},
        {"type": "TextOutputCallback", "output": [{"name": "message", "value": "Anmeldung fehlgeschlagen für 01701234567"}]},
        {"type": "TextOutputCallback", "output": [{"name": "message", "value": "Bitte prüfe deine Eingaben"}]},
        {"type": "NameCallback", "output": [{"name": "prompt", "value": "01701234567"}]},
    ]}
    samples = probe._text_output_samples(obj)
    assert samples == ["Anmeldung fehlgeschlagen für [PHONE]", "Bitte prüfe deine Eingaben"]
    serialized = json.dumps(samples, ensure_ascii=False)
    assert "01701234567" not in serialized
    assert "PRIVATE-PASS!42" not in serialized


def test_shape_extension_does_not_expose_auth_material(monkeypatch):
    monkeypatch.setattr(probe.watcher, "ALDI_USER", "01701234567")
    monkeypatch.setattr(probe.watcher, "ALDI_PASS", "PRIVATE-PASS!42")
    obj = {
        "authId": "0123456789abcdef0123456789abcdef",
        "stage": "stage-loginPage",
        "callbacks": [
            {"type": "TextOutputCallback", "output": [{"name": "message", "value": "Fehler 01701234567"}]},
        ],
    }
    shape = probe._shape_with_sanitized_text(obj, 200)
    serialized = json.dumps(shape, ensure_ascii=False)
    assert "01701234567" not in serialized
    assert "PRIVATE-PASS!42" not in serialized
    assert "0123456789abcdef0123456789abcdef" not in serialized
    assert shape["sanitized_text_outputs"] == ["Fehler [PHONE]"]
