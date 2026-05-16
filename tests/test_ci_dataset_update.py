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

    def test_overlapping_upload_dedupes_by_billed_item_identity(self):
        existing = pd.DataFrame(
            {
                "ChargeDate": pd.to_datetime(["2025-01-01"] * 10),
                "Client Name": ["Owner A"] * 10,
                "Animal Name": ["Pet A"] * 10,
                "Item Name": [f"Item {idx:02d}" for idx in range(10)],
                "Amount": list(range(10)),
            }
        )
        new = pd.DataFrame(
            {
                "ChargeDate": pd.to_datetime(["2025-01-01"] * 25),
                "Client Name": ["Owner A"] * 25,
                "Animal Name": ["Pet A"] * 25,
                "Item Name": [f"Item {idx:02d}" for idx in range(25)],
                "Amount": [100 + idx for idx in range(25)],
            }
        )

        merged = self.app.merge_dataset_update(existing, new, replace_overlapping_dates=False)

        self.assertEqual(len(merged), 25)
        self.assertEqual(set(merged["Item Name"]), {f"Item {idx:02d}" for idx in range(25)})
        self.assertEqual(
            int(merged.loc[merged["Item Name"] == "Item 00", "Amount"].iloc[0]),
            100,
        )

    def test_single_upload_dedupes_exact_billed_item_identity(self):
        new = pd.DataFrame(
            {
                "ChargeDate": pd.to_datetime(["2025-01-01", "2025-01-01", "2025-01-01"]),
                "Client Name": ["Owner A", "owner  a", "Owner A"],
                "Animal Name": ["Pet A", "Pet A", "Pet B"],
                "Item Name": ["Rabies", " rabies ", "Rabies"],
                "Amount": [10, 20, 30],
            }
        )

        merged = self.app.merge_dataset_update(None, new)

        self.assertEqual(len(merged), 2)
        self.assertEqual(
            int(merged.loc[merged["Animal Name"] == "Pet A", "Amount"].iloc[0]),
            20,
        )

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

    def test_valid_csv_upload_history_does_not_need_metadata_repair(self):
        history = [
            {
                "file_name": "january.csv",
                "pms": "CSV",
                "rows": 100,
                "from": "2025-01-01",
                "to": "2025-01-31",
                "status": "Saved",
            }
        ]

        self.assertFalse(self.app.dataset_history_needs_metadata_repair(history))

    def test_upload_history_appends_new_csv_row_without_dropping_existing(self):
        existing = [
            {
                "file_name": "january.csv",
                "pms": "CSV",
                "rows": 100,
                "from": "2025-01-01",
                "to": "2025-01-31",
                "status": "Saved",
            }
        ]
        incoming = [
            {
                "file_name": "february.csv",
                "pms": "CSV",
                "rows": 120,
                "from": "2025-02-01",
                "to": "2025-02-28",
                "status": "Saved",
            }
        ]

        merged = self.app.merge_dataset_upload_history(
            existing,
            incoming,
            replace_overlapping_dates=False,
            upload_min=pd.Timestamp("2025-02-01"),
            upload_max=pd.Timestamp("2025-02-28"),
        )

        self.assertEqual([row["file_name"] for row in merged], ["january.csv", "february.csv"])

    def test_upload_history_keeps_overlapping_rows_when_saved_as_additional(self):
        existing = [
            {
                "file_name": "january.csv",
                "pms": "CSV",
                "rows": 100,
                "from": "2025-01-01",
                "to": "2025-01-31",
                "status": "Saved",
            }
        ]
        incoming = [
            {
                "file_name": "january-extra.csv",
                "pms": "CSV",
                "rows": 50,
                "from": "2025-01-15",
                "to": "2025-01-20",
                "status": "Saved",
            }
        ]

        merged = self.app.merge_dataset_upload_history(
            existing,
            incoming,
            replace_overlapping_dates=False,
            upload_min=pd.Timestamp("2025-01-15"),
            upload_max=pd.Timestamp("2025-01-20"),
        )

        self.assertEqual([row["file_name"] for row in merged], ["january.csv", "january-extra.csv"])

    def test_upload_history_collapses_exact_duplicate_rows(self):
        existing = [
            {
                "file_name": "january.csv",
                "pms": "CSV",
                "rows": 100,
                "from": "2025-01-01",
                "to": "2025-01-31",
                "status": "Saved",
            }
        ]
        incoming = [
            {
                "file_name": "january.csv",
                "pms": "CSV",
                "rows": 100,
                "from": "2025-01-01",
                "to": "2025-01-31",
                "status": "Saved",
            }
        ]

        merged = self.app.merge_dataset_upload_history(
            existing,
            incoming,
            replace_overlapping_dates=False,
            upload_min=pd.Timestamp("2025-01-01"),
            upload_max=pd.Timestamp("2025-01-31"),
        )

        self.assertEqual([row["file_name"] for row in merged], ["january.csv"])

    def test_upload_history_detects_row_that_overlaps_another_upload(self):
        rows = [
            {
                "file_name": "january-partial.csv",
                "pms": "CSV",
                "rows": 10,
                "from": "2025-01-01",
                "to": "2025-01-01",
                "status": "Saved",
            },
            {
                "file_name": "january-full.csv",
                "pms": "CSV",
                "rows": 25,
                "from": "2025-01-01",
                "to": "2025-01-01",
                "status": "Saved",
            },
            {
                "file_name": "february.csv",
                "pms": "CSV",
                "rows": 20,
                "from": "2025-02-01",
                "to": "2025-02-28",
                "status": "Saved",
            },
        ]

        self.assertTrue(self.app.dataset_history_row_overlaps_other(rows, 0))
        self.assertTrue(self.app.dataset_history_row_overlaps_other(rows, 1))
        self.assertFalse(self.app.dataset_history_row_overlaps_other(rows, 2))

    def test_remove_overlapping_upload_keeps_rows_covered_by_remaining_history(self):
        state = self.app.st.session_state
        for key in list(state.keys()):
            del state[key]
        state["clinic_id"] = "Clinic Save State"
        state["dataset_upload_history"] = [
            {
                "file_name": "january-partial.csv",
                "pms": "CSV",
                "rows": 1,
                "from": "2025-01-01",
                "to": "2025-01-01",
                "status": "Saved",
            },
            {
                "file_name": "january-full.csv",
                "pms": "CSV",
                "rows": 2,
                "from": "2025-01-01",
                "to": "2025-01-31",
                "status": "Saved",
            },
        ]
        state["working_df"] = pd.DataFrame(
            {
                "ChargeDate": pd.to_datetime(["2025-01-01", "2025-01-15"]),
                "Client Name": ["Client A", "Client B"],
                "Animal Name": ["Pet A", "Pet B"],
                "Item Name": ["Rabies", "Dental"],
                "Qty": [1, 1],
                "Amount": [10, 20],
            }
        )

        with (
            patch.object(self.app, "get_existing_dataset_pointer", return_value=("file-id", "clinic_shared_dataset.csv")),
            patch.object(self.app, "drive_upsert_csv_bytes", return_value="file-id"),
            patch.object(self.app, "update_clinic_dataset_pointer", return_value="2026-05-16T00:00:00"),
            patch.object(self.app, "save_settings_quietly", return_value=True),
            patch.object(self.app, "record_dataset_tracker_event"),
        ):
            self.app.remove_dataset_upload_at_index(0)

        self.assertEqual(
            [row["file_name"] for row in state["dataset_upload_history"]],
            ["january-full.csv"],
        )
        self.assertEqual(len(state["working_df"]), 2)

    def test_upload_history_drops_overlapping_rows_when_replacing_dates(self):
        existing = [
            {
                "file_name": "january.csv",
                "pms": "CSV",
                "rows": 100,
                "from": "2025-01-01",
                "to": "2025-01-31",
                "status": "Saved",
            },
            {
                "file_name": "february.csv",
                "pms": "CSV",
                "rows": 120,
                "from": "2025-02-01",
                "to": "2025-02-28",
                "status": "Saved",
            },
        ]
        incoming = [
            {
                "file_name": "january-corrected.csv",
                "pms": "CSV",
                "rows": 95,
                "from": "2025-01-01",
                "to": "2025-01-31",
                "status": "Saved",
            }
        ]

        merged = self.app.merge_dataset_upload_history(
            existing,
            incoming,
            replace_overlapping_dates=True,
            upload_min=pd.Timestamp("2025-01-01"),
            upload_max=pd.Timestamp("2025-01-31"),
        )

        self.assertEqual([row["file_name"] for row in merged], ["february.csv", "january-corrected.csv"])

    def test_simplify_vaccine_text_handles_generic_vaccine_terms(self):
        self.assertEqual(self.app.simplify_vaccine_text("Vaccine"), "Vaccine")
        self.assertEqual(self.app.simplify_vaccine_text("Vaccination, Vaccine"), "Vaccine")

    def test_parse_dates_handles_dayfirst_and_iso_saved_dates(self):
        values = pd.Series(["30/09/2025", "2025-10-01", "01/Sep/2025"])

        parsed = self.app.parse_dates(values)

        self.assertEqual(list(parsed.dt.strftime("%Y-%m-%d")), ["2025-09-30", "2025-10-01", "2025-09-01"])

    def test_process_file_prefers_canonical_charge_date_over_pms_looking_columns(self):
        csv_bytes = (
            "ChargeDate,Date,Client Name,Animal Name,Item Name,Qty,Amount\n"
            "30/09/2025,,Client A,Pet A,Rabies,1,100\n"
        ).encode("utf-8")

        df, pms_name, _amount_col = self.app.process_file(csv_bytes, "PatTest_shared_dataset.csv")

        self.assertEqual(pms_name, "Canonical CSV")
        self.assertEqual(df.loc[0, "ChargeDate"].strftime("%Y-%m-%d"), "2025-09-30")
        self.assertEqual(df.loc[0, "Client Name"], "Client A")

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
