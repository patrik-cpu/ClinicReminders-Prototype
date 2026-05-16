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

    def test_google_user_info_normalizes_identity_fields(self):
        user = {
            "is_logged_in": True,
            "email": " User@Example.COM ",
            "sub": "google-subject",
            "name": "Clinic Owner",
        }

        normalized = self.app.get_google_user_info(user)

        self.assertTrue(normalized["is_logged_in"])
        self.assertEqual(normalized["email"], "user@example.com")
        self.assertEqual(normalized["subject"], "google-subject")
        self.assertEqual(normalized["name"], "Clinic Owner")

    def test_google_identity_matches_by_subject_or_email(self):
        google_user = {
            "is_logged_in": True,
            "email": "owner@example.com",
            "subject": "google-subject",
        }

        self.assertTrue(
            self.app.google_identity_matches_row(
                {"GoogleSubject": "google-subject", "GoogleEmail": ""},
                google_user,
            )
        )
        self.assertTrue(
            self.app.google_identity_matches_row(
                {"GoogleSubject": "", "GoogleEmail": "Owner@Example.com"},
                google_user,
            )
        )
        self.assertFalse(
            self.app.google_identity_matches_row(
                {"GoogleSubject": "other", "GoogleEmail": "other@example.com"},
                google_user,
            )
        )

    def test_settings_row_values_writes_google_columns_when_present(self):
        headers = [
            "ClinicID",
            "PasswordHash",
            "SettingsJSON",
            "GoogleEmail",
            "GoogleSubject",
        ]
        row = self.app.settings_row_values(
            headers,
            {
                "ClinicID": "Clinic A",
                "PasswordHash": "",
                "SettingsJSON": "{}",
                "GoogleEmail": "owner@example.com",
                "GoogleSubject": "google-subject",
            },
        )

        self.assertEqual(row, ["Clinic A", "", "{}", "owner@example.com", "google-subject"])

    def test_data_privacy_copy_is_clear_about_storage_and_use(self):
        content = self.app.data_privacy_policy_content()
        text = " ".join(
            [content["headline"], content["intro"], content["footer"]]
            + [section["title"] + " " + section["body"] for section in content["sections"]]
        )

        self.assertIn("managed Google Drive storage", text)
        self.assertIn("managed Google Sheets", text)
        self.assertIn("We do not sell clinic data", text)
        self.assertIn("clinic financial data", text)
        self.assertIn("permanent deletion requests", text)

    def test_data_privacy_dialog_html_escapes_policy_text(self):
        html = self.app.data_privacy_dialog_html(
            {
                "headline": "<Clinic>",
                "intro": "Safe & clear",
                "sections": [{"title": "Use", "body": "<script>alert(1)</script>"}],
                "footer": "Done",
            }
        )

        self.assertIn("&lt;Clinic&gt;", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertNotIn("<script>alert(1)</script>", html)


if __name__ == "__main__":
    unittest.main()
