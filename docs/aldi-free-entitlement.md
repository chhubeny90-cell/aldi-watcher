# ALDI TALK offer classification

Policy updated 2026-10-20. This describes the repository's conservative gate;
it is not a claim about the user's authenticated subscription.

The public provider page describes repeatable free 1-GB refill for eligible
Unlimited tariffs. Checked 2026-10-20:
https://www.alditalk.de/tarife-unlimited-gb-nachbuchen

The website says below 1 GB; an older published price list uses at most 1 GB:
https://media.medion.com/cms/medion/alditalkde/ALDI-TALK-Tarif-S-M-L-Unlimited-GB-nachbuchen-Preisliste-0625.pdf
The current detector deliberately uses the stricter below-1-GB boundary. An
independently verified provider eligibility contract would need a separate change.

`core/aldi_refill.py` requires all of:

1. Verified finite nonnegative remaining volume below 1 GB.
2. Exactly one explicit Unlimited tariff heading; plain Tarif S/M/L is insufficient.
3. Exactly one enabled local refill control; candidate count must be a strict int,
   equal to 1. Booleans, floats, strings, zero and negative counts are rejected.
4. Exactly 1 GB and a local literal `0,00 €` price. `0 €`, `EUR`, absent price and
   generic free wording do not satisfy this deliberately strict parser policy.
5. No positive, malformed or conflicting price, paid option or tariff-change terms.

A separately labelled wallet balance can be excluded only on a real independent
rendered block line. This parsing helper does not authorize reading arbitrary
ancestors: the Selenium locator now uses ONLY the control's rendered subtree.
Unpriced buttons cannot borrow a zero from a sibling card or page-level wrapper.
A sibling-price layout remains BLOCKED until an actual provider-scoped offer
relationship has been observed and independently reviewed. Generic card classes,
one-control ancestry, and a configured selector alone are not identity proof.

The classifier does not authorize login or booking. Current rollout remains BLOCKED.
