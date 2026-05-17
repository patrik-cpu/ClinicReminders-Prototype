import unittest

from scripts import auth_legacy_audit


class AuthLegacyAuditTests(unittest.TestCase):
    def test_classifies_supported_password_hash_shapes(self):
        cases = [
            ("", "blank"),
            ("   ", "blank"),
            ("pbkdf2_sha256$260000$salt$digest", "pbkdf2"),
            ("5ebe2294ecd0e0f08eab7690d2a6ee69", "legacy_md5"),
            ("not-a-known-format", "unknown"),
        ]

        for stored_hash, expected in cases:
            with self.subTest(stored_hash=stored_hash):
                self.assertEqual(auth_legacy_audit.classify_password_hash(stored_hash), expected)

    def test_audits_legacy_hashes_and_plain_password_cells_without_exposing_values(self):
        audit = auth_legacy_audit.audit_settings_records(
            [
                {"ClinicID": "safe", "PasswordHash": "pbkdf2_sha256$260000$salt$digest", "PlainPassword": ""},
                {"ClinicID": "legacy", "PasswordHash": "5ebe2294ecd0e0f08eab7690d2a6ee69", "PlainPassword": ""},
                {"ClinicID": "plain", "PasswordHash": "", "PlainPassword": "secret-password"},
                {"ClinicID": "unknown", "PasswordHash": "opaque", "PlainPassword": ""},
            ]
        )

        self.assertTrue(audit.has_risk)
        self.assertEqual(audit.total_rows, 4)
        self.assertEqual(audit.pbkdf2_password_hashes, 1)
        self.assertEqual(audit.legacy_md5_password_hashes, 1)
        self.assertEqual(audit.blank_password_hashes, 1)
        self.assertEqual(audit.unknown_password_hashes, 1)
        self.assertEqual(audit.plain_password_nonblank, 1)
        self.assertEqual(audit.risky_clinic_ids, {"legacy", "plain", "unknown"})

    def test_blank_password_hash_without_plain_password_is_not_a_risk(self):
        audit = auth_legacy_audit.audit_settings_records(
            [{"ClinicID": "oauth-only", "PasswordHash": "", "PlainPassword": ""}]
        )

        self.assertFalse(audit.has_risk)
        self.assertEqual(audit.blank_password_hashes, 1)


if __name__ == "__main__":
    unittest.main()
