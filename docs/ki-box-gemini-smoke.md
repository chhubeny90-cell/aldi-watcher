# Guarded Gemini smoke test

Status: **BLOCKED for live execution until separate setup is verified**. This
manual-only workflow does not merge code, enable ALDI, or change release status.
It builds on the receipt/transport hardening in draft PR #128 (`ecaa419`).

## What this proves

`.github/workflows/ki-box-gemini-smoke.yml` has three separate stages:

1. `prepare` produces a public run-bound task, unpredictable challenge and
   `PREPARED` summary. It has no secrets, checkout or network calls. Both inputs
   default to false. `publish=true` without `live=true` fails.
2. After a protected-environment approval and free-tier setup, `generate` makes
   **one** fixed Google REST POST containing only that public task. It validates
   the exact typed JSON echo, one model text candidate, STOP finish reason,
   canonical model version and response ID. No tools, repository contents,
   GitHub credentials or automatic retries are involved.
3. Separately approved `publish` can post the validated smoke receipt to open,
   unlocked Issue #126 with a repository-scoped GitHub App issues-write token.
   It first verifies the configured bot's durable numeric ID, checks existing
   run markers, then performs at most one POST and validates the exact comment
   ID, body, URL, issue, bot ID/login/type and performing App ID/slug on readback.

`MODEL_ECHO_VALIDATED` means an authenticated API response returned the requested
echo. `POSTED_AND_READ_BACK` additionally proves GitHub storage by the configured
App. Neither is `KI_ACK_V1`, an independent review, an always-on agent, proof of
free billing, or release approval. The general receipt audit remains unchanged
and will not relabel this Markdown smoke receipt as an ACK.

## Required separate setup

Do not paste any credential into chat, a PR, Issue #126, or workflow inputs.
This implementation neither creates secrets nor changes any activation flag.

| Scope | Name | Required verification |
| --- | --- | --- |
| Repository variable | `KI_BOX_ACTIONS_ZERO_COST_VERIFIED` | Exactly `true` only after the owner verifies Actions runs incur no charge |
| Repository variable | `KI_BOX_GEMINI_FREE_TIER_VERIFIED` | Exactly `true` only after verifying the chosen project/key/model is eligible for a genuinely free route, with paid usage prevented outside this code |
| Repository variable | `KI_BOX_GEMINI_PUBLISH_ENABLED` | Exactly `true` only after the dedicated App identity and intended publication have been approved |
| Generate environment variable | `KI_BOX_GEMINI_MODEL` | Explicit approved canonical `gemini-...` model ID; returned `modelVersion` must equal it, aliases returning a different version fail closed |
| Generate environment secret | `GEMINI_API_KEY` | Dedicated Google project/key for this test; never reuse GitHub, OpenAI or Perplexity credentials |
| Publish environment variable | `KI_BOX_GEMINI_MODEL` | Same approved canonical model ID as generate |
| Publish environment variable | `KI_BOX_GEMINI_APP_ID` | Independently verified positive immutable App ID, distinct from its bot account ID |
| Publish environment variable | `KI_BOX_GEMINI_BOT_LOGIN` | Dedicated App login ending `[bot]`, matching the token action's App slug |
| Publish environment variable | `KI_BOX_GEMINI_BOT_ID` | Independently verified immutable numeric GitHub bot account ID; never inferred from a comment body |
| Publish environment secret | `KI_BOX_GEMINI_APP_PRIVATE_KEY` | Dedicated App key, installed only on `chhubeny90-cell/aldi-watcher`, issues write only |

Create protected environments `ki-box-gemini-test` and `ki-box-gemini-publish`,
require independent reviewers, prevent self-approval/bypass where available,
and restrict deployment to protected `main`. Keep Google and App secrets only
in their respective environment. Repository-level gating variables are needed
because job `if` conditions are evaluated before environment variables load.
Environment protection and branch protection are external requirements; this
YAML cannot configure or prove them. If the account/plan cannot enforce them,
keep all live/publish gates disabled and record that blocker.

Boolean flags and a consumer subscription cannot prove Google billing state.
Do not enable the live stage until external project, model, quota and billing
evidence confirms zero-cost use without paid fallback. No paid request is
authorized by this workflow or its tests. A successful echo does not prove
future requests will remain free. No specific model or free-tier availability
is assumed by the implementation.

The App-token action is pinned to Node-24 release commit
`64ab729a6294000f5aa4a4bc0b73d1f32bc45510` (`actions/create-github-app-token` v3).
Its `action.yml` was fetched and checked for Node 24, scoped repositories,
`permission-issues` and automatic token revocation. The proposed older pin
`fee1f7d63c2ff003460e3d139729b119787bc349` uses Node 20. The supported App-ID input
is retained for the supplied setup; v3 marks it deprecated in favor of client ID.

## Controlled execution after review and setup

Only `workflow_dispatch` on protected `main`, in the canonical repository and
with the cost gate, is eligible. No schedule, push, pull-request or issue trigger
can execute this workflow. It must first be merged through the normal release
process; a feature-branch dispatch is deliberately blocked.

- First dispatch with `live=false`, `publish=false`. The expected result is only
  `PREPARED`, or skipped jobs if a gate is absent. A skipped run proves nothing
  about API access.
- Only after the Google environment/key/billing approvals, use `live=true`,
  `publish=false` for one model echo. Check the exact commit, run ID, challenge,
  model metadata and `MODEL_ECHO_VALIDATED` summary.
- Use `live=true`, `publish=true` only when both environments and the dedicated
  App setup are approved and a new one-request smoke test is intended. This
  dispatch creates a new task and a new Gemini request; it does not publish a
  previous run's receipt.

No dispatch or real API call was made as part of implementing or testing this
workflow. Do not run it just to discover whether billing/protection is safe.

## Fail-closed transport and replay behavior

All programs validate repository, main ref, dispatch event, full commit, run ID
and attempt. Both sensitive jobs independently gate `run_attempt == 1`; their
Python programs also reject attempts other than 1 before any HTTP call. Thus
GitHub's "rerun failed jobs" cannot reuse a previously successful prepare job
to repeat generation or publication. Concurrency serializes runs without
cancelling an in-flight request.

The Google key is a header on the fixed HTTPS Google URL only. The App token is
used on fixed HTTPS GitHub API paths only. Redirects are rejected before any
credential can be forwarded. Responses require the exact requested URL/status,
strict duplicate-key/nonstandard-JSON rejection, bounded size, and complete
declared Content-Length. Ambiguous or decoder-unsupported transfer framing
fails closed. HTTP errors, malformed data and raw exception text are withheld.
The standard decoder's tolerance for optional trailer termination after a
complete zero chunk is unchanged; trailers do not authenticate the payload.

Task ID, full SHA, run ID/attempt and challenge must match exactly, including
JSON types. Provider response IDs and model metadata cannot replace this binding.
The publisher revalidates the receipt against `prepare` rather than trusting
the output's repository field alone. Shared owner credentials cannot satisfy
the dedicated Bot/App checks.

Before mutation, a full bounded scan accepts up to 1,000 issue comments plus an
empty-page probe. An existing matching run marker is re-read without another
POST; a spoofed, conflicting or duplicate marker blocks. This is a guarded
manual smoke artifact, not a durable exactly-once worker: deletion of evidence
or an independently repeated new dispatch is not recoverable task history.

After a timeout or any uncertain POST/readback, the comment or model request
may already exist. The job fails without retries or a success claim. Inspect
the run and Issue #126 before creating any new dispatch. Never blindly repeat a
model call or comment POST to recover missing evidence. No automatic worker,
ALDI action, tariff change or release transition is implemented.

## Tests and review evidence

`tests/test_ki_box_gemini_smoke.py` compiles and executes the exact embedded
workflow programs with isolated synthetic environments and memory transports.
It checks dry preparation, all context/rerun gates, one fixed request, strict
typed echoes, bounded HTTP framing, actual urllib redirect behavior, separate
credentials, immutable bot/App IDs, exact readback, pagination, deduplication
and uncertain writes without retry. No network or real secrets are needed.

Local pre-publication verification: **1,302 full-suite tests passed, one existing
obsolete-lock test skipped, 12 subtests passed**, including **78 smoke regression
cases**. `actionlint` 1.7.12, Python 3.10 grammar for all three embedded programs
and the regression file, and staged whitespace checks passed. No workflow was
dispatched and no Gemini request or Issue #126 publication was performed.

Commit SHA, current-commit CI/CodeQL results and independent Codex review links
are recorded in the draft PR discussion after publication. All setup and live
execution remain **BLOCKED** until separately verified and authorized.
