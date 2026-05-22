import base64
import contextlib
import importlib
import io
import json
import time
import unittest
from unittest.mock import patch

import pandas as pd


class AuditCharacterizationTests(unittest.TestCase):
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

    def test_remember_login_token_rejects_malformed_expired_and_rotated_password_hash(self):
        clinic_id = "Clinic Login"
        old_hash = self.app.password_hash_for_storage("secret-password")
        token = self.app.create_remember_login_token(clinic_id, {"PasswordHash": old_hash})

        with patch.object(self.app, "get_clinic_row", return_value={"ClinicID": clinic_id, "PasswordHash": old_hash}):
            self.assertEqual(self.app.validate_remember_login_token(token), clinic_id)

        new_hash = self.app.password_hash_for_storage("secret-password")
        with patch.object(self.app, "get_clinic_row", return_value={"ClinicID": clinic_id, "PasswordHash": new_hash}):
            self.assertIsNone(self.app.validate_remember_login_token(token))

        expired_payload = {
            "clinic_id": clinic_id,
            "expires_at": int(time.time()) - 1,
            "signature": self.app._remember_login_signature(clinic_id, int(time.time()) - 1, old_hash),
        }
        expired_token = base64.urlsafe_b64encode(json.dumps(expired_payload).encode("utf-8")).decode("ascii")
        self.assertIsNone(self.app.validate_remember_login_token(expired_token))
        self.assertIsNone(self.app.validate_remember_login_token("not valid base64"))

    def test_authenticate_user_returns_none_for_wrong_password_or_missing_clinic(self):
        stored_hash = self.app.password_hash_for_storage("secret-password")
        headers = [self.app.SHEET_COL_CLINIC_ID, self.app.SHEET_COL_PASSWORD_HASH]

        class FakeSheet:
            def get_all_values(self):
                return [headers, ["Clinic A", stored_hash]]

            def get_all_records(self):
                raise AssertionError("authenticate_user should use one row-values snapshot")

        with patch.object(self.app, "get_settings_sheet", return_value=FakeSheet()):
            self.assertIsNone(self.app.authenticate_user("Clinic A", "wrong-password"))
            self.assertIsNone(self.app.authenticate_user("Missing Clinic", "secret-password"))

        self.assertNotIn("_settings_row_cache", self.app.st.session_state)

    def test_google_clinic_lookup_requires_logged_in_identity_before_reading_sheet(self):
        with patch.object(self.app, "get_settings_sheet") as get_sheet:
            self.assertIsNone(self.app.get_clinic_row_by_google_identity({"is_logged_in": False}))

        get_sheet.assert_not_called()

    def test_create_clinic_account_appends_hashed_password_and_default_settings(self):
        headers = list(self.app.SETTINGS_REQUIRED_COLUMNS)

        class FakeSheet:
            def __init__(self):
                self.appended = None
                self.get_all_values_calls = 0
                self.get_all_records_calls = 0

            def get_all_values(self):
                self.get_all_values_calls += 1
                return [headers]

            def get_all_records(self):
                self.get_all_records_calls += 1
                return []

            def append_row(self, values, value_input_option=None):
                self.appended = {
                    "values": values,
                    "value_input_option": value_input_option,
                }

        sheet = FakeSheet()
        with (
            patch.object(self.app, "get_settings_sheet", return_value=sheet),
            patch.object(self.app, "ensure_settings_sheet_columns", return_value=headers),
            patch.object(self.app, "_gspread_retry", side_effect=self.retry_immediately),
            patch.object(self.app, "upsert_user_tracker") as upsert_tracker,
            patch.object(self.app, "record_account_lifecycle_event") as lifecycle_event,
        ):
            password_hash = self.app.create_clinic_account("Clinic New", "United Arab Emirates", "secret-password")

        values = sheet.appended["values"]
        by_header = dict(zip(headers, values))
        self.assertEqual(sheet.appended["value_input_option"], "USER_ENTERED")
        self.assertEqual(by_header[self.app.SHEET_COL_CLINIC_ID], "Clinic New")
        self.assertNotIn(self.app.SHEET_COL_PLAIN_PASSWORD, headers)
        self.assertEqual(by_header[self.app.SHEET_COL_PASSWORD_HASH], password_hash)
        self.assertTrue(self.app.verify_password("secret-password", password_hash))
        self.assertEqual(json.loads(by_header[self.app.SHEET_COL_SETTINGS_JSON])["country"], "United Arab Emirates")
        self.assertEqual(by_header[self.app.SHEET_COL_ACCOUNT_STATUS], "active")
        self.assertEqual(sheet.get_all_values_calls, 1)
        self.assertEqual(sheet.get_all_records_calls, 0)
        upsert_tracker.assert_called_once_with("Clinic New", country="United Arab Emirates", event="created")
        lifecycle_event.assert_called_once_with(
            "Clinic New",
            "created",
            clinic_name="Clinic New",
            auth_provider="password",
            country="United Arab Emirates",
            source="password_signup",
        )

    def test_create_clinic_account_rejects_duplicate_before_writing(self):
        headers = list(self.app.SETTINGS_REQUIRED_COLUMNS)

        class FakeSheet:
            def __init__(self):
                self.appended = False
                self.get_all_values_calls = 0
                self.get_all_records_calls = 0

            def get_all_values(self):
                self.get_all_values_calls += 1
                return [headers, ["Clinic Existing"]]

            def get_all_records(self):
                self.get_all_records_calls += 1
                return [{"ClinicID": "Clinic Existing"}]

            def append_row(self, values, value_input_option=None):
                self.appended = True

        sheet = FakeSheet()
        with (
            patch.object(self.app, "get_settings_sheet", return_value=sheet),
            patch.object(self.app, "_gspread_retry", side_effect=self.retry_immediately),
            patch.object(self.app, "upsert_user_tracker") as upsert_tracker,
            patch.object(self.app, "record_account_lifecycle_event") as lifecycle_event,
        ):
            with self.assertRaisesRegex(ValueError, "already registered"):
                self.app.create_clinic_account("Clinic Existing", "United States", "secret-password")

        self.assertEqual(sheet.get_all_values_calls, 1)
        self.assertEqual(sheet.get_all_records_calls, 0)
        self.assertFalse(sheet.appended)
        upsert_tracker.assert_not_called()
        lifecycle_event.assert_not_called()

    def test_create_google_clinic_account_rejects_missing_email_before_writing(self):
        with patch.object(self.app, "get_settings_sheet") as get_sheet:
            with self.assertRaisesRegex(ValueError, "Google did not return an email"):
                self.app.create_google_clinic_account("Clinic Google", "United States", {"subject": "sub"})

        get_sheet.assert_not_called()

    def test_create_google_clinic_account_uses_one_sheet_snapshot_for_success(self):
        headers = list(self.app.SETTINGS_REQUIRED_COLUMNS)

        class FakeSheet:
            def __init__(self):
                self.appended = None
                self.get_all_values_calls = 0
                self.get_all_records_calls = 0

            def get_all_values(self):
                self.get_all_values_calls += 1
                return [headers]

            def get_all_records(self):
                self.get_all_records_calls += 1
                return []

            def append_row(self, values, value_input_option=None):
                self.appended = {
                    "values": values,
                    "value_input_option": value_input_option,
                }

        sheet = FakeSheet()
        google_user = {
            "email": "Owner@Example.com",
            "subject": "google-subject",
            "name": "Owner Name",
        }
        with (
            patch.object(self.app, "get_settings_sheet", return_value=sheet),
            patch.object(self.app, "ensure_settings_sheet_columns", return_value=headers),
            patch.object(self.app, "_gspread_retry", side_effect=self.retry_immediately),
            patch.object(self.app, "upsert_user_tracker") as upsert_tracker,
            patch.object(self.app, "record_account_lifecycle_event") as lifecycle_event,
        ):
            values_by_header = self.app.create_google_clinic_account(
                "Clinic Google",
                "United States",
                google_user,
            )

        appended = dict(zip(headers, sheet.appended["values"]))
        self.assertEqual(sheet.get_all_values_calls, 1)
        self.assertEqual(sheet.get_all_records_calls, 0)
        self.assertEqual(sheet.appended["value_input_option"], "USER_ENTERED")
        self.assertEqual(values_by_header[self.app.SHEET_COL_CLINIC_ID], "Clinic Google")
        self.assertEqual(appended[self.app.SHEET_COL_GOOGLE_EMAIL], "owner@example.com")
        self.assertEqual(appended[self.app.SHEET_COL_GOOGLE_SUBJECT], "google-subject")
        self.assertEqual(appended[self.app.SHEET_COL_AUTH_PROVIDER], self.app.GOOGLE_AUTH_PROVIDER)
        upsert_tracker.assert_called_once_with("Clinic Google", country="United States", event="google_created")
        lifecycle_event.assert_called_once_with(
            "Clinic Google",
            "created",
            clinic_name="Clinic Google",
            auth_provider=self.app.GOOGLE_AUTH_PROVIDER,
            country="United States",
            source="google_signup",
        )

    def test_create_google_clinic_account_rejects_duplicate_clinic_from_one_snapshot(self):
        headers = list(self.app.SETTINGS_REQUIRED_COLUMNS)
        app = self.app

        class FakeSheet:
            def __init__(self):
                self.appended = False
                self.get_all_values_calls = 0
                self.get_all_records_calls = 0

            def get_all_values(self):
                self.get_all_values_calls += 1
                row = app.settings_row_values(headers, {app.SHEET_COL_CLINIC_ID: "Clinic Google"})
                return [headers, row]

            def get_all_records(self):
                self.get_all_records_calls += 1
                return [{app.SHEET_COL_CLINIC_ID: "Clinic Google"}]

            def append_row(self, values, value_input_option=None):
                self.appended = True

        sheet = FakeSheet()
        with (
            patch.object(self.app, "get_settings_sheet", return_value=sheet),
            patch.object(self.app, "_gspread_retry", side_effect=self.retry_immediately),
            patch.object(self.app, "upsert_user_tracker") as upsert_tracker,
            patch.object(self.app, "record_account_lifecycle_event") as lifecycle_event,
        ):
            with self.assertRaisesRegex(ValueError, "already registered"):
                self.app.create_google_clinic_account(
                    "clinic google",
                    "United States",
                    {"email": "owner@example.com", "subject": "new-subject"},
                )

        self.assertEqual(sheet.get_all_values_calls, 1)
        self.assertEqual(sheet.get_all_records_calls, 0)
        self.assertFalse(sheet.appended)
        upsert_tracker.assert_not_called()
        lifecycle_event.assert_not_called()

    def test_create_google_clinic_account_rejects_duplicate_google_from_one_snapshot(self):
        headers = list(self.app.SETTINGS_REQUIRED_COLUMNS)
        app = self.app

        class FakeSheet:
            def __init__(self):
                self.appended = False
                self.get_all_values_calls = 0
                self.get_all_records_calls = 0

            def get_all_values(self):
                self.get_all_values_calls += 1
                row = app.settings_row_values(
                    headers,
                    {
                        app.SHEET_COL_CLINIC_ID: "Other Clinic",
                        app.SHEET_COL_GOOGLE_EMAIL: "owner@example.com",
                    },
                )
                return [headers, row]

            def get_all_records(self):
                self.get_all_records_calls += 1
                return [{app.SHEET_COL_GOOGLE_EMAIL: "owner@example.com"}]

            def append_row(self, values, value_input_option=None):
                self.appended = True

        sheet = FakeSheet()
        with (
            patch.object(self.app, "get_settings_sheet", return_value=sheet),
            patch.object(self.app, "_gspread_retry", side_effect=self.retry_immediately),
            patch.object(self.app, "upsert_user_tracker") as upsert_tracker,
            patch.object(self.app, "record_account_lifecycle_event") as lifecycle_event,
        ):
            with self.assertRaisesRegex(ValueError, "Google account is already linked"):
                self.app.create_google_clinic_account(
                    "Clinic New",
                    "United States",
                    {"email": "Owner@Example.com", "subject": "google-subject"},
                )

        self.assertEqual(sheet.get_all_values_calls, 1)
        self.assertEqual(sheet.get_all_records_calls, 0)
        self.assertFalse(sheet.appended)
        upsert_tracker.assert_not_called()
        lifecycle_event.assert_not_called()

    def test_update_rows_with_clinic_id_updates_only_matching_tenant_rows(self):
        class FakeWorksheet:
            def __init__(self, values):
                self.values = values
                self.batch_updates = []

            def get_all_values(self):
                return self.values

            def batch_update(self, updates):
                self.batch_updates.append(updates)

        matching = FakeWorksheet([
            ["ClinicID", "Event"],
            ["Clinic A", "one"],
            ["Clinic B", "two"],
            ["clinic a", "three"],
        ])
        skipped = FakeWorksheet([["Other", "Event"], ["Clinic A", "ignored"]])

        class FakeSpreadsheet:
            def worksheets(self):
                return [matching, skipped]

        self.app.st.session_state["_settings_row_cache"] = {"clinic_key": "clinic a"}
        with (
            patch.object(self.app, "get_settings_spreadsheet", return_value=FakeSpreadsheet()),
            patch.object(self.app, "_gspread_retry", side_effect=self.retry_immediately),
        ):
            updated = self.app.update_rows_with_clinic_id("Clinic A", "Clinic Renamed")

        self.assertEqual(updated, 2)
        self.assertEqual(
            matching.batch_updates,
            [[
                {"range": "A2:A2", "values": [["Clinic Renamed"]]},
                {"range": "A4:A4", "values": [["Clinic Renamed"]]},
            ]],
        )
        self.assertEqual(skipped.batch_updates, [])
        self.assertNotIn("_settings_row_cache", self.app.st.session_state)

    def test_dataset_pointer_read_requires_current_tenant_before_sheet_access(self):
        self.app.st.session_state["logged_in"] = True
        self.app.st.session_state["clinic_id"] = "Clinic A"

        with patch.object(self.app, "_get_settings_row_for_clinic") as get_row:
            with self.assertRaises(self.app.TenantAuthorizationError):
                self.app.get_existing_dataset_pointer("Clinic B")

        get_row.assert_not_called()

    def test_action_tracker_load_fails_closed_for_other_tenant_before_sheet_access(self):
        self.app.st.session_state["logged_in"] = True
        self.app.st.session_state["clinic_id"] = "Clinic A"

        with patch.object(self.app, "get_or_create_tracker_sheet") as get_sheet:
            records = self.app.load_action_tracker_records_for_clinic("Clinic B")

        self.assertEqual(records, [])
        get_sheet.assert_not_called()

    def test_update_clinic_profile_validates_input_and_renames_dataset_pointer_when_clinic_changes(self):
        old_row = {
            "ClinicID": "Clinic A",
            self.app.SHEET_COL_DATASET_FILE_ID: "drive-file-id",
        }

        with patch.object(self.app, "get_clinic_row", return_value=None):
            with self.assertRaisesRegex(ValueError, "Enter a clinic name"):
                self.app.update_clinic_profile("Clinic A", "", "owner@example.com")
            with self.assertRaisesRegex(ValueError, "valid email"):
                self.app.update_clinic_profile("Clinic A", "Clinic A", "not-an-email")

        def get_row(clinic_id):
            if str(clinic_id).strip().lower() == "clinic renamed":
                return None
            return old_row

        self.app.st.session_state["logged_in"] = True
        self.app.st.session_state["clinic_id"] = "Clinic A"
        with (
            patch.object(self.app, "get_clinic_row", side_effect=get_row),
            patch.object(
                self.app,
                "require_clinic_dataset_file_access",
            ) as require_dataset_access,
            patch.object(self.app, "drive_rename_file") as rename_file,
            patch.object(self.app, "update_settings_row_fields") as update_fields,
            patch.object(
                self.app,
                "update_rows_with_clinic_id",
                return_value=3,
            ) as update_rows,
        ):
            updated = self.app.update_clinic_profile(
                "Clinic A",
                "Clinic Renamed",
                " Owner@Example.COM ",
            )

        self.assertEqual(
            updated,
            {"clinic_id": "Clinic Renamed", "email": "owner@example.com"},
        )
        self.assertEqual(
            [args for args, _kwargs in require_dataset_access.call_args_list],
            [("Clinic A", "drive-file-id"), ("Clinic A", "drive-file-id")],
        )
        rename_file.assert_called_once_with(
            "drive-file-id",
            "Clinic Renamed_shared_dataset.csv",
            clinic_id="Clinic A",
            current_file_id="drive-file-id",
        )
        update_fields.assert_called_once()
        args, _kwargs = update_fields.call_args
        self.assertEqual(args[0], "Clinic A")
        self.assertEqual(args[1]["ClinicID"], "Clinic Renamed")
        self.assertEqual(
            args[1][self.app.SHEET_COL_GOOGLE_EMAIL],
            "owner@example.com",
        )
        self.assertEqual(
            args[1][self.app.SHEET_COL_DATASET_FILE_NAME],
            "Clinic Renamed_shared_dataset.csv",
        )
        update_rows.assert_called_once_with("Clinic A", "Clinic Renamed")

    def test_profile_save_reuses_displayed_profile_row_without_extra_account_reads(self):
        headers = list(self.app.SETTINGS_REQUIRED_COLUMNS)
        row = {
            "ClinicID": "Clinic A",
            self.app.SHEET_COL_GOOGLE_EMAIL: "old@example.com",
            self.app.SHEET_COL_AUTH_PROVIDER: "",
        }

        class FakeSettingsSheet:
            def __init__(self):
                self.get_all_records_calls = 0

            def get_all_records(self):
                self.get_all_records_calls += 1
                return [row]

        sheet = FakeSettingsSheet()
        self.app.st.session_state["logged_in"] = True
        self.app.st.session_state["clinic_id"] = "Clinic A"

        with (
            patch.object(self.app, "get_settings_sheet", return_value=sheet),
            patch.object(self.app, "update_settings_row_fields", return_value=(sheet, headers, 2)) as update_fields,
            patch.object(self.app, "utc_now_iso", return_value="2026-05-19T12:00:00"),
        ):
            profile = self.app.get_clinic_profile("Clinic A")
            updated = self.app.update_clinic_profile("Clinic A", "Clinic A", "owner@example.com")

        self.assertEqual(profile["clinic_id"], "Clinic A")
        self.assertEqual(updated, {"clinic_id": "Clinic A", "email": "owner@example.com"})
        self.assertEqual(sheet.get_all_records_calls, 1)
        update_fields.assert_called_once()
        self.assertEqual(update_fields.call_args.args[0], "Clinic A")
        self.assertEqual(
            update_fields.call_args.args[1][self.app.SHEET_COL_GOOGLE_EMAIL],
            "owner@example.com",
        )

    def test_update_clinic_profile_rejects_google_sign_in_email_change(self):
        old_row = {
            "ClinicID": "Clinic A",
            self.app.SHEET_COL_AUTH_PROVIDER: self.app.GOOGLE_AUTH_PROVIDER,
            self.app.SHEET_COL_GOOGLE_EMAIL: "owner@example.com",
            self.app.SHEET_COL_GOOGLE_SUBJECT: "google-subject",
        }
        self.app.st.session_state["logged_in"] = True
        self.app.st.session_state["clinic_id"] = "Clinic A"

        with (
            patch.object(self.app, "get_clinic_row", return_value=old_row),
            patch.object(self.app, "update_settings_row_fields") as update_fields,
            patch.object(self.app, "update_rows_with_clinic_id") as update_rows,
        ):
            with self.assertRaisesRegex(ValueError, "Google sign-in email"):
                self.app.update_clinic_profile(
                    "Clinic A",
                    "Clinic A",
                    "other@example.com",
                )

        update_fields.assert_not_called()
        update_rows.assert_not_called()

    def test_profile_rename_revalidates_dataset_pointer_before_identity_update(self):
        old_row = {
            "ClinicID": "Clinic A",
            self.app.SHEET_COL_DATASET_FILE_ID: "stale-file-id",
        }

        def get_row(clinic_id):
            if str(clinic_id).strip().lower() == "clinic renamed":
                return None
            return old_row

        self.app.st.session_state["logged_in"] = True
        self.app.st.session_state["clinic_id"] = "Clinic A"
        with (
            patch.object(self.app, "get_clinic_row", side_effect=get_row),
            patch.object(
                self.app,
                "require_clinic_dataset_file_access",
                side_effect=self.app.TenantAuthorizationError(
                    "dataset pointer mismatch"
                ),
            ) as require_dataset_access,
            patch.object(self.app, "drive_rename_file") as rename_file,
            patch.object(self.app, "update_settings_row_fields") as update_fields,
            patch.object(self.app, "update_rows_with_clinic_id") as update_rows,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "Could not update the saved clinic data",
            ):
                self.app.update_clinic_profile(
                    "Clinic A",
                    "Clinic Renamed",
                    "owner@example.com",
                )

        require_dataset_access.assert_called_once_with("Clinic A", "stale-file-id")
        rename_file.assert_not_called()
        update_fields.assert_not_called()
        update_rows.assert_not_called()

    def test_delete_clinic_account_and_data_trashes_dataset_deletes_rows_and_clears_caches(self):
        class FakeWorksheet:
            def __init__(self, values):
                self.values = values
                self.deleted_rows = []

            def get_all_values(self):
                return self.values

            def delete_rows(self, row_idx):
                self.deleted_rows.append(row_idx)

        settings_ws = FakeWorksheet([
            ["ClinicID", "SettingsJSON"],
            ["Clinic A", "{}"],
            ["Clinic B", "{}"],
        ])
        tracker_ws = FakeWorksheet([
            ["ClinicID", "Event"],
            ["clinic a", "sent"],
            ["Clinic C", "sent"],
            ["Clinic A", "declined"],
        ])

        class FakeSpreadsheet:
            def worksheets(self):
                return [settings_ws, tracker_ws]

        state = self.app.st.session_state
        state["_settings_row_cache"] = {"clinic_key": "clinic a"}
        state["_remote_settings_cache"] = {"clinic_key": "clinic a"}
        state["_tracker_sheet_cache"] = {"cached": True}
        state["logged_in"] = True
        state["clinic_id"] = "Clinic A"

        with (
            patch.object(self.app, "get_clinic_row", return_value={
                "ClinicID": "Clinic A",
                self.app.SHEET_COL_DATASET_FILE_ID: "drive-file-id",
            }),
            patch.object(self.app, "drive_file_owner_key", return_value=""),
            patch.object(self.app, "drive_trash_file") as trash_file,
            patch.object(self.app, "get_settings_spreadsheet", return_value=FakeSpreadsheet()),
            patch.object(self.app, "_gspread_retry", side_effect=self.retry_immediately),
            patch.object(self.app, "record_account_lifecycle_event") as lifecycle_event,
        ):
            result = self.app.delete_clinic_account_and_data(" Clinic A ")

        self.assertEqual(result, {"deleted_rows": 3, "trashed_dataset": True})
        trash_file.assert_called_once_with("drive-file-id", clinic_id="Clinic A", current_file_id="drive-file-id")
        self.assertEqual(settings_ws.deleted_rows, [2])
        self.assertEqual(tracker_ws.deleted_rows, [4, 2])
        lifecycle_event.assert_called_once_with(
            "Clinic A",
            "deleted",
            clinic_name="Clinic A",
            auth_provider="",
            country="",
            deleted_rows=3,
            trashed_data_file=True,
            source="delete_account_and_data",
        )
        self.assertNotIn("_settings_row_cache", state)
        self.assertNotIn("_remote_settings_cache", state)
        self.assertNotIn("_tracker_sheet_cache", state)

    def test_delete_clinic_account_and_data_rejects_empty_or_missing_clinic_before_writes(self):
        with self.assertRaisesRegex(ValueError, "No clinic"):
            self.app.delete_clinic_account_and_data("")

        self.app.st.session_state["logged_in"] = True
        self.app.st.session_state["clinic_id"] = "Missing Clinic"
        with (
            patch.object(self.app, "get_clinic_row", return_value=None),
            patch.object(self.app, "drive_trash_file") as trash_file,
            patch.object(self.app, "get_settings_spreadsheet") as spreadsheet,
        ):
            with self.assertRaisesRegex(ValueError, "could not be found"):
                self.app.delete_clinic_account_and_data("Missing Clinic")

        trash_file.assert_not_called()
        spreadsheet.assert_not_called()

    def test_delete_account_dialog_does_not_treat_rerun_as_delete_failure(self):
        class FakeForm:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        def passthrough_dialog(*args, **kwargs):
            def decorator(fn):
                return fn
            return decorator

        state = self.app.st.session_state
        state["show_delete_account_dialog"] = True
        state["clinic_id"] = "Clinic A"

        with (
            patch.object(self.app.st, "dialog", side_effect=passthrough_dialog),
            patch.object(self.app.st, "markdown"),
            patch.object(self.app.st, "form", return_value=FakeForm()),
            patch.object(self.app.st, "caption"),
            patch.object(self.app.st, "text_input", return_value="DELETE Clinic A"),
            patch.object(self.app.st, "form_submit_button", return_value=True),
            patch.object(self.app.st, "button", return_value=False),
            patch.object(self.app.st, "error") as show_error,
            patch.object(self.app.st, "rerun", side_effect=RuntimeError("rerun control")),
            patch.object(self.app, "delete_clinic_account_and_data") as delete_account,
            patch.object(self.app, "get_google_user_info", return_value={"is_logged_in": False}),
            patch.object(self.app, "clear_remember_login_token"),
            patch.object(self.app, "clear_account_session_state"),
            patch.object(self.app, "record_error_tracker_event") as record_error,
        ):
            with self.assertRaisesRegex(RuntimeError, "rerun control"):
                self.app.render_delete_account_dialog()

        delete_account.assert_called_once_with("Clinic A")
        show_error.assert_not_called()
        record_error.assert_not_called()
        self.assertFalse(state["show_delete_account_dialog"])

    def test_delete_account_dialog_does_not_report_delete_failure_when_cleanup_fails(self):
        class FakeForm:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        def passthrough_dialog(*args, **kwargs):
            def decorator(fn):
                return fn
            return decorator

        state = self.app.st.session_state
        state["show_delete_account_dialog"] = True
        state["clinic_id"] = "Clinic A"
        state["logged_in"] = True

        with (
            patch.object(self.app.st, "dialog", side_effect=passthrough_dialog),
            patch.object(self.app.st, "markdown"),
            patch.object(self.app.st, "form", return_value=FakeForm()),
            patch.object(self.app.st, "caption"),
            patch.object(self.app.st, "text_input", return_value="DELETE Clinic A"),
            patch.object(self.app.st, "form_submit_button", return_value=True),
            patch.object(self.app.st, "button", return_value=False),
            patch.object(self.app.st, "error") as show_error,
            patch.object(self.app.st, "rerun", side_effect=RuntimeError("rerun control")),
            patch.object(self.app, "busy_overlay", return_value=contextlib.nullcontext()),
            patch.object(self.app, "delete_clinic_account_and_data") as delete_account,
            patch.object(self.app, "get_google_user_info", return_value={"is_logged_in": False}),
            patch.object(self.app, "clear_remember_login_token"),
            patch.object(self.app, "clear_account_session_state", side_effect=RuntimeError("widget key already instantiated")),
            patch.object(self.app, "record_error_tracker_event") as record_error,
        ):
            with self.assertRaisesRegex(RuntimeError, "rerun control"):
                self.app.render_delete_account_dialog()

        delete_account.assert_called_once_with("Clinic A")
        show_error.assert_not_called()
        record_error.assert_called_once()
        self.assertEqual(record_error.call_args.kwargs["stage"], "delete_account_session_state")
        self.assertFalse(state["logged_in"])
        self.assertNotIn("clinic_id", state)
        self.assertFalse(state["show_delete_account_dialog"])

    def test_tenant_guard_blocks_cross_tenant_profile_update_before_mutations(self):
        self.app.st.session_state["logged_in"] = True
        self.app.st.session_state["clinic_id"] = "Clinic A"

        with (
            patch.object(self.app, "get_clinic_row", return_value=None),
            patch.object(self.app, "drive_rename_file") as rename_file,
            patch.object(self.app, "update_settings_row_fields") as update_fields,
            patch.object(self.app, "update_rows_with_clinic_id") as update_rows,
        ):
            with self.assertRaises(self.app.TenantAuthorizationError):
                self.app.update_clinic_profile("Clinic B", "Clinic Renamed", "owner@example.com")

        rename_file.assert_not_called()
        update_fields.assert_not_called()
        update_rows.assert_not_called()

    def test_tenant_guard_blocks_cross_tenant_delete_before_writes(self):
        self.app.st.session_state["logged_in"] = True
        self.app.st.session_state["clinic_id"] = "Clinic A"

        with (
            patch.object(self.app, "get_clinic_row") as get_row,
            patch.object(self.app, "get_settings_spreadsheet") as get_spreadsheet,
            patch.object(self.app, "drive_trash_file") as trash_file,
        ):
            with self.assertRaises(self.app.TenantAuthorizationError):
                self.app.delete_clinic_account_and_data("Clinic B")

        get_row.assert_not_called()
        get_spreadsheet.assert_not_called()
        trash_file.assert_not_called()

    def test_tenant_guard_blocks_cross_tenant_dataset_pointer_clear_before_writes(self):
        self.app.st.session_state["logged_in"] = True
        self.app.st.session_state["clinic_id"] = "Clinic A"

        with (
            patch.object(self.app, "update_authorized_settings_row_fields") as update_fields,
            patch.object(self.app, "update_cached_settings_row_fields") as update_cache,
        ):
            with self.assertRaises(self.app.TenantAuthorizationError):
                self.app.clear_clinic_dataset_pointer("Clinic B")

        update_fields.assert_not_called()
        update_cache.assert_not_called()

    def test_clear_clinic_dataset_pointer_only_clears_signed_in_clinic_pointer(self):
        self.app.st.session_state["logged_in"] = True
        self.app.st.session_state["clinic_id"] = "Clinic A"

        with (
            patch.object(self.app, "update_authorized_settings_row_fields") as update_fields,
            patch.object(self.app, "update_cached_settings_row_fields") as update_cache,
        ):
            self.app.clear_clinic_dataset_pointer(" Clinic A ")

        expected_values = {
            self.app.SHEET_COL_DATASET_FILE_ID: "",
            self.app.SHEET_COL_DATASET_FILE_NAME: "",
            self.app.SHEET_COL_DATASET_UPDATED_AT: "",
        }
        update_fields.assert_called_once_with(
            "Clinic A",
            expected_values,
            self.app.SETTINGS_REQUIRED_COLUMNS,
        )
        update_cache.assert_called_once_with("Clinic A", expected_values)

    def test_authorized_settings_repository_update_blocks_cross_tenant_raw_write(self):
        self.app.st.session_state["logged_in"] = True
        self.app.st.session_state["clinic_id"] = "Clinic A"

        with patch.object(self.app, "_raw_update_settings_row_fields") as raw_update:
            with self.assertRaises(self.app.TenantAuthorizationError):
                self.app.update_authorized_settings_row_fields(
                    "Clinic B",
                    {self.app.SHEET_COL_ACCOUNT_STATUS: "active"},
                    self.app.SETTINGS_REQUIRED_COLUMNS,
                )

        raw_update.assert_not_called()

    def test_default_settings_row_update_blocks_cross_tenant_raw_write(self):
        self.app.st.session_state["logged_in"] = True
        self.app.st.session_state["clinic_id"] = "Clinic A"

        with patch.object(self.app, "_raw_update_settings_row_fields") as raw_update:
            with self.assertRaises(self.app.TenantAuthorizationError):
                self.app.update_settings_row_fields(
                    "Clinic B",
                    {self.app.SHEET_COL_ACCOUNT_STATUS: "active"},
                    self.app.SETTINGS_REQUIRED_COLUMNS,
                )

        raw_update.assert_not_called()

    def test_authorized_settings_repository_update_allows_signed_in_clinic(self):
        self.app.st.session_state["logged_in"] = True
        self.app.st.session_state["clinic_id"] = "Clinic A"

        with patch.object(self.app, "_raw_update_settings_row_fields", return_value=("sheet", ["ClinicID"], 2)) as raw_update:
            result = self.app.update_authorized_settings_row_fields(
                " Clinic A ",
                {self.app.SHEET_COL_ACCOUNT_STATUS: "active"},
                self.app.SETTINGS_REQUIRED_COLUMNS,
            )

        self.assertEqual(result, ("sheet", ["ClinicID"], 2))
        raw_update.assert_called_once_with(
            "Clinic A",
            {self.app.SHEET_COL_ACCOUNT_STATUS: "active"},
            self.app.SETTINGS_REQUIRED_COLUMNS,
        )

    def test_dataset_publish_rejects_existing_file_id_not_owned_by_signed_in_clinic(self):
        self.app.st.session_state["logged_in"] = True
        self.app.st.session_state["clinic_id"] = "Clinic A"
        new_df = pd.DataFrame({"ChargeDate": pd.to_datetime(["2025-01-01"]), "Client Name": ["Client"]})

        with (
            patch.object(self.app, "get_existing_dataset_pointer", return_value=("clinic-a-file", "clinic-a.csv")),
            patch.object(self.app, "drive_upsert_csv_bytes") as upsert,
            patch.object(self.app, "update_clinic_dataset_pointer") as update_pointer,
        ):
            with self.assertRaises(self.app.TenantAuthorizationError):
                self.app.publish_dataset_for_clinic(
                    "Clinic A",
                    new_df,
                    self.app.DATASETS_FOLDER_ID,
                    existing_file_id="clinic-b-file",
                    existing_name="clinic-b.csv",
                    existing_df=pd.DataFrame(),
                )

        upsert.assert_not_called()
        update_pointer.assert_not_called()

    def test_dataset_file_owner_metadata_must_match_signed_in_clinic(self):
        self.app.st.session_state["logged_in"] = True
        self.app.st.session_state["clinic_id"] = "Clinic A"

        with (
            patch.object(self.app, "get_existing_dataset_pointer", return_value=("shared-file", "clinic-a.csv")),
            patch.object(self.app, "drive_file_owner_key", return_value="clinic b"),
        ):
            with self.assertRaises(self.app.TenantAuthorizationError):
                self.app.require_clinic_dataset_file_access("Clinic A", "shared-file")

    def test_append_tracker_row_returns_false_when_external_sheet_write_fails(self):
        with patch.object(self.app, "get_or_create_tracker_sheet", side_effect=RuntimeError("permission denied")):
            saved = self.app.append_tracker_row("Action tracker", self.app.ACTION_TRACKER_HEADERS, ["value"])

        self.assertFalse(saved)

    def test_upload_validation_characterizes_missing_dates_empty_and_unsupported_file(self):
        with self.assertRaisesRegex(self.app.UploadValidationError, "missing required column"):
            self.app.validate_upload_dataframe(pd.DataFrame({"Client Name": ["Client A"]}), "missing.csv")

        bad_dates = pd.DataFrame({
            "ChargeDate": ["not a date"],
            "Client Name": ["Client A"],
            "Animal Name": ["Pet A"],
            "Item Name": ["Rabies"],
        })
        with self.assertRaisesRegex(self.app.UploadValidationError, "readable date"):
            self.app.validate_upload_dataframe(bad_dates, "bad-dates.csv")

        empty = pd.DataFrame({
            "ChargeDate": [],
            "Client Name": [],
            "Animal Name": [],
            "Item Name": [],
        })
        with self.assertRaisesRegex(self.app.UploadValidationError, "readable date"):
            self.app.validate_upload_dataframe(empty, "empty.csv")

        with self.assertRaisesRegex(ValueError, "Unsupported file type"):
            self.app.process_file(b"not relevant", "upload.txt")

    def test_oversized_upload_is_rejected_before_csv_parser_runs(self):
        self.assertEqual(self.app.MAX_UPLOAD_FILE_BYTES, 50 * 1024 * 1024)
        self.assertEqual(self.app.format_file_size(self.app.MAX_UPLOAD_FILE_BYTES), "50 MB")
        oversized = b"x" * (self.app.MAX_UPLOAD_FILE_BYTES + 1)

        with patch.object(self.app.pd, "read_csv") as read_csv:
            with self.assertRaisesRegex(
                self.app.UploadResourceLimitError,
                "too large",
            ):
                self.app.process_file(oversized, "large.csv")

        read_csv.assert_not_called()

    def test_upload_dataframe_limits_reject_excessive_rows_and_columns(self):
        with patch.object(self.app, "MAX_UPLOAD_ROWS", 2):
            with self.assertRaisesRegex(
                self.app.UploadResourceLimitError,
                "too many rows",
            ):
                self.app.validate_upload_dataframe_limits(
                    pd.DataFrame({"ChargeDate": ["2026-01-01"] * 3}),
                    "many-rows.csv",
                )

        with patch.object(self.app, "MAX_UPLOAD_COLUMNS", 2):
            with self.assertRaisesRegex(
                self.app.UploadResourceLimitError,
                "too many columns",
            ):
                self.app.validate_upload_dataframe_limits(
                    pd.DataFrame(columns=["a", "b", "c"]),
                    "many-columns.csv",
                )

    def test_upload_file_collection_limits_file_count(self):
        too_many_files = [
            {"name": f"upload-{idx}.csv", "bytes": b"data"}
            for idx in range(self.app.MAX_UPLOAD_FILES + 1)
        ]

        with self.assertRaisesRegex(
            self.app.UploadResourceLimitError,
            "Upload at most",
        ):
            self.app.validate_upload_file_collection(too_many_files)

    def test_finish_authenticated_session_sets_session_and_invokes_external_side_effects(self):
        state = self.app.st.session_state
        state["working_df"] = "stale"
        google_user = {"email": "owner@example.com", "subject": "google-subject"}

        with (
            patch.object(self.app, "close_account_dialogs") as close_dialogs,
            patch.object(self.app, "reset_uploaded_data_state") as reset_uploaded,
            patch.object(self.app, "load_settings") as load_settings,
            patch.object(self.app, "load_shared_dataset_for_clinic") as load_dataset,
            patch.object(self.app, "record_settings_account_event") as record_account,
            patch.object(self.app, "upsert_user_tracker") as upsert_tracker,
        ):
            self.app.finish_authenticated_session(
                " Clinic A ",
                event="google_login",
                auth_provider=self.app.GOOGLE_AUTH_PROVIDER,
                google_user=google_user,
            )

        self.assertEqual(state["clinic_id"], "Clinic A")
        self.assertTrue(state["logged_in"])
        self.assertFalse(state["show_top_change_password"])
        self.assertEqual(state["auth_provider"], self.app.GOOGLE_AUTH_PROVIDER)
        self.assertEqual(state["google_email"], "owner@example.com")
        self.assertEqual(state["google_subject"], "google-subject")
        close_dialogs.assert_called_once()
        reset_uploaded.assert_called_once_with(clear_cache=False, reset_uploader=True)
        load_settings.assert_called_once_with(load_action_history=False)
        load_dataset.assert_called_once()
        record_account.assert_called_once()
        upsert_tracker.assert_called_once()


if __name__ == "__main__":
    unittest.main()
