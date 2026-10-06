import pytest
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
    monkeypatch, statuses, expected_exit_code
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
