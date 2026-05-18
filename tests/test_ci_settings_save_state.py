import contextlib
import importlib
import io
import json
import unittest
from unittest.mock import patch

from requests import Response


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


class FailingSettingsSheet(FakeSettingsSheet):
    def row_values(self, row_idx):
        raise TimeoutError("network timeout")


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

    def test_quiet_save_refreshes_remote_by_default_to_avoid_stale_overwrite(self):
        base_settings = {
            "rules": {"rabies": {"days": 365, "use_qty": False}},
            "exclusions": ["old"],
        }
        remote_settings = {
            "rules": {
                "rabies": {"days": 365, "use_qty": False},
                "librela": {"days": 30, "use_qty": False},
            },
            "exclusions": ["old", "remote-only"],
        }
        headers = ["ClinicID", "PlainPassword", "PasswordHash", "SettingsJSON", "UpdatedAt"]
        sheet = FakeSettingsSheet(remote_settings)
        captured = {}

        def capture_settings_update(sheet, headers, row_idx, settings_json, updated_at):
            captured["settings"] = json.loads(settings_json)

        self.app.cache_remote_settings("Clinic Save State", base_settings)
        self.app.st.session_state["rules"] = {"rabies": {"days": 400, "use_qty": False}}
        self.app.st.session_state["exclusions"] = ["old", "local-only"]

        with (
            patch.object(self.app, "_get_settings_row_for_clinic", return_value=(sheet, headers, 2)),
            patch.object(self.app, "_update_settings_cells", side_effect=capture_settings_update),
        ):
            saved = self.app.save_settings_quietly()

        self.assertTrue(saved)
        self.assertEqual(captured["settings"]["rules"]["rabies"]["days"], 400)
        self.assertEqual(captured["settings"]["rules"]["librela"]["days"], 30)
        self.assertEqual(captured["settings"]["exclusions"], ["old", "remote-only", "local-only"])

    def test_quiet_save_can_still_skip_remote_refresh_for_internal_migration_paths(self):
        with patch.object(self.app, "save_settings") as save_settings:
            self.app.save_settings_quietly(refresh_remote=False)

        save_settings.assert_called_once_with(track_user=False, refresh_remote=False)

    def test_quiet_save_blocks_stale_overwrite_when_fresh_remote_read_fails(self):
        headers = ["ClinicID", "PlainPassword", "PasswordHash", "SettingsJSON", "UpdatedAt"]
        sheet = FailingSettingsSheet({"rules": {"remote-only": {"days": 30, "use_qty": False}}})

        self.app.cache_remote_settings(
            "Clinic Save State",
            {"rules": {"old-base": {"days": 365, "use_qty": False}}},
        )
        self.app.st.session_state["rules"] = {"local-change": {"days": 90, "use_qty": False}}

        with (
            patch.object(self.app, "_get_settings_row_for_clinic", return_value=(sheet, headers, 2)),
            patch.object(self.app, "_update_settings_cells") as update_settings_cells,
        ):
            saved = self.app.save_settings_quietly()

        self.assertFalse(saved)
        update_settings_cells.assert_not_called()
        self.assertIn("could not be checked", self.app.st.session_state["_pending_settings_sync_warning"])

    def test_save_settings_does_not_persist_action_logs(self):
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

        self.assertNotIn("deleted_reminders", saved)
        self.assertNotIn("wa_reminder_log", saved)

    def test_save_settings_persists_reminder_lookback_days(self):
        self.app.cache_remote_settings("Clinic Save State", {})
        self.app.st.session_state["reminder_lookback_days"] = 7

        saved = self.run_save_with_remote({})

        self.assertEqual(saved["reminder_lookback_days"], 7)

    def test_quiet_settings_save_handles_sheets_api_error(self):
        response = Response()
        response.status_code = 429
        response._content = json.dumps({
            "error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}
        }).encode("utf-8")

        with patch.object(self.app, "save_settings", side_effect=self.app.APIError(response)):
            saved = self.app.save_settings_quietly()

        self.assertFalse(saved)
        self.assertIn("Google Sheets was busy", self.app.st.session_state["_pending_settings_sync_warning"])

    def test_action_tracker_reduce_keeps_other_actions_when_one_is_undone(self):
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
        undo_a = dict(hidden_a, Action="active", ActionedAt="2026-05-15T12:00:00")

        reduced = self.app.reduce_action_tracker_records([hidden_a, hidden_b, undo_a])

        hidden_keys = {self.app.hidden_reminder_key(entry) for entry in reduced}
        self.assertNotIn(self.app.hidden_reminder_key(hidden_a), hidden_keys)
        self.assertIn(self.app.hidden_reminder_key(hidden_b), hidden_keys)

    def test_action_tracker_row_preserves_sent_message(self):
        row = {
            "Client Name": "Client A",
            "Animal Name": "Pet A",
            "Plan Item": "Rabies",
            "Reminder Date": "01 Jun 2026",
            "Due Date": "01 Jun 2026",
            "Charge Date": "01 Jun 2025",
            "Qty": "1",
            "Days": "365",
        }
        self.app.st.session_state["clinic_id"] = "Clinic Save State"
        self.app.st.session_state["user_name"] = "Nurse"

        values = self.app.action_tracker_row_values(
            row,
            self.app.REMINDER_ACTION_SENT,
            message="Hi Client A, Pet A is due.",
            source="test_sent",
        )
        record = self.app.action_tracker_values_to_record(self.app.ACTION_TRACKER_HEADERS, values)

        self.assertEqual(record["Action"], self.app.REMINDER_ACTION_SENT)
        self.assertEqual(record["MessageCreated"], "Hi Client A, Pet A is due.")
        self.assertEqual(record["Actioned By"], "Nurse")

    def test_sent_action_skips_redundant_settings_save_and_overlay(self):
        row = {
            "Client Name": "Client A",
            "Animal Name": "Pet A",
            "Plan Item": "Rabies",
            "Reminder Date": "01 Jun 2026",
            "Due Date": "01 Jun 2026",
            "Charge Date": "01 Jun 2025",
            "Qty": "1",
            "Days": "365",
        }
        state = self.app.st.session_state
        state["user_name"] = "Nurse"
        state["deleted_reminders"] = []
        state["wa_reminder_log"] = []

        with (
            patch.object(self.app, "build_whatsapp_message_for_row", return_value="Reminder message"),
            patch.object(self.app, "record_action_tracker") as record_action,
            patch.object(self.app, "save_settings_quietly") as save_settings,
            patch.object(self.app, "busy_overlay") as overlay,
        ):
            self.app.mark_reminder_sent_action(row, "daily", "wa_message", 0)

        record_action.assert_called_once()
        save_settings.assert_not_called()
        overlay.assert_not_called()
        self.assertEqual(state["wa_message"], "Reminder message")
        self.assertEqual(state["deleted_reminders"][-1]["Action"], self.app.REMINDER_ACTION_SENT)
        self.assertEqual(state["wa_reminder_log"][-1]["ReminderKey"], list(self.app.hidden_reminder_key(row)))
        self.assertFalse(state["daily_reveal_hidden_reminders"])

    def test_decline_action_skips_redundant_settings_save_and_overlay(self):
        row = {
            "Client Name": "Client A",
            "Animal Name": "Pet A",
            "Plan Item": "Rabies",
            "Reminder Date": "01 Jun 2026",
            "Due Date": "01 Jun 2026",
            "Charge Date": "01 Jun 2025",
            "Qty": "1",
            "Days": "365",
        }
        sent_record = dict(row, Action=self.app.REMINDER_ACTION_SENT, ActionedAt="2026-05-15T10:00:00")
        state = self.app.st.session_state
        state["user_name"] = "Nurse"
        state["deleted_reminders"] = [sent_record]
        state["wa_reminder_log"] = [{
            "Client Name": "Client A",
            "RemindedAt": "2026-05-15T10:00:00",
            "ReminderKey": list(self.app.hidden_reminder_key(row)),
        }]

        with (
            patch.object(self.app, "record_action_tracker") as record_action,
            patch.object(self.app, "save_settings_quietly") as save_settings,
            patch.object(self.app, "busy_overlay") as overlay,
        ):
            self.app.decline_reminder_action(row, "daily")

        record_action.assert_called_once()
        save_settings.assert_not_called()
        overlay.assert_not_called()
        self.assertEqual(state["deleted_reminders"][-1]["Action"], self.app.REMINDER_ACTION_DECLINED)
        self.assertEqual(state["wa_reminder_log"], [])
        self.assertNotIn("_wa_reminder_remove_keys_once", state)
        self.assertFalse(state["daily_reveal_hidden_reminders"])

    def test_final_sheet_layout_includes_seven_expected_tabs(self):
        tracker_titles = {title for title, _headers in self.app.TRACKER_SHEET_DEFINITIONS}
        expected_titles = {
            "Saved settings",
            self.app.USER_TRACKER_WORKSHEET,
            self.app.ACTION_TRACKER_WORKSHEET,
            self.app.DATASET_TRACKER_WORKSHEET,
            self.app.SETTINGS_AUDIT_WORKSHEET,
            self.app.ERROR_TRACKER_WORKSHEET,
            self.app.PERFORMANCE_TRACKER_WORKSHEET,
        }

        self.assertEqual(tracker_titles | {"Saved settings"}, expected_titles)
        self.assertEqual(len(expected_titles), 7)

    def test_tracker_events_write_compact_rows(self):
        captured = {}

        def capture_append(title, headers, values):
            captured["title"] = title
            captured["headers"] = headers
            captured["values"] = values
            return True

        self.app.st.session_state["clinic_id"] = "Clinic Save State"
        self.app.st.session_state["user_name"] = "Nurse"
        with patch.object(self.app, "append_tracker_row", side_effect=capture_append):
            self.app.record_settings_audit_event(
                "search_term_changed",
                "search_terms",
                "rabies",
                "visible_text",
                "A" * 600,
                {"days": 365, "use_qty": False},
                "test",
            )

        self.assertEqual(captured["title"], self.app.SETTINGS_AUDIT_WORKSHEET)
        self.assertEqual(captured["headers"], self.app.SETTINGS_AUDIT_HEADERS)
        self.assertEqual(captured["values"][1], "Clinic Save State")
        self.assertEqual(captured["values"][2], "Nurse")
        self.assertLessEqual(len(captured["values"][7]), self.app.TRACKER_CELL_TEXT_LIMIT)
        self.assertIn('"days": 365', captured["values"][8])


if __name__ == "__main__":
    unittest.main()
