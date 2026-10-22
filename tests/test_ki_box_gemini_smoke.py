"""Execute the exact inline Actions programs with memory-only HTTP transports."""
import copy
from email.message import Message
from http.client import HTTPResponse
import io
import itertools
import json
from pathlib import Path
import re
import secrets
import urllib.request
from urllib.response import addinfourl

import pytest


WORKFLOW = Path(__file__).resolve().parents[1] / '.github/workflows/ki-box-gemini-smoke.yml'
TEXT = WORKFLOW.read_text()


def programs():
    blocks = []
    lines = iter(TEXT.splitlines(keepends=True))
    for line in lines:
        if line == '        run: |\n':
            block = []
            for line in lines:
                if not line.strip() or line.startswith('          '):
                    block.append(line[10:] if line.strip() else '\n')
                else:
                    break
            blocks.append(''.join(block))
    assert len(blocks) == 3
    return blocks


PREPARE, GENERATE, PUBLISH = programs()
REPO = 'chhubeny90-cell/aldi-watcher'
BASE = 'https://api.github.com/repos/' + REPO
ISSUE = BASE + '/issues/126'
HTML = 'https://github.com/' + REPO + '/issues/126'
MODEL = 'gemini-synthetic-model'
TOKEN = 'synthetic_app_token_123456'
KEY = 'synthetic_google_key_123456'


class Response(io.BytesIO):
    def __init__(self, value, url, status=200):
        data = value if isinstance(value, bytes) else json.dumps(value).encode()
        super().__init__(data)
        self.url, self.status, self.headers = url, status, Message()
        self.headers['Content-Length'] = str(len(data))


@pytest.fixture
def env(tmp_path, monkeypatch):
    values = {
        'GITHUB_REPOSITORY': REPO, 'GITHUB_EVENT_NAME': 'workflow_dispatch',
        'GITHUB_REF': 'refs/heads/main', 'GITHUB_RUN_ATTEMPT': '1',
        'GITHUB_RUN_ID': '12345', 'GITHUB_SHA': 'a' * 40,
        'GITHUB_OUTPUT': str(tmp_path / 'output'), 'GITHUB_STEP_SUMMARY': str(tmp_path / 'summary'),
        'LIVE': 'false', 'PUBLISH': 'false', 'MODEL': MODEL, 'GEMINI_API_KEY': KEY,
        'APP_TOKEN': TOKEN, 'APP_SLUG': 'ki-box-smoke', 'EXPECTED_BOT': 'ki-box-smoke[bot]',
        'EXPECTED_BOT_ID': '700', 'EXPECTED_APP_ID': '701',
    }
    monkeypatch.setattr('os.environ', values)
    monkeypatch.setattr(secrets, 'token_hex', lambda size: 'b' * 48)
    monkeypatch.setattr(urllib.request, 'build_opener', lambda *a: pytest.fail('unexpected HTTP'))
    return values


def execute(program):
    scope = {}
    exec(compile(program, str(WORKFLOW), 'exec'), scope)
    return scope


def output(env, name):
    path = Path(env['GITHUB_OUTPUT'])
    return [line.split('=', 1)[1] for line in path.read_text().splitlines() if line.startswith(name + '=')][-1]


def summary(env):
    path = Path(env['GITHUB_STEP_SUMMARY'])
    return path.read_text() if path.exists() else ''


def task(env):
    execute(PREPARE)
    env['TASK'] = output(env, 'task')
    Path(env['GITHUB_OUTPUT']).unlink()
    Path(env['GITHUB_STEP_SUMMARY']).unlink()
    return json.loads(env['TASK'])


def expected(task):
    return dict(task, type='KI_BOX_SMOKE_V1', provider='gemini')


def gemini_result(task):
    return {
        'candidates': [{'finishReason': 'STOP', 'content': {'role': 'model', 'parts': [
            {'text': json.dumps(expected(task))}]}}],
        'responseId': 'synthetic-response-001', 'modelVersion': MODEL,
    }


def install(monkeypatch, handler):
    calls = []
    class Opener:
        def open(self, req, timeout):
            calls.append(req)
            return handler(req, timeout)
    monkeypatch.setattr(urllib.request, 'build_opener', lambda *a: Opener())
    return calls


def valid_receipt(env, task):
    receipt = dict(expected(task), requested_model=MODEL,
                   api_metadata={'responseId': 'synthetic-response-001', 'modelVersion': MODEL},
                   run_url='https://github.com/' + REPO + '/actions/runs/12345')
    env['RECEIPT'] = json.dumps(receipt)
    return receipt


def test_prepare_is_nonsecret_and_has_no_http(env):
    execute(PREPARE)
    prepared = json.loads(output(env, 'task'))
    assert prepared['challenge'] == 'b' * 48
    assert prepared['task_id'] == 'GEMINI-SMOKE-12345'
    assert 'PREPARED only' in summary(env) and 'No Gemini delivery' in summary(env)
    assert KEY not in summary(env) and TOKEN not in summary(env)


def test_publish_without_live_fails_before_output(env):
    env['PUBLISH'] = 'true'
    with pytest.raises(SystemExit, match='BLOCKED'):
        execute(PREPARE)
    assert not Path(env['GITHUB_OUTPUT']).exists()


@pytest.mark.parametrize('field', ['LIVE', 'PUBLISH'])
def test_unrecognized_boolean_representation_fails_closed(env, field):
    env[field] = 'unexpected'
    with pytest.raises(SystemExit, match='BLOCKED'):
        execute(PREPARE)
    assert not Path(env['GITHUB_OUTPUT']).exists() and summary(env) == ''


@pytest.mark.parametrize('field,value', [
    ('GITHUB_RUN_ATTEMPT', '2'), ('GITHUB_REF', 'refs/heads/unsafe'),
    ('GITHUB_EVENT_NAME', 'pull_request'), ('GITHUB_REPOSITORY', 'other/repo'),
    ('GITHUB_RUN_ID', '1\ninjection'), ('GITHUB_SHA', 'not-a-sha'),
])
@pytest.mark.parametrize('program', [PREPARE, GENERATE, PUBLISH], ids=['prepare', 'generate', 'publish'])
def test_context_and_reruns_fail_closed_in_every_program(env, field, value, program):
    prepared = task(env)
    valid_receipt(env, prepared)
    env[field] = value
    with pytest.raises(SystemExit, match='BLOCKED'):
        execute(program)
    assert not Path(env['GITHUB_OUTPUT']).exists() and summary(env) == ''


def test_one_fixed_gemini_post_no_tools_no_git_or_github_credentials(env, monkeypatch):
    prepared = task(env)
    def handler(req, timeout):
        assert timeout == 60 and req.get_method() == 'POST'
        assert req.full_url == 'https://generativelanguage.googleapis.com/v1beta/models/' + MODEL + ':generateContent'
        assert req.get_header('X-goog-api-key') == KEY
        assert req.get_header('Authorization') is None and KEY not in req.full_url
        payload = json.loads(req.data)
        assert set(payload) == {'contents', 'generationConfig'}
        assert TOKEN not in req.data.decode() and KEY not in req.data.decode()
        return Response(gemini_result(prepared), req.full_url)
    calls = install(monkeypatch, handler)
    execute(GENERATE)
    assert len(calls) == 1
    receipt = json.loads(output(env, 'receipt'))
    assert receipt['api_metadata']['modelVersion'] == MODEL
    assert receipt['type'] == 'KI_BOX_SMOKE_V1'
    assert 'not KI_ACK_V1' in summary(env) and KEY not in summary(env)


@pytest.mark.parametrize('change', ['duplicate', 'wrong_task', 'bool_attempt', 'extra_candidate',
                                 'tool_part', 'bad_role', 'finish', 'version', 'echo_key', 'oversized'])
def test_bad_gemini_responses_never_publish_or_retry(env, monkeypatch, change):
    prepared = task(env)
    result = gemini_result(prepared)
    if change == 'duplicate':
        result = json.dumps(result)[:-1] + ',"responseId":"other"}'
        result = result.encode()
    elif change in ('wrong_task', 'bool_attempt'):
        echo = expected(prepared)
        echo['task_id' if change == 'wrong_task' else 'run_attempt'] = 'other' if change == 'wrong_task' else True
        result['candidates'][0]['content']['parts'][0]['text'] = json.dumps(echo)
    elif change == 'extra_candidate':
        result['candidates'] *= 2
    elif change == 'tool_part':
        result['candidates'][0]['content']['parts'][0]['functionCall'] = {'name': 'leak'}
    elif change == 'bad_role':
        result['candidates'][0]['content']['role'] = 'user'
    elif change == 'finish':
        result['candidates'][0]['finishReason'] = 'MAX_TOKENS'
    elif change == 'version':
        result['modelVersion'] = 'gemini-unapproved-model'
    elif change == 'echo_key':
        result['responseId'] = KEY
    else:
        result = b' ' * 65537
    calls = install(monkeypatch, lambda req, timeout: Response(result, req.full_url))
    with pytest.raises(SystemExit) as error:
        execute(GENERATE)
    assert KEY not in str(error.value) and TOKEN not in str(error.value)
    assert len(calls) == 1 and not Path(env['GITHUB_OUTPUT']).exists() and summary(env) == ''


@pytest.mark.parametrize('program,token_header,token', [(GENERATE, 'X-goog-api-key', KEY), (PUBLISH, 'Authorization', 'Bearer ' + TOKEN)], ids=['gemini', 'github'])
@pytest.mark.parametrize('code', [301, 302, 303, 307, 308])
@pytest.mark.parametrize('target', ['https://collector.invalid/leak', 'http://api.github.com/leak'])
def test_actual_urllib_redirect_flow_never_forwards_credentials(env, monkeypatch, program, token_header, token, code, target):
    prepared = task(env)
    valid_receipt(env, prepared)
    sent = []
    class Transport(urllib.request.HTTPSHandler, urllib.request.HTTPHandler):
        def response(self, req):
            sent.append((req.full_url, req.get_header(token_header)))
            headers = Message()
            headers['Location'] = target
            response = addinfourl(io.BytesIO(b''), headers, req.full_url, code)
            response.msg = 'Redirect'
            return response
        https_open = response
        http_open = response
    # Fixture replaced build_opener, so obtain the unmodified class factory via stored module helper.
    monkeypatch.setattr(urllib.request, 'build_opener', lambda *handlers: ORIGINAL_OPENER(*handlers, Transport()))
    with pytest.raises(SystemExit, match='BLOCKED'):
        execute(program)
    assert len(sent) == 1 and sent[0][1] == token
    assert 'collector.invalid' not in sent[0][0]


ORIGINAL_OPENER = urllib.request.build_opener


class GitHub:
    def __init__(self):
        self.comments, self.posts = [], 0
        self.bad_identity, self.bad_readback, self.timeout_post = False, False, False
    def identity(self):
        return {'id': 999 if self.bad_identity else 700, 'login': 'ki-box-smoke[bot]', 'type': 'Bot'}
    def comment(self, body):
        return {'id': 42, 'body': body, 'user': self.identity(),
                'performed_via_github_app': {'id': 701, 'slug': 'ki-box-smoke'},
                'issue_url': ISSUE, 'html_url': HTML + '#issuecomment-42'}
    def __call__(self, req, timeout):
        assert timeout == 30 and req.get_header('Authorization') == 'Bearer ' + TOKEN
        assert req.get_header('X-goog-api-key') is None
        assert req.full_url.startswith('https://api.github.com/')
        if req.full_url.endswith('/users/ki-box-smoke%5Bbot%5D'):
            result = self.identity()
        elif req.full_url == ISSUE:
            result = {'state': 'open', 'number': 126, 'locked': False, 'url': ISSUE, 'html_url': HTML}
        elif req.get_method() == 'POST':
            assert req.full_url == ISSUE + '/comments'
            self.posts += 1
            self.comments.append(self.comment(json.loads(req.data)['body']))
            if self.timeout_post:
                raise TimeoutError('SYNTHETIC_PRIVATE_SERVER_DATA')
            return Response(self.comments[-1], req.full_url, 201)
        elif '/comments?per_page=100&page=' in req.full_url:
            page = int(req.full_url.rsplit('=', 1)[1])
            result = self.comments[(page - 1) * 100:page * 100]
        else:
            assert req.full_url == BASE + '/issues/comments/42'
            result = copy.deepcopy(self.comments[-1])
            if self.bad_readback:
                result['id'] = 43
                result['html_url'] = HTML + '#issuecomment-43'
        return Response(result, req.full_url)


def test_publishing_requires_bot_id_app_id_and_exact_readback_then_deduplicates(env, monkeypatch):
    valid_receipt(env, task(env))
    github = GitHub()
    calls = install(monkeypatch, github)
    execute(PUBLISH)
    assert github.posts == 1 and 'POSTED_AND_READ_BACK' in summary(env)
    execute(PUBLISH)
    assert github.posts == 1 and 'ALREADY_POSTED_AND_READ_BACK' in summary(env)
    assert TOKEN not in summary(env) and KEY not in summary(env)
    assert len([r for r in calls if r.get_method() == 'POST']) == 1


@pytest.mark.parametrize('change', ['identity', 'id_bool', 'app_id', 'receipt_run', 'receipt_duplicate', 'model', 'extra_receipt'])
def test_bad_identity_or_receipt_never_posts(env, monkeypatch, change):
    receipt = valid_receipt(env, task(env))
    github = GitHub()
    if change == 'identity':
        github.bad_identity = True
    elif change == 'id_bool':
        env['EXPECTED_BOT_ID'] = 'True'
    elif change == 'app_id':
        env['EXPECTED_APP_ID'] = 'invalid'
    elif change == 'receipt_run':
        receipt['run_id'] = '999'
    elif change == 'receipt_duplicate':
        env['RECEIPT'] = env['RECEIPT'][:-1] + ',"provider":"gemini"}'
    elif change == 'model':
        receipt['requested_model'] = 'gemini-wrong'
    else:
        receipt['secret_extra'] = 'SYNTHETIC_PRIVATE_DATA'
    if change != 'receipt_duplicate':
        env['RECEIPT'] = json.dumps(receipt)
    install(monkeypatch, github)
    with pytest.raises(SystemExit, match='BLOCKED'):
        execute(PUBLISH)
    assert github.posts == 0 and summary(env) == ''


@pytest.mark.parametrize('failure', ['wrong_readback', 'timeout_post'])
def test_uncertain_publish_never_reports_success_or_retries(env, monkeypatch, failure):
    valid_receipt(env, task(env))
    github = GitHub()
    github.bad_readback = failure == 'wrong_readback'
    github.timeout_post = failure == 'timeout_post'
    install(monkeypatch, github)
    with pytest.raises(SystemExit) as error:
        execute(PUBLISH)
    assert 'do NOT retry blindly' in str(error.value)
    assert 'SYNTHETIC_PRIVATE_SERVER_DATA' not in str(error.value)
    assert github.posts == 1 and summary(env) == ''
    env['GITHUB_RUN_ATTEMPT'] = '2'
    with pytest.raises(SystemExit, match='BLOCKED'):
        execute(PUBLISH)
    assert github.posts == 1


def test_spoofed_or_duplicate_run_marker_blocks_without_post(env, monkeypatch):
    valid_receipt(env, task(env))
    github = GitHub()
    install(monkeypatch, github)
    execute(PUBLISH)
    Path(env['GITHUB_STEP_SUMMARY']).unlink()
    github.comments[0]['user']['id'] = 999
    with pytest.raises(SystemExit, match='BLOCKED'):
        execute(PUBLISH)
    assert github.posts == 1 and summary(env) == ''


def test_duplicate_run_markers_are_ambiguous_even_with_correct_identity(env, monkeypatch):
    valid_receipt(env, task(env))
    github = GitHub()
    install(monkeypatch, github)
    execute(PUBLISH)
    Path(env['GITHUB_STEP_SUMMARY']).unlink()
    github.comments.append(copy.deepcopy(github.comments[0]))
    with pytest.raises(SystemExit, match='BLOCKED'):
        execute(PUBLISH)
    assert github.posts == 1 and summary(env) == ''


@pytest.mark.parametrize('total', [100, 1000, 1001])
def test_publish_scans_to_exhaustion_or_fails_closed_before_mutation(env, monkeypatch, total):
    valid_receipt(env, task(env))
    github = GitHub()
    github.comments = [{'body': 'unrelated comment'} for _ in range(total)]
    calls = install(monkeypatch, github)
    if total > 1000:
        with pytest.raises(SystemExit, match='BLOCKED'):
            execute(PUBLISH)
        assert github.posts == 0 and summary(env) == ''
    else:
        execute(PUBLISH)
        assert github.posts == 1 and 'POSTED_AND_READ_BACK' in summary(env)
    scans = [r for r in calls if '?per_page=100&page=' in r.full_url]
    assert len(scans) == min(total // 100 + 1, 11)


@pytest.mark.parametrize('field,value', [('EXPECTED_BOT_ID', '701'), ('EXPECTED_APP_ID', '700')])
def test_wrong_durable_bot_or_app_identity_cannot_report_success(env, monkeypatch, field, value):
    valid_receipt(env, task(env))
    env[field] = value
    github = GitHub()
    install(monkeypatch, github)
    with pytest.raises(SystemExit, match='BLOCKED'):
        execute(PUBLISH)
    assert github.posts <= 1 and summary(env) == ''


@pytest.mark.parametrize('program', [GENERATE, PUBLISH], ids=['gemini', 'github'])
def test_transport_exception_details_are_withheld_and_not_retried(env, monkeypatch, program):
    valid_receipt(env, task(env))
    def failed(req, timeout):
        raise OSError('SYNTHETIC_PRIVATE_TRANSPORT_DETAIL')
    calls = install(monkeypatch, failed)
    with pytest.raises(SystemExit) as error:
        execute(program)
    assert 'SYNTHETIC_PRIVATE_TRANSPORT_DETAIL' not in str(error.value)
    assert len(calls) == 1 and summary(env) == ''


@pytest.mark.parametrize('wire', [
    b'HTTP/1.1 200 OK\r\nContent-Length: 999\r\n\r\n[]',
    b'HTTP/1.1 200 OK\r\nTransfer-Encoding: gzip\r\n\r\n[]',
    b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked \r\n\r\n[]',
    b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\nContent-Length: 2\r\n\r\n[]',
])
def test_real_http_response_framing_failures_stop_before_json_success(env, monkeypatch, wire):
    task(env)
    class Socket:
        def makefile(self, *a):
            return io.BytesIO(wire)
    def handler(req, timeout):
        response = HTTPResponse(Socket())
        response.begin()
        response.url = req.full_url
        return response
    calls = install(monkeypatch, handler)
    with pytest.raises(SystemExit, match='BLOCKED'):
        execute(GENERATE)
    assert len(calls) == 1 and summary(env) == ''


def test_workflow_gates_and_secret_separation():
    assert TEXT.count('default: false') == 2
    assert '  push:' not in TEXT and '  schedule:' not in TEXT
    assert TEXT.count('github.run_attempt == 1') == 3
    assert TEXT.count("github.ref == 'refs/heads/main'") == 3
    assert TEXT.count('permissions: {}') == 4
    assert 'cancel-in-progress: false' in TEXT
    assert 'checkout@' not in TEXT and 'pip install' not in TEXT
    generate = TEXT.split('\n  generate:\n')[1].split('\n  publish:\n')[0]
    publish = TEXT.split('\n  publish:\n')[1]
    assert 'secrets.GEMINI_API_KEY' in generate and 'APP_PRIVATE_KEY' not in generate
    assert 'secrets.KI_BOX_GEMINI_APP_PRIVATE_KEY' in publish and 'secrets.GEMINI_API_KEY' not in publish
    assert 'permission-issues: write' in publish and 'skip-token-revoke: false' in publish
    assert re.search(r'uses: actions/create-github-app-token@[0-9a-f]{40}', publish)
    for source in programs():
        compile(source, str(WORKFLOW), 'exec')
        assert '${{' not in source


def test_activation_matrix_requires_each_approval_and_first_main_attempt():
    conditions = re.findall(r'^    if: >-\n((?:^      .*\n)+)', TEXT, re.MULTILINE)
    assert len(conditions) == 3
    for live, publish, zero, free, enabled, first in itertools.product([False, True], repeat=6):
        bindings = {
            'inputs.live': live, 'inputs.publish': publish,
            'github.event_name': 'workflow_dispatch', 'github.ref': 'refs/heads/main',
            'github.repository': REPO, 'github.run_attempt': 1 if first else 2,
            'vars.KI_BOX_ACTIONS_ZERO_COST_VERIFIED': 'true' if zero else '',
            'vars.KI_BOX_GEMINI_FREE_TIER_VERIFIED': 'true' if free else '',
            'vars.KI_BOX_GEMINI_PUBLISH_ENABLED': 'true' if enabled else '',
        }
        values = []
        for condition in conditions:
            expression = ' '.join(condition.split())
            for name, value in sorted(bindings.items(), key=lambda pair: -len(pair[0])):
                expression = expression.replace(name, repr(value))
            expression = expression.replace('&&', ' and ')
            assert re.fullmatch(r"[A-Za-z0-9_' /:().=\-]+", expression)
            values.append(bool(eval(expression, {'__builtins__': {}}, {})))
        prepared = values[0]
        generated = prepared and values[1]
        published = generated and values[2]
        assert prepared == (zero and first)
        assert generated == (zero and free and live and first)
        assert published == (zero and free and live and publish and enabled and first)
