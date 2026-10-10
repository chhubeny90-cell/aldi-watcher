# Protected ALDI multi-account checks

Account numbers and passwords belong in an encrypted private manifest, never in
this repository. The private mapping uses account_a through account_e.

Create a local JSON with version=1 and an accounts array. Each account has
account_id (account_a, etc.), provider (aldi_talk), account_user (international
phone format), optional login_user (the actual portal identifier), enabled
(boolean, initially false), and policy (monitor_only or free_unlimited).

Run python encrypt_aldi_accounts.py /absolute/private/accounts.json locally.
The shared password and existing Fernet key are requested without echoing.
The command creates an owner-only encrypted file and refuses to overwrite it.
Store its content as GitHub secret ALDI_ACCOUNTS_ENC, and the existing key as
CREDENTIAL_ENCRYPTION_KEY. No connector used by this change can write secrets.

Each enabled profile gets a fresh Selenium browser and an exact selected-SIM
identity check. A linked SIM is selected only through the existing account menu;
accounts are never merged or logged out. Reports contain anonymous account IDs
and allowlisted status fields. An ALDI account is declared by the manifest and
verified against the trusted ALDI portal; the mobile prefix is not used to infer
the provider. The booked-product view identifies annual/base tariffs.

The new ALDI Accounts workflow runs manually. Its hourly schedule is inactive
unless repository variable ALDI_ACCOUNTS_MONITOR_ENABLED=true. Set enabled=true
for individual profiles only after confirming their login identifier/password.
Do not activate repeated login attempts while credentials are rejected.

All scheduled multi-account runs remain read-only. free_unlimited records the
requested booking policy, not an authorization or proof of eligibility.
Recurring live refill remains blocked until authenticated target identity,
active Unlimited tariff, free 1-GB control, and durable cross-run reconciliation
are proven. The separate existing manual live workflow is unchanged.
