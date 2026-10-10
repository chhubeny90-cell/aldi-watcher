import base64
import json
import http.cookiejar
from unittest.mock import patch

import pytest

from aldi_http_probe import HttpProbe, ProbeError, AUTH_URL, OVERVIEW, MASTER, OFFERS, main, trusted, login_choice

PHONE = '015000000000'
PASSWORD = 'test-only-password'


def test_password_login_choice_excludes_sms_and_reset():
    assert login_choice(['custom.resetPassword', 'custom.passwordlessLogin', 'custom.loginButton']) == 2
    assert login_choice(['Anmelden', 'Passwort vergessen', 'Login mit SMS']) == 0
    assert login_choice(['custom.alditalk.login.cancelButton', 'custom.alditalk.login.sendSms',
                         'custom.alditalk.login.loginButton']) == 2
    assert login_choice(['custom.alditalk.loginuserbasic.loginWithoutPassword',
                         'custom.alditalk.loginuserbasic.registerbtn',
                         'custom.alditalk.loginuserbasic.loginbtn',
                         'custom.alditalk.loginuserbasic.forgetP']) == 2


def test_ambiguous_login_choices_are_not_submitted():
    with pytest.raises(ProbeError, match='login_choice_unrecognized'):
        login_choice(['Login', 'Anmelden'])


def login_form():
    return {'authId': 'test-id', 'callbacks': [
        {'type': 'NameCallback', 'input': [{'name': 'IDToken1', 'value': ''}], 'output': []},
        {'type': 'PasswordCallback', 'input': [{'name': 'IDToken2', 'value': ''}], 'output': []}]}


def fake_probe(auth_result=None, subscriptions=None, cookie_number=PHONE, packs=None):
    report = {'login_ok': False, 'account_matches': False, 'credential_submissions': 0}
    probe = HttpProbe(report)
    calls = []
    def request(url, payload=None):
        calls.append((url, payload))
        if url == AUTH_URL:
            result = (auth_result if auth_result is not None else {'successUrl': OVERVIEW}) if payload.get('authId') else login_form()
        elif url == MASTER:
            result = {'userDetails': {'subscriptions': subscriptions if subscriptions is not None else [{'contractId': 'test-contract'}]}}
        elif url.startswith(OFFERS):
            result = {'subscribedOffers': [{'pack': packs if packs is not None else [
                {'type': 'data', 'allocated': '1048576', 'used': '524288', 'unit': 'kilobytes'}]}]}
        else:
            return url, b'<html>not proof of authentication</html>'
        return url, json.dumps(result).encode()
    probe.request = request
    if cookie_number:
        cookie = http.cookiejar.Cookie(0, 'lgrs_id', base64.b64encode(cookie_number.encode()).decode(),
            None, False, 'www.alditalk-kundenportal.de', True, False, '/', True,
            True, None, True, None, None, {}, False)
        probe.cookies.set_cookie(cookie)
    return probe, report, calls


def test_verified_account_and_volume_with_exact_number():
    probe, report, calls = fake_probe()
    probe.run(PHONE, PASSWORD)
    assert report['outcome'] == 'read_only_access_verified'
    assert report['login_ok'] and report['account_matches']
    assert report['remaining_gb'] == 0.5
    submitted = [p for _, p in calls if p and p.get('authId')]
    assert len(submitted) == 1
    assert submitted[0]['callbacks'][0]['input'][0]['value'] == PHONE
    assert submitted[0]['callbacks'][1]['input'][0]['value'] == PASSWORD
    assert all(url == AUTH_URL for url, payload in calls if payload is not None)


def test_http_success_without_auth_result_is_failure_no_retry():
    probe, report, calls = fake_probe(auth_result={'callbacks': []})
    with pytest.raises(ProbeError, match='authentication_not_completed'):
        probe.run(PHONE, PASSWORD)
    assert not report['login_ok']
    assert report['credential_submissions'] == 1
    assert not any(url == MASTER for url, _ in calls)


def test_wrong_sim_never_reads_volume():
    probe, report, calls = fake_probe(cookie_number='015000000001')
    with pytest.raises(ProbeError, match='sim_identity_unverified'):
        probe.run(PHONE, PASSWORD)
    assert report['login_ok'] and not report['account_matches']
    assert not any(url.startswith(OFFERS) for url, _ in calls)


def test_multiple_accounts_are_not_selected_from_cookie():
    probe, _, calls = fake_probe(subscriptions=[{'contractId': 'one'}, {'contractId': 'two'}])
    with pytest.raises(ProbeError, match='sim_identity_unverified'):
        probe.run(PHONE, PASSWORD)
    assert not any(url.startswith(OFFERS) for url, _ in calls)


@pytest.mark.parametrize('url', ['https://evil.example/', 'https://login.alditalk-kundenbetreuung.de.evil.example/',
                                  'http://www.alditalk-kundenportal.de/', 'https://www.alditalk-kundenportal.de:444/'])
def test_foreign_or_insecure_redirect_blocked(url):
    with pytest.raises(ProbeError, match='untrusted_redirect'):
        trusted(url)


def test_unknown_challenge_does_not_submit_password():
    probe, report, calls = fake_probe()
    original = probe.request
    def request(url, payload=None):
        if url == AUTH_URL and payload == {}:
            form = login_form()
            form['callbacks'].append({'type': 'OTPCallback'})
            calls.append((url, payload))
            return url, json.dumps(form).encode()
        return original(url, payload)
    probe.request = request
    with pytest.raises(ProbeError, match='additional_authentication_required'):
        probe.run(PHONE, PASSWORD)
    assert report['credential_submissions'] == 0


def test_exception_never_leaks_credentials_to_report(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('ALDI_HTTP_REPORT', str(tmp_path / 'report.json'))
    with patch('core.credentials.get_credential', side_effect=lambda key: PHONE if key == 'ALDI_USER' else PASSWORD), \
         patch.object(HttpProbe, 'run', side_effect=ValueError(PHONE + PASSWORD)):
        assert main() == 2
    output = capsys.readouterr().out + (tmp_path / 'report.json').read_text()
    assert PHONE not in output and PASSWORD not in output
    assert 'technical_error' in output
