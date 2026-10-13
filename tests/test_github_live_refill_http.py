import github_live_refill_http as wrapper


def test_configure_hosted_auth_replaces_only_login_and_failure_classifier(monkeypatch):
    old_login = object()
    fallback_calls = []

    def fallback(driver):
        fallback_calls.append(driver)
        return "fallback"

    monkeypatch.setattr(wrapper.hosted, "_ORIGINAL_LOGIN", old_login)
    monkeypatch.setattr(wrapper.hosted, "_provider_login_outcome", fallback)
    monkeypatch.setattr(wrapper.auth, "login_with_http_session", lambda driver: True)
    monkeypatch.setattr(wrapper.auth, "last_auth_outcome", lambda: "account_locked")

    wrapper.configure_hosted_auth()

    assert wrapper.hosted._ORIGINAL_LOGIN is wrapper.auth.login_with_http_session
    assert wrapper.hosted._provider_login_outcome(object()) == "account_locked"
    assert fallback_calls == []


def test_hosted_auth_classifier_falls_back_when_http_has_no_fixed_outcome(monkeypatch):
    driver = object()
    monkeypatch.setattr(wrapper.hosted, "_ORIGINAL_LOGIN", object())
    monkeypatch.setattr(wrapper.hosted, "_provider_login_outcome", lambda current: "browser-diagnostic")
    monkeypatch.setattr(wrapper.auth, "login_with_http_session", lambda current: True)
    monkeypatch.setattr(wrapper.auth, "last_auth_outcome", lambda: None)

    wrapper.configure_hosted_auth()

    assert wrapper.hosted._provider_login_outcome(driver) == "browser-diagnostic"
