# NettoKOM LIFT – separate offline watcher variant (2026-11-06)

## Verified official offer

- LIFT S/M/L: 25/50/100 GB initial volume in the Telefónica network.
- Below 1 GB remaining, the provider sends an SMS.
- Customers can manually add 1 GB for free repeatedly through NettoKOM App or Mein NettoKOM on the web.
- LIFT S/M/L regular rates: €9.99/€14.99/€19.99 per 4 weeks; promotions vary.
- SMART tariffs do not offer free unlimited 1-GB refills.

Sources:
- https://www.nettokom.de/prepaid-tarife/lift/
- https://www.nettokom.de/prepaid-tarife/unlimited-on-demand/

## Feasibility assessment

Potential advantage: SMS at the threshold could wake a watcher without constant account polling; official web access offers manual one-click refills.
**Not established:** automatic SMS forwarding on iOS, official API, provider permission for scripts, session stability / authentication requirements, authenticated account parsing, transaction-bound receipts or low-cost always-on runtime.
Manual one-click refill does **not** imply that a bot or public API is supported.

## Scope of this proposal

- core/nettokom_lift.py: pure offline candidate rules; only LIFT S/M/L, <1 GB, exact 1 GB offer and explicitly €0.00, no unresolved transaction.
- plugins/nettokom_lift.py: provider slot with **both** authenticated usage and booking explicitly disabled.
- tests/test_nettokom_lift.py: local fail-closed tests; no provider access.
- Not wired to main.py, scheduler or GitHub Actions. No secrets, new workflow, network calls, paid actions or real bookings.

## Gates for an eventual live implementation

1. Check current conditions and obtain necessary explicit provider access authorization.
2. Validate a supported read-only account/status method and authenticated SIM/tariff context.
3. Confirm exact 1 GB / €0.00 in a unique enabled offer, and absence of a paid conflict.
4. Reuse a private durable per-account journal with reservation, lock and no blind retries.
5. Verify provider operation-bound **success confirmation**; volume increase alone is not proof.
6. Offline tests, dry-run validation and explicit separate live approval before activation.

**Status:** OFFLINE SCAFFOLD ONLY / LIVE BLOCKED. Do not interpret offline candidate assessment as permission to book.
