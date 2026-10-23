# Runtime unblock: original recovery key and history

Task WATCH-WORKFLOW-FORTSETZUNG-20261020. Overall BLOCKED.

## Evidence collected 2026-10-20

- Main remains d0bb785bc66d0bc07213c7a409d69ad130ab14a7.
- Scheduled mail run 39434447578, 13:54 UTC / 15:54 Europe/Berlin:
  one mailbox configured, dedup_key_configured=false, dedup_key_missing,
  no portal access or provider action. It stopped BEFORE IMAP.
  https://github.com/chhubeny90-cell/aldi-watcher/actions/runs/39434447578
- Prior observed schedules: 08:54:59 and 03:19:43 UTC. The approximately five-hour
  observed gaps do not establish hourly execution. No private host/timer is
  reachable through the current connected toolset.
- Current state branch directory contains the public guard and heartbeat only;
  guard schema 2 has zero unresolved entries and a historical auth retry time.
  This does NOT prove a complete queue, dedup history or private SQLite journal.
- No ALDI_RECOVERY_KEY/ALDI_JOURNAL_PATH in this execution environment or the
  known project configuration locations. This is not proof of permanent loss.
- The GitHub connector has no Actions-secret read/write, runner administration
  or workflow-dispatch tool. Secrets cannot be recovered from masked logs.
  No secret values, credential exports or requests to paste them into chat.

## Required owner action

1. Locate the ORIGINAL recovery key in the user's own trusted configuration or
   backup. Do not generate a new value and do not use an ALDI/Gmail password.
2. Open repository Settings -> Secrets and variables -> Actions. For this
   repository-level sensor, ensure the existing original value is provided as
   the repository secret ALDI_RECOVERY_KEY. If it lives only in an environment,
   that is a different scope: do not assume the sensor can read it. Preserve
   sharing/approvals and inspect scope privately before changing anything.
3. Confirm only presence/scope in the task record, never the value. Ensure the
   original key belongs to the retained state history before enabling polling.
4. Once the reviewed sensor code is merged, run the mail-monitor workflow manually
   twice. Read both sanitized reports: first actual IMAP access and committed
   event state, then duplicate rejection with durable state readback. A consumer
   Gmail connector search is not this evidence. Booking remains disabled.
5. Inspect further real scheduled runs. If hosted scheduling is too delayed,
   use the existing private host only after availability, persistent state,
   locking, and independent heartbeat have actually been demonstrated.

## If the original key cannot be recovered

Remain BLOCKED. Do not relabel old HMAC fingerprints or treat missing history as
empty. First inventory all historical state revisions and retained source events
privately. Preserve immutable snapshots. Prepare a separately reviewed migration
with an explicit cutoff and permanent quarantine of every ambiguous old event.
A replacement key without a proven historical mapping cannot identify old HMACs.
Do not execute such a migration or initialize a new history under this task.

## Downstream boundary

A real mail/SIM/tariff mapping, authenticated offer context, private persistent
runner/journal, official operation completion and recovery remain unproven. The
live rollout gate stays in place. No real live attempt is authorized here.
