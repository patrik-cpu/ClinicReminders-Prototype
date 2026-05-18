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

    def test_dataset_summary_checks_html_renders_three_status_boxes(self):
        rows = [
            {
                "file_name": "full-year.csv",
                "pms": "VetPORT",
                "rows": 100,
                "from": "2025-01-01",
                "to": "2025-12-31",
                "status": "Saved",
            }
        ]

        with patch.object(self.app, "user_today", return_value=pd.Timestamp("2026-01-01").date()):
            html = self.app.dataset_summary_checks_html(rows)

        self.assertIn("dataset-check-grid", html)
        self.assertEqual(html.count("dataset-check "), 3)
        self.assertIn("Same supported PMS", html)
        self.assertIn("30-365 day reminder window covered", html)
        self.assertIn("No 3+ day gaps between uploads", html)
        self.assertEqual(html.count("dataset-check good"), 3)

    def test_upload_data_badge_matches_failed_dataset_checks(self):
        rows = [
            {
                "file_name": "stale-monthly.csv",
                "pms": "VetPORT",
                "rows": 100,
                "from": "2025-05-31",
                "to": "2026-05-01",
                "status": "Saved",
            }
        ]

        with patch.object(self.app, "user_today", return_value=pd.Timestamp("2026-05-31").date()):
            self.assertEqual(self.app.dataset_summary_issue_count(rows), 1)
            label = self.app.upload_data_badge_label(count=self.app.dataset_summary_issue_count(rows))

        self.assertIn("Upload Data", label)
        self.assertIn("1 upload data checks need attention", label)
        self.assertIn("data:image/svg+xml;base64", label)

    def test_dataset_coverage_turns_red_on_day_30_since_last_upload(self):
        rows = [
            {
                "file_name": "monthly.csv",
                "pms": "VetPORT",
                "rows": 100,
                "from": "2025-05-31",
                "to": "2026-05-01",
                "status": "Saved",
            }
        ]

        with patch.object(self.app, "user_today", return_value=pd.Timestamp("2026-05-31").date()):
            checks = self.app.dataset_summary_checks(rows)

        self.assertFalse(checks[1]["good"])
        self.assertEqual(checks[1]["text"], "30-365 day reminder window needs data")

    def test_upload_data_badge_clears_when_dataset_checks_are_green(self):
        rows = [
            {
                "file_name": "fresh-monthly.csv",
                "pms": "VetPORT",
                "rows": 100,
                "from": "2025-05-31",
                "to": "2026-05-02",
                "status": "Saved",
            }
        ]

        with patch.object(self.app, "user_today", return_value=pd.Timestamp("2026-05-31").date()):
            self.assertEqual(self.app.dataset_summary_issue_count(rows), 0)
            self.assertEqual(self.app.upload_data_badge_label(count=0), "Upload Data")

    def test_dataset_saved_summary_shows_total_rows_and_date_range(self):
        summary = self.app.format_dataset_saved_summary(
            54489,
            pd.Timestamp("2024-01-01"),
            pd.Timestamp("2025-09-30"),
        )

        self.assertIn("**Total rows:** 54,489", summary)
        self.assertIn("**Total date range (all uploads):** 01 Jan 2024 → 30 Sep 2025", summary)
        self.assertNotIn("duplicate rows are ignored", summary)

    def test_saved_upload_key_does_not_skip_save_when_history_is_missing(self):
        self.assertFalse(
            self.app.upload_save_can_be_skipped(
                "upload-key",
                "upload-key",
                [],
            )
        )
        self.assertFalse(
            self.app.upload_save_can_be_skipped(
                "upload-key",
                "",
                [{"file_name": "sales.csv", "rows": 10}],
            )
        )
        self.assertTrue(
            self.app.upload_save_can_be_skipped(
                "upload-key",
                "upload-key",
                [{"file_name": "sales.csv", "rows": 10}],
            )
        )

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

    def test_publish_dataset_records_repairable_operation_success(self):
        state = self.app.st.session_state
        state["clinic_id"] = "Clinic A"
        state["logged_in"] = True
        new_df = pd.DataFrame(
            {
                "ChargeDate": pd.to_datetime(["2025-01-01"]),
                "Client Name": ["Client A"],
                "Animal Name": ["Pet A"],
                "Item Name": ["Rabies"],
            }
        )
        call_order = []
        tracker_events = []

        def capture_tracker(event, status, **kwargs):
            tracker_events.append({"event": event, "status": status, **kwargs})
            call_order.append(f"tracker:{status}")
            return True

        def drive_upload(**kwargs):
            call_order.append("drive")
            return "new-drive-file"

        def update_pointer(clinic_id, file_id, filename):
            call_order.append("pointer")
            return "2026-05-16T00:00:00"

        with (
            patch.object(self.app, "make_dataset_publish_operation_id", return_value="op-123"),
            patch.object(self.app, "record_dataset_tracker_event", side_effect=capture_tracker),
            patch.object(self.app, "drive_upsert_csv_bytes", side_effect=drive_upload),
            patch.object(self.app, "update_clinic_dataset_pointer", side_effect=update_pointer),
        ):
            merged, file_id, filename = self.app.publish_dataset_for_clinic(
                "Clinic A",
                new_df,
                "datasets-folder",
                existing_file_id="",
                existing_name="",
                existing_df=pd.DataFrame(),
            )

        self.assertEqual(file_id, "new-drive-file")
        self.assertEqual(filename, "Clinic A_shared_dataset.csv")
        self.assertEqual(len(merged), 1)
        self.assertEqual(call_order, ["tracker:started", "drive", "pointer", "tracker:success"])
        self.assertEqual([event["status"] for event in tracker_events], ["started", "success"])
        self.assertEqual({event["operation_id"] for event in tracker_events}, {"op-123"})
        self.assertEqual(tracker_events[0]["message"], "stage=drive_upload")
        self.assertEqual(tracker_events[1]["message"], "stage=complete")
        self.assertEqual(tracker_events[1]["drive_file_id"], "new-drive-file")

    def test_publish_dataset_records_pointer_update_failure_with_uploaded_file_id(self):
        state = self.app.st.session_state
        state["clinic_id"] = "Clinic A"
        state["logged_in"] = True
        new_df = pd.DataFrame(
            {
                "ChargeDate": pd.to_datetime(["2025-01-01"]),
                "Client Name": ["Client A"],
                "Animal Name": ["Pet A"],
                "Item Name": ["Rabies"],
            }
        )
        tracker_events = []

        def capture_tracker(event, status, **kwargs):
            tracker_events.append({"event": event, "status": status, **kwargs})
            return True

        with (
            patch.object(self.app, "make_dataset_publish_operation_id", return_value="op-456"),
            patch.object(self.app, "record_dataset_tracker_event", side_effect=capture_tracker),
            patch.object(self.app, "drive_upsert_csv_bytes", return_value="orphan-drive-file"),
            patch.object(self.app, "update_clinic_dataset_pointer", side_effect=RuntimeError("sheet unavailable")),
        ):
            with self.assertRaisesRegex(RuntimeError, "sheet unavailable"):
                self.app.publish_dataset_for_clinic(
                    "Clinic A",
                    new_df,
                    "datasets-folder",
                    existing_file_id="",
                    existing_name="",
                    existing_df=pd.DataFrame(),
                )

        self.assertEqual([event["status"] for event in tracker_events], ["started", "error"])
        self.assertEqual({event["operation_id"] for event in tracker_events}, {"op-456"})
        self.assertEqual(tracker_events[1]["drive_file_id"], "orphan-drive-file")
        self.assertIn("stage=settings_pointer_update", tracker_events[1]["message"])

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
        state["logged_in"] = True
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

    def test_remove_last_upload_clears_stale_uploader_selection(self):
        state = self.app.st.session_state
        for key in list(state.keys()):
            del state[key]
        state["clinic_id"] = "Clinic Remove Last"
        state["logged_in"] = True
        state["dataset_upload_history"] = [
            {
                "file_name": "sample.csv",
                "pms": "CSV",
                "rows": 1,
                "from": "2025-01-01",
                "to": "2025-01-01",
                "status": "Saved",
            }
        ]
        state["working_df"] = pd.DataFrame(
            {
                "ChargeDate": pd.to_datetime(["2025-01-01"]),
                "Client Name": ["Client A"],
                "Animal Name": ["Pet A"],
                "Item Name": ["Rabies"],
                "Qty": [1],
                "Amount": [10],
            }
        )
        state["file_uploader_main_3"] = ["sample.csv"]
        state["file_uploader_reset_version"] = 3
        state["last_uploaded_files"] = ["sample.csv"]
        state["last_saved_upload_key"] = "saved-key"

        with (
            patch.object(self.app, "get_existing_dataset_pointer", return_value=("file-id", "clinic_shared_dataset.csv")),
            patch.object(self.app, "clear_clinic_dataset_pointer"),
            patch.object(self.app, "save_settings_quietly", return_value=True),
            patch.object(self.app, "record_dataset_tracker_event"),
        ):
            self.app.remove_dataset_upload_at_index(0)

        self.assertEqual(state["dataset_upload_history"], [])
        self.assertFalse(state["shared_dataset_loaded"])
        self.assertNotIn("working_df", state)
        self.assertNotIn("file_uploader_main_3", state)
        self.assertEqual(state["last_uploaded_files"], [])
        self.assertNotIn("last_saved_upload_key", state)
        self.assertGreater(state["file_uploader_reset_version"], 3)

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
        state["logged_in"] = True
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
        state["logged_in"] = True
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
        state["logged_in"] = True
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

        download.assert_called_once_with(
            "fresh-drive-file-id",
            clinic_id="Clinic With Saved Data",
            current_file_id="fresh-drive-file-id",
        )
        self.assertIn("working_df", state)
        self.assertEqual(len(state["working_df"]), 1)
        self.assertEqual(state["_settings_row_cache"]["row_values"][4], "fresh-drive-file-id")


if __name__ == "__main__":
    unittest.main()
