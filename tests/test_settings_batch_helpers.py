import unittest
import reminders_app_v3 as app


class FakeSheet:
    def __init__(self):
        self.batch_payloads = []

    def batch_update(self, payload, value_input_option="RAW"):
        self.batch_payloads.append(payload)


class SettingsHelperTests(unittest.TestCase):
    def test_update_dataset_pointer_cells_batches_single_range(self):
        sheet = FakeSheet()
        headers = ["ClinicID", "DatasetFileId", "DatasetFileName", "DatasetUpdatedAt"]

        captured = {}

        def fake_retry(fn, *args, **kwargs):
            captured["fn_name"] = fn.__name__
            return fn(*args, **kwargs)

        old_retry = app._gspread_retry
        app._gspread_retry = fake_retry
        try:
            app._update_dataset_pointer_cells(sheet, headers, 5, "fid", "name.csv", "2026-05-08T00:00:00")
        finally:
            app._gspread_retry = old_retry

        self.assertEqual(captured["fn_name"], "batch_update")
        self.assertEqual(len(sheet.batch_payloads), 1)
        self.assertEqual(sheet.batch_payloads[0], [{"range": "B5:D5", "values": [["fid", "name.csv", "2026-05-08T00:00:00"]]}])

    def test_update_settings_cells_batches_single_range(self):
        sheet = FakeSheet()
        headers = ["ClinicID", "Some", "SettingsJSON", "UpdatedAt"]

        old_retry = app._gspread_retry
        app._gspread_retry = lambda fn, *args, **kwargs: fn(*args, **kwargs)
        try:
            app._update_settings_cells(sheet, headers, 3, '{"a":1}', "2026-05-08T00:00:00")
        finally:
            app._gspread_retry = old_retry

        self.assertEqual(len(sheet.batch_payloads), 1)
        self.assertEqual(sheet.batch_payloads[0], [{"range": "C3:D3", "values": [['{"a":1}', "2026-05-08T00:00:00"]]}])

    def test_update_settings_cells_batches_metadata_fields_in_same_call(self):
        sheet = FakeSheet()
        headers = ["ClinicID", "SettingsJSON", "UpdatedAt", "Country", "AccountStatus"]

        old_retry = app._gspread_retry
        app._gspread_retry = lambda fn, *args, **kwargs: fn(*args, **kwargs)
        try:
            app._update_settings_cells(
                sheet,
                headers,
                4,
                '{"a":1}',
                "2026-05-08T00:00:00",
                {
                    "Country": "United Arab Emirates",
                    "AccountStatus": "active",
                },
            )
        finally:
            app._gspread_retry = old_retry

        self.assertEqual(len(sheet.batch_payloads), 1)
        self.assertEqual(
            sheet.batch_payloads[0],
            [
                {"range": "B4:C4", "values": [['{"a":1}', "2026-05-08T00:00:00"]]},
                {"range": "D4:D4", "values": [["United Arab Emirates"]]},
                {"range": "E4:E4", "values": [["active"]]},
            ],
        )


if __name__ == "__main__":
    unittest.main()
