import contextlib
import importlib
import io
import json
import unittest
from unittest.mock import patch


class FakeSettingsSheet:
    def __init__(self, remote_settings):
        self.remote_settings = remote_settings

    def row_values(self, row_idx):
        return [
            "Clinic Save State",
            "",
            "",
            json.dumps(self.remote_settings),
            "2026-05-15T00:00:00",
        ]


class SettingsSaveStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            cls.app = importlib.import_module("reminders_app_v3")

    def setUp(self):
        state = self.app.st.session_state
        for key in list(state.keys()):
            del state[key]
        state["clinic_id"] = "Clinic Save State"

    def run_save_with_remote(self, remote_settings):
        headers = ["ClinicID", "PlainPassword", "PasswordHash", "SettingsJSON", "UpdatedAt"]
        sheet = FakeSettingsSheet(remote_settings)
        captured = {}

        def capture_settings_update(sheet, headers, row_idx, settings_json, updated_at):
            captured["settings"] = json.loads(settings_json)

        with (
            patch.object(self.app, "_get_settings_row_for_clinic", return_value=(sheet, headers, 2)),
            patch.object(self.app, "_update_settings_cells", side_effect=capture_settings_update),
        ):
            self.app.save_settings(track_user=False)

        return captured["settings"]

    def test_save_settings_preserves_remote_search_terms_from_other_computers(self):
        base_settings = {
            "rules": {"rabies": {"days": 365, "use_qty": False}},
            "exclusions": ["old"],
            "client_exclusions": [],
            "patient_exclusions": [],
        }
        remote_settings = {
            "rules": {
                "rabies": {"days": 365, "use_qty": False},
                "librela": {"days": 30, "use_qty": False},
            },
            "exclusions": ["old", "remote-only"],
            "client_exclusions": [],
            "patient_exclusions": [],
        }
        self.app.cache_remote_settings("Clinic Save State", base_settings)
        self.app.st.session_state["rules"] = {"rabies": {"days": 400, "use_qty": False}}
        self.app.st.session_state["exclusions"] = ["old", "local-only"]

        saved = self.run_save_with_remote(remote_settings)

        self.assertEqual(saved["rules"]["rabies"]["days"], 400)
        self.assertEqual(saved["rules"]["librela"]["days"], 30)
        self.assertEqual(saved["exclusions"], ["old", "remote-only", "local-only"])

    def test_undo_reminder_action_removes_one_key_without_dropping_remote_actions(self):
        hidden_a = {
            "Client Name": "Client A",
            "Animal Name": "Pet A",
            "Plan Item": "Rabies",
            "Due Date": "01 Jun 2026",
            "Reminder Date": "01 Jun 2026",
            "Action": "sent",
            "ActionedAt": "2026-05-15T10:00:00",
        }
        hidden_b = {
            "Client Name": "Client B",
            "Animal Name": "Pet B",
            "Plan Item": "Librela",
            "Due Date": "02 Jun 2026",
            "Reminder Date": "02 Jun 2026",
            "Action": "sent",
            "ActionedAt": "2026-05-15T11:00:00",
        }
        wa_a = {
            "Client Name": "Client A",
            "RemindedAt": "2026-05-15T10:00:00",
            "ReminderKey": list(self.app.hidden_reminder_key(hidden_a)),
        }
        wa_b = {
            "Client Name": "Client B",
            "RemindedAt": "2026-05-15T11:00:00",
            "ReminderKey": list(self.app.hidden_reminder_key(hidden_b)),
        }
        base_settings = {
            "rules": {},
            "deleted_reminders": [hidden_a],
            "wa_reminder_log": [wa_a],
        }
        remote_settings = {
            "rules": {},
            "deleted_reminders": [hidden_a, hidden_b],
            "wa_reminder_log": [wa_a, wa_b],
        }
        self.app.cache_remote_settings("Clinic Save State", base_settings)
        self.app.st.session_state["deleted_reminders"] = [hidden_a]
        self.app.st.session_state["wa_reminder_log"] = [wa_a]

        self.app.remove_actioned_reminder(hidden_a)
        self.app.remove_wa_reminder_click_for_row(hidden_a)
        saved = self.run_save_with_remote(remote_settings)

        hidden_keys = {self.app.hidden_reminder_key(entry) for entry in saved["deleted_reminders"]}
        wa_keys = {tuple(entry.get("ReminderKey", [])) for entry in saved["wa_reminder_log"]}
        self.assertNotIn(self.app.hidden_reminder_key(hidden_a), hidden_keys)
        self.assertIn(self.app.hidden_reminder_key(hidden_b), hidden_keys)
        self.assertNotIn(tuple(wa_a["ReminderKey"]), wa_keys)
        self.assertIn(tuple(wa_b["ReminderKey"]), wa_keys)


if __name__ == "__main__":
    unittest.main()
