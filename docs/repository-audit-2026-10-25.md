# Safe repository audit — 2026-10-25

Baseline: main at `27d46e90c6ec8d640f2c75cc3abfb3af865b4e7a`. This is a read-only assessment; no authenticated provider action, refill, task registration or merge was performed.

## Verified inventory
- 34 open PRs and 4 open issues (GitHub search, 2026-10-25).
- Latest ALDI Watcher scheduled run **success**: [40181874217](https://github.com/chhubeny90-cell/aldi-watcher/actions/runs/40181874217). The documented `run.yml` tests/public probes do **not** prove a provider login or a free refill.
- Latest ALDI Usage Mail Monitor scheduled run **failure**: [40183910537](https://github.com/chhubeny90-cell/aldi-watcher/actions/runs/40183910537). Installation, monitor subprocess step (with `continue-on-error`) and artifact step succeeded; the final **Surface refill-ready mail or mailbox failure** step failed. The sanitized artifact contents were not inspected, so exact runtime cause is **unverified**.
- `.github/workflows/mail-trigger.yml` schedules hourly (`0 * * * *`), not every five minutes. The workflow deliberately returns exit 2 for configuration/mailing errors and exit 1 for actionable signals, so a red job does not by itself identify the underlying failure.
- [PR #122](https://github.com/chhubeny90-cell/aldi-watcher/pull/122) and [PR #124](https://github.com/chhubeny90-cell/aldi-watcher/pull/124) currently report `mergeable=false`, `mergeable_state=dirty` (conflicts). Do not merge without rebase, conflict resolution, and retesting.
- The README heading still calls the October 17 baseline current, and its October 14 historical subsection says five-minute mail polling. Those are historical claims only.

## Priorities and acceptance gates
1. **P0 mail diagnostics:** Inspect sanitized JSON from run 40183910537; distinguish `configuration_error`, `failed_mailboxes`, `actionable_alerts` before changing workflow exit handling. Never conceal configuration failure as success. Check IMAP account mapping and HMAC recovery-key continuity privately, not in PR logs.
2. **P0 safe refill:** Keep `DRY_RUN=true`, `AUTO_BOOK_ENABLED=false` and provider actions disabled. Require authenticated account-to-SIM match, verified tariff, unequivocal zero-cost offer, durable per-profile idempotency and official completion confirmation. Unknown outcome remains blocked, not retried.
3. **P1 PR triage:** Resolve overlapping safety contracts in #107/#114/#115/#117/#120/#121/#130/#132 before any deployment; treat #124 as local opt-in work and #137 as read-only LIDL assessment, not release approval. Recheck against current main because their reviews/CI can change.
4. **P1 CI:** Separate public-probe success, offline-test success, signal detected, configuration failure and verified production readiness in reporting. Keep the failures visible.
5. **P2 housekeeping:** Reconcile README, local configuration guide and branch-specific instructions. Audit 34 PRs for redundancy individually; do not mass-close unreviewed work.

## Change record
- 2026-10-25: Added this diagnostic/triage document on an isolated branch. No booking code, workflows, credentials, repository settings, PR states or live services changed.
