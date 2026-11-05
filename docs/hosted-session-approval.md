# ALDI hosted session — owner-gated manual and scheduled refill (PR #156)

**Deployment remains blocked by default.** This PR prepares code and tests; it does not prove that ALDI has authorized scripted customer access. Repository variables are declarations, not permission evidence.

## Modes and triggers

| Trigger | Mode | Behavior |
| --- | --- | --- |
| Manual workflow_dispatch | preflight (default) | Checks configuration presence; no ALDI request |
| Manual workflow_dispatch | initialize | Creates encrypted state and journal; no ALDI login |
| Manual workflow_dispatch | observe | One authenticated read-only status check, with gates |
| Manual workflow_dispatch | refill | At most one guarded free 1-GB refill attempt |
| Cron (21 * * * *, hourly UTC) | automatic | Checks account and may perform one guarded free 1-GB refill |

Cron is selected by the schedule event, not a manual input. GitHub schedules may be delayed or dropped.

The existing provider-changing runner remains authoritative: an exact single enabled +1 GB control, the correct verified account and eligible active tariff, less than 1.0 GB remaining, explicit local price 0.00 EUR, fresh pre-click identity/offer/confirmation checks, persistent journal reservation, UNKNOWN/PENDING lockout, 30-second cross-run success cooldown, provider-operation-bound completion and one refill per run. Ambiguous, priced or unconfirmed results never authorize a second click. Only an independently verified terminal provider receipt can count as SUCCESS.

## Required Repository Variables

Set at Repository → Settings → Secrets and variables → Actions → Variables.

| Variable | Required value | Purpose |
| --- | --- | --- |
| ALDI_SCRIPT_ACCESS_APPROVED | true only after documented provider permission | Gate for any scripted portal access |
| ALDI_PROVIDER_APPROVAL_REFERENCE | Nonempty permission reference, no private document | Link to independently held provider authorization |
| ALDI_OWNER_AUTO_REFILL_APPROVED | true | Persistent owner permission for unattended scheduled access/refill |
| ALDI_LIVE_REFILL_APPROVED | true | Separate owner permission for booking-changing actions |

All are default-deny when absent. The manual dispatch also requires confirm_provider_authorization=true. Cron uses durable ALDI_OWNER_AUTO_REFILL_APPROVED instead of a per-run checkbox; it still requires provider authorization and booking approval.

## Required Repository Secrets

Set at Repository → Settings → Secrets and variables → Actions → Secrets. Current preflight reads only presence booleans, so configure at repository scope.

| Secret | Usage |
| --- | --- |
| ALDI_PROFILE_1_USER | Exact private target account / SIM for account binding |
| ALDI_REQUIRED_TARGET_SUFFIX | Exactly four target digits; required for any refill |
| ALDI_PASS or ALDI_PASS_ENC | Private customer credential |
| CREDENTIAL_ENCRYPTION_KEY | Required when ALDI_PASS_ENC is used |
| ALDI_STATE_ENCRYPTION_KEY | Existing valid Fernet key, preserve for all historical encrypted journal snapshots |

The GITHUB_TOKEN is provided by GitHub Actions; do not create it as a secret. The gated session job has write permission solely to persist encrypted state and journal through CAS. No raw session cookies, credentials, databases or screenshots are uploaded as CI artifacts.

## GitHub Environments and branch controls

Create the GitHub Environments named **aldi-session** (for manual dispatch, prefer required reviewers) and **aldi-auto** (for Cron, no per-run reviewers, or the unattended job stalls). Restrict both to main only, keep secrets private, and configure required CI/reviews on main. This PR does not configure environment protection or provider authorization on your behalf.

## Rollout gates

1. Independently verify written provider permission for automated authenticated access; owner approval alone is not sufficient under the repository's documented ALDI policy.
2. Review encrypted state persistence, branch protection, durable journal, account targeting, target suffix and key backups. The public repository retains encrypted cookies and SQLite journal data in Git history: a leaked key would expose them.
3. After provider approval, configure the above variables, secrets and environments. Leave ALDI_SCRIPT_ACCESS_APPROVED=false until the review is finished.
4. On main: dispatch preflight, then initialize **once** (never recreate a missing historical journal), then observe and validate correct SIM/tariff/volume and explicit zero price.
5. Only after these steps allow a single refill acceptance run or unattended Cron. A first scheduled run may attempt the refill directly if the durable owner approval is true, but only through the same 0.00 EUR/journal/completion guards.
6. On UNKNOWN, PENDING, account lock or ambiguous provider response, stop and reconcile manually. Do not reset state or automatically retry.

## Emergency stop and rollback

Set ALDI_SCRIPT_ACCESS_APPROVED=false (and ALDI_OWNER_AUTO_REFILL_APPROVED=false) to block authenticated runs. Disable hosted-session.yml to suppress further scheduled preflight jobs. Never delete or reset encrypted history, and never treat a git revert as reversal of a provider-side booking.

**Unverified at PR creation:** provider permission, actual account/offer evidence, current configured environment protections, and provider-side completion behavior. CI green does not establish these facts.
