# KI-Box delivery and receipt contract (21 October 2026)

Canonical repo: https://github.com/chhubeny90-cell/aldi-watcher
Related control issue: #106. Integration against `main` only after PR review.

## Separate the four claims

1. **PREPARED**: ChatGPT or `tools/ai_review_hub.py prepare` produced a model-specific request.
2. **POSTED**: an authorized user or bot wrote the request to a GitHub thread; GitHub readback proves storage, not that the external model saw it.
3. **ACKNOWLEDGED**: a separately authenticated GitHub counterpart account wrote an exact `KI_ACK_V1` into the same thread, matching task, 40-character commit and per-task challenge. The GitHub account is authenticated, not the upstream inference engine.
4. **REVIEWED / COMPLETED**: independent review and acceptance evidence exists for the precise commit. An ACK is never review approval or completion.

The `tools/ki_box_receipts.py` audit supports **step 3 only**. It does not send, schedule, authorize or execute requests to models. It makes no ALDI portal requests.

## Provider roles and confirmed delivery status

| Provider | Intended responsibility | Transport state at setup | Rule |
| --- | --- | --- | --- |
| Codex / Copilot | code review and concrete patch suggestions | Existing GitHub Codex bot reviews PRs; PR #123 has a completed review on its own head | Model's usual Markdown review is **not** `KI_ACK_V1`; do not relabel it |
| Gemini | independent architecture / security challenge | No authenticated callback transport verified | `NOT_CONNECTED` until installed/configured |
| Perplexity | public provider research and source checking | No authenticated callback transport verified | `NOT_CONNECTED` until installed/configured |
| ChatGPT | implementation, reconciliation and CI | Connected GitHub writer, **task sender** | Own posts/readbacks cannot satisfy independent ACK |

Existing external AI text is untrusted data. Use `tools/ai_review_hub.py` to prepare and validate model-specific JSON, without paid API access.

## Task schema

Commit a public **nonsecret** task JSON on a feature branch, with:
`repository`, `thread_kind` = `issues` or `pull`, positive `thread_number`,
`commit` = full 40-hex SHA, `task_id`, `challenge` = unique 16–128 character
nonsecret random string, `sender_login`, and a `recipients` map with
exactly `copilot`, `gemini`, `perplexity`, `openai`.
Each value is the verified GitHub account permitted to acknowledge that
provider, or `null` when no authenticated bridge has been installed.

Do not fill an identity based solely on an AI's claimed name or a comment body.
If a provider sends no authenticated comment, leave it `NOT_CONNECTED` or
`AWAITING_ACK`, not `ACKNOWLEDGED`.

### Example of a counterpart comment body

```json
{
  "type": "KI_ACK_V1",
  "task_id": "WATCH-KIBOX-20261021",
  "commit": "d0bb785bc66d0bc07213c7a409d69ad130ab14a7",
  "challenge": "nonsecret_unique_challenge_20261021",
  "provider": "gemini",
  "owner": "chhubeny90-cell"
}
```

**Do not have the task owner post this on the model's behalf.** A reply from a real
approved bridge's GitHub account is needed. A future bridge must authenticate
the upstream model, prevent replay, and preserve its own delivery receipt.
The GitHub-side checker alone cannot verify upstream model provenance.

## Read-only audit from authorized environment

```sh
# GITHUB_TOKEN must be a scoped token supplied through protected execution,
# never committed or pasted into a public issue or model prompt.
python tools/ki_box_receipts.py --task docs/ki-box-current-task.json
```

With an authenticated GitHub API read, it produces a sanitized JSON status with
the exact task commit and each expected provider; it exits nonzero if the
configuration, token or API is unavailable. It never silently reports success.
Without a supported connector or token there is no claim of a completed audit.

## Integration steps

1. Keep a single GitHub issue as the inbox for model task envelopes; PRs are used for code reviews. Do not imply GitHub issue mentions directly ping Gemini or Perplexity.
2. Install and configure genuine provider bridges **only if a cost-free, authorized transport is available**. New secrets belong to protected runtime configuration, never a repo/issue/prompt. No consumer subscription implies metered API entitlement.
3. For each bridge, set its authenticated GitHub account as `recipients[provider]`; fetch signed-in comments via GitHub REST; verify task + commit + challenge + exact thread.
4. Route `ACKNOWLEDGED` to `tools/ai_review_hub.py validate` for findings; reconcile differences with code and tests. Never let model consensus promote a release.
5. Report `NOT_CONNECTED`, `AWAITING_ACK`, `REVIEWED` and `COMPLETED` separately. Only measured actions may move states. Missing access must be recorded as a blocker.

## Safety and scope

- **Zero-cost only**: no metered Gemini, Perplexity, OpenAI or GhostGPT APIs without a separate cost decision.
- **No secrets/identifiers** in public repo, issue, bot messages or AI requests.
- **No ALDI live operation**: existing `BLOCKED` gate, legacy journal, recovery key, paid booking bans, account binding and runtime preconditions remain untouched.
- Never replace the original `ALDI_RECOVERY_KEY` or clear deduplication history merely to make CI green.
- No unverified provider callback, third-party AI claim or runbook may grant booking authority.
- PR #121 / #123 may be pending: integrate by review rather than blindly cherry-picking overlaps.
