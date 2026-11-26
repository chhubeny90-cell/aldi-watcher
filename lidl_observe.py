"""One read-only Lidl account inspection. This entrypoint cannot book data."""

import argparse
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from core.credentials import get_credential
from core.lidl_refill import assess_refill


PORTAL = "https://kundenkonto.lidl-connect.de/mein-lidl-connect.html"
SELECTORS = {
    "account": "LIDL_ACCOUNT_SELECTOR",
    "remaining": "LIDL_REMAINING_SELECTOR",
    "tariff": "LIDL_ACTIVE_TARIFF_SELECTOR",
    "offer": "LIDL_REFILL_OFFER_SELECTOR",
    "button": "LIDL_REFILL_BUTTON_SELECTOR",
}


class Blocked(Exception):
    """Only fixed, non-personal reason codes may leave this module."""


def normalize_phone(value):
    if not isinstance(value, str) or re.search(r"[^\d+\s()/.-]", value):
        raise Blocked("target_invalid")
    digits = re.sub(r"\D", "", value)
    if digits.startswith("0049"):
        digits = "0" + digits[4:]
    elif digits.startswith("49"):
        digits = "0" + digits[2:]
    if not re.fullmatch(r"01\d{9,10}", digits):
        raise Blocked("target_invalid")
    return digits


def verify_account(text, expected):
    matches = re.findall(r"(?<![\d+])(?:\+49|0049|0)\s*1(?:[\s()/.-]*\d){8,11}(?!\d)", text)
    try:
        numbers = [normalize_phone(match) for match in matches]
    except Blocked:
        raise Blocked("account_unverified") from None
    if numbers != [expected]:
        raise Blocked("account_mismatch_or_ambiguous")


def parse_remaining(text):
    """Accept only explicitly labelled remaining volume, never a used/total tile."""
    text = " ".join(text.split())
    match = re.fullmatch(
        r"(?:(?:Restvolumen|Verbleibend|Verfügbar|Noch verfügbar|Noch)\s*:?\s*)?"
        r"(?P<value>(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d+)?)\s*(?P<unit>GB|MB)"
        r"(?:\s*(?:verbleibend|verfügbar|übrig|Restvolumen))?", text, re.I,
    )
    if not match or not re.search(r"Restvolumen|Verbleibend|Verfügbar|Noch|übrig", text, re.I):
        raise Blocked("remaining_volume_unverified")
    amount = Decimal(match["value"].replace(".", "").replace(",", "."))
    mb = amount * (1000 if match["unit"].upper() == "GB" else 1)
    # Compare in the displayed unit: exactly 1 GB must NOT pass the strict
    # below-1-GB gate, regardless of decimal display conversion.
    below_one_gb = amount < (Decimal("1") if match["unit"].upper() == "GB" else Decimal("1024"))
    return {"remaining_mb": float(mb), "remaining_gb": float(mb / 1000),
            "below_one_gb": bool(below_one_gb)}


def configuration():
    # An independent protected target is required; the login alone is not identity evidence.
    user, password = get_credential("LIDL_USER"), get_credential("LIDL_PASS")
    target = os.getenv("LIDL_EXPECTED_MSISDN", "").strip()
    selectors = {key: os.getenv(name, "").strip() for key, name in SELECTORS.items()}
    missing = [name for name, value in (("LIDL_USER", user), ("LIDL_PASS", password),
               ("LIDL_EXPECTED_MSISDN", target)) if not value]
    missing += [SELECTORS[key] for key in ("account", "remaining", "tariff") if not selectors[key]]
    if missing:
        return None, missing
    return (user, password, normalize_phone(target), selectors), []


def require_origin(page):
    url = urlsplit(page.url)
    if url.scheme != "https" or url.hostname != "kundenkonto.lidl-connect.de":
        raise Blocked("unexpected_origin")


async def unique(root, selector):
    element = root.locator(selector)
    if await element.count() != 1 or not await element.is_visible():
        raise Blocked("element_missing_hidden_or_ambiguous")
    return element


async def inspect_page(page, target, selectors):
    require_origin(page)
    if await page.locator("input[type='password']").is_visible():
        raise Blocked("session_unverified")
    account = await unique(page, selectors["account"])
    verify_account(await account.inner_text(), target)
    remaining = await unique(page, selectors["remaining"])
    volume = parse_remaining(await remaining.inner_text())
    tariff = await unique(page, selectors["tariff"])
    tariff_text = " ".join((await tariff.inner_text()).split())
    valid_tariff = bool(re.fullmatch(r"(?:LIDL Connect )?Unlimited on Demand [SML]", tariff_text, re.I))
    report = {
        "status": "OBSERVING", "account_verified": True, **volume,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "active_tariff": tariff_text.upper() if valid_tariff else None,
        "refill_available": None, "refill_reason": "offer_selectors_unconfigured",
        "notice": None, "manual_refill_ready": False, "manual_refill_url": None,
    }
    if not valid_tariff:
        report["refill_reason"] = "active_tariff_unverified"
        return report
    if not selectors["offer"] or not selectors["button"]:
        return report
    try:
        offer = await unique(page, selectors["offer"])
        button = await unique(offer, selectors["button"])
        enabled = (await button.is_enabled() and
                   await button.get_attribute("aria-disabled") != "true" and
                   await button.get_attribute("disabled") is None)
        evidence = assess_refill(tariff_text, await offer.inner_text(), await button.inner_text(), enabled)
        report["refill_available"] = evidence["refill_eligible"]
        report["refill_reason"] = evidence["refill_reason"]
        if evidence["refill_eligible"]:
            report["notice"] = "Kostenlose 1-GB-Nachbuchung ist jetzt verfügbar. Es wurde nichts gebucht."
            if volume["below_one_gb"]:
                # Provide only a user-operated handoff. No browser click or
                # background refill: LIDL Connect declined automatic booking.
                report["manual_refill_ready"] = True
                report["manual_refill_url"] = PORTAL
    except Blocked:
        report["refill_reason"] = "offer_not_visible_or_ambiguous"
    return report


async def read_account(config):
    from playwright.async_api import async_playwright
    user, password, target, selectors = config
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            page.set_default_timeout(15000)
            response = await page.goto(PORTAL, wait_until="domcontentloaded", timeout=30000)
            require_origin(page)
            if not response or response.status >= 400:
                raise Blocked("portal_access_blocked")
            username = await unique(page, "input[type='tel']")
            password_field = await unique(page, "input[type='password']")
            submit = await unique(page, "button[type='submit']")
            await username.fill(user)
            await password_field.fill(password)
            # The only click in this module submits the login. No booking controls are clicked.
            await submit.click()
            await page.locator(selectors["account"]).wait_for(state="visible", timeout=30000)
            return await inspect_page(page, target, selectors)
        finally:
            await browser.close()


async def observe(reader=read_account):
    base = {"checked_at": datetime.now(timezone.utc).isoformat(), "booking_enabled": False,
            "booking_performed": False, "remaining_gb": None, "remaining_mb": None,
            "observed_at": None, "account_verified": False, "active_tariff": None,
            "refill_available": None, "manual_refill_ready": False,
            "manual_refill_url": None, "below_one_gb": None}
    try:
        config, missing = configuration()
        if missing:
            return {**base, "status": "BLOCKED", "reason": "configuration_missing", "missing": missing}
        return {**base, **await reader(config)}
    except Blocked as exc:
        return {**base, "status": "BLOCKED", "reason": str(exc)}
    except Exception:
        # Do not expose credentials, DOM, request URLs, exception messages, screenshots or cookies.
        return {**base, "status": "BLOCKED", "reason": "account_read_failed"}


async def configuration_only(_config):
    """No network or browser access; configuration is not account evidence."""
    return {"status": "PREFLIGHT_OK"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight", action="store_true",
                        help="Check configuration without opening a browser")
    args = parser.parse_args(argv)
    report = asyncio.run(observe(reader=configuration_only) if args.preflight else observe())
    output = json.dumps(report, ensure_ascii=False, sort_keys=True)
    Path("lidl-observation.json").write_text(output + "\n", encoding="utf-8")
    print(output)
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as stream:
            stream.write("## Lidl Connect: nur beobachten\n\n```json\n" + output + "\n```\n")
    return 2 if report["status"] == "BLOCKED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
