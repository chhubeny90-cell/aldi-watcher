# ALDI read-only refill evidence

This branch adds read-only evidence collection for the ALDI TALK free 1-GB refill.
It does not enable booking and does not remove the live-booking guard.

A candidate is eligible only when all of the following are true in one authenticated
provider session:

1. The configured account selector resolves to exactly one visible element whose
   full mobile number matches `ALDI_USER` after normalization.
2. The configured active-tariff selector resolves uniquely.
3. The configured refill-offer selector resolves uniquely and contains exactly
   1 GB plus explicit `0 EUR`/`kostenlos` evidence.
4. No non-zero price or conflicting paid/subscription wording is present.
5. The configured refill button is uniquely scoped inside that offer and is enabled.

The monitoring report stores only classified evidence such as
`account_verified`, `refill_eligible`, `refill_type`, and `refill_reason`.
It does not persist the account number, tariff text, offer text, cookies, tokens,
or credentials.

Selectors intentionally have no defaults. They must be captured from observed,
authenticated provider markup. Until then the result is
`selectors_unconfigured` and the gate remains closed.

The remaining rollout gates are still separate:

- successful authenticated ALDI login and protected usage read,
- observed selectors from the real account portal,
- provider-specific post-booking success confirmation,
- persistent provider reconciliation for PENDING/UNKNOWN operations.

No live booking is authorized by this change.
