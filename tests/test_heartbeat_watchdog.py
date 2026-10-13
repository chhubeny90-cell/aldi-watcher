from datetime import datetime, timezone

import heartbeat_watchdog as watchdog


class Response:
    def __init__(self, status_code=204):
        self.status_code = status_code


def test_fresh_heartbeat_does_not_dispatch(monkeypatch):
    monkeypatch.setenv("ALDI_WATCHDOG_RECOVERY", "true")
    monkeypatch.setattr(watchdog, "heartbeat_age_seconds", lambda: 120.0)
    monkeypatch.setattr(
        watchdog,
        "claim_trigger_key",
        lambda key: (_ for _ in ()).throw(AssertionError("claim must not run")),
    )

    assert watchdog.main() == 0


def test_stale_heartbeat_dispatches_one_guarded_repository_event(monkeypatch):
    monkeypatch.setenv("ALDI_WATCHDOG_RECOVERY", "true")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "private-token")
    monkeypatch.setattr(watchdog, "heartbeat_age_seconds", lambda: 1900.0)
    claimed = []
    monkeypatch.setattr(watchdog, "claim_trigger_key", lambda key: claimed.append(key) or True)
    calls = []

    def post(url, headers, json, timeout):
        calls.append((url, headers, json, timeout))
        return Response(204)

    monkeypatch.setattr(watchdog.requests, "post", post)

    assert watchdog.main() == 0
    assert len(claimed) == 1
    assert claimed[0].startswith("watchdog-recovery:")
    assert calls[0][0] == "https://api.github.com/repos/owner/repo/dispatches"
    assert calls[0][2] == {
        "event_type": "aldi-watchdog-recovery",
        "client_payload": {"source": "heartbeat-watchdog"},
    }


def test_duplicate_recovery_in_same_hour_fails_without_second_dispatch(monkeypatch):
    monkeypatch.setenv("ALDI_WATCHDOG_RECOVERY", "true")
    monkeypatch.setattr(watchdog, "heartbeat_age_seconds", lambda: 1900.0)
    monkeypatch.setattr(watchdog, "claim_trigger_key", lambda key: False)
    monkeypatch.setattr(
        watchdog.requests,
        "post",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("dispatch must not run")),
    )

    assert watchdog.main() == 2


def test_dispatch_failure_is_fail_closed(monkeypatch):
    monkeypatch.setenv("ALDI_WATCHDOG_RECOVERY", "true")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "private-token")
    monkeypatch.setattr(watchdog, "heartbeat_age_seconds", lambda: None)
    monkeypatch.setattr(watchdog, "claim_trigger_key", lambda key: True)
    monkeypatch.setattr(watchdog.requests, "post", lambda *args, **kwargs: Response(500))

    assert watchdog.main() == 2


def test_hourly_recovery_key_is_stable_within_hour_and_changes_next_hour():
    first = datetime(2026, 10, 13, 11, 1, tzinfo=timezone.utc)
    same = datetime(2026, 10, 13, 11, 59, tzinfo=timezone.utc)
    next_hour = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)

    assert watchdog._hourly_recovery_key(first) == watchdog._hourly_recovery_key(same)
    assert watchdog._hourly_recovery_key(first) != watchdog._hourly_recovery_key(next_hour)
