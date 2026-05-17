import contextlib
import importlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import live_google_smoke_check


class GoogleResourceConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            cls.app = importlib.import_module("reminders_app_v3")

    def test_app_resource_ids_are_configured_with_nonempty_fallbacks(self):
        self.assertTrue(self.app.SETTINGS_SHEET_ID)
        self.assertTrue(self.app.DATASETS_FOLDER_ID)
        self.assertTrue(self.app.FEEDBACK_SHEET_ID)

        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(self.app.config_value("NEVER_SET_TEST_RESOURCE_ID", "default-id"), "default-id")

    def test_app_config_value_prefers_environment_override(self):
        with patch.dict(os.environ, {"SETTINGS_SHEET_ID": " env-settings-id "}, clear=False):
            self.assertEqual(self.app.config_value("SETTINGS_SHEET_ID", "default-id"), "env-settings-id")

    def test_production_redirect_uri_defaults_to_live_worksheet_suffix(self):
        secrets = {
            "auth": {
                "redirect_uri": "https://clinic-reminders.streamlit.app/oauth2callback",
            }
        }

        with patch.object(self.app.st, "secrets", secrets):
            self.assertEqual(self.app.default_worksheet_name_suffix(), "-live")
            self.assertEqual(
                self.app.config_value(
                    "WORKSHEET_NAME_SUFFIX",
                    self.app.default_worksheet_name_suffix(),
                ),
                "-live",
            )

    def test_nonproduction_redirect_uri_does_not_default_to_live_worksheet_suffix(self):
        secrets = {
            "auth": {
                "redirect_uri": "https://clinicreminders-dev.streamlit.app/oauth2callback",
            }
        }

        with patch.object(self.app.st, "secrets", secrets):
            self.assertEqual(self.app.default_worksheet_name_suffix(), "")

    def test_smoke_script_resource_id_uses_nested_streamlit_secrets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            secrets_path = Path(temp_dir) / "secrets.toml"
            secrets_path.write_text(
                '[google_resources]\nSETTINGS_SHEET_ID = "secret-settings-id"\nWORKSHEET_NAME_SUFFIX = "-live"\n',
                encoding="utf-8",
            )

            self.assertEqual(
                live_google_smoke_check.configured_resource_id(
                    "SETTINGS_SHEET_ID",
                    "default-id",
                    str(secrets_path),
                ),
                "secret-settings-id",
            )

            class Args:
                secrets_toml = str(secrets_path)

            live_google_smoke_check.apply_resource_config(Args())
            self.assertEqual(live_google_smoke_check.SETTINGS_WORKSHEET_NAME, "Clinic settings-live")
            self.assertIn("Action tracker-live", live_google_smoke_check.TRACKER_SHEETS)


if __name__ == "__main__":
    unittest.main()
