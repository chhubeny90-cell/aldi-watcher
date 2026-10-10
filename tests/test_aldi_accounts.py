import unittest
from types import SimpleNamespace
from unittest.mock import patch
from core.aldi_accounts import normalise_number, validate_accounts, number_from_label, require_selected_account


def item(**changes):
    result = dict(account_id="account_a", account_user="+4915112345678",
                  provider="aldi_talk", enabled=False, policy="monitor_only")
    result.update(changes)
    return result


class AccountTests(unittest.TestCase):
    def test_number_formats(self):
        for value in ("+49 151 12345678", "004915112345678", "015112345678"):
            self.assertEqual(normalise_number(value), "+4915112345678")

    def test_invalid_numbers(self):
        for value in ("", "+4415112345678", "phone123", None, "+49"):
            with self.assertRaises(ValueError):
                normalise_number(value)

    def test_duplicate_number_is_blocked(self):
        with self.assertRaises(ValueError):
            validate_accounts({"version": 1, "accounts": [item(), item(account_id="account_b")]})

    def test_provider_must_be_declared_aldi(self):
        with self.assertRaises(ValueError):
            validate_accounts({"version": 1, "accounts": [item(provider="lidl_connect")]})

    def test_enabled_profile_requires_password(self):
        with self.assertRaises(ValueError):
            validate_accounts({"version": 1, "accounts": [item(enabled=True)]})

    def test_credentials_do_not_appear_in_repr(self):
        account = validate_accounts({"version": 1, "accounts": [item(password="test-secret")]})[0]
        self.assertNotIn("test-secret", repr(account))
        self.assertNotIn("12345678", repr(account))

    def test_profiles_are_sorted(self):
        accounts = validate_accounts({"version": 1, "accounts": [
            item(account_id="account_b", account_user="+4916112345678"), item()]})
        self.assertEqual([a.account_id for a in accounts], ["account_a", "account_b"])

    def test_free_policy_does_not_implicitly_enable_account(self):
        account = validate_accounts({"version": 1, "accounts": [item(policy="free_unlimited")]})[0]
        self.assertFalse(account.enabled)

    def test_actual_selected_number_must_match(self):
        button = SimpleNamespace(label="0151 12345678 Test SIM")
        dom = SimpleNamespace(find_visible_elements=lambda *_: [button],
                              element_label=lambda driver, control: control.label)
        watcher = SimpleNamespace(ALDI_OVERVIEW_URL="https://example.test")
        monitoring = SimpleNamespace(require_origin=lambda *_: None)
        with patch.dict("sys.modules", browser_dom=dom, watcher=watcher, monitoring=monitoring):
            require_selected_account(None, "+4915112345678")
            with self.assertRaises(PermissionError):
                require_selected_account(None, "+4916112345678")

    def test_ambiguous_selected_number_is_rejected(self):
        controls = [SimpleNamespace(label="0151 12345678 Test SIM"),
                    SimpleNamespace(label="0161 12345678 Other SIM")]
        dom = SimpleNamespace(find_visible_elements=lambda *_: controls,
                              element_label=lambda driver, control: control.label)
        watcher = SimpleNamespace(ALDI_OVERVIEW_URL="https://example.test")
        monitoring = SimpleNamespace(require_origin=lambda *_: None)
        with patch.dict("sys.modules", browser_dom=dom, watcher=watcher, monitoring=monitoring):
            with self.assertRaises(PermissionError):
                require_selected_account(None, "+4915112345678")

    def test_tariff_name_cannot_replace_account_number(self):
        self.assertIsNone(number_from_label("Tarif S Unlimited"))


if __name__ == "__main__":
    unittest.main()
