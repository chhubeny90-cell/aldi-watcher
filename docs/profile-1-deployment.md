# Profile 1 target (user-confirmed, 2026-10-17)

The user identified the ALDI TALK Unlimited Tarif S subscription ending **1869**
as the free 1-GB refill target. This is user-reported, not a fresh automated
provider verification. SIM is available. The display “1.6 GB of 25 GB” has not
been verified as remaining allowance.

Linked line ending **2640** has an annual package until 2026-11-02.
Line ending **2626** has no active package and an outstanding replacement-SIM
activation. Neither line is the refill target for this deployment.

Set GitHub Actions secret `ALDI_PROFILE_1_USER` to the full target phone number
ending 1869. Do not commit the phone number. Set `ALDI_PROFILE_1_LOGIN_USER` only
when the login identifier differs from the target; retain its matching password
in `ALDI_PASS`. Account linkage with the target has not yet been demonstrated.

The guarded workflow requires suffix 1869 in addition to the existing full-number
comparison and authenticated selected-account/subscription checks. The suffix
alone never proves identity or eligibility. Local runners can set
`ALDI_REQUIRED_TARGET_SUFFIX=1869` and `ALDI_EXPECTED_ACCOUNT` to the full target.

This change does not configure secrets, install a runner, or prove a live login,
mail trigger, or booking. The integration cannot write Actions secrets. Mailbox
credentials, recovery key, and durable journal/runner remain deployment items.
Only a verified free 1-GB offer may be booked; paid options and tariff changes
remain excluded.
