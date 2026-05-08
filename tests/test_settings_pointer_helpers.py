import unittest
from unittest.mock import patch

import reminders_app_v3 as app


class FakeSheet:
    def __init__(self):
        self.calls = []

    def batch_update(self, body, value_input_option="RAW"):
        self.calls.append((body, value_input_option))
        return {"updated": True}


class SettingsPointerHelpersTests(unittest.TestCase):
    def test_settings_col_index(self):
        headers = ["ClinicID", "DatasetFileId", "DatasetFileName", "DatasetUpdatedAt"]
        self.assertEqual(app._settings_col_index(headers, "ClinicID"), 1)
        self.assertEqual(app._settings_col_index(headers, "DatasetUpdatedAt"), 4)

    def test_update_dataset_pointer_cells_batches_single_range(self):
        headers = ["ClinicID", "DatasetFileId", "DatasetFileName", "DatasetUpdatedAt"]
        sheet = FakeSheet()

        with patch.object(app, "_gspread_retry", side_effect=lambda fn, *a, **k: fn(*a, **k)):
            app._update_dataset_pointer_cells(
                sheet=sheet,
                headers=headers,
                row_idx=5,
                file_id="file-123",
                filename="clinic.csv",
                updated_at="2026-05-04T12:00:00",
            )

        self.assertEqual(len(sheet.calls), 1)
        body, value_input_option = sheet.calls[0]
        self.assertEqual(value_input_option, "RAW")
        self.assertEqual(body[0]["range"], "B5:D5")
        self.assertEqual(body[0]["values"], [["file-123", "clinic.csv", "2026-05-04T12:00:00"]])


if __name__ == "__main__":
    unittest.main()
