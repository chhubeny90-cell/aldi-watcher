"""Offline coverage of the user-facing summary and its disclosure boundary."""
import json

import pytest

import aldi_http_login_summary as summary


def test_success_reports_verified_login_and_its_limits():
    text = summary.render_summary({
        "outcome": "login_verified", "login_ok": True, "account_match": True,
        "reservation_status": "confirmed", "retry_after": "2026-10-26T12:00:00Z",
    })
    assert "**Login bestätigt.**" in text
    assert "Tarif und Restvolumen wurden dabei nicht geprüft" in text
    assert "keine Buchung" in text
    assert "2026-10-26 12:00:00 UTC" in text
    assert "24-Stunden-Abstand" in text


@pytest.mark.parametrize("patch", [
    {"login_ok": False}, {"account_match": False}, {"login_ok": "true"},
    {"account_match": 1}, {"outcome": "probe_error"},
])
def test_success_requires_explicit_verification(patch):
    report = {"outcome": "login_verified", "login_ok": True, "account_match": True}
    report.update(patch)
    assert "**Login nicht bestätigt.**" in summary.render_summary(report)


@pytest.mark.parametrize("outcome,expected", [
    ("expected_account_required", "ALDI_PROFILE_1_USER"),
    ("phone_identifier_required", "ALDI_PROFILE_1_USER"),
    ("configured_account_mismatch", "ALDI_PROFILE_1_USER"),
    ("password_missing", "ALDI_PASS"),
    ("account_locked", "offiziellen ALDI-Weg"),
    ("auth_guard_missing", "keine leere Ersatzhistorie"),
    ("unresolved_provider_state", "ungeklärten Vorgang"),
    ("controlled_dispatch_required", "`main`"),
    ("read_only_required", "AUTO_BOOK_ENABLED"),
])
def test_known_failures_explain_cause_and_next_step(outcome, expected):
    text = summary.render_summary({"outcome": outcome})
    assert "Login nicht bestätigt" in text
    assert "Nächster Schritt:" in text
    assert expected in text


def test_password_failure_explains_encrypted_alternative():
    text = summary.render_summary({"outcome": "password_missing"})
    assert "ALDI_PASS_ENC" in text
    assert "CREDENTIAL_ENCRYPTION_KEY" in text


def test_active_backoff_shows_normalized_utc_time():
    text = summary.render_summary({
        "outcome": "auth_backoff_active", "retry_after": "2026-10-26T14:00:00+02:00",
    })
    assert "kein Anbieterzugriff" in text
    assert "Frühester nächster Versuch: **2026-10-26 12:00:00 UTC**" in text
    assert "Sperre nicht zurücksetzen" in text


def test_unconfirmed_reservation_does_not_present_time_as_confirmed():
    text = summary.render_summary({
        "outcome": "auth_reservation_unverified", "reservation_status": "unconfirmed",
        "retry_after": "2026-10-26T12:00:00Z",
    })
    assert "könnte bereits gespeichert sein" in text
    assert "nicht sofort erneut starten" in text
    assert "2026-10-26 12:00:00 UTC" in text
    assert "Frühester nächster Versuch" not in text


@pytest.mark.parametrize("value", [
    None, {}, 123, "2026-10-26T12:00:00", "2026-99-26T12:00:00Z",
    "2026-10-26T12:00:00Z PRIVATE_TIME", "<script>PRIVATE_TIME</script>",
])
def test_invalid_times_are_omitted(value):
    text = summary.render_summary({
        "outcome": "auth_backoff_active", "retry_after": value,
    })
    assert "Frühester nächster Versuch:" not in text
    assert "PRIVATE_TIME" not in text


@pytest.mark.parametrize("outcome", ["PRIVATE_OUTCOME", {"private": "PRIVATE_OUTCOME"}])
def test_arbitrary_report_content_is_never_echoed(outcome):
    text = summary.render_summary({
        "outcome": outcome, "exception_type": "PRIVATE_EXCEPTION", "phone": "01529999999",
        "password": "PRIVATE_PASSWORD", "provider_response": "PRIVATE_PROVIDER",
        "retry_after": "PRIVATE_TIME", "phase": "PRIVATE_PHASE",
    })
    assert "Login nicht bestätigt" in text
    assert "PRIVATE" not in text
    assert "01529999999" not in text


@pytest.mark.parametrize("content", [None, "{PRIVATE_BROKEN", '"PRIVATE_STRING"',
                                         '["PRIVATE_LIST"]', b"\xffPRIVATE_BYTES"])
def test_missing_or_unreadable_report_does_not_confirm_timeout_login(
        tmp_path, monkeypatch, content):
    report = tmp_path / "report.json"
    if isinstance(content, bytes):
        report.write_bytes(content)
    elif content is not None:
        report.write_text(content)
    output = tmp_path / "summary.md"
    monkeypatch.setenv("ALDI_HTTP_REPORT", str(report))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(output))
    assert summary.main() == 0
    text = output.read_text()
    assert "Login nicht bestätigt" in text
    assert "Timeout" in text
    assert "nicht sofort erneut starten" in text
    assert "PRIVATE" not in text


def test_cli_appends_summary_without_overwriting_existing_content(tmp_path, monkeypatch):
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"outcome": "password_missing"}))
    output = tmp_path / "summary.md"
    output.write_text("Existing summary\n\n")
    monkeypatch.setenv("ALDI_HTTP_REPORT", str(report))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(output))
    assert summary.main() == 0
    assert output.read_text().startswith("Existing summary\n\n## ALDI-Login")
    assert "ALDI_PASS" in output.read_text()


def test_cli_without_actions_summary_prints_only_safe_text(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ALDI_HTTP_REPORT", raising=False)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert summary.main() == 0
    assert "Login nicht bestätigt" in capsys.readouterr().out
