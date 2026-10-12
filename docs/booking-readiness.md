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
- Remaining volume is strictly below 1 GB and exactly one enabled local offer
  displays exactly 1 GB.
- A local `0 €` / `0,00 €` price is sufficient free-price evidence. When that
  numeric zero-price label is absent, only a uniquely identified active
  Unlimited tariff plus the same local Unlimited/On-Demand refill context may
  use ALDI's published free-refill entitlement. Generic `1 GB nachbuchen`,
  generic `kostenlos` wording, positive prices and unparsed currency markers
  remain blocked.
- No prior unresolved ALDI operation exists. Unknown account/provider mappings
  block execution rather than hide old reservations.
- One durable reservation is committed before clicking. The workflow performs
  at most one refill; a confirmation is repriced and revalidated before its click.
- A fresh protected volume increase greater than zero and no more than 1 GB is
  currently used only for the NEW same-session operation. Historical operations
  are not reconciled from volume or button state.

A journal-wide executor lock plus the per-account lock prevent concurrent local
bookings. All workers must share the same durable journal; independent hosts or
journals are unsupported. The runner never replaces a lost or corrupt journal.

## Durable journal bootstrap

Create the journal once on the private POSIX host that will run the
`aldi-journal` self-hosted runner:

```bash
python scripts/init_aldi_journal.py /absolute/private/path/aldi-live.sqlite
```

The bootstrap creates a missing SQLite journal with mode `0600`, initializes the
schema, validates an existing journal without replacing it, and rejects relative
paths, symlinks and broad file permissions. Configure the same absolute path as
the repository variable `ALDI_JOURNAL_PATH`. The file must remain outside the
GitHub checkout so a new checkout cannot replace runtime state.

## Historical recovery

`ALDI_RECONCILIATION_VERIFIED` remains false. No verified ALDI provider endpoint
has been found that maps the watcher's local operation ID to an authoritative
provider receipt. Old PENDING/UNKNOWN records therefore remain blocked; neither
present volume nor a reoffered button clears them. A provider receipt/status
lookup or another operation-bound authoritative signal is still required after
an uncertain or crashed booking.

Public research checked the official ALDI tariff pages and public automation
implementations again on 2026-10-12. They confirm the repeated free 1-GB action
below 1 GB, but the public implementations found only automate the UI button and
do not expose an authoritative per-booking receipt/status API.

## Current authentication evidence

The initial no-submit challenge probe on main captured the normal login challenge
without typing or submitting credentials. Proof-of-work was present, but the
provider account-lock key was not. No SMS request or portal write occurred.

The separately controlled single credential-submit diagnostic then received the
provider localization key `custom.alditalk.accountLock.accountLockMsg` and no
successful portal token/session. This means the account-lock indication appeared
as a response to credential submission rather than as part of the untouched
initial challenge. Further automated password attempts are intentionally stopped
until the account is restored through the normal provider flow.

The existing sanitized provider diagnostics already classify `accountLock` as an
account-lock indication without persisting provider response text or secrets.

## Deployment status

The controlled manual live-mode check previously passed tests but reported
`journal_path_configured=false`; the live-refill job was skipped and runner
availability was not established. The connected GitHub integration cannot update
repository variables or self-hosted runner administration. Those two deployment
items must be configured in GitHub/runner administration before the live job can
start.

PR #40 is merged on main. Its tests verify the fail-closed Unlimited entitlement
logic, including positive/mixed prices, malformed currency markers, generic
free-wording, exact 1.00-GB boundary, plain Tarif S and annual plans. A fresh
successful login and a real provider-confirmed free refill have not yet been
demonstrated.

No mail-triggered live deployment is established by enabling the manual workflow.
