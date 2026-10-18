# KI-Box: operational blocker review, 17 October 2026

Base: `3dd4e17c467811154fbde9ad03743193eb7e69e6`.

## Mail monitor

Run [39058873535](https://github.com/chhubeny90-cell/aldi-watcher/actions/runs/39058873535)
used the older `4b7d787` revision and reported one configured mailbox and
`dedup_key_missing` before IMAP access. This is not a successful mailbox test.
The later main revision passes a mailbox password as a fallback recovery key.
That changes durable message fingerprints when mailbox credentials change or
when a dedicated recovery key is later introduced. Do not treat that fallback
as a verified deployment fix. Restore the dedicated, stable `ALDI_RECOVERY_KEY`.
This also resolves the two failing workflow-security tests on current main.

The missing secret remains a deployment blocker. Configure it privately through
GitHub's secure settings; these tools cannot read or set its value. If any
fallback-key run already wrote state, reconcile its message history before
changing keys. No automatic migration or trigger replay is performed here.

## Legacy refill runner

Run [39055012689](https://github.com/chhubeny90-cell/aldi-watcher/actions/runs/39055012689)
on `4b7d787` reported only `PermissionError`. The catch in `simple_free_1gb.py`
discarded the traceback and reason. Its exact origin cannot be established from
that log. Portal origin/session guards can raise that exception, and browser
startup can also propagate it. The current OAuth-path allowlist is newer than
the failed run and already has regression tests. Do not claim a live fix or
weaken an origin guard based on the exception class alone.

Independently confirmed: the legacy script clicked a refill without the durable
journal, full target-account binding or provider completion contract, then
returned zero after reading volume. Its schedule also ran independently of the
consumed-mail signal. Retire both this workflow schedule and the direct script.
The retired script exits 3 before any credential or browser access, even when
`AUTO_BOOK_ENABLED=true`. The manual retired workflow receives no secrets and
exits 3 with a pointer to the existing `ALDI Guarded Free Refill` workflow.

The guarded workflow and `aldi_live_refill_contract.py` remain the intended path;
they are not activated by this change. Mail-to-actor integration, private target
configuration, durable journal deployment and one real provider-confirmed
completion still require verification. No ALDI login or booking was executed.

## Current evidence

- Main test run [39061087105](https://github.com/chhubeny90-cell/aldi-watcher/actions/runs/39061087105):
  548 passed, 2 failed, 1 skipped, 12 subtests passed.
- Main CodeQL [39061087139](https://github.com/chhubeny90-cell/aldi-watcher/actions/runs/39061087139): successful.
- Scheduled [39061643691](https://github.com/chhubeny90-cell/aldi-watcher/actions/runs/39061643691):
  public probe only; test job skipped. No account or booking evidence.

External model responses were not requested or invented during this review.
Existing older Gemini findings were checked against current source as recorded
in the shared task box. A task-box write is not a direct model notification.
