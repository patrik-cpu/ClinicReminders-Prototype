import contextlib
import importlib
import io
import unittest
from datetime import date

import pandas as pd


class StatisticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            cls.app = importlib.import_module("reminders_app_v3")

    def setUp(self):
        state = self.app.st.session_state
        for key in list(state.keys()):
            del state[key]

    def make_generated_rows(self):
        return pd.DataFrame(
            [
                {
                    "Reminder Date": "16 May 2026",
                    "Due Date": "16 May 2026",
                    "Charge Date": "16 May 2025",
                    "Client Name": "Client A",
                    "Animal Name": "Pet A",
                    "Plan Item": "Rabies",
                    "Qty": 1,
                    "Days": 365,
                },
                {
                    "Reminder Date": "16 May 2026",
                    "Due Date": "16 May 2026",
                    "Charge Date": "16 May 2025",
                    "Client Name": "Client B",
                    "Animal Name": "Pet B",
                    "Plan Item": "Librela",
                    "Qty": 1,
                    "Days": 30,
                },
                {
                    "Reminder Date": "10 May 2026",
                    "Due Date": "10 May 2026",
                    "Charge Date": "10 May 2025",
                    "Client Name": "Client C",
                    "Animal Name": "Pet C",
                    "Plan Item": "Rabies",
                    "Qty": 1,
                    "Days": 365,
                },
            ]
        )

    def make_action_records(self):
        return [
            {
                "Reminder Date": "16 May 2026",
                "Due Date": "16 May 2026",
                "Charge Date": "16 May 2025",
                "Client Name": "Client A",
                "Animal Name": "Pet A",
                "Plan Item": "Rabies",
                "Action": self.app.REMINDER_ACTION_SENT,
                "ActionedAt": "2026-05-16T09:00:00",
                "Actioned By": "Nurse A",
            },
            {
                "Reminder Date": "16 May 2026",
                "Due Date": "16 May 2026",
                "Charge Date": "16 May 2025",
                "Client Name": "Client B",
                "Animal Name": "Pet B",
                "Plan Item": "Librela",
                "Action": self.app.REMINDER_ACTION_DECLINED,
                "ActionedAt": "2026-05-16T10:00:00",
                "Actioned By": "Nurse B",
            },
        ]

    def test_statistics_summary_counts_generated_actioned_and_completion(self):
        summary = self.app.statistics_summary_for_period(
            self.make_generated_rows(),
            self.make_action_records(),
            "Today",
            today=date(2026, 5, 16),
        )

        self.assertEqual(summary["generated"], 2)
        self.assertEqual(summary["actioned"], 2)
        self.assertEqual(summary["sent"], 1)
        self.assertEqual(summary["declined"], 1)
        self.assertEqual(summary["remaining"], 0)
        self.assertEqual(summary["completion_rate"], 1.0)

    def test_statistics_team_and_item_frames(self):
        generated = self.make_generated_rows()
        actions = self.make_action_records()

        team = self.app.build_statistics_team_frame(actions, "Today", today=date(2026, 5, 16))
        self.assertEqual(set(team["User"]), {"Nurse A", "Nurse B"})
        self.assertEqual(int(team["Actioned"].sum()), 2)

        items = self.app.build_statistics_item_frame(generated, actions, "Today", today=date(2026, 5, 16))
        item_rows = {row["Item"]: row for row in items.to_dict("records")}
        self.assertEqual(item_rows["Rabies"]["Generated"], 1)
        self.assertEqual(item_rows["Rabies"]["Sent"], 1)
        self.assertEqual(item_rows["Librela"]["Declined"], 1)


if __name__ == "__main__":
    unittest.main()
