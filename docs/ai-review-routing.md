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
6. Never copy secrets, tokens, credentials, phone numbers or provider identifiers into issues, PRs or logs.
7. Never weaken fail-closed behavior because multiple AI systems agree.

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
- Keep `main` as the sole source of truth for the current implementation state.

## Working convention

When AI-generated material is pasted into a chat or issue without a label, classify and route it automatically using the rules above before acting on it. The user does not need to name the source role or destination manually.
