import pytest

from lite.supervisor import TransportSupervisor
from tests.test_lite_runtime import Gmail, configured, mail, runtime


class Clock:
    value = 100.
    def __call__(self):
        return self.value


def test_no_false_ready_before_first_sync_and_no_idle_browser(configured):
    calls, clock = [], Clock()
    gmail = Gmail(configured.mailbox)
    app = runtime(configured, gmail, calls)
    app.initialize()
    supervisor = TransportSupervisor(app, clock=clock)
    assert supervisor.readiness()["transport_ready"] is False
    supervisor.tick()
    assert supervisor.readiness()["transport_ready"] is True
    assert supervisor.readiness()["booking_readiness"] == "not_assessed"
    assert calls == [] and gmail.reads == gmail.watches == 1
    supervisor.tick()
    assert gmail.reads == gmail.watches == 1
    clock.value += 300
    supervisor.tick()
    assert gmail.reads == 2 and gmail.watches == 1 and calls == []


def test_lost_push_is_caught_up_once_and_restart_preserves_cursor(configured):
    calls, clock = [], Clock()
    event = mail(configured)
    gmail = Gmail(configured.mailbox, [event])
    app = runtime(configured, gmail, calls)
    app.initialize()
    supervisor = TransportSupervisor(app, clock=clock)
    supervisor.tick()
    assert calls == ["inspect", "close"]
    assert app.cursor() == "20"
    # Replay after restart is safely deduplicated by the real engine/journal.
    resumed = runtime(configured, gmail, calls)
    TransportSupervisor(resumed, clock=clock).tick()
    assert calls.count("inspect") == 1 and resumed.cursor() == "20"


def test_expired_history_is_visible_and_never_reset(configured):
    from lite.mail import HistoryExpired
    clock = Clock()
    gmail = Gmail(configured.mailbox)
    app = runtime(configured, gmail)
    app.initialize()
    def expired(*args):
        raise HistoryExpired("gmail_history_expired")
    gmail.events_since = expired
    supervisor = TransportSupervisor(app, clock=clock)
    supervisor.tick()
    report = supervisor.readiness()
    assert not report["transport_ready"]
    assert report["error_classes"] == ["gmail_history_expired"]
    assert app.cursor() == "10"


def test_transient_failure_retries_bounded_and_recovers_without_secret_output(configured):
    clock = Clock()
    app = runtime(configured, Gmail(configured.mailbox))
    app.initialize()
    original, attempts = app.poll_once, []
    def flaky():
        attempts.append(True)
        if len(attempts) == 1:
            raise ValueError("private-token@example.com")
        return original()
    app.poll_once = flaky
    supervisor = TransportSupervisor(app, clock=clock)
    supervisor.tick()
    assert supervisor.readiness()["error_classes"] == ["transport_maintenance_failed"]
    clock.value += 59
    supervisor.tick()
    assert len(attempts) == 1
    clock.value += 1
    supervisor.tick()
    assert supervisor.readiness()["transport_ready"]
    assert len(attempts) == 2


def test_stalled_worker_and_stop_are_not_healthy(configured):
    clock = Clock()
    app = runtime(configured, Gmail(configured.mailbox))
    app.initialize()
    supervisor = TransportSupervisor(app, clock=clock)
    supervisor.tick()
    clock.value += 361
    assert not supervisor.readiness()["transport_ready"]
    supervisor.tick()
    assert supervisor.readiness()["transport_ready"]
    supervisor.stopped.set()
    assert not supervisor.readiness()["transport_ready"]


def test_daily_renew_does_not_skip_events(configured):
    clock = Clock()
    gmail = Gmail(configured.mailbox)
    app = runtime(configured, gmail)
    app.initialize()
    supervisor = TransportSupervisor(app, clock=clock)
    supervisor.tick()
    clock.value += 86400
    supervisor.tick()
    assert gmail.watches == 2 and app.cursor() == "20"


@pytest.mark.parametrize("value", [0, -1, 59, 3601, float("nan"), float("inf"), True])
def test_invalid_poll_interval_rejected(value):
    with pytest.raises(ValueError):
        TransportSupervisor(None, poll_seconds=value)


def test_http_liveness_is_separate_from_transport_readiness_and_stops_worker(configured, monkeypatch):
    import json
    import threading
    from urllib.error import HTTPError
    from urllib.request import urlopen
    from lite import runtime as runtime_module, supervisor as supervisor_module

    app = runtime(configured, Gmail(configured.mailbox))
    app.initialize()
    controller = TransportSupervisor(app)
    # Drive maintenance explicitly so the not-ready response is deterministic.
    controller.run = lambda: controller.stopped.wait(10)
    monkeypatch.setattr(supervisor_module, "TransportSupervisor", lambda _: controller)
    created, servers = threading.Event(), []
    server_class = runtime_module.ThreadingHTTPServer
    def capture(*args):
        server = server_class(*args)
        servers.append(server)
        created.set()
        return server
    monkeypatch.setattr(runtime_module, "ThreadingHTTPServer", capture)
    worker = threading.Thread(target=runtime_module.serve, args=(app, "127.0.0.1", 0))
    worker.start()
    assert created.wait(5)
    server = servers[0]
    base = "http://127.0.0.1:" + str(server.server_port)
    try:
        with urlopen(base + "/health", timeout=5) as response:
            assert json.load(response) == {"alive": True}
        with pytest.raises(HTTPError) as error:
            urlopen(base + "/ready", timeout=5)
        assert error.value.code == 503
        error.value.close()
        controller.tick()
        with urlopen(base + "/ready", timeout=5) as response:
            report = json.load(response)
            assert report["transport_ready"]
            assert report["booking_readiness"] == "not_assessed"
            assert configured.mailbox not in json.dumps(report)
    finally:
        server.shutdown()
        worker.join(5)
    assert not worker.is_alive() and controller.stopped.is_set()
