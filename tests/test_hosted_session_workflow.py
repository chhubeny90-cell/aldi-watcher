"""Hosted-session workflow boundaries; no provider or GitHub access."""
from pathlib import Path
import re
import textwrap
from types import SimpleNamespace

import pytest


WORKFLOW = Path(__file__).resolve().parents[1] / '.github/workflows/hosted-session.yml'


def _text():
    return WORKFLOW.read_text(encoding='utf-8')


def _evaluate(expression, **values):
    expression = ' '.join(expression.replace('&&', 'and').replace('||', 'or').split())
    return eval(expression, {'__builtins__': {}}, values)


def test_hourly_dispatch_and_mail_completion_are_the_only_triggers():
    triggers = _text().split('\npermissions:', 1)[0]
    assert 'workflow_dispatch:' in triggers
    assert "cron: '17 * * * *'" in triggers
    assert "workflows: ['ALDI Usage Mail Monitor']" in triggers
    assert 'types: [completed]' in triggers
    assert 'branches: [main]' in triggers
    assert 'default: initialize' in triggers
    assert 'options: [initialize, observe, refill]' in triggers
    assert 'push:' not in triggers and 'pull_request:' not in triggers
    assert 'automatic' not in triggers  # Scheduled mode cannot be manually selected.


@pytest.mark.parametrize('repository,ref,event,attempt,allowed', [
    ('chhubeny90-cell/aldi-watcher', 'refs/heads/main', 'schedule', 1, True),
    ('chhubeny90-cell/aldi-watcher', 'refs/heads/main', 'workflow_dispatch', 1, True),
    ('chhubeny90-cell/aldi-watcher', 'refs/heads/main', 'workflow_run', 1, True),
    ('other/repo', 'refs/heads/main', 'workflow_dispatch', 1, False),
    ('chhubeny90-cell/aldi-watcher', 'refs/heads/feature', 'workflow_dispatch', 1, False),
    ('chhubeny90-cell/aldi-watcher', 'refs/heads/main', 'push', 1, False),
    ('chhubeny90-cell/aldi-watcher', 'refs/heads/main', 'pull_request', 1, False),
    ('chhubeny90-cell/aldi-watcher', 'refs/heads/main', 'schedule', 2, False),
])
def test_preflight_and_execution_reject_uncontrolled_contexts(repository, ref, event, attempt, allowed):
    text = _text()
    upstream = SimpleNamespace(name='ALDI Usage Mail Monitor', conclusion='success',
                               head_repository=SimpleNamespace(full_name='chhubeny90-cell/aldi-watcher'),
                               head_branch='main', event='schedule')
    github = SimpleNamespace(repository=repository, ref=ref, event_name=event, run_attempt=attempt,
                             event=SimpleNamespace(workflow_run=upstream))
    conditions = re.findall(r'    if: >-\n(.*?)    runs-on:', text, re.S)
    assert len(conditions) == 2
    assert _evaluate(conditions[0], github=github) is allowed
    needs = SimpleNamespace(preflight=SimpleNamespace(outputs=SimpleNamespace(ready='true')))
    assert _evaluate(conditions[1], github=github, needs=needs) is allowed
    needs.preflight.outputs.ready = 'false'
    assert _evaluate(conditions[1], github=github, needs=needs) is False


@pytest.mark.parametrize('event,mode,actual,booking', [
    ('workflow_dispatch', 'initialize', 'initialize', 'false'),
    ('workflow_dispatch', 'observe', 'observe', 'false'),
    ('workflow_dispatch', 'refill', 'refill', 'true'),
    ('schedule', '', 'automatic', 'true'),
    ('workflow_run', '', 'automatic', 'true'),
])
def test_requested_mode_and_booking_permission_are_passed_without_shell_interpolation(event, mode, actual, booking):
    env = _text().split('      - name: Geschützte Sitzung und Gratis-Nachbuchung prüfen\n', 1)[1]
    github = SimpleNamespace(event_name=event)
    inputs = SimpleNamespace(mode=mode)
    mode_expr = re.search(r'ALDI_HOSTED_MODE: \$\{\{ (.*?) \}\}', env).group(1)
    book_expr = re.search(r'AUTO_BOOK_ENABLED: \$\{\{ (.*?) \}\}', env).group(1)
    assert _evaluate(mode_expr, github=github, inputs=inputs) == actual
    assert _evaluate(book_expr, github=github, inputs=inputs) == booking
    assert 'run: timeout 240s python aldi_hosted_runtime.py --mode "$ALDI_HOSTED_MODE"' in env


@pytest.mark.parametrize('field,value', [
    ('name', 'untrusted-workflow'), ('conclusion', 'failure'),
    ('head_branch', 'feature/untrusted'), ('event', 'pull_request'),
    ('head_repository', SimpleNamespace(full_name='foreign/fork')),
])
def test_mail_completion_never_elevates_untrusted_upstream(field, value):
    upstream = SimpleNamespace(name='ALDI Usage Mail Monitor', conclusion='success',
                               head_repository=SimpleNamespace(full_name='chhubeny90-cell/aldi-watcher'),
                               head_branch='main', event='schedule')
    setattr(upstream, field, value)
    github = SimpleNamespace(repository='chhubeny90-cell/aldi-watcher', ref='refs/heads/main',
                             event_name='workflow_run', run_attempt=1,
                             event=SimpleNamespace(workflow_run=upstream))
    conditions = re.findall(r'    if: >-\n(.*?)    runs-on:', _text(), re.S)
    needs = SimpleNamespace(preflight=SimpleNamespace(outputs=SimpleNamespace(ready='true')))
    assert not _evaluate(conditions[0], github=github)
    assert not _evaluate(conditions[1], github=github, needs=needs)


def test_secrets_are_scoped_to_execution_and_only_sanitized_result_is_uploaded():
    text = _text()
    before, execution = text.split('      - name: Geschützte Sitzung und Gratis-Nachbuchung prüfen\n', 1)
    execution, after = execution.split('      - name: Bereinigtes Ergebnis aufbewahren\n', 1)
    # Preflight receives only presence expressions; it never sees raw values.
    preflight = before.split('  runtime:\n', 1)[0]
    for expression in re.findall(r'\$\{\{ (secrets\..*?) \}\}', preflight):
        assert "!= ''" in expression
    assert 'ALDI_USER: ${{ secrets.ALDI_PROFILE_1_USER }}' in execution
    assert 'ALDI_EXPECTED_ACCOUNT: ${{ secrets.ALDI_PROFILE_1_USER }}' in execution
    assert 'ALDI_STATE_ENCRYPTION_KEY: ${{ secrets.ALDI_STATE_ENCRYPTION_KEY }}' in execution
    assert 'ALDI_REQUIRED_TARGET_SUFFIX: ${{ secrets.ALDI_REQUIRED_TARGET_SUFFIX }}' in execution
    assert 'vars.ALDI_REQUIRED_TARGET_SUFFIX' not in text
    assert 'secrets.ALDI_USER' not in execution
    assert 'GITHUB_TOKEN: ${{ github.token }}' in execution
    assert 'secrets.' not in after and 'GITHUB_TOKEN:' not in after
    assert 'path: aldi-hosted-report.json' in after
    assert 'path: |' not in after
    assert 'run: python aldi_hosted_runtime.py --summary-only' in after
    assert after.count('if: always()') == 2


@pytest.mark.parametrize('patch,ready', [
    ({}, True),
    ({'EXPECTED_ACCOUNT_CONFIGURED': 'false'}, False),
    ({'PASSWORD_CONFIGURED': 'false'}, False),
    ({'STATE_KEY_CONFIGURED': 'false'}, False),
    ({'TARGET_SUFFIX_CONFIGURED': 'false'}, False),
    ({'PASSWORD_KEY_REQUIRED': 'true'}, False),
    ({'PASSWORD_KEY_REQUIRED': 'true', 'PASSWORD_KEY_CONFIGURED': 'true'}, True),
])
def test_actual_preflight_requires_state_key_and_complete_credentials(tmp_path, monkeypatch, patch, ready):
    flags = {
        'EXPECTED_ACCOUNT_CONFIGURED': 'true', 'PASSWORD_CONFIGURED': 'true',
        'PASSWORD_KEY_REQUIRED': 'false', 'PASSWORD_KEY_CONFIGURED': 'false',
        'STATE_KEY_CONFIGURED': 'true',
        'TARGET_SUFFIX_CONFIGURED': 'true',
    }
    flags.update(patch)
    for name, value in flags.items():
        monkeypatch.setenv(name, value)
    output = tmp_path / 'output'
    summary = tmp_path / 'summary'
    monkeypatch.setenv('GITHUB_OUTPUT', str(output))
    monkeypatch.setenv('GITHUB_STEP_SUMMARY', str(summary))
    source = _text().split("          python - <<'PY'\n", 1)[1].split('          PY\n', 1)[0]
    exec(compile(textwrap.dedent(source), 'workflow-preflight', 'exec'), {})
    assert output.read_text() == 'ready=' + str(ready).lower() + '\n'
    assert summary.exists() is (not ready)
    if not ready:
        assert 'Einrichtung unvollständig' in summary.read_text()
        assert 'kein ALDI-Zugriff' in summary.read_text()
        if flags['STATE_KEY_CONFIGURED'] == 'false':
            assert 'ALDI_STATE_ENCRYPTION_KEY' in summary.read_text()
        if flags['TARGET_SUFFIX_CONFIGURED'] == 'false':
            assert 'ALDI_REQUIRED_TARGET_SUFFIX' in summary.read_text()


def test_shared_concurrency_and_minimal_permissions():
    text = _text()
    assert 'permissions:\n  contents: none\n' in text
    assert '    permissions:\n      contents: write' in text
    assert text.count('contents: write') == 1
    assert 'group: aldi-live-refill-profile-1' in text
    assert 'cancel-in-progress: false' in text
    assert 'persist-credentials: false' in text
    assert 'ref: ${{ github.sha }}' in text
    assert 'timeout-minutes: 8' in text
    assert 'runs-on: self-hosted' not in text
    assert 'actions/cache' not in text
    assert 'actions/checkout@v7.0.1' in text
    assert 'actions/setup-python@v7.0.0' in text
    assert 'browser-actions/setup-chrome@v2.2.0' in text
    assert 'actions/upload-artifact@v7.0.2' in text
