"""Run the full-fidelity ALDI callback probe against the exact initial auth URL.

This reuses the sanitized fidelity probe but retains ALDI's initial query string
for the single continuation POST. No raw query, credential, authId or token is
logged or persisted.
"""

import aldi_callback_fidelity_probe as base


_original_prepare_payload = base._prepare_payload


def _prepare_payload(challenge):
    callbacks, normalization = _original_prepare_payload(challenge)
    normalization["continuation_query_stripped"] = False
    normalization["exact_initial_auth_url_reused"] = True
    return callbacks, normalization


def _submit_full_challenge(driver, initial_info, challenge, prepared_callbacks):
    exact_url = initial_info["url"]
    if not base._validated_auth_url(exact_url):
        raise PermissionError("untrusted_auth_url")

    payload = base.copy.deepcopy(challenge)
    payload["callbacks"] = prepared_callbacks
    headers = dict(initial_info.get("headers") or {})
    headers.setdefault("Accept", "application/json")
    headers.setdefault("Content-Type", "application/json")

    result = driver.execute_async_script(r"""
        const url = arguments[0];
        const payload = arguments[1];
        const headers = arguments[2];
        const done = arguments[arguments.length - 1];
        fetch(url, {
          method: 'POST',
          credentials: 'include',
          cache: 'no-store',
          headers: headers,
          body: JSON.stringify(payload)
        }).then(async response => {
          let body = null;
          try { body = await response.json(); } catch (_) {}
          done({status: response.status, body: body});
        }).catch(() => done({status: 0, body: null}));
    """, exact_url, payload, headers)
    if not isinstance(result, dict):
        return 0, None
    return int(result.get("status") or 0), result.get("body")


base._prepare_payload = _prepare_payload
base._submit_full_challenge = _submit_full_challenge
main = base.main


if __name__ == "__main__":
    raise SystemExit(main())
