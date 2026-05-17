import base64
import contextlib
import importlib
import io
import json
from pathlib import Path
import time
import unittest
from datetime import date, datetime
from unittest.mock import patch


class AuthSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            cls.app = importlib.import_module("reminders_app_v3")

    def test_user_today_uses_browser_timezone_when_available(self):
        utc_midday = datetime(2026, 5, 16, 12, 0, 0)

        with patch.object(self.app, "user_timezone_name", return_value="Pacific/Auckland"):
            self.assertEqual(self.app.user_today(utc_midday), date(2026, 5, 17))

        with patch.object(self.app, "user_timezone_name", return_value="America/Los_Angeles"):
            self.assertEqual(self.app.user_today(utc_midday), date(2026, 5, 16))

    def test_user_timezone_falls_back_to_utc_for_unknown_browser_timezone(self):
        utc_midday = datetime(2026, 5, 16, 12, 0, 0)

        with patch.object(self.app, "user_timezone_name", return_value="Not/AZone"):
            self.assertEqual(self.app.user_now(utc_midday), utc_midday)

    def test_statistics_default_today_uses_user_timezone_helper(self):
        with patch.object(self.app, "user_today", return_value=date(2026, 5, 17)):
            self.assertEqual(self.app.statistics_period_start("Today"), date(2026, 5, 17))

    def test_remember_login_token_default_is_short_lived(self):
        self.assertLessEqual(self.app.REMEMBER_LOGIN_DAYS, 30)

        token = self.app.create_remember_login_token(
            "Clinic Login",
            {"PasswordHash": self.app.hash_pw("secret-password")},
        )

        payload = json.loads(base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8"))

        max_expected_expiry = int(time.time()) + 31 * 24 * 60 * 60
        self.assertLessEqual(payload["expires_at"], max_expected_expiry)

    def test_remember_login_token_is_not_written_to_query_params(self):
        with (
            patch.object(self.app, "set_query_param") as set_query_param,
            patch.object(self.app, "clear_query_param") as clear_query_param,
        ):
            self.app.set_remember_login_token("unsafe-token")

        set_query_param.assert_not_called()
        clear_query_param.assert_called_once_with(self.app.REMEMBER_LOGIN_QUERY_PARAM)

    def test_incoming_remember_login_query_param_is_discarded_without_validation(self):
        with (
            patch.object(self.app, "get_query_param", return_value="unsafe-token"),
            patch.object(self.app, "clear_remember_login_token") as clear_token,
            patch.object(self.app, "validate_remember_login_token") as validate_token,
        ):
            discarded = self.app.discard_remember_login_query_param()

        self.assertTrue(discarded)
        clear_token.assert_called_once()
        validate_token.assert_not_called()

    def test_dataset_upload_removal_query_param_is_cleared_without_mutation(self):
        with (
            patch.object(self.app, "get_query_param_value", return_value="0"),
            patch.object(self.app, "clear_query_param") as clear_query_param,
            patch.object(self.app, "remove_dataset_upload_at_index") as remove_upload,
            patch.object(self.app.st, "rerun") as rerun,
        ):
            self.app.consume_dataset_upload_removal()

        clear_query_param.assert_called_once_with("remove_dataset_upload")
        remove_upload.assert_not_called()
        rerun.assert_called_once()

    def test_invalid_dataset_upload_removal_query_param_is_ignored_without_mutation(self):
        with (
            patch.object(self.app, "get_query_param_value", return_value="not-an-index"),
            patch.object(self.app, "clear_query_param") as clear_query_param,
            patch.object(self.app, "remove_dataset_upload_at_index") as remove_upload,
            patch.object(self.app.st, "rerun") as rerun,
        ):
            self.app.consume_dataset_upload_removal()

        clear_query_param.assert_called_once_with("remove_dataset_upload")
        remove_upload.assert_not_called()
        rerun.assert_called_once()

    def test_password_storage_uses_salted_hash_and_keeps_legacy_md5_login(self):
        stored_hash = self.app.password_hash_for_storage("secret-password")

        self.assertTrue(stored_hash.startswith(f"{self.app.PASSWORD_HASH_ALGORITHM}$"))
        self.assertNotEqual(stored_hash, self.app.hash_pw("secret-password"))
        self.assertTrue(self.app.verify_password("secret-password", stored_hash))
        self.assertFalse(self.app.verify_password("wrong-password", stored_hash))
        self.assertTrue(self.app.verify_password("secret-password", self.app.hash_pw("secret-password")))

    def test_password_policy_rejects_short_common_and_clinic_derived_passwords(self):
        self.assertEqual(
            self.app.password_policy_error("short", "Clinic New"),
            "Password must be at least 12 characters.",
        )
        self.assertEqual(
            self.app.password_policy_error("password123456", "Clinic New"),
            "Choose a less common password.",
        )
        self.assertEqual(
            self.app.password_policy_error("Clinic New 2026!", "Clinic New"),
            "Password cannot include the clinic name.",
        )
        self.assertEqual(
            self.app.password_policy_error(
                "better-random-passphrase-2026",
                "Clinic New",
            ),
            "",
        )

    def test_create_clinic_account_rejects_weak_password_before_writing(self):
        with (
            patch.object(self.app, "get_clinic_row") as get_row,
            patch.object(self.app, "get_settings_sheet") as get_sheet,
        ):
            with self.assertRaisesRegex(ValueError, "less common"):
                self.app.create_clinic_account(
                    "Clinic New",
                    "United States",
                    "password123456",
                )

        get_row.assert_not_called()
        get_sheet.assert_not_called()

    def test_update_clinic_password_rejects_weak_password_before_writing(self):
        with patch.object(self.app, "_get_settings_row_for_clinic") as get_row:
            with self.assertRaisesRegex(ValueError, "clinic name"):
                self.app.update_clinic_password(
                    "Clinic New",
                    "Clinic New 2026!",
                )

        get_row.assert_not_called()

    def test_settings_schema_excludes_legacy_plain_password_column(self):
        self.assertNotIn(
            self.app.SHEET_COL_PLAIN_PASSWORD,
            self.app.SETTINGS_REQUIRED_COLUMNS,
        )

    def test_update_clinic_password_clears_legacy_plaintext_cell(self):
        headers = [
            self.app.SHEET_COL_CLINIC_ID,
            self.app.SHEET_COL_PLAIN_PASSWORD,
            self.app.SHEET_COL_PASSWORD_HASH,
            self.app.SHEET_COL_UPDATED_AT,
        ]

        class FakeSheet:
            def __init__(self):
                self.updates = None

            def batch_update(self, updates):
                self.updates = updates

        sheet = FakeSheet()
        with (
            patch.object(
                self.app,
                "_get_settings_row_for_clinic",
                return_value=(sheet, headers, 2),
            ),
            patch.object(self.app, "_gspread_retry", side_effect=lambda fn, *a, **kw: fn(*a, **kw)),
        ):
            password_hash = self.app.update_clinic_password(
                "Clinic New",
                "better-random-passphrase-2026",
            )

        updates_by_range = {
            update["range"]: update["values"][0][0]
            for update in sheet.updates
        }
        self.assertEqual(updates_by_range["B2:B2"], "")
        self.assertEqual(updates_by_range["C2:C2"], password_hash)
        self.assertNotEqual(updates_by_range["C2:C2"], "better-random-passphrase-2026")

    def test_legacy_plain_password_migration_clears_nonblank_values(self):
        headers = [
            self.app.SHEET_COL_CLINIC_ID,
            self.app.SHEET_COL_PLAIN_PASSWORD,
            self.app.SHEET_COL_PASSWORD_HASH,
        ]

        class FakeSheet:
            def __init__(self):
                self.updates = None

            def get_all_values(self):
                return [
                    headers,
                    ["Clinic A", "plaintext-one", "hash-a"],
                    ["Clinic B", "", "hash-b"],
                    ["Clinic C", " plaintext-two ", "hash-c"],
                ]

            def batch_update(self, updates):
                self.updates = updates

        sheet = FakeSheet()
        with patch.object(self.app, "_gspread_retry", side_effect=lambda fn, *a, **kw: fn(*a, **kw)):
            cleared = self.app.clear_legacy_plain_password_column(sheet, headers)

        self.assertEqual(cleared, 2)
        self.assertEqual(
            sheet.updates,
            [
                {"range": "B2:B2", "values": [[""]]},
                {"range": "B4:B4", "values": [[""]]},
            ],
        )

    def test_remember_login_signature_depends_on_password_hash_secret(self):
        clinic_id = "Clinic Login"
        expires_at = int(time.time()) + 3600
        first_hash = self.app.password_hash_for_storage("secret-password")
        second_hash = self.app.password_hash_for_storage("secret-password")

        first_signature = self.app._remember_login_signature(clinic_id, expires_at, first_hash)
        second_signature = self.app._remember_login_signature(clinic_id, expires_at, second_hash)

        self.assertNotEqual(first_hash, second_hash)
        self.assertNotEqual(first_signature, second_signature)

    def test_login_tracker_events_include_google_and_remembered_login(self):
        self.assertIn("login", self.app.LOGIN_TRACKER_EVENTS)
        self.assertIn("google_login", self.app.LOGIN_TRACKER_EVENTS)
        self.assertIn("remembered_login", self.app.LOGIN_TRACKER_EVENTS)

    def test_failed_login_attempts_lock_username_temporarily(self):
        state = {}
        username = "Clinic Login"
        now = 1_000.0

        for offset in range(self.app.LOGIN_FAILURE_LIMIT):
            allowed, retry_after = self.app.login_attempt_allowed(
                username,
                now=now + offset,
                state=state,
            )
            self.assertTrue(allowed)
            self.assertEqual(retry_after, 0)
            self.app.record_failed_login_attempt(
                username,
                now=now + offset,
                state=state,
            )

        allowed, retry_after = self.app.login_attempt_allowed(
            " clinic login ",
            now=now + self.app.LOGIN_FAILURE_LIMIT,
            state=state,
        )

        self.assertFalse(allowed)
        self.assertGreater(retry_after, 0)

    def test_successful_login_resets_failed_attempt_counter(self):
        state = {}
        username = "Clinic Login"

        for offset in range(self.app.LOGIN_FAILURE_LIMIT - 1):
            self.app.record_failed_login_attempt(
                username,
                now=2_000.0 + offset,
                state=state,
            )

        self.app.record_successful_login_attempt(" clinic login ", state=state)
        self.assertNotIn(
            self.app.normalize_clinic_id_key(username),
            state[self.app.AUTH_ABUSE_STATE_KEY]["login"],
        )
        allowed, retry_after = self.app.login_attempt_allowed(
            username,
            now=2_010.0,
            state=state,
        )

        self.assertTrue(allowed)
        self.assertEqual(retry_after, 0)

    def test_signup_attempts_are_rate_limited(self):
        state = {}
        now = 3_000.0

        for offset in range(self.app.SIGNUP_ATTEMPT_LIMIT):
            allowed, retry_after = self.app.signup_attempt_allowed(
                now=now + offset,
                state=state,
            )
            self.assertTrue(allowed)
            self.assertEqual(retry_after, 0)
            self.app.record_signup_attempt(now=now + offset, state=state)

        allowed, retry_after = self.app.signup_attempt_allowed(
            now=now + self.app.SIGNUP_ATTEMPT_LIMIT,
            state=state,
        )

        self.assertFalse(allowed)
        self.assertGreater(retry_after, 0)

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

    def test_google_user_info_requires_real_google_identity(self):
        class UserProxyLike:
            is_logged_in = object()

            def __iter__(self):
                return iter(())

        normalized = self.app.get_google_user_info(UserProxyLike())

        self.assertFalse(normalized["is_logged_in"])
        self.assertEqual(normalized["email"], "")
        self.assertEqual(normalized["subject"], "")

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

    def test_clinic_row_lookup_handles_non_string_sheet_values(self):
        class FakeSheet:
            def get_all_records(self):
                return [
                    {"ClinicID": 12345, "PasswordHash": ""},
                    {"ClinicID": "Clinic A", "PasswordHash": self_hash},
                ]

        self_hash = self.app.password_hash_for_storage("secret-password")
        with patch.object(self.app, "get_settings_sheet", return_value=FakeSheet()):
            row = self.app.get_clinic_row(" clinic a ")
            authenticated = self.app.authenticate_user("CLINIC A", "secret-password")

        self.assertEqual(row["ClinicID"], "Clinic A")
        self.assertEqual(authenticated["ClinicID"], "Clinic A")

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

    def test_settings_schema_has_named_tab_and_account_metadata(self):
        self.assertEqual(self.app.SETTINGS_WORKSHEET_NAME, "Clinic settings")
        for column in [
            "ClinicID",
            "SettingsJSON",
            "DatasetFileId",
            "AuthProvider",
            "GoogleEmail",
            "Country",
            "CreatedAtGST",
            "LastLoginAtGST",
            "LastLoginProvider",
            "AccountStatus",
        ]:
            self.assertIn(column, self.app.SETTINGS_REQUIRED_COLUMNS)

        self.assertTrue(
            self.app.worksheet_values_have_settings_schema([
                ["ClinicID", "SettingsJSON"],
                ["Clinic A", "{}"],
            ])
        )
        self.assertFalse(self.app.worksheet_values_have_settings_schema([["ClinicID", "Name"]]))

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

    def test_user_controlled_html_labels_escape_stored_xss_payloads(self):
        payload = '<img src=x onerror=alert(1)>'

        rule_html = self.app.padded_html_text(payload)
        patient_html = self.app.patient_exclusion_label_html(payload, payload)

        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", rule_html)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", patient_html)
        self.assertNotIn(payload, rule_html)
        self.assertNotIn(payload, patient_html)

    def test_authlib_requirement_is_patched_for_oidc_advisory(self):
        requirements = Path("requirements.txt").read_text(encoding="utf-8").splitlines()
        authlib_pins = [
            line.strip()
            for line in requirements
            if line.strip().lower().startswith("authlib==")
        ]

        self.assertEqual(authlib_pins, ["authlib==1.6.12"])
        version = tuple(int(part) for part in authlib_pins[0].split("==", 1)[1].split("."))
        self.assertGreaterEqual(version, (1, 6, 12))

    def test_delete_rows_matching_clinic_id_deletes_matching_rows_bottom_up(self):
        class FakeWorksheet:
            def __init__(self):
                self.deleted_rows = []

            def get_all_values(self):
                return [
                    ["ClinicID", "Event"],
                    ["Clinic A", "one"],
                    ["Clinic B", "two"],
                    ["clinic a", "three"],
                ]

            def delete_rows(self, row_idx):
                self.deleted_rows.append(row_idx)

        worksheet = FakeWorksheet()
        with patch.object(self.app, "_gspread_retry", side_effect=lambda fn, *args, **kwargs: fn(*args, **kwargs)):
            deleted = self.app.delete_rows_matching_clinic_id(worksheet, {"Clinic A"})

        self.assertEqual(deleted, 2)
        self.assertEqual(worksheet.deleted_rows, [4, 2])


if __name__ == "__main__":
    unittest.main()
