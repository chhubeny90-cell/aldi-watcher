"""Run isolated read-only checks for an encrypted ALDI account manifest."""
import json
import os
from core.aldi_accounts import load_accounts, require_selected_account, select_account
from monitoring import execute_provider, utcnow, write_report


def tariff_snapshot(driver):
    """Read booked products, never infer the active tariff from a SIM nickname."""
    from browser_dom import find_visible_elements, element_label, rendered_text
    from monitoring import require_origin
    from selenium.webdriver.support.ui import WebDriverWait
    import watcher
    require_origin(driver, watcher.ALDI_OVERVIEW_URL)
    controls = [control for control in find_visible_elements(driver, "button")
                if element_label(driver, control).strip() == "Buchungsübersicht"]
    if len(controls) != 1:
        return {"tariff_status": "unverified"}
    controls[0].click()
    def headings(_):
        require_origin(driver, watcher.ALDI_OVERVIEW_URL)
        return [rendered_text(driver, heading)
                for heading in find_visible_elements(driver, "h1,h2,h3,h4,h5,h6,[role='heading']")]
    import re
    def active_tariff(_):
        candidates = [text for text in headings(_) if
                      re.fullmatch(r"(?:Jahres[ -]*Paket|Basis[ -]*Tarif|Tarif|Unlimited)"
                                   r"(?:[ -]+(?:XS|S|M|L|Unlimited))*", text.strip(), re.I)]
        return candidates if candidates else False
    try:
        candidates = WebDriverWait(driver, watcher.WAIT_TIMEOUT).until(active_tariff)
    except Exception:
        return {"tariff_status": "unverified"}
    if len(candidates) != 1:
        return {"tariff_status": "ambiguous"}
    text = candidates[0].strip()
    # Output only fixed, nonpersonal product names.
    if re.fullmatch(r"Jahres[ -]*Paket(?:[ -]+(?:XS|S|M|L))?", text, re.I):
        return {"tariff_status": "annual", "booking_allowed": False}
    if re.fullmatch(r"Basis[ -]*Tarif", text, re.I):
        return {"tariff_status": "base", "booking_allowed": False}
    from core.aldi_refill import _eligible_tariff
    return {"tariff_status": "unlimited" if _eligible_tariff(text) else "unverified"}


def main():
    import watcher
    report = {"started_at": utcnow(), "booking_executed": False, "accounts": []}
    report_path = os.getenv("ALDI_ACCOUNTS_REPORT", "aldi-accounts-report.json")
    write_report(report_path, report)
    try:
        accounts = load_accounts()
    except ValueError:
        report["status"] = "configuration_error"
        write_report(report_path, report)
        print(json.dumps({"status": report["status"]}))
        return 3
    if os.getenv("AUTO_BOOK_ENABLED", "false").lower() != "false":
        report["status"] = "configuration_error"
        write_report(report_path, report)
        return 3
    failures = 0
    for account in accounts:
        if not account.enabled:
            report["accounts"].append({"account_id": account.account_id, "status": "disabled"})
            continue
        # Each execute_provider call creates and closes its own browser. No user
        # browser session or global secret/environment value is overwritten.
        def login(driver, profile=account):
            watcher.ALDI_ACCOUNT_USER = profile.account_user
            watcher.ALDI_USER = profile.login_user
            watcher.ALDI_PASS = profile.password
            if not watcher.aldi_login(driver):
                return False
            select_account(driver, profile.account_user)
            require_selected_account(driver, profile.account_user)
            return True
        product = {}
        def read(driver, profile=account):
            require_selected_account(driver, profile.account_user)
            product.update(tariff_snapshot(driver))
            require_selected_account(driver, profile.account_user)
            status = watcher.aldi_read_status(driver)
            require_selected_account(driver, profile.account_user)
            if status.get("inland_frei_gb") is None:
                import re
                from browser_dom import rendered_text
                matches = re.findall(r"\bNoch\s*(\d+(?:[.,]\d+)?)\s*(GB|MB)\b",
                                     rendered_text(driver), re.I)
                values = {float(value.replace(",", ".")) / (1000 if unit.upper() == "MB" else 1)
                          for value, unit in matches}
                if len(values) == 1:
                    status["inland_frei_gb"] = values.pop()
                    from core.aldi_refill import inspect_selenium
                    status.update(inspect_selenium(driver, status["inland_frei_gb"]))
            return status
        try:
            result = execute_provider("aldi_talk", watcher.build_driver, login, read,
                                      utcnow() + "-" + account.account_id)
        finally:
            watcher.ALDI_ACCOUNT_USER = ""
            watcher.ALDI_USER = ""
            watcher.ALDI_PASS = ""
        result.update(account_id=account.account_id, requested_policy=account.policy,
                      booking_executed=False, **product)
        if result.get("status") != "ok":
            failures += 1
        report["accounts"].append(result)
        write_report(report_path, report)
        print(json.dumps(result, ensure_ascii=False))
    report["status"] = "failed" if failures else ("checked" if any(a.enabled for a in accounts) else "not_configured")
    report["finished_at"] = utcnow()
    write_report(report_path, report)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
