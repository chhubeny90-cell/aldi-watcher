# Verifiable AI handoffs

Owner for this integration: ChatGPT/Codex, task `WATCH-MASTER-20261020`.
GitHub is source of truth for code; Drive 04_KI_AUFTRAGSBOX records deltas and
links. One owner per task. Independent reviewers do not approve their own work.

## Evidence stages

| Stage | Required evidence | What it cannot prove |
| --- | --- | --- |
| PREPARED | Task ID, owner, full commit, expected reviewer, random challenge | Delivery |
| STORED | GitHub/Drive write result and exact readback of challenge | Another AI received it |
| ACKNOWLEDGED | Counterpart-authored ACK from the authenticated transport, matching task/commit/challenge/owner | Review approval or completion |
| REVIEWED | Independent findings tied to that commit and checked by coordinator | Live provider success |
| CLOSED | Result link, tests, accepted review and coordinator's closure record | Unrelated tasks or later commits |

`tools/ai_handoff_receipts.py` validates an ACK fetched by the authenticated GitHub
connector. Never feed an arbitrary user-supplied JSON file as authenticated
transport evidence. Author identity and repository/thread must be verified at
read time. Its positive tests are synthetic protocol tests, not real delivery.

A minimal counterpart response is JSON (fill fields from the assigned task):

```json
{"type":"KI_ACK_V1","task_id":"<task-id>","commit":"<40-hex>","owner":"<owner>","challenge":"<received-challenge>"}
```

ACK is separate from results. Result records include reviewer identity, commit,
findings with file/test/public-source links, outcome and timestamp. A changed
commit invalidates the prior review until explicitly revalidated.

## Real interfaces in this session

| Participant | Actual route | Receipt status |
| --- | --- | --- |
| ChatGPT | Authenticated GitHub and Google Drive connectors | Own storage readback test possible |
| GitHub Codex | Existing repository review integration; explicit PR `@codex review` request | Must observe bot response for the current commit; request alone is insufficient |
| Gemini | No callable authenticated Gemini interface discovered | NOT_ACKNOWLEDGED; structured manual patch |
| Perplexity | No callable authenticated Perplexity interface discovered | NOT_ACKNOWLEDGED; structured manual patch |
| Microsoft Copilot | No callable authenticated Copilot task/ACK interface discovered | NOT_ACKNOWLEDGED; structured manual patch |

The existing `tools/ai_review_hub.py` builds sanitized provider-specific prompts
and validates returned reviews. It does not call provider APIs. Do not purchase
API access, infer it from subscriptions, publish private documents or pretend
that an issue starts a closed assistant app. No continuous background sync exists.

Patch fallback: task ID, source assistant, timestamp/timezone, source commit,
actual read/write capabilities, proposed delta, evidence links, unresolved points.
The authorized coordinator checks it, writes a scoped Drive delta and reads it back.

## Rollout report

Use exactly BLOCKED, DRY_RUN_READY, LIVE_READY or LIVE_VERIFIED for overall
reporting. Pending tasks/reviews, unavailable interfaces and unproven runtime
capabilities remain explicit; a successful storage test never promotes readiness.
