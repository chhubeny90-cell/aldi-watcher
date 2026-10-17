# ALDI provider completion contract — 2026-10-17

## Purpose

The public `epicexcelsior/alditalk-refill` implementation provides useful current
portal evidence for the action path: the dashboard BFF exposes an on-demand refill
flow using an `updateUnlimited` request and a resource identifier. Its own success
check is balance-based. This repository deliberately keeps the stricter local
transaction model: a balance increase is supporting evidence, not a terminal
receipt for one local `recharge_id`.

## Runtime path added

`aldi_live_refill_contract.py` is the guarded rollout entrypoint. It reuses the
existing `aldi_live_refill.py` eligibility, account/tariff binding, persistent
PENDING reservation, trusted UI click and UNKNOWN lockout.

The adapter additionally:

1. clears old Chrome performance-log noise immediately before the already-approved
   UI click;
2. observes (but never sends or retries) the portal-generated
   `POST .../v1/offer/updateUnlimited` exchange;
3. reads only Chrome-cached request/response bodies through DevTools;
4. evaluates `core/aldi_completion.py`;
5. stores provider operation/resource identifiers only in the private SQLite
   journal;
6. upgrades the existing PENDING/UNKNOWN operation to SUCCESS only if all four
   completion gates are true.

## SUCCESS contract

```text
SUCCESS =
  account_binding_verified
  AND offer_binding_verified
  AND provider_operation_bound
  AND provider_terminal_success
```

`account_binding_verified` means the protected account/tariff binding after the
provider operation is identical to the pre-click binding.

`offer_binding_verified` requires the observed request to be the portal's
`updateUnlimited` action and to contain exactly one resource id. If the response
also contains a resource id, it must match.

`provider_operation_bound` requires exactly one transaction/order/operation/reference
identifier in the provider response. Multiple different identifiers are treated as
ambiguous and remain UNKNOWN.

`provider_terminal_success` requires a 2xx response and one explicit terminal
status such as `SUCCESS`, `COMPLETED` or `FULFILLED`. `202 Accepted`, `PENDING`,
`PROCESSING`, `QUEUED`, generic banners and HTTP success alone are not terminal.

## Supporting evidence only

The following may be logged for diagnosis but cannot independently create SUCCESS:

- visible +1 GB balance increase;
- identical SIM/tariff after refresh;
- disappearance/reappearance of the refill control;
- success banner;
- provider SMS or e-mail;
- green unit/CI tests.

## Data handling

Raw request/response bodies, cookies, tokens, headers and authentication material
must never be written to reports. Reports contain only top-level field names,
booleans, HTTP status and sanitized contract state. Full provider operation and
resource identifiers are permitted only in the private persistent POSIX SQLite
journal (0600).

## Controlled rollout

The provider-contract entrypoint currently forces a maximum of one refill attempt
per process. A controlled live E2E remains blocked until login, correct SIM,
eligible free offer and persistent journal are all verified. If the real ALDI
response does not expose the required operation/status contract, the transaction
stays UNKNOWN and no second booking is allowed.

## Reconciliation next step

The new journal evidence is sufficient to bind a future read-only provider
status/history lookup to a specific local `recharge_id`. Such a lookup must not be
invented. Until a real portal response or provider history endpoint proves its
schema, historical `check_recharge_status(...)` remains UNKNOWN.
