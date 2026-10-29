"""Send one manual ALDI refill reminder per consumed-alert event.

This utility deliberately never accesses the provider or triggers a booking.
Pass a stable event identifier issued by the existing mail monitor; do not use
the mailbox display name or SIM number as identity.
"""
import argparse
import os
import smtplib
import sqlite3
import ssl
from email.message import EmailMessage
from pathlib import Path

def notify(event_id: str, database: Path) -> bool:
    if not event_id or len(event_id) > 200 or any(ord(ch) < 32 for ch in event_id):
        raise ValueError("invalid event id")
    database.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database, timeout=30) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS notifications (event_id TEXT PRIMARY KEY, state TEXT NOT NULL)")
        conn.execute("BEGIN IMMEDIATE")
        old = conn.execute("SELECT state FROM notifications WHERE event_id=?", (event_id,)).fetchone()
        if old:
            return False
        conn.execute("INSERT INTO notifications VALUES (?, 'pending')", (event_id,))
    # Do not automatically retry an ambiguous SMTP outcome: the message may
    # have been accepted even if the connection failed after DATA.
    try:
        required = ("ALDI_NOTIFY_SMTP_HOST", "ALDI_NOTIFY_SMTP_USER",
                    "ALDI_NOTIFY_SMTP_PASS", "ALDI_NOTIFY_FROM",
                    "ALDI_REFILL_RECIPIENTS")
        missing = [key for key in required if not os.environ.get(key)]
        if missing:
            raise RuntimeError("Missing notification configuration: " + ", ".join(missing))
        recipients = [x.strip() for x in os.environ["ALDI_REFILL_RECIPIENTS"].split(",") if x.strip()]
        if not recipients:
            raise ValueError("No recipients")
        message = EmailMessage()
        message["Subject"] = "ALDI TALK: 1-GB-Refill selbst pruefen"
        message["From"] = os.environ["ALDI_NOTIFY_FROM"]
        message["To"] = ", ".join(recipients)
        message.set_content(
            "Der Watcher meldet verbrauchtes Datenvolumen.\n"
            "Oeffne die offizielle ALDI-TALK-App selbst.\n"
            "Pruefe SIM, Unlimited-Tarif, genau 1 GB und explizit 0,00 EUR.\n"
            "Nur dann einmal selbst buchen. Bei unklarem Ergebnis nicht wiederholen.\n"
            "Dies ist keine Buchungsbestaetigung.\n"
        )
        with smtplib.SMTP_SSL(os.environ["ALDI_NOTIFY_SMTP_HOST"],
                              int(os.environ.get("ALDI_NOTIFY_SMTP_PORT", "465")),
                              context=ssl.create_default_context(), timeout=20) as smtp:
            smtp.login(os.environ["ALDI_NOTIFY_SMTP_USER"], os.environ["ALDI_NOTIFY_SMTP_PASS"])
            smtp.send_message(message)
    except Exception:
        with sqlite3.connect(database) as conn:
            conn.execute("UPDATE notifications SET state='unknown' WHERE event_id=?", (event_id,))
        raise
    with sqlite3.connect(database) as conn:
        conn.execute("UPDATE notifications SET state='sent' WHERE event_id=?", (event_id,))
    return True

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--db", default=os.getenv("ALDI_NOTIFY_DB", "state/iphone-notifications.db"))
    args = parser.parse_args()
    print("sent" if notify(args.event_id, Path(args.db)) else "already-handled")

if __name__ == "__main__":
    main()
