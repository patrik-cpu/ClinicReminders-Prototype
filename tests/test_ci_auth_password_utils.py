import unittest

import auth_password_utils


class AuthPasswordUtilsTests(unittest.TestCase):
    def test_password_hash_is_pbkdf2_only_and_verifies(self):
        stored_hash = auth_password_utils.password_hash_for_storage("secret-password")

        self.assertTrue(stored_hash.startswith(f"{auth_password_utils.PASSWORD_HASH_ALGORITHM}$"))
        self.assertTrue(auth_password_utils.verify_password("secret-password", stored_hash))
        self.assertFalse(auth_password_utils.verify_password("wrong-password", stored_hash))
        self.assertFalse(auth_password_utils.verify_password("secret-password", "5ebe2294ecd0e0f08eab7690d2a6ee69"))

    def test_password_policy_rejects_common_and_clinic_derived_passwords(self):
        self.assertEqual(
            auth_password_utils.password_policy_error("short", "Clinic New"),
            "Password must be at least 12 characters.",
        )
        self.assertEqual(
            auth_password_utils.password_policy_error("password123456", "Clinic New"),
            "Choose a less common password.",
        )
        self.assertEqual(
            auth_password_utils.password_policy_error("Clinic New 2026!", "Clinic New"),
            "Password cannot include the clinic name.",
        )


if __name__ == "__main__":
    unittest.main()
