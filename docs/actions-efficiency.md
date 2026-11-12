# Actions efficiency and hardening — 28 October 2026

## Changes

- Feature branches use pull-request checks rather than running the same Python
  checks on both push and pull_request. Push checks remain on main and develop;
  manual runs remain available. Both Python 3.10 head-commit and Python 3.11
  merge-commit regression checks, and CodeQL, are retained.
- Superseded PR checks can be cancelled. Workflow name, event and PR/ref identify
  the concurrency group; schedules, manual runs and main pushes are not cancelled.
  Stateful mailbox/refill workflow concurrency is unchanged.
- Python 3.10 installs use the pip cache and have a ten-minute job timeout. Its
  full pytest run already includes the migration/hardening subsets, so those
  subsets no longer run twice in the same job.
- Scheduled jobs install only their actual runtime dependencies. Root
  requirements remain the version-constraint source. The public probe uses
  Selenium; neither scheduled job installs Playwright, pytest or aiohttp.
  Both entrypoints are imported in fresh virtual environments in PR/main CI to
  detect missing transitive dependencies without logging into any service.
- Actions in these four workflows are pinned to upstream tag-resolved commit
  SHAs. Checkout does not persist credentials. CodeQL upload permission is scoped
  to its analysis job. Mailbox passwords, the deduplication key and the explicit
  state-write token are passed only to the mail-polling step, not the dependency
  installation or artifact-upload steps.

## Expected effect and limits

The current PR event launches three workflow runs: the ALDI Watcher workflow
has two jobs (the setup-python regression and full test suite), Python
compatibility has five matrix jobs plus its aggregation job, and CodeQL has one
analysis job. That is nine jobs before considering skipped schedule/manual-only
jobs. The earlier five-job estimate no longer applies after main added a
separate setup-python regression and expanded Python compatibility to a matrix.
Job count is not a measurement of runtime or billing. Cache hits and dependency
downloads determine actual resource use.

Public portal checks still run every fifteen minutes and the mail monitor runs
hourly. The explicit Chrome/driver setup, seven-day reports, mailbox failure
reporting and all booking/account/recovery guards remain in place. Existing
mailbox configuration failures are not hidden. No provider login, booking or
recurring refill is activated by this change.

## Validation

Run `python scripts/check_workflow_dependencies.py` for isolated dependency
imports, `python -m pytest -q` for regressions, and actionlint for the four changed
workflow files. Scheduled entrypoint imports perform no polling, login or booking.
Branch pushes without a PR no longer receive automatic Python CI; open a PR or
use the manual workflow dispatch when that validation is needed.
