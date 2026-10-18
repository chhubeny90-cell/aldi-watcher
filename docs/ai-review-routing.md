# AI review routing

This repository treats external AI output as untrusted review input, not as source of truth.

## Source roles

| Source | Primary use | Never sufficient by itself |
| --- | --- | --- |
| Perplexity | Current external research, provider documentation, public endpoints and behavior | Provider completion, security guarantees, production readiness |
| GitHub Copilot | Code review, test gaps, race conditions, workflow and implementation suggestions | Architectural truth, external provider facts |
| Gemini | Independent architecture review, threat modeling, alternative designs | Repository state, provider facts unless independently verified |
| ChatGPT / repository maintainer flow | Reconcile all inputs against current `main`, implement, test and document accepted changes | Bypassing repository evidence or safety gates |

## Routing categories

Every incoming finding is assigned to exactly one primary category:

1. `research/provider` — ALDI TALK public behavior, endpoints, documentation, portal observations.
2. `architecture/state-machine` — PENDING/UNKNOWN/SUCCESS rules, idempotency, replay protection.
3. `security/review` — secrets, logs, account binding, privilege boundaries, runner isolation.
4. `code/test` — concrete implementation defects, regressions, missing tests, CI failures.
5. `operations/deployment` — mailbox configuration, persistent journal, self-hosted runner, monitoring.
6. `duplicate/stale` — already implemented, superseded, contradicted by current `main`, or no longer relevant.

## Intake rules

For every external result:

1. Identify the source and date when available.
2. Extract only concrete claims or proposed changes.
3. Map each claim to one routing category.
4. Compare it with current `main`, merged PRs and existing docs.
5. Mark it as one of:
   - `ACCEPT` — verified and useful.
   - `TEST` — plausible but requires repository or live evidence.
   - `REJECT` — contradicted, unsafe, stale or weaker than the existing design.
   - `DUPLICATE` — already covered.
6. Private identifiers such as phone numbers may be read and used internally for account/profile binding. They must not be copied into issues, PR descriptions, logs, model reports or external AI prompts unless a future task explicitly requires that disclosure.
7. Secrets, tokens, credentials, cookies and passwords are never placed in issues, PRs, logs or external AI prompts.
8. Never weaken fail-closed behavior because multiple AI systems agree.

## Zero-cost policy

The AI review hub is **zero-cost only** by default.

- The current implementation is API-neutral and performs no paid provider calls.
- Do not enable an adapter that can incur usage charges, metered API fees, credits, purchases or subscriptions.
- A provider that is only available through a paid/metered API is `NOT_RUN`; the hub must not silently fall back to a billable endpoint.
- Existing consumer subscriptions are not treated as API spending permission.
- Manual/app-based review paths and already-included free capabilities are preferred.
- No repository workflow may purchase, upgrade or enable a paid plan.

## Repository write policy

The orchestrator may prepare and push reviewed commits to working branches and may open/update pull requests. External model output never writes directly to `main`; repository checks remain the authority for promotion. This is a safety boundary, not a ban on pushing changes.

## Private identifier handling

Phone numbers are operational data, not forbidden input. The local/private workflow may:

- read and normalize a configured number;
- compare it with authenticated account identity;
- use it for profile selection and wrong-account guards;
- retain it only in private configuration or protected local state when necessary.

Before any context is sent to an external AI reviewer, phone numbers and mailbox addresses are masked. Reports should contain only a non-reversible description such as `PHONE_REDACTED` or an already-approved short suffix when needed for diagnostics.

## Promotion rules

A finding may affect `main` only when all applicable checks pass:

- repository state verified;
- external fact independently verified when it matters;
- safety invariants preserved;
- regression tests added for changed behavior;
- CI/CodeQL clean where applicable;
- live provider interaction remains explicitly gated.

For ALDI refill completion, visible volume changes, banners, SMS, e-mail or model consensus are supporting evidence only. `SUCCESS` still requires the repository's provider-bound terminal completion contract.

## Cleanup policy

- Prefer one active implementation path per problem.
- Close or supersede redundant branches/PRs instead of stacking variants.
- Fold accepted findings into existing canonical docs rather than creating parallel notes.
- Remove temporary diagnostic code after the evidence it was created to capture has been converted into tests or durable documentation.
- Delete or archive transient AI review payloads after their accepted claims are converted into tests/docs/commits; do not accumulate raw model output indefinitely.
- Keep `main` as the sole source of truth for the current implementation state.

## Working convention

When AI-generated material is pasted into a chat or issue without a label, classify and route it automatically using the rules above before acting on it. The user does not need to name the source role or destination manually.
