import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

import lidl_observe as observe


@pytest.mark.parametrize("text,mb", [
    ("Restvolumen: 2.024 MB", 2024), ("Noch 2,024 GB verfügbar", 2024),
    ("0 MB verbleibend", 0), ("Verfügbar: 512,5 MB", 512.5),
])
def test_explicit_remaining_volume(text, mb):
    result = observe.parse_remaining(text)
    assert result["remaining_mb"] == mb
    assert result["remaining_gb"] == mb / 1000


@pytest.mark.parametrize("text", ["2024 MB", "2 GB von 50 GB", "Verbraucht: 2 GB",
                                      "Restvolumen: -1 MB", "Noch NaN GB", "Noch 1 GB und 5 GB"])
def test_used_total_ambiguous_and_invalid_tiles_are_not_remaining(text):
    with pytest.raises(observe.Blocked):
        observe.parse_remaining(text)


def test_exact_account_verification_does_not_accept_login_or_suffix_only():
    target = "015123456789"
    observe.verify_account("Rufnummer: +49 151 23456789", target)
    for text in ("Login erfolgreich", "Rufnummer: ***6789", "015198765432",
                 "015123456789 und 015198765432"):
        with pytest.raises(observe.Blocked):
            observe.verify_account(text, target)


def test_missing_configuration_never_opens_browser(monkeypatch):
    monkeypatch.setattr(observe, "get_credential", lambda name: None)
    for name in ["LIDL_EXPECTED_MSISDN", *observe.SELECTORS.values()]:
        monkeypatch.delenv(name, raising=False)
    reader = AsyncMock()
    result = asyncio.run(observe.observe(reader))
    assert result["status"] == "BLOCKED"
    assert result["remaining_gb"] is None
    assert "LIDL_USER" in result["missing"]
    assert not result["booking_enabled"] and not result["booking_performed"]
    reader.assert_not_awaited()


def configured(monkeypatch):
    monkeypatch.setattr(observe, "configuration", lambda: (("private", "private", "015123456789", {}), []))


def page_fixture(enabled=True, offer="Unlimited Refill 1 GB kostenlos"):
    def element(text):
        node = MagicMock()
        node.count = AsyncMock(return_value=1)
        node.is_visible = AsyncMock(return_value=True)
        node.inner_text = AsyncMock(return_value=text)
        node.click = AsyncMock(side_effect=AssertionError("No provider clicks allowed"))
        return node
    nodes = {"account": element("Rufnummer: 015123456789"),
             "remaining": element("Restvolumen: 2.024 MB"),
             "tariff": element("Unlimited on Demand M"), "offer": element(offer),
             "button": element("Nachbuchen")}
    nodes["button"].is_enabled = AsyncMock(return_value=enabled)
    nodes["button"].get_attribute = AsyncMock(return_value=None)
    nodes["offer"].locator.return_value = nodes["button"]
    password = element("")
    password.is_visible = AsyncMock(return_value=False)
    page = MagicMock(url=observe.PORTAL)
    page.locator.side_effect = lambda selector: password if selector == "input[type='password']" else nodes[selector]
    return page, nodes


@pytest.mark.parametrize("enabled,offer,available,notice", [
    (True, "Unlimited Refill 1 GB kostenlos", True, True),
    (False, "Unlimited Refill 1 GB kostenlos", False, False),
    (True, "Unlimited Refill 1 GB 2,99 EUR", False, False),
    (True, "Unlimited Refill 1 GB", False, False),
])
def test_notice_requires_exact_free_enabled_offer_and_never_clicks(enabled, offer, available, notice):
    page, nodes = page_fixture(enabled, offer)
    result = asyncio.run(observe.inspect_page(page, "015123456789", {key: key for key in observe.SELECTORS}))
    assert result["remaining_gb"] == 2.024
    assert result["refill_available"] is available
    assert bool(result["notice"]) is notice
    for node in nodes.values():
        node.click.assert_not_awaited()



@pytest.mark.parametrize("remaining,expected", [
    ("1 GB", False), ("1,00 GB", False), ("0,99 GB", True),
    ("1.024 MB", False), ("1023 MB", True), ("1.000 MB", True),
    ("2 GB", False),
])
def test_manual_handoff_only_below_one_gb_with_verified_free_button(remaining, expected):
    page, nodes = page_fixture()
    nodes["remaining"].inner_text.return_value = f"Restvolumen: {remaining}"
    result = asyncio.run(observe.inspect_page(
        page, "015123456789", {key: key for key in observe.SELECTORS}))
    assert result["refill_available"] is True
    assert result["below_one_gb"] is expected
    assert result["manual_refill_ready"] is expected
    assert result["manual_refill_url"] == (observe.PORTAL if expected else None)
    for node in nodes.values():
        node.click.assert_not_awaited()


@pytest.mark.parametrize("enabled,offer", [
    (False, "Unlimited Refill 1 GB kostenlos"),
    (True, "Unlimited Refill 1 GB 3,99 EUR"),
    (True, "Unlimited Refill 1 GB"),
])
def test_manual_handoff_blocks_disabled_paid_and_unpriced_offers(enabled, offer):
    page, nodes = page_fixture(enabled=enabled, offer=offer)
    nodes["remaining"].inner_text.return_value = "Restvolumen: 200 MB"
    result = asyncio.run(observe.inspect_page(
        page, "015123456789", {key: key for key in observe.SELECTORS}))
    assert result["manual_refill_ready"] is False
    assert result["manual_refill_url"] is None
    for node in nodes.values():
        node.click.assert_not_awaited()



def test_wrong_account_never_exposes_any_volume():
    page, nodes = page_fixture()
    with pytest.raises(observe.Blocked):
        asyncio.run(observe.inspect_page(page, "015198765432", {key: key for key in observe.SELECTORS}))
    nodes["remaining"].inner_text.assert_not_awaited()


def test_raw_provider_failure_is_not_logged(monkeypatch):
    configured(monkeypatch)
    secret = "password cookie private phone"
    result = asyncio.run(observe.observe(AsyncMock(side_effect=RuntimeError(secret))))
    assert secret not in json.dumps(result)
    assert result["reason"] == "account_read_failed"
    assert result["remaining_gb"] is None


def test_workflow_only_observes_with_read_permissions():
    workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/lidl-observe.yml").read_text()
    assert "contents: read" in workflow
    assert "AUTO_BOOK_ENABLED: 'false'" in workflow
    assert "cron: '17 * * * *'" in workflow
    assert "python lidl_observe.py" in workflow
    assert "main.py" not in workflow and "free-1gb" not in workflow
    assert "pull_request_target" not in workflow

def test_preflight_writes_non_observation_and_does_not_read_account(monkeypatch, tmp_path, capsys):
    configured(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert observe.main(["--preflight"]) == 0
    report = json.loads((tmp_path / "lidl-observation.json").read_text())
    assert report["status"] == "PREFLIGHT_OK"
    assert report["observed_at"] is None
    assert report["remaining_mb"] is None
    assert report["account_verified"] is False
    assert report["booking_performed"] is False
    assert "private" not in capsys.readouterr().out


def test_preflight_missing_config_is_failure_and_preserves_report(monkeypatch, tmp_path):
    monkeypatch.setattr(observe, "configuration", lambda: (None, ["LIDL_EXPECTED_MSISDN"]))
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert observe.main(["--preflight"]) == 2
    report = json.loads((tmp_path / "lidl-observation.json").read_text())
    assert report["status"] == "BLOCKED"
    assert report["reason"] == "configuration_missing"
    assert report["missing"] == ["LIDL_EXPECTED_MSISDN"]
    assert report["observed_at"] is None


def test_workflow_preflights_before_browser_install():
    workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/lidl-observe.yml").read_text()
    assert workflow.index("python lidl_observe.py --preflight") < workflow.index("python -m playwright install")
    assert workflow.index("python -m playwright install") < workflow.index("run: python lidl_observe.py\n")
    assert "if: always()" in workflow
