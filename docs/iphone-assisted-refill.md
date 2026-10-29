# Assisted iPhone refill — real alternative to blocked portal automation

This is a **human-confirmed** handoff, not disguised unattended portal automation.
The watcher's verified consumed-volume mail event can produce a single reminder,
but the official ALDI TALK app must be opened and used by the account holder.

## What is implemented
`scripts/iphone_refill_reminder.py` takes a stable, deduplicated event ID from
the existing mail monitor and sends an ordinary email reminder using the
existing `ALDI_NOTIFY_*` SMTP settings. It records the event in persistent SQLite
before delivery. A failed/ambiguous SMTP result becomes `unknown`: **never
resend automatically**, to avoid duplicate prompts. No credentials or tokens
appear in the message; no ALDI portal request is sent.

Example, on a private persistent host after a **real consumed event**:

```bash
export ALDI_NOTIFY_DB=/var/lib/aldi-watcher/iphone-notifications.db
python -m scripts.iphone_refill_reminder --event-id '<stable monitored message id>'
```

The database must not be on an ephemeral GitHub runner. Do not wire the command
directly after a mail-monitor claim until event identity and delivery handoff
are durably connected; otherwise mail-monitor crashes can lose alerts.

## iPhone quick action
1. In Apple's **Shortcuts** app, create a shortcut named `ALDI 1 GB`.
2. Add **Open App** and choose the official ALDI TALK app.
3. Add the shortcut to the Home Screen. Leave the login and refill buttons
   inside the official app. No unverified URL scheme or screen-coordinate tap.
4. Enable email notifications for the reminder sender. When an actual consumed
   alert arrives, use the Home Screen shortcut, verify the target SIM, tariff,
   exactly 1 GB and explicit **0.00 EUR**; tap the refill button yourself **once**.
5. Confirm completion in the official provider interface. At an unknown outcome
   do not tap twice.

This is a manual booking, and the shortcut merely opens the app. A fully
autonomous ALDI button press is *not* delivered.

## Remaining wiring
- Persistently map actual consumed mail IDs to target account without guessing.
- Integrate a durable monitor-to-reminder outbox (the current monitor claims
  before downstream delivery; adding a naïve notification step loses events).
- Prove SMTP configuration and test a reminder on a private host.
- Obtain authorized provider integration before attempting autonomous booking.

No automatic booking, CI deployment, provider login, or live run is implied.
