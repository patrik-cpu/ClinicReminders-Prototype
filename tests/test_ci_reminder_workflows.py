import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from tests.workflow_harness import (
    TrackerCapture,
    import_app,
    quiet_busy_overlay,
    reset_session_state,
    sample_reminder_row,
)


class ReminderWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = import_app()

    def setUp(self):
        reset_session_state(
            self.app,
            clinic_id="Clinic Workflow",
            user_name="Nurse",
            deleted_reminders=[],
            wa_reminder_log=[],
            reminder_warning_days=0,
            main_section_tab="Upload Data",
        )

    def test_sent_declined_and_undo_workflow_records_tracker_rows_and_session_state(self):
        row = sample_reminder_row()
        tracker = TrackerCapture(self.app)
        sent_now = datetime(2026, 5, 16, 12, 0, 0)
        declined_now = sent_now + timedelta(minutes=5)
        undo_now = sent_now + timedelta(minutes=10)
        clock_values = iter([sent_now, declined_now, undo_now])

        def fake_utc_now(now=None):
            if now is not None:
                return now
            return next(clock_values)

        with (
            tracker.patch_append_row(),
            patch.object(self.app, "user_timezone_name", return_value="Pacific/Auckland"),
            patch.object(self.app, "utc_now", side_effect=fake_utc_now),
            patch.object(self.app, "busy_overlay", side_effect=quiet_busy_overlay),
            patch.object(self.app, "save_settings_quietly", return_value=True) as save_settings,
        ):
            self.app.mark_reminder_sent_action(row, "daily", "wa_message", 0)
            self.app.decline_reminder_action(row, "daily")
            self.app.remove_actioned_reminder_action(row, "daily")

        with patch.object(self.app, "user_timezone_name", return_value="Pacific/Auckland"):
            records = tracker.action_records()
        actions = [record["Action"] for record in records]
        self.assertEqual(actions, [
            self.app.REMINDER_ACTION_SENT,
            self.app.REMINDER_ACTION_DECLINED,
            "active",
        ])
        self.assertEqual(records[0]["ActionedAt"], "2026-05-17T00:00:00")
        self.assertEqual(records[0]["ActionedAtUTC"], "2026-05-16T12:00:00")
        self.assertEqual(records[0]["Actioned By"], "Nurse")
        self.assertIn("Nurse", self.app.st.session_state["wa_message"])

        state = self.app.st.session_state
        self.assertEqual(state["main_section_tab"], "Reminders")
        self.assertEqual(state["deleted_reminders"], [])
        self.assertEqual(state["wa_reminder_log"], [])
        self.assertEqual(
            state["_deleted_reminder_remove_keys_once"],
            [list(self.app.hidden_reminder_key(row))],
        )
        self.assertFalse(state["daily_reveal_hidden_reminders"])
        save_settings.assert_called_once()

    def test_sent_action_does_not_update_local_state_when_tracker_write_fails(self):
        row = sample_reminder_row()

        with (
            patch.object(self.app, "build_whatsapp_message_for_row", return_value="Reminder message"),
            patch.object(self.app, "append_tracker_row", return_value=False),
        ):
            self.app.mark_reminder_sent_action(row, "daily", "wa_message", 0)

        state = self.app.st.session_state
        self.assertEqual(state["deleted_reminders"], [])
        self.assertEqual(state["wa_reminder_log"], [])
        self.assertIn("was not saved", state["_pending_action_sync_warning"])

    def test_send_all_marks_listed_reminders_sent_with_one_tracker_write(self):
        rows = [
            sample_reminder_row(**{"Client Name": "Client A", "Animal Name": "Pet A", "Plan Item": "Rabies"}),
            sample_reminder_row(**{"Client Name": "Client B", "Animal Name": "Pet B", "Plan Item": "Librela"}),
        ]
        captured_rows = []

        def capture_rows(title, headers, rows_to_append):
            self.assertEqual(title, self.app.ACTION_TRACKER_WORKSHEET)
            captured_rows.extend(rows_to_append)
            return True

        with (
            patch.object(self.app, "append_tracker_rows", side_effect=capture_rows) as append_rows,
            patch.object(self.app, "build_whatsapp_message_for_row", return_value="Reminder message"),
            patch.object(self.app, "utc_now", return_value=datetime(2026, 5, 16, 12, 0, 0)),
        ):
            self.app.mark_all_listed_reminders_sent_action(rows, "daily", "wa_message")

        append_rows.assert_called_once()
        records = [
            self.app.action_tracker_values_to_record(self.app.ACTION_TRACKER_HEADERS, values)
            for values in captured_rows
        ]
        self.assertEqual([record["Action"] for record in records], [self.app.REMINDER_ACTION_SENT, self.app.REMINDER_ACTION_SENT])
        self.assertEqual([record["Source"] for record in records], ["daily_send_all", "daily_send_all"])
        self.assertEqual([record["Client Name"] for record in records], ["Client A", "Client B"])

        state = self.app.st.session_state
        self.assertEqual(state["main_section_tab"], "Reminders")
        self.assertEqual(len(state["deleted_reminders"]), 2)
        self.assertEqual(len(state["wa_reminder_log"]), 2)
        self.assertEqual(state["wa_message"], "Reminder message")
        self.assertEqual(state["_bulk_sent_success"], "Marked 2 reminders as sent.")
        self.assertFalse(state["daily_reveal_hidden_reminders"])

    def test_send_all_does_not_update_local_state_when_tracker_write_fails(self):
        rows = [sample_reminder_row()]

        with (
            patch.object(self.app, "append_tracker_rows", return_value=False),
            patch.object(self.app, "build_whatsapp_message_for_row", return_value="Reminder message"),
        ):
            self.app.mark_all_listed_reminders_sent_action(rows, "daily", "wa_message")

        state = self.app.st.session_state
        self.assertEqual(state["deleted_reminders"], [])
        self.assertEqual(state["wa_reminder_log"], [])
        self.assertNotIn("wa_message", state)
        self.assertIn("was not saved", state["_pending_action_sync_warning"])

    def test_refresh_outcomes_syncs_actions_and_reloads_dataset(self):
        tracked_record = sample_reminder_row(
            **{
                "Action": self.app.REMINDER_ACTION_SENT,
                "ActionedAt": "2026-05-16T12:00:00",
                "Actioned By": "Nurse",
            }
        )

        with (
            patch.object(self.app, "load_action_tracker_records_for_clinic", return_value=[tracked_record]) as load_actions,
            patch.object(self.app, "load_shared_dataset_for_clinic") as load_dataset,
        ):
            self.app.refresh_outcome_results_state()

        state = self.app.st.session_state
        load_actions.assert_called_once_with("Clinic Workflow")
        load_dataset.assert_called_once()
        self.assertEqual(len(state["deleted_reminders"]), 1)
        self.assertEqual(state["deleted_reminders"][0]["Action"], self.app.REMINDER_ACTION_SENT)
        self.assertEqual(len(state["wa_reminder_log"]), 1)
        self.assertEqual(state["_outcomes_refresh_success"], "Stats refreshed.")

    def test_decline_action_preserves_existing_sent_state_when_tracker_write_fails(self):
        row = sample_reminder_row()
        sent_record = dict(row, Action=self.app.REMINDER_ACTION_SENT, ActionedAt="2026-05-16T12:00:00")
        state = self.app.st.session_state
        state["deleted_reminders"] = [sent_record]
        state["wa_reminder_log"] = [{
            "Client Name": row["Client Name"],
            "RemindedAt": "2026-05-16T12:00:00",
            "ReminderKey": list(self.app.hidden_reminder_key(row)),
        }]

        with patch.object(self.app, "append_tracker_row", return_value=False):
            self.app.decline_reminder_action(row, "daily")

        self.assertEqual(state["deleted_reminders"], [sent_record])
        self.assertEqual(len(state["wa_reminder_log"]), 1)
        self.assertIn("was not saved", state["_pending_action_sync_warning"])


if __name__ == "__main__":
    unittest.main()
