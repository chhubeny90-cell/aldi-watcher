# Local durable mail sensor (WATCH-DAUERBETRIEB-20261020)

Overall release remains **BLOCKED**. This component only reads IMAP and stores
non-actionable observations. It never dispatches a provider job, logs into ALDI,
books data, changes tariffs, resolves provider UNKNOWN, or emits LIVE_READY.

Base: current main d0bb785, reviewed draft #121 b044402 and the independently
reviewed ACK-thread fix #123 e4b6ac0. PR #104/#108 are historical references only.

## Actual implemented loop

- Default: no network. Real IMAP reads additionally require
  `ALDI_IMAP_MONITOR_ENABLED=true`, existing mailbox configuration, the ORIGINAL
  history-compatible `ALDI_RECOVERY_KEY`, and an explicitly initialized sensor ledger.
- Poll every 60 seconds after a cycle; this is a minimum wait, not an exact SLA.
  Each mailbox has independently persisted 60/120/240/.../900-second network backoff.
- Login/protocol errors and changed UIDVALIDITY latch BLOCKED until independently
  reconciled. They are not retried each minute. Successful polling resets backoff.
- Read-only INBOX, UID SEARCH and BODY.PEEK. Includes read messages, unlike UNSEEN.
  UID identity is HMAC(host, port, user, folder) + UIDVALIDITY + UID.
- Oldest-first batches of at most 100; a failed fetch does not advance past it.
  Filter reversed UID search ranges. INTERNALDATE, not a caller-controlled Date
  header, enforces the approved initial cutoff. Refuse oversized body downloads.
- A second stable message identity detects reimports under a new UID even when
  the Date header changed. Two configured mailboxes keep separate progress.
- Observation and UID cursor commit atomically in SQLite with FULL synchronous
  writes. Reopen after process failure does not replay committed observations.
  Missing/corrupt/rekeyed history is rejected, never silently recreated.
- Candidate classifier is NOT an authenticity proof: even a consumed signal is
  stored as BLOCKED. Warnings never authorize actions. Real mail/SIM/tariff binding
  and trusted delivery/authentication evidence remain downstream requirements.
- Reports contain counters and fixed states only; no subjects, sender addresses,
  mailbox usernames, Message-IDs, raw bodies, passwords or exception text.

## Ownership of states

IDLE and RETRY_WAIT belong to the sensor. Detection and metadata validation occur
before committing an observation. Consumed candidates remain BLOCKED, not READY.
PENDING, UNKNOWN and COMPLETED belong to the existing actor/booking journal and
receipt contract. This sensor does not create a competing booking state machine.
It does not join the remote queue or turn its local observations into live orders.

The sensor SQLite ledger is progress metadata, separate from booking authority.
Creating it does NOT initialize/migrate the private booking journal or reset the
existing remote HMAC/tombstone history. Local observation dedupe is not proof of
end-to-end booking dedupe. No historical migration is implied by the cutoff.

## Operator commands after review and private configuration

Do not generate/replace a recovery key to run these commands. Use a dedicated
private directory outside the checkout and protect it with POSIX 0700/0600 or
reviewed owner/SYSTEM/Administrators-only Windows ACLs. Existing history is never
replaced. Initialization requires an operator-approved timezone-aware cutoff.

```text
python mail_monitor_daemon.py --ledger <absolute-private-sensor-ledger> --initialize --cutoff <approved-ISO-timestamp-with-offset>
python mail_monitor_daemon.py --ledger <existing-sensor-ledger> --verify-backup
python mail_monitor_daemon.py --ledger <existing-sensor-ledger> --once
python -u mail_monitor_daemon.py --ledger <existing-sensor-ledger> --report <same-private-directory/report.json>
```

`--verify-backup` copies locally, closes/reopens, checks integrity and deletes its
private temporary copy. It is not off-host backup or a real power-loss test.
Report writes use an atomic sibling temporary file; they cannot overwrite the ledger.
SIGINT/SIGTERM stop the wait loop gracefully. A missing ledger fails before IMAP.

## Windows preparation

`scripts/windows/Register-MailSensor.ps1` is a current-user, LIMITED, at-logon
Task Scheduler registration script. It checks existing paths and restrictive ACLs,
refuses an existing task, and supports `-WhatIf`. No password, mailbox credentials
or key appears in task arguments. It does not create history, set secrets, enable
IMAP, start a task or start a provider actor. It uses IgnoreNew, three bounded
restart attempts at five minutes, and no default three-day execution time limit.

This is AT LOGON after a reboot, not unattended operation before login. The machine
must remain powered and awake; an interactive task does not solve sleep/offline
periods. Credentials/opt-in must already exist in the actual task's private runtime.

The Windows CI job executes synthetic IMAP and real local SQLite tests and parses
the PowerShell script natively. Even green CI does not prove task registration,
actual Windows ACL setup, automatic boot/logon recovery or IMAP access on the user's
machine. Those real-host checks remain outstanding; Linux POSIX live-actor guards
are not removed to claim Windows booking support.

Microsoft settings reference:
https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/new-scheduledtasksettingsset

## Remaining release gates

Original key availability and full historical state, real IMAP run/repeat evidence,
trusted mail identity and SIM mapping, private host persistence/ACLs, reviewed offer
relationship, provider completion/recovery and specific live authorization.
Never release an unresolved provider reservation because this sensor restarted.
