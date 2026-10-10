"""Private multi-account ALDI monitoring. This module never books or changes tariffs."""
import json
import os
import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Account:
    account_id: str
    account_user: str = field(repr=False)
    login_user: str = field(repr=False)
    password: str = field(repr=False)
    enabled: bool = False
    policy: str = "monitor_only"


def normalise_number(value):
    if not isinstance(value, str):
        raise ValueError("invalid_account_number")
    compact = "".join(value.split())
    if compact.startswith("00"):
        compact = "+" + compact[2:]
    elif compact.startswith("0"):
        compact = "+49" + compact[1:]
    if not re.fullmatch(r"\+49[1-9][0-9]{8,12}", compact):
        raise ValueError("invalid_account_number")
    return compact


def validate_accounts(payload):
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError("invalid_account_manifest")
    raw = payload.get("accounts")
    if not isinstance(raw, list) or not 1 <= len(raw) <= 20:
        raise ValueError("invalid_account_manifest")
    result, ids, numbers = [], set(), set()
    for item in raw:
        if not isinstance(item, dict) or item.get("provider") != "aldi_talk":
            raise ValueError("unsupported_account_provider")
        account_id = item.get("account_id")
        if not isinstance(account_id, str) or not re.fullmatch(r"account_[a-z]", account_id):
            raise ValueError("invalid_account_id")
        number = normalise_number(item.get("account_user"))
        enabled = item.get("enabled", False)
        policy = item.get("policy", "monitor_only")
        if type(enabled) is not bool or policy not in {"monitor_only", "free_unlimited"}:
            raise ValueError("invalid_account_policy")
        password = item.get("password", "")
        login_user = item.get("login_user") or number
        if not isinstance(password, str) or not isinstance(login_user, str):
            raise ValueError("invalid_account_credentials")
        if enabled and not password:
            raise ValueError("missing_account_password")
        if account_id in ids or number in numbers:
            raise ValueError("duplicate_account")
        ids.add(account_id)
        numbers.add(number)
        result.append(Account(account_id, number, login_user, password, enabled, policy))
    return sorted(result, key=lambda item: item.account_user)


def load_accounts(environ=None):
    environ = os.environ if environ is None else environ
    token = environ.get("ALDI_ACCOUNTS_ENC", "")
    if not token:
        return []
    from core.security import SecurityManager
    try:
        payload = json.loads(SecurityManager().decrypt(token))
        return validate_accounts(payload)
    except Exception:
        raise ValueError("invalid_encrypted_account_manifest") from None


def number_from_label(label):
    match = re.match(r"^(\+?\d[\d ]*)", label.strip())
    if not match:
        return None
    try:
        return normalise_number(match.group(1))
    except ValueError:
        return None


def selected_account_control(driver):
    from browser_dom import find_visible_elements, element_label
    controls = [control for control in find_visible_elements(driver, "button")
                if number_from_label(element_label(driver, control)) is not None]
    # A closed account dropdown must expose exactly one selected SIM.
    return controls[0] if len(controls) == 1 else None


def require_selected_account(driver, expected):
    from browser_dom import element_label
    import watcher
    from monitoring import require_origin
    require_origin(driver, watcher.ALDI_OVERVIEW_URL)
    control = selected_account_control(driver)
    if (control is None or
            number_from_label(element_label(driver, control)) != normalise_number(expected)):
        raise PermissionError("account_identity_unverified")


def select_account(driver, expected):
    """Switch linked SIMs only, without logout, credential resubmission or account merging."""
    from browser_dom import find_visible_elements, element_label
    from selenium.webdriver.support.ui import WebDriverWait
    import watcher
    from monitoring import require_origin
    require_origin(driver, watcher.ALDI_OVERVIEW_URL)
    expected = normalise_number(expected)
    current = selected_account_control(driver)
    if current is None:
        raise PermissionError("account_identity_unverified")
    if number_from_label(element_label(driver, current)) == expected:
        return
    current.click()
    def target(_):
        require_origin(driver, watcher.ALDI_OVERVIEW_URL)
        matches = [control for control in find_visible_elements(driver, "button")
                   if number_from_label(element_label(driver, control)) == expected]
        return matches[0] if len(matches) == 1 and matches[0].is_enabled() else False
    candidate = WebDriverWait(driver, watcher.WAIT_TIMEOUT).until(target)
    candidate.click()
    def confirmed(_):
        require_selected_account(driver, expected)
        return True
    # Transitional DOM absence is retried; wrong/ambiguous identity is never accepted.
    def settled(_):
        try:
            return confirmed(_)
        except PermissionError:
            return False
    WebDriverWait(driver, watcher.WAIT_TIMEOUT).until(settled)
