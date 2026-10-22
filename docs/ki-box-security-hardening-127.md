# KI-Box security hardening evidence — PR #127

Overall status: **BLOCKED**. No release or ALDI authorization is granted.

## Commit and branch ledger

| Step | Commit / branch | Evidence and next step |
| --- | --- | --- |
| Initial inventory | main `d0bb785bc66d0bc07213c7a409d69ad130ab14a7`; PR HEAD `3f41723a4c9bf55d46d70b41dd061d32f4fa37a3` | All three P1 and four P2 findings read; [inventory](https://github.com/chhubeny90-cell/aldi-watcher/pull/127#issuecomment-6314867525) |
| Initial implementation | `ce5bd59c8f18242a708bee7406f9115ac50d919a`; `fix/ki-box-security-hardening-127` | Tested locally, published to the feature branch and fast-forwarded to the existing PR branch; no merge command executed by this agent |
| Independent GitHub review | exact `ce5bd59c8f18242a708bee7406f9115ac50d919a` | [Review request](https://github.com/chhubeny90-cell/aldi-watcher/pull/127#issuecomment-6314997051), [review with three further findings](https://github.com/chhubeny90-cell/aldi-watcher/pull/127#pullrequestreview-5599119904) |
| External merge observed | `3425b110ee2fe754a2c8f3b8285297a0f476ed95` | GitHub PR metadata and timeline record `chhubeny90-cell` as merger at 2026-10-21 11:58:26 UTC; this happened outside the agent's merge actions and does not constitute security approval |
| Follow-up implementation | `fix/ki-box-security-followup-127` from exact main `3425b110ee2fe754a2c8f3b8285297a0f476ed95` | Fix the three current review findings, run regression/full tests, publish a draft PR with auto-merge disabled and request independent review of its exact HEAD |

The follow-up commit SHA and its current-commit CI/review results are recorded in
the draft PR discussion after publication. A document cannot contain its own
commit SHA; the GitHub evidence entry binds the full SHA to the test and CI links.

## Original findings and implementation

| Finding | Disposition | Regression evidence |
| --- | --- | --- |
| P1 GitHub App login regex | Existing fix `872cf2ee1ba835e75a9ecb80335d66aaf198dcca` preserved | Bot login and positive receipt cases |
| P1 bearer forwarding on redirects | Existing pre-forwarding rejection preserved | Real urllib redirect processing over memory transport for 301/302/303/307/308, cross-origin and HTTPS downgrade; one request only |
| P1 reclaimed login identity | Require immutable numeric ID plus case-insensitive login | Wrong/missing/bool IDs rejected; sender and provider identities must be distinct |
| P2 duplicate task keys | Strict recursive duplicate-key parsing for task, API response and ACK | Root and nested duplicates fail before network access |
| P2 exactly 1,000 comments | Empty page 11 exhaustion probe | 0/99/100/999/1000 accepted, 1001 fails without partial audit success |
| P2 login capitalization | Case-insensitive identity matching with the same numeric ID | Canonical API login matches configured mixed-case spelling |
| P2 HTTP protocol failures | Sanitized failure and no retry | BadStatusLine, IncompleteRead, 401/429, timeout and later-page failure cases |

Additional initial fixes: validate again at the public network boundary, reject
path/query injection and shared provider identities, bind comment ID to anchor,
bound response/task input, sanitize CLI/path/exception text, and guard offline
review publication against recognizable secrets and ambiguous JSON.

## Findings from the current GitHub review

| Finding | Follow-up correction |
| --- | --- |
| [P1 multiline quoted credentials](https://github.com/chhubeny90-cell/aldi-watcher/pull/127#discussion_r4336360668) | Reject recognizable credential assignments/headers at any nonempty value, including quoted multiline, incomplete and angle-bracket literals; regress prepare/validate/aggregate and CLI publication |
| [P2 truncated valid-JSON HTTP body](https://github.com/chhubeny90-cell/aldi-watcher/pull/127#discussion_r4336360674) | Validate declared length before/after bounded read; reject ambiguous framing; use real HTTPResponse in-memory regression tests |
| [P2 valid dot-prefixed repository](https://github.com/chhubeny90-cell/aldi-watcher/pull/127#discussion_r4336360678) | Permit `.github` and other valid names while rejecting exact traversal segments and URL delimiters |

## Files changed

Initial hardening: `tools/ki_box_receipts.py`, `tools/ai_review_hub.py`,
`tests/test_ki_box_receipts.py`, `tests/test_ai_review_hub.py`,
`docs/ki-box-current-task.json`, `docs/ki-box-delivery-contract.md`, and
`.github/workflows/python-package-conda.yml`.

Follow-up: both tool files and test files, the delivery contract, and this log.
The existing architecture and previously passing Python matrix are preserved.

## Verified initial results

- Local Python 3.12: 267 focused tests; full suite 948 passed, one existing
  obsolete-lock test skipped, 12 subtests passed. Python 3.10 AST grammar and
  `git diff --check` passed.
- Exact initial hardening commit: [Python 3.10–3.14 CI](https://github.com/chhubeny90-cell/aldi-watcher/actions/runs/39593159293),
  every matrix entry and aggregate `build-linux` passed.
- [CodeQL security-extended](https://github.com/chhubeny90-cell/aldi-watcher/actions/runs/39593159229)
  and [full suite CI](https://github.com/chhubeny90-cell/aldi-watcher/actions/runs/39593159217)
  passed. Public portal probe was skipped. Passing CodeQL did not negate the
  three later review findings above.
- Live GET-only GitHub readback for Issue #126: Codex `AWAITING_ACK`;
  Gemini/Perplexity/OpenAI `NOT_CONNECTED`; upstream execution `NOT_PROVEN`;
  ALDI `BLOCKED`. No provider API was called.

## Verified follow-up results before publication

- Local Python 3.12: **543 focused tests passed**; full suite **1,224 passed,
  one pre-existing obsolete-lock test skipped, 12 subtests passed**.
- Python 3.10 AST grammar and `git diff --check` passed.
- Independent local security review reproduced and checked the fixes for all
  three GitHub findings and two additional residual bypasses: angle-leading
  credential literals and unsupported/duplicate/decoder-mismatched
  Transfer-Encoding. No actionable P1/P2 remains in that reviewed scope.
- Real HTTPResponse tests use memory transports and verify declared length,
  complete/truncated chunked payloads, encoding ambiguity and valid framing.
  The existing stdlib tolerance after a complete zero chunk does not truncate
  the JSON payload; unused trailers do not authenticate receipts.
- The corrected real GitHub GET-only audit was repeated successfully with the
  same `AWAITING_ACK` / `NOT_CONNECTED` / `NOT_PROVEN` / `BLOCKED` result.

## Remaining blockers and next concrete step

The follow-up requires passing current-commit CI/CodeQL and an independent
current-commit Codex review. No earlier green check or review approves new code.
The integration token cannot list repository-wide code-scanning alerts or branch
protection settings (HTTP 403). Local CodeQL CLI is absent; use the existing PR
CodeQL workflow. No protection setting or CI gate was changed to bypass checks.

There are no authenticated Gemini/Perplexity bridges, upstream delivery proofs,
or task execution workers. Separate credentials and identities per service,
durable atomic worker deduplication and bounded authenticated dispatch are
requirements before any future activation, not implemented worker capabilities.
Repeated receipt reads are idempotent observations and never execute a task.

No ALDI booking, tariff change, paid API, credential change/publication, live
activation or agent-initiated merge is part of this work. Keep the follow-up PR
in draft and overall status **BLOCKED** until security verification and release.
