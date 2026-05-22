import contextlib
import importlib
import io
import json
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from requests import Response


class FakeSettingsSheet:
    def __init__(self, remote_settings):
        self.remote_settings = remote_settings
        self.batch_updates = []
        self.row_values_calls = 0

    def row_values(self, row_idx):
        self.row_values_calls += 1
        return [
            "Clinic Save State",
            "",
            "",
            json.dumps(self.remote_settings),
            "2026-05-15T00:00:00",
        ]

    def batch_update(self, updates):
        self.batch_updates.append(updates)


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
            "client_item_exclusions": [
                {"client": "Existing Client", "item": "Dental"}
            ],
        }
        remote_settings = {
            "rules": {
                "rabies": {"days": 365, "use_qty": False},
                "librela": {"days": 30, "use_qty": False},
            },
            "exclusions": ["old", "remote-only"],
            "client_exclusions": [],
            "patient_exclusions": [],
            "client_item_exclusions": [
                {"client": "Existing Client", "item": "Dental"},
                {"client": "Remote Client", "item": "Rabies"},
            ],
        }
        self.app.cache_remote_settings("Clinic Save State", base_settings)
        self.app.st.session_state["rules"] = {"rabies": {"days": 400, "use_qty": False}}
        self.app.st.session_state["exclusions"] = ["old", "local-only"]
        self.app.st.session_state["client_item_exclusions"] = [
            {"client": "Existing Client", "item": "Dental"},
            {"client": "Local Client", "item": "Groom"},
        ]

        saved = self.run_save_with_remote(remote_settings)

        self.assertEqual(saved["rules"]["rabies"]["days"], 400)
        self.assertEqual(saved["rules"]["librela"]["days"], 30)
        self.assertEqual(saved["exclusions"], ["old", "remote-only", "local-only"])
        self.assertEqual(
            saved["client_item_exclusions"],
            [
                {"client": "Existing Client", "item": "Dental"},
                {"client": "Remote Client", "item": "Rabies"},
                {"client": "Local Client", "item": "Groom"},
            ],
        )

    def test_search_term_rules_get_default_categories(self):
        normalized = self.app.normalize_search_term_rules({
            "rabies": {"days": 365, "use_qty": False},
            "bravecto": {"days": 90, "use_qty": True},
            "cardisure": {"days": 30, "use_qty": False},
            "custom local term": {"days": 30, "use_qty": False},
        })

        self.assertEqual(normalized["rabies"]["category"], "Vaccinations")
        self.assertEqual(normalized["bravecto"]["category"], "Parasite Control")
        self.assertEqual(normalized["cardisure"]["category"], "Medications")
        self.assertEqual(normalized["custom local term"]["category"], "Other")

    def test_search_term_category_aliases_migrate_old_saved_names(self):
        normalized = self.app.normalize_search_term_rules({
            "librela": {"days": 30, "use_qty": False, "category": "Injection Therapies"},
            "cytopoint": {"days": 30, "use_qty": False, "category": "Injections"},
            "dental": {"days": 365, "use_qty": False, "category": "Dental Care"},
            "arthritis": {"days": 30, "use_qty": False, "category": "Mobility & Pain Management"},
        })

        self.assertEqual(normalized["librela"]["category"], "Injectables")
        self.assertEqual(normalized["cytopoint"]["category"], "Injectables")
        self.assertEqual(normalized["dental"]["category"], "Dental")
        self.assertEqual(normalized["arthritis"]["category"], "Mobility & Pain")

    def test_search_term_category_tab_label_hides_zero_counts(self):
        self.assertEqual(
            self.app.search_term_category_tab_label("Vaccinations", 3),
            "Vaccinations (3)",
        )
        self.assertEqual(
            self.app.search_term_category_tab_label("Behaviour", 0),
            "Behaviour",
        )

    def test_save_settings_persists_automatic_patient_exclusions_and_keywords(self):
        self.app.cache_remote_settings(
            "Clinic Save State",
            {
                "rules": {},
                "exclusions": [],
                "client_exclusions": [],
                "patient_exclusions": [],
                "automatic_patient_exclusions": [
                    {"client": "Remote Client", "patient": "Remote Pet"}
                ],
                "patient_passaway_keywords": ["euthanasia"],
            },
        )
        remote_settings = {
            "rules": {},
            "exclusions": [],
            "client_exclusions": [],
            "patient_exclusions": [],
            "automatic_patient_exclusions": [
                {"client": "Remote Client", "patient": "Remote Pet"}
            ],
            "patient_passaway_keywords": ["euthanasia"],
        }
        self.app.st.session_state["rules"] = {}
        self.app.st.session_state["exclusions"] = []
        self.app.st.session_state["client_exclusions"] = []
        self.app.st.session_state["patient_exclusions"] = []
        self.app.st.session_state["automatic_patient_exclusions"] = [
            {"client": "Remote Client", "patient": "Remote Pet"},
            {"client": "Local Client", "patient": "Local Pet"},
        ]
        self.app.st.session_state["patient_passaway_keywords"] = ["euthanasia", "pentobarb"]

        saved = self.run_save_with_remote(remote_settings)

        self.assertEqual(
            saved["automatic_patient_exclusions"],
            [
                {"client": "Remote Client", "patient": "Remote Pet"},
                {"client": "Local Client", "patient": "Local Pet"},
            ],
        )
        self.assertEqual(saved["patient_passaway_keywords"], ["euthanasia", "pentobarb"])

    def test_wa_templates_migrate_legacy_template_to_general(self):
        templates = self.app.normalize_wa_templates({}, "Legacy [Pet Name] template")

        self.assertEqual(templates, {"General": "Legacy [Pet Name] template"})

    def test_save_settings_persists_named_wa_templates_and_current_selection(self):
        self.app.cache_remote_settings(
            "Clinic Save State",
            {
                "rules": {},
                "exclusions": [],
                "client_exclusions": [],
                "patient_exclusions": [],
                "wa_templates": {"General": "General message"},
                "current_wa_template_name": "General",
                "user_template": "General message",
            },
        )
        self.app.st.session_state["rules"] = {}
        self.app.st.session_state["exclusions"] = []
        self.app.st.session_state["client_exclusions"] = []
        self.app.st.session_state["patient_exclusions"] = []
        self.app.st.session_state["automatic_patient_exclusions"] = []
        self.app.st.session_state["patient_passaway_keywords"] = []
        self.app.st.session_state["wa_templates"] = {
            "General": "General message",
            "Puppy School": "Puppy school reminder for [Pet Name]",
        }
        self.app.st.session_state["current_wa_template_name"] = "Puppy School"
        self.app.st.session_state["user_template"] = "Puppy school reminder for [Pet Name]"

        saved = self.run_save_with_remote({
            "rules": {},
            "exclusions": [],
            "client_exclusions": [],
            "patient_exclusions": [],
            "wa_templates": {"General": "General message"},
            "current_wa_template_name": "General",
            "user_template": "General message",
        })

        self.assertEqual(saved["wa_templates"]["General"], "General message")
        self.assertEqual(saved["wa_templates"]["Puppy School"], "Puppy school reminder for [Pet Name]")
        self.assertEqual(saved["current_wa_template_name"], "Puppy School")
        self.assertEqual(saved["user_template"], "Puppy school reminder for [Pet Name]")

    def test_whatsapp_message_uses_selected_named_template(self):
        state = self.app.st.session_state
        state["user_name"] = "Nurse"
        state["wa_templates"] = {
            "General": "General [Pet Name]",
            "Puppy School": "Hi [Client Name], [Pet Name] is booked for puppy school.",
        }
        state["current_wa_template_name"] = "Puppy School"
        state["user_template"] = "General [Pet Name]"

        message = self.app.build_whatsapp_message_for_row({
            "Client Name": "Client A",
            "Animal Name": "Fluffy",
            "Plan Item": "Puppy School",
            "Due Date": "01 Jun 2026",
        })

        self.assertEqual(message, "Hi Client, Fluffy is booked for puppy school.")

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

    def test_save_settings_batches_country_metadata_with_existing_settings_row(self):
        headers = [
            self.app.SHEET_COL_CLINIC_ID,
            self.app.SHEET_COL_PASSWORD_HASH,
            self.app.SHEET_COL_SETTINGS_JSON,
            self.app.SHEET_COL_UPDATED_AT,
            self.app.SHEET_COL_COUNTRY,
            self.app.SHEET_COL_ACCOUNT_STATUS,
        ]
        sheet = FakeSettingsSheet({"rules": {}})
        self.app.st.session_state["user_country"] = "United Arab Emirates"

        with (
            patch.object(self.app, "_get_settings_row_for_clinic", return_value=(sheet, headers, 2)),
            patch.object(self.app, "_gspread_retry", side_effect=lambda fn, *args, **kwargs: fn(*args, **kwargs)),
            patch.object(self.app, "update_settings_row_fields") as update_fields,
        ):
            saved = self.app.save_settings(track_user=False)

        self.assertTrue(saved)
        update_fields.assert_not_called()
        self.assertEqual(len(sheet.batch_updates), 1)
        self.assertEqual(len(sheet.batch_updates[0]), 3)
        updates_by_range = {
            update["range"]: update["values"][0][0]
            for update in sheet.batch_updates[0]
        }
        self.assertIn("C2:D2", {update["range"] for update in sheet.batch_updates[0]})
        self.assertEqual(updates_by_range["E2:E2"], "United Arab Emirates")
        self.assertEqual(updates_by_range["F2:F2"], "active")

    def test_save_settings_skips_batch_update_when_remote_payload_is_unchanged(self):
        expected_settings = self.run_save_with_remote({})
        self.setUp()
        headers = [
            self.app.SHEET_COL_CLINIC_ID,
            self.app.SHEET_COL_PLAIN_PASSWORD,
            self.app.SHEET_COL_PASSWORD_HASH,
            self.app.SHEET_COL_SETTINGS_JSON,
            self.app.SHEET_COL_UPDATED_AT,
            self.app.SHEET_COL_COUNTRY,
            self.app.SHEET_COL_ACCOUNT_STATUS,
        ]
        sheet = FakeSettingsSheet(expected_settings)
        self.app.cache_remote_settings("Clinic Save State", expected_settings)
        self.app.st.session_state["_settings_row_cache"] = {
            "clinic_key": "clinic save state",
            "headers": headers,
            "row_idx": 2,
            "row_values": [
                "Clinic Save State",
                "",
                "",
                json.dumps(expected_settings),
                "2026-05-15T00:00:00",
                str(expected_settings.get("country", "")),
                "active",
            ],
        }

        with (
            patch.object(self.app, "_get_settings_row_for_clinic", return_value=(sheet, headers, 2)),
            patch.object(self.app, "_gspread_retry", side_effect=lambda fn, *args, **kwargs: fn(*args, **kwargs)),
            patch.object(self.app, "update_settings_row_fields") as update_fields,
        ):
            saved = self.app.save_settings(track_user=False)

        self.assertTrue(saved)
        self.assertEqual(sheet.row_values_calls, 1)
        self.assertEqual(sheet.batch_updates, [])
        update_fields.assert_not_called()

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

    def test_save_settings_persists_reminder_filter_days(self):
        self.app.cache_remote_settings("Clinic Save State", {})
        self.app.st.session_state["reminder_lookback_days"] = 7
        self.app.st.session_state["reminder_window_days"] = 5
        self.app.st.session_state["client_group_days"] = 3
        self.app.st.session_state["reminder_warning_days"] = 4

        saved = self.run_save_with_remote({})

        self.assertEqual(saved["reminder_lookback_days"], 7)
        self.assertEqual(saved["reminder_window_days"], 5)
        self.assertEqual(saved["client_group_days"], 3)
        self.assertEqual(saved["reminder_warning_days"], 4)

    def test_same_clinic_settings_changes_from_other_computer_are_preserved(self):
        base_settings = {
            "rules": {},
            "reminder_lookback_days": 2,
            "reminder_window_days": 1,
            "client_group_days": 1,
            "reminder_warning_days": 0,
        }
        remote_settings = {
            **base_settings,
            "reminder_lookback_days": 9,
            "reminder_window_days": 6,
        }
        self.app.cache_remote_settings("Clinic Save State", base_settings)
        self.app.st.session_state["rules"] = {}
        self.app.st.session_state["reminder_lookback_days"] = 2
        self.app.st.session_state["reminder_window_days"] = 1
        self.app.st.session_state["client_group_days"] = 4
        self.app.st.session_state["reminder_warning_days"] = 0

        saved = self.run_save_with_remote(remote_settings)

        self.assertEqual(saved["reminder_lookback_days"], 9)
        self.assertEqual(saved["reminder_window_days"], 6)
        self.assertEqual(saved["client_group_days"], 4)
        self.assertEqual(saved["reminder_warning_days"], 0)

    def test_save_settings_persists_outcome_due_date_window_days(self):
        self.app.cache_remote_settings("Clinic Save State", {})
        self.app.st.session_state["outcome_due_date_window_days"] = 30

        saved = self.run_save_with_remote({})

        self.assertEqual(saved["outcome_due_date_window_days"], 30)

    def test_save_settings_persists_outcome_post_reminder_window_days(self):
        self.app.cache_remote_settings("Clinic Save State", {})
        self.app.st.session_state["outcome_post_reminder_window_days"] = 10

        saved = self.run_save_with_remote({})

        self.assertEqual(saved["outcome_post_reminder_window_days"], 10)

    def test_post_reminder_window_save_callback_marks_user_set_value(self):
        self.app.st.session_state["outcome_post_reminder_window_days"] = 0

        with patch.object(self.app, "save_settings_quietly", return_value=True):
            self.app.save_outcome_post_reminder_window_days()

        self.assertEqual(
            self.app.st.session_state["outcome_post_reminder_window_days"],
            self.app.DEFAULT_OUTCOME_POST_REMINDER_WINDOW_DAYS,
        )
        self.assertTrue(
            self.app.st.session_state[self.app.OUTCOME_POST_REMINDER_WINDOW_USER_SET_KEY]
        )

    def test_reminder_filter_callback_skips_save_when_value_is_unchanged(self):
        self.app.st.session_state["reminder_lookback_days"] = 7
        self.app.st.session_state[self.app.REMINDER_LOOKBACK_DAYS_LOADED_KEY] = 7
        self.app.st.session_state[self.app.REMINDER_LOOKBACK_DAYS_DIRTY_KEY] = False

        with patch.object(self.app, "save_settings_quietly") as save_settings:
            self.app.save_reminder_lookback_days()

        save_settings.assert_not_called()
        self.assertFalse(self.app.st.session_state[self.app.REMINDER_LOOKBACK_DAYS_DIRTY_KEY])
        self.assertEqual(self.app.st.session_state[self.app.REMINDER_LOOKBACK_DAYS_LOADED_KEY], 7)

    def test_reminder_filter_callback_saves_when_value_changed(self):
        self.app.st.session_state["reminder_lookback_days"] = 9
        self.app.st.session_state[self.app.REMINDER_LOOKBACK_DAYS_LOADED_KEY] = 7
        self.app.st.session_state[self.app.REMINDER_LOOKBACK_DAYS_DIRTY_KEY] = False

        with patch.object(self.app, "save_settings_quietly", return_value=True) as save_settings:
            self.app.save_reminder_lookback_days()

        save_settings.assert_called_once()
        self.assertFalse(self.app.st.session_state[self.app.REMINDER_LOOKBACK_DAYS_DIRTY_KEY])
        self.assertEqual(self.app.st.session_state[self.app.REMINDER_LOOKBACK_DAYS_LOADED_KEY], 9)

    def test_outcome_window_callback_skips_save_when_value_is_unchanged(self):
        self.app.st.session_state["outcome_due_date_window_days"] = 14
        self.app.st.session_state[self.app.OUTCOME_DUE_DATE_WINDOW_LOADED_KEY] = 14
        self.app.st.session_state[self.app.OUTCOME_DUE_DATE_WINDOW_DIRTY_KEY] = False

        with patch.object(self.app, "save_settings_quietly") as save_settings:
            self.app.save_outcome_due_date_window_days()

        save_settings.assert_not_called()
        self.assertFalse(self.app.st.session_state[self.app.OUTCOME_DUE_DATE_WINDOW_DIRTY_KEY])
        self.assertEqual(self.app.st.session_state[self.app.OUTCOME_DUE_DATE_WINDOW_LOADED_KEY], 14)

    def test_outcome_window_callback_saves_when_value_changed(self):
        self.app.st.session_state["outcome_due_date_window_days"] = 30
        self.app.st.session_state[self.app.OUTCOME_DUE_DATE_WINDOW_LOADED_KEY] = 14
        self.app.st.session_state[self.app.OUTCOME_DUE_DATE_WINDOW_DIRTY_KEY] = False

        with patch.object(self.app, "save_settings_quietly", return_value=True) as save_settings:
            self.app.save_outcome_due_date_window_days()

        save_settings.assert_called_once()
        self.assertFalse(self.app.st.session_state[self.app.OUTCOME_DUE_DATE_WINDOW_DIRTY_KEY])
        self.assertEqual(self.app.st.session_state[self.app.OUTCOME_DUE_DATE_WINDOW_LOADED_KEY], 30)

    def test_save_settings_falls_back_when_outcome_window_default_is_missing(self):
        self.app.cache_remote_settings("Clinic Save State", {})
        default_value = self.app.DEFAULT_OUTCOME_DUE_DATE_WINDOW_DAYS

        try:
            delattr(self.app, "DEFAULT_OUTCOME_DUE_DATE_WINDOW_DAYS")
            saved = self.run_save_with_remote({})
        finally:
            self.app.DEFAULT_OUTCOME_DUE_DATE_WINDOW_DAYS = default_value

        self.assertEqual(saved["outcome_due_date_window_days"], 14)

    def test_save_settings_persists_period_window_preferences(self):
        self.app.cache_remote_settings("Clinic Save State", {})
        self.app.st.session_state["stats_period"] = "Custom"
        self.app.st.session_state["stats_custom_range"] = (date(2026, 5, 1), date(2026, 5, 22))
        self.app.st.session_state["stats_custom_range_last_complete"] = (date(2026, 5, 1), date(2026, 5, 22))
        self.app.st.session_state["reminders_actioned_period"] = "Past"
        self.app.st.session_state["reminders_actioned_period_rolling_more"] = "Past 6 months"

        saved = self.run_save_with_remote({})

        preferences = saved[self.app.PERIOD_WINDOW_PREFERENCES_SETTINGS_KEY]
        self.assertEqual(preferences["stats_period"], "Custom")
        self.assertEqual(preferences["stats_custom_range"], ["2026-05-01", "2026-05-22"])
        self.assertEqual(preferences["stats_custom_range_last_complete"], ["2026-05-01", "2026-05-22"])
        self.assertEqual(preferences["reminders_actioned_period"], "Past")
        self.assertEqual(preferences["reminders_actioned_period_rolling_more"], "Past 6 months")

    def test_load_settings_restores_period_window_preferences(self):
        headers = ["ClinicID", "PlainPassword", "PasswordHash", "SettingsJSON", "UpdatedAt"]
        sheet = FakeSettingsSheet({
            self.app.PERIOD_WINDOW_PREFERENCES_SETTINGS_KEY: {
                "stats_period": "Custom",
                "stats_custom_range": ["2026-05-01", "2026-05-22"],
                "reminders_actioned_period": "Calendar",
                "reminders_actioned_period_calendar_year": "2026",
                "reminders_actioned_period_calendar_period": "Quarter",
                "reminders_actioned_period_calendar_quarter": "1",
            }
        })

        with (
            patch.object(self.app, "_get_settings_row_for_clinic", return_value=(sheet, headers, 2)),
            patch.object(self.app, "load_action_tracker_records_for_clinic", return_value=[]),
        ):
            self.app.load_settings()

        self.assertEqual(self.app.st.session_state["stats_period"], "Custom")
        self.assertEqual(self.app.st.session_state["stats_custom_range"], (date(2026, 5, 1), date(2026, 5, 22)))
        self.assertEqual(
            self.app.st.session_state["stats_custom_range_last_complete"],
            (date(2026, 5, 1), date(2026, 5, 22)),
        )
        self.assertEqual(self.app.st.session_state["reminders_actioned_period"], "Calendar")
        self.assertEqual(self.app.st.session_state["reminders_actioned_period_calendar_year"], 2026)
        self.assertEqual(self.app.st.session_state["reminders_actioned_period_calendar_period"], "Quarter")
        self.assertEqual(self.app.st.session_state["reminders_actioned_period_calendar_quarter"], 1)

    def test_load_settings_restores_outcome_due_date_window_days(self):
        headers = ["ClinicID", "PlainPassword", "PasswordHash", "SettingsJSON", "UpdatedAt"]
        sheet = FakeSettingsSheet({"outcome_due_date_window_days": 30})

        with (
            patch.object(self.app, "_get_settings_row_for_clinic", return_value=(sheet, headers, 2)),
            patch.object(self.app, "load_action_tracker_records_for_clinic", return_value=[]),
        ):
            self.app.load_settings()

        self.assertEqual(self.app.st.session_state["outcome_due_date_window_days"], 30)

    def test_load_settings_upgrades_zero_outcome_due_date_window_to_default(self):
        headers = ["ClinicID", "PlainPassword", "PasswordHash", "SettingsJSON", "UpdatedAt"]
        sheet = FakeSettingsSheet({"outcome_due_date_window_days": 0})

        with (
            patch.object(self.app, "_get_settings_row_for_clinic", return_value=(sheet, headers, 2)),
            patch.object(self.app, "load_action_tracker_records_for_clinic", return_value=[]),
        ):
            self.app.load_settings()

        self.assertEqual(
            self.app.st.session_state["outcome_due_date_window_days"],
            self.app.DEFAULT_OUTCOME_DUE_DATE_WINDOW_DAYS,
        )

    def test_load_settings_restores_outcome_post_reminder_window_days(self):
        headers = ["ClinicID", "PlainPassword", "PasswordHash", "SettingsJSON", "UpdatedAt"]
        sheet = FakeSettingsSheet({"outcome_post_reminder_window_days": 10})

        with (
            patch.object(self.app, "_get_settings_row_for_clinic", return_value=(sheet, headers, 2)),
            patch.object(self.app, "load_action_tracker_records_for_clinic", return_value=[]),
        ):
            self.app.load_settings()

        self.assertEqual(self.app.st.session_state["outcome_post_reminder_window_days"], 10)

    def test_load_settings_can_defer_action_tracker_read_until_needed(self):
        headers = ["ClinicID", "PlainPassword", "PasswordHash", "SettingsJSON", "UpdatedAt"]
        legacy_action = {
            "Client Name": "Legacy Client",
            "Animal Name": "Legacy Pet",
            "Plan Item": "Rabies Vaccine",
            "Due Date": "2026-05-01",
            "Reminder Date": "2026-05-01",
            "Action": self.app.REMINDER_ACTION_SENT,
            "ActionedAt": "2026-05-02T09:00:00",
        }
        tracked_action = {
            "Client Name": "Tracked Client",
            "Animal Name": "Tracked Pet",
            "Plan Item": "Tricat Vaccine",
            "Due Date": "2026-06-01",
            "Reminder Date": "2026-06-01",
            "Action": self.app.REMINDER_ACTION_SENT,
            "ActionedAt": "2026-06-02T09:00:00",
        }
        sheet = FakeSettingsSheet({
            "deleted_reminders": [legacy_action],
            "wa_reminder_log": [{"Client Name": "Legacy Client", "RemindedAt": "2026-05-02T09:00:00"}],
        })

        with (
            patch.object(self.app, "_get_settings_row_for_clinic", return_value=(sheet, headers, 2)),
            patch.object(self.app, "load_action_tracker_records_for_clinic", return_value=[tracked_action]) as load_actions,
        ):
            self.app.load_settings(load_action_history=False)

        load_actions.assert_not_called()
        self.assertEqual(
            self.app.st.session_state["_action_tracker_pending_load_for"],
            self.app.normalize_clinic_id_key("Clinic Save State"),
        )
        self.assertEqual(
            [row["Client Name"] for row in self.app.st.session_state["deleted_reminders"]],
            ["Legacy Client"],
        )

        with patch.object(self.app, "load_action_tracker_records_for_clinic", return_value=[tracked_action]) as load_actions:
            self.app.ensure_action_tracker_loaded_for_current_clinic()

        load_actions.assert_called_once_with("Clinic Save State")
        self.assertNotIn("_action_tracker_pending_load_for", self.app.st.session_state)
        self.assertEqual(
            {row["Client Name"] for row in self.app.st.session_state["deleted_reminders"]},
            {"Legacy Client", "Tracked Client"},
        )

    def test_load_settings_upgrades_legacy_zero_post_reminder_window_to_default(self):
        headers = ["ClinicID", "PlainPassword", "PasswordHash", "SettingsJSON", "UpdatedAt"]
        sheet = FakeSettingsSheet({"outcome_post_reminder_window_days": 0})

        with (
            patch.object(self.app, "_get_settings_row_for_clinic", return_value=(sheet, headers, 2)),
            patch.object(self.app, "load_action_tracker_records_for_clinic", return_value=[]),
        ):
            self.app.load_settings()

        self.assertEqual(
            self.app.st.session_state["outcome_post_reminder_window_days"],
            self.app.DEFAULT_OUTCOME_POST_REMINDER_WINDOW_DAYS,
        )

    def test_load_settings_upgrades_user_set_zero_post_reminder_window_to_default(self):
        headers = ["ClinicID", "PlainPassword", "PasswordHash", "SettingsJSON", "UpdatedAt"]
        sheet = FakeSettingsSheet({
            "outcome_post_reminder_window_days": 0,
            "outcome_post_reminder_window_days_user_set": True,
        })

        with (
            patch.object(self.app, "_get_settings_row_for_clinic", return_value=(sheet, headers, 2)),
            patch.object(self.app, "load_action_tracker_records_for_clinic", return_value=[]),
        ):
            self.app.load_settings()

        self.assertEqual(
            self.app.st.session_state["outcome_post_reminder_window_days"],
            self.app.DEFAULT_OUTCOME_POST_REMINDER_WINDOW_DAYS,
        )

    def test_outcome_due_date_window_load_helper_is_defined_before_load_settings(self):
        source = Path("reminders_app_v3.py").read_text(encoding="utf-8")

        self.assertLess(
            source.index("def load_outcome_due_date_window_days"),
            source.index("def load_settings"),
        )
        self.assertLess(
            source.index("def load_outcome_post_reminder_window_days"),
            source.index("def load_settings"),
        )
        self.assertLess(
            source.index("def normalized_reminder_lookback_days"),
            source.index("def load_settings"),
        )
        self.assertLess(
            source.index("def load_reminder_filter_settings"),
            source.index("def load_settings"),
        )
        self.assertLess(
            source.index("DEFAULT_OUTCOME_DUE_DATE_WINDOW_DAYS = 14"),
            source.index("def load_settings"),
        )
        self.assertLess(
            source.index("DEFAULT_OUTCOME_POST_REMINDER_WINDOW_DAYS = 7"),
            source.index("def load_settings"),
        )

    def test_load_settings_preserves_dirty_outcome_due_date_window_days(self):
        headers = ["ClinicID", "PlainPassword", "PasswordHash", "SettingsJSON", "UpdatedAt"]
        sheet = FakeSettingsSheet({"outcome_due_date_window_days": 14})
        self.app.st.session_state["outcome_due_date_window_days"] = 30
        self.app.st.session_state[self.app.OUTCOME_DUE_DATE_WINDOW_DIRTY_KEY] = True

        with (
            patch.object(self.app, "_get_settings_row_for_clinic", return_value=(sheet, headers, 2)),
            patch.object(self.app, "load_action_tracker_records_for_clinic", return_value=[]),
        ):
            self.app.load_settings()

        self.assertEqual(self.app.st.session_state["outcome_due_date_window_days"], 30)
        self.assertTrue(self.app.st.session_state[self.app.OUTCOME_DUE_DATE_WINDOW_DIRTY_KEY])

    def test_load_settings_preserves_dirty_reminder_filter_days(self):
        headers = ["ClinicID", "PlainPassword", "PasswordHash", "SettingsJSON", "UpdatedAt"]
        sheet = FakeSettingsSheet({
            "reminder_lookback_days": 2,
            "reminder_window_days": 1,
            "client_group_days": 1,
            "reminder_warning_days": 0,
        })
        self.app.st.session_state["reminder_lookback_days"] = 7
        self.app.st.session_state["reminder_window_days"] = 5
        self.app.st.session_state["client_group_days"] = 3
        self.app.st.session_state["reminder_warning_days"] = 4
        self.app.st.session_state[self.app.REMINDER_LOOKBACK_DAYS_DIRTY_KEY] = True
        self.app.st.session_state[self.app.REMINDER_WINDOW_DAYS_DIRTY_KEY] = True
        self.app.st.session_state[self.app.REMINDER_GROUP_DAYS_DIRTY_KEY] = True
        self.app.st.session_state[self.app.REMINDER_WARNING_DAYS_DIRTY_KEY] = True

        with (
            patch.object(self.app, "_get_settings_row_for_clinic", return_value=(sheet, headers, 2)),
            patch.object(self.app, "load_action_tracker_records_for_clinic", return_value=[]),
        ):
            self.app.load_settings()

        self.assertEqual(self.app.st.session_state["reminder_lookback_days"], 7)
        self.assertEqual(self.app.st.session_state["reminder_window_days"], 5)
        self.assertEqual(self.app.st.session_state["client_group_days"], 3)
        self.assertEqual(self.app.st.session_state["reminder_warning_days"], 4)
        self.assertTrue(self.app.st.session_state[self.app.REMINDER_LOOKBACK_DAYS_DIRTY_KEY])
        self.assertTrue(self.app.st.session_state[self.app.REMINDER_WINDOW_DAYS_DIRTY_KEY])
        self.assertTrue(self.app.st.session_state[self.app.REMINDER_GROUP_DAYS_DIRTY_KEY])
        self.assertTrue(self.app.st.session_state[self.app.REMINDER_WARNING_DAYS_DIRTY_KEY])

    def test_load_settings_clears_dirty_post_reminder_window_when_zero_upgrades_to_current_default(self):
        headers = ["ClinicID", "PlainPassword", "PasswordHash", "SettingsJSON", "UpdatedAt"]
        sheet = FakeSettingsSheet({"outcome_post_reminder_window_days": 0})
        self.app.st.session_state["outcome_post_reminder_window_days"] = 7
        self.app.st.session_state[self.app.OUTCOME_POST_REMINDER_WINDOW_DIRTY_KEY] = True

        with (
            patch.object(self.app, "_get_settings_row_for_clinic", return_value=(sheet, headers, 2)),
            patch.object(self.app, "load_action_tracker_records_for_clinic", return_value=[]),
        ):
            self.app.load_settings()

        self.assertEqual(self.app.st.session_state["outcome_post_reminder_window_days"], 7)
        self.assertFalse(self.app.st.session_state[self.app.OUTCOME_POST_REMINDER_WINDOW_DIRTY_KEY])

    def test_load_settings_keeps_existing_outcome_window_when_saved_key_missing(self):
        headers = ["ClinicID", "PlainPassword", "PasswordHash", "SettingsJSON", "UpdatedAt"]
        sheet = FakeSettingsSheet({})
        self.app.st.session_state["outcome_due_date_window_days"] = 30
        self.app.st.session_state["outcome_post_reminder_window_days"] = 10

        with (
            patch.object(self.app, "_get_settings_row_for_clinic", return_value=(sheet, headers, 2)),
            patch.object(self.app, "load_action_tracker_records_for_clinic", return_value=[]),
        ):
            self.app.load_settings()

        self.assertEqual(self.app.st.session_state["outcome_due_date_window_days"], 30)
        self.assertEqual(self.app.st.session_state["outcome_post_reminder_window_days"], 10)

    def test_outcome_due_date_window_save_callback_stays_dirty_until_saved(self):
        self.app.st.session_state["outcome_due_date_window_days"] = 30

        with patch.object(self.app, "save_settings_quietly", return_value=False):
            self.app.save_outcome_due_date_window_days()

        self.assertTrue(self.app.st.session_state[self.app.OUTCOME_DUE_DATE_WINDOW_DIRTY_KEY])

        with patch.object(self.app, "save_settings_quietly", return_value=True):
            self.app.save_outcome_due_date_window_days()

        self.assertFalse(self.app.st.session_state[self.app.OUTCOME_DUE_DATE_WINDOW_DIRTY_KEY])
        self.assertEqual(self.app.st.session_state[self.app.OUTCOME_DUE_DATE_WINDOW_LOADED_KEY], 30)

    def test_outcome_post_reminder_window_save_callback_stays_dirty_until_saved(self):
        self.app.st.session_state["outcome_post_reminder_window_days"] = 10

        with patch.object(self.app, "save_settings_quietly", return_value=False):
            self.app.save_outcome_post_reminder_window_days()

        self.assertTrue(self.app.st.session_state[self.app.OUTCOME_POST_REMINDER_WINDOW_DIRTY_KEY])

        with patch.object(self.app, "save_settings_quietly", return_value=True):
            self.app.save_outcome_post_reminder_window_days()

        self.assertFalse(self.app.st.session_state[self.app.OUTCOME_POST_REMINDER_WINDOW_DIRTY_KEY])
        self.assertEqual(self.app.st.session_state[self.app.OUTCOME_POST_REMINDER_WINDOW_LOADED_KEY], 10)

    def test_quiet_settings_save_reports_false_without_logged_in_clinic(self):
        del self.app.st.session_state["clinic_id"]

        saved = self.app.save_settings_quietly()

        self.assertFalse(saved)

    def test_post_reminder_window_callback_stays_dirty_without_logged_in_clinic(self):
        del self.app.st.session_state["clinic_id"]
        self.app.st.session_state["outcome_post_reminder_window_days"] = 7

        self.app.save_outcome_post_reminder_window_days()

        self.assertEqual(self.app.st.session_state["outcome_post_reminder_window_days"], 7)
        self.assertTrue(self.app.st.session_state[self.app.OUTCOME_POST_REMINDER_WINDOW_DIRTY_KEY])
        self.assertNotIn(self.app.OUTCOME_POST_REMINDER_WINDOW_LOADED_KEY, self.app.st.session_state)

    def test_reminder_filter_callbacks_stay_dirty_without_logged_in_clinic(self):
        del self.app.st.session_state["clinic_id"]
        self.app.st.session_state["reminder_lookback_days"] = 7
        self.app.st.session_state["reminder_window_days"] = 5
        self.app.st.session_state["client_group_days"] = 3
        self.app.st.session_state["reminder_warning_days"] = 4

        self.app.save_reminder_lookback_days()
        self.app.save_reminder_window_days()
        self.app.save_reminder_group_days()
        self.app.save_reminder_warning_days()

        self.assertEqual(self.app.st.session_state["reminder_lookback_days"], 7)
        self.assertEqual(self.app.st.session_state["reminder_window_days"], 5)
        self.assertEqual(self.app.st.session_state["client_group_days"], 3)
        self.assertEqual(self.app.st.session_state["reminder_warning_days"], 4)
        self.assertTrue(self.app.st.session_state[self.app.REMINDER_LOOKBACK_DAYS_DIRTY_KEY])
        self.assertTrue(self.app.st.session_state[self.app.REMINDER_WINDOW_DAYS_DIRTY_KEY])
        self.assertTrue(self.app.st.session_state[self.app.REMINDER_GROUP_DAYS_DIRTY_KEY])
        self.assertTrue(self.app.st.session_state[self.app.REMINDER_WARNING_DAYS_DIRTY_KEY])

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

    def test_different_staff_users_append_sent_actions_for_same_clinic(self):
        row_a = {
            "Client Name": "Client A",
            "Animal Name": "Pet A",
            "Plan Item": "Rabies",
            "Reminder Date": "01 Jun 2026",
            "Due Date": "01 Jun 2026",
            "Charge Date": "01 Jun 2025",
            "Qty": "1",
            "Days": "365",
        }
        row_b = {
            "Client Name": "Client B",
            "Animal Name": "Pet B",
            "Plan Item": "Librela",
            "Reminder Date": "02 Jun 2026",
            "Due Date": "02 Jun 2026",
            "Charge Date": "02 May 2026",
            "Qty": "1",
            "Days": "30",
        }
        appended = []
        appended_raw = []

        def capture_append(title, headers, values):
            appended_raw.append({
                header: values[idx] if idx < len(values) else ""
                for idx, header in enumerate(headers)
            })
            appended.append(self.app.action_tracker_values_to_record(headers, values))
            return True

        with (
            patch.object(self.app, "build_whatsapp_message_for_row", return_value="Reminder message"),
            patch.object(self.app, "append_tracker_row", side_effect=capture_append),
            patch.object(self.app, "save_settings_quietly") as save_settings,
        ):
            for user_name, row, idx in [("Nurse A", row_a, 0), ("Nurse B", row_b, 1)]:
                self.app.st.session_state.clear()
                self.app.st.session_state["clinic_id"] = "Clinic Save State"
                self.app.st.session_state["user_name"] = user_name
                self.app.st.session_state["deleted_reminders"] = []
                self.app.st.session_state["wa_reminder_log"] = []
                self.app.mark_reminder_sent_action(row, "daily", "wa_message", idx)

        save_settings.assert_not_called()
        self.assertEqual(len(appended), 2)
        self.assertEqual([row["ClinicID"] for row in appended_raw], ["Clinic Save State", "Clinic Save State"])
        self.assertEqual([record["Actioned By"] for record in appended], ["Nurse A", "Nurse B"])
        self.assertEqual([record["Action"] for record in appended], [self.app.REMINDER_ACTION_SENT, self.app.REMINDER_ACTION_SENT])
        self.assertEqual(
            {tuple(json.loads(row["ReminderKey"])) for row in appended_raw},
            {tuple(self.app.hidden_reminder_key(row_a)), tuple(self.app.hidden_reminder_key(row_b))},
        )

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

    def test_final_sheet_layout_includes_eight_expected_tabs(self):
        tracker_titles = {title for title, _headers in self.app.TRACKER_SHEET_DEFINITIONS}
        expected_titles = {
            "Saved settings",
            self.app.USER_TRACKER_WORKSHEET,
            self.app.ACTION_TRACKER_WORKSHEET,
            self.app.DATASET_TRACKER_WORKSHEET,
            self.app.SETTINGS_AUDIT_WORKSHEET,
            self.app.ERROR_TRACKER_WORKSHEET,
            self.app.PERFORMANCE_TRACKER_WORKSHEET,
            self.app.ACCOUNT_LIFECYCLE_WORKSHEET,
        }

        self.assertEqual(tracker_titles | {"Saved settings"}, expected_titles)
        self.assertEqual(len(expected_titles), 8)

    def test_upsert_user_tracker_reuses_cached_row_after_first_scan(self):
        class FakeUserTrackerSheet:
            def __init__(self, headers):
                self.headers = headers
                self.rows = [
                    headers,
                    [
                        "Clinic Save State",
                        "United Arab Emirates",
                        "2026-05-01 09:00:00",
                        "2026-05-01 09:00:00",
                        "2026-05-01 09:00:00",
                        "active",
                        "login",
                    ],
                ]
                self.get_all_values_calls = 0
                self.updates = []

            def get_all_values(self):
                self.get_all_values_calls += 1
                return [list(row) for row in self.rows]

            def update(self, values=None, range_name=None, **_kwargs):
                self.updates.append({"range_name": range_name, "values": values})

        sheet = FakeUserTrackerSheet(self.app.USER_TRACKER_HEADERS)

        with (
            patch.object(self.app, "get_or_create_tracker_sheet", return_value=sheet),
            patch.object(self.app, "_gspread_retry", side_effect=lambda fn, *args, **kwargs: fn(*args, **kwargs)),
        ):
            self.app.upsert_user_tracker(
                "Clinic Save State",
                country="United Arab Emirates",
                event="login",
                now=self.app.datetime(2026, 5, 19, 8, 0, 0),
            )
            self.app.upsert_user_tracker(
                "Clinic Save State",
                country="United Arab Emirates",
                event="settings_saved",
                now=self.app.datetime(2026, 5, 19, 9, 0, 0),
            )

        self.assertEqual(sheet.get_all_values_calls, 1)
        self.assertEqual(len(sheet.updates), 2)
        first_update = sheet.updates[0]["values"][0]
        second_update = sheet.updates[1]["values"][0]
        self.assertEqual(first_update[self.app.USER_TRACKER_HEADERS.index("CreatedAtGST")], "2026-05-01 09:00:00")
        self.assertEqual(second_update[self.app.USER_TRACKER_HEADERS.index("CreatedAtGST")], "2026-05-01 09:00:00")
        self.assertEqual(second_update[self.app.USER_TRACKER_HEADERS.index("LastEvent")], "settings_saved")

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

    def test_account_lifecycle_event_uses_durable_non_clinicid_reference(self):
        captured = {}

        def capture_append(title, headers, values):
            captured["title"] = title
            captured["headers"] = headers
            captured["values"] = values
            return True

        with patch.object(self.app, "append_tracker_row", side_effect=capture_append):
            saved = self.app.record_account_lifecycle_event(
                "Clinic Save State",
                "deleted",
                clinic_name="Clinic Save State",
                auth_provider="google",
                country="United Arab Emirates",
                deleted_rows=7,
                trashed_data_file=True,
                source="unit_test",
            )

        self.assertTrue(saved)
        self.assertEqual(captured["title"], self.app.ACCOUNT_LIFECYCLE_WORKSHEET)
        self.assertEqual(captured["headers"], self.app.ACCOUNT_LIFECYCLE_HEADERS)
        self.assertNotIn("ClinicID", self.app.ACCOUNT_LIFECYCLE_HEADERS)
        self.assertIn("ClinicName", self.app.ACCOUNT_LIFECYCLE_HEADERS)
        self.assertEqual(captured["values"][1], "deleted")
        self.assertEqual(captured["values"][2], "success")
        self.assertEqual(len(captured["values"][3]), 16)
        self.assertNotEqual(captured["values"][3], "Clinic Save State")
        self.assertEqual(captured["values"][4], "Clinic Save State")
        self.assertEqual(captured["values"][7], "7")
        self.assertEqual(captured["values"][8], "True")

    def test_account_lifecycle_legacy_rows_shift_under_clinic_name_header(self):
        clinic_ref = self.app.account_lifecycle_clinic_ref("Legacy Clinic")
        legacy_row = [
            "2026-05-18 06:57:21",
            "deleted",
            "success",
            clinic_ref,
            "google",
            "United Arab Emirates",
            "2",
            "FALSE",
            "",
            "delete_account_and_data",
        ]

        normalized = self.app.normalize_account_lifecycle_row(
            legacy_row,
            {clinic_ref: "Legacy Clinic"},
        )

        self.assertEqual(normalized, [
            "2026-05-18 06:57:21",
            "deleted",
            "success",
            clinic_ref,
            "Legacy Clinic",
            "google",
            "United Arab Emirates",
            "2",
            "FALSE",
            "",
            "delete_account_and_data",
        ])

    def test_account_lifecycle_repair_updates_legacy_and_blank_name_rows(self):
        clinic_ref = self.app.account_lifecycle_clinic_ref("Repair Clinic")
        blank_name_ref = self.app.account_lifecycle_clinic_ref("Blank Name Clinic")
        values = [
            self.app.ACCOUNT_LIFECYCLE_HEADERS,
            [
                "2026-05-18 06:57:21",
                "deleted",
                "success",
                clinic_ref,
                "google",
                "United Arab Emirates",
                "2",
                "FALSE",
                "",
                "delete_account_and_data",
            ],
            [
                "2026-05-18 06:58:37",
                "created",
                "success",
                blank_name_ref,
                "",
                "google",
                "United Arab Emirates",
                "",
                "",
                "",
                "google_signup",
            ],
        ]

        class FakeWorksheet:
            def __init__(self, rows):
                self.rows = rows
                self.updates = []

            def get_all_values(self):
                return self.rows

            def batch_update(self, updates):
                self.updates = updates

        worksheet = FakeWorksheet(values)

        with patch.object(self.app, "_gspread_retry", side_effect=lambda fn, *args, **kwargs: fn(*args, **kwargs)):
            repaired = self.app.repair_account_lifecycle_rows(
                worksheet,
                {
                    clinic_ref: "Repair Clinic",
                    blank_name_ref: "Blank Name Clinic",
                },
            )

        self.assertEqual(repaired, 2)
        self.assertEqual(worksheet.updates[0]["range"], "A2:K2")
        self.assertEqual(worksheet.updates[0]["values"][0][4], "Repair Clinic")
        self.assertEqual(worksheet.updates[0]["values"][0][5], "google")
        self.assertEqual(worksheet.updates[1]["range"], "A3:K3")
        self.assertEqual(worksheet.updates[1]["values"][0][4], "Blank Name Clinic")


if __name__ == "__main__":
    unittest.main()
