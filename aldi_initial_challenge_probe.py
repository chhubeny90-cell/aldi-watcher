"""Inspect ALDI's initial login challenge without typing or submitting credentials.

The report keeps only structural metadata and sanitized TextOutputCallback samples.
It performs no password submit, SMS request, portal write, or refill action.
"""

import json
import os

import watcher
from monitoring import navigate, require_origin
from aldi_frontend_submit_probe import _capture_initial
from aldi_sanitized_error_probe import _shape_with_sanitized_text
from aldi_callback_fidelity_probe import _confirmation_meta, _hidden_meta

REPORT_PATH = os.getenv("ALDI_INITIAL_CHALLENGE_REPORT", "aldi-initial-challenge.json")


def _challenge_flags(shape):
    samples = (shape or {}).get("sanitized_text_outputs") or []
    return {
        "proof_of_work_present": any("startProofOfWork" in text for text in samples),
        "account_lock_key_present": any("accountLock.accountLockMsg" in text for text in samples),
        "custom_error_key_present": any("custom.alditalk.common.error$" in text for text in samples),
    }


def _structural_metadata(challenge):
    """Return only non-secret callback structure useful for drift detection."""
    return {
        "confirmation_meta": _confirmation_meta(challenge),
        "hidden_meta": _hidden_meta(challenge),
    }


def main():
    report = {
        "outcome": "unknown",
        "typed_credentials": False,
        "credential_submit_count": 0,
        "sms_requested": False,
        "booking_executed": False,
        "initial_request_captured": False,
        "initial_shape": None,
        "challenge_flags": None,
        "confirmation_meta": None,
        "hidden_meta": None,
        "exception_type": None,
    }

    driver = None
    try:
        driver = watcher.build_driver()
        navigate(driver, watcher.ALDI_LOGIN_URL)
        require_origin(driver, watcher.ALDI_LOGIN_URL, login_hosts=watcher.ALDI_LOGIN_HOSTS)
        watcher.dismiss_cookie_banner(driver)

        initial_info, challenge = _capture_initial(driver, timeout=20)
        if initial_info is None or challenge is None:
            report["outcome"] = "initial_challenge_not_captured"
            return 2

        report["initial_request_captured"] = True
        shape = _shape_with_sanitized_text(challenge, 200)
        report["initial_shape"] = shape
        report["challenge_flags"] = _challenge_flags(shape)
        metadata = _structural_metadata(challenge)
        report.update(metadata)
        report["outcome"] = "observed"
        return 0
    except Exception as exc:
        report["outcome"] = "exception"
        report["exception_type"] = type(exc).__name__
        return 2
    finally:
        with open(REPORT_PATH, "w", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
        print(json.dumps(report, ensure_ascii=False), flush=True)
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
