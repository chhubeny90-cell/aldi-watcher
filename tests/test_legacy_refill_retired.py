import json
from pathlib import Path
from unittest.mock import Mock

import simple_free_1gb
import watcher


def test_legacy_runner_cannot_read_credentials_or_start_browser(monkeypatch, capsys):
    credentials = Mock(side_effect=AssertionError("credentials accessed"))
    browser = Mock(side_effect=AssertionError("browser started"))
    monkeypatch.setattr(watcher, "configure_credentials", credentials)
    monkeypatch.setattr(watcher, "build_driver", browser)
    monkeypatch.setenv("AUTO_BOOK_ENABLED", "true")
    assert simple_free_1gb.main() == 3
    report = json.loads(capsys.readouterr().out)
    assert report["provider_action"] is False
    assert report["outcome"] == "legacy_refill_disabled"
    credentials.assert_not_called()
    browser.assert_not_called()


def test_legacy_workflow_cannot_schedule_or_inject_credentials():
    workflow = Path(".github/workflows/free-1gb.yml").read_text()
    assert "schedule:" not in workflow
    assert "secrets." not in workflow
    assert "python simple_free_1gb.py" not in workflow
    assert "exit 3" in workflow
