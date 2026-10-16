# iPhone refill handoff — readiness, 2026-10-16

## Verified scope

`refill_link_notify.py` creates an HMAC-signed request and can email an HTTPS
activation URL with the token in its fragment. `refill_link_accept.accept` verifies
that request and atomically records it once in SQLite. Acceptance returns
`pending`, never booking success. No ALDI credentials belong in the link.

## Integration contract

The HTTPS activation service must obtain the fragment on the client and submit
it explicitly in a POST body to its own trusted backend. GET, HEAD, email previews
and link scanners must never consume tokens or trigger provider actions. Never
put the signing key in browser JavaScript or an iPhone shortcut. The backend uses
the same signing key and expected profile as the issuer and a persistent SQLite
database shared by all workers. Do not use ephemeral runner storage.

A duplicate request must return a conflict without invoking a provider action.
An accepted request must remain pending until its outcome is reconciled; do not
retry an uncertain provider action. This module only reserves the request: the
provider adapter, worker recovery and official booking confirmation remain open.

## Required configuration

Mail reader: `MAILBOX_1_HOST`, `MAILBOX_1_USER`, `MAILBOX_1_PASS`,
`ALDI_RECOVERY_KEY`. Mail sender: `ALDI_NOTIFY_SMTP_HOST`,
`ALDI_NOTIFY_SMTP_USER`, `ALDI_NOTIFY_SMTP_PASS`, `ALDI_NOTIFY_FROM`,
`ALDI_REFILL_RECIPIENTS`. Links: `ALDI_ACTIVATION_BASE_URL`,
`ALDI_LINK_SIGNING_KEY` (at least 32 bytes). Optional SMTP port defaults to 465.
Link lifetime defaults to 900 seconds.

The mail-trigger workflow currently does NOT call the sender. Do not simply add
a sender step: the monitor claims a mail before delivery. A delivery failure
would then suppress retries. A durable outbox with delivery acknowledgement must
be implemented before connecting these stages.

## Release gates

- [ ] Mail credentials available to Actions; real consumed mail recognized.
- [ ] Durable notification outbox retries SMTP failure without losing a trigger.
- [ ] HTTPS activation service deployed with persistent state and explicit POST.
- [ ] Existing iPhone shortcut inspected or a concrete shortcut installed.
- [ ] Link delivered and accepted exactly once on the actual iPhone.
- [ ] Correct SIM and verified free Unlimited refill identified.
- [ ] Official provider confirmation tied to the request; uncertain state blocked.

No end-to-end or live-booking release is granted by unit tests alone.
