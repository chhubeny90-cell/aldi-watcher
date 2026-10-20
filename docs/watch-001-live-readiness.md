# WATCH-001 and controlled live prerequisites

Overall status remains **BLOCKED** until operational evidence is obtained.
This branch builds on PR109 HEAD `0ed0c5d451a94393c38ffc34dbdb14d61f12fd30`.
PR107's old evaluator is not treated as verified or silently merged.

## WATCH-001 correction

`core/release_status.py` replaces arbitrary truthy live criteria with a versioned
catalog: DRY-001..009, LIVE-001..010, BLOCK-001..028 and TEST-001..004. All IDs
have explicit meanings in the source. This is a proposed repository policy,
not a claim that an unseen KI-Box document contains these exact definitions.
TEST-001 is full regressions, TEST-002 release hardening, TEST-003 mail migration,
and TEST-004 snapshot/archive crash safety.

The evaluator requires exact ID coverage, strict booleans, zero integer pending
and unknown counts, assessed changes, current commit/CI identity, one coherent
snapshot, evidence references and a reproducible test mapping. Every dry and
block criterion needs evidence. LIVE_READY additionally requires all live
criteria and evidence, explicit authorization, account and receipt verification.
Security changes invalidate every proof until explicit revalidation. Proofs older
than 24 hours, future proofs and naive timestamps are rejected.

Synthetic positive fixtures prove the evaluator's logic only. The evaluator
cannot verify the contents of a URL, the truth of a supplied boolean, or the
existence of a live provider receipt. It is deliberately not connected as an
actor authorization switch. Audit records include evidence IDs and snapshot;
a digest is not external append-only storage or a signature.

## Schema 3: independent recovery evidence

The active wire schema is **3**, not 2. Schema 2 payloads must be rebuilt and
independently revalidated; do not relabel old evidence. Exact LIVE-001..010
coverage is mandatory. LIVE-007 requires completion-contract proof and LIVE-010
requires its own recovery-contract proof. Reusing one evidence record for both
criteria is rejected. The pure evaluator does not fetch or authenticate URLs.

`LIVE_VERIFIED` is reserved as an operational reporting state for the exact
completed authorized event after independent official receipt, private durable
journal and replay guard verification. The pure pre-action evaluator deliberately
never emits it; no such operational verification exists yet.

## Historical schema 2: first-run readiness is not a completion result

Schema 1 required `provider_receipt_verified` before LIVE_READY, which was
circular for the operation that had not yet run. Schema 2 rejects schema 1
instead of silently upgrading evidence. It requires independently evidenced
`provider_completion_contract_verified` and `provider_recovery_contract_verified`
in addition to the complete catalog, explicit authorization and account binding.
An old receipt or a true receipt flag cannot replace either contract. LIVE_READY
only describes readiness for the authorized attempt; it is never SUCCESS or a
claim that the system works. The independent actor/completion verifier still
requires the current operation's official receipt before persisting SUCCESS.
No actor permission check is removed or connected to this pure evaluator.

## Private runtime check

On the actual POSIX runner, run `python scripts/check_aldi_runtime.py` with the
existing `ALDI_JOURNAL_PATH`. The source is opened read-only and never initialized
or repaired. The probe verifies private permissions, schema and integrity, and
creates a private temporary backup on the same filesystem, closes/reopens it,
checks unresolved counts, and removes its copy. It never prints paths or rows.
Missing/corrupt/ephemeral journals and unresolved operations return exit 2.
No provider access or credentials are used. A successful probe still reports
BLOCKED: host-restart persistence, off-host backup and account/provider binding
remain separate operational evidence. A passing synthetic test is not host proof.

The readiness workflow can explicitly request this probe with
`private_runtime=true`; it defaults to false and requires the configured journal
path and private runner. A queued or skipped job proves neither runner availability
nor a working private journal. Do not launch the refill workflow to test the host.

## Actual live blockers to inspect

The existing `aldi_live_refill_contract.py` already observes portal-generated
updateUnlimited exchanges. Its parser is implemented and unit-tested. What is
unproven is the real provider schema and operation-bound recovery, not the
existence of the adapter. No provider endpoint or receipt may be fabricated.

The new read-only workflow checks configuration **presence**, exact commit tests,
and a coherent remote queue/provider-guard snapshot. It does not transmit ALDI
credentials, log into ALDI, create a journal or attempt a refill. Its job success
must never imply LIVE_READY: host availability, private journal integrity,
authenticated target, tariff, zero price, completion and recovery remain separate
operational proofs.

The existing manual `free-refill.yml` additionally requires a private self-hosted
Linux runner labelled `aldi-journal` and `ALDI_JOURNAL_PATH`. A repository variable
alone does not prove that host or file exists. The GitHub connector in this
session has no runner-administration or workflow-dispatch capability.

The user authorized progressing toward one controlled free 1GB run on 2026-10-19.
This is not authorization for paid options, tariff changes, repeated retries or
removing UNKNOWN/PENDING guards. Never clear a historical guard to make a test
pass. No code in this patch enables automated provider actions.
