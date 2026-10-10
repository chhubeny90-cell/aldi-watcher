"""Run the full-fidelity ALDI password-login callback diagnostic.

Only public ALDI localization keys, callback IDs and structural booleans are
added to the sanitized report. No raw query, credential, hidden value, authId,
token or cookie is logged or persisted.
"""

import re
import aldi_callback_fidelity_probe as base


LOGIN_OPTION = "custom.alditalk.loginuserbasic.loginbtn"
SAFE_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,119}$")

_original_confirmation_meta = base._confirmation_meta
_original_hidden_meta = base._hidden_meta
_original_text_output_category = base._text_output_category


def _safe_public_key(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not SAFE_KEY.fullmatch(value):
        return None
    # Restrict persisted strings to obvious UI/technical localization keys.
    lowered = value.casefold()
    if not any(marker in lowered for marker in ("custom.", "alditalk", "login", "auth", "error", "message", "label")):
        return None
    return value


def _confirmation_meta_with_labels(challenge):
    result = _original_confirmation_meta(challenge)
    result["option_labels"] = []
    result["option_type"] = None
    result["prompt_key"] = None
    for callback in challenge.get("callbacks", []) if isinstance(challenge, dict) else []:
        if not isinstance(callback, dict) or callback.get("type") != "ConfirmationCallback":
            continue
        outputs = {
            item.get("name"): item.get("value")
            for item in callback.get("output", [])
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        }
        options = outputs.get("options")
        if isinstance(options, list):
            result["option_labels"] = [
                _safe_public_key(option) or "non_key_label"
                for option in options[:10]
            ]
        option_type = outputs.get("optionType")
        if isinstance(option_type, int) and not isinstance(option_type, bool):
            result["option_type"] = option_type
        result["prompt_key"] = _safe_public_key(outputs.get("prompt"))
        break
    return result


def _hidden_meta_with_ids(challenge):
    rows = _original_hidden_meta(challenge)
    hidden_callbacks = [
        callback for callback in challenge.get("callbacks", [])
        if isinstance(callback, dict) and callback.get("type") == "HiddenValueCallback"
    ] if isinstance(challenge, dict) else []
    for row, callback in zip(rows, hidden_callbacks):
        outputs = {
            item.get("name"): item.get("value")
            for item in callback.get("output", [])
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        }
        row["id_key"] = _safe_public_key(outputs.get("id")) or "non_key_id"
        inputs = callback.get("input")
        if isinstance(inputs, list) and len(inputs) == 1 and isinstance(inputs[0], dict):
            row["input_initially_empty"] = inputs[0].get("value") in (None, "", [], {})
            row["input_equals_output_value"] = inputs[0].get("value") == outputs.get("value")
    return rows


def _text_output_category_with_keys(obj):
    result = _original_text_output_category(obj)
    keys = []
    non_key_messages = 0
    if isinstance(obj, dict):
        for callback in obj.get("callbacks", []):
            if not isinstance(callback, dict) or callback.get("type") != "TextOutputCallback":
                continue
            for item in callback.get("output", []):
                if not isinstance(item, dict) or item.get("name") != "message":
                    continue
                key = _safe_public_key(item.get("value"))
                if key:
                    keys.append(key)
                elif isinstance(item.get("value"), str) and item.get("value").strip():
                    non_key_messages += 1
    result["message_keys"] = keys[:10]
    result["non_key_message_count"] = non_key_messages
    return result


def _password_login_confirmation(callback):
    options = base._output_value(callback, "options")
    if not isinstance(options, list) or not options or len(options) > 10:
        raise RuntimeError("confirmation_options_unexpected")
    matches = [
        index for index, option in enumerate(options)
        if isinstance(option, str) and option.strip().casefold() == LOGIN_OPTION.casefold()
    ]
    if len(matches) != 1:
        raise RuntimeError("password_login_callback_not_unique")
    return matches[0], "unique_aldi_loginbtn_option"


base._confirmation_meta = _confirmation_meta_with_labels
base._hidden_meta = _hidden_meta_with_ids
base._text_output_category = _text_output_category_with_keys
base._confirmation_index = _password_login_confirmation
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
