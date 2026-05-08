import unittest

import settings_pointer_utils as spu


class FakeSheet:
    def __init__(self):
        self.calls = []

    def batch_update(self, body, value_input_option="RAW"):
        self.calls.append((body, value_input_option))
        return {"updated": True}

class FakeLookupSheet:
    def __init__(self, rows):
        self._rows = rows

    def get_all_values(self):
        return self._rows


class SettingsPointerHelpersTests(unittest.TestCase):
    def test_settings_col_index(self):
        headers = ["ClinicID", "DatasetFileId", "DatasetFileName", "DatasetUpdatedAt"]
        self.assertEqual(spu.settings_col_index(headers, "ClinicID"), 1)
        self.assertEqual(spu.settings_col_index(headers, "DatasetUpdatedAt"), 4)

    def test_update_dataset_pointer_cells_batches_single_range(self):
        headers = ["ClinicID", "DatasetFileId", "DatasetFileName", "DatasetUpdatedAt"]
        sheet = FakeSheet()
        spu.update_dataset_pointer_cells(
            sheet=sheet,
            headers=headers,
            row_idx=5,
            file_id="file-123",
            filename="clinic.csv",
            updated_at="2026-05-04T12:00:00",
            dataset_file_id_col="DatasetFileId",
            dataset_updated_at_col="DatasetUpdatedAt",
            retry_fn=lambda fn, *a, **k: fn(*a, **k),
        )

        self.assertEqual(len(sheet.calls), 1)
        body, value_input_option = sheet.calls[0]
        self.assertEqual(value_input_option, "RAW")
        self.assertEqual(body[0]["range"], "B5:D5")
        self.assertEqual(body[0]["values"], [["file-123", "clinic.csv", "2026-05-04T12:00:00"]])

    def test_settings_col_index_missing_header_raises(self):
        headers = ["ClinicID", "DatasetFileId"]
        with self.assertRaises(ValueError):
            spu.settings_col_index(headers, "DatasetUpdatedAt")

    def test_update_dataset_pointer_cells_rejects_header_row(self):
        headers = ["ClinicID", "DatasetFileId", "DatasetFileName", "DatasetUpdatedAt"]
        sheet = FakeSheet()
        with self.assertRaises(ValueError):
            spu.update_dataset_pointer_cells(
                sheet=sheet,
                headers=headers,
                row_idx=1,
                file_id="file-123",
                filename="clinic.csv",
                updated_at="2026-05-04T12:00:00",
                dataset_file_id_col="DatasetFileId",
                dataset_updated_at_col="DatasetUpdatedAt",
                retry_fn=lambda fn, *a, **k: fn(*a, **k),
            )

    def test_get_settings_row_for_clinic_case_insensitive_and_trim(self):
        sheet = FakeLookupSheet(
            [
                ["ClinicID", "Other"],
                ["clinic-a", "x"],
                ["Clinic-B", "y"],
            ]
        )
        headers, row_idx = spu.get_settings_row_for_clinic(sheet, " CLINIC-b ")
        self.assertEqual(row_idx, 3)
        self.assertEqual(headers[0], "ClinicID")

    def test_get_settings_row_for_clinic_missing_raises(self):
        sheet = FakeLookupSheet(
            [
                ["ClinicID", "Other"],
                ["clinic-a", "x"],
            ]
        )
        with self.assertRaises(ValueError):
            spu.get_settings_row_for_clinic(sheet, "clinic-z")


if __name__ == "__main__":
    unittest.main()
