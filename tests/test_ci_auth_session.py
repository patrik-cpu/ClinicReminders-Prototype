import base64
import contextlib
import importlib
import io
import json
import time
import unittest


class AuthSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            cls.app = importlib.import_module("reminders_app_v3")

    def test_remember_login_token_default_is_long_lived(self):
        token = self.app.create_remember_login_token(
            "Clinic Login",
            {"PasswordHash": self.app.hash_pw("secret-password")},
        )

        payload = json.loads(base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8"))

        min_expected_expiry = int(time.time()) + (self.app.REMEMBER_LOGIN_DAYS - 1) * 24 * 60 * 60
        self.assertGreaterEqual(payload["expires_at"], min_expected_expiry)

    def test_password_storage_uses_salted_hash_and_keeps_legacy_md5_login(self):
        stored_hash = self.app.password_hash_for_storage("secret-password")

        self.assertTrue(stored_hash.startswith(f"{self.app.PASSWORD_HASH_ALGORITHM}$"))
        self.assertNotEqual(stored_hash, self.app.hash_pw("secret-password"))
        self.assertTrue(self.app.verify_password("secret-password", stored_hash))
        self.assertFalse(self.app.verify_password("wrong-password", stored_hash))
        self.assertTrue(self.app.verify_password("secret-password", self.app.hash_pw("secret-password")))

    def test_remember_login_signature_depends_on_password_hash_secret(self):
        clinic_id = "Clinic Login"
        expires_at = int(time.time()) + 3600
        first_hash = self.app.password_hash_for_storage("secret-password")
        second_hash = self.app.password_hash_for_storage("secret-password")

        first_signature = self.app._remember_login_signature(clinic_id, expires_at, first_hash)
        second_signature = self.app._remember_login_signature(clinic_id, expires_at, second_hash)

        self.assertNotEqual(first_hash, second_hash)
        self.assertNotEqual(first_signature, second_signature)


if __name__ == "__main__":
    unittest.main()
