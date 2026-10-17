"""Exercise imports in fresh interpreters, independent of test collection stubs."""

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def run_isolated(source):
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(source)],
        cwd=ROOT, capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_package_and_base_import_without_heavy_dependencies():
    run_isolated('''
        import importlib.abc
        import sys

        class BlockHeavy(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname.split('.')[0] in {'aiohttp', 'playwright'}:
                    raise AssertionError('Heavy dependency imported: ' + fullname)

        sys.meta_path.insert(0, BlockHeavy())
        import plugins
        assert not any(name.startswith('plugins.') for name in sys.modules)
        assert set(plugins.__all__) <= set(dir(plugins))
        assert len(dir(plugins)) == len(set(dir(plugins)))
        from plugins import BaseWatcher
        from plugins.base_watcher import BaseWatcher as direct
        assert BaseWatcher is direct is plugins.BaseWatcher
        assert 'plugins.aldi_talk' not in sys.modules
        assert 'plugins.lidl_connect' not in sys.modules
        try:
            plugins.DoesNotExist
        except AttributeError:
            pass
        else:
            raise AssertionError('Unknown export accepted')
    ''')


@pytest.mark.parametrize('watcher,dependency', [
    ('AldiTalkWatcher', 'aiohttp'),
    ('LidlConnectWatcher', 'aiohttp'),
    ('LidlConnectWatcher', 'playwright'),
])
def test_missing_dependency_is_actionable_and_retryable(watcher, dependency):
    run_isolated(f'''
        import plugins
        from types import SimpleNamespace
        missing = ModuleNotFoundError('missing dependency', name={dependency!r})

        def fail(*args):
            raise missing

        plugins.import_module = fail
        try:
            from plugins import {watcher}
        except ImportError as exc:
            assert exc.__cause__ is missing
            assert {watcher!r} in str(exc)
            assert {dependency!r} in str(exc)
            assert 'pip install -r requirements.txt' in str(exc)
        else:
            raise AssertionError('Expected ImportError')
        assert {watcher!r} not in vars(plugins)
        sentinel = object()
        calls = []

        def succeed(*args):
            calls.append(args)
            return SimpleNamespace({watcher}=sentinel)

        plugins.import_module = succeed
        from plugins import {watcher}
        assert {watcher} is plugins.{watcher} is sentinel
        assert len(calls) == 1
    ''')


@pytest.mark.parametrize('error', [
    "RuntimeError('broken watcher')",
    "ImportError('incompatible dependency')",
    "ModuleNotFoundError('missing internal module', name='internal_bug')",
    "ModuleNotFoundError('broken install', name='aiohttp.internal_bug')",
])
def test_unrelated_errors_are_not_relabelled(error):
    run_isolated(f'''
        import plugins
        original = {error}

        def fail(*args):
            raise original

        plugins.import_module = fail
        try:
            plugins.AldiTalkWatcher
        except Exception as exc:
            assert exc is original
        else:
            raise AssertionError('Expected original error')
    ''')


@pytest.mark.parametrize('watcher,dependency', [
    ('AldiTalkWatcher', 'aiohttp'),
    ('LidlConnectWatcher', 'aiohttp'),
    ('LidlConnectWatcher', 'playwright'),
])
def test_real_watcher_import_with_blocked_dependency(watcher, dependency):
    run_isolated(f'''
        import importlib.abc
        import sys

        class BlockDependency(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == {dependency!r}:
                    raise ModuleNotFoundError('blocked dependency', name=fullname)

        sys.meta_path.insert(0, BlockDependency())
        import plugins
        try:
            from plugins import {watcher}
        except ImportError as exc:
            assert type(exc) is ImportError
            assert exc.__cause__.name == {dependency!r}
            assert {watcher!r} in str(exc)
            assert 'pip install' in str(exc)
        else:
            raise AssertionError('Expected ImportError')
    ''')
