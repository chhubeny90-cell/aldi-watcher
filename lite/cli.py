"""Private local commands and an authenticated Gmail Pub/Sub listener."""

import argparse
import json
import signal
import tempfile
import threading
from collections import Counter
from dataclasses import asdict, replace
from pathlib import Path

from .models import MailEvent
from .runtime import (MailRuntime, RuntimeConfig, RuntimeErrorClass, classified,
                      process_event, serve)


def _print(value):
    print(json.dumps(value, separators=(",", ":"), sort_keys=True), flush=True)


def _mail_runtime(config):
    from .mail import GmailClient
    return MailRuntime(config, GmailClient(config.mailbox))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Event-driven ALDI Watcher LITE")
    commands = parser.add_subparsers(dest="command", required=True)
    event = commands.add_parser("event", help="DRY_RUN a private local event JSON")
    event.add_argument("--event-file", required=True)
    commands.add_parser("recover", help="Reconcile durable pending bookings; never book")
    commands.add_parser("login-probe", help="Read-only login probe; no page content output")
    check = commands.add_parser("mailbox-check", help="Bounded read-only ALDI mail check")
    check.add_argument("--limit", type=int, default=10)
    check.add_argument("--max-age-seconds", type=float, default=3600)
    check.add_argument("--dry-run-events", action="store_true")
    commands.add_parser("mailbox-init", help="Explicit initial cursor at verified mailbox current state")
    commands.add_parser("watch-renew", help="Register/renew Gmail watch without touching ALDI")
    poll = commands.add_parser("mailbox-poll", help="Optional Gmail-only polling fallback")
    poll.add_argument("--once", action="store_true")
    poll.add_argument("--interval", type=float, default=60)
    listener = commands.add_parser("serve", help="Google-signed Pub/Sub push listener")
    listener.add_argument("--bind", default="0.0.0.0")
    listener.add_argument("--port", type=int, default=8080)
    args = parser.parse_args(argv)
    try:
        config = RuntimeConfig.from_env()
        if args.command == "event":
            if not config.dry_run:
                raise RuntimeErrorClass("local_event_requires_dry_run")
            path = Path(args.event_file)
            if path.stat().st_size > 65536:
                raise RuntimeErrorClass("event_file_too_large")
            event = MailEvent(**json.loads(path.read_text()))
            if event.mailbox.lower() != config.mailbox or event.account != config.account:
                raise RuntimeErrorClass("mail_event_mapping_invalid")
            result = process_event(config, event)
            # recharge_id is an internal random transaction ID, not a credential.
            _print(asdict(result))
            return 0 if result.status in {"SUCCESS", "DRY_RUN", "NO_ACTION", "DUPLICATE"} else 1
        if args.command == "recover":
            from .engine import Engine
            from .portal import AldiPortal
            engine = Engine(config.database_path, AldiPortal(), config.account,
                            dry_run=config.dry_run,
                            recent_success_guard_seconds=config.recent_success_guard_seconds)
            results = engine.recover_pending()
            pending = engine.store.get_unresolved_recharges(engine.PROVIDER, config.account)
            clear = not pending and not any(
                result.status in {"BUSY", "BLOCKED", "UNKNOWN"}
                or (result.status == "FAILED" and result.action != "RECONCILED")
                for result in results)
            _print({"recovery_results": len(results),
                    "statuses": dict(Counter(result.status for result in results)),
                    "error_classes": dict(Counter(result.error_class for result in results if result.error_class)),
                    "remaining_unresolved": len(pending), "recovery_clear": clear})
            return 0 if clear else 1
        if args.command == "login-probe":
            from .portal import AldiPortal
            portal = AldiPortal()
            try:
                portal.login()
                confirmed = bool(portal._session())
                _print({"login_confirmed": confirmed,
                        "provider_flow_configured": bool(portal.config.configured())})
            finally:
                portal.close()
            return 0 if confirmed else 1
        runtime = _mail_runtime(config)
        if args.command == "mailbox-check":
            runtime.gmail.get_profile()
            events = runtime.gmail.scan_recent(config.account, args.limit, args.max_age_seconds)
            output = {"mailbox_verified": True, "relevant_events": len(events),
                      "kinds": dict(Counter(event.kind for event in events))}
            if args.dry_run_events:
                # Never consume the live event journal while testing historic mail.
                with tempfile.TemporaryDirectory(prefix="aldi-lite-dry-") as directory:
                    isolated = replace(config, dry_run=True, database_path=str(Path(directory) / "dry.sqlite"))
                    results = [process_event(isolated, event) for event in events]
                    output["dry_run_statuses"] = dict(Counter(result.status for result in results))
            _print(output)
        elif args.command == "mailbox-init":
            _print(runtime.initialize())
        elif args.command == "watch-renew":
            _print(runtime.renew_watch())
        elif args.command == "serve":
            serve(runtime, args.bind, args.port)
        elif args.command == "mailbox-poll":
            if not 60 <= args.interval <= 86400:
                raise RuntimeErrorClass("mail_poll_interval_must_be_at_least_60_seconds")
            if args.once:
                _print(runtime.poll_once())
            else:
                stopped = threading.Event()
                for sig in (signal.SIGTERM, signal.SIGINT):
                    signal.signal(sig, lambda *_: stopped.set())
                while not stopped.is_set():
                    try:
                        output = runtime.poll_once()
                        if output["events"]:
                            _print(output)
                    except Exception as error:
                        _print({"error_class": classified(error, "mail_poll_failed")})
                    stopped.wait(args.interval)
        return 0
    except Exception as error:
        _print({"error_class": classified(error, "command_failed")})
        return 1
