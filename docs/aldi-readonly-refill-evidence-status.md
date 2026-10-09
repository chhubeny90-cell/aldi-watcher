# Status

Branch: `hardening/aldi-readonly-refill-evidence`

Implemented:

- read-only ALDI account/refill evidence parser,
- exact full-number account binding in memory,
- explicit free 1-GB / zero-price policy,
- selector configuration without guessed defaults,
- allowlisted monitoring result fields,
- read-only provider reconciliation evidence (`ALDI_REFILL_RECONCILE_SELECTOR`),
- explicit success wording validation for exactly 1 GB,
- regression tests for fail-closed account/price/button/reconciliation handling,
- no booking click or POST.

Safety boundary:

- the existing ALDI live-booking guard remains required,
- `AUTO_BOOK_ENABLED=false` remains hard-coded in the hosted monitoring workflow,
- ambiguous or missing provider reconciliation stays `UNKNOWN` and must block retry,
- no live booking executor is wired into GitHub Actions.

Still provider-dependent before any live authorization:

1. observe and configure the authenticated ALDI account/tariff/offer/button selectors,
2. observe an account-scoped success confirmation for exactly 1 GB,
3. observe a persistent provider-side reconciliation/history marker that survives a new session,
4. validate those selectors in a controlled account flow without exposing raw account data.

Only after those provider facts are observed can a live action be reviewed separately. This branch itself remains non-transactional.
