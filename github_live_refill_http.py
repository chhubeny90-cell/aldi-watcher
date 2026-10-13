"""Hosted live-refill entry point using verified HTTP authentication.

All booking guards remain in github_live_refill.py. This wrapper replaces only
its credential-login primitive and failure classification.
"""

import github_http_auth as auth
import github_live_refill as hosted


def configure_hosted_auth():
    fallback = hosted._provider_login_outcome

    def provider_outcome(driver):
        outcome = auth.last_auth_outcome()
        if outcome in {"account_locked", "provider_maintenance", "auth_failed"}:
            return outcome
        return fallback(driver)

    hosted._ORIGINAL_LOGIN = auth.login_with_http_session
    hosted._provider_login_outcome = provider_outcome


def main():
    configure_hosted_auth()
    return hosted.main()


if __name__ == "__main__":
    raise SystemExit(main())
