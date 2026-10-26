"""Synthetic account identifiers only: never use a real subscriber number here.

The intentionally zero-filled 0150 examples exercise parsing and identity
guards without recording any deployed SIM, suffix or mailbox identity.
"""
import pytest
from core.aldi_target import require_refill_target


TEST_PREFIX = "0150000"
TEST_SUFFIX = "4827"
TEST_ACCOUNT = TEST_PREFIX + TEST_SUFFIX
TEST_OTHER_PREFIX = "0151000"
TEST_OTHER_ACCOUNT = TEST_OTHER_PREFIX + TEST_SUFFIX


@pytest.mark.parametrize("expected", [
    TEST_ACCOUNT,
    "+49 150 000" + TEST_SUFFIX,
    "0049 150 000" + TEST_SUFFIX,
])
def test_target_accepts_equivalent_full_numbers(expected):
    require_refill_target(TEST_ACCOUNT, expected, TEST_SUFFIX)


@pytest.mark.parametrize("suffix", ["1425", "2468"])
def test_linked_non_target_accounts_are_rejected(suffix):
    number = TEST_PREFIX + suffix
    with pytest.raises(ValueError, match="^target_profile_mismatch$"):
        require_refill_target(number, number, TEST_SUFFIX)


def test_matching_suffix_does_not_replace_full_identity_check():
    with pytest.raises(ValueError, match="^target_account_mismatch$"):
        require_refill_target(TEST_ACCOUNT, TEST_OTHER_ACCOUNT, TEST_SUFFIX)


@pytest.mark.parametrize("expected, suffix, error", [
    ("", TEST_SUFFIX, "expected_target_missing"),
    ("invalid", TEST_SUFFIX, "target_account_invalid"),
    (TEST_ACCOUNT, "", "target_suffix_invalid"),
    (TEST_ACCOUNT, ".*", "target_suffix_invalid"),
])
def test_invalid_configuration_fails_closed(expected, suffix, error):
    with pytest.raises(ValueError, match="^" + error + "$"):
        require_refill_target(TEST_ACCOUNT, expected, suffix)


@pytest.mark.parametrize("account, expected", [
    (TEST_PREFIX + "1425", TEST_PREFIX + "1425"),
    (TEST_PREFIX + "2468", TEST_PREFIX + "2468"),
    (TEST_ACCOUNT, ""),
    (TEST_ACCOUNT, TEST_OTHER_ACCOUNT),
])
def test_invalid_deployment_stops_before_journal_and_browser(monkeypatch, tmp_path, account, expected):
    import json
    from unittest.mock import Mock
    import aldi_live_refill as live
    monkeypatch.setenv("AUTO_BOOK_ENABLED", "true")
    monkeypatch.setenv("ALDI_REQUIRED_TARGET_SUFFIX", TEST_SUFFIX)
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


@pytest.mark.parametrize("suffix,expected", [
    ("", TEST_ACCOUNT),
    (TEST_SUFFIX, ""),
    (TEST_SUFFIX, TEST_OTHER_ACCOUNT),
])
def test_missing_or_mismatched_target_blocks_before_journal_browser(monkeypatch, tmp_path, suffix, expected):
    import json
    from unittest.mock import Mock
    import aldi_live_refill as live
    monkeypatch.setenv("AUTO_BOOK_ENABLED", "true")
    monkeypatch.setenv("ALDI_REQUIRED_TARGET_SUFFIX", suffix)
    monkeypatch.setenv("ALDI_EXPECTED_ACCOUNT", expected)
    monkeypatch.setattr(live.watcher, "configure_credentials", lambda _: True)
    monkeypatch.setattr(live.watcher, "ALDI_ACCOUNT_USER", TEST_ACCOUNT)
    monkeypatch.setattr(live, "REPORT_PATH", str(tmp_path / "report.json"))
    journal = Mock(side_effect=AssertionError("journal must not open"))
    browser = Mock(side_effect=AssertionError("browser must not start"))
    monkeypatch.setattr(live, "open_live_journal", journal)
    monkeypatch.setattr(live.watcher, "build_driver", browser)
    assert live.main() == 2
    journal.assert_not_called()
    browser.assert_not_called()
    report_text = (tmp_path / "report.json").read_text()
    assert json.loads(report_text)["booking_clicks"] == 0
    assert TEST_ACCOUNT not in report_text
