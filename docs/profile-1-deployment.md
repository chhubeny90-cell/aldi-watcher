# ALDI target profile – privacy-safe deployment notes

The active target SIM, tariff, mailbox linkage, and all other subscription
details must be verified inside the authenticated provider account before any
refill. The earlier user-reported SIM-to-mailbox mapping is not a provider
verification. Never identify the target from an email address or a four-digit
suffix alone. Do not publish real or partial phone numbers in source, tests,
issues, pull requests, logs, or workflow artifacts.

## Operating scope (confirmed 2026-10-26)

Maintain the existing single configured ALDI account. Limit changes to necessary
bug fixes and improvements that support reliable automated operation. Do not
add other phone numbers, compare unrelated accounts, try unrelated passwords,
or expand the deployment to additional profiles. Keep the hourly schedules,
durable state and duplicate protection in place. Existing target-account and
zero-price checks still apply to this one account.

The scheduled mail-monitor run 40274486428 on 2026-10-26 ran on main
`f3ade551` and reported one configured mailbox, `dedup_key_missing`,
and an unsuccessful read-only IMAP connection (`IMAPError`). Both
`ALDI_RECOVERY_KEY` and `ALDI_STATE_ENCRYPTION_KEY` were absent from
that job's environment. The dependent session run 40274521456 was skipped.
A scheduled workflow firing is therefore not proof of working end-to-end
automation.

Restore the required stable state/deduplication key through private repository
Secrets configuration and resolve the existing mailbox's IMAP authentication.
Preserve any existing encrypted state and journal; do not rotate keys blindly
or replace history with an empty state. Do not work around these failures by
disabling duplicate protection, suppressing errors, or adding another account.
Recheck the monitor and protected runtime after configuration is repaired.

Evidence: https://github.com/chhubeny90-cell/aldi-watcher/actions/runs/40274486428

## Private configuration

- GitHub Actions secret `ALDI_PROFILE_1_USER`: full target number.
- GitHub Actions secret `ALDI_PROFILE_1_LOGIN_USER`: optional separate login
  identifier, only when it differs from the target account identifier.
- GitHub Actions secret `ALDI_PASS`: login credential.
- GitHub Actions secret `ALDI_REQUIRED_TARGET_SUFFIX`: four-digit target
  cross-check, configured in repository settings, never hard-coded in YAML.
  Use a secret so Actions masks it in step headers; an ordinary repository
  variable is not masked there.
- The private runner must provide `ALDI_EXPECTED_ACCOUNT` when required;
  keep the full value outside repository files and logs.
- Mailbox credentials, recovery key, and private journal/runner are separate
  deployment requirements. Do not commit their contents.

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
