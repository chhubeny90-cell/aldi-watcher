"""Drain queued manual refill reminders. SMTP acceptance != phone receipt or refill."""
import json
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage

from core import iphone_notification_outbox as outbox


def _email_settings():
    names = ("ALDI_NOTIFY_SMTP_HOST", "ALDI_NOTIFY_SMTP_USER",
             "ALDI_NOTIFY_SMTP_PASS", "ALDI_NOTIFY_FROM", "ALDI_REFILL_RECIPIENTS")
    if any(not os.environ.get(name, "").strip() for name in names):
        raise RuntimeError("smtp_configuration_missing")
    sender = os.environ["ALDI_NOTIFY_FROM"].strip()
    recipients = [value.strip() for value in
                  os.environ["ALDI_REFILL_RECIPIENTS"].replace(";", ",").split(",")
                  if value.strip()]
    if (not recipients or len(recipients) > 20
            or any("@" not in value or "\n" in value or "\r" in value
                   for value in [sender, *recipients])):
        raise RuntimeError("smtp_address_invalid")
    try:
        port = int(os.environ.get("ALDI_NOTIFY_SMTP_PORT") or "465")
    except ValueError:
        raise RuntimeError("smtp_port_invalid") from None
    if not 1 <= port <= 65535:
        raise RuntimeError("smtp_port_invalid")
    return (os.environ["ALDI_NOTIFY_SMTP_HOST"].strip(), port,
            os.environ["ALDI_NOTIFY_SMTP_USER"].strip(),
            os.environ["ALDI_NOTIFY_SMTP_PASS"], sender, recipients)


def _send(settings):
    host, port, user, password, sender, recipients = settings
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = "ALDI TALK: Datenvolumen verbraucht - manuell 1 GB pruefen"
    msg.set_content(
        "Der Mailmonitor hat ein neues Verbrauchssignal erkannt.\n\n"
        "Oeffne die offizielle ALDI-TALK-App und pruefe selbst die passende SIM, "
        "den aktiven Unlimited-Tarif und das Angebot: genau 1 GB, 0,00 EUR.\n"
        "Nur bei eindeutiger Anzeige einmal selbst buchen. Keine Wiederholung bei "
        "unklarem Ergebnis.\n\n"
        "Dies ist weder eine Buchung noch eine Providerbestaetigung.\n"
    )
    with smtplib.SMTP_SSL(host, port, timeout=20,
                          context=ssl.create_default_context()) as smtp:
        smtp.login(user, password)
        smtp.send_message(msg)


def drain(max_items=5):
    """Never retry an already SENDING/UNKNOWN item, including after a crash."""
    settings = _email_settings()  # Misconfiguration must not claim an event.
    delivered = 0
    for _ in range(max_items):
        key = outbox.claim_one()
        if key is None:
            return {"smtp_accepted": delivered, "ambiguous": 0}
        try:
            _send(settings)
        except Exception:
            outbox.finish(key, "UNKNOWN")
            return {"smtp_accepted": delivered, "ambiguous": 1}
        outbox.finish(key, "SMTP_ACCEPTED")
        delivered += 1
    return {"smtp_accepted": delivered, "ambiguous": 0}


def main():
    try:
        result = drain()
    except Exception:
        # Do not print SMTP-server responses or credentials in Actions logs.
        print(json.dumps({"status": "failed", "reason": "configuration_or_state_error"}))
        return 2
    print(json.dumps(result))
    return 2 if result["ambiguous"] else 0


if __name__ == "__main__":
    sys.exit(main())
