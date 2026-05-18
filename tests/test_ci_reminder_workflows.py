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

        records = tracker.action_records()
        actions = [record["Action"] for record in records]
        self.assertEqual(actions, [
            self.app.REMINDER_ACTION_SENT,
            self.app.REMINDER_ACTION_DECLINED,
            "active",
        ])
        self.assertEqual(records[0]["ActionedAt"], "2026-05-16T12:00:00")
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
