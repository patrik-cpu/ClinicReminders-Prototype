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
        self.assertEqual(state["deleted_reminders"], [])
        self.assertEqual(state["wa_reminder_log"], [])
        self.assertEqual(
            state["_deleted_reminder_remove_keys_once"],
            [list(self.app.hidden_reminder_key(row))],
        )
        self.assertFalse(state["daily_reveal_hidden_reminders"])
        save_settings.assert_called_once()


if __name__ == "__main__":
    unittest.main()
