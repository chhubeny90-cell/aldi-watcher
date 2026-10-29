# ALDI target profile – privacy-safe deployment notes

## Current status (2026-10-29): provider automation disabled

ALDI login, authenticated status checks and refills are disabled in the current
GitHub workflows. `hosted-session.yml` has no schedule or runtime modes; a manual
dispatch only reports the block. Adding secrets does not activate it. Check the
account manually using [the current live-check guide](aldi-safe-manual-live-check.md).
See [the session-runtime status](github-session-runtime.md) for the prerequisites
of any future reassessment.

The active target SIM, tariff, mailbox linkage, and all other subscription
details must be verified inside the authenticated provider account before any
refill. The earlier user-reported SIM-to-mailbox mapping is not a provider
verification. Never identify the target from an email address or a four-digit
suffix alone. Do not publish real or partial phone numbers in source, tests,
issues, pull requests, logs, or workflow artifacts.

## Operating scope and historical evidence

Maintain the existing single configured ALDI account. Limit changes to necessary
bug fixes and improvements to the existing installation. Do not
add other phone numbers, compare unrelated accounts, try unrelated passwords,
or expand the deployment to additional profiles. The mail monitor remains
scheduled hourly and preserves durable state and duplicate protection; it
does not trigger any provider action. Existing target-account and zero-price
checks do not override the disabled provider workflows.

The scheduled mail-monitor run 40274486428 on 2026-10-26 ran on main
`f3ade551` and reported one configured mailbox, `dedup_key_missing`,
and an unsuccessful read-only IMAP connection (`IMAPError`). Both
`ALDI_RECOVERY_KEY` and `ALDI_STATE_ENCRYPTION_KEY` were absent from
that job's environment. The dependent session run 40274521456 was skipped.
A scheduled workflow firing is therefore not proof of working end-to-end
automation.

For the mail monitor, configure the existing mailbox's `MAILBOX_1_USER` and
`MAILBOX_1_PASS` privately as repository Secrets (`MAILBOX_1_HOST` defaults to
`imap.gmail.com`; `MAILBOX_1_PORT` defaults to 993). Deduplication requires the
stable `ALDI_RECOVERY_KEY` or correctly configured `ALDI_STATE_ENCRYPTION_KEY`.
Resolve the mailbox's IMAP authentication before claiming successful monitoring.
Preserve any existing encrypted state and journal; do not rotate keys blindly
or replace history with an empty state. Do not work around these failures by
disabling duplicate protection, suppressing errors, or adding another account.
Recheck only the mail monitor after configuration is repaired. A working
mailbox does not prove an ALDI login, refill eligibility or booking.

Evidence: https://github.com/chhubeny90-cell/aldi-watcher/actions/runs/40274486428

## Historical provider configuration (inactive)

The following names describe preserved provider code, not current setup steps.
Do not add or alter ALDI login secrets to try to activate a disabled workflow.
Do not invoke the old runtime directly or restore an old workflow to bypass it.

- GitHub Actions secret `ALDI_PROFILE_1_USER`: full target number.
- GitHub Actions secret `ALDI_PROFILE_1_LOGIN_USER`: optional separate login
  identifier, only when it differs from the target account identifier.
- GitHub Actions secret `ALDI_PASS`: login credential.
- GitHub Actions secret `ALDI_REQUIRED_TARGET_SUFFIX`: four-digit target
  cross-check, configured in repository settings, never hard-coded in YAML.
  Use a secret so Actions masks it in step headers; an ordinary repository
  variable is not masked there.
- The former private-runner path used `ALDI_EXPECTED_ACCOUNT` when required;
  keep the full value outside repository files and logs.
- Mailbox credentials and the stable deduplication key are separate from this
  inactive provider configuration. Do not commit any secret contents.

The suffix is an additional consistency check, not identity proof. The full
selected-account identity and active subscription must match independently.
Missing configuration must fail closed. A successful preflight is not proof
of a live login or refill eligibility. Do not assume a free 1-GB offer from
the plan name or a message's wording; require an authenticated, current
offer with an explicit zero price and a confirmed transaction receipt.

## Privacy remediation note

Historic commits or artifacts may still expose older example-like values
after current files are updated. Check repository history, forks, caches and
public Actions artifacts independently; code edits do not erase history.
Never put the original sensitive values into a public remediation issue.
Do not rewrite published Git history without a separately planned,
coordinated cleanup; replacing a real leaked password requires rotation,
not merely editing the repository.

This document does not configure secrets, start a runner, authorize any
booking, or prove a successful provider login.
