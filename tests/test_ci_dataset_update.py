import contextlib
import hashlib
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
        self.assertEqual(html.count("column-help"), 3)
        self.assertIn("Checks that saved uploads use one recognized PMS/export format", html)
        self.assertIn("Checks that uploaded sales cover the dates needed", html)
        self.assertIn("Gaps of 3+ days can hide purchases", html)
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

    def test_saved_upload_history_repair_skips_summary_parse_when_history_exists(self):
        file_blobs = ({"name": "sales.csv", "bytes": b"csv"},)
        saved_history = [{"file_name": "sales.csv", "pms": "VetPORT", "rows": 10}]

        with patch.object(self.app, "summarize_uploads", side_effect=AssertionError("should not parse")):
            repaired = self.app.repair_saved_upload_history_if_missing(file_blobs, saved_history)

        self.assertFalse(repaired)

    def test_saved_upload_history_repair_preserves_missing_history_fallback(self):
        file_blobs = ({"name": "sales.csv", "bytes": b"csv"},)
        summary_rows = [{
            "File name": "sales.csv",
            "Rows": 10,
            "PMS": "VetPORT",
            "From": "01 Jan 2026",
            "To": "31 Jan 2026",
        }]

        with (
            patch.object(self.app, "summarize_uploads", return_value=([], summary_rows)) as summarize,
            patch.object(self.app, "repair_dataset_upload_history_from_rows", return_value=True) as repair,
        ):
            repaired = self.app.repair_saved_upload_history_if_missing(file_blobs, [])

        summarize.assert_called_once_with(file_blobs, self.app.UPLOAD_SUMMARY_SCHEMA_VERSION)
        repair.assert_called_once_with(summary_rows)
        self.assertTrue(repaired)

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
        self.assertIn("stage=drive_upload", tracker_events[0]["message"])
        self.assertIn("new_rows=1", tracker_events[0]["message"])
        self.assertIn("merged_rows=1", tracker_events[0]["message"])
        self.assertIn("new_df_bytes=", tracker_events[0]["message"])
        self.assertIn("merged_df_bytes=", tracker_events[0]["message"])
        self.assertIn("csv_bytes=", tracker_events[0]["message"])
        self.assertIn("stage=complete", tracker_events[1]["message"])
        self.assertIn("csv_bytes=", tracker_events[1]["message"])
        self.assertEqual(tracker_events[1]["drive_file_id"], "new-drive-file")

    def test_update_clinic_dataset_pointer_uses_cached_row_without_fresh_readback(self):
        headers = list(self.app.SETTINGS_REQUIRED_COLUMNS)
        dataset_file_id_col = self.app.SHEET_COL_DATASET_FILE_ID
        dataset_file_name_col = self.app.SHEET_COL_DATASET_FILE_NAME
        dataset_updated_at_col = self.app.SHEET_COL_DATASET_UPDATED_AT

        class FakeSettingsSheet:
            def __init__(self):
                self.get_all_values_calls = 0
                self.row_values_calls = 0
                self.batch_updates = []

            def get_all_values(self):
                self.get_all_values_calls += 1
                row_values = [""] * len(headers)
                row_values[headers.index("ClinicID")] = "Clinic A"
                row_values[headers.index("SettingsJSON")] = "{}"
                row_values[headers.index(dataset_file_id_col)] = "old-file"
                row_values[headers.index(dataset_file_name_col)] = "old.csv"
                row_values[headers.index(dataset_updated_at_col)] = "2026-05-01T00:00:00"
                return [
                    headers,
                    row_values,
                ]

            def row_values(self, row_idx):
                self.row_values_calls += 1
                raise AssertionError("pointer update should not re-read the row after a successful batch update")

            def batch_update(self, updates, **kwargs):
                self.batch_updates.append({"updates": updates, "kwargs": kwargs})

        sheet = FakeSettingsSheet()
        state = self.app.st.session_state
        state["clinic_id"] = "Clinic A"
        state["logged_in"] = True

        with (
            patch.object(self.app, "get_settings_sheet", return_value=sheet),
            patch.object(self.app, "_gspread_retry", side_effect=lambda fn, *args, **kwargs: fn(*args, **kwargs)),
            patch.object(self.app, "utc_now_iso", return_value="2026-05-19T12:00:00"),
        ):
            updated_at = self.app.update_clinic_dataset_pointer(
                "Clinic A",
                "new-file",
                "Clinic A_shared_dataset.csv",
            )

        self.assertEqual(updated_at, "2026-05-19T12:00:00")
        self.assertEqual(sheet.get_all_values_calls, 1)
        self.assertEqual(sheet.row_values_calls, 0)
        self.assertEqual(len(sheet.batch_updates), 1)
        self.assertEqual(
            state["_settings_row_cache"]["row_values"][headers.index(self.app.SHEET_COL_DATASET_FILE_ID)],
            "new-file",
        )
        self.assertEqual(
            state["_settings_row_cache"]["row_values"][headers.index(self.app.SHEET_COL_DATASET_FILE_NAME)],
            "Clinic A_shared_dataset.csv",
        )

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
            patch.object(self.app, "drive_trash_file") as trash_file,
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
        self.assertIn("cleanup=trashed_orphan_drive_file", tracker_events[1]["message"])
        trash_file.assert_called_once_with(
            "orphan-drive-file",
            clinic_id="Clinic A",
            current_file_id="orphan-drive-file",
        )

    def test_publish_dataset_does_not_trash_existing_file_when_pointer_update_fails(self):
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

        with (
            patch.object(self.app, "require_clinic_dataset_file_access"),
            patch.object(self.app, "load_existing_shared_df", return_value=pd.DataFrame()),
            patch.object(self.app, "record_dataset_tracker_event"),
            patch.object(self.app, "drive_upsert_csv_bytes", return_value="existing-drive-file"),
            patch.object(self.app, "update_clinic_dataset_pointer", side_effect=RuntimeError("sheet unavailable")),
            patch.object(self.app, "drive_trash_file") as trash_file,
        ):
            with self.assertRaisesRegex(RuntimeError, "sheet unavailable"):
                self.app.publish_dataset_for_clinic(
                    "Clinic A",
                    new_df,
                    "datasets-folder",
                    existing_file_id="existing-drive-file",
                    existing_name="clinic-a.csv",
                )

        trash_file.assert_not_called()

    def test_publish_dataset_fails_closed_when_existing_dataset_load_fails(self):
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

        with (
            patch.object(self.app, "require_clinic_dataset_file_access"),
            patch.object(self.app, "load_existing_shared_df", side_effect=RuntimeError("download failed")),
            patch.object(self.app, "drive_upsert_csv_bytes") as upsert,
            patch.object(self.app, "update_clinic_dataset_pointer") as update_pointer,
        ):
            with self.assertRaisesRegex(RuntimeError, "Could not load the saved clinic data"):
                self.app.publish_dataset_for_clinic(
                    "Clinic A",
                    new_df,
                    "datasets-folder",
                    existing_file_id="existing-drive-file",
                    existing_name="clinic-a.csv",
                )

        upsert.assert_not_called()
        update_pointer.assert_not_called()

    def test_publish_dataset_recovery_flag_allows_new_copy_when_existing_load_fails(self):
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

        with (
            patch.object(self.app, "require_clinic_dataset_file_access"),
            patch.object(self.app, "load_existing_shared_df", side_effect=RuntimeError("download failed")),
            patch.object(self.app, "drive_upsert_csv_bytes", return_value="new-drive-file") as upsert,
            patch.object(self.app, "update_clinic_dataset_pointer", return_value="2026-05-16T00:00:00") as update_pointer,
            patch.object(self.app, "record_dataset_tracker_event"),
        ):
            merged, file_id, filename = self.app.publish_dataset_for_clinic(
                "Clinic A",
                new_df,
                "datasets-folder",
                existing_file_id="existing-drive-file",
                existing_name="clinic-a.csv",
                allow_publish_without_existing_dataset=True,
            )

        self.assertEqual(len(merged), 1)
        self.assertEqual(file_id, "new-drive-file")
        self.assertEqual(filename, "Clinic A_shared_dataset.csv")
        upsert.assert_called_once()
        update_pointer.assert_called_once_with("Clinic A", "new-drive-file", "Clinic A_shared_dataset.csv")

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

    def test_remove_last_upload_clears_undated_leftover_rows(self):
        state = self.app.st.session_state
        for key in list(state.keys()):
            del state[key]
        state["clinic_id"] = "Clinic Remove Undated"
        state["logged_in"] = True
        state["dataset_upload_history"] = [
            {
                "file_name": "sample.csv",
                "pms": "Merlin",
                "rows": 1,
                "from": "2026-01-01",
                "to": "2026-01-01",
                "status": "Saved",
            }
        ]
        state["working_df"] = pd.DataFrame(
            {
                "ChargeDate": pd.to_datetime(["2026-01-01", None]),
                "Client Name": ["Client A", "Client B"],
                "Animal Name": ["Pet A", "Pet B"],
                "Item Name": ["Vaccination", "Clinical note residue"],
                "Qty": [1, 1],
                "Amount": [10, 0],
            }
        )

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
        self.assertEqual(self.app.get_saved_dataset_summary_rows(), [])

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

    def test_parse_dates_handles_excel_serial_dates(self):
        values = pd.Series(["46044.6958838773"])

        parsed = self.app.parse_dates(values)

        self.assertEqual(parsed.iloc[0].strftime("%Y-%m-%d"), "2026-01-22")

    def test_dataframe_to_csv_bytes_matches_existing_serialization(self):
        df = pd.DataFrame({
            "ChargeDate": pd.to_datetime(["2025-10-01", "2025-10-02"]),
            "Client Name": ["Client A", "Client, B"],
            "Animal Name": ["Pet A", "Pet B"],
            "Item Name": ["Rabies", "Dental\nExam"],
            "Amount": [10.5, None],
        })

        expected = df.to_csv(index=False).encode("utf-8")

        self.assertEqual(self.app.dataframe_to_csv_bytes(df), expected)

    def test_clear_upload_parse_caches_clears_cached_parse_function(self):
        with patch.object(self.app.process_file, "clear") as process_clear:
            self.app.clear_upload_parse_caches()

        process_clear.assert_called_once_with()
        self.assertFalse(hasattr(self.app.summarize_uploads, "clear"))

    def test_to_blob_stores_digest_and_size_with_file_bytes(self):
        class UploadedFile:
            name = "sales.csv"
            size = 12

            def getvalue(self):
                return b"csv contents"

        blob = self.app._to_blob(UploadedFile())

        self.assertEqual(blob["name"], "sales.csv")
        self.assertEqual(blob["bytes"], b"csv contents")
        self.assertEqual(blob["size"], len(b"csv contents"))
        self.assertEqual(blob["sha256"], hashlib.sha256(b"csv contents").hexdigest())

    def test_upload_fingerprint_uses_blob_digest_when_available(self):
        digest = hashlib.sha256(b"csv contents").hexdigest()
        first = self.app.upload_fingerprint(({
            "name": "sales.csv",
            "bytes": b"csv contents",
            "sha256": digest,
        },))
        same_digest_different_bytes = self.app.upload_fingerprint(({
            "name": "sales.csv",
            "bytes": b"different bytes",
            "sha256": digest,
        },))
        different_digest = self.app.upload_fingerprint(({
            "name": "sales.csv",
            "bytes": b"csv contents",
            "sha256": hashlib.sha256(b"changed contents").hexdigest(),
        },))

        self.assertEqual(first, same_digest_different_bytes)
        self.assertNotEqual(first, different_digest)

    def test_normalized_charge_dates_uses_datetime_fast_path(self):
        values = pd.Series(pd.to_datetime(["2025-09-30 13:45:00", "2025-10-01 08:15:00"]))

        with patch.object(self.app, "parse_dates", side_effect=AssertionError("datetime input should not reparse")):
            parsed = self.app.normalized_charge_dates(values)

        self.assertEqual(list(parsed.dt.strftime("%Y-%m-%d")), ["2025-09-30", "2025-10-01"])
        self.assertTrue((parsed.dt.hour == 0).all())

    def test_dataset_date_bounds_uses_datetime_fast_path(self):
        df = pd.DataFrame({
            "ChargeDate": pd.to_datetime(["2025-10-03 11:00:00", "2025-10-01 09:00:00"]),
        })

        with patch.object(self.app, "parse_dates", side_effect=AssertionError("datetime bounds should not reparse")):
            dmin, dmax = self.app.dataset_date_bounds(df)

        self.assertEqual(dmin, pd.Timestamp("2025-10-01"))
        self.assertEqual(dmax, pd.Timestamp("2025-10-03"))

    def test_process_file_prefers_canonical_charge_date_over_pms_looking_columns(self):
        csv_bytes = (
            "ChargeDate,Date,Client Name,Animal Name,Item Name,Qty,Amount\n"
            "30/09/2025,,Client A,Pet A,Rabies,1,100\n"
        ).encode("utf-8")

        df, pms_name, _amount_col = self.app.process_file(csv_bytes, "PatTest_shared_dataset.csv")

        self.assertEqual(pms_name, "Canonical CSV")
        self.assertEqual(df.loc[0, "ChargeDate"].strftime("%Y-%m-%d"), "2025-09-30")
        self.assertEqual(df.loc[0, "Client Name"], "Client A")

    def test_process_file_accepts_billed_date_canonical_alias(self):
        csv_bytes = (
            "Billed Date,Client Name,Animal Name,Item Name,Qty,Amount\n"
            "30/09/2025,Client A,Pet A,Rabies,1,100\n"
        ).encode("utf-8")

        df, pms_name, _amount_col = self.app.process_file(csv_bytes, "billed-date.csv")

        self.assertEqual(pms_name, "Canonical CSV")
        self.assertEqual(df.loc[0, "ChargeDate"].strftime("%Y-%m-%d"), "2025-09-30")

    def test_process_file_accepts_excel_serial_dates_across_pms_uploads(self):
        expected_date = "2026-02-21"
        cases = [
            (
                "canonical-serial.csv",
                "Billed Date,Client Name,Animal Name,Item Name,Qty,Amount\n"
                "46074,Client A,Pet A,Rabies,1,100\n",
                "Canonical CSV",
            ),
            (
                "vetport-serial.csv",
                "Planitem Performed,Client Name,Patient Name,Plan Item Name,Plan Item Quantity,Plan Item Amount\n"
                "46074,Client A,Pet A,Rabies,1,100\n",
                "VETport",
            ),
            (
                "xpress-serial.csv",
                "Date,Client ID,Client Name,SLNo,Doctor,Animal Name,Item Name,Item ID,Qty,Rate,Amount\n"
                "46074,C1,Client A,1,Dr A,Pet A,Rabies,I1,1,100,100\n",
                "Xpress",
            ),
            (
                "ezyvet-serial.csv",
                "Invoice Date,First Name,Last Name,Patient Name,Product Name,Qty,Total Invoiced (excl)\n"
                "46074,Client,A,Pet A,Rabies,1,100\n",
                "ezyVet",
            ),
            (
                "merlin-serial.csv",
                "Itemdate\tDescription\tAnimalName\tQty\tTotal\tSurname\tFirstName\tTreatmentDate\tCodeDescription\n"
                "46074\tProduct sale\tPet A\t1\t100\tA\tClient\t46074\tRabies\n",
                "Merlin",
            ),
        ]

        for filename, csv_text, expected_pms in cases:
            with self.subTest(pms=expected_pms):
                df, pms_name, _amount_col = self.app.process_file(csv_text.encode("utf-8"), filename)

                self.assertEqual(pms_name, expected_pms)
                self.assertEqual(len(df), 1)
                self.assertEqual(df.loc[0, "ChargeDate"].strftime("%Y-%m-%d"), expected_date)

    def test_process_file_preserves_utf8_bom_international_characters(self):
        csv_bytes = (
            "Billed Date,Client Name,Animal Name,Item Name,Qty,Amount\n"
            "20/05/2026,José García,قطرة,Rappel santé,1,100\n"
        ).encode("utf-8-sig")

        df, pms_name, _amount_col = self.app.process_file(csv_bytes, "international.csv")

        self.assertEqual(pms_name, "Canonical CSV")
        self.assertEqual(df.loc[0, "Client Name"], "José García")
        self.assertEqual(df.loc[0, "Animal Name"], "قطرة")
        self.assertEqual(df.loc[0, "Item Name"], "Rappel santé")

    def test_process_file_accepts_windows_1252_international_characters(self):
        csv_bytes = (
            "Billed Date,Client Name,Animal Name,Item Name,Qty,Amount\n"
            "20/05/2026,Chloë D’Arcy,Renée,Crème fraîche,1,100\n"
        ).encode("cp1252")

        df, pms_name, _amount_col = self.app.process_file(csv_bytes, "windows-1252.csv")

        self.assertEqual(pms_name, "Canonical CSV")
        self.assertEqual(df.loc[0, "Client Name"], "Chloë D’Arcy")
        self.assertEqual(df.loc[0, "Animal Name"], "Renée")
        self.assertEqual(df.loc[0, "Item Name"], "Crème fraîche")

    def test_dataframe_to_csv_bytes_preserves_international_characters(self):
        df = pd.DataFrame({
            "Client Name": ["José García", "ليلى منصور"],
            "Animal Name": ["Renée", "قطرة"],
            "Item Name": ["Crème fraîche", "تطعيم"],
        })

        exported = self.app.dataframe_to_csv_bytes(df).decode("utf-8")

        self.assertIn("José García", exported)
        self.assertIn("ليلى منصور", exported)
        self.assertIn("قطرة", exported)

    def test_process_file_accepts_merlin_tab_separated_csv(self):
        csv_bytes = (
            "Itemdate\tDescription\tAnimalName\tQty\tTotal\tSurname\tFirstName\tTreatmentDate\tCodeDescription\n"
            "46044.6958838773\tDiagnosis and Plan - simparica reminder note\tAlfie\t1\t0\tAaron\tSusan\t46044.5\t\n"
            "46044.6958838773\tLong product row text\tAlfie\t2\t123.45\tAaron\tSusan\t46044.5\tRabies Vaccination\n"
        ).encode("utf-8")

        df, pms_name, amount_col = self.app.process_file(csv_bytes, "merlin.csv")

        self.assertEqual(pms_name, "Merlin")
        self.assertEqual(amount_col, "Total")
        self.assertEqual(len(df), 1)
        self.assertEqual(df.loc[0, "ChargeDate"].strftime("%Y-%m-%d"), "2026-01-22")
        self.assertEqual(df.loc[0, "Client Name"], "Susan Aaron")
        self.assertEqual(df.loc[0, "Animal Name"], "Alfie")
        self.assertEqual(df.loc[0, "Item Name"], "Rabies Vaccination")
        self.assertEqual(df.loc[0, "Qty"], 2)
        self.assertEqual(df.loc[0, "Amount"], 123.45)

    def test_process_file_drops_pre_2000_artifact_dates(self):
        csv_bytes = (
            "ChargeDate,Client Name,Animal Name,Item Name,Qty,Amount\n"
            "30/12/1899,Artifact Client,Artifact Pet,Artifact Item,1,0\n"
            "22/01/2026,Client A,Pet A,Rabies,1,100\n"
        ).encode("utf-8")

        df, pms_name, _amount_col = self.app.process_file(csv_bytes, "artifact-date.csv")

        self.assertEqual(pms_name, "Canonical CSV")
        self.assertEqual(len(df), 1)
        self.assertEqual(df.loc[0, "Client Name"], "Client A")
        self.assertEqual(df.loc[0, "ChargeDate"].strftime("%Y-%m-%d"), "2026-01-22")

    def test_upload_validation_reports_billed_date_label(self):
        df = pd.DataFrame(
            {
                "Client Name": ["Client A"],
                "Animal Name": ["Pet A"],
                "Item Name": ["Rabies"],
            }
        )

        with self.assertRaises(self.app.UploadValidationError) as raised:
            self.app.validate_upload_dataframe(df, "missing-date.csv")

        message = str(raised.exception)
        self.assertIn("Billed Date", message)
        self.assertNotIn("ChargeDate", message)

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
