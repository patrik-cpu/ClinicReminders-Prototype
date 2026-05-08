import unittest
from unittest.mock import patch

import reminders_app_v3 as app


class PointerWrapperTests(unittest.TestCase):
    def test_wrapper_passes_expected_column_names_and_retry(self):
        captured = {}

        def fake_update_dataset_pointer_cells(**kwargs):
            captured.update(kwargs)

        with patch.object(app, "update_dataset_pointer_cells", side_effect=fake_update_dataset_pointer_cells):
            app._update_dataset_pointer_cells(
                sheet="SHEET",
                headers=["ClinicID", "DatasetFileId", "DatasetFileName", "DatasetUpdatedAt"],
                row_idx=8,
                file_id="f1",
                filename="name.csv",
                updated_at="2026-05-08T00:00:00",
            )

        self.assertEqual(captured["sheet"], "SHEET")
        self.assertEqual(captured["row_idx"], 8)
        self.assertEqual(captured["dataset_file_id_col"], app.SHEET_COL_DATASET_FILE_ID)
        self.assertEqual(captured["dataset_updated_at_col"], app.SHEET_COL_DATASET_UPDATED_AT)
        self.assertIs(captured["retry_fn"], app._gspread_retry)

    def test_update_settings_cells_uses_single_batch_update(self):
        calls = []

        class FakeSheet:
            def batch_update(self, body, value_input_option="RAW"):
                calls.append((body, value_input_option))

        def passthrough_retry(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        with patch.object(app, "_gspread_retry", side_effect=passthrough_retry):
            app._update_settings_cells(
                sheet=FakeSheet(),
                headers=["ClinicID", "SettingsJSON", "UpdatedAt"],
                row_idx=5,
                settings_json='{"a":1}',
                updated_at="2026-05-08T00:00:00",
            )

        self.assertEqual(len(calls), 1)
        body, value_input_option = calls[0]
        self.assertEqual(value_input_option, "RAW")
        self.assertEqual(body[0]["range"], "B5:C5")
        self.assertEqual(body[0]["values"], [['{"a":1}', "2026-05-08T00:00:00"]])


if __name__ == "__main__":
    unittest.main()
