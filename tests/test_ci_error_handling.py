import contextlib
import importlib
import io
import unittest
from datetime import datetime
from unittest.mock import patch


class ErrorHandlingObservabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            cls.app = importlib.import_module("reminders_app_v3")

    def setUp(self):
        state = self.app.st.session_state
        for key in list(state.keys()):
            del state[key]

    def test_sanitize_diagnostic_message_redacts_common_secret_shapes(self):
        raw = (
            "failed password=hunter2 token=abc123 "
            "Authorization: Bearer ya29.this-token-should-not-survive "
            "remember=eyJjbGluaWNfaWQiOiJDbGluaWMgQSIsImV4cGlyZXNfYXQiOjE3OTAwMDAwMDB9 "
            "owner@example.com file 1AbCdEfGhIjKlMnOpQrStUv"
        )

        sanitized = self.app.sanitize_diagnostic_message(raw)

        self.assertIn("password=[redacted]", sanitized)
        self.assertIn("token=[redacted]", sanitized)
        self.assertIn("Authorization: Bearer [redacted]", sanitized)
        self.assertIn("remember=[redacted]", sanitized)
        self.assertIn("[redacted-email]", sanitized)
        self.assertNotIn("hunter2", sanitized)
        self.assertNotIn("abc123", sanitized)
        self.assertNotIn("ya29.this-token-should-not-survive", sanitized)
        self.assertNotIn("owner@example.com", sanitized)
        self.assertNotIn("1AbCdEfGhIjKlMnOpQrStUv", sanitized)

    def test_error_tracker_event_writes_sanitized_message_with_context(self):
        captured = {}

        def capture_append(title, headers, values):
            captured["title"] = title
            captured["headers"] = headers
            captured["values"] = values
            return True

        self.app.st.session_state["clinic_id"] = "Clinic Errors"
        self.app.st.session_state["user_name"] = "Support User"
        error = RuntimeError(
            'Drive failed for owner@example.com with {"password": "hunter2", "access_token": "secret-token"}'
        )

        with patch.object(self.app, "append_tracker_row", side_effect=capture_append):
            recorded = self.app.record_error_tracker_event(
                "drive_save_failed",
                stage="publish_dataset_for_clinic",
                error=error,
                source="test",
            )

        self.assertTrue(recorded)
        self.assertEqual(captured["title"], self.app.ERROR_TRACKER_WORKSHEET)
        row = dict(zip(captured["headers"], captured["values"]))
        self.assertEqual(row["ClinicID"], "Clinic Errors")
        self.assertEqual(row["YourNameClinic"], "Support User")
        self.assertEqual(row["Event"], "drive_save_failed")
        self.assertEqual(row["Stage"], "publish_dataset_for_clinic")
        self.assertEqual(row["ErrorType"], "RuntimeError")
        self.assertEqual(row["Source"], "test")
        self.assertIn("[redacted-email]", row["Message"])
        self.assertIn('"password": "[redacted]"', row["Message"])
        self.assertIn('"access_token": "[redacted]"', row["Message"])
        self.assertNotIn("owner@example.com", row["Message"])
        self.assertNotIn("hunter2", row["Message"])
        self.assertNotIn("secret-token", row["Message"])

    def test_dataset_and_performance_tracker_messages_are_sanitized(self):
        captured = []

        def capture_append(title, headers, values):
            captured.append((title, dict(zip(headers, values))))
            return True

        sensitive_message = (
            "Drive failed for owner@example.com file 1AbCdEfGhIjKlMnOpQrStUv "
            "access_token=secret-token"
        )

        with patch.object(self.app, "append_tracker_row", side_effect=capture_append):
            self.app.record_dataset_tracker_event(
                "upload_save_failed",
                "error",
                drive_file_id="1AbCdEfGhIjKlMnOpQrStUv",
                message=sensitive_message,
                source="test",
            )
            self.app.record_performance_tracker_event(
                "dataset_publish",
                123,
                status="error",
                message=sensitive_message,
                source="test",
            )

        dataset_row = captured[0][1]
        performance_row = captured[1][1]
        self.assertEqual(dataset_row["DriveFileId"], "[redacted]")
        for row in (dataset_row, performance_row):
            self.assertIn("[redacted-email]", row["Message"])
            self.assertIn("access_token=[redacted]", row["Message"])
            self.assertNotIn("owner@example.com", row["Message"])
            self.assertNotIn("1AbCdEfGhIjKlMnOpQrStUv", row["Message"])
            self.assertNotIn("secret-token", row["Message"])

    def test_slow_render_performance_is_thresholded_and_compact(self):
        with (
            patch.object(self.app.time, "perf_counter", return_value=10.5),
            patch.object(self.app, "record_performance_tracker_event") as record_performance,
        ):
            recorded = self.app.record_slow_render_performance(
                "stats_tab_render",
                started_at=10.0,
                rows=25,
                source="stats",
                threshold_ms=1000,
            )

        self.assertFalse(recorded)
        record_performance.assert_not_called()

        with (
            patch.object(self.app.time, "perf_counter", return_value=11.5),
            patch.object(self.app, "record_performance_tracker_event", return_value=True) as record_performance,
        ):
            recorded = self.app.record_slow_render_performance(
                "stats_tab_render",
                started_at=10.0,
                rows=25,
                source="stats",
                threshold_ms=1000,
            )

        self.assertTrue(recorded)
        record_performance.assert_called_once_with(
            "stats_tab_render",
            1500.0,
            rows=25,
            status="slow",
            message="phase=stats_tab_render",
            source="stats",
        )

    def test_dataset_tracker_batch_uses_one_append_rows_call(self):
        class FakeTrackerSheet:
            def __init__(self):
                self.append_rows_calls = 0
                self.append_row_calls = 0
                self.rows = []

            def append_rows(self, rows, value_input_option=None):
                self.append_rows_calls += 1
                self.rows.extend(rows)

            def append_row(self, row, value_input_option=None):
                self.append_row_calls += 1
                self.rows.append(row)

        sheet = FakeTrackerSheet()
        self.app.st.session_state["clinic_id"] = "Clinic A"
        self.app.st.session_state["user_name"] = "Tester"

        with (
            patch.object(self.app, "get_or_create_tracker_sheet", return_value=sheet),
            patch.object(self.app, "utc_now", return_value=datetime(2026, 5, 19, 12, 0, 0)),
        ):
            saved = self.app.record_dataset_tracker_events([
                {
                    "event": "upload_saved",
                    "status": "success",
                    "file_name": "jan.csv",
                    "pms": "Vetport",
                    "rows": 10,
                    "from_date": "2026-01-01",
                    "to_date": "2026-01-31",
                    "replace_overlapping_dates": False,
                    "drive_file_id": "file-1",
                    "drive_file_name": "Clinic A_shared_dataset.csv",
                    "source": "file_uploader",
                },
                {
                    "event": "upload_saved",
                    "status": "success",
                    "file_name": "feb.csv",
                    "pms": "Vetport",
                    "rows": 20,
                    "from_date": "2026-02-01",
                    "to_date": "2026-02-28",
                    "replace_overlapping_dates": False,
                    "drive_file_id": "file-1",
                    "drive_file_name": "Clinic A_shared_dataset.csv",
                    "source": "file_uploader",
                },
            ])

        self.assertTrue(saved)
        self.assertEqual(sheet.append_rows_calls, 1)
        self.assertEqual(sheet.append_row_calls, 0)
        self.assertEqual(len(sheet.rows), 2)

        records = [
            dict(zip(self.app.DATASET_TRACKER_HEADERS, row))
            for row in sheet.rows
        ]
        self.assertEqual([row["Event"] for row in records], ["upload_saved", "upload_saved"])
        self.assertEqual([row["FileName"] for row in records], ["jan.csv", "feb.csv"])
        self.assertEqual([row["Rows"] for row in records], ["10", "20"])
        self.assertEqual({row["Source"] for row in records}, {"file_uploader"})

    def test_tracking_sheet_ensure_reuses_verified_header_for_next_append(self):
        class FakeWorksheet:
            def __init__(self, title, headers):
                self.title = title
                self.headers = list(headers)
                self.row_values_calls = 0
                self.update_calls = 0
                self.append_row_calls = 0

            def row_values(self, row_idx):
                self.row_values_calls += 1
                return list(self.headers)

            def get_all_values(self):
                return [list(self.headers)]

            def update(self, values=None, range_name=None):
                self.update_calls += 1

            def append_row(self, row, value_input_option=None):
                self.append_row_calls += 1

        class FakeSpreadsheet:
            def __init__(self, worksheets_by_title):
                self.worksheets_by_title = worksheets_by_title
                self.worksheet_calls = 0

            def worksheets(self):
                return list(self.worksheets_by_title.values())

            def worksheet(self, title):
                self.worksheet_calls += 1
                return self.worksheets_by_title[title]

            def add_worksheet(self, title, rows, cols):
                worksheet = FakeWorksheet(title, [])
                self.worksheets_by_title[title] = worksheet
                return worksheet

        worksheets = {
            title: FakeWorksheet(title, headers)
            for title, headers in self.app.TRACKER_SHEET_DEFINITIONS
        }
        spreadsheet = FakeSpreadsheet(worksheets)
        dataset_sheet = worksheets[self.app.DATASET_TRACKER_WORKSHEET]
        self.app.st.session_state["clinic_id"] = "Clinic A"

        clear_cache = getattr(self.app.ensure_tracking_sheets_once, "clear", None)
        if callable(clear_cache):
            clear_cache()

        try:
            with patch.object(self.app, "get_settings_spreadsheet", return_value=spreadsheet):
                self.app.ensure_tracking_sheets()
                header_reads_after_ensure = dataset_sheet.row_values_calls
                saved = self.app.record_dataset_tracker_event("upload_saved", "success")
        finally:
            if callable(clear_cache):
                clear_cache()

        self.assertTrue(saved)
        self.assertEqual(header_reads_after_ensure, 1)
        self.assertEqual(dataset_sheet.row_values_calls, header_reads_after_ensure)
        self.assertEqual(spreadsheet.worksheet_calls, 0)
        self.assertEqual(dataset_sheet.append_row_calls, 1)

    def test_dataset_status_does_not_render_raw_load_exception_text(self):
        raw_error = "Drive failed for owner@example.com file 1AbCdEfGhIjKlMnOpQrStUv"
        self.app.st.session_state["shared_dataset_error"] = raw_error

        with (
            patch.object(self.app.st, "warning") as warning,
            patch.object(self.app.st, "caption"),
        ):
            self.app.render_dataset_status([])

        rendered = warning.call_args[0][0]
        self.assertIn("Could not load clinic data", rendered)
        self.assertNotIn("owner@example.com", rendered)
        self.assertNotIn("1AbCdEfGhIjKlMnOpQrStUv", rendered)

    def test_drive_download_http_error_does_not_render_response_content(self):
        class FakeResp:
            status = 403
            reason = "Forbidden"

        class FakeFiles:
            def get_media(self, **kwargs):
                return object()

        class FakeService:
            def files(self):
                return FakeFiles()

        class FailingDownloader:
            def __init__(self, *args, **kwargs):
                pass

            def next_chunk(self):
                raise self.app.HttpError(
                    FakeResp(),
                    b'{"error":"file 1AbCdEfGhIjKlMnOpQrStUv owner@example.com"}',
                )

        FailingDownloader.app = self.app

        with (
            patch.object(self.app, "get_drive_service", return_value=FakeService()),
            patch.object(self.app, "MediaIoBaseDownload", FailingDownloader),
            patch.object(self.app, "record_error_tracker_event") as record_error,
            patch.object(self.app.st, "error") as st_error,
            patch.object(self.app.st, "code") as st_code,
        ):
            with self.assertRaises(self.app.HttpError):
                self.app.drive_download_bytes("1AbCdEfGhIjKlMnOpQrStUv")

        st_error.assert_called_once_with("Drive download failed. Please try again or contact support.")
        st_code.assert_not_called()
        record_error.assert_called_once()

    def test_drive_download_timeout_records_sanitized_diagnostic(self):
        class FakeFiles:
            def get_media(self, **kwargs):
                return object()

        class FakeService:
            def files(self):
                return FakeFiles()

        class SlowDownloader:
            def __init__(self, *args, **kwargs):
                pass

            def next_chunk(self):
                return None, False

        with (
            patch.object(self.app, "get_drive_service", return_value=FakeService()),
            patch.object(self.app, "MediaIoBaseDownload", SlowDownloader),
            patch.object(self.app.time, "perf_counter", side_effect=[0.0, 0.5, 2.0]),
            patch.object(self.app, "record_error_tracker_event") as record_error,
            patch.object(self.app.st, "error") as st_error,
        ):
            with self.assertRaises(self.app.DriveTransferTimeoutError):
                self.app.drive_download_bytes("1AbCdEfGhIjKlMnOpQrStUv", timeout_seconds=1)

        st_error.assert_called_once_with("Drive download timed out. Please try again or contact support.")
        record_error.assert_called_once()
        _, kwargs = record_error.call_args
        self.assertEqual(kwargs["stage"], "drive_download_bytes")
        self.assertEqual(kwargs["source"], "drive_download_bytes")

    def test_drive_upload_timeout_records_sanitized_diagnostic(self):
        class SlowUploadRequest:
            def next_chunk(self):
                return None, None

        class FakeFiles:
            def create(self, **kwargs):
                return SlowUploadRequest()

        class FakeService:
            def files(self):
                return FakeFiles()

        with (
            patch.object(self.app, "get_drive_service", return_value=FakeService()),
            patch.object(self.app.time, "perf_counter", side_effect=[0.0, 0.5, 2.0]),
            patch.object(self.app, "record_error_tracker_event") as record_error,
        ):
            with self.assertRaises(self.app.DriveTransferTimeoutError):
                self.app.drive_upsert_csv_bytes(
                    b"ChargeDate,Client Name\n2025-01-01,Client A\n",
                    "clinic.csv",
                    "folder-id",
                    existing_file_id=None,
                    timeout_seconds=1,
                )

        record_error.assert_called_once()
        _, kwargs = record_error.call_args
        self.assertEqual(kwargs["stage"], "drive_upsert_csv_bytes")
        self.assertEqual(kwargs["source"], "drive_upsert_csv_bytes")

    def test_gspread_retry_returns_fast_success_with_elapsed_budget(self):
        with patch.object(self.app.time, "perf_counter", side_effect=[0.0, 0.1, 0.2]):
            result = self.app._gspread_retry(lambda: "ok", timeout_seconds=1)

        self.assertEqual(result, "ok")

    def test_gspread_retry_times_out_after_slow_successful_call(self):
        calls = []

        def slow_call():
            calls.append("called")
            return "late"

        with patch.object(self.app.time, "perf_counter", side_effect=[0.0, 0.5, 2.0]):
            with self.assertRaises(self.app.GoogleSheetsOperationTimeoutError):
                self.app._gspread_retry(slow_call, timeout_seconds=1)

        self.assertEqual(calls, ["called"])

    def test_gspread_retry_times_out_before_transient_retry_sleep(self):
        class FakeResponse:
            text = "quota"

            def json(self):
                return {
                    "error": {
                        "code": 503,
                        "message": "backend unavailable",
                        "status": "UNAVAILABLE",
                    }
                }

        calls = []

        def transient_failure():
            calls.append("called")
            raise self.app.APIError(FakeResponse())

        with (
            patch.object(self.app.time, "perf_counter", side_effect=[0.0, 0.1, 0.2, 1.2]),
            patch.object(self.app.time, "sleep") as sleep,
        ):
            with self.assertRaises(self.app.GoogleSheetsOperationTimeoutError):
                self.app._gspread_retry(transient_failure, timeout_seconds=1)

        self.assertEqual(calls, ["called"])
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
