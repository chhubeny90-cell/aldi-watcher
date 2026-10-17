"""Automatic local ALDI/LIDL Unlimited movie-mode web UI with combined read-only test mode.

First opening shows setup for provider, phone/email and password. Credentials
are stored locally. The dashboard can start Unlimited movie mode or run a
read-only test against both ALDI Talk and Lidl Connect.
"""

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, render_template, request
from selenium.webdriver.common.by import By

import watcher
from core.aldi_refill import locate_selenium as locate_aldi
from core.lidl_refill import assess_refill, configured_selectors

app = Flask(__name__)
CONFIG_PATH = Path(__file__).parent / "local_config.json"

NORMAL_INTERVAL = 60
TURBO_INTERVAL = 20
TURBO_THRESHOLD_GB = 1.2
BOOKING_THRESHOLD_GB = 1.0
ACTIVATION_WAIT_SECONDS = 15

state = {
    "running": False,
    "should_stop": False,
    "provider": "ALDI",
    "mode": "NORMAL",
    "remaining_gb": None,
    "bookings": 0,
    "last_check": None,
    "status": "Bereit.",
    "ends_at": None,
}
state_lock = threading.Lock()


def load_config():
    if not CONFIG_PATH.exists():
        return None
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_config(config):
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except Exception:
        pass


def apply_credentials(provider, username, password):
    if provider == "ALDI":
        os.environ["ALDI_USER"] = username
        os.environ["ALDI_PASS"] = password
    else:
        os.environ["LIDL_USER"] = username
        os.environ["LIDL_PASS"] = password


def update(**values):
    with state_lock:
        state.update(values)


def wait_seconds(total):
    for _ in range(total):
        if state["should_stop"]:
            return
        time.sleep(1)


def aldi_cycle(driver):
    status = watcher.aldi_read_status(driver, include_refill=False)
    remaining_gb = status.get("inland_frei_gb")
    mode = "TURBO" if remaining_gb is not None and remaining_gb <= TURBO_THRESHOLD_GB else "NORMAL"
    update(remaining_gb=remaining_gb, mode=mode, last_check=datetime.now().isoformat(timespec="seconds"))

    if remaining_gb is None or remaining_gb > BOOKING_THRESHOLD_GB:
        update(status="Ausreichend Highspeed verfügbar.")
        return

    result, control = locate_aldi(driver, remaining_gb)
    if not result.get("refill_eligible") or control is None:
        update(status="Unter 1 GB, aber kein verifizierter Gratis-Refill verfügbar.")
        return

    watcher.safe_click(driver, control)
    update(status="1 GB gebucht – warte auf Aktivierung…")
    wait_seconds(ACTIVATION_WAIT_SECONDS)

    after = watcher.aldi_read_status(driver, include_refill=False)
    with state_lock:
        state["bookings"] += 1
        state["remaining_gb"] = after.get("inland_frei_gb")
        state["status"] = "1 GB kostenlos nachgebucht."


def lidl_cycle(driver):
    status = watcher.lidl_read_status(driver)
    remaining_gb = status.get("inland_frei_gb")
    mode = "TURBO" if remaining_gb is not None and remaining_gb <= TURBO_THRESHOLD_GB else "NORMAL"
    update(remaining_gb=remaining_gb, mode=mode, last_check=datetime.now().isoformat(timespec="seconds"))

    selectors = configured_selectors()
    if not all(selectors.values()):
        update(status="Lidl-Selektoren fehlen – nur Überwachung aktiv.")
        return

    try:
        tariff = driver.find_element(By.CSS_SELECTOR, selectors["active_tariff"])
        offer = driver.find_element(By.CSS_SELECTOR, selectors["refill_offer"])
        button = offer.find_element(By.CSS_SELECTOR, selectors["refill_button"])
        enabled = button.is_enabled() and button.get_attribute("aria-disabled") != "true" and button.get_attribute("disabled") is None
        result = assess_refill(tariff.text, offer.text, button.text, enabled)

        if remaining_gb is not None and remaining_gb <= BOOKING_THRESHOLD_GB and result.get("refill_eligible"):
            watcher.safe_click(driver, button)
            update(status="Lidl 1-GB-Refill gebucht – warte auf Aktivierung…")
            wait_seconds(ACTIVATION_WAIT_SECONDS)
            after = watcher.lidl_read_status(driver)
            with state_lock:
                state["bookings"] += 1
                state["remaining_gb"] = after.get("inland_frei_gb")
                state["status"] = "Lidl 1 GB nachgebucht."
        else:
            update(status="Kein verifizierter kostenloser Lidl-Refill verfügbar.")
    except Exception as exc:
        update(status=f"Lidl-Prüfung fehlgeschlagen: {type(exc).__name__}")


def movie_mode(provider, duration_minutes):
    config = load_config()
    if not config:
        update(running=False, status="Keine Zugangsdaten gespeichert.")
        return

    apply_credentials(config["provider"], config["username"], config["password"])
    prefix = "ALDI" if provider == "ALDI" else "LIDL"

    if not watcher.configure_credentials(prefix):
        update(running=False, status=f"{prefix}-Zugangsdaten unvollständig.")
        return

    driver = None
    deadline = time.monotonic() + duration_minutes * 60

    try:
        driver = watcher.build_driver()
        login_ok = watcher.aldi_login(driver) if provider == "ALDI" else watcher.lidl_login(driver)
        if not login_ok:
            update(running=False, status=f"{prefix}-Login fehlgeschlagen.")
            return

        update(running=True, should_stop=False, provider=provider, mode="NORMAL", status="Unlimited Filmmodus aktiv.")

        while time.monotonic() < deadline and not state["should_stop"]:
            if provider == "ALDI":
                aldi_cycle(driver)
            else:
                lidl_cycle(driver)

            interval = TURBO_INTERVAL if state["mode"] == "TURBO" else NORMAL_INTERVAL
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            wait_seconds(min(interval, int(remaining)))

        update(running=False, status="Filmmodus beendet.")
    except Exception as exc:
        update(running=False, status=f"Fehler: {type(exc).__name__}")
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


def run_read_only_test():
    """Test both providers without clicking any refill control."""
    results = {}

    aldi_config = load_config()
    if aldi_config:
        apply_credentials("ALDI", aldi_config["username"], aldi_config["password"])
        if watcher.configure_credentials("ALDI"):
            driver = None
            try:
                driver = watcher.build_driver()
                if watcher.aldi_login(driver):
                    status = watcher.aldi_read_status(driver, include_refill=False)
                    remaining_gb = status.get("inland_frei_gb")
                    refill = None
                    if remaining_gb is not None and remaining_gb <= BOOKING_THRESHOLD_GB:
                        refill, _ = locate_aldi(driver, remaining_gb)
                    results["ALDI"] = {
                        "ok": True,
                        "remaining_gb": remaining_gb,
                        "refill_available": bool(refill and refill.get("refill_eligible")),
                        "refill_reason": refill.get("refill_reason") if refill else "above_booking_threshold",
                    }
                else:
                    results["ALDI"] = {"ok": False, "error": "login_failed"}
            except Exception as exc:
                results["ALDI"] = {"ok": False, "error": type(exc).__name__}
            finally:
                if driver:
                    try:
                        driver.quit()
                    except Exception:
                        pass

    lidl_config = load_config()
    if lidl_config:
        apply_credentials("LIDL", lidl_config["username"], lidl_config["password"])
        if watcher.configure_credentials("LIDL"):
            driver = None
            try:
                driver = watcher.build_driver()
                if watcher.lidl_login(driver):
                    status = watcher.lidl_read_status(driver)
                    remaining_gb = status.get("inland_frei_gb")
                    selectors = configured_selectors()
                    refill_available = False
                    reason = "selectors_unconfigured"
                    if all(selectors.values()):
                        tariff = driver.find_element(By.CSS_SELECTOR, selectors["active_tariff"])
                        offer = driver.find_element(By.CSS_SELECTOR, selectors["refill_offer"])
                        button = offer.find_element(By.CSS_SELECTOR, selectors["refill_button"])
                        enabled = button.is_enabled() and button.get_attribute("aria-disabled") != "true" and button.get_attribute("disabled") is None
                        refill = assess_refill(tariff.text, offer.text, button.text, enabled)
                        refill_available = bool(refill.get("refill_eligible"))
                        reason = refill.get("refill_reason")
                    results["LIDL"] = {
                        "ok": True,
                        "remaining_gb": remaining_gb,
                        "refill_available": refill_available,
                        "refill_reason": reason,
                    }
                else:
                    results["LIDL"] = {"ok": False, "error": "login_failed"}
            except Exception as exc:
                results["LIDL"] = {"ok": False, "error": type(exc).__name__}
            finally:
                if driver:
                    try:
                        driver.quit()
                    except Exception:
                        pass

    return results


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/config")
def get_config():
    config = load_config()
    if not config:
        return jsonify({"configured": False})
    return jsonify({
        "configured": True,
        "provider": config["provider"],
        "username": config["username"],
    })


@app.post("/api/config")
def post_config():
    provider = request.form.get("provider", "ALDI").upper()
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    if provider not in {"ALDI", "LIDL"} or not username or not password:
        return jsonify({"ok": False, "message": "Anbieter, Benutzername und Passwort sind erforderlich."})

    save_config({"provider": provider, "username": username, "password": password})
    return jsonify({"ok": True, "message": "Zugangsdaten lokal gespeichert."})


@app.get("/api/status")
def status():
    with state_lock:
        return jsonify(state)


@app.post("/api/start")
def start():
    config = load_config()
    if not config:
        return jsonify({"ok": False, "message": "Bitte zuerst anmelden."})

    with state_lock:
        if state["running"]:
            return jsonify({"ok": False, "message": "Filmmodus läuft bereits."})

    try:
        duration = int(request.form.get("duration_minutes", "120"))
    except ValueError:
        duration = 120
    duration = min(max(duration, 15), 360)

    update(should_stop=False, provider=config["provider"], bookings=0, remaining_gb=None, mode="NORMAL")
    threading.Thread(target=movie_mode, args=(config["provider"], duration), daemon=True).start()
    return jsonify({"ok": True, "message": f"Unlimited Filmmodus für {duration} Minuten gestartet."})


@app.post("/api/stop")
def stop():
    update(should_stop=True, status="Stoppen angefordert…")
    return jsonify({"ok": True, "message": "Filmmodus wird gestoppt."})


@app.post("/api/test")
def test_both():
    """Read-only test for ALDI Talk and Lidl Connect. Never books."""
    results = run_read_only_test()
    return jsonify({"ok": True, "results": results})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)
