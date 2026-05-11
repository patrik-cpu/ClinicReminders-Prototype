import unittest
import pandas as pd
import reminders_app_v3 as app


class FakeSheet:
    def __init__(self):
        self.batch_payloads = []

    def batch_update(self, payload):
        self.batch_payloads.append(payload)


class FakeLookupSheet:
    def __init__(self, rows):
        self._rows = rows

    def get_all_values(self):
        return self._rows


class SettingsHelperTests(unittest.TestCase):
    def test_reset_uploaded_data_state_alias_calls_internal_helper(self):
        called = {}
        old_impl = app._reset_uploaded_data_state
        app._reset_uploaded_data_state = lambda clear_cache=True: called.setdefault("clear_cache", clear_cache)
        try:
            app.reset_uploaded_data_state(clear_cache=False)
        finally:
            app._reset_uploaded_data_state = old_impl

        self.assertEqual(called["clear_cache"], False)

    def test_get_settings_row_for_clinic_case_insensitive(self):
        rows = [
            ["ClinicID", "SettingsJSON", "UpdatedAt"],
            ["AlphaVet", "{}", "2026-05-01"],
            ["BetaPet", "{}", "2026-05-02"],
        ]
        old_get_sheet = app.get_settings_sheet
        old_retry = app._gspread_retry
        app.get_settings_sheet = lambda: FakeLookupSheet(rows)
        app._gspread_retry = lambda fn, *args, **kwargs: fn(*args, **kwargs)
        try:
            _, headers, row_idx = app._get_settings_row_for_clinic("  betapet ")
        finally:
            app.get_settings_sheet = old_get_sheet
            app._gspread_retry = old_retry

        self.assertEqual(headers[0], "ClinicID")
        self.assertEqual(row_idx, 3)

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

    def test_update_password_cells_batches_single_range(self):
        sheet = FakeSheet()
        headers = ["ClinicID", "PlainPassword", "PasswordHash", "UpdatedAt"]

        old_retry = app._gspread_retry
        app._gspread_retry = lambda fn, *args, **kwargs: fn(*args, **kwargs)
        try:
            app._update_password_cells(sheet, headers, 4, "pw", "hash", "2026-05-08T00:00:00")
        finally:
            app._gspread_retry = old_retry

        self.assertEqual(len(sheet.batch_payloads), 1)
        self.assertEqual(sheet.batch_payloads[0], [{"range": "B4:D4", "values": [["pw", "hash", "2026-05-08T00:00:00"]]}])

    def test_bundle_client_reminders_by_window_groups_within_five_days(self):
        df = pd.DataFrame([
            {"DueDate": "2026-05-11", "DueDateFmt": "2026-05-11", "ChargeDate": "2026-05-01", "ChargeDateFmt": "2026-05-01", "Client Name": "Jane Doe", "Animal Name": "Barney", "MatchedItems": ["Apoquel"], "Qty": 1, "IntervalDays": 30, "BaseIntervalDays": 30},
            {"DueDate": "2026-05-14", "DueDateFmt": "2026-05-14", "ChargeDate": "2026-05-02", "ChargeDateFmt": "2026-05-02", "Client Name": "Jane Doe", "Animal Name": "Sammy", "MatchedItems": ["Dental"], "Qty": 1, "IntervalDays": 180, "BaseIntervalDays": 180},
        ])

        grouped = app.bundle_client_reminders_by_window(df, window_days=5)

        self.assertEqual(len(grouped), 1)
        row = grouped.iloc[0]
        self.assertEqual(row["Client Name"], "Jane Doe")
        self.assertIn("Barney", row["Animal Name"])
        self.assertIn("Sammy", row["Animal Name"])
        self.assertIn("2026-05-11", row["Due Date"])
        self.assertIn("2026-05-14", row["Due Date"])


if __name__ == "__main__":
    unittest.main()
