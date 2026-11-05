# Owner-gated ALDI hosted session (manual-only proposal)

This is a **review-only proposal**. It is not provider authorization and it does not enable live account automation by itself.

## Default behavior

- Manual `workflow_dispatch` only. No schedule, mail wake-up, push, or pull request provider job.
- The default `preflight` only checks presence of configuration and reports boolean readiness. It does not load raw credentials or contact ALDI.
- `initialize` prepares the encrypted persisted state but does **not** authenticate with ALDI. Initialization writes durable state/marker data to GitHub and is not reversible by deleting the last run.
- `observe` attempts a read-only authenticated session **only after** the explicit gating conditions below pass.
- There is **no `refill` or `automatic` dispatch mode**, and `AUTO_BOOK_ENABLED=false`. No provider bookings are authorized by this workflow.
- No raw cookies, SQLite journal, login credentials or screenshots are uploaded as public artifacts. Only the sanitized runtime summary is presented. **Encrypted runtime state still lands in the public repository's Git history**, so encryption-key management and visibility must be reviewed separately.

## Prerequisites before changing default-deny settings

1. Obtain **explicit provider authorization** for scripted customer-portal access. Being the account owner is not itself sufficient under the policy documented in `docs/aldi-safe-manual-live-check.md`. No such provider authorization has been independently verified by this PR.
2. Configure GitHub Environment `aldi-session` with **required reviewers** and restrictive deployment branch rules for `main`. An environment name in YAML alone does not impose reviewers. Prefer environment-scoped secrets.
3. Review the irreversible encrypted-state initialization and recovery path, account targeting, durable journal and public repository exposure. Do not replace or silently regenerate historical encryption keys or journals.
4. Only after written approval and security review, set repository variable `ALDI_SCRIPT_ACCESS_APPROVED=true` and a nonempty `ALDI_PROVIDER_APPROVAL_REFERENCE`. Record the authorization evidence privately, not in public Actions logs or this document. These flags are declarations, not cryptographic proof of provider consent.
5. Configure `ALDI_PROFILE_1_USER`, `ALDI_PASS` or `ALDI_PASS_ENC`, `CREDENTIAL_ENCRYPTION_KEY` when needed, and `ALDI_STATE_ENCRYPTION_KEY` as private GitHub secrets. Never put real values into YAML, commits or workflow logs.

## Operation

After merge to `main`, run `preflight` and review the booleans. With all prerequisites independently fulfilled, use `initialize` once and inspect the persisted state. Later, run `observe` once. Every dispatched `initialize` or `observe` also requires selecting the explicit provider-authorization checkbox and may require a protected environment approval.

**Do not use this workflow for scheduled retries or free-1GB bookings.** A separate, reviewable PR and verified operation-bound provider completion proof are needed for any future booking mode. On uncertainty or lost state: stop, recover the durable journal, and do not retry a provider-changing operation.

## Rollback

Keep the provider approval flag absent or set to false to block the session job. Disable the workflow if needed. Roll back the code through a new PR; do not delete or reset journal and state blobs until a backup/recovery plan has been checked. Rotate exposed credentials if logs or artifacts accidentally disclose secrets.
