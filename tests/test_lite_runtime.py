import base64
import json
import time
from dataclasses import replace

import pytest

from lite.engine import Engine
from lite.models import MailEvent, ProcessResult, Snapshot
from lite.runtime import MailRuntime, RuntimeConfig, RuntimeErrorClass, classified, log_event_result


class Gmail:
    def __init__(self, mailbox, events=(), cursor="20"):
        self.mailbox, self.events, self.new_cursor = mailbox, list(events), cursor
        self.reads, self.watches = 0, 0

    def get_profile(self):
        return {"emailAddress": self.mailbox, "historyId": "10"}

    def events_since(self, previous, account):
        self.reads += 1
        return self.events, self.new_cursor

    def watch(self, topic):
        self.watches += 1
        return {"historyId": "999", "expiration": "1999999999999"}


class Provider:
    def __init__(self, calls):
        self.calls = calls

    def inspect(self):
        self.calls.append("inspect")
        return Snapshot(True, True)

    def close(self):
        self.calls.append("close")

    def book(self, *args):
        pytest.fail("Transport test must never book")

    def reconcile(self, *args):
        pytest.fail("Transport test has no pending recharge")


@pytest.fixture
def configured(tmp_path):
    return RuntimeConfig(str(tmp_path / "lite.sqlite"), "primary", "test@example.com",
                         push_audience="https://example.com/pubsub/gmail",
                         push_service_account="push@project.iam.gserviceaccount.com",
                         push_subscription="projects/project/subscriptions/aldi",
                         watch_topic="projects/project/topics/aldi")


def mail(config, suffix="a"):
    return MailEvent("event-" + suffix, config.mailbox, suffix, time.time(), "exhausted", config.account)


def claims(config):
    return {"email": config.push_service_account, "email_verified": True,
            "aud": config.push_audience, "iss": "https://accounts.google.com"}


def push(config, history="20"):
    data = json.dumps({"emailAddress": config.mailbox, "historyId": history}).encode()
    return {"subscription": config.push_subscription,
            "message": {"messageId": "notification-1", "data": base64.b64encode(data).decode()}}


def runtime(config, gmail, calls=None, token_claims=None):
    calls = [] if calls is None else calls
    return MailRuntime(config, gmail,
        processor=lambda event: Engine(config.database_path, Provider(calls), config.account).process(event),
        token_verifier=lambda token, audience: claims(config) if token_claims is None else token_claims)


def test_live_requires_explicit_flags_and_absolute_durable_database():
    env = {"ALDI_ACCOUNT_ALIAS": "primary", "ALDI_MAILBOX": "test@example.com"}
    assert RuntimeConfig.from_env(env).dry_run is True
    with pytest.raises(RuntimeErrorClass, match="live_booking_disabled"):
        RuntimeConfig.from_env(dict(env, DRY_RUN="false"))
    with pytest.raises(RuntimeErrorClass, match="live_durable_database_path_required"):
        RuntimeConfig.from_env(dict(env, DRY_RUN="false", AUTO_BOOK_ENABLED="true"))
    with pytest.raises(RuntimeErrorClass, match="live_durable_database_path_required"):
        RuntimeConfig.from_env(dict(env, DRY_RUN="false", AUTO_BOOK_ENABLED="true", LITE_DB_PATH="relative.sqlite"))
    config = RuntimeConfig.from_env(dict(env, DRY_RUN="false", AUTO_BOOK_ENABLED="true", LITE_DB_PATH="/data/state.sqlite"))
    assert config.dry_run is False
    assert config.recent_success_guard_seconds == 0


@pytest.mark.parametrize("value", ["nan", "inf", "-1", "no"])
def test_recent_success_guard_requires_finite_nonnegative_number(value):
    with pytest.raises(RuntimeErrorClass, match="recent_success_guard_invalid"):
        RuntimeConfig.from_env({"ALDI_ACCOUNT_ALIAS": "primary", "ALDI_MAILBOX": "test@example.com",
                               "LITE_RECENT_SUCCESS_GUARD_SECONDS": value})


@pytest.mark.parametrize("value", ["1", "yes", "tru", "false\nextra"])
def test_ambiguous_boolean_never_enables_live(value):
    with pytest.raises(RuntimeErrorClass, match="boolean_configuration_invalid"):
        RuntimeConfig.from_env({"ALDI_ACCOUNT_ALIAS": "primary", "ALDI_MAILBOX": "test@example.com", "DRY_RUN": value})


def test_init_is_explicit_and_repeated_init_preserves_existing_cursor(configured):
    gmail = Gmail(configured.mailbox)
    app = runtime(configured, gmail)
    with pytest.raises(RuntimeErrorClass, match="gmail_cursor_not_initialized"):
        app.poll_once()
    assert app.initialize()["mailbox_verified"]
    app.poll_once()
    assert app.cursor() == "20"
    app.initialize()
    assert app.cursor() == "20"


def test_push_processes_real_engine_event_and_acknowledges_old_notification_without_provider(configured):
    event, calls = mail(configured), []
    gmail = Gmail(configured.mailbox, [event])
    app = runtime(configured, gmail, calls)
    app.initialize()
    assert app.handle_push("Bearer valid-token", push(configured)) == (200, {"events": 1, "duplicate": False})
    assert app.cursor() == "20"
    assert calls == ["inspect", "close"]
    assert app.handle_push("Bearer valid-token", push(configured, "15")) == (200, {"events": 0, "duplicate": True})
    assert gmail.reads == 1
    assert calls == ["inspect", "close"]


@pytest.mark.parametrize("mutated", [
    {"email": "other@project.iam.gserviceaccount.com"},
    {"email_verified": False}, {"email_verified": "true"},
    {"aud": "https://other.example.com"}, {"iss": "untrusted.example.com"},
])
def test_identity_claim_mismatch_cannot_start_lite(configured, mutated):
    token_claims = dict(claims(configured), **mutated)
    gmail = Gmail(configured.mailbox, [mail(configured)])
    app = runtime(configured, gmail, token_claims=token_claims)
    assert app.handle_push("Bearer signed-token", push(configured))[0] == 403
    assert gmail.reads == 0


def test_unsigned_and_failed_signature_requests_cannot_read_mail(configured):
    gmail = Gmail(configured.mailbox, [mail(configured)])
    app = runtime(configured, gmail)
    assert app.handle_push(None, push(configured))[0] == 401
    def bad_signature(*args):
        raise ValueError("sensitive-token-never-log")
    app.token_verifier = bad_signature
    status, result = app.handle_push("Bearer untrusted-token", push(configured))
    assert status == 403
    assert "sensitive" not in json.dumps(result)
    assert gmail.reads == 0


def test_wrong_subscription_mailbox_and_malformed_data_rejected(configured):
    gmail = Gmail(configured.mailbox)
    app = runtime(configured, gmail)
    payload = push(configured)
    payload["subscription"] = "projects/other/subscriptions/other"
    assert app.handle_push("Bearer token", payload)[0] == 400
    for notification in [{"emailAddress": "other@example.com", "historyId": "20"},
                         {"emailAddress": {}, "historyId": "20"},
                         {"emailAddress": configured.mailbox, "historyId": "invalid"}]:
        payload = push(configured)
        payload["message"]["data"] = base64.b64encode(json.dumps(notification).encode()).decode()
        assert app.handle_push("Bearer token", payload)[0] == 400
    payload = push(configured)
    payload["message"]["data"] = "not-base64!"
    assert app.handle_push("Bearer token", payload)[0] == 400
    assert gmail.reads == 0


def test_busy_second_event_keeps_cursor_then_replay_deduplicates_first(configured):
    events, calls = [mail(configured, "a"), mail(configured, "b")], []
    gmail = Gmail(configured.mailbox, events)
    app = runtime(configured, gmail, calls)
    normal = app.processor
    app.processor = lambda event: ProcessResult("BUSY", "RETRY") if event.mail_id == "b" else normal(event)
    app.initialize()
    status, result = app.handle_push("Bearer token", push(configured))
    assert status == 503 and result["error_class"] == "lite_busy"
    assert app.cursor() == "10"
    assert calls.count("inspect") == 1
    # Simulate a restarted listener opening the same persisted database.
    restarted = runtime(configured, gmail, calls)
    assert restarted.handle_push("Bearer token", push(configured))[0] == 200
    assert restarted.cursor() == "20"
    assert calls.count("inspect") == 2


def test_claimed_result_without_committed_event_is_not_acknowledged(configured, capsys):
    gmail = Gmail(configured.mailbox, [mail(configured)])
    app = runtime(configured, gmail)
    app.initialize()
    app.processor = lambda event: ProcessResult("SUCCESS", "REFILL")
    status, result = app.handle_push("Bearer token", push(configured))
    assert status == 503 and result["error_class"] == "event_not_durably_completed"
    assert app.cursor() == "10"
    log = capsys.readouterr().out
    assert "SUCCESS" not in log
    assert "FAILED → event_not_durably_completed" in log


def test_concurrent_transport_cannot_advance_cursor_or_start_provider(configured):
    gmail = Gmail(configured.mailbox, [mail(configured)])
    app = runtime(configured, gmail)
    app.initialize()
    other = runtime(configured, gmail)
    with app._transport_lock():
        status, result = other.handle_push("Bearer token", push(configured))
    assert status == 503 and result["error_class"] == "mail_transport_busy"
    assert gmail.reads == 0
    assert app.cursor() == "10"


def test_existing_mailbox_cannot_silently_change_account(configured):
    gmail = Gmail(configured.mailbox)
    runtime(configured, gmail).initialize()
    changed = runtime(replace(configured, account="other"), gmail)
    with pytest.raises(RuntimeErrorClass, match="mailbox_account_mapping_changed"):
        changed.poll_once()


def test_watch_renewal_never_advances_cursor_or_contacts_provider(configured):
    gmail, calls = Gmail(configured.mailbox), []
    app = runtime(configured, gmail, calls)
    app.initialize()
    assert app.renew_watch() == {"watch_registered": True}
    assert app.cursor() == "10"
    assert gmail.watches == 1 and gmail.reads == 0 and calls == []


def test_expired_history_does_not_reset_cursor_or_invent_replay(configured):
    from lite.mail import HistoryExpired
    gmail = Gmail(configured.mailbox)
    app = runtime(configured, gmail)
    app.initialize()
    def expired(*args):
        raise HistoryExpired("gmail_history_expired")
    gmail.events_since = expired
    status, result = app.handle_push("Bearer token", push(configured))
    assert status == 503 and result["error_class"] == "gmail_history_expired"
    assert app.cursor() == "10"


def test_no_events_and_idle_mail_poll_never_contact_provider(configured, capsys):
    gmail, calls = Gmail(configured.mailbox), []
    app = runtime(configured, gmail, calls)
    app.initialize()
    assert app.poll_once() == {"events": 0, "duplicate": False}
    assert calls == [] and gmail.reads == 1
    assert capsys.readouterr().out == ""


def test_cursor_does_not_advance_beyond_known_gmail_history(configured):
    gmail = Gmail(configured.mailbox, [mail(configured)], cursor="19")
    app = runtime(configured, gmail)
    app.initialize()
    status, result = app.handle_push("Bearer token", push(configured, "20"))
    assert status == 503 and result["error_class"] == "gmail_history_not_caught_up"
    assert app.cursor() == "10"


def test_untrusted_exception_messages_are_never_logged():
    assert classified(ValueError("secret-token"), "fallback") == "fallback"


def test_cli_rejects_provider_polling_frequency(configured, monkeypatch, capsys):
    from lite import cli
    monkeypatch.setattr(cli.RuntimeConfig, "from_env", lambda: configured)
    monkeypatch.setattr(cli, "_mail_runtime", lambda _: runtime(configured, Gmail(configured.mailbox)))
    assert cli.main(["mailbox-poll", "--interval", "5"]) == 1
    assert json.loads(capsys.readouterr().out)["error_class"] == "mail_poll_interval_must_be_at_least_60_seconds"


def test_cli_local_json_cannot_trigger_live_booking(configured, monkeypatch, capsys):
    from lite import cli
    monkeypatch.setattr(cli.RuntimeConfig, "from_env", lambda: replace(configured, dry_run=False))
    def forbidden(*args):
        pytest.fail("Synthetic event must not reach provider in live mode")
    monkeypatch.setattr(cli, "process_event", forbidden)
    assert cli.main(["event", "--event-file", "/does-not-exist.json"]) == 1
    assert json.loads(capsys.readouterr().out)["error_class"] == "local_event_requires_dry_run"


@pytest.mark.parametrize("results,pending,expected_clear", [
    ([], [], True),
    ([ProcessResult("UNKNOWN", "RECONCILED", error_class="provider_history_unverified")], [object()], False),
    ([ProcessResult("BUSY", "RETRY", error_class="ACCOUNT_BUSY")], [], False),
    ([ProcessResult("BLOCKED", "PROVIDER_CHECK_REQUIRED")], [], False),
    ([ProcessResult("FAILED", "PROVIDER_CHECK_REQUIRED")], [], False),
    ([ProcessResult("FAILED", "RECONCILED")], [], True),
])
def test_cli_recovery_reports_uncertainty_without_processing_new_event(configured, monkeypatch, capsys,
                                                                     results, pending, expected_clear):
    from lite import cli, engine
    calls = []
    class Store:
        def get_unresolved_recharges(self, provider, account):
            assert provider == "aldi_talk" and account == configured.account
            return pending
    class RecoveryEngine:
        PROVIDER = "aldi_talk"
        def __init__(self, *args, **kwargs):
            self.store = Store()
        def recover_pending(self):
            calls.append("recover")
            return results
        def process(self, *args):
            pytest.fail("Recovery must not process or fabricate a mail event")
    monkeypatch.setattr(cli.RuntimeConfig, "from_env", lambda: configured)
    monkeypatch.setattr(engine, "Engine", RecoveryEngine)
    assert cli.main(["recover"]) == (0 if expected_clear else 1)
    output = json.loads(capsys.readouterr().out)
    assert output["recovery_clear"] is expected_clear
    assert output["remaining_unresolved"] == len(pending)
    assert calls == ["recover"]
    assert configured.mailbox not in json.dumps(output)


def test_real_mail_processing_logs_classification_without_event_identity(configured, capsys):
    event = mail(configured, "private-mail-id")
    app = runtime(configured, Gmail(configured.mailbox, [event]))
    app.initialize()
    assert app.handle_push("Bearer private-oauth-token", push(configured))[0] == 200
    line = capsys.readouterr().out
    assert "MAIL → CHECK → NO_ACTION" in line
    for private in (configured.mailbox, configured.account, event.event_id, event.mail_id, "private-oauth-token"):
        assert private not in line


def test_refill_unknown_log_uses_utc_time_and_only_classified_fields(capsys):
    log_event_result(ProcessResult("UNKNOWN", "REFILL", "private-recharge-id",
                                  "provider_check_required"), timestamp=0)
    assert capsys.readouterr().out == "00:00 MAIL → CHECK → REFILL → UNKNOWN → provider_check_required\n"


def test_log_rejects_untrusted_status_action_and_exception_message(capsys):
    log_event_result(ProcessResult("mailbox@example.com", "password=private", "private-recharge-id",
                                  "Bearer private-token\nupstream body"), timestamp=0)
    assert capsys.readouterr().out == "00:00 MAIL → INVALID_RESULT → INVALID_RESULT → UNCLASSIFIED_ERROR\n"


def test_broken_log_pipe_does_not_fail_committed_event(monkeypatch):
    def broken_print(*args, **kwargs):
        raise BrokenPipeError("pipe unavailable")
    monkeypatch.setattr("builtins.print", broken_print)
    log_event_result(ProcessResult("SUCCESS", "REFILL"), timestamp=0)


@pytest.mark.parametrize("failure,expected_code", [
    (None, None),
    ("classified", "credentials_missing"),
    ("untrusted", "login_probe_failed"),
    ("unconfirmed", "login_not_confirmed"),
])
def test_login_probe_works_before_mailbox_setup_and_never_books(monkeypatch, capsys,
                                                             failure, expected_code):
    from lite import cli, portal
    calls = []
    for key in ("ALDI_MAILBOX", "ALDI_ACCOUNT_ALIAS", "GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    def unrelated_config():
        pytest.fail("Read-only login probe must not validate mailbox/live runtime configuration")
    monkeypatch.setattr(cli.RuntimeConfig, "from_env", unrelated_config)
    class Config:
        def configured(self):
            return False
    class LoginOnlyPortal:
        config = Config()
        def login(self):
            calls.append("login")
            if failure == "classified":
                raise portal.PortalError("credentials_missing")
            if failure == "untrusted":
                raise ValueError("password=private-token; mailbox@example.com")
        def _session(self):
            return failure != "unconfirmed"
        def close(self):
            calls.append("close")
        def inspect(self):
            pytest.fail("Login probe must not inspect a productive refill")
        def book(self, *args):
            pytest.fail("Login probe must never book")
    monkeypatch.setattr(portal, "AldiPortal", LoginOnlyPortal)
    assert cli.main(["login-probe"]) == (0 if failure is None else 1)
    output = json.loads(capsys.readouterr().out)
    assert output["login_confirmed"] is (failure is None)
    assert output.get("error_class") == expected_code
    assert calls == ["login", "close"]
    assert "private-token" not in json.dumps(output)
    assert "mailbox@example.com" not in json.dumps(output)
