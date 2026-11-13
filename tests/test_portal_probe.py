import pytest
from core.database import Database


@pytest.fixture(autouse=True)
def isolated_probe_database(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "probe.db"))
    monkeypatch.chdir(tmp_path)
    return tmp_path / "probe.db"

import portal_probe as probe


def test_probe_refuses_provider_credentials(monkeypatch):
    monkeypatch.setenv('ALDI_PASS', 'private')
    monkeypatch.setattr(probe, 'build_driver', lambda: pytest.fail('browser must not start'))
    with pytest.raises(RuntimeError, match='without provider credentials'):
        probe.main()


def test_console_classification_never_returns_raw_error():
    message = 'TypeError: PRIVATE password at https://example.invalid/?token=PRIVATE'
    assert probe.error_categories(message) == ['type_error']


def test_host_discards_credentials_path_query_and_fragment():
    assert probe.host('https://secret:password@example.invalid/account?token=PRIVATE#PRIVATE') == 'example.invalid'


@pytest.mark.parametrize(
    ("statuses", "expected_exit_code"),
    [
        (["complete", "complete"], 0),
        (["failed", "complete"], 1),
        (["complete", "failed"], 1),
    ],
)
def test_main_persists_report_and_returns_nonzero_for_incomplete_probe(
    monkeypatch, statuses, expected_exit_code, isolated_probe_database
):
    results = iter(
        {"provider": name, "status": status}
        for name, status in zip(("aldi_talk", "lidl_connect"), statuses)
    )
    monkeypatch.setattr(probe, "probe", lambda name, url: next(results))
    written = {}
    monkeypatch.setattr(
        probe,
        "write_report",
        lambda path, report: written.update(path=path, report=report),
    )

    assert probe.main() == expected_exit_code
    assert written["path"] == "portal-probe-report.json"
    assert [item["status"] for item in written["report"]["providers"]] == statuses
    rows = Database(str(isolated_probe_database)).get_recent_logs()
    assert len(rows) == statuses.count("failed")
    assert all(row.error_message == "public_probe_failed" for row in rows)


def test_browser_exception_is_persisted_without_sensitive_text(
    monkeypatch, isolated_probe_database
):
    def fail_browser():
        raise RuntimeError("PRIVATE password at https://example.invalid/?token=PRIVATE")

    monkeypatch.setattr(probe, "build_driver", fail_browser)
    assert probe.main() == 1
    rows = Database(str(isolated_probe_database)).get_recent_logs()
    assert {row.provider for row in rows} == {"aldi_talk", "lidl_connect"}
    assert all(row.username == "public_probe" for row in rows)
    assert all(row.error_message == "public_probe_failed" for row in rows)
    assert b"PRIVATE" not in isolated_probe_database.read_bytes()


def test_browser_diagnostics_and_cleanup_errors_are_persisted(
    isolated_probe_database,
):
    database = Database(str(isolated_probe_database))
    probe.record_probe_errors(database, {
        "provider": "lidl_connect",
        "status": "complete",
        "console_categories": ["type_error"],
        "resource_failures": [{"status": 403}],
        "cleanup_failed": True,
    })
    assert {row.error_message for row in database.get_recent_logs()} == {
        "public_probe_console_error",
        "public_probe_resource_error",
        "public_probe_cleanup_failed",
    }
