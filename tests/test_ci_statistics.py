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

    def test_statistics_completion_labels_follow_selected_period(self):
        self.assertEqual(
            self.app.statistics_completion_metric_labels("All time"),
            [
                "All time Generated",
                "All time Actioned",
                "All time Remaining",
                "All time Ring",
            ],
        )

    def test_statistics_exclusion_fingerprint_tracks_filter_changes(self):
        state = self.app.st.session_state
        state["exclusions"] = ["Rabies"]
        state["client_exclusions"] = ["Client A"]
        state["patient_exclusions"] = [{"client": "Client B", "patient": "Pet B"}]
        original_fp = self.app.statistics_exclusion_fp()

        state["patient_exclusions"] = [{"client": "Client B", "patient": "Pet C"}]
        changed_fp = self.app.statistics_exclusion_fp()

        self.assertNotEqual(original_fp, changed_fp)

    def test_reminder_outcomes_match_sent_reminder_to_future_sale(self):
        actions = [
            {
                "Reminder Date": "01 May 2026",
                "Due Date": "10 May 2026",
                "Charge Date": "01 May 2025",
                "Client Name": "Client A",
                "Animal Name": "Pet A",
                "Plan Item": "Rabies",
                "Action": self.app.REMINDER_ACTION_SENT,
                "ActionedAt": "2026-05-01T09:00:00",
                "Actioned By": "Nurse A",
            }
        ]
        sales = pd.DataFrame(
            [
                {
                    "ChargeDate": "2026-05-12",
                    "Client Name": "Client A",
                    "Animal Name": "Pet A",
                    "Item Name": "Rabies Vaccine",
                    "Amount": 100,
                }
            ]
        )

        outcomes = self.app.build_reminder_outcomes(
            actions,
            sales,
            due_date_window_days=30,
            on_time_grace_days=14,
            today=date(2026, 6, 1),
        )

        self.assertEqual(len(outcomes), 1)
        row = outcomes.iloc[0]
        self.assertEqual(row["Outcome"], "Reminder Success")
        self.assertEqual(row["Timing"], "On time")
        self.assertEqual(int(row["Days to Success"]), 11)
        self.assertEqual(int(row["Days vs Due Date"]), 2)
        self.assertEqual(float(row["Revenue"]), 100.0)
        self.assertEqual(row["Matched Item"], "Rabies Vaccine")

    def test_reminder_outcomes_use_reminder_date_for_historical_backtests(self):
        actions = [
            {
                "Reminder Date": "01 May 2025",
                "Due Date": "10 May 2025",
                "Charge Date": "01 May 2024",
                "Client Name": "Client A",
                "Animal Name": "Pet A",
                "Plan Item": "Rabies",
                "Action": self.app.REMINDER_ACTION_SENT,
                "ActionedAt": "2026-05-18T09:00:00",
                "Actioned By": "Nurse A",
            }
        ]
        sales = pd.DataFrame(
            [
                {
                    "ChargeDate": "2025-05-12",
                    "Client Name": "Client A",
                    "Animal Name": "Pet A",
                    "Item Name": "Rabies Vaccine",
                    "Amount": 100,
                }
            ]
        )

        outcomes = self.app.build_reminder_outcomes(
            actions,
            sales,
            due_date_window_days=30,
            on_time_grace_days=14,
            today=date(2026, 5, 18),
        )

        row = outcomes.iloc[0]
        self.assertEqual(row["Outcome"], "Reminder Success")
        self.assertEqual(str(row["Sent Date"].date()), "2025-05-01")
        self.assertEqual(str(row["Actioned Date"].date()), "2026-05-18")
        self.assertEqual(int(row["Days to Success"]), 11)

    def test_reminder_outcomes_search_around_due_date_but_not_before_sent_date(self):
        actions = [
            {
                "Reminder Date": "01 May 2026",
                "Due Date": "10 May 2026",
                "Charge Date": "01 May 2025",
                "Client Name": "Client A",
                "Animal Name": "Pet A",
                "Plan Item": "Rabies",
                "Action": self.app.REMINDER_ACTION_SENT,
                "ActionedAt": "2026-05-01T09:00:00",
                "Actioned By": "Nurse A",
            }
        ]
        sales = pd.DataFrame(
            [
                {
                    "ChargeDate": "2026-04-25",
                    "Client Name": "Client A",
                    "Animal Name": "Pet A",
                    "Item Name": "Rabies Vaccine",
                    "Amount": 50,
                },
                {
                    "ChargeDate": "2026-05-05",
                    "Client Name": "Client A",
                    "Animal Name": "Pet A",
                    "Item Name": "Rabies Vaccine",
                    "Amount": 100,
                },
            ]
        )

        outcomes = self.app.build_reminder_outcomes(
            actions,
            sales,
            due_date_window_days=14,
            today=date(2026, 6, 1),
        )

        row = outcomes.iloc[0]
        self.assertEqual(row["Outcome"], "Reminder Success")
        self.assertEqual(str(row["Window Starts"].date()), "2026-05-01")
        self.assertEqual(str(row["Success Date"].date()), "2026-05-05")
        self.assertEqual(float(row["Revenue"]), 100.0)

    def test_reminder_outcomes_report_no_match_after_window(self):
        actions = [
            {
                "Reminder Date": "01 May 2026",
                "Due Date": "10 May 2026",
                "Charge Date": "01 May 2025",
                "Client Name": "Client A",
                "Animal Name": "Pet A",
                "Plan Item": "Rabies",
                "Action": self.app.REMINDER_ACTION_SENT,
                "ActionedAt": "2026-05-01T09:00:00",
                "Actioned By": "Nurse A",
            }
        ]
        sales = pd.DataFrame(
            [
                {
                    "ChargeDate": "2026-05-12",
                    "Client Name": "Client A",
                    "Animal Name": "Pet A",
                    "Item Name": "Dental Scale",
                    "Amount": 100,
                }
            ]
        )

        outcomes = self.app.build_reminder_outcomes(
            actions,
            sales,
            due_date_window_days=7,
            today=date(2026, 6, 1),
        )

        self.assertEqual(outcomes.iloc[0]["Outcome"], "No Match")

    def test_outcome_group_frame_summarizes_success_rates(self):
        outcomes = pd.DataFrame(
            [
                {"Sender": "Nurse A", "Outcome": "Reminder Success", "Timing": "On time", "Days to Success": 5, "Days vs Due Date": 0, "Revenue": 120},
                {"Sender": "Nurse A", "Outcome": "No Match", "Timing": "", "Days to Success": None, "Days vs Due Date": None, "Revenue": 0},
                {"Sender": "Nurse B", "Outcome": "Reminder Success", "Timing": "Late", "Days to Success": 20, "Days vs Due Date": 15, "Revenue": 80},
            ]
        )

        grouped = self.app.build_outcome_group_frame(outcomes, "Sender")
        rows = {row["Sender"]: row for row in grouped.to_dict("records")}

        self.assertEqual(rows["Nurse A"]["Sent"], 2)
        self.assertEqual(rows["Nurse A"]["Successes"], 1)
        self.assertEqual(rows["Nurse A"]["Success Rate"], 0.5)
        self.assertEqual(rows["Nurse A"]["On-time Rate"], 1.0)
        self.assertEqual(rows["Nurse B"]["Late Recovery Rate"], 1.0)


if __name__ == "__main__":
    unittest.main()
