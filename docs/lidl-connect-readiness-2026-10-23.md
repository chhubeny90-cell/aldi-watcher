# LIDL Connect — independent login and refill readiness (2026-10-23)

Status: **BLOCKED**, no authenticated login, no live booking.

## Verified published terms
LIDL Connect Unlimited on Demand S/M/L offer repeated manual 1 GB additional high-speed allowance without additional charge. This only applies to an eligible *active* tariff; the monthly tariff itself is paid. Source: https://www.lidl.de/c/lidl-connect/s10007717 and https://www.lidl.de/c/lidl-connect-unlimited-on-demand-m/s10076491 . Paid one-time data options exist; free must not be inferred from a generic 1 GB label.

## Repository findings on main (c4262092669405e63fa7cdb40386cce120ec2f04)
- watcher.py: LIDL_LOGIN_URL and LIDL_OVERVIEW_URL point to https://kundenkonto.lidl-connect.de/mein-lidl-connect.html.
- Existing historical protected monitor run found public LIDL HTTP 403, with no visible input. This is not a failed password and is not proof of an IP ban.
- Existing core/lidl_refill.py is **inspection-only**, insists on validated tariff, exact 1 GB, free offer, button and verified session, and refuses when selectors are absent. It does not prove live operation.
- run.yml public_probe checks public ALDI and Lidl pages without secrets. Its scheduled runs are NOT login tests.
- No verified LIDL identity, active tariff, available remaining allowance, price confirmation or provider receipt in this session.

## Acceptance steps
1. Run **credential-free** public diagnostic: preserve only host, HTTP status, JS error category and login-field visibility. Compare official account link; do not guess alternate login endpoints or circumvent a provider 403.
2. If official login path is accessible and automation permitted, authorize one manually launched, **read-only** login with existing protected LIDL Secrets. Do not leak passwords, cookies, session tokens, OTP or private DOM.
3. Verify selected account identity and tariff from protected provider content, not the login URL or a cookie alone.
4. Read exact eligible 1 GB free refill offer in an authenticated session; distinguish any paid 1 GB/DayFlat from the free on-demand benefit; no click until binding and operation receipts are implemented and approved.
5. Persist a per-account/per-provider-cycle atomic booking reservation; classify UNKNOWN without retry; check official operation-linked receipt before success. Never book across unknown history.
6. Schedule at most passive mail/state inspections every 10 minutes; do **not** reauthenticate every 10 minutes, and respect auth throttling/lockout.

## Distinct boundaries
ALDI 2 GB claim is unrelated and not evidence for LIDL. ALDI's draft PR #132 and policy correction PR #134 are not merged here. No GitHub Secrets were read or changed. No provider action was executed.

## Needed regressions
- Public 403 with zero inputs is an access blocker, not bad credentials.
- Login URL/cookie alone never means login success.
- Reject SMART/Classic/annual tariff, payable 1 GB, ambiguous prices, multiple elements, hidden and disabled controls.
- Refuse duplicate mailbox notifications and unknown booking completion; never bypass account lock or repeated auth errors.
