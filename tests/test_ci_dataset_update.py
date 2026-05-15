import contextlib
import importlib
import io
import unittest
from unittest.mock import patch

import pandas as pd


class DatasetUpdateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            cls.app = importlib.import_module("reminders_app_v3")

    def test_replace_overlapping_upload_date_range(self):
        existing = pd.DataFrame(
            {
                "ChargeDate": pd.to_datetime(["2025-01-15", "2025-02-10", "2025-03-05"]),
                "Client Name": ["Jan", "Old Feb", "Mar"],
                "Animal Name": ["A", "B", "C"],
                "Item Name": ["Consult", "Old vaccine", "Consult"],
                "Qty": [1, 1, 1],
                "Amount": [10, 20, 30],
            }
        )
        new = pd.DataFrame(
            {
                "ChargeDate": pd.to_datetime(["2025-02-01", "2025-02-28"]),
                "Client Name": ["New Feb 1", "New Feb 2"],
                "Animal Name": ["D", "E"],
                "Item Name": ["Vaccine", "Consult"],
                "Qty": [1, 1],
                "Amount": [40, 50],
            }
        )

        merged = self.app.merge_dataset_update(existing, new, replace_overlapping_dates=True)

        self.assertEqual(
            list(merged["Client Name"]),
            ["Jan", "New Feb 1", "New Feb 2", "Mar"],
        )

    def test_append_non_overlapping_upload(self):
        existing = pd.DataFrame({"ChargeDate": pd.to_datetime(["2025-01-15"]), "Client Name": ["Jan"]})
        new = pd.DataFrame({"ChargeDate": pd.to_datetime(["2025-02-15"]), "Client Name": ["Feb"]})

        merged = self.app.merge_dataset_update(existing, new, replace_overlapping_dates=False)

        self.assertEqual(list(merged["Client Name"]), ["Jan", "Feb"])

    def test_history_row_count_accepts_float_string(self):
        self.assertEqual(self.app.parse_history_int("56,123.0"), 56123)

    def test_history_row_count_prefers_nonzero_alias(self):
        history = [{"file_name": "sales.csv", "rows": 0, "Rows": "56,123.0"}]

        normalized = self.app.normalize_dataset_upload_history(history)

        self.assertEqual(normalized[0]["rows"], 56123)

    def test_repairs_zero_history_row_count_from_dataframe(self):
        history = [
            {
                "file_name": "sales.csv",
                "pms": "VetPORT",
                "rows": 0,
                "from": "2025-01-01",
                "to": "2025-01-31",
                "status": "Saved",
            }
        ]
        df = pd.DataFrame({"ChargeDate": pd.to_datetime(["2025-01-01", "2025-01-15", "2025-02-01"])})

        repaired, changed = self.app.repair_history_row_counts_from_df(history, df)

        self.assertTrue(changed)
        self.assertEqual(repaired[0]["rows"], 2)

    def test_repairs_single_zero_history_row_count_even_when_dates_do_not_match(self):
        history = [
            {
                "file_name": "sales.csv",
                "pms": "VetPORT",
                "rows": 0,
                "from": "2025-01-01",
                "to": "2025-01-31",
                "status": "Saved",
            }
        ]
        df = pd.DataFrame({"ChargeDate": pd.to_datetime(["2025-02-01", "2025-02-15", "2025-03-01"])})

        repaired, changed = self.app.repair_history_row_counts_from_df(history, df)

        self.assertTrue(changed)
        self.assertEqual(repaired[0]["rows"], 3)

    def test_repairs_single_zero_history_row_count_without_charge_date_column(self):
        history = [{"file_name": "sales.csv", "pms": "VetPORT", "rows": 0}]
        df = pd.DataFrame({"Client Name": ["A", "B", "C", "D"]})

        repaired, changed = self.app.repair_history_row_counts_from_df(history, df)

        self.assertTrue(changed)
        self.assertEqual(repaired[0]["rows"], 4)

    def test_ensure_shared_dataset_loads_when_logged_session_lacks_dataframe(self):
        state = self.app.st.session_state
        state["clinic_id"] = "Clinic With Saved Data"
        state["dataset_upload_history"] = []
        state.pop("working_df", None)
        state.pop("_shared_dataset_load_attempted_for", None)

        with patch.object(self.app, "load_shared_dataset_for_clinic") as load_shared:
            self.app.ensure_shared_dataset_loaded_for_session()

        load_shared.assert_called_once()
        self.assertTrue(state["_shared_dataset_load_attempted_for"].startswith("Clinic With Saved Data:"))

    def test_saved_history_retries_shared_dataset_load_after_prior_empty_attempt(self):
        state = self.app.st.session_state
        state["clinic_id"] = "Clinic With Saved Data"
        state.pop("working_df", None)
        state["dataset_upload_history"] = []
        state["_shared_dataset_load_attempted_for"] = self.app.shared_dataset_load_attempt_token("Clinic With Saved Data")

        state["dataset_upload_history"] = [{"file_name": "sales.csv", "pms": "VetPORT", "rows": 56139}]

        with patch.object(self.app, "load_shared_dataset_for_clinic") as load_shared:
            self.app.ensure_shared_dataset_loaded_for_session()

        load_shared.assert_called_once()

    def test_shared_dataset_load_uses_fresh_pointer_row(self):
        headers = [
            "ClinicID",
            "PlainPassword",
            "SettingsJSON",
            "UpdatedAt",
            self.app.SHEET_COL_DATASET_FILE_ID,
            self.app.SHEET_COL_DATASET_FILE_NAME,
            self.app.SHEET_COL_DATASET_UPDATED_AT,
        ]
        state = self.app.st.session_state
        state["clinic_id"] = "Clinic With Saved Data"
        state["_settings_row_cache"] = {
            "clinic_key": "clinic with saved data",
            "headers": headers,
            "row_idx": 2,
            "row_values": ["Clinic With Saved Data", "", "{}", "", "", "", ""],
        }

        test_case = self

        class FakeSheet:
            def row_values(self, row_idx):
                test_case.assertEqual(row_idx, 2)
                return [
                    "Clinic With Saved Data",
                    "",
                    "{}",
                    "",
                    "fresh-drive-file-id",
                    "clinic_shared_dataset.csv",
                    "2026-05-15T16:00:00",
                ]

        loaded_df = pd.DataFrame(
            {
                "ChargeDate": pd.to_datetime(["2025-01-01"]),
                "Client Name": ["Client"],
                "Animal Name": ["Patient"],
                "Item Name": ["Item"],
                "Qty": [1],
                "Amount": [10],
            }
        )

        with (
            patch.object(self.app, "get_settings_sheet", return_value=FakeSheet()),
            patch.object(self.app, "drive_download_bytes", return_value=b"csv") as download,
            patch.object(self.app, "process_file", return_value=(loaded_df, "Canonical CSV", "Amount")),
        ):
            self.app.load_shared_dataset_for_clinic()

        download.assert_called_once_with("fresh-drive-file-id")
        self.assertIn("working_df", state)
        self.assertEqual(len(state["working_df"]), 1)
        self.assertEqual(state["_settings_row_cache"]["row_values"][4], "fresh-drive-file-id")


if __name__ == "__main__":
    unittest.main()
