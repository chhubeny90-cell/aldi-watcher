# ALDI/Lidl refill engine v2 – foundation (steps 1–3)

Status: **foundation only, no provider access, no logins, no booking clicks**.

The code lives in a separate refill_v2 namespace. It does not change the
legacy core/database.py, BaseWatcher, or the previously disabled ALDI workflows.
Provider automation and deployment must not be activated without authorization
and a provider-specific completion contract.

## 1. File tree

    aldi-watcher/
      refill_v2/
        __init__.py
        models.py                 # provider, offer, receipt and state types
        db.py                     # SQLite journal, reservations and cooldown
        humanizer.py              # bounded UI waits, retry-only-read operations
        session_vault.py          # encrypted credentials and browser state
        accounts.example.yaml     # only non-sensitive aliases; not loaded yet
        providers/                # PLANNED, not implemented
          base.py                 # PLANNED BaseProvider
          aldi.py                 # PLANNED
          lidl.py                 # PLANNED
        main.py                   # PLANNED CLI/runner
      tests/
        test_refill_v2_db.py
        test_refill_v2_humanizer.py
      Dockerfile                  # PLANNED (step 6)
      .github/workflows/refill.yml # PLANNED (step 6, never unattended live by default)

## 2. SQLite State Machine

    NO_OPERATION -> PENDING (durably committed before a possible click)
    PENDING -> UNKNOWN (timeout, crash, ambiguous/absent confirmation)
    PENDING / UNKNOWN -> SUCCESS (only provider-bound official receipt)
    PENDING / UNKNOWN -> manual/authoritative FAILED (future, not implemented)
    UNKNOWN -X-> another automatic refill

The database is created only in a private directory (0700), mode 0600, using
SQLite WAL, synchronous FULL, explicit BEGIN IMMEDIATE and a unique partial
index that rejects multiple unresolved operations per account. Each account
has a private alias and its own observation/cooldown. A booking reservation
requires a fresh observation below 1.0 GB, exact 1-GB offer, explicitly zero
price, verified session identity and separately verified provider permission.
These gates are all false by default; their implementation in the future
providers requires independent acceptance tests, not just user-set booleans.

SUCCESS records a SHA-256 digest of the official provider receipt identifier
and a 30-minute cooldown. A changed GB balance alone is never a receipt.
Unknown operations remain blocked across process restarts. Never wipe the DB
to recover a booking error.

The old live code persists usernames; this v2 journal intentionally stores
neither subscriber number nor email address.

## 3. Playwright interaction and session

- No stealth flags, CAPTCHA bypass, fake user agents or rate-limit evasion.
  Random waits are for pacing only. Read-only retry budget is two extra
  attempts on timeouts/connections; never automatically replay login submits
  or refill clicks.
- Use a stable viewport and browser-native user agent. Input helpers enforce
  exactly one target element and scroll/press sequentially but do not click.
- Authenticated storage_state is captured in memory using
  context.storage_state(indexed_db=True), encrypted with Fernet, atomically
  written as 0600 *.enc. Decryption produces a dictionary passed directly to
  browser.new_context(storage_state=...), with no plaintext JSON on disk.
- Session reuse is an optimization, **not** verification of authenticated
  identity; provider must revalidate current SIM/account before any action.
- REFILL_SESSION_FERNET_KEY must come from the host secret manager or process
  environment. Do not commit it or store it alongside encrypted data in
  .env. Do not regenerate it automatically when a key is lost.
- Never upload raw Playwright storage state, screenshots or HTML snapshots:
  these can expose credentials, tokens, full phone numbers, and personal data.
  Redacted/encrypted diagnostics are a future deliverable.

## Validation

    python -m pytest -q tests/test_refill_v2_db.py tests/test_refill_v2_humanizer.py

All tests are offline. They do not launch a browser or reach ALDI/Lidl.

## Remaining gates before production

1. A provider-authenticated BaseProvider contract with verified, authorized
   endpoints/locators and read-only SIM/tariff/price identity evidence.
2. Operation-specific official provider completion receipt. No inferred SUCCESS
   from allowance change or generic toast.
3. Browser/process crash recovery and concurrency integration, encrypted
   diagnostics and notifications, provider Terms compliance.
4. CLI, service supervision, configuration loading, Docker, read-only CI and
   staging acceptance. No hosted GitHub Action with live booking permissions
   without explicit approval and durable shared journal.

The v2 foundation intentionally cannot book a refill.
