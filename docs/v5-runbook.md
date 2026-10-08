# ALDI Watcher V5 deployment

The default is DRY_RUN. Code and deployment files do not mean a working live
subscription. LITE becomes READY only after an actual mail starts a verified
free 1-GB refill, the provider confirms success and the process exits.

## Deployment choice

Run one listener on one persistent host with one SQLite volume. Render with a
persistent disk, an existing Oracle VM or a Google Compute Engine VM can host
this arrangement. Cloud Run's ephemeral filesystem and ordinary GitHub Actions
jobs do not provide this database's durable single-host locking. GitHub Actions
can still run tests. An existing VM is usually the smallest setup. Render disks
require a paid service; Oracle availability and Google Cloud charges must be
checked in the actual account. No service was provisioned by these files.

## Initial setup

Use the existing repository. Copy `deploy/v5/.env.example` to the ignored
`deploy/v5/.env.v5`, set mode 0600 and provision credentials privately. Explicitly
map `ALDI_MAILBOX` to the account named by `ALDI_ACCOUNT_ALIAS`. Use a logical
alias such as `primary`, never a phone number. Do not infer the mapping from a
message greeting. Set provider selectors only after observing the authenticated
ALDI account. Empty or ambiguous evidence blocks booking.

From `deploy/v5`, build and verify in this order:

```sh
docker compose build lite
docker compose run --rm --no-deps lite python -m lite login-probe
docker compose run --rm --no-deps lite python -m lite mailbox-check --dry-run-events
docker compose run --rm --no-deps lite python -m lite mailbox-init
```

`mailbox-check` reads at most ten recent relevant messages by default; output is
only classifications/counts. Its optional provider test uses an isolated DRY_RUN
database, so historic test messages do not consume live events. `login-probe`
performs a regular login and emits booleans only. It never clicks a refill.
MFA/CAPTCHA requires the provider's regular user action. Do not bypass it.

`mailbox-init` sets a verified mailbox's first cursor to its current history,
without booking historic mail. Repeating it preserves the existing cursor.
Messages received before initial setup are intentionally not automatically
replayed. A manually selected local event can be tested with:

```sh
python -m lite event --event-file /private/event.json
```

The JSON has exactly `event_id`, `mailbox`, `mail_id`, `received_at` (UTC epoch
seconds), `kind` (`warning80` or `exhausted`), and `account`. Keep it private. The
local event command requires DRY_RUN and rejects live mode. Productive triggers
come only from authenticated Gmail messages, never caller-supplied event JSON.

## Gmail push

Provision Gmail API OAuth with the `gmail.readonly` scope and a durable refresh
token in an appropriate production OAuth configuration. A ChatGPT Gmail connector
does not export an OAuth refresh token or provide an always-running push bridge
for this deployed process. Gmail OAuth consent in testing mode may expire refresh
tokens after seven days, so verify the application's actual consent status.

Create a Pub/Sub topic in the same Google Cloud project used for the Gmail watch.
Grant **only Pub/Sub Publisher on that topic** to
`gmail-api-push@system.gserviceaccount.com`, as required by Gmail's official push
guide. Create a push subscription to the host's exact HTTPS endpoint
`https://YOUR_DOMAIN/pubsub/gmail`. Select a dedicated service account for signed
OIDC push authentication and configure that exact URL as its audience. Grant the
Pub/Sub service agent the required service-account token creation role; the user
who configures the subscription also needs permission to act as the selected
service account. This service account needs no Gmail or ALDI credentials.

Set `GMAIL_PUBSUB_TOPIC`, the full `PUBSUB_SUBSCRIPTION` resource name,
`PUBSUB_PUSH_AUDIENCE` and `PUBSUB_SERVICE_ACCOUNT_EMAIL`. The listener verifies
Google's signature, audience, issuer, verified service-account email, subscription
and configured mailbox. Unsigned requests never start LITE. Pub/Sub's message is
only a notification; authenticated Gmail History supplies the actual email.
Keep Pub/Sub retries/dead-letter monitoring enabled so permanent failures are
visible. Configure the subscription's retry policy with a minimum backoff of
60 seconds and a maximum of 600 seconds, avoiding rapid repeated logins. Choose
a reasonable acknowledgement deadline; a login can take longer
than the default, and duplicate notifications are expected and safe.

For the included TLS proxy, set `LITE_PUBLIC_DOMAIN`, point DNS at this host and
allow ports 80/443. Caddy handles TLS. If an existing managed HTTPS proxy is used,
forward only `/pubsub/gmail` and optionally `/health` to local port 8080.

```sh
docker compose run --rm --no-deps lite python -m lite watch-renew
docker compose --env-file .env.v5 --profile pubsub up -d
```

The `serve` process now renews Gmail watch on startup and every day, and catches
up Gmail History every five minutes even when a push notification is lost. Both
use the same transport lock and persistent cursor as push delivery. Failures are
retried at most once per minute. No idle Gmail poll or renewal logs into ALDI;
only verified messages start LITE. Watch renewal preserves the processing cursor.
Do not install the separate renewal/poll units alongside this supervised server.
Those units remain alternatives for a deployment without `serve`.
The TLS container receives only `LITE_PUBLIC_DOMAIN`; ALDI and Gmail credentials
are passed solely to the LITE container.

`/health` reports HTTP liveness only. `/ready` reports **mail transport** readiness
and returns 503 before the first successful renewal/sync, after a maintenance
error, or when successful maintenance becomes stale. Docker checks `/ready`.
`booking_readiness=not_assessed` deliberately distinguishes this from successful
provider login, refill eligibility or cleared PENDING/UNKNOWN reservations.
Inspect those separately with WATCHDOG and the account probes. Docker marking a
container unhealthy does not restart it automatically; `restart: unless-stopped`
only restarts an exited process. An independent monitor on another host must
observe the health status and alert on missing responses. That monitor and its
delivery destination have not been provisioned by these files.

The five-minute fallback covers missed Gmail push notifications, **not missing
ALDI warning emails**. A provider-side fallback still requires verified account
state and an authorized durable host; it is not enabled by this transport change.

Each processed event writes one concise UTC status line, for example
`07:32 MAIL → CHECK → REFILL → SUCCESS` or
`07:32 MAIL → CHECK → FAILED → login_not_confirmed`. Logs contain no mailbox,
event/booking IDs, credentials or exception bodies. Idle checks are silent.

Official reference:
<https://developers.google.com/workspace/gmail/api/guides/push>
<https://cloud.google.com/pubsub/docs/authenticate-push-subscriptions>

## Live operation and recovery

After authenticated provider evidence, the dry run and durable-host checks pass,
set `DRY_RUN=false` and `AUTO_BOOK_ENABLED=true`. An explicit absolute
`LITE_DB_PATH` is mandatory in live mode. Recreate the listener with the same
volume. LITE is the sole booking component. Portal price/account/tariff checks
and unresolved bookings still block any uncertain action.

Keep one replica, one explicitly bound ALDI account alias and the same SQLite
volume across restarts/deployments. The core rejects a second alias in that
database and serializes ALDI access with a shared process lock. The
mailbox transport lock prevents concurrent cursor updates; each event commits
before the history cursor advances. A busy engine or a failed journal returns
HTTP 503, causing redelivery. A crash after some events commit safely replays the
batch and deduplicates them. Old notification history IDs are acknowledged without
querying ALDI. PENDING/UNKNOWN reservations survive crashes and require provider
reconciliation; they never trigger a blind second click.

Use `python -m lite recover` (or the corresponding `docker compose run` command)
after a restart to reconcile existing reservations without creating any event,
reservation or booking. Output contains only counts and statuses. UNKNOWN remains
unresolved and exits with an error; it does not mean recovery is READY. A provider
history or booking-ID confirmation is required to clear that uncertainty.

The optional `LITE_RECENT_SUCCESS_GUARD_SECONDS` defaults to zero. A valid new
exhaustion event can therefore refill as soon as ALDI independently proves a new
free offer with no pending booking. A configured cooldown returns BUSY for later
processing rather than consuming the message and losing a legitimate refill.

An expired Gmail history cursor is a visible error. Do not reset the database or
cursor to hide it: review the delivery gap and selected messages in DRY_RUN,
reconcile provider reservations, then deliberately re-establish the transport.
The included transport does not silently replay stale messages in live mode.

Do not run old provider polling/refill jobs alongside LITE. Keep any existing
production service running until the replacement is actually verified, then
ensure only LITE owns booking. No old workflow was stopped by this runbook.

WATCHDOG and PRO read the same database; their separate commands never book.
Back up SQLite with its backup API or while the service is stopped. Preserve the
volume when rolling back the image. Tag a known working version only after the
real end-to-end READY conditions pass; do not label a dry run as a live release.
