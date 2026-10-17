import pytest
from core.aldi_target import require_refill_target


@pytest.mark.parametrize("expected", ["01630001869", "+49 163 0001869", "00491630001869"])
def test_target_accepts_equivalent_full_numbers(expected):
    require_refill_target("01630001869", expected, "1869")


@pytest.mark.parametrize("suffix", ["2640", "2626"])
def test_linked_non_target_accounts_are_rejected(suffix):
    number = "0163000" + suffix
    with pytest.raises(ValueError, match="^target_profile_mismatch$"):
        require_refill_target(number, number, "1869")


def test_matching_suffix_does_not_replace_full_identity_check():
    with pytest.raises(ValueError, match="^target_account_mismatch$"):
        require_refill_target("01630001869", "01740001869", "1869")


@pytest.mark.parametrize("expected, suffix, error", [
    ("", "1869", "expected_target_missing"),
    ("invalid", "1869", "target_account_invalid"),
    ("01630001869", "", "target_suffix_invalid"),
    ("01630001869", ".*", "target_suffix_invalid"),
])
def test_invalid_configuration_fails_closed(expected, suffix, error):
    with pytest.raises(ValueError, match="^" + error + "$"):
        require_refill_target("01630001869", expected, suffix)


@pytest.mark.parametrize("account, expected", [
    ("01630002640", "01630002640"),
    ("01630002626", "01630002626"),
    ("01630001869", ""),
    ("01630001869", "01740001869"),
])
def test_invalid_deployment_stops_before_journal_and_browser(monkeypatch, tmp_path, account, expected):
    import json
    from unittest.mock import Mock
    import aldi_live_refill as live
    monkeypatch.setenv("AUTO_BOOK_ENABLED", "true")
    monkeypatch.setenv("ALDI_REQUIRED_TARGET_SUFFIX", "1869")
    monkeypatch.setenv("ALDI_EXPECTED_ACCOUNT", expected)
    monkeypatch.setattr(live.watcher, "configure_credentials", lambda _: True)
    monkeypatch.setattr(live.watcher, "ALDI_ACCOUNT_USER", account)
    monkeypatch.setattr(live, "REPORT_PATH", str(tmp_path / "report.json"))
    journal = Mock(side_effect=AssertionError("journal must not open"))
    browser = Mock(side_effect=AssertionError("browser must not start"))
    monkeypatch.setattr(live, "open_live_journal", journal)
    monkeypatch.setattr(live.watcher, "build_driver", browser)
    assert live.main() == 2
    journal.assert_not_called()
    browser.assert_not_called()
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["booking_clicks"] == 0
    assert report["outcome"] in {"target_profile_mismatch", "expected_target_missing", "target_account_mismatch"}
    assert account not in (tmp_path / "report.json").read_text()
