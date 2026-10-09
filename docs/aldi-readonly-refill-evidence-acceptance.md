# Acceptance criteria

This branch is ready for review only when CI is green and all changes remain read-only.

Provider acceptance remains blocked until a real authenticated run can prove:

- `login_ok=true` on the official ALDI portal,
- unambiguous protected usage data,
- `account_verified=true`,
- `refill_type=FREE_ONE_GB`,
- `refill_reason=free_one_gb_offer_available`,
- explicit zero-price evidence,
- no booking request or click.

A later booking implementation must additionally persist PENDING before the single
side effect, verify a new account-scoped success state, and reconcile provider state
before any retry. The current branch deliberately does not implement that side effect.
