# Controlled refill rollout

Current implementation status: **BLOCKED**. CI is not provider evidence.
The reference workflow is `.github/workflows/free-refill.yml`.

## Two stages

| Stage | Runner and state | Allowed action |
| --- | --- | --- |
| Mail sensor | GitHub hosted runner; CAS-backed remote state branch | Hourly IMAP check, 80% warning, reserve consumed events; no ALDI credentials/browser |
| Controlled actor | Private self-hosted Linux runner labelled `aldi-journal`; existing private SQLite journal outside checkout | One separately authorized free 1-GB attempt only after all gates |

The sensor's cron is minute 17 each hour, UTC. GitHub schedules are best effort;
they are not an exact hourly SLA. A reliable host timer and independent heartbeat
would be needed for a strict cadence. Remote state failure is not empty history.
Do not replace the original HMAC key or clear prior events to start a test.

Observed scheduled run 39396855864 (2026-10-20 08:55 UTC) stopped with
`dedup_key_missing` before checking mail. This establishes a missing runtime
`ALDI_RECOVERY_KEY` in that run, not the absence of consumer Gmail access.
https://github.com/chhubeny90-cell/aldi-watcher/actions/runs/39396855864

## Manual workflow gates

Default is preflight with `DRY_RUN=true`, `AUTO_BOOK_ENABLED=false`.
Refill dispatch requires main, the exact approved commit and a specific `AUTH-`
reference, successful offline tests/config presence checks, and the `aldi-live`
environment. Its administrator must configure required reviewers and main-only
deployment protection. Declaring the environment name does not prove protection.

Before any login, `scripts/check_live_workflow.py` rejects missing or stale
commit-bound schema-v3 evidence and the known incomplete mail-to-private-actor,
operation-recovery and Selenium pre-auth contracts. These are factual code gaps,
not repository variables to toggle. Even a fabricated all-true readiness payload
cannot bypass them. This gate currently always blocks: it is rollout scaffolding,
not a completed live integration or a substitute for the missing implementations.

`scripts/check_aldi_runtime.py` then checks the existing private journal and local
backup/reopen. `open_live_journal()` independently enforces the same schema before
opening the actor. Nullable IDs, incomplete status rules, partial lookup indexes
and triggers on the safety table block execution. No automatic migration or
replacement of an existing journal is permitted. A local copy/reopen is not proof
of restart persistence or off-host backup; those need separate real-host evidence.

## Offer and completion contracts

See [exact offer policy](aldi-free-entitlement.md). Before clicking, revalidate
full account, tariff, offer and zero price. PENDING must be committed and retained;
reservation deletion/rebinding is rejected. A crash or uncertain request outcome
remains PENDING/UNKNOWN and prevents automatic retry after restart.

The existing `aldi_live_refill_contract.py` observes `updateUnlimited` exchanges.
Its synthetic parser tests do not establish the current provider response schema.
Only an official operation-bound terminal receipt can establish SUCCESS. A volume
increase, generic banner, email, green CI or AI agreement cannot substitute.
The queue's COMPLETED transition remains intentionally blocked pending verified
receipt-to-event integration. Historical recovery remains unverified.

## Required external evidence

- Original stable recovery key and complete event history; exact mail/SIM/tariff binding.
- Current restored login and real-account offer evidence, with no blind credential retry.
- Actual protected environment, private runner, existing journal and restart/restore proof.
- Observed completion and recovery contracts, reviewed against the exact commit.
- New specific authorization for the one concrete live attempt.

No provider login or booking was performed by this change. No paid options or
plan changes are authorized. Do not run journal initialization to repair lost history.
