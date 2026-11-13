# iPhone message-trigger sensor: strictly local dry run

**Status:** setup instructions, not deployed or proven on this iPhone. No
provider login, SMS forwarding, webhook, booking, or external event dispatch.
This is deliberately separate from the existing iPhone-assisted *reminder*
document and from the ALDI mail monitor.

## What Apple documents

Apple's Shortcuts User Guide lists **Message** among personal automation
triggers that can run automatically. A Message trigger may filter by sender
and/or message content. Whether specific message fields can be consumed by
subsequent actions, whether a given sender format matches, and how this behaves
with the phone locked must be verified on the actual device.

References:
- https://support.apple.com/guide/shortcuts/enable-or-disable-a-personal-automation-apd602971e63/ios
- https://support.apple.com/guide/shortcuts/communication-triggers-apdd711f9dff/ios

## Test 1: trigger reliability without collecting message contents

1. On the iPhone that **actually receives** the target SMS, open
   **Shortcuts -> Automation -> + -> Message**.
2. For an initial test, select a **trusted test sender** and an unmistakable
   harmless marker such as "WATCHER-SMS-TEST". Do not start with a real ALDI
   or LIDL sender and do not use a one-time code.
3. Where available choose **Run Immediately** / disable **Ask Before Running**.
   Configure the shortcut with only **Show Notification** and the fixed
   text "SMS sensor test triggered". Do **not** include the message, sender,
   number or other private information in this notification.
4. Have the trusted sender send the marker. Test once while the device is
   unlocked, then while locked. Record only: triggered yes/no, locked yes/no,
   manual confirmation required yes/no. A shortcut may require separate
   per-action permissions.
5. Disable the test automation after collecting the result.

A successful test proves only a trigger on that device. It does **not** prove
body extraction, correct SIM association, reliable delivery after device
restarts, an official provider confirmation, or a free 1-GB refill.

## Test 2: possible future provider-event input (not enabled)

Only after the local trigger has been verified:

- Inspect actual provider notification formats *on-device* without copying
  full SMS text, verification codes or phone numbers into GitHub.
- Classify an event as **untrusted notification evidence**. A sender label
  or SMS contents can be spoofed; no mail or SMS event alone may authorize
  an account action.
- If an event bridge is later designed, require HTTPS, authenticated requests,
  rate limiting, replay protection and an explicit server-side parser. Do not
  use a public ntfy topic or an unauthenticated GitHub dispatcher.
- Use the existing durable journal and UNKNOWN/PENDING fail-closed rules.
  Do not introduce a second writable state.json.
- Bookings remain disabled. A provider-specific, transaction-bound official
  acknowledgement and authorized account access must be established separately.

## Mailmonitor configuration (separate problem)

The current passive workflow expects repository Actions secrets
MAILBOX_2_USER and MAILBOX_2_PASS. The GitHub job provides
MAILBOX_2_HOST as a configured host or the gmail.com IMAP default when
MAILBOX_2_USER is present. The **presence-only** preflight prints whether
each variable is set, never its value or length, and then lets the existing
monitor produce the authoritative sanitized failure report.

To repair missing mailbox configuration, open GitHub repository
**Settings -> Secrets and variables -> Actions**. Verify the exact secret
names and that they are accessible to scheduled workflows on main. Never
paste the secret values into an issue, a commit, a log or chat.

After correcting them, dispatch **ALDI Usage Mail Monitor** with
**connection_only=true** to perform a read-only IMAP authentication and
INBOX select. This is not a provider login, email-processing test, booking,
or permission to activate a live refill.
