# Guarded refill deployment

The user authorized repeated free 1-GB refills on 17 October 2026. Paid offers
and tariff changes remain excluded. Authorization alone is not operational proof.

`ALDI Guarded Free Refill` provides two explicit manual modes. `preflight`
reports configuration booleans only and never logs in. `refill` requires passing
tests, a configured expected account and an existing private journal, then runs
`aldi_live_refill_contract.main()` on a private Linux runner labelled
`aldi-journal`. The journal must live outside the checkout and survive restarts.
Only one refill is attempted per run. This workflow has no booking schedule.

Required configuration:

- `ALDI_PROFILE_1_USER`: expected target SIM number, kept as a GitHub Secret.
- `ALDI_PASS` or `ALDI_PASS_ENC`: existing provider password.
- Optional `ALDI_LOGIN_USER`, `ALDI_USER_ENC`, with
  `CREDENTIAL_ENCRYPTION_KEY` for encrypted credentials.
- Repository variable `ALDI_JOURNAL_PATH`: absolute private SQLite journal path
  on that runner. Initialize once using `scripts/init_aldi_journal.py`.
- The configured mailbox and `ALDI_RECOVERY_KEY` are separate requirements for
  proving the real mail trigger. A ChatGPT Gmail connection supplies neither.

The runner now branches on the persisted recharge status and marks a cycle
verified only after a provider receipt passes the completion contract. A unique
SQLite index prevents one provider operation ID from binding multiple recharge
IDs, including after reopening the same durable journal. Evidence may be updated
idempotently but may not be rebound to a different operation or resource.

Do not substitute the older GitHub-hosted JSON guard adapter for this persistent
journal: that adapter only restores unresolved local operation guards and does
not preserve provider evidence or terminal-operation uniqueness across runs.

Remaining acceptance evidence is operational: a real mailbox trigger, successful
authentication, the selected SIM and free offer, and one provider-confirmed
refill. A green unit-test run does not establish any of those. Historical
PENDING/UNKNOWN operations remain blocked pending authoritative reconciliation.
The current mail monitor remains notification-only until this acceptance is
complete; no inferred success or retry may release an unresolved operation.
