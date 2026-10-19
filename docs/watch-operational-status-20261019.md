# ALDI-WATCHER-COMPLETE-20261019: operational checkpoint

Overall status: **BLOCKED**. Responsible implementation: ChatGPT/Codex.
Starting main / HEAD_BEFORE_PATCH: `2ff0d1a2b514e646f6a282909498c40cbcb10109`.

## Independently observed on 2026-10-19

PR #111 was merged as `0cb8fbed878cdc1bf9507b475b545ce955095305`.
Its post-merge code review at 06:06 UTC reports no findings. Main additionally
contains PR #112 (hourly mail schedule and stronger refill configuration gates).

Configuration source: guarded preflight run
https://github.com/chhubeny90-cell/aldi-watcher/actions/runs/39207953484
job `117914791071`, output at 06:05:53 UTC (08:05 Europe/Berlin):

| Check | Observed |
| --- | --- |
| General account and password | configured |
| At least one mailbox | configured |
| Expected account `ALDI_PROFILE_1_USER` | absent |
| Stable `ALDI_RECOVERY_KEY` | absent |
| Journal path repository variable | absent |
| Private runner availability | unverified |
| Manual refill configured | false |
| Refill execution | skipped |

Configuration presence is not credential validity, mailbox login, account/SIM
binding or host evidence. No secret values were retrieved or changed.

State branch ref inspected: `5c6949237e9e82c1275cbcc2236201828ebedc38`.
At that exact immutable tree, `.aldi-state/profile-1.json` has schema version 2,
zero unresolved operations and an expired authentication backoff. No mail queue,
legacy trigger/history or tombstone file exists in that tree. This is not proof
of complete historic deduplication or the private SQLite journal's integrity.
No remote state was initialized, overwritten or cleared.

## Changes in this checkpoint

- Release evidence schema 2 removes the circular requirement for the yet-to-run
  operation's receipt. It instead requires separately evidenced completion and
  recovery contracts. Full catalog, exact commit/snapshot, evidence freshness,
  authorization and account binding remain mandatory. Schema 1 is rejected.
- A private-runtime probe opens only an existing journal read-only, validates
  private permissions/schema/integrity and closes/reopens a private local backup.
  It reports unresolved counts without paths, accounts or operation identifiers.
  Missing state is never initialized or repaired. Temporary backups are removed.
- An optional, manual-only readiness job can run that probe on the private
  `aldi-journal` runner. No provider credentials, browser or refill invocation.

## Remaining external and provider-dependent work

GitHub's current cloud-browser session is stopped by a mandatory 2FA checkup.
GitHub explicitly reports it is not authorized to send SMS to the configured
recipient. The only visible alternatives are SMS resend and account 2FA
reconfiguration. No resend, credential change, recovery-code use or 2FA bypass
was performed. The connector can read repository data, but does not expose
secret/variable administration, runner registration or workflow dispatch.

The account owner must restore this GitHub session's 2FA through the secure
handoff. Then configure the verified target account, recover the original HMAC
key (or perform an independently reviewed historic identity migration), and set
the actual persistent journal path on an existing private runner. Do not choose
an invented path or create an empty journal to replace lost operational state.

The hourly monitor exists but cannot deduplicate without its key. There is no
verified real mail-to-SIM admission and completed actor handoff. The manual
refill workflow's configuration flags do not prove a consumed event. Do not use
it to bypass the required real mail event and account mapping. Historical
identities evicted before migration need authoritative reconciliation. The mail
queue still prohibits COMPLETED because a trusted receipt-to-event integration
is unproven. The provider completion parser exists; its real schema and historical
reconciliation remain unverified. Do not guess lookup endpoints or clear UNKNOWN.

Before the authorized one-shot run, prove real consumed-mail binding, fresh
account/tariff and explicit 0-EUR 1-GB offer, durable journal/host, complete guards,
and the real completion/recovery contract. Then execute at most one attempt and
require the operation's official receipt for SUCCESS. Do not activate recurring
bookings. No provider login, booking, artificial consumption or tariff change
was performed during this checkpoint.
