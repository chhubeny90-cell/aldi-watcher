"""One browser-free password login using ALDI_USER (the SIM number).

Read-only: only authentication POSTs and account GETs. No booking endpoint.
Reports never contain credentials, cookies, auth payloads, or response bodies.
Protocol reference: JonasJoKuJonas/homeassistant-AldiTalk, aldi_talk.py.
"""
import base64
import copy
import hashlib
import http.cookiejar
import json
import math
import os
import re
import time
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPCookieProcessor, Request, build_opener

PORTAL = 'https://www.alditalk-kundenportal.de'
AUTH = 'https://login.alditalk-kundenbetreuung.de'
OVERVIEW = PORTAL + '/portal/auth/uebersicht/'
AUTH_URL = AUTH + '/signin/json/authenticate?' + urlencode({
    'realm': '/alditalk', 'authIndexType': 'service', 'authIndexValue': 'Login'})
MASTER = PORTAL + '/scs/bff/scs-207-customer-master-data-bff/customer-master-data/v1/navigation-list'
OFFERS = PORTAL + '/scs/bff/scs-209-selfcare-dashboard-bff/selfcare-dashboard/v1/offers'
HOSTS = {'www.alditalk-kundenportal.de', 'login.alditalk-kundenbetreuung.de',
         'www.alditalk-kundenbetreuung.de'}
CALLBACKS = {'NameCallback', 'PasswordCallback', 'HiddenValueCallback',
             'TextOutputCallback', 'ConfirmationCallback'}


class ProbeError(Exception):
    """Only fixed, non-sensitive reason codes are exposed."""


def trusted(url):
    parts = urlsplit(url)
    if (parts.scheme != 'https' or parts.hostname not in HOSTS
            or parts.port not in (None, 443) or parts.username or parts.password):
        raise ProbeError('untrusted_redirect')
    return url


class TrustedRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        trusted(newurl)
        if req.get_method() != 'GET':
            raise ProbeError('unexpected_auth_redirect')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def normalized_number(value):
    value = re.sub(r'[\s()\-]', '', value or '')
    if value.startswith('+49'):
        value = '0' + value[3:]
    elif value.startswith('0049'):
        value = '0' + value[4:]
    elif value.startswith('49'):
        value = '0' + value[2:]
    if not re.fullmatch(r'0\d{9,14}', value):
        raise ProbeError('phone_number_required')
    return value


def proof_of_work(callbacks):
    for cb in callbacks:
        if cb.get('type') != 'TextOutputCallback':
            continue
        for out in cb.get('output', []):
            message = str(out.get('value', ''))
            match = re.search(r'var work\s*=\s*["\']([^"\']+)["\']', message)
            if not match:
                continue
            diff = re.search(r'var difficulty\s*=\s*(\d+)', message)
            difficulty = int(diff[1]) if diff else 3
            if difficulty > 5:
                raise ProbeError('proof_of_work_limit')
            until = time.monotonic() + 5
            for nonce in range(2000000):
                if time.monotonic() >= until:
                    break
                digest = hashlib.sha1((match[1] + str(nonce)).encode()).hexdigest()
                if digest.startswith('0' * difficulty):
                    return str(nonce)
            raise ProbeError('proof_of_work_limit')
    return None


def login_choice(options):
    if not options:
        return 2
    choices = []
    for index, label in enumerate(options):
        text = str(label).casefold().rsplit('.', 1)[-1]
        if any(word in text for word in ('sms', 'otp', 'tan', 'reset', 'forgot', 'forget', 'vergessen', 'passwordless', 'withoutpassword', 'cancel', 'abbrechen')):
            continue
        if 'login' in text or 'anmelden' in text or 'einloggen' in text:
            choices.append(index)
    if len(choices) != 1:
        raise ProbeError('login_choice_unrecognized')
    return choices[0]


def fill_callbacks(payload, username, password):
    result = copy.deepcopy(payload)
    callbacks = result.get('callbacks')
    if not isinstance(callbacks, list) or not callbacks or not result.get('authId'):
        raise ProbeError('auth_shape_unrecognized')
    nonce = proof_of_work(callbacks)
    has_name = has_password = False
    for cb in callbacks:
        kind = cb.get('type')
        if kind not in CALLBACKS:
            raise ProbeError('additional_authentication_required')
        outputs = {x.get('name'): x.get('value') for x in cb.get('output', [])}
        if kind == 'TextOutputCallback':
            message = str(outputs.get('message', '')).casefold()
            if 'accountlock' in message or 'gesperrt' in message:
                raise ProbeError('account_locked')
            if 'custom.alditalk.common.error' in message:
                raise ProbeError('provider_auth_error')
            continue
        if kind == 'NameCallback':
            value = username
            has_name = True
        elif kind == 'PasswordCallback':
            prompt = str(outputs.get('prompt', '')).casefold()
            if any(x in prompt for x in ('otp', 'tan', 'code')):
                raise ProbeError('additional_authentication_required')
            value = password
            has_password = True
        elif kind == 'HiddenValueCallback':
            if outputs.get('id') == 'proofOfWorkNonce':
                if nonce is None:
                    raise ProbeError('proof_of_work_unrecognized')
                value = nonce
            else:
                value = outputs.get('value')
                if value is None:
                    raise ProbeError('auth_shape_unrecognized')
        else:
            # Recognize the password-login choice from the current callback list.
            # Never choose password reset or the passwordless/SMS route.
            value = login_choice(outputs.get('options'))
        inputs = cb.get('input', [])
        if len(inputs) != 1:
            raise ProbeError('auth_shape_unrecognized')
        inputs[0]['value'] = value
    if not has_name or not has_password:
        raise ProbeError('password_login_form_unavailable')
    return result


class HttpProbe:
    def __init__(self, report):
        self.report = report
        self.cookies = http.cookiejar.CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.cookies), TrustedRedirect())

    def request(self, url, payload=None):
        trusted(url)
        headers = {'User-Agent': 'Mozilla/5.0', 'Accept-Language': 'de-DE,de;q=0.9',
                   'Accept': 'application/json, text/plain, */*'}
        data = None
        if payload is not None:
            if url != AUTH_URL:
                raise ProbeError('non_auth_post_blocked')
            data = json.dumps(payload).encode()
            headers.update({'Content-Type': 'application/json',
                            'Accept-API-Version': 'protocol=1.0,resource=2.1',
                            'X-Username': 'anonymous', 'X-Password': 'anonymous',
                            'X-NoSession': 'true', 'Origin': AUTH,
                            'Referer': AUTH + '/signin/XUI/'})
        else:
            headers['Referer'] = OVERVIEW
        try:
            with self.opener.open(Request(url, data=data, headers=headers), timeout=20) as response:
                self.report['last_http_status'] = response.status
                body = response.read(2000001)
                if len(body) > 2000000:
                    raise ProbeError('response_too_large')
                return response.geturl(), body
        except HTTPError as exc:
            self.report['last_http_status'] = exc.code
            raise ProbeError('http_error') from None

    def request_json(self, url, payload=None):
        _, body = self.request(url, payload)
        try:
            parsed = json.loads(body)
        except (ValueError, UnicodeError):
            raise ProbeError('json_unavailable') from None
        if not isinstance(parsed, dict):
            raise ProbeError('json_shape_unrecognized')
        return parsed

    def run(self, username, password):
        expected = normalized_number(username)
        self.report['phase'] = 'portal_session'
        self.request(OVERVIEW)
        self.report['phase'] = 'auth_callbacks'
        payload = self.request_json(AUTH_URL, {})
        self.report['callback_types'] = sorted({
            cb.get('type') if cb.get('type') in CALLBACKS else 'unsupported'
            for cb in payload.get('callbacks', [])})
        self.report['confirmation_option_keys'] = [
            label if isinstance(label, str) and re.fullmatch(r'custom\.[A-Za-z._-]{1,120}', label)
            else 'public_label_unclassified'
            for cb in payload.get('callbacks', []) if cb.get('type') == 'ConfirmationCallback'
            for out in cb.get('output', []) if out.get('name') == 'options'
            for label in out.get('value', [])]
        payload = fill_callbacks(payload, username, password)
        self.report['phase'] = 'password_submission'
        self.report['credential_submissions'] = 1
        result = self.request_json(AUTH_URL, payload)
        success = result.get('successUrl')
        if not success:
            raise ProbeError('authentication_not_completed')
        self.report['phase'] = 'portal_redirects'
        self.request(trusted(urljoin(AUTH, success)))
        final_url, _ = self.request(OVERVIEW)
        if urlsplit(final_url).hostname != urlsplit(PORTAL).hostname:
            raise ProbeError('portal_session_unavailable')
        self.report['phase'] = 'account_identity'
        identities = self.request_json(MASTER).get('userDetails', {}).get('subscriptions', [])
        self.report['subscription_count'] = len(identities)
        if not identities:
            raise ProbeError('account_identity_unavailable')
        self.report['login_ok'] = True
        cookie_numbers = []
        for cookie in self.cookies:
            if cookie.name == 'lgrs_id' and cookie.domain.lstrip('.') in HOSTS:
                try:
                    raw = cookie.value + '=' * (-len(cookie.value) % 4)
                    cookie_numbers.append(normalized_number(base64.b64decode(raw).decode()))
                except (ValueError, UnicodeError, ProbeError):
                    pass
        matches = []
        for identity in identities:
            numbers = [identity.get(key) for key in ('msisdn', 'phoneNumber', 'telephoneNumber')
                       if isinstance(identity.get(key), str)]
            matched = any(normalized_number(n) == expected for n in numbers)
            if matched or (len(identities) == 1 and expected in cookie_numbers):
                matches.append(identity)
        if len(matches) != 1 or not matches[0].get('contractId'):
            raise ProbeError('sim_identity_unverified')
        self.report['account_matches'] = True
        self.report['phase'] = 'data_volume'
        offers = self.request_json(OFFERS + '?' + urlencode({
            'contractId': matches[0]['contractId'], 'productType': ''}))
        packs = [pack for offer in offers.get('subscribedOffers', [])
                 for pack in offer.get('pack', []) if pack.get('type') == 'data'
                 and pack.get('balanceAttributeReference') != 'dataGrantAmountFUP']
        if len(packs) != 1:
            raise ProbeError('data_volume_ambiguous')
        pack = packs[0]
        divisor = {'bytes': 1024**3, 'kilobytes': 1024**2,
                   'megabytes': 1024, 'gigabytes': 1}.get(str(pack.get('unit', '')).lower())
        if not divisor:
            raise ProbeError('data_volume_unit_unverified')
        remaining = (float(pack['allocated']) - float(pack['used'])) / divisor
        if not math.isfinite(remaining) or remaining < 0:
            raise ProbeError('data_volume_invalid')
        self.report['remaining_gb'] = round(remaining, 3)
        self.report['outcome'] = 'read_only_access_verified'
        self.report['phase'] = 'done'


def main():
    from core.credentials import get_credential
    report = {'started_at': datetime.now(timezone.utc).isoformat(),
              'login_identifier_source': 'ALDI_USER', 'phase': 'credentials',
              'outcome': 'unknown', 'login_ok': False, 'account_matches': False,
              'credential_submissions': 0, 'booking_executed': False}
    try:
        username = ''.join((get_credential('ALDI_USER') or '').split())
        password = get_credential('ALDI_PASS') or ''
        if not username or not password:
            raise ProbeError('credentials_unavailable')
        HttpProbe(report).run(username, password)
    except ProbeError as exc:
        report['outcome'] = str(exc)
    except Exception as exc:
        report['outcome'] = 'technical_error'
        report['exception_type'] = type(exc).__name__
    report['finished_at'] = datetime.now(timezone.utc).isoformat()
    path = os.getenv('ALDI_HTTP_REPORT', 'aldi-http-access.json')
    with open(path + '.tmp', 'w', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
    os.replace(path + '.tmp', path)
    print(json.dumps(report))
    return 0 if report['outcome'] == 'read_only_access_verified' else 2


if __name__ == '__main__':
    raise SystemExit(main())
