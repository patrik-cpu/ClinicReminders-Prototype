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


if __name__ == "__main__":
    unittest.main()
