import unittest
from core.credentials import validated


class GermanPlaceholderTests(unittest.TestCase):
    def test_german_password_placeholders_are_rejected(self):
        for name in ('ALDI_PASS', 'LIDL_PASS'):
            for value in ('your-aldi-passwort', 'your-lidl-passwort',
                          'your-passwort', 'your_aldi_passwort',
                          'your_lidl_passwort', 'YOUR-ALDI-PASSWORT'):
                with self.subTest(name=name, value=value):
                    with self.assertRaises(ValueError):
                        validated(name, value)

    def test_existing_english_placeholder_is_rejected(self):
        with self.assertRaises(ValueError):
            validated('ALDI_PASS', 'your-aldi-password')

    def test_real_password_is_unchanged(self):
        self.assertEqual(validated('ALDI_PASS', 'synthetic-valid-password'),
                         'synthetic-valid-password')

    def test_username_is_not_filtered_as_password(self):
        self.assertEqual(validated('ALDI_USER', 'your-aldi-passwort'),
                         'your-aldi-passwort')

    def test_empty_password_remains_none(self):
        self.assertIsNone(validated('ALDI_PASS', ''))
