# Status

Branch: `hardening/aldi-readonly-refill-evidence`

Implemented:

- read-only ALDI account/refill evidence parser,
- exact full-number account binding in memory,
- explicit free 1-GB / zero-price policy,
- selector configuration without guessed defaults,
- allowlisted monitoring result fields,
- regression tests for fail-closed behavior,
- no booking click or POST.

Still blocked on live evidence and reconciliation. The existing ALDI live-booking guard remains required.
