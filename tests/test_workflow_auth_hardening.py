from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def _workflow(name):
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def test_authenticated_account_workflow_remains_disabled():
    text = _workflow("accounts.yml")
    assert "ALDI Accounts (disabled)" in text
    assert "Authenticated ALDI account automation is disabled." in text
    assert "ALDI_ACCOUNTS_ENC" not in text
    assert "ALDI_PASS" not in text
    assert "Install Chrome" not in text


def test_mail_monitor_does_not_receive_provider_password():
    text = _workflow("mail-trigger.yml")

    assert "ALDI_RECOVERY_KEY: ${{ secrets.ALDI_RECOVERY_KEY }}" in text
    assert "ALDI_PASS: ${{ secrets.ALDI_PASS }}" not in text
    assert "ALDI_PASS_ENC: ${{ secrets.ALDI_PASS_ENC }}" not in text
    assert "ALDI_USER:" not in text
    assert "usage_mail_notify.py" in text
    assert "repository_dispatch" not in text


def test_main_workflow_has_no_authenticated_live_refill():
    text = _workflow("run.yml")

    assert "github_live_refill_http.py" not in text
    assert "github_live_refill.py" not in text
    assert "ALDI_MANUAL_AUTH_ONCE" not in text
    assert "ALDI_EXPECTED_ACCOUNT" not in text
    assert "ALDI_PASS:" not in text
    assert "AUTO_BOOK_ENABLED: 'false'" in text
    assert "portal_probe.py" in text


def test_policy_safe_24_7_workflow_cadence_is_preserved():
    assert "cron: '0 * * * *'" in _workflow("mail-trigger.yml")
    assert "cron: '7-59/15 * * * *'" in _workflow("run.yml")
    assert "schedule:" not in _workflow("watchdog.yml")
    assert "schedule:" not in _workflow("accounts.yml")


def test_24_7_active_workflows_use_node24_compatible_action_generations():
    for name in ("run.yml", "mail-trigger.yml"):
        text = _workflow(name)
        assert "actions/checkout@v4" not in text
        assert "actions/setup-python@v5" not in text
        assert "browser-actions/setup-chrome@v1" not in text
        assert "actions/upload-artifact@v4" not in text

    run = _workflow("run.yml")
    mail = _workflow("mail-trigger.yml")
    assert "actions/checkout@v7.0.1" in run
    assert "actions/setup-python@v7.0.0" in run
    assert "browser-actions/setup-chrome@v2.2.0" in run
    assert "actions/upload-artifact@v7.0.2" in run
    assert "actions/checkout@v7.0.1" in mail
    assert "actions/setup-python@v7.0.0" in mail
    assert "actions/upload-artifact@v7.0.2" in mail


def test_disabled_workflows_have_no_provider_credentials_or_browser_runtime():
    for name in ("accounts.yml", "status-probe.yml", "watchdog.yml"):
        text = _workflow(name)
        assert "ALDI_PASS" not in text
        assert "ALDI_USER" not in text
        assert "browser-actions/setup-chrome" not in text


def test_login_diagnostics_default_to_public_controls_without_push_trigger():
    text = _workflow("login-format.yml")
    triggers = text.split("\npermissions:", 1)[0]
    assert "  push:" not in triggers
    assert "        required: true" in triggers
    assert "        type: choice" in triggers
    assert "        default: public_controls" in triggers
    public_job = text.split("\n  public_controls:\n", 1)[1]
    assert "secrets." not in public_job
    assert "python aldi_public_login_controls.py" in public_job


def test_manual_diagnostic_selection_never_fans_out_into_other_jobs():
    text = _workflow("login-format.yml")
    options = re.findall(r"^          - (\w+)$", text, re.MULTILINE)
    jobs = re.findall(r"^  (\w+):\n    if: (.+)$", text, re.MULTILINE)
    assert len(options) == len(jobs) == 7
    assert set(options) == {name for name, _ in jobs}
    # Evaluate the restricted conditions for each UI choice and an invalid input.
    # An unconditional dispatch condition would start every sensitive probe.
    for event in ("workflow_dispatch", "push"):
        for selected in [*options, "", "invalid"]:
            active = []
            for name, condition in jobs:
                expression = condition.replace("github.event_name", repr(event))
                expression = expression.replace("inputs.diagnostic", repr(selected))
                expression = expression.replace("&&", " and ").replace("||", " or ")
                assert re.fullmatch(r"[\w\s'!=()]+", expression)
                if eval(expression, {"__builtins__": {}}, {}):
                    active.append(name)
            expected = [selected] if event == "workflow_dispatch" and selected in options else []
            assert active == expected
