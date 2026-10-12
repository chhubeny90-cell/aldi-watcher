# Conditional free-refill execution

The source switches for the configured account checks and the separate manual
live-refill job are enabled. `all` and scheduled account checks remain read-only.
The manual `live-refill` job runs only on main after tests pass and requires a
configured persistent journal and a private self-hosted Linux runner labelled
`aldi-journal`. A prerequisite report exposes only configuration booleans, never
the journal path or credentials.

## Conditions checked for each NEW booking

- Selected SIM matches the configured account, with a protected navigation-list
  response in the same browser session.
- The visible eligible tariff and protected subscription signature remain the
  same before the action, any confirmation, and the refreshed volume check.
- Remaining volume is strictly below 1 GB. Exactly one enabled offer explicitly
  displays exactly 1 GB and 0 Euro. “kostenlos” alone is insufficient.
- No prior unresolved ALDI operation exists. Unknown account/provider mappings
  block execution rather than hide old reservations.
- One durable reservation is committed before clicking. The workflow performs
  at most one refill; a confirmation is repriced and revalidated before its click.
- A fresh protected volume increase greater than zero and no more than 1 GB
  confirms the new operation. Ambiguous results stay UNKNOWN and prevent retries.

A journal-wide executor lock plus the per-account lock prevent concurrent local
bookings. All workers must share the same durable journal; independent hosts or
journals are unsupported. The runner never replaces a lost or corrupt journal.

## Historical recovery

`ALDI_RECONCILIATION_VERIFIED` remains false. The existing provider-status adapter
cannot authoritatively recover a historical operation. Old PENDING/UNKNOWN records
remain blocked; neither present volume nor a reoffered button clears them.
Provider receipt lookup or another authoritative reconciliation mechanism is
still needed after an uncertain or crashed booking.

## Actual runtime evidence

The diagnostic on main after workflow activation did not confirm a portal session:
[run 38287286880](https://github.com/chhubeny90-cell/aldi-watcher/actions/runs/38287286880).
It timed out at the protected-page probe, and captured authentication-response
metadata was unavailable. This does not establish a current account lock or an
incorrect password.

The production login now submits through one native Chrome pointer activation
instead of JavaScript `element.click()`. The read-only pointer diagnostic uses
the same protected profile credentials. A fresh successful login and a real free
refill have not yet been demonstrated by these code changes. No mail-triggered
deployment is established by enabling the manual workflow.

Validation: the full local suite passed with 336 tests and 12 subtests, including
paid/malformed offers, account changes, failed confirmation, unresolved aliases,
concurrent execution and uncertain pointer activation. These tests use simulated
provider/browser responses and do not prove a real ALDI booking.
