import contextlib
import importlib
import io
import unittest
from datetime import date
from unittest.mock import patch


class LogicEdgeCaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            cls.app = importlib.import_module("reminders_app_v3")

    def setUp(self):
        state = self.app.st.session_state
        for key in list(state.keys()):
            del state[key]

    def test_create_clinic_account_rejects_blank_clinic_before_sheet_access(self):
        with (
            patch.object(self.app, "get_clinic_row") as get_row,
            patch.object(self.app, "get_settings_sheet") as get_sheet,
        ):
            with self.assertRaisesRegex(ValueError, "Enter a clinic name"):
                self.app.create_clinic_account("   ", "United States", "secret-password")

        get_row.assert_not_called()
        get_sheet.assert_not_called()

    def test_create_clinic_account_rejects_short_password_before_writing(self):
        with (
            patch.object(self.app, "get_clinic_row") as get_row,
            patch.object(self.app, "get_settings_sheet") as get_sheet,
        ):
            with self.assertRaisesRegex(ValueError, "Password must be at least 12 characters"):
                self.app.create_clinic_account("Clinic Short", "United States", "12345")

        get_row.assert_not_called()
        get_sheet.assert_not_called()

    def test_update_clinic_profile_stops_if_dataset_rename_fails(self):
        old_row = {
            "ClinicID": "Clinic A",
            self.app.SHEET_COL_DATASET_FILE_ID: "drive-file-id",
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
            ) as require_dataset_access,
            patch.object(
                self.app,
                "drive_rename_file",
                side_effect=RuntimeError("drive down"),
            ),
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

        require_dataset_access.assert_called_once_with("Clinic A", "drive-file-id")
        update_fields.assert_not_called()
        update_rows.assert_not_called()

    def test_delete_account_does_not_trash_dataset_if_sheet_delete_fails(self):
        class FailingWorksheet:
            def get_all_values(self):
                return [["ClinicID", "SettingsJSON"], ["Clinic A", "{}"]]

            def delete_rows(self, row_idx):
                raise RuntimeError("sheet write failed")

        class FakeSpreadsheet:
            def worksheets(self):
                return [FailingWorksheet()]

        self.app.st.session_state["logged_in"] = True
        self.app.st.session_state["clinic_id"] = "Clinic A"
        with (
            patch.object(self.app, "get_clinic_row", return_value={
                "ClinicID": "Clinic A",
                self.app.SHEET_COL_DATASET_FILE_ID: "drive-file-id",
            }),
            patch.object(self.app, "drive_file_owner_key", return_value=""),
            patch.object(self.app, "get_settings_spreadsheet", return_value=FakeSpreadsheet()),
            patch.object(self.app, "drive_trash_file") as trash_file,
            patch.object(self.app, "record_account_lifecycle_event") as lifecycle_event,
            patch.object(self.app, "_gspread_retry", side_effect=lambda fn, *a, **k: fn(*a, **k)),
        ):
            with self.assertRaisesRegex(RuntimeError, "sheet write failed"):
                self.app.delete_clinic_account_and_data("Clinic A")

        trash_file.assert_not_called()
        lifecycle_event.assert_not_called()

    def test_delete_account_does_not_delete_sheet_rows_if_drive_ownership_fails(self):
        self.app.st.session_state["logged_in"] = True
        self.app.st.session_state["clinic_id"] = "Clinic A"
        with (
            patch.object(self.app, "get_clinic_row", return_value={
                "ClinicID": "Clinic A",
                self.app.SHEET_COL_DATASET_FILE_ID: "drive-file-id",
            }),
            patch.object(
                self.app,
                "require_clinic_dataset_file_access",
                side_effect=PermissionError("dataset access denied"),
            ) as require_access,
            patch.object(self.app, "get_settings_spreadsheet") as spreadsheet,
            patch.object(self.app, "drive_trash_file") as trash_file,
            patch.object(self.app, "record_account_lifecycle_event") as lifecycle_event,
        ):
            with self.assertRaisesRegex(PermissionError, "dataset access denied"):
                self.app.delete_clinic_account_and_data("Clinic A")

        require_access.assert_called_once_with(
            "Clinic A",
            "drive-file-id",
            current_file_id="drive-file-id",
        )
        spreadsheet.assert_not_called()
        trash_file.assert_not_called()
        lifecycle_event.assert_not_called()

    def test_statistics_team_frame_handles_missing_optional_action_columns(self):
        team = self.app.build_statistics_team_frame(
            [{"ActionedAt": "2026-05-16T09:00:00"}],
            "Today",
            today=date(2026, 5, 16),
        )

        self.assertEqual(len(team.index), 1)
        row = team.to_dict("records")[0]
        self.assertEqual(row["User"], "Unknown")
        self.assertEqual(row["Actioned"], 1)
        self.assertEqual(row["Sent"], 0)
        self.assertEqual(row["Declined"], 0)


if __name__ == "__main__":
    unittest.main()
