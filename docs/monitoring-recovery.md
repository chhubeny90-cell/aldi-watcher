# Monitoring recovery: verified scope and remaining rollout

## Browser startup correction, 2026-10-07

The latest scheduled run's second attempt
(https://github.com/chhubeny90-cell/aldi-watcher/actions/runs/37597714666)
failed at `browser_start` for both providers. Its setup step installed Chrome
and ChromeDriver 155.0.8059.39, but Selenium selected the runner's preinstalled
Chrome 154.0.8037.57 and warned about the incompatible driver. Neither account
reached credential entry in that attempt.

Both browser workflows now pass `setup-chrome`'s `chrome-path` and
`chromedriver-path` outputs as `CHROME_BINARY` and `CHROMEDRIVER_PATH`.
`build_driver()` uses these explicit paths when supplied and retains local
discovery when they are absent. Provider login logic and the read-only workflow
remain unchanged. All 127 local tests pass, including regression coverage for
explicit paths and default discovery. Authenticated monitoring still needs a
successful live run; fixing browser selection does not establish portal access.

The validation run on the corrected branch
(https://github.com/chhubeny90-cell/aldi-watcher/actions/runs/37640387233)
passed its tests and successfully started both browsers. ALDI then timed out at
`username_field`: HTTP 200 on the official SSO host, zero visible inputs, two
failed resources and two severe script log entries. LIDL returned HTTP 403 with
zero visible inputs. Neither provider reached credential entry. These observations
do not establish an incorrect username or password. ALDI's configured login
number now has whitespace removed before form entry; the password is used as
configured. Further authenticated retries need new evidence that the public
login form is available on the execution host.

## Readiness follow-up, 2026-10-06

PR: https://github.com/chhubeny90-cell/aldi-watcher/pull/6
Public browser diagnosis: https://github.com/chhubeny90-cell/aldi-watcher/actions/runs/37482318763
Scheduled full run: https://github.com/chhubeny90-cell/aldi-watcher/actions/runs/37479323642

The latest scheduled full run still fails before credential entry on both providers.
A separate probe with no provider secrets narrowed the evidence:

- ALDI: SSO document loads; zero visible input fields; the single hidden frame is
  Usercentrics consent management, not a login form. An XHR on the SSO host returns
  HTTP 401. This does not establish bad credentials or the root cause of the
  missing form. The endpoint, response body and credentials are not recorded.
- LIDL: the public login document itself returns HTTP 403, as do two resources.
  No login fields or frames are visible. This does not establish an IP block.
- Diagnostic workflow success means the public inspection completed, not that
  either account authenticated. `portal_probe.py` refuses provider credentials,
  submits no form, retains only classified metadata, and is manual-only after merge.

88 local tests pass. The temporary diagnostic branch push trigger is removed.
No booking was enabled. Repeated authenticated runs without a new explanation for
these public-page failures would not validate a repair.

Release remains blocked pending these external prerequisites and acceptance tests:

1. Resolve the official portal's public-login failures with the provider or a
   supported execution host. Re-run the credential-free probe there, then prove
   session and protected usage for both accounts with booking disabled.
2. Select a persistent execution host and an independent heartbeat service plus
   notification destination. Configure the scheduler, observe multiple real runs,
   deliberately stop it and verify a delivered missing-heartbeat alert after the
   agreed deadline. A GitHub cron or successful artifact upload is not that test.
3. Enable required branch checks using repository administration access; the
   current GitHub connection cannot write branch protection.
4. Implement and validate actual tariff/refill evidence and provider reconciliation
   before any controlled booking rollout; neither public diagnostics nor mocked
   recharge tests prove those live prerequisites.

## Full-run hardening, 2026-10-06

The scheduled run `37399082074` on main `585b515` executed the watcher,
retained a finished report, and failed correctly: ALDI was rejected on the
official SSO redirect; LIDL returned HTTP 403 at username_field. Scheduling
therefore exists, but the configured ten-minute interval is not proven reliable.
The earlier statement below that the latest run was in July is historical.

ALDI's login redirect was verified without credentials from the configured
portal, to `login.alditalk-kundenbetreuung.de/signin/XUI/`. Only that exact
HTTPS host and login path are accepted as an additional credential-entry origin.
Protected-page validation still requires the configured portal origin.
Official source: https://www.alditalk.de/tarifverwaltung (Mein ALDI TALK).

The official https://www.lidl-connect.de/ customer-account link points to
https://kundenkonto.lidl-connect.de/, which was observed redirecting to
/mein-lidl-connect.html with HTTP 200 and a login form. Monitoring now uses
that entry instead of the /mein-lidl-connect/uebersicht.html URL that returned
403 in Actions. Public endpoint reachability is not authenticated live success.

The second full run `37421394774` on `ff5836b` passed tests but failed live:
ALDI had zero visible inputs at username_field; LIDL still returned HTTP 403
on its corrected public entry, despite HTTP 200 from the development environment.
Both provider checks finished with booking disabled. A final check uses ALDI's
customer-area link published directly on https://www.alditalk.de/:
https://www.alditalk-kundenportal.de/portal/auth/uebersicht/.
SSO document-status matching now ignores URL fragments, without retaining URLs.

LIDL booking now makes one attempt on the selected channel. An uncertain API
outcome never falls back to browser booking; a click followed by timeout never
repeats the click and is persisted as UNKNOWN. Terminal DB outcomes cannot be
overwritten by stale recovery results. Tests cover both crash boundaries,
terminal recovery, concurrent stale recovery, lock timeout, and invalid flags.

Three explicitly authorized complete test-and-monitoring jobs ran on the
validation branch, using existing Actions Secrets without retrieving or exposing
them. The temporary push-to-watch condition has been removed. Regular push/PR
runs execute tests only; schedule and workflow_dispatch execute the safe watcher.

Final full run: https://github.com/chhubeny90-cell/aldi-watcher/actions/runs/37421795572
Commit: `cdb87edc182bfecf537e4d6466a11946b6325c74`.
Tests: 85 passed without warnings. Live result: failed, exit 1; both providers
were attempted, a finished heartbeat was uploaded, and no booking was executed.
ALDI: official SSO host, HTTP 200, username_field timeout, zero visible inputs,
one frame, one severe browser log entry and one failed resource.
LIDL: corrected entry, HTTP 403, access_denied, zero visible inputs.
These counts do not identify the ALDI script-error cause or prove that LIDL is
blocking by IP. No invalid-password conclusion is supported: no visible username
field was found in either provider run. Further live repair requires investigating
the frontend resource failure and the portal's access-denied response.

Remaining gates: real session/usage success; verified tariff/refill evidence;
provider status reconciliation; enforced branch checks; independent heartbeat
delivery with an explicitly chosen destination. No live booking is enabled.

## Active deployment

Baseline main commit: `ea482c9a8e868b3ce3ebe63ca74f99e5d55708c3`.
GitHub Actions `.github/workflows/run.yml` launches `watcher.py` in an ephemeral
Python 3.11 runner. It does not launch `main.py` or the plugin orchestrator.
No systemd service, virtual environment, encrypted home configuration or persistent
SQLite database is configured by this workflow. Local systemctl output would not
establish anything about the GitHub runner or another user's machine.

The plugin recharge concurrency/crash tests do not cover the old Selenium booking
functions. This change removes those booking functions from the monitoring entry
point. Setting AUTO_BOOK_ENABLED=true now produces exit 3 before opening a browser.
The plugin implementation remains separate and is not production-approved by this PR.

## Execution and result contract

```
AUTO_BOOK_ENABLED=false python watcher.py --run-once
AUTO_BOOK_ENABLED=false python watcher.py --run-once --provider aldi_talk
AUTO_BOOK_ENABLED=false python watcher.py --run-once --provider lidl_connect
python -m pytest -q
```

Credentials remain ALDI_USER/ALDI_PASS and LIDL_USER/LIDL_PASS environment variables
or GitHub Secrets. Selecting one provider needs only that provider's credentials.

Exit 0: all selected providers successfully authenticated and usage validated.
Exit 1: no successful check (including zero providers).
Exit 2: some successful checks and some failed checks.
Exit 3: missing credentials or unsafe/invalid booking configuration.
GitHub marks both exit 1 and 2 red; degraded is yellow only conceptually, not a native
Actions job conclusion. Details appear in the step summary and JSON artifact.

Unknown statuses, circuit_open, missing usage, ambiguous volume, NaN, negative
volume and authentication failures never count as success.

Each provider gets a separate browser. Result records include run_id, provider,
phase, status and elapsed_seconds. A run_id is shared with the start/end heartbeat.
The atomic report is mode 0600. GitHub preserves only this allowlisted report for
seven days, including failed runs. No screenshot, HTML, account text, password,
phone number, cookie value, authorization header or token is stored in the report.
HTTP metadata is diagnostic evidence, not proof of successful authentication.

## Login evidence and diagnostics

The existing provider URLs and input selectors are retained pending live evidence.
URLs alone cannot establish login. A visible logout control, absence of a visible
password field, cookies, protected-page validation and unambiguous labelled volume
are required. This is intentionally conservative and may reject a legitimate portal
with different markup. A redirect to another origin is rejected before credential
entry; observed legitimate SSO hosts must be reviewed before adding support.

Phases distinguish login_page, username_field, password_field, login_submit,
session_validation, protected_page, usage_parse and browser_start. Browser page
loads have a 20-second timeout; element waits are 30 seconds. Only idempotent page
GET navigation is retried, once with exponential delay and jitter. Form submission
is never automatically repeated. Driver shutdown and provider isolation are tested.

HTTP status, redirect count, DOM CSRF indicator, visible password field, host
allowlist result and cookie count are best-effort evidence. Unavailable values
remain null; DOM csrf_found=false is not proof that a JavaScript portal lacks CSRF
protection. Network metadata currently covers document responses, not every fetch/
XHR request. DNS/TCP/TLS timings and full SSO/API diagnosis are not yet implemented.
401/403/429/5xx document responses classify failed checks where available.
No HTTP-rate-limit retry is implemented: 429 is reported, not retried, so Retry-After
is not ignored by an aggressive retry loop. No circuit breaker is deployed; a new
one would need state persisted across ephemeral runners.

## Scheduler and independent alerting

The workflow keeps `*/10 * * * *`. API inspection on 2026-10-05 returned the newest
scheduled run as 2026-07-31T22:17:09Z (2026-08-01 00:17 Berlin), run 30669457678.
This does not establish why scheduling stopped. Manual green runs do not validate
scheduled operation. After merge, check workflow enablement in GitHub, enable it
if disabled, and observe several runs whose event is `schedule` on the new commit.

Step summaries and Actions error annotations are implemented. Delivery of GitHub
failure notifications depends on the account's notification settings. Telegram/
email delivery and an independent >20-minute missing-heartbeat alarm are not
configured. An alarm running inside the same unscheduled job cannot detect that
job's absence. A separate scheduler/service and an explicit destination are needed.
Artifacts retain per-run history; there is no persistent monitoring SQLite history
in the active Actions deployment.

## Live rollout gate

1. Merge reviewed PR; run workflow_dispatch on the new commit with booking false.
2. Inspect per-provider phase and safe diagnostic metadata; confirm or fix actual
   portal selectors/SSO based on observed evidence, without logging secrets.
3. Confirm authenticated protected data on both providers; test failures as well.
4. Observe multiple real schedule events and retained finished heartbeat artifacts.
5. Configure and independently test missing-heartbeat and failure notifications.
6. Only then design controlled booking through the persistent idempotent engine,
   with verified tariff option, balance, volume threshold, daily limits, minimum
   interval, cross-run persistence and unambiguous post-booking reconciliation.

No live booking or authenticated production success is claimed by this PR.
The suggested 20/day and 300-second limits are proposals, not validated provider
limits or permission to perform real transactions.

## Public endpoint probe (no credentials)

A probe from the development environment on 2026-10-05 returned HTML HTTP 200
after redirects for the configured ALDI login URL (about 53 seconds), and HTTP
401 for the configured LIDL URL (about 14 seconds). This was not a browser login
and does not prove invalid user credentials or reproduce GitHub runner behavior.
Both endpoints require further browser-specific diagnosis before declaring a fix.
