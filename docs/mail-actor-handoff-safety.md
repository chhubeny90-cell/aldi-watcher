# ALDI mail-to-actor handoff: safety status (2026-10-18)

This document describes the **draft PR #105**, not a live deployment.
The one-time live booking test remains blocked. No provider login or click is
performed by the mail monitor, preflight, or integration tests.

## Implemented path

1. `usage_mail_notify.py` reads IMAP messages in read-only mode. A consumed
   signal is enqueued on the dedicated GitHub state branch before an actionable
   alert is reported. An 80% warning is notification-only.
2. `core/mail_handoff_queue.py` stores only keyed HMAC event fingerprints,
   phases and revisions, with GitHub SHA compare-and-set protection.
   Duplicate events cannot create a second reservation.
3. `mail_actor_preflight.py` inspects the mail queue **and** the existing
   `github_journal_state.py` provider journal. Missing remote journal state,
   unresolved provider operations, or uncertain mail events block the preflight.
4. `github_live_refill.py` rejects raw mail-trigger keys and unverified
   `ALDI_TRIGGER_PRECLAIMED` flags. There is no dispatch from the mail queue
   to a provider-changing actor.
5. `core/mail_actor_handoff.py` rejects COMPLETED until a real
   operation-bound provider receipt verifier is implemented. A changed volume,
   generic success message, or synthetic test result cannot finish a booking.

The mail queue is an **event inbox**, not a second provider booking journal.
The existing provider journal remains authoritative for unresolved
`PENDING`/`UNKNOWN` booking operations.

## Evidence still required before any live booking

- Authenticated portal account and subscription must be bound to the
  particular queued event; two mailboxes or SIMs must not cross-trigger.
- A currently active, uniquely identifiable **free 1 GB** offer and unchanged
  tariff/account must be verified immediately before each provider action.
- The official provider's completed provisioning receipt must be verified
  and linked to that operation; observation of additional volume is insufficient.
- Production mailbox and provider credentials must be configured securely
  in the appropriate runner; no secrets belong in logs or shared documents.
- The end-to-end actor adapter must use the existing durable journal, prove
  crash/UNKNOWN/duplicate behavior and pass CI and independent review.
- The one-time, zero-cost live test may happen only after the above evidence
  and an explicit final readiness check; uncertain results must never be retried.

## Offline verification

```bash
python -m pytest -q tests/test_mail_actor_handoff.py \
  tests/test_mail_handoff_queue.py \
  tests/test_mail_monitor_queue_integration.py \
  tests/test_mail_actor_preflight.py \
  tests/test_mail_actor_e2e_dry_run.py \
  tests/test_github_live_refill.py
```

This test set uses synthetic messages and an in-memory remote-state fake.
Passing it proves internal guard behavior, **not** ALDI account access,
provider terms, or successful refill provisioning.
