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

## Confirmed mail monitor root cause (job 121140543650)
The 2026-10-25 [job log](https://github.com/chhubeny90-cell/aldi-watcher/actions/runs/40183910537) explicitly reports `Monitor configuration incomplete: dedup_key_missing` and shows `ALDI_RECOVERY_KEY` unset. `MAILBOX_1_USER` and `MAILBOX_1_PASS` are masked/present. The report is produced, and the final step intentionally exits 2. **Do not downgrade this to green or invent a recovery key**: recover the existing durable key from a trusted private source and install it as an Actions secret after verifying continuity with the existing state. If continuity cannot be demonstrated, keep processing blocked pending a reviewed safe migration. This is not a proven successful IMAP poll or provider session.

## Cross-check with Google Drive, 2026-10-25
- [Watcher checklist](https://docs.google.com/document/d/1SpcxYbSBuSs-o0SkWoRtuKBqiRsVQtYyb9R6oCNY4kU/edit) last substantive snapshot 2026-10-19; preserves E2E BLOCKED gates.
- [Gmail trigger analysis](https://docs.google.com/document/d/1Z4XmkB4_yazVJXEnEVIqPwzmsi-4YSyHuT5Gprgoits/edit) documents eight content-identical 100-percent mails on 21/22 October, requiring account/cycle verification; #132 remains a draft, not production validation.
- [Canonical knowledge hub](https://docs.google.com/document/d/1GQk3HvhQ_seMnLPodcK9Db2uyKMuCuebTBSVdbvKOfg/edit) prioritizes current GitHub code evidence over old summary text. No claim of direct inter-AI communication is established.

## Closure checklist and operator-only boundary
1. Locate **the previously used** `ALDI_RECOVERY_KEY` in a trusted private credential store, if it exists. Do not paste it into Drive, issues, PRs, logs, or chat. Preserve continuity with the persisted state; if the old key cannot be recovered, stop and design a migration that retains historical consumed-mail claims without rebooking.
2. Configure that key as a GitHub Actions repository secret `ALDI_RECOVERY_KEY` using GitHub's secret-management UI; this repository audit has **not** written a secret. This is a human/private-credential prerequisite, not a code fix.
3. Inspect a fresh `ALDI Usage Mail Monitor` run for no `configuration_error` and no `failed_mailboxes`; verify the sanitized report, avoid treating `actionable_alerts` as authorization to book. Run a controlled, read-only mailbox check only after the key is in place.
4. Offline regression tests already on main in `tests/test_usage_mail_notify_fail_closed.py` assert that missing-key detection prevents polling and that no sensitive strings are echoed. They are **existing tests**, not tests executed by this audit. Re-run CI after relevant code changes.
5. E2E cannot be marked completed until verified provider account identity, actual tariff and 0-euro offer, correct cycle-bound once-only journal, and authoritative completion evidence are available. Do not activate a live booking actor or pay for data to manufacture these proofs.

**Closure result:** repository/Drive documentation synchronized; runtime remediation **blocked by private secret and unproven external prerequisites**. No success claim for the live watcher.

## State-branch read-only inspection, 2026-10-25
On `aldi-watcher-state`, `.aldi-state/` currently contains only `profile-1.json` and `profile-1.heartbeat.json`. `profile-1.json` has `version:2` and `unresolved: []`; the heartbeat timestamp is 2026-10-13T09:16:22.396347Z. No `profile-1.triggers.json` or `profile-1.recovery.json` appeared in this **specific listed directory**. That does not prove no prior fingerprints, journals, backups, or external state exist. Do not generate a replacement key merely from this absence.
The live workflow still lacks `ALDI_RECOVERY_KEY` (observed run 40183910537). GitHub connector access used here cannot read, restore, or securely set a repository Actions secret. **Operator prerequisite:** verify historical key continuity or explicitly approve reviewed state migration, then configure the secret privately. Until then the monitor must fail closed. No state-branch edits were performed.

## Cross-source verification — 2026-10-25
- Read-only checks confirmed that ALDI usage notifications arrive in two separate connected mailboxes. The notifications do not include an independently verified SIM identifier; mailbox-to-SIM mappings remain unproven.
- One mailbox also contains an account-lock notification after failed authentication attempts. The current unlock status remains unknown. No authentication attempt was performed.
- Do not rely on message greetings, similar content, or a password-change notice for account binding. Require independent authenticated read-only account evidence before any provider action.
- No passwords, verification codes, security keys or phone numbers are included in this audit.
- The isolated audit branch passed its latest Python compatibility CI on commit 40975eb1; this is not live-service validation.
