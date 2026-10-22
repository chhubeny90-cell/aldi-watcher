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
nonsecret random string, `sender_login`, positive integer `sender_id`, and a `recipients` map with
exactly `copilot`, `gemini`, `perplexity`, `openai`.
Each value is an object such as
`{"login": "chatgpt-codex-connector[bot]", "id": 199175422}`, or `null` when no
authenticated bridge has been installed. Obtain IDs from authenticated GitHub
API metadata, never from the comment body. The committed sender and Codex IDs
were verified against PR #127's GitHub API author metadata. Match both the
immutable numeric ID and case-insensitive login; renamed accounts require an
explicitly reviewed envelope update. Reclaimed logins never inherit authority.
Sender and recipients must have distinct IDs and logins, and each provider must
have its own recipient. Old login-only envelopes are rejected without migration.
Duplicate JSON keys at any depth and non-finite numbers are rejected.

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
3. For each bridge, set its verified GitHub login and immutable ID as `recipients[provider]`; fetch signed-in comments via GitHub REST; verify task + commit + challenge + exact thread and comment ID.
4. Route `ACKNOWLEDGED` to `tools/ai_review_hub.py validate` for findings; reconcile differences with code and tests. Never let model consensus promote a release.
5. Report `NOT_CONNECTED`, `AWAITING_ACK`, `REVIEWED` and `COMPLETED` separately. Only measured actions may move states. Missing access must be recorded as a blocker.

## Network, credentials and replay boundaries

The audit accepts only validated canonical `https://api.github.com/repos/...`
comment URLs. Validation runs at the public fetch function as well as the CLI.
All redirects are blocked before another request can forward authorization,
including same-host redirects and HTTPS downgrades. Only HTTP 200 at the exact
requested URL is accepted. Requests are GET-only, with a 15-second timeout and
zero automatic retries. Authentication, throttling, protocol and JSON failures
stop the audit with a fixed error message; exception bodies and file paths are
never printed. Responses are bounded to 8 MiB per page, with at most 1,000
comments and one additional empty-page probe. Overflow fails the whole audit.
Declared Content-Length must match the complete bounded body; duplicate length
headers or mixed Content-Length/Transfer-Encoding framing fail closed. Chunked
payload framing is checked by the HTTP decoder; unknown, duplicate or unsupported
Transfer-Encoding values are rejected. Declared payload truncation containing
valid JSON is never sufficient evidence. The standard decoder's tolerance for
missing optional trailer termination after a complete zero chunk is unchanged;
trailers do not authenticate receipts. Dot-prefixed repository names such as `.github`
are supported; the exact `.` and `..` path segments are forbidden.

`GITHUB_TOKEN` is exclusively a least-privilege GitHub read credential. It is
never sent to Gemini, Perplexity, OpenAI or ALDI. There are no provider adapters,
callback endpoints, dispatchers or task-execution workers in this integration.
Introducing a bridge requires separately provisioned credentials per service,
a dedicated verified GitHub identity and independent upstream authentication;
shared owner credentials are not acceptable evidence. No provider credential is
loaded or provisioned by this patch, and disconnected providers remain disabled.

Task ID + provider + full commit + unique challenge + exact thread bind an ACK
to one request. Issue a new ID and random challenge for every new task; never
reuse the envelope for different work. A duplicate ACK or repeated audit is an
idempotent read of historical evidence: it cannot execute or enqueue anything.
This audit is not an exactly-once worker. Before a future worker can be enabled,
it needs durable atomic task claiming, a consumed-ID journal, bounded retries
and authenticated upstream delivery evidence. These are outstanding bridge
requirements, not capabilities claimed by this read-only checker.

The offline review hub rejects recognizable GitHub, OpenAI, Gemini and
Perplexity token formats, credential headers and credential assignments before
preparing prompts, validating reviews or aggregating outputs. CLI failures use
fixed messages. These checks provide defense in depth; arbitrary passwords and
unknown credential formats cannot be identified reliably by a text pattern.
Quoted credential assignments and headers are rejected as soon as the quoted
value begins, including multiline, empty and incomplete quoted values.
Recognizable credential labels also reject any other nonempty value, including
angle-bracket literals and redaction placeholders; there is no placeholder bypass.
Only independently checked public context may enter the hub. Review JSON is
untrusted content, even after validation; it carries no provider authentication
or permission to run a task. Duplicate JSON keys are rejected there as well.

## Safety and scope

- **Zero-cost only**: no metered Gemini, Perplexity, OpenAI or GhostGPT APIs without a separate cost decision.
- **No secrets/identifiers** in public repo, issue, bot messages or AI requests.
- **No ALDI live operation**: existing `BLOCKED` gate, legacy journal, recovery key, paid booking bans, account binding and runtime preconditions remain untouched.
- Never replace the original `ALDI_RECOVERY_KEY` or clear deduplication history merely to make CI green.
- No unverified provider callback, third-party AI claim or runbook may grant booking authority.
- PR #121 / #123 may be pending: integrate by review rather than blindly cherry-picking overlaps.
