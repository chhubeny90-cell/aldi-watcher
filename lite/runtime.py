"""Durable Gmail transport. Only verified mail events reach the one-shot LITE engine."""

import base64
import binascii
import fcntl
import hashlib
import json
import math
import os
import re
import signal
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .models import MailEvent, ProcessResult


class RuntimeErrorClass(RuntimeError):
    """Messages are fixed classifications, never upstream response bodies."""


def classified(error, fallback="runtime_failed"):
    # Only our fixed error classes may contribute text. Arbitrary exception
    # messages can contain passwords, OAuth tokens or upstream response bodies.
    if isinstance(error, RuntimeErrorClass) or type(error).__module__ == "lite.mail":
        value = str(error)
    elif type(error).__module__ == "lite.portal":
        value = getattr(error, "error_class", "")
    else:
        value = ""
    return value if re.fullmatch(r"[a-z][a-z0-9_]{0,63}", value) else fallback


def log_event_result(result, timestamp=None):
    """One UTC line containing only fixed steps/status and a classified code."""
    steps = {
        "CHECK": "CHECK", "REFILL": "CHECK → REFILL",
        "WOULD_REFILL": "CHECK → WOULD_REFILL", "IGNORE": "IGNORE",
        "RETRY": "RETRY", "RECONCILED": "RECONCILE",
        "PROVIDER_CHECK_REQUIRED": "PROVIDER_CHECK_REQUIRED",
        "HUMAN_ACTION_REQUIRED": "HUMAN_ACTION_REQUIRED",
    }
    statuses = {"SUCCESS", "DRY_RUN", "NO_ACTION", "DUPLICATE", "BUSY",
                "REJECTED", "FAILED", "UNKNOWN", "BLOCKED"}
    action = steps.get(result.action, "INVALID_RESULT")
    status = result.status if result.status in statuses else "INVALID_RESULT"
    stamp = datetime.fromtimestamp(time.time() if timestamp is None else timestamp,
                                   timezone.utc).strftime("%H:%M")
    line = f"{stamp} MAIL → {action} → {status}"
    if result.error_class:
        error = result.error_class
        code = error if isinstance(error, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", error) else "UNCLASSIFIED_ERROR"
        line += " → " + code
    try:
        print(line, flush=True)
    except (OSError, UnicodeError):
        # A broken log pipe must not turn an already committed refill into an
        # indefinitely redelivered event. The SQLite journal remains available.
        pass


def _boolean(environ, name, default=False):
    value = environ.get(name, str(default)).strip().lower()
    if value not in {"true", "false"}:
        raise RuntimeErrorClass("boolean_configuration_invalid")
    return value == "true"


@dataclass(frozen=True)
class RuntimeConfig:
    database_path: str
    account: str
    mailbox: str
    dry_run: bool = True
    push_audience: str = ""
    push_service_account: str = ""
    push_subscription: str = ""
    watch_topic: str = ""
    recent_success_guard_seconds: float = 0

    @classmethod
    def from_env(cls, environ=None):
        environ = os.environ if environ is None else environ
        account = environ.get("ALDI_ACCOUNT_ALIAS", "").strip()
        mailbox = environ.get("ALDI_MAILBOX", "").strip().lower()
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,63}", account):
            raise RuntimeErrorClass("account_alias_missing_or_invalid")
        if not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", mailbox):
            raise RuntimeErrorClass("mailbox_mapping_missing_or_invalid")
        dry_run = _boolean(environ, "DRY_RUN", True)
        if not dry_run and not _boolean(environ, "AUTO_BOOK_ENABLED"):
            raise RuntimeErrorClass("live_booking_disabled")
        db_path = environ.get("LITE_DB_PATH", "").strip()
        if not dry_run and (not db_path or not Path(db_path).is_absolute()):
            raise RuntimeErrorClass("live_durable_database_path_required")
        if db_path == ":memory:":
            raise RuntimeErrorClass("durable_database_required")
        try:
            guard = float(environ.get("LITE_RECENT_SUCCESS_GUARD_SECONDS", "0"))
        except (TypeError, ValueError):
            raise RuntimeErrorClass("recent_success_guard_invalid") from None
        if not math.isfinite(guard) or guard < 0:
            raise RuntimeErrorClass("recent_success_guard_invalid")
        return cls(str(Path(db_path or "data/lite.sqlite").resolve()), account, mailbox,
                   dry_run, environ.get("PUBSUB_PUSH_AUDIENCE", ""),
                   environ.get("PUBSUB_SERVICE_ACCOUNT_EMAIL", ""),
                   environ.get("PUBSUB_SUBSCRIPTION", ""),
                   environ.get("GMAIL_PUBSUB_TOPIC", ""), guard)

    def validate_push(self):
        if not self.push_audience.startswith("https://"):
            raise RuntimeErrorClass("https_push_audience_required")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+@[A-Za-z0-9.-]+\.iam\.gserviceaccount\.com",
                            self.push_service_account):
            raise RuntimeErrorClass("push_service_account_required")
        if not re.fullmatch(r"projects/[A-Za-z0-9-]+/subscriptions/[A-Za-z0-9_.~+%-]+",
                            self.push_subscription):
            raise RuntimeErrorClass("push_subscription_required")


def process_event(config, event):
    # Imported here so mailbox setup, health checks and PRO never load a browser.
    from .engine import Engine
    from .portal import AldiPortal
    return Engine(config.database_path, AldiPortal(), config.account,
                  dry_run=config.dry_run,
                  recent_success_guard_seconds=config.recent_success_guard_seconds).process(event)


def google_claims(token, audience):
    from google.auth.transport.requests import Request
    from google.oauth2.id_token import verify_oauth2_token
    class BoundedRequest(Request):
        def __call__(self, *args, **kwargs):
            kwargs["timeout"] = 10
            return super().__call__(*args, **kwargs)
    return verify_oauth2_token(token, BoundedRequest(), audience=audience)


class MailRuntime:
    def __init__(self, config, gmail, processor=None, token_verifier=None):
        self.config, self.gmail = config, gmail
        self.processor = processor or (lambda event: process_event(config, event))
        self.token_verifier = token_verifier or google_claims
        path = Path(config.database_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(config.mailbox.encode()).hexdigest()[:24]
        self.lock_path = path.parent / (path.name + ".mail." + digest + ".lock")
        with self._connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS lite_mail_cursors (
                mailbox TEXT PRIMARY KEY, account TEXT NOT NULL,
                history_id TEXT NOT NULL, updated_at REAL NOT NULL,
                watch_expires_at REAL)""")
        os.chmod(path, 0o600)

    def _connect(self):
        return sqlite3.connect(self.config.database_path, timeout=10)

    @contextmanager
    def _transport_lock(self):
        fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeErrorClass("mail_transport_busy") from None
            yield
        finally:
            os.close(fd)

    def cursor(self):
        with self._connect() as conn:
            row = conn.execute("SELECT account,history_id FROM lite_mail_cursors WHERE mailbox=?",
                               (self.config.mailbox,)).fetchone()
        if row and row[0] != self.config.account:
            raise RuntimeErrorClass("mailbox_account_mapping_changed")
        return row[1] if row else None

    def _save_cursor(self, cursor):
        if not re.fullmatch(r"\d+", str(cursor)):
            raise RuntimeErrorClass("gmail_history_invalid")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT account,history_id FROM lite_mail_cursors WHERE mailbox=?",
                               (self.config.mailbox,)).fetchone()
            if row and row[0] != self.config.account:
                raise RuntimeErrorClass("mailbox_account_mapping_changed")
            if row and int(cursor) < int(row[1]):
                raise RuntimeErrorClass("gmail_cursor_regressed")
            conn.execute("""INSERT INTO lite_mail_cursors(mailbox,account,history_id,updated_at)
                VALUES(?,?,?,?) ON CONFLICT(mailbox) DO UPDATE SET
                history_id=excluded.history_id,updated_at=excluded.updated_at""",
                (self.config.mailbox, self.config.account, str(cursor), time.time()))

    def initialize(self):
        """Explicit first setup; preserve an existing cursor on repeated setup."""
        with self._transport_lock():
            profile = self.gmail.get_profile()
            if not self.cursor():
                self._save_cursor(profile["historyId"])
        return {"mailbox_verified": True, "cursor_initialized": True}

    def _durably_completed(self, event):
        with self._connect() as conn:
            try:
                row = conn.execute("""SELECT state,mailbox,mail_id,account,kind,received_at
                    FROM lite_events WHERE event_id=?""", (event.event_id,)).fetchone()
            except sqlite3.OperationalError:
                return False
        return row == ("COMPLETED", event.mailbox, event.mail_id, event.account,
                       event.kind, event.received_at)

    def _consume_locked(self, notification_history=None):
        previous = self.cursor()
        if previous is None:
            raise RuntimeErrorClass("gmail_cursor_not_initialized")
        if notification_history is not None and int(notification_history) <= int(previous):
            return {"events": 0, "duplicate": True}
        # A missing/expired history is a visible failure. Never silently reset it
        # or replay arbitrary old messages into a live account.
        events, next_cursor = self.gmail.events_since(previous, self.config.account)
        if not re.fullmatch(r"\d+", str(next_cursor)) or int(next_cursor) < int(previous):
            raise RuntimeErrorClass("gmail_cursor_regressed")
        if notification_history is not None and int(next_cursor) < int(notification_history):
            raise RuntimeErrorClass("gmail_history_not_caught_up")
        for event in events:
            if (not isinstance(event, MailEvent) or event.mailbox != self.config.mailbox
                    or event.account != self.config.account):
                raise RuntimeErrorClass("mail_event_mapping_invalid")
            result = self.processor(event)
            if result.status == "BUSY":
                log_event_result(result)
                raise RuntimeErrorClass("lite_busy")
            if not self._durably_completed(event):
                log_event_result(ProcessResult("FAILED", "CHECK", error_class="event_not_durably_completed"))
                raise RuntimeErrorClass("event_not_durably_completed")
            log_event_result(result)
        # Every individual event has committed before the batch cursor advances.
        # If a later event crashes, replay deduplicates the already committed ones.
        self._save_cursor(next_cursor)
        return {"events": len(events), "duplicate": False}

    def poll_once(self):
        with self._transport_lock():
            return self._consume_locked()

    def renew_watch(self):
        with self._transport_lock():
            if self.cursor() is None:
                raise RuntimeErrorClass("gmail_cursor_not_initialized")
            result = self.gmail.watch(self.config.watch_topic)
            with self._connect() as conn:
                conn.execute("UPDATE lite_mail_cursors SET watch_expires_at=? WHERE mailbox=?",
                             (int(result["expiration"]) / 1000, self.config.mailbox))
        # watch returns a current historyId. It MUST NOT replace the processing
        # cursor; doing so could skip unread events received during renewal.
        return {"watch_registered": True}

    def handle_push(self, authorization, payload):
        try:
            self.config.validate_push()
            if not isinstance(authorization, str) or not authorization.startswith("Bearer "):
                return 401, {"error_class": "push_auth_required"}
            token = authorization[7:]
            if not token or len(token) > 16384:
                return 401, {"error_class": "push_token_invalid"}
            try:
                claims = self.token_verifier(token, self.config.push_audience)
            except Exception:
                return 403, {"error_class": "push_identity_unverified"}
            if (not isinstance(claims, dict)
                    or claims.get("email") != self.config.push_service_account
                    or claims.get("email_verified") is not True
                    or claims.get("aud") != self.config.push_audience
                    or claims.get("iss") not in {"accounts.google.com", "https://accounts.google.com"}):
                return 403, {"error_class": "push_identity_unverified"}
            if (not isinstance(payload, dict)
                    or payload.get("subscription") != self.config.push_subscription
                    or not isinstance(payload.get("message"), dict)):
                return 400, {"error_class": "push_subscription_invalid"}
            encoded = payload["message"].get("data")
            if not isinstance(encoded, str) or len(encoded) > 32768:
                return 400, {"error_class": "push_data_invalid"}
            try:
                notification = json.loads(base64.b64decode(encoded, validate=True))
            except (ValueError, UnicodeError, binascii.Error):
                return 400, {"error_class": "push_data_invalid"}
            if (not isinstance(notification, dict)
                    or not isinstance(notification.get("emailAddress"), str)
                    or notification["emailAddress"].strip().lower() != self.config.mailbox
                    or not re.fullmatch(r"\d+", str(notification.get("historyId", "")))):
                return 400, {"error_class": "push_mailbox_or_history_invalid"}
            with self._transport_lock():
                result = self._consume_locked(str(notification["historyId"]))
            return 200, result
        except Exception as error:
            return 503, {"error_class": classified(error, "mail_processing_failed")}


def serve(runtime, bind="0.0.0.0", port=8080):
    from .supervisor import TransportSupervisor

    runtime.config.validate_push()
    if runtime.cursor() is None:
        raise RuntimeErrorClass("gmail_cursor_not_initialized")
    supervisor = TransportSupervisor(runtime)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # Never log authorization, mailbox, URL queries or body.

        def _reply(self, status, result):
            encoded = json.dumps(result, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self):
            if self.path == "/health":
                return self._reply(200, {"alive": True})
            if self.path == "/ready":
                report = supervisor.readiness()
                return self._reply(200 if report["transport_ready"] else 503, report)
            self._reply(404, {})

        def do_POST(self):
            if self.path != "/pubsub/gmail":
                return self._reply(404, {})
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 65536:
                    return self._reply(413, {"error_class": "push_body_size_invalid"})
                self.connection.settimeout(20)
                payload = json.loads(self.rfile.read(size))
            except (ValueError, UnicodeError, OSError):
                return self._reply(400, {"error_class": "push_json_invalid"})
            status, result = runtime.handle_push(self.headers.get("Authorization"), payload)
            self._reply(status, result)

    server = ThreadingHTTPServer((bind, port), Handler)
    # Finish an in-flight event on a normal container stop. A hard kill is still
    # safe through the durable reservation and redelivery paths.
    server.daemon_threads = False
    worker = threading.Thread(target=supervisor.run, name="gmail-maintenance")
    handlers = {}
    if threading.current_thread() is threading.main_thread():
        def stop(*_):
            supervisor.stopped.set()
            threading.Thread(target=server.shutdown, daemon=True).start()
        for sig in (signal.SIGTERM, signal.SIGINT):
            handlers[sig] = signal.signal(sig, stop)
    try:
        worker.start()
        server.serve_forever()
    finally:
        supervisor.stopped.set()
        server.server_close()
        worker.join()
        for sig, previous in handlers.items():
            signal.signal(sig, previous)
