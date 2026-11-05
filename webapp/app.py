"""Local, passive status page.

The former movie-mode web UI accepted unauthenticated requests, wrote provider
passwords to a plaintext JSON file and bypassed the durable recharge journal.
Until authentication, durable journaling, provider authorization and receipt
reconciliation are implemented and reviewed, no provider access is possible
through this service. This module deliberately does not import any watcher.
"""

from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

# Browser requests from another machine are not supported. In addition to
# binding to loopback, reject requests routed through a non-loopback host and
# Host headers that could be used for DNS rebinding.
_LOCAL_ADDRESSES = frozenset({"127.0.0.1", "::1"})
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "[::1]"})
_DISABLED = (
    "Webapp-Automation ist aus Sicherheitsgründen deaktiviert. "
    "Keine Anmeldung, Speicherung von Zugangsdaten oder Buchung möglich."
)


@app.before_request
def local_requests_only():
    hostname = request.host.rsplit(":", 1)[0]
    if request.remote_addr not in _LOCAL_ADDRESSES or hostname not in _LOCAL_HOSTS:
        return jsonify({"ok": False, "message": "Nur lokaler Zugriff erlaubt."}), 403


@app.after_request
def harden_response(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    )
    return response


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/config")
def get_config():
    # Never read or return the previous plaintext local_config.json.
    return jsonify({"configured": False, "read_only": True})


@app.get("/api/status")
def status():
    return jsonify({
        "running": False,
        "provider": None,
        "mode": "DISABLED",
        "remaining_gb": None,
        "bookings": 0,
        "last_check": None,
        "status": _DISABLED,
    })


def _disabled_action():
    return jsonify({"ok": False, "message": _DISABLED}), 410


# Preserve the old routes so existing clients receive an explicit failure
# instead of trying alternative or legacy implementations.
@app.post("/api/config")
def post_config():
    return _disabled_action()


@app.post("/api/start")
def start():
    return _disabled_action()


@app.post("/api/stop")
def stop():
    return _disabled_action()


@app.post("/api/test")
def test_both():
    return _disabled_action()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=False)
