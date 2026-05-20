import base64
import contextlib
import importlib
import io
import inspect
import json
from pathlib import Path
import time
import unittest
from datetime import date, datetime
from urllib.parse import quote
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

    def test_datepicker_today_ring_css_targets_current_date(self):
        css = self.app.datepicker_today_ring_css(date(2026, 5, 20))

        self.assertIn("May 20", css)
        self.assertIn("2026", css)
        self.assertIn("#dc2626", css)
        self.assertIn('[data-baseweb="calendar"]', css)

    def test_action_tracker_read_converts_utc_timestamp_to_browser_timezone(self):
        row = dict(zip(self.app.ACTION_TRACKER_HEADERS, [
            "2026-05-17 00:30:00",
            "2026-05-17T00:30:00",
            "Clinic A",
            "Nurse A",
            self.app.REMINDER_ACTION_SENT,
            "Client A",
            "Pet A",
            "Rabies",
            "17 May 2026",
            "17 May 2026",
            "17 May 2025",
            "1",
            "365",
            "",
            "test",
            "[]",
            "",
        ]))

        with patch.object(self.app, "user_timezone_name", return_value="America/Los_Angeles"):
            record = self.app.action_tracker_values_to_record(self.app.ACTION_TRACKER_HEADERS, list(row.values()))

        self.assertEqual(record["ActionedAt"], "2026-05-16T17:30:00")
        self.assertEqual(record["ActionedAtUTC"], "2026-05-17T00:30:00")
        self.assertEqual(self.app.statistics_actioned_date(record), date(2026, 5, 16))

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
        self.assertEqual(
            self.app.st.session_state[self.app.REMEMBER_LOGIN_COOKIE_UPDATE_KEY],
            "unsafe-token",
        )
        self.app.st.session_state.pop(self.app.REMEMBER_LOGIN_COOKIE_UPDATE_KEY, None)

    def test_clear_remember_login_token_queues_cookie_deletion(self):
        with patch.object(self.app, "clear_query_param") as clear_query_param:
            self.app.clear_remember_login_token()

        clear_query_param.assert_called_once_with(self.app.REMEMBER_LOGIN_QUERY_PARAM)
        self.assertEqual(
            self.app.st.session_state[self.app.REMEMBER_LOGIN_COOKIE_UPDATE_KEY],
            "",
        )
        self.app.st.session_state.pop(self.app.REMEMBER_LOGIN_COOKIE_UPDATE_KEY, None)

    def test_restore_remembered_login_validates_cookie_before_session_restore(self):
        self.app.st.session_state["logged_in"] = False
        token = "signed-cookie-token"

        with (
            patch.object(self.app, "get_remember_login_cookie", return_value=token),
            patch.object(self.app, "validate_remember_login_token", return_value="Clinic Login") as validate_token,
            patch.object(self.app, "finish_authenticated_session") as finish_session,
            patch.object(self.app, "remember_authenticated_session") as remember_session,
        ):
            restored = self.app.restore_remembered_login_session()

        self.assertTrue(restored)
        validate_token.assert_called_once_with(token)
        finish_session.assert_called_once_with(
            "Clinic Login",
            event="remembered_login",
            auth_provider="password",
        )
        remember_session.assert_called_once_with("Clinic Login")

    def test_remember_login_cookie_value_decodes_url_encoded_value(self):
        token = "signed-cookie-token=="
        self.assertEqual(
            self.app.normalize_remember_login_cookie_value(quote(token)),
            token,
        )

    def test_remember_login_cookie_falls_back_to_raw_cookie_header(self):
        token = "signed-cookie-token=="
        fake_context = type(
            "FakeContext",
            (),
            {
                "cookies": {},
                "headers": {
                    "Cookie": f"other=value; {self.app.REMEMBER_LOGIN_COOKIE_NAME}={quote(token)}"
                },
            },
        )()

        with patch.object(self.app.st, "context", fake_context):
            self.assertEqual(self.app.get_remember_login_cookie(), token)

    def test_remember_login_cookie_writer_targets_top_parent_and_current_window(self):
        self.app.st.session_state[self.app.REMEMBER_LOGIN_COOKIE_UPDATE_KEY] = "signed-cookie-token"

        with patch.object(self.app.components, "html") as html:
            self.app.render_pending_remember_login_cookie_update()

        script = html.call_args.args[0]
        self.assertIn("window.top", script)
        self.assertIn("window.parent", script)
        self.assertIn("Max-Age=", script)
        self.assertIn("Expires=", script)

    def test_restore_remembered_login_clears_invalid_cookie(self):
        self.app.st.session_state["logged_in"] = False
        with (
            patch.object(self.app, "get_remember_login_cookie", return_value="bad-token"),
            patch.object(self.app, "validate_remember_login_token", return_value=None),
            patch.object(self.app, "clear_remember_login_token") as clear_token,
        ):
            restored = self.app.restore_remembered_login_session()

        self.assertFalse(restored)
        clear_token.assert_called_once()

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
        self.app.st.session_state["logged_in"] = True
        self.app.st.session_state["clinic_id"] = "Clinic New"
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

    def test_update_clinic_password_blocks_cross_tenant_write_before_fetching_row(self):
        self.app.st.session_state["logged_in"] = True
        self.app.st.session_state["clinic_id"] = "Clinic A"

        with patch.object(self.app, "_get_settings_row_for_clinic") as get_row:
            with self.assertRaises(self.app.TenantAuthorizationError):
                self.app.update_clinic_password(
                    "Clinic B",
                    "better-random-passphrase-2026",
                )

        get_row.assert_not_called()

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
        self.assertIn("clinic_access_login", self.app.LOGIN_TRACKER_EVENTS)
        self.assertIn("remembered_login", self.app.LOGIN_TRACKER_EVENTS)

    def test_clinic_access_code_is_normalized_and_hashed(self):
        stored_hash = self.app.clinic_access_code_hash_for_storage("ab12-cd34 ef56")

        self.assertTrue(stored_hash.startswith(f"{self.app.PASSWORD_HASH_ALGORITHM}$"))
        self.assertNotIn("AB12CD34EF56", stored_hash)
        self.assertTrue(self.app.verify_clinic_access_code("AB12 CD34-EF56", stored_hash))
        self.assertFalse(self.app.verify_clinic_access_code("AB12 CD34 WRONG", stored_hash))
        self.assertEqual(self.app.format_clinic_access_code("ab12cd34ef56"), "AB12CD34EF56")

    def test_generated_clinic_access_code_is_six_digit_number(self):
        access_code = self.app.generate_clinic_access_code()

        self.assertRegex(access_code, r"^\d{6}$")

    def test_clinic_access_share_text_contains_required_login_details(self):
        share_text = self.app.clinic_access_share_text(
            "Clinic A",
            "https://clinic-reminders.streamlit.app/",
            "123456",
        )

        self.assertIn("Clinic name: Clinic A", share_text)
        self.assertIn("Login URL: https://clinic-reminders.streamlit.app", share_text)
        self.assertIn("Access code: 123456", share_text)
        self.assertIn("choose Staff Access", share_text)

    def test_clinic_access_app_url_is_public_login_url(self):
        self.assertEqual(self.app.clinic_access_app_url(), "https://clinic-reminders.streamlit.app")

    def test_authenticate_clinic_access_uses_settings_hash(self):
        stored_hash = self.app.clinic_access_code_hash_for_storage("123456")
        headers = [self.app.SHEET_COL_CLINIC_ID, self.app.SHEET_COL_SETTINGS_JSON]
        values_row = [
            "Clinic A",
            json.dumps({"clinic_access_code_hash": stored_hash}),
        ]

        class FakeSheet:
            def __init__(self):
                self.get_all_values_calls = 0
                self.get_all_records_calls = 0

            def get_all_values(self):
                self.get_all_values_calls += 1
                return [headers, values_row]

            def get_all_records(self):
                self.get_all_records_calls += 1
                return []

        sheet = FakeSheet()
        with patch.object(self.app, "get_settings_sheet", return_value=sheet):
            authenticated = self.app.authenticate_clinic_access("clinic a", "123 456")
            _sheet, cached_headers, row_idx = self.app._get_settings_row_for_clinic("Clinic A")
            self.app.st.session_state.pop("_settings_row_cache", None)
            rejected = self.app.authenticate_clinic_access("clinic a", "wrong-code")

        self.assertEqual(
            authenticated,
            {
                self.app.SHEET_COL_CLINIC_ID: "Clinic A",
                self.app.SHEET_COL_SETTINGS_JSON: json.dumps({"clinic_access_code_hash": stored_hash}),
            },
        )
        self.assertEqual(cached_headers, headers)
        self.assertEqual(row_idx, 2)
        self.assertIsNone(rejected)
        self.assertNotIn("_settings_row_cache", self.app.st.session_state)
        self.assertEqual(sheet.get_all_values_calls, 2)
        self.assertEqual(sheet.get_all_records_calls, 0)

    def test_clinic_access_code_can_be_reused_by_staff_without_rotation(self):
        stored_hash = self.app.clinic_access_code_hash_for_storage("123456")
        headers = [self.app.SHEET_COL_CLINIC_ID, self.app.SHEET_COL_SETTINGS_JSON]
        values_row = [
            "Clinic A",
            json.dumps({"clinic_access_code_hash": stored_hash}),
        ]

        class FakeSheet:
            def get_all_values(self):
                return [headers, values_row]

            def get_all_records(self):
                return []

        with (
            patch.object(self.app, "get_settings_sheet", return_value=FakeSheet()),
            patch.object(self.app, "update_clinic_access_code_hash") as update_code,
        ):
            first_login = self.app.authenticate_clinic_access("Clinic A", "123456")
            self.app.st.session_state.pop("_settings_row_cache", None)
            second_login = self.app.authenticate_clinic_access("Clinic A", "123456")

        self.assertIsNotNone(first_login)
        self.assertEqual(first_login, second_login)
        update_code.assert_not_called()

    def test_clinic_access_dialog_updates_code_only_from_admin_button(self):
        source = inspect.getsource(self.app.render_clinic_access_dialog)
        update_call = "update_clinic_access_code_hash(clinic_id, clinic_access_code_hash_for_storage(access_code))"
        button_block_start = source.index('if st.button(primary_label, key="clinic_access_generate_button"')
        update_index = source.index(update_call)

        self.assertGreater(update_index, button_block_start)
        self.assertIn('primary_label = "Rotate access code" if access_hash else "Generate access code"', source)
        self.assertNotIn("generate_clinic_access_code()", source[:button_block_start])

    def test_finish_staff_access_session_sets_display_name_without_google_identity(self):
        state = self.app.st.session_state

        with (
            patch.object(self.app, "close_account_dialogs"),
            patch.object(self.app, "reset_uploaded_data_state"),
            patch.object(self.app, "load_settings") as load_settings,
            patch.object(self.app, "load_shared_dataset_for_clinic"),
            patch.object(self.app, "record_settings_account_event"),
            patch.object(self.app, "upsert_user_tracker"),
        ):
            def load_settings_side_effect(*_args, **_kwargs):
                state["user_name"] = "Saved Clinic Name"

            load_settings.side_effect = load_settings_side_effect
            self.app.finish_authenticated_session(
                "Clinic A",
                event="clinic_access_login",
                auth_provider=self.app.CLINIC_ACCESS_AUTH_PROVIDER,
                session_user_name="Nurse A",
            )

        self.assertTrue(state["logged_in"])
        self.assertEqual(state["clinic_id"], "Clinic A")
        self.assertEqual(state["auth_provider"], self.app.CLINIC_ACCESS_AUTH_PROVIDER)
        self.assertEqual(state["user_name"], "Nurse A")
        self.assertNotIn("google_email", state)
        load_settings.assert_called_once_with(load_action_history=False)

    def test_finish_authenticated_session_can_refresh_password_remember_cookie(self):
        state = self.app.st.session_state
        state.pop(self.app.REMEMBER_LOGIN_COOKIE_UPDATE_KEY, None)

        with (
            patch.object(self.app, "close_account_dialogs"),
            patch.object(self.app, "reset_uploaded_data_state"),
            patch.object(self.app, "load_settings"),
            patch.object(self.app, "load_shared_dataset_for_clinic"),
            patch.object(self.app, "record_settings_account_event"),
            patch.object(self.app, "upsert_user_tracker"),
            patch.object(self.app, "create_remember_login_token", return_value="fresh-token") as create_token,
            patch.object(self.app, "clear_query_param"),
        ):
            self.app.finish_authenticated_session(
                "Clinic A",
                event="login",
                auth_provider="password",
                remember_session=True,
                user_row={self.app.SHEET_COL_PASSWORD_HASH: "hash"},
            )

        create_token.assert_called_once_with(
            "Clinic A",
            user_row={self.app.SHEET_COL_PASSWORD_HASH: "hash"},
        )
        self.assertEqual(state[self.app.REMEMBER_LOGIN_COOKIE_UPDATE_KEY], "fresh-token")
        state.pop(self.app.REMEMBER_LOGIN_COOKIE_UPDATE_KEY, None)

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
                {"GoogleSubject": "other", "GoogleEmail": "owner@example.com"},
                google_user,
            )
        )

    def test_google_clinic_lookup_seeds_settings_row_cache(self):
        self.app.st.session_state.pop("_settings_row_cache", None)
        headers = [
            self.app.SHEET_COL_CLINIC_ID,
            self.app.SHEET_COL_GOOGLE_EMAIL,
            self.app.SHEET_COL_GOOGLE_SUBJECT,
            self.app.SHEET_COL_SETTINGS_JSON,
        ]

        class FakeSheet:
            def __init__(self):
                self.get_all_values_calls = 0
                self.get_all_records_calls = 0

            def get_all_values(self):
                self.get_all_values_calls += 1
                return [
                    headers,
                    ["Other Clinic", "other@example.com", "other-subject", "{}"],
                    ["Clinic Google", "owner@example.com", "google-subject", '{"rules": {}}'],
                ]

            def get_all_records(self):
                self.get_all_records_calls += 1
                return []

        sheet = FakeSheet()
        google_user = {
            "is_logged_in": True,
            "email": "owner@example.com",
            "subject": "google-subject",
        }

        with patch.object(self.app, "get_settings_sheet", return_value=sheet):
            row = self.app.get_clinic_row_by_google_identity(google_user)
            _sheet, cached_headers, row_idx = self.app._get_settings_row_for_clinic("Clinic Google")

        self.assertEqual(row[self.app.SHEET_COL_CLINIC_ID], "Clinic Google")
        self.assertEqual(cached_headers, headers)
        self.assertEqual(row_idx, 3)
        self.assertEqual(sheet.get_all_values_calls, 1)
        self.assertEqual(sheet.get_all_records_calls, 0)

    def test_google_clinic_lookup_miss_does_not_seed_settings_row_cache(self):
        self.app.st.session_state.pop("_settings_row_cache", None)
        headers = [
            self.app.SHEET_COL_CLINIC_ID,
            self.app.SHEET_COL_GOOGLE_EMAIL,
            self.app.SHEET_COL_GOOGLE_SUBJECT,
        ]

        class FakeSheet:
            def __init__(self):
                self.get_all_values_calls = 0
                self.get_all_records_calls = 0

            def get_all_values(self):
                self.get_all_values_calls += 1
                return [headers, ["Other Clinic", "other@example.com", "other-subject"]]

            def get_all_records(self):
                self.get_all_records_calls += 1
                return []

        sheet = FakeSheet()
        google_user = {
            "is_logged_in": True,
            "email": "owner@example.com",
            "subject": "google-subject",
        }

        with patch.object(self.app, "get_settings_sheet", return_value=sheet):
            self.assertIsNone(self.app.get_clinic_row_by_google_identity(google_user))

        self.assertNotIn("_settings_row_cache", self.app.st.session_state)
        self.assertEqual(sheet.get_all_values_calls, 1)
        self.assertEqual(sheet.get_all_records_calls, 0)

    def test_google_profile_copy_makes_email_read_only(self):
        html = self.app.profile_dialog_html(
            {
                "auth_provider": self.app.GOOGLE_AUTH_PROVIDER,
                "email": "owner@example.com",
            }
        )

        self.assertIn("Google sign-in email is read-only here", html)
        self.assertIn("managed by Google", html)
        self.assertIn("cannot be changed", html)

    def test_profile_dialog_clears_state_when_dismissed(self):
        source = Path("reminders_app_v3.py").read_text()

        self.assertIn('@st.dialog("Profile", on_dismiss=close_profile_dialog)', source)

    def test_clinic_row_lookup_handles_non_string_sheet_values(self):
        class FakeSheet:
            def get_all_values(self):
                return [
                    [self_app.SHEET_COL_CLINIC_ID, self_app.SHEET_COL_PASSWORD_HASH],
                    [12345, ""],
                    ["Clinic A", self_hash],
                ]

            def get_all_records(self):
                return [
                    {"ClinicID": 12345, "PasswordHash": ""},
                    {"ClinicID": "Clinic A", "PasswordHash": self_hash},
                ]

        self_hash = self.app.password_hash_for_storage("secret-password")
        self_app = self.app
        with patch.object(self.app, "get_settings_sheet", return_value=FakeSheet()):
            row = self.app.get_clinic_row(" clinic a ")
            authenticated = self.app.authenticate_user("CLINIC A", "secret-password")

        self.assertEqual(row["ClinicID"], "Clinic A")
        self.assertEqual(authenticated["ClinicID"], "Clinic A")

    def test_successful_authentication_seeds_settings_row_cache(self):
        headers = [
            self.app.SHEET_COL_CLINIC_ID,
            self.app.SHEET_COL_PASSWORD_HASH,
            self.app.SHEET_COL_SETTINGS_JSON,
        ]
        password_hash = self.app.password_hash_for_storage("secret-password")

        class FakeSheet:
            def __init__(self):
                self.get_all_values_calls = 0
                self.get_all_records_calls = 0

            def get_all_values(self):
                self.get_all_values_calls += 1
                return [
                    headers,
                    ["Other Clinic", "", "{}"],
                    ["Clinic A", password_hash, '{"rules": {}}'],
                ]

            def get_all_records(self):
                self.get_all_records_calls += 1
                return []

        sheet = FakeSheet()
        with patch.object(self.app, "get_settings_sheet", return_value=sheet):
            authenticated = self.app.authenticate_user("clinic a", "secret-password")
            _sheet, cached_headers, row_idx = self.app._get_settings_row_for_clinic("Clinic A")

        self.assertEqual(authenticated["ClinicID"], "Clinic A")
        self.assertEqual(cached_headers, headers)
        self.assertEqual(row_idx, 3)
        self.assertEqual(sheet.get_all_values_calls, 1)
        self.assertEqual(sheet.get_all_records_calls, 0)

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
        self.assertEqual(self.app.suffixed_name("Clinic settings", "-live"), "Clinic settings-live")
        self.assertEqual(self.app.suffixed_name("Clinic settings", ""), "Clinic settings")
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

    def test_suffixed_settings_tab_starts_blank_instead_of_copying_dev_sheet(self):
        class FakeWorksheet:
            def __init__(self, title, values=None):
                self.title = title
                self.values = values or []
                self.updated = []

            def get_all_values(self):
                return [list(row) for row in self.values]

            def update(self, values=None, range_name=None, **_kwargs):
                self.updated.append({"values": values, "range_name": range_name})
                self.values = [list(row) for row in values]

            def resize(self, rows=None, cols=None):
                self.resized = {"rows": rows, "cols": cols}

            def row_values(self, index):
                return self.values[index - 1] if index - 1 < len(self.values) else []

            def batch_update(self, updates):
                self.batch_updates = updates

        class FakeSpreadsheet:
            def __init__(self):
                self.worksheets_by_title = {
                    "Clinic settings": FakeWorksheet(
                        "Clinic settings",
                        [["ClinicID", "SettingsJSON"], ["Dev Clinic", "{}"]],
                    ),
                    "Clinic settings-live": FakeWorksheet("Clinic settings-live", []),
                }
                self.sheet1 = self.worksheets_by_title["Clinic settings"]

            def worksheet(self, title):
                return self.worksheets_by_title[title]

            def add_worksheet(self, title, rows, cols):
                worksheet = FakeWorksheet(title, [])
                self.worksheets_by_title[title] = worksheet
                return worksheet

        spreadsheet = FakeSpreadsheet()
        live_sheet = spreadsheet.worksheets_by_title["Clinic settings-live"]

        with (
            patch.object(self.app, "WORKSHEET_NAME_SUFFIX", "-live"),
            patch.object(self.app, "SETTINGS_WORKSHEET_NAME", "Clinic settings-live"),
            patch.object(self.app, "clear_legacy_plain_password_column"),
        ):
            worksheet = self.app.get_or_create_settings_worksheet(spreadsheet)

        self.assertIs(worksheet, live_sheet)
        self.assertEqual(live_sheet.values, [self.app.SETTINGS_REQUIRED_COLUMNS])
        self.assertNotIn(["Dev Clinic", "{}"], live_sheet.values)

    def test_data_privacy_copy_is_clear_about_storage_and_use(self):
        content = self.app.data_privacy_policy_content()
        text = " ".join(
            [content["headline"], content["intro"], content["footer"]]
            + [section["title"] + " " + section["body"] for section in content["sections"]]
        )

        self.assertIn("managed Google Drive storage", text)
        self.assertIn("managed Google Sheets", text)
        self.assertIn("Clinic financial data is not sold", text)
        self.assertIn("Clinic financial data", text)
        self.assertIn("used to train AI models", text)
        self.assertIn("workflow is not lost", text)
        self.assertIn("unrelated product work", text)
        self.assertIn("Account > Delete account and data", text)
        self.assertIn("Clear Clinic Data", text)
        self.assertIn("keeping clinic settings and search terms", text)
        self.assertIn("export, recovery, retention, or permanent deletion", text)

    def test_upload_data_assurance_box_is_not_rendered_inline(self):
        self.assertEqual(self.app.data_assurance_box_html(), "")

        content = self.app.data_privacy_policy_content()
        text = " ".join(
            [content["headline"], content["intro"], content["footer"]]
            + [section["title"] + " " + section["body"] for section in content["sections"]]
        )
        self.assertIn("Clinic financial data is not sold", text)
        self.assertIn("Delete account and data", text)

    def test_upload_sales_data_help_copy_shows_minimum_required_shape(self):
        html = self.app.upload_sales_data_help_html()

        self.assertIn("What should uploaded sales data look like?", html)
        self.assertIn("One row per billed item", html)
        self.assertIn("single billed product or service", html)
        self.assertIn("Six useful fields", html)
        self.assertIn("Date billed", html)
        self.assertIn("Client name", html)
        self.assertIn("Animal name", html)
        self.assertIn("Billed product or service", html)
        self.assertIn("Qty", html)
        self.assertIn("Revenue", html)
        self.assertIn("Dental scale and polish", html)
        self.assertIn("Flea and worm treatment", html)
        self.assertIn("cr-upload-help-row + .cr-upload-help-row", html)
        self.assertIn("Extra columns are fine", html)

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

    def test_delete_rows_matching_clinic_id_batches_contiguous_ranges_when_supported(self):
        class FakeClient:
            def __init__(self):
                self.batch_calls = []

            def batch_update(self, spreadsheet_id, body):
                self.batch_calls.append((spreadsheet_id, body))

        class FakeWorksheet:
            id = 123
            spreadsheet_id = "spreadsheet-id"

            def __init__(self):
                self.client = FakeClient()
                self.deleted_rows = []

            def get_all_values(self):
                return [
                    ["ClinicID", "Event"],
                    ["Clinic A", "one"],
                    ["clinic a", "two"],
                    ["Clinic B", "three"],
                    ["Clinic A", "four"],
                    ["clinic a", "five"],
                ]

            def delete_rows(self, row_idx, end_idx=None):
                self.deleted_rows.append((row_idx, end_idx))

        worksheet = FakeWorksheet()
        with patch.object(self.app, "_gspread_retry", side_effect=lambda fn, *args, **kwargs: fn(*args, **kwargs)):
            deleted = self.app.delete_rows_matching_clinic_id(worksheet, {"Clinic A"})

        self.assertEqual(deleted, 4)
        self.assertEqual(worksheet.deleted_rows, [])
        self.assertEqual(len(worksheet.client.batch_calls), 1)
        spreadsheet_id, body = worksheet.client.batch_calls[0]
        self.assertEqual(spreadsheet_id, "spreadsheet-id")
        self.assertEqual(
            body,
            {
                "requests": [
                    {
                        "deleteDimension": {
                            "range": {
                                "sheetId": 123,
                                "dimension": "ROWS",
                                "startIndex": 4,
                                "endIndex": 6,
                            }
                        }
                    },
                    {
                        "deleteDimension": {
                            "range": {
                                "sheetId": 123,
                                "dimension": "ROWS",
                                "startIndex": 1,
                                "endIndex": 3,
                            }
                        }
                    },
                ]
            },
        )


if __name__ == "__main__":
    unittest.main()
