# 2026-10-23: eight identical 100%-usage mails — cycle identity not proven

## Observed evidence (read-only Gmail inspection)
Thread `1a15ec0f92115177` in the explicitly selected Gmail account had eight
messages from 2026-10-21 13:57:29 UTC to 2026-10-22 02:07:04 UTC.
All eight had identical consumed-volume subject and body and the same authenticated
ALDI sender. All eight had distinct Gmail IDs and RFC 822 Message-IDs. No 80%
warning or provider event ID appears in that thread. Raw headers showed SPF,
DKIM and DMARC pass. This proves eight deliveries, NOT eight consumption cycles.
Do not store names, mailbox identifiers or body text in code or persistent logs.

## Actual code behavior
- `usage_mail_bridge._message_key`: HMACs Message-ID plus Date (or raw hash
  fallback). It correctly recognizes the eight deliveries as eight distinct mails.
- `usage_mail_notify._poll_one`: enqueues each new consumed mail separately;
  the `actionable` report field means a consumed-*notification*, not a
  provider-booking authorization.
- `core.mail_handoff_queue`: persists per-message reservations with CAS.
  It does not prove SIM binding or a new consumption cycle.
- `github_live_refill._claim_mail_trigger`: mail-driven live booking is
  currently blocked until the queue and provider journal share a proven gate.

## Required release contract — still BLOCKED
1. Persist Gmail/RFC-message deduplication independently of provider-cycle state.
2. Resolve mail to an authenticated, explicitly intended SIM. Email account or
   Gmail thread membership is not proof of SIM binding.
3. For a new consumed notification without authoritative cycle ID, create only
   a candidate. Repeated candidates for an unresolved SIM/cycle do not authorize
   further booking attempts. Do not collapse all identical-body mail forever:
   legitimate later cycles may generate the same text.
4. Require authenticated current allowance, eligible active tariff, exactly one
   *explicitly zero-cost* 1 GB offer and a durable operation reservation.
5. A fresh cycle needs independent authenticated evidence of a prior reset/
   renewal/refill and subsequent consumption, or a provider-defined unique
   event identifier. Do not infer it from elapsed time, Gmail Message-ID,
   a different sender worker, or a Google thread boundary.
6. Exactly one provider-changing attempt per proven cycle, with a durable
   PENDING/UNKNOWN guard and official request-bound completion evidence.
   Unknown state never automatically retries. Keep mail dispatch blocked until
   the account+cycle+provider journal contract is end-to-end proven.

## Regression evidence
`tests/test_repeated_consumed_mail_20261023.py` uses eight synthetic mails at
the observed Date-header timestamps, never copies personal mailbox contents,
and verifies that message deduplication alone would create eight candidates.
It also verifies warnings cannot enqueue and the monitor does not book.

## Implemented in this draft PR (not production-approved)
- `core/mail_cycle_guard.py`: CAS-backed, HMAC-only profile-scoped ledger.
  First consumed candidate is `UNVERIFIED`; seven more for the same explicitly
  configured profile do not open another candidate. `UNKNOWN` never auto-retries.
  A different message ID or passage of time cannot clear this guard.
- `usage_mail_notify.py`: when `ALDI_MAILBOX_N_PROFILE_BINDING` is explicitly
  configured, report `cycle_candidate` and `unverified_cycle_candidates`.
  Existing per-message notifications and legacy `actionable_alerts` are
  preserved for compatibility. They must not be mistaken for booking permission.
- A profile binding is a *configuration label*, NOT authenticated SIM identity.
  No binding is inferred from the mailbox. Without explicit configuration,
  the guard does not claim a verified profile or create a cycle candidate.
- Queue entries remain per-message for forensic dedupe. Candidate reporting
  and mail queue are separate remote files: a partial failure must be reconciled
  before considering any actor handoff. The actor remains blocked.
- `reserve_verified_provider_cycle` explicitly rejects all calls until an
  actual authenticated provider-cycle verifier is implemented. There is no
  time-based automatic release, and a genuine new cycle cannot be accepted
  without a future verified reset mechanism.

This PR does NOT implement a speculative provider event ID, merge provider
identities, change live booking permissions, mark any refill successful or
assert that the account is accessible. Do not enable a live mail actor based
on this ledger alone.
