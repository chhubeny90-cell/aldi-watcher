"""Offline checks: provider and owner approval must fail closed before any portal work."""

import pytest

from aldi_hosted_runtime import HostedRuntimeError, _authorization_context


@pytest.fixture
def approved(monkeypatch):
    for key, value in {
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "ALDI_SCRIPT_ACCESS_APPROVED": "true",
        "ALDI_PROVIDER_APPROVAL_REFERENCE": "offline-test-evidence",
        "ALDI_OWNER_MANUAL_APPROVED": "true",
        "ALDI_OWNER_AUTO_REFILL_APPROVED": "true",
        "ALDI_LIVE_REFILL_APPROVED": "true",
        "DRY_RUN": "false",
    }.items():
        monkeypatch.setenv(key, value)


@pytest.mark.parametrize("mode,event,missing,error", [
    ("observe", "workflow_dispatch", "ALDI_SCRIPT_ACCESS_APPROVED", "provider_authorization_required"),
    ("observe", "workflow_dispatch", "ALDI_PROVIDER_APPROVAL_REFERENCE", "provider_authorization_required"),
    ("observe", "workflow_dispatch", "ALDI_OWNER_MANUAL_APPROVED", "owner_approval_required"),
    ("refill", "workflow_dispatch", "ALDI_LIVE_REFILL_APPROVED", "live_refill_authorization_required"),
    ("refill", "workflow_dispatch", "DRY_RUN", "dry_run"),
    ("automatic", "schedule", "ALDI_OWNER_AUTO_REFILL_APPROVED", "owner_approval_required"),
    ("automatic", "schedule", "ALDI_LIVE_REFILL_APPROVED", "live_refill_authorization_required"),
    ("automatic", "schedule", "DRY_RUN", "dry_run"),
])
def test_missing_approval_aborts_before_provider_contact(
        approved, monkeypatch, mode, event, missing, error):
    monkeypatch.setenv("GITHUB_EVENT_NAME", event)
    monkeypatch.delenv(missing)
    with pytest.raises(HostedRuntimeError, match="^" + error + "$"):
        _authorization_context(mode)


def test_schedule_uses_persistent_owner_setting_without_manual_input(approved, monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    monkeypatch.setenv("ALDI_OWNER_MANUAL_APPROVED", "false")
    _authorization_context("automatic")


def test_manual_refill_needs_manual_approval_but_not_auto_setting(approved, monkeypatch):
    monkeypatch.setenv("ALDI_OWNER_AUTO_REFILL_APPROVED", "false")
    _authorization_context("refill")


def test_automatic_mode_cannot_be_invoked_from_manual_event(approved):
    with pytest.raises(HostedRuntimeError, match="owner_approval_required"):
        _authorization_context("automatic")


def test_only_explicit_false_dry_run_allows_booking(approved, monkeypatch):
    for value in ("", "FALSE", "False", "true", "0"):
        monkeypatch.setenv("DRY_RUN", value)
        with pytest.raises(HostedRuntimeError, match="dry_run"):
            _authorization_context("refill")
