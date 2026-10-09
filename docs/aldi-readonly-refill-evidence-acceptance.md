# Acceptance criteria and current gate status

This branch is ready for review only when CI is green and all changes remain read-only.
No transactional ALDI action belongs in this PR.

## Current automated evidence

| Gate | Status | Evidence requirement |
| --- | --- | --- |
| Official ALDI SSO reached | PASS | allowlisted HTTPS SSO host |
| Credential fields populated | PASS | both native inputs have values and pass native validity before submit |
| Single submit attempt | PASS | exactly one submit attempt; no fallback/retry loop |
| Provider credential request | BLOCKED | latest probe observed no post-submit network request |
| Protected ALDI session | BLOCKED | `login_ok=true` on the official customer portal |
| MFA / OTP challenge | NOT OBSERVED | no OTP input visible |
| Server-side credential rejection | NOT OBSERVED | no post-submit 401/403/5xx response exists because no request leaves the browser |
| Client-side login validation | BLOCKED | after submit both inputs are cleared and become `valueMissing`/invalid locally |
| Account binding | BLOCKED | exact full-number `account_verified=true` |
| Active tariff | BLOCKED | one observed authenticated selector |
| Free refill | BLOCKED | exactly `1 GB` plus explicit `0 EUR` / `kostenlos` |
| Booking control | BLOCKED | one enabled control scoped inside the verified offer |
| New success confirmation | BLOCKED | account-scoped explicit successful 1-GB result |
| Persistent reconciliation | BLOCKED | provider-side marker/history surviving a new session |
| Live booking | DISABLED | existing RuntimeError guard remains; hosted workflow keeps `AUTO_BOOK_ENABLED=false` |

## Latest authenticated diagnostic finding

The current GitHub Actions probe reaches the official ALDI SSO login UI. Immediately
before the single submit attempt, both username and password inputs are populated,
natively valid, and not marked invalid. After the submit attempt, both native inputs
are empty and locally marked invalid with `valueMissing=true`. The sanitized network
probe observes no post-submit request, redirect, 401, 403, or 5xx response.

Therefore the remaining authentication blocker is currently classified as a
client-side ALDI SSO/component-state problem. This is not evidence of wrong
credentials and not evidence of a provider HTTP authentication rejection.

The diagnostic deliberately records only booleans, counts and coarse classifications.
It does not persist page text, account identifiers, field values, full URLs, cookie
values, headers, tokens or provider response bodies.

All ALDI account/tariff/offer/button/success/reconciliation selectors remain
provider-observation inputs. They must not be guessed or populated from unrelated
markup. Until authenticated observation supplies them, refill evidence remains
fail-closed.

## Acceptance before any later transactional review

A real authenticated read-only run must prove:

- `login_ok=true` on the official ALDI portal,
- unambiguous protected usage data,
- `account_verified=true`,
- `refill_type=FREE_ONE_GB`,
- `refill_reason=free_one_gb_offer_available`,
- explicit zero-price evidence,
- persistent provider reconciliation semantics,
- no booking request or refill click during evidence collection.

A later booking implementation must additionally persist PENDING before the single
side effect, verify a new account-scoped success state, and reconcile provider state
before any retry. The current branch deliberately does not implement that side effect.
