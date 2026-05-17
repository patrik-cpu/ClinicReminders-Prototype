import contextlib
import importlib
import io
import unittest
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


if __name__ == "__main__":
    unittest.main()
