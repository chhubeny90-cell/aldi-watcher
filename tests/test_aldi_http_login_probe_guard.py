"""Offline regression coverage for the controlled read-only login boundary."""
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

import aldi_http_login_probe as probe
from github_journal_state import _encode_state, _parse_state


PHONE = "01520000000"
PASSWORD = "synthetic-password-not-a-real-secret"
NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/http-login.yml"


@pytest.fixture
def guarded(tmp_path, monkeypatch):
    values = {
        "GITHUB_REPOSITORY": "chhubeny90-cell/aldi-watcher",
        "GITHUB_REF": "refs/heads/main", "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_RUN_ATTEMPT": "1", "GITHUB_SHA": "d" * 40, "GITHUB_RUN_ID": "12345",
        "AUTO_BOOK_ENABLED": "false", "ALDI_MANUAL_LOGIN_VERIFIED": "true",
        "ALDI_EXPECTED_ACCOUNT": PHONE,
        "ALDI_HTTP_REPORT": str(tmp_path / "report.json"),
    }
    monkeypatch.setattr(probe.os, "environ", values)
    # A missed mock must fail rather than send provider or GitHub traffic.
    monkeypatch.setattr(requests.sessions.Session, "request",
                        Mock(side_effect=AssertionError("unexpected network")))
    credentials = {"ALDI_USER": PHONE, "ALDI_PASS": PASSWORD}
    resolver = Mock(side_effect=lambda name: credentials[name])
    monkeypatch.setattr(probe, "get_credential", resolver)
    state = {"version": 2, "unresolved": [], "auth_retry_after": None}
    events = {}
    storage = {"sha": "b" * 40, "state": state}
    def read_snapshot():
        return copy.deepcopy(("a" * 40, events, (storage["sha"], storage["state"])))
    snapshot = Mock(side_effect=read_snapshot)
    monkeypatch.setattr(probe, "consistent_mail_snapshot", snapshot)
    def store_reserved(reserved, sha, **kwargs):
        if sha != storage["sha"]:
            raise RuntimeError("github_state_http_409")
        # Match the real GitHub persistence boundary, including its UTC-Z
        # canonicalization. A deepcopy hid a previously broken readback check.
        encoded = _encode_state(reserved["unresolved"], reserved["auth_retry_after"])
        storage.update(sha="c" * 40, state=_parse_state(encoded), encoded=encoded)
    writes = Mock(side_effect=store_reserved)
    monkeypatch.setattr(probe, "_put_state", writes)
    client = Mock(report={})

    def login(phone, password):
        assert (phone, password) == (PHONE, PASSWORD)
        client.report.update(login_ok=True, account_match=True, credential_submissions=1)
        return True

    client.login.side_effect = login
    factory = Mock(return_value=client)
    monkeypatch.setattr(probe, "AldiHttpLogin", factory)
    return SimpleNamespace(env=values, credentials=credentials, resolver=resolver,
                           state=state, events=events, snapshot=snapshot,
                           writes=writes, client=client, factory=factory,
                           report=Path(values["ALDI_HTTP_REPORT"]), storage=storage,
                           read_snapshot=read_snapshot, store_reserved=store_reserved)


def read_report(guarded):
    return json.loads(guarded.report.read_text())


def assert_no_provider(guarded):
    guarded.factory.assert_not_called()
    guarded.client.login.assert_not_called()


@pytest.mark.parametrize("name,value", [
    ("GITHUB_REPOSITORY", "other/repository"),
    ("GITHUB_REF", "refs/heads/feature"),
    ("GITHUB_EVENT_NAME", "push"),
    ("GITHUB_EVENT_NAME", "schedule"),
    ("GITHUB_RUN_ATTEMPT", "2"),
    ("GITHUB_RUN_ATTEMPT", "01"),
    ("GITHUB_RUN_ATTEMPT", ""),
    ("GITHUB_SHA", "abcd"),
    ("GITHUB_SHA", "G" * 40),
    ("GITHUB_RUN_ID", "0"),
    ("GITHUB_RUN_ID", "01"),
])
def test_invalid_context_cannot_read_guard_or_contact_provider(guarded, name, value):
    guarded.env[name] = value
    assert probe.main() == 2
    assert read_report(guarded)["outcome"] == "controlled_dispatch_required"
    guarded.snapshot.assert_not_called()
    guarded.writes.assert_not_called()
    assert_no_provider(guarded)


@pytest.mark.parametrize("value", ["false", "True", "1", "", None])
def test_manual_recovery_confirmation_is_required_before_io(guarded, value):
    if value is None:
        guarded.env.pop("ALDI_MANUAL_LOGIN_VERIFIED")
    else:
        guarded.env["ALDI_MANUAL_LOGIN_VERIFIED"] = value
    assert probe.main() == 2
    assert read_report(guarded)["outcome"] == "manual_login_verification_required"
    guarded.resolver.assert_not_called()
    guarded.snapshot.assert_not_called()
    guarded.writes.assert_not_called()
    assert_no_provider(guarded)


@pytest.mark.parametrize("value", ["true", "False", "", None])
def test_booking_configuration_must_be_explicitly_disabled(guarded, value):
    if value is None:
        guarded.env.pop("AUTO_BOOK_ENABLED")
    else:
        guarded.env["AUTO_BOOK_ENABLED"] = value
    assert probe.main() == 2
    assert read_report(guarded)["outcome"] == "read_only_required"
    guarded.snapshot.assert_not_called()
    guarded.writes.assert_not_called()
    assert_no_provider(guarded)


@pytest.mark.parametrize("value,outcome", [
    ("", "expected_account_required"),
    ("not-a-phone", "phone_identifier_required"),
    ("01529999999", "configured_account_mismatch"),
])
def test_missing_or_wrong_explicit_target_blocks_generic_credentials(guarded, value, outcome):
    guarded.env["ALDI_EXPECTED_ACCOUNT"] = value
    assert probe.main() == 2
    assert read_report(guarded)["outcome"] == outcome
    guarded.snapshot.assert_not_called()
    guarded.writes.assert_not_called()
    assert_no_provider(guarded)


def test_missing_password_never_reserves_or_contacts_provider(guarded):
    guarded.credentials["ALDI_PASS"] = None
    assert probe.main() == 2
    assert read_report(guarded)["outcome"] == "password_missing"
    guarded.snapshot.assert_not_called()
    guarded.writes.assert_not_called()
    assert_no_provider(guarded)


@pytest.mark.parametrize("failure", [RuntimeError("private GitHub response"),
                                     TimeoutError("private timeout data")])
def test_unreadable_or_incoherent_guard_is_not_treated_as_empty(guarded, failure):
    guarded.snapshot.side_effect = failure
    assert probe.main() == 2
    assert read_report(guarded)["outcome"] == "probe_error"
    guarded.writes.assert_not_called()
    assert_no_provider(guarded)
    assert "private" not in guarded.report.read_text()


def test_missing_guard_does_not_create_replacement_history(guarded):
    guarded.snapshot.side_effect = None
    guarded.snapshot.return_value = ("a" * 40, {}, None)
    assert probe.main() == 2
    assert read_report(guarded)["outcome"] == "auth_guard_missing"
    guarded.writes.assert_not_called()
    assert_no_provider(guarded)


@pytest.mark.parametrize("phase", ["IN_FLIGHT", "QUARANTINED_UNKNOWN"])
def test_unresolved_mail_handoff_blocks_login(guarded, phase):
    guarded.events["synthetic-event"] = {"phase": phase}
    assert probe.main() == 2
    assert read_report(guarded)["outcome"] == "unresolved_provider_state"
    guarded.writes.assert_not_called()
    assert_no_provider(guarded)


def test_unresolved_provider_operation_blocks_login(guarded):
    guarded.state["unresolved"] = [{"status": "UNKNOWN", "recharge_id": "synthetic"}]
    assert probe.main() == 2
    assert read_report(guarded)["outcome"] == "unresolved_provider_state"
    guarded.writes.assert_not_called()
    assert_no_provider(guarded)


def test_active_backoff_cannot_be_overridden_by_manual_confirmation(guarded):
    guarded.state["auth_retry_after"] = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    assert probe.main() == 2
    assert read_report(guarded)["outcome"] == "auth_backoff_active"
    guarded.writes.assert_not_called()
    assert_no_provider(guarded)


@pytest.mark.parametrize("retry", ["bad-time", "2026-10-24T12:00:00"])
def test_unverifiable_backoff_does_not_allow_login(guarded, retry):
    guarded.state["auth_retry_after"] = retry
    assert probe.main() == 2
    guarded.writes.assert_not_called()
    assert_no_provider(guarded)


def test_expired_guard_is_replaced_by_exact_24h_cas_without_mutating_snapshot(guarded):
    guarded.state["auth_retry_after"] = (NOW - timedelta(hours=1)).isoformat()
    original = copy.deepcopy(guarded.state)
    report = {"reservation_status": "not_attempted"}
    probe._reserve_attempt(NOW, report)
    assert report["reservation_status"] == "confirmed"
    guarded.writes.assert_called_once()
    state, sha = guarded.writes.call_args.args
    assert sha == "b" * 40
    assert datetime.fromisoformat(state["auth_retry_after"].replace("Z", "+00:00")) == NOW + timedelta(hours=24)
    assert state["auth_retry_after"].endswith("Z")
    assert state["unresolved"] == []
    assert guarded.state == original


@pytest.mark.parametrize("failure", [RuntimeError("conflict PRIVATE_PAYLOAD"),
                                     TimeoutError("unknown write PRIVATE_PAYLOAD")])
def test_failed_or_uncertain_reservation_never_calls_provider_or_retries(guarded, failure):
    guarded.writes.side_effect = failure
    assert probe.main() == 2
    guarded.writes.assert_called_once()
    assert_no_provider(guarded)
    report = read_report(guarded)
    assert report["reservation_status"] == "unconfirmed"
    assert report["outcome"] == "probe_error"
    assert "PRIVATE_PAYLOAD" not in guarded.report.read_text()


@pytest.mark.parametrize("change", ["missing_journal", "changed_guard", "changed_queue", "read_error"])
def test_unverified_readback_retains_guard_but_blocks_provider(guarded, change):
    reads = 0

    def snapshot():
        nonlocal reads
        reads += 1
        result = guarded.read_snapshot()
        if reads == 1:
            return result
        version, events, journal = result
        if change == "read_error":
            raise TimeoutError("PRIVATE_READBACK_DETAIL")
        if change == "missing_journal":
            return version, events, None
        if change == "changed_guard":
            journal[1]["auth_retry_after"] = None
        if change == "changed_queue":
            events["synthetic-mail"] = {"phase": "IN_FLIGHT"}
        return version, events, journal

    guarded.snapshot.side_effect = snapshot
    assert probe.main() == 2
    guarded.writes.assert_called_once()
    assert guarded.storage["state"]["auth_retry_after"] is not None
    assert read_report(guarded)["reservation_status"] == "unconfirmed"
    assert_no_provider(guarded)
    assert "PRIVATE_READBACK_DETAIL" not in guarded.report.read_text()


def test_timeout_after_committed_write_still_prevents_provider_attempt(guarded):
    def uncertain_write(*args, **kwargs):
        guarded.store_reserved(*args, **kwargs)
        raise TimeoutError("PRIVATE_WRITE_DETAIL")

    guarded.writes.side_effect = uncertain_write
    assert probe.main() == 2
    assert read_report(guarded)["reservation_status"] == "unconfirmed"
    assert guarded.storage["state"]["auth_retry_after"] is not None
    guarded.writes.assert_called_once()
    assert_no_provider(guarded)


def test_durable_reservation_precedes_client_construction_and_one_login(guarded):
    sequence = []
    def store(*args, **kwargs):
        sequence.append("reserve")
        return guarded.store_reserved(*args, **kwargs)
    guarded.writes.side_effect = store
    guarded.factory.side_effect = lambda: sequence.append("client") or guarded.client
    login = guarded.client.login.side_effect
    guarded.client.login.side_effect = lambda *args: sequence.append("login") or login(*args)
    assert probe.main() == 0
    assert sequence == ["reserve", "client", "login"]
    guarded.client.login.assert_called_once_with(PHONE, PASSWORD)
    guarded.client.close.assert_called_once()
    guarded.writes.assert_called_once()  # Success does not clear the 24-hour guard.
    report = read_report(guarded)
    assert report["outcome"] == "login_verified"
    assert report["login_ok"] is True
    assert report["account_match"] is True
    assert report["reservation_status"] == "confirmed"
    assert report["booking_clicks"] == 0
    assert report["read_only"] is True
    assert report["tariff_loaded"] is False
    assert report["remaining_volume_loaded"] is False


def test_successful_login_roundtrips_real_guard_encoding_before_provider_call(guarded):
    def login_after_roundtrip(phone, password):
        persisted = _parse_state(guarded.storage["encoded"])
        reserved = guarded.writes.call_args.args[0]
        assert persisted == reserved
        assert persisted["auth_retry_after"].endswith("Z")
        guarded.client.report.update(login_ok=True, account_match=True, credential_submissions=1)
        return True

    guarded.client.login.side_effect = login_after_roundtrip
    assert probe.main() == 0
    assert read_report(guarded)["reservation_status"] == "confirmed"
    guarded.client.login.assert_called_once_with(PHONE, PASSWORD)
    assert guarded.snapshot.call_count == 2
    guarded.writes.assert_called_once()


def test_reservation_from_non_utc_clock_roundtrips_as_canonical_utc(guarded):
    offset_now = NOW.astimezone(timezone(timedelta(hours=2)))
    report = {"reservation_status": "not_attempted"}
    probe._reserve_attempt(offset_now, report)
    persisted = _parse_state(guarded.storage["encoded"])
    assert persisted["auth_retry_after"] == "2026-10-24T12:00:00Z"
    assert report["reservation_status"] == "confirmed"


@pytest.mark.parametrize("failure,outcome", [
    (probe.LoginError("account_locked"), "account_locked"),
    (probe.LoginError("authentication_not_completed"), "authentication_not_completed"),
    (TimeoutError("PRIVATE_PROVIDER_RESPONSE"), "probe_error"),
])
def test_provider_failure_keeps_reservation_and_does_not_retry(guarded, failure, outcome):
    guarded.client.login.side_effect = failure
    assert probe.main() == 2
    guarded.writes.assert_called_once()
    guarded.client.login.assert_called_once()
    guarded.client.close.assert_called_once()
    report = read_report(guarded)
    assert report["reservation_status"] == "confirmed"
    assert report["outcome"] == outcome
    assert report["booking_clicks"] == 0
    assert "PRIVATE_PROVIDER_RESPONSE" not in guarded.report.read_text()


def test_two_stale_snapshot_attempts_only_one_can_pass_cas(guarded):
    stale = guarded.read_snapshot()
    reads = 0

    def snapshot():
        nonlocal reads
        reads += 1
        # First snapshot + confirmed readback, then a racing stale snapshot.
        return copy.deepcopy(stale) if reads in (1, 3) else guarded.read_snapshot()

    guarded.snapshot.side_effect = snapshot
    assert probe.main() == 0
    assert probe.main() == 2
    assert guarded.writes.call_count == 2
    guarded.factory.assert_called_once()
    guarded.client.login.assert_called_once()
    assert guarded.storage["state"]["auth_retry_after"] is not None


def test_login_report_never_contains_credential_or_raw_failure_text(guarded, capsys):
    guarded.resolver.side_effect = RuntimeError(PASSWORD + " PRIVATE_DETAIL " + PHONE)
    assert probe.main() == 2
    text = guarded.report.read_text() + capsys.readouterr().out
    for value in (PHONE, PASSWORD, "PRIVATE_DETAIL"):
        assert value not in text
    assert read_report(guarded)["exception_type"] == "RuntimeError"
    assert_no_provider(guarded)


def test_cleanup_error_does_not_leak_details_or_erase_success(guarded, capsys):
    guarded.client.close.side_effect = RuntimeError("PRIVATE_CLEANUP_DETAIL")
    assert probe.main() == 0
    assert "PRIVATE_CLEANUP_DETAIL" not in capsys.readouterr().out
    assert read_report(guarded)["outcome"] == "login_verified"


def test_workflow_is_manual_only_and_keeps_credentials_scoped_to_guarded_step():
    text = WORKFLOW.read_text()
    triggers = text.split("on:\n", 1)[1].split("permissions:\n", 1)[0]
    assert "  workflow_dispatch:\n" in triggers
    assert "push:" not in triggers and "schedule:" not in triggers and "pull_request:" not in triggers
    assert "      manual_login_verified:\n" in triggers
    assert "        type: boolean\n" in triggers
    assert "        default: false\n" in triggers
    assert "permissions:\n  contents: none\n" in text
    assert "    permissions:\n      contents: write" in text
    assert "persist-credentials: false" in text
    assert "ref: ${{ github.sha }}" in text
    assert "AUTO_BOOK_ENABLED: 'false'" in text
    assert "ALDI_EXPECTED_ACCOUNT: ${{ secrets.ALDI_PROFILE_1_USER }}" in text
    assert "ALDI_USER: ${{ secrets.ALDI_PROFILE_1_USER }}" in text
    assert "secrets.ALDI_USER" not in text
    assert "GITHUB_TOKEN: ${{ github.token }}" in text
    assert text.count("python aldi_http_login_probe.py") == 1


@pytest.mark.parametrize("repository,event,ref,attempt,allowed", [
    ("chhubeny90-cell/aldi-watcher", "workflow_dispatch", "refs/heads/main", 1, True),
    ("other/repo", "workflow_dispatch", "refs/heads/main", 1, False),
    ("chhubeny90-cell/aldi-watcher", "push", "refs/heads/main", 1, False),
    ("chhubeny90-cell/aldi-watcher", "workflow_dispatch", "refs/heads/feature", 1, False),
    ("chhubeny90-cell/aldi-watcher", "workflow_dispatch", "refs/heads/main", 2, False),
])
def test_actual_workflow_job_condition_rejects_wrong_context(repository, event, ref, attempt, allowed):
    expression = re.search(r"    if: >-\n(.*?)    runs-on:", WORKFLOW.read_text(), re.S).group(1)
    expression = " ".join(expression.replace("&&", "and").replace("||", "or").split())
    github = SimpleNamespace(repository=repository, event_name=event, ref=ref, run_attempt=attempt)
    assert eval(expression, {"__builtins__": {}}, {"github": github}) is allowed
