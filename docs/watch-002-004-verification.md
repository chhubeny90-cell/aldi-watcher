# WATCH-002 / WATCH-003 / WATCH-004

Overall status: **BLOCKED**. This patch grants no provider or booking permission.

## Proven starting point

- BASE_COMMIT / HEAD_BEFORE_PATCH: `cbe8388157a8fa65cd9e1a93016953167a9a4492`.
- Separate branch: `fix/watch-002-004-20261019`; PR #107 remains independent.
- PR #107 still points at `1dda8df2cbea07c516cba532e6bfb7257d43c0e7` when inspected.
- No new WATCH-001 patch commit or its claimed 35-test evidence was available.
- On this source tree, `python -m pytest -k hardening --tb=short -q`
  selects 20 tests. This does not independently certify WATCH-001 or Issue #106.

## WATCH-002 / REV-001

Mail identity uses HMAC-SHA256 with **ALDI_RECOVERY_KEY only**, binding
Message-ID and sent Date using length-delimited JSON. With no Message-ID a
stable raw-message digest is included. No raw headers leave the process.

Before a consumed-mail reservation, check both the new identity and the original
SHA-256 identity against old queue entries, archived tombstones and the legacy
trigger fingerprints. Copy every still-retained trigger fingerprint to a
permanent CAS-backed `profile-1.legacy-trigger-history.json` ledger before
acknowledgement. Read/write errors abort; no failed read means "unseen".

There is **no `processed_mails.json` source or schema in this repository**.
The actual migration source is `profile-1.triggers.json`. Do not invent a file
format or claim to have migrated an unseen external file.

Limitation: the old trigger ledger kept only 128 keys. Keys already evicted
before this migration cannot be reconstructed. Historical completeness needs
an independent source/backup or explicit reconciliation before LIVE readiness.
Keep the recovery key stable; rotating it requires a separate dedup migration.

## WATCH-003 / REV-002

The active queue remains capped at 512. At capacity it attempts archival:
only COMPLETED entries with an aware `completed_at` **strictly older than
30 days** are eligible. A timestamp-less legacy completion stays in the queue.
RESERVED, IN_FLIGHT and QUARANTINED_UNKNOWN are never retired.

First CAS-write permanent tombstones to `profile-1.provider-journal.json`, then
CAS-remove the archived queue entries. A crash/conflict may retain both copies;
it cannot remove the last guard. Every enqueue checks tombstones. The main
provider guard file (`profile-1.json`) is not repurposed.

This does not enable the COMPLETED transition: the official receipt verifier
remains unavailable. A queue filled exclusively with unresolved entries stays
BLOCKED without dropping data; archival cannot resolve those entries.

## WATCH-004 / REV-003

`github_journal_state.consistent_mail_snapshot()` resolves the state branch to
an immutable commit, reads both queue and provider guard at that exact ref,
and checks the branch revision again. Changed/invalid refs or read failures
block preflight. Successful results include that commit as `snapshot_version`.
These reads never create a branch. A snapshot is observational evidence, not
a lock or booking authorization; subsequent workers still require CAS.

## Regression coverage

`tests/test_watch_002_004.py` covers HMAC identity, legacy trigger/queue aliases,
migration survival after old-ledger eviction, unavailable history, 30-day
boundaries, archive ordering/failure/crash, 513th enqueue, unresolved capacity,
same-ref reads, changed/invalid snapshot refs, and bridge fail-closed behavior.
All fixtures are synthetic. No IMAP account, ALDI login or live booking is used.

The Python compatibility workflow prints its exact HEAD and runs the requested
old-mail regression, hardening selection and full suite in the same step.

## Follow-up after merge: legacy 80% warnings

Starting point: main `bca7dc9482c747cc53482d4314a08bc5394ec227`.
PR #109 review `discussion_r4310599334` identified a missing migration check
for non-consumed alerts in `usage_mail_notify.py`. Both warning and consumed
paths now preserve and consult retained trigger history before acknowledgement.
Warnings still never enter the actor queue. State read/write failures abort
before claiming or reporting a warning. Regression fixtures cover old-warning
migration followed by ledger eviction, new-warning deduplication through the
real trigger ledger, and both migration read and write failures.

Historical identities evicted before migration remain unreconstructable.
Overall status remains BLOCKED. No provider login, booking, or tariff change.
