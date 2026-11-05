"""Offline regressions for the retired webapp action surface.

These tests use Flask's in-memory test client and make no provider requests.
"""

from pathlib import Path

import pytest

from webapp.app import app


@pytest.fixture
def client():
    app.config.update(TESTING=True)
    with app.test_client() as test_client:
        yield test_client


def test_dashboard_is_passive_and_has_no_credentials_or_actions(client):
    response = client.get("/")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Automatische Nachbuchung deaktiviert" in html
    assert 'type="password"' not in html
    assert 'id="startButton"' not in html
    assert "/api/start" not in html


@pytest.mark.parametrize("path", ["/api/config", "/api/start", "/api/stop", "/api/test"])
def test_legacy_mutating_routes_are_gone(client, path):
    response = client.post(path, data={
        "provider": "ALDI",
        "username": "should-never-be-saved",
        "password": "should-never-be-saved",
        "duration_minutes": "120",
    })
    assert response.status_code == 410
    assert response.json["ok"] is False
    assert "deaktiviert" in response.json["message"]


def test_status_does_not_claim_running_or_bookings(client):
    response = client.get("/api/status")
    assert response.status_code == 200
    assert response.json["running"] is False
    assert response.json["bookings"] == 0
    assert response.json["remaining_gb"] is None
    assert response.json["mode"] == "DISABLED"


def test_config_endpoint_never_exposes_legacy_account(client):
    response = client.get("/api/config")
    assert response.status_code == 200
    assert response.json == {"configured": False, "read_only": True}


def test_external_client_is_rejected(client):
    response = client.get("/api/status", environ_overrides={"REMOTE_ADDR": "192.0.2.25"})
    assert response.status_code == 403


def test_dns_rebinding_host_header_is_rejected(client):
    response = client.get("/api/status", headers={"Host": "attacker.example:8000"})
    assert response.status_code == 403


def test_browser_security_headers(client):
    response = client.get("/")
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'none'" in response.headers["Content-Security-Policy"]


def test_old_webapp_credential_storage_and_browser_clicks_cannot_regress():
    root = Path(__file__).resolve().parents[1]
    code = (root / "webapp" / "app.py").read_text(encoding="utf-8")
    ignore = (root / ".gitignore").read_text(encoding="utf-8")
    assert 'app.run(host="127.0.0.1"' in code
    assert "CONFIG_PATH" not in code
    assert "save_config(" not in code
    assert "safe_click" not in code
    assert "import watcher" not in code
    assert "selenium" not in code
    assert "webapp/local_config.json" in ignore
