# WATCH-001 and controlled live prerequisites

Overall status remains **BLOCKED** until operational evidence is obtained.
This branch builds on PR109 HEAD `0ed0c5d451a94393c38ffc34dbdb14d61f12fd30`.
PR107's old evaluator is not treated as verified or silently merged.

## WATCH-001 correction

`core/release_status.py` replaces arbitrary truthy live criteria with a versioned
catalog: DRY-001..009, LIVE-001..009, BLOCK-001..028 and TEST-001..004. All IDs
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
