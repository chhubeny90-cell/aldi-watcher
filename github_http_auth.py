"""Verified ALDI HTTP authentication handoff for the hosted live runner.

Credentials are submitted once through the provider's ForgeRock callback API.
Only first-party ALDI cookies from the verified requests session are copied into
Chrome memory. Cookie values, tokens and credentials are never logged or stored.
"""

import time

import watcher
from core.aldi_http_login import ALLOWED_HOSTS, AldiHttpLogin, LoginError


_LAST_AUTH_OUTCOME = None
_PORTAL_HOST = "www.alditalk-kundenportal.de"
_COOKIE_ORIGINS = {host: host for host in ALLOWED_HOSTS}
_COOKIE_ORIGINS.update({host.removeprefix("www."): host
                        for host in ALLOWED_HOSTS if host.startswith("www.")})


def _cookie_payload(cookie):
    name = getattr(cookie, "name", None)
    value = getattr(cookie, "value", None)
    raw_domain = getattr(cookie, "domain", "")
    if not isinstance(raw_domain, str):
        return None
    raw_domain = raw_domain.casefold()
    domain = raw_domain.removeprefix(".")
    domain_specified = bool(getattr(cookie, "domain_specified", False))
    path = getattr(cookie, "path", None) or "/"
    expires = getattr(cookie, "expires", None)

    if not isinstance(name, str) or not name or not isinstance(value, str):
        return None
    origin = _COOKIE_ORIGINS.get(domain)
    if origin is None:
        return None
    # Parent-domain cookies use a known child HTTPS origin. Host-only cookies
    # cannot be moved to that child because doing so changes their scope.
    if not domain_specified and (domain != origin or raw_domain.startswith(".")):
        return None
    if not isinstance(path, str) or not path.startswith("/"):
        path = "/"
    if isinstance(expires, (int, float)) and expires <= time.time():
        return None

    payload = {
        "name": name,
        "value": value,
        "url": f"https://{origin}{path}",
        "path": path,
        "secure": bool(getattr(cookie, "secure", False)),
    }
    if domain_specified:
        payload["domain"] = raw_domain
    if isinstance(expires, (int, float)):
        payload["expires"] = float(expires)

    rest = getattr(cookie, "_rest", {}) or {}
    if isinstance(rest, dict):
        if "HttpOnly" in rest:
            payload["httpOnly"] = True
        same_site = rest.get("SameSite") or rest.get("samesite")
        if isinstance(same_site, str) and same_site.capitalize() in {"Strict", "Lax", "None"}:
            payload["sameSite"] = same_site.capitalize()
    return payload


def inject_verified_cookies(driver, cookie_jar):
    """Copy only trusted ALDI cookies into Chrome and require a portal cookie."""
    driver.execute_cdp_cmd("Network.enable", {})
    injected = 0
    portal = 0
    for cookie in cookie_jar:
        payload = _cookie_payload(cookie)
        if payload is None:
            continue
        result = driver.execute_cdp_cmd("Network.setCookie", payload)
        if not isinstance(result, dict) or result.get("success") is not True:
            raise LoginError("selenium_cookie_injection_failed")
        injected += 1
        if payload["url"].startswith(f"https://{_PORTAL_HOST}/"):
            portal += 1
    if injected == 0 or portal == 0:
        raise LoginError("portal_session_cookie_missing")
    return injected


def _fixed_outcome(code, report):
    provider = report.get("provider_indications") if isinstance(report, dict) else None
    provider = provider if isinstance(provider, dict) else {}
    if code == "account_locked" or provider.get("account_locked") is True:
        return "account_locked"
    if provider.get("maintenance") is True:
        return "provider_maintenance"
    return "auth_failed"


def last_auth_outcome():
    return _LAST_AUTH_OUTCOME


def login_with_http_session(driver):
    """Authenticate once via HTTP, hand verified session cookies to Chrome."""
    global _LAST_AUTH_OUTCOME
    _LAST_AUTH_OUTCOME = None
    client = AldiHttpLogin()
    try:
        client.login(watcher.ALDI_USER, watcher.ALDI_PASS)
        inject_verified_cookies(driver, client.session.cookies)
        watcher.navigate(driver, watcher.ALDI_OVERVIEW_URL, attempts=2)
        if not watcher.aldi_session_visible(driver):
            raise LoginError("selenium_session_handoff_unverified")
        _LAST_AUTH_OUTCOME = "ok"
        return True
    except LoginError as exc:
        _LAST_AUTH_OUTCOME = _fixed_outcome(str(exc), client.report)
        return False
    except Exception:
        _LAST_AUTH_OUTCOME = "auth_failed"
        return False
    finally:
        client.close()
