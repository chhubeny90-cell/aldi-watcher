import inspect

import aldi_live_refill as live


def test_live_runner_has_no_parallel_account_lock():
    source = inspect.getsource(live.main)
    assert '.account_lock(' not in source
    assert 'alditalk_executor' not in source
