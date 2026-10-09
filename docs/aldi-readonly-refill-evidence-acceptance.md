# Acceptance criteria and current gate status

This branch is ready for review only when CI is green and all changes remain read-only.
No transactional ALDI action belongs in this PR.

## Current automated evidence

| Gate | Status | Evidence requirement |
| --- | --- | --- |
| Official ALDI SSO reached | PASS | allowlisted HTTPS SSO host |
| Credentials submitted once | PASS | no retry loop |
| Protected ALDI session | BLOCKED | `login_ok=true` on the official customer portal |
| MFA / OTP challenge | NOT OBSERVED | structural probe only; no OTP input visible |
| Visible credential validation error | NOT OBSERVED | no invalid input / alert state observed |
| Account binding | BLOCKED | exact full-number `account_verified=true` |
| Active tariff | BLOCKED | one observed authenticated selector |
| Free refill | BLOCKED | exactly `1 GB` plus explicit `0 EUR` / `kostenlos` |
| Booking control | BLOCKED | one enabled control scoped inside the verified offer |
| New success confirmation | BLOCKED | account-scoped explicit successful 1-GB result |
| Persistent reconciliation | BLOCKED | provider-side marker/history surviving a new session |
| Live booking | DISABLED | existing RuntimeError guard remains; hosted workflow keeps `AUTO_BOOK_ENABLED=false` |

The latest automated auth probe reaches ALDI SSO but does not establish a protected
customer-portal session. It intentionally records only structural and HTTP-category
counts; it does not persist page text, account identifiers, URLs, cookie values,
headers, tokens or provider response bodies.

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
- no booking request or click during evidence collection.

A later booking implementation must additionally persist PENDING before the single
side effect, verify a new account-scoped success state, and reconcile provider state
before any retry. The current branch deliberately does not implement that side effect.
