import contextlib
import importlib
import io
import unittest
from datetime import date
from unittest import mock

import pandas as pd


class RemindersBadgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            cls.app = importlib.import_module("reminders_app_v3")

    def setUp(self):
        state = self.app.st.session_state
        for key in list(state.keys()):
            del state[key]

    def test_reminders_badge_hides_at_zero_and_shows_active_count(self):
        self.assertEqual(self.app.reminders_badge_label(count=0), "Reminders")

        label = self.app.reminders_badge_label(count=3)

        self.assertIn("Reminders", label)
        self.assertIn("3 active reminders today", label)
        self.assertIn("data:image/svg+xml;base64", label)

    def test_today_active_reminder_count_excludes_actioned_rows(self):
        today_row = {
            "Reminder Date": "16 May 2026",
            "Due Date": "16 May 2026",
            "Client Name": "Client A",
            "Animal Name": "Pet A",
            "Plan Item": "Rabies",
        }
        actioned_today_row = {
            "Reminder Date": "16 May 2026",
            "Due Date": "16 May 2026",
            "Client Name": "Client B",
            "Animal Name": "Pet B",
            "Plan Item": "Librela",
        }
        tomorrow_row = {
            "Reminder Date": "17 May 2026",
            "Due Date": "17 May 2026",
            "Client Name": "Client C",
            "Animal Name": "Pet C",
            "Plan Item": "Annual Exam",
        }
        prepared = pd.DataFrame({
            "ReminderDateTs": pd.to_datetime(["2026-05-16"]),
            "NextDueDate": pd.to_datetime(["2026-05-16"]),
        })
        grouped = pd.DataFrame([today_row, actioned_today_row, tomorrow_row])

        state = self.app.st.session_state
        state["working_df"] = pd.DataFrame({"row": [1]})
        state["deleted_reminders"] = [
            {**actioned_today_row, "Action": self.app.REMINDER_ACTION_SENT},
        ]

        with (
            mock.patch.object(self.app, "get_applied_reminder_rules", return_value={}),
            mock.patch.object(self.app, "get_prepared_df", return_value=prepared),
            mock.patch.object(self.app, "bundle_client_reminders_by_window", return_value=grouped),
        ):
            count = self.app.get_today_active_reminder_count(today=date(2026, 5, 16))

        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
