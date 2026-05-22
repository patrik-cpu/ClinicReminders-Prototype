import contextlib
import importlib
import io
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch


class FakeSettingsSheet:
    def __init__(self, headers, rows):
        self.headers = list(headers)
        self.rows = [list(row) for row in rows]
        self.batch_updates = []

    def get_all_values(self):
        return [self.headers] + [list(row) for row in self.rows]

    def batch_update(self, updates):
        self.batch_updates.append(updates)
        for update in updates:
            cell_range = update["range"].split(":", 1)[0]
            col_letters = "".join(ch for ch in cell_range if ch.isalpha())
            row_digits = "".join(ch for ch in cell_range if ch.isdigit())
            row_idx = int(row_digits) - 2
            col_idx = self._column_letters_to_index(col_letters) - 1
            while len(self.rows[row_idx]) < len(self.headers):
                self.rows[row_idx].append("")
            self.rows[row_idx][col_idx] = update["values"][0][0]

    @staticmethod
    def _column_letters_to_index(letters):
        value = 0
        for char in letters:
            value = value * 26 + (ord(char.upper()) - ord("A") + 1)
        return value


class EmailAuthFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            cls.app = importlib.import_module("reminders_app_v3")

    def setUp(self):
        state = self.app.st.session_state
        for key in list(state.keys()):
            del state[key]

    def retry_immediately(self, fn, *args, **kwargs):
        return fn(*args, **kwargs)

    def test_email_helpers_normalize_and_validate_basic_shape(self):
        self.assertEqual(self.app.normalize_email(" Owner@Example.COM "), "owner@example.com")
        self.assertTrue(self.app.is_valid_email("owner@example.com"))
        self.assertFalse(self.app.is_valid_email("not-an-email"))
        with self.assertRaisesRegex(ValueError, "valid email"):
            self.app.validate_required_email("not-an-email")

    def test_verification_token_is_hashed_and_marks_email_verified_once(self):
        now = datetime(2026, 5, 22, 12, 0, 0)
        token = "verification-token"
        headers = [
            self.app.SHEET_COL_CLINIC_ID,
            self.app.SHEET_COL_GOOGLE_EMAIL,
            self.app.SHEET_COL_EMAIL_VERIFIED,
            self.app.SHEET_COL_EMAIL_VERIFICATION_TOKEN_HASH,
            self.app.SHEET_COL_EMAIL_VERIFICATION_EXPIRES_AT,
            self.app.SHEET_COL_EMAIL_VERIFICATION_USED_AT,
            self.app.SHEET_COL_UPDATED_AT,
        ]
        sheet = FakeSettingsSheet(headers, [[
            "Clinic A",
            "owner@example.com",
            "false",
            self.app.token_hash_for_storage(token),
            (now + timedelta(minutes=30)).isoformat(),
            "",
            "",
        ]])

        with (
            patch.object(self.app, "get_settings_sheet", return_value=sheet),
            patch.object(self.app, "_gspread_retry", side_effect=self.retry_immediately),
        ):
            self.assertTrue(self.app.verify_email_token(token, now=now))
            self.assertFalse(self.app.verify_email_token(token, now=now))

        row = dict(zip(headers, sheet.rows[0]))
        self.assertEqual(row[self.app.SHEET_COL_EMAIL_VERIFIED], "true")
        self.assertEqual(row[self.app.SHEET_COL_EMAIL_VERIFICATION_TOKEN_HASH], "")
        self.assertNotEqual(row[self.app.SHEET_COL_EMAIL_VERIFICATION_TOKEN_HASH], token)

    def test_create_password_account_rejects_invalid_and_duplicate_email(self):
        headers = [
            self.app.SHEET_COL_CLINIC_ID,
            self.app.SHEET_COL_GOOGLE_EMAIL,
            self.app.SHEET_COL_PASSWORD_HASH,
            self.app.SHEET_COL_SETTINGS_JSON,
        ]
        sheet = FakeSettingsSheet(headers, [[
            "Existing Clinic",
            "owner@example.com",
            self.app.password_hash_for_storage("old-password-123"),
            "{}",
        ]])
        sheet.appended = False

        def append_row(_values, value_input_option=None):
            sheet.appended = True

        sheet.append_row = append_row

        with patch.object(self.app, "get_settings_sheet") as get_sheet:
            with self.assertRaisesRegex(ValueError, "valid email"):
                self.app.create_clinic_account("Clinic New", "United States", "new-password-123", "not-an-email")
        get_sheet.assert_not_called()

        with (
            patch.object(self.app, "get_settings_sheet", return_value=sheet),
            patch.object(self.app, "_gspread_retry", side_effect=self.retry_immediately),
        ):
            with self.assertRaisesRegex(ValueError, "email address is already registered"):
                self.app.create_clinic_account("Clinic New", "United States", "new-password-123", " Owner@Example.COM ")

        self.assertFalse(sheet.appended)

    def test_expired_and_invalid_verification_tokens_are_rejected(self):
        now = datetime(2026, 5, 22, 12, 0, 0)
        headers = [
            self.app.SHEET_COL_CLINIC_ID,
            self.app.SHEET_COL_GOOGLE_EMAIL,
            self.app.SHEET_COL_EMAIL_VERIFICATION_TOKEN_HASH,
            self.app.SHEET_COL_EMAIL_VERIFICATION_EXPIRES_AT,
            self.app.SHEET_COL_EMAIL_VERIFICATION_USED_AT,
        ]
        sheet = FakeSettingsSheet(headers, [[
            "Clinic A",
            "owner@example.com",
            self.app.token_hash_for_storage("expired-token"),
            (now - timedelta(minutes=1)).isoformat(),
            "",
        ]])

        with (
            patch.object(self.app, "get_settings_sheet", return_value=sheet),
            patch.object(self.app, "_gspread_retry", side_effect=self.retry_immediately),
        ):
            self.assertFalse(self.app.verify_email_token("expired-token", now=now))
            self.assertFalse(self.app.verify_email_token("missing-token", now=now))

    def test_password_reset_request_is_generic_and_only_sends_for_verified_email(self):
        headers = [
            self.app.SHEET_COL_CLINIC_ID,
            self.app.SHEET_COL_GOOGLE_EMAIL,
            self.app.SHEET_COL_EMAIL_VERIFIED,
            self.app.SHEET_COL_PASSWORD_HASH,
            self.app.SHEET_COL_PASSWORD_RESET_TOKEN_HASH,
            self.app.SHEET_COL_PASSWORD_RESET_EXPIRES_AT,
            self.app.SHEET_COL_PASSWORD_RESET_SENT_AT,
            self.app.SHEET_COL_PASSWORD_RESET_USED_AT,
            self.app.SHEET_COL_UPDATED_AT,
        ]
        sheet = FakeSettingsSheet(headers, [
            ["Clinic A", "owner@example.com", "true", self.app.password_hash_for_storage("old-password-123"), "", "", "", "", ""],
            ["Clinic B", "unverified@example.com", "false", self.app.password_hash_for_storage("old-password-123"), "", "", "", "", ""],
            ["Clinic C", "", "false", self.app.password_hash_for_storage("old-password-123"), "", "", "", "", ""],
        ])

        with (
            patch.object(self.app, "get_settings_sheet", return_value=sheet),
            patch.object(self.app, "_gspread_retry", side_effect=self.retry_immediately),
            patch.object(self.app, "generate_email_token", return_value="reset-token"),
            patch.object(self.app, "send_clinic_email", return_value=True) as send_email,
        ):
            existing = self.app.request_password_reset("owner@example.com")
            unknown = self.app.request_password_reset("unknown@example.com")
            unverified = self.app.request_password_reset("unverified@example.com")
            legacy = self.app.request_password_reset("")

        self.assertEqual(existing, self.app.FORGOT_PASSWORD_GENERIC_MESSAGE)
        self.assertEqual(unknown, self.app.FORGOT_PASSWORD_GENERIC_MESSAGE)
        self.assertEqual(unverified, self.app.FORGOT_PASSWORD_GENERIC_MESSAGE)
        self.assertEqual(legacy, self.app.FORGOT_PASSWORD_GENERIC_MESSAGE)
        send_email.assert_called_once()
        self.assertEqual(send_email.call_args.args[0], "owner@example.com")
        self.assertEqual(send_email.call_args.args[1], "Reset your Clinic Reminders password")
        row = dict(zip(headers, sheet.rows[0]))
        self.assertEqual(row[self.app.SHEET_COL_PASSWORD_RESET_TOKEN_HASH], self.app.token_hash_for_storage("reset-token"))
        self.assertNotEqual(row[self.app.SHEET_COL_PASSWORD_RESET_TOKEN_HASH], "reset-token")

    def test_valid_password_reset_updates_hash_and_rejects_reuse(self):
        now = datetime(2026, 5, 22, 12, 0, 0)
        old_hash = self.app.password_hash_for_storage("old-password-123")
        token = "reset-token"
        headers = [
            self.app.SHEET_COL_CLINIC_ID,
            self.app.SHEET_COL_PASSWORD_HASH,
            self.app.SHEET_COL_PASSWORD_RESET_TOKEN_HASH,
            self.app.SHEET_COL_PASSWORD_RESET_EXPIRES_AT,
            self.app.SHEET_COL_PASSWORD_RESET_USED_AT,
            self.app.SHEET_COL_UPDATED_AT,
        ]
        sheet = FakeSettingsSheet(headers, [[
            "Clinic A",
            old_hash,
            self.app.token_hash_for_storage(token),
            (now + timedelta(minutes=30)).isoformat(),
            "",
            "",
        ]])

        with (
            patch.object(self.app, "get_settings_sheet", return_value=sheet),
            patch.object(self.app, "_gspread_retry", side_effect=self.retry_immediately),
            patch.object(self.app, "clear_remember_login_token"),
        ):
            self.assertTrue(self.app.complete_password_reset(token, "new-password-123", "new-password-123", now=now))
            with self.assertRaisesRegex(ValueError, "invalid or expired"):
                self.app.complete_password_reset(token, "new-password-123", "new-password-123", now=now)

        row = dict(zip(headers, sheet.rows[0]))
        self.assertFalse(self.app.verify_password("old-password-123", row[self.app.SHEET_COL_PASSWORD_HASH]))
        self.assertTrue(self.app.verify_password("new-password-123", row[self.app.SHEET_COL_PASSWORD_HASH]))
        self.assertEqual(row[self.app.SHEET_COL_PASSWORD_RESET_TOKEN_HASH], "")

    def test_password_reset_rejects_expired_invalid_mismatch_and_weak_password(self):
        now = datetime(2026, 5, 22, 12, 0, 0)
        token = "reset-token"
        headers = [
            self.app.SHEET_COL_CLINIC_ID,
            self.app.SHEET_COL_PASSWORD_HASH,
            self.app.SHEET_COL_PASSWORD_RESET_TOKEN_HASH,
            self.app.SHEET_COL_PASSWORD_RESET_EXPIRES_AT,
            self.app.SHEET_COL_PASSWORD_RESET_USED_AT,
        ]
        sheet = FakeSettingsSheet(headers, [[
            "Clinic A",
            self.app.password_hash_for_storage("old-password-123"),
            self.app.token_hash_for_storage(token),
            (now - timedelta(minutes=1)).isoformat(),
            "",
        ]])

        with (
            patch.object(self.app, "get_settings_sheet", return_value=sheet),
            patch.object(self.app, "_gspread_retry", side_effect=self.retry_immediately),
        ):
            with self.assertRaisesRegex(ValueError, "Passwords do not match"):
                self.app.complete_password_reset(token, "new-password-123", "different-password-123", now=now)
            with self.assertRaisesRegex(ValueError, "invalid or expired"):
                self.app.complete_password_reset(token, "new-password-123", "new-password-123", now=now)
            with self.assertRaisesRegex(ValueError, "invalid or expired"):
                self.app.complete_password_reset("missing-token", "new-password-123", "new-password-123", now=now)

        sheet.rows[0][headers.index(self.app.SHEET_COL_PASSWORD_RESET_EXPIRES_AT)] = (now + timedelta(minutes=30)).isoformat()
        with (
            patch.object(self.app, "get_settings_sheet", return_value=sheet),
            patch.object(self.app, "_gspread_retry", side_effect=self.retry_immediately),
        ):
            with self.assertRaisesRegex(ValueError, "at least 12 characters"):
                self.app.complete_password_reset(token, "short", "short", now=now)

    def test_email_sender_uses_info_sender_and_local_outbox(self):
        with patch.object(self.app, "EMAIL_SEND_MODE", "local"), patch.object(self.app, "EMAIL_SENDER_FROM", "info@novavetfamily.com"):
            self.assertTrue(
                self.app.send_clinic_email(
                    "owner@example.com",
                    "Verify your Clinic Reminders account",
                    "Hello",
                )
            )

        outbox = self.app.st.session_state["_email_outbox"]
        self.assertEqual(outbox[0]["from"], "info@novavetfamily.com")
        self.assertEqual(outbox[0]["subject"], "Verify your Clinic Reminders account")


if __name__ == "__main__":
    unittest.main()
