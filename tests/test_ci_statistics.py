import contextlib
import importlib
import io
import unittest
from datetime import date
from unittest import mock

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

    def test_stats_team_frame_combines_outcomes_and_actioning(self):
        outcome_sender = pd.DataFrame(
            [
                {
                    "Sender": "Nurse A",
                    "Sent": 3,
                    "Successes": 1,
                    "Pending": 1,
                    "No Match": 1,
                    "Success Rate": 1 / 3,
                    "Revenue": 120,
                },
            ]
        )

        team = self.app.build_stats_team_frame(
            outcome_sender,
            self.make_action_records(),
            "Today",
            today=date(2026, 5, 16),
        )
        rows = {row["Team Member"]: row for row in team.to_dict("records")}

        self.assertEqual(rows["Nurse A"]["Sent Reminders"], 3)
        self.assertEqual(rows["Nurse A"]["Successes"], 1)
        self.assertEqual(rows["Nurse A"]["Actioned"], 1)
        self.assertEqual(rows["Nurse A"]["Sent Actions"], 1)
        self.assertEqual(rows["Nurse B"]["Sent Reminders"], 0)
        self.assertEqual(rows["Nurse B"]["Declined Actions"], 1)

    def test_stats_actioning_column_configs_explain_headers(self):
        item_config = self.app.stats_item_actioning_column_config()
        team_config = self.app.stats_team_column_config()

        self.assertIn("scheduled for this item", item_config["Scheduled reminders"]["help"])
        self.assertIn("marked sent or declined", item_config["Actioned"]["help"])
        self.assertIn("outcome matching", team_config["Sent Reminders"]["help"])
        self.assertIn("All reminders this team member", team_config["Actioned"]["help"])

    def test_statistics_display_frame_renames_generated_for_users(self):
        frame = pd.DataFrame([{"Generated": 2, "Actioned": 1}])

        display_frame = self.app.prepare_statistics_display_frame(frame)

        self.assertIn("Scheduled reminders", display_frame.columns)
        self.assertNotIn("Generated", display_frame.columns)
        self.assertEqual(display_frame.iloc[0]["Scheduled reminders"], 2)

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
        self.assertEqual(str(row["Charge Date"].date()), "2025-05-01")
        self.assertEqual(str(row["Reminder Date"].date()), "2026-05-01")
        self.assertEqual(str(row["Sent Date"].date()), "2026-05-01")
        self.assertEqual(str(row["Due Date"].date()), "2026-05-10")
        self.assertEqual(str(row["Window Starts"].date()), "2026-04-10")
        self.assertEqual(str(row["Window Ends"].date()), "2026-06-09")
        self.assertEqual(str(row["Next Purchase Date"].date()), "2026-05-12")
        self.assertEqual(int(row["Success Gap Days"]), 376)
        self.assertEqual(float(row["Revenue"]), 100.0)
        self.assertEqual(row["Matched Item"], "Rabies Vaccine")

    def test_outcome_as_of_date_uses_latest_uploaded_sale_date(self):
        sales = pd.DataFrame(
            [
                {"ChargeDate": "2025-01-01"},
                {"ChargeDate": "2025-09-30"},
                {"ChargeDate": ""},
            ]
        )

        self.assertEqual(
            self.app.outcome_as_of_date(sales, fallback=date(2026, 5, 18)),
            date(2025, 9, 30),
        )

    def test_reminder_outcomes_status_uses_dataset_as_of_date_by_default(self):
        actions = [
            {
                "Reminder Date": "25 Sep 2025",
                "Due Date": "10 Oct 2025",
                "Charge Date": "10 Jul 2025",
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
                    "ChargeDate": "2025-09-30",
                    "Client Name": "Other Client",
                    "Animal Name": "Other Pet",
                    "Item Name": "Rabies Vaccine",
                    "Amount": 100,
                }
            ]
        )

        outcomes = self.app.build_reminder_outcomes(
            actions,
            sales,
            due_date_window_days=14,
            rules={},
        )

        self.assertEqual(outcomes.iloc[0]["Outcome"], "Pending")

    def test_outcome_period_filter_uses_dataset_as_of_date(self):
        outcomes = pd.DataFrame(
            [
                {"Sent Date": pd.Timestamp("2025-09-30"), "Outcome": "No Match"},
                {"Sent Date": pd.Timestamp("2025-09-20"), "Outcome": "No Match"},
            ]
        )

        filtered = self.app.filter_outcomes_for_period(
            outcomes,
            "7 days",
            today=date(2025, 9, 30),
        )

        self.assertEqual(len(filtered), 1)
        self.assertEqual(str(filtered.iloc[0]["Sent Date"].date()), "2025-09-30")

    def test_sent_reminders_period_filter_uses_sent_date_labels(self):
        outcomes = pd.DataFrame(
            [
                {"Sent Date": pd.Timestamp("2025-09-30"), "Outcome": "No Match", "Client Name": "Today"},
                {"Sent Date": pd.Timestamp("2025-09-24"), "Outcome": "No Match", "Client Name": "Seven Days"},
                {"Sent Date": pd.Timestamp("2025-09-01"), "Outcome": "No Match", "Client Name": "Thirty Days"},
                {"Sent Date": pd.Timestamp("2025-08-31"), "Outcome": "No Match", "Client Name": "All Time"},
            ]
        )

        today_rows = self.app.filter_sent_outcomes_for_period(outcomes, "Today", today=date(2025, 9, 30))
        seven_day_rows = self.app.filter_sent_outcomes_for_period(outcomes, "Previous 7 days", today=date(2025, 9, 30))
        thirty_day_rows = self.app.filter_sent_outcomes_for_period(outcomes, "Previous 30 days", today=date(2025, 9, 30))
        all_time_rows = self.app.filter_sent_outcomes_for_period(outcomes, "All-time", today=date(2025, 9, 30))

        self.assertEqual(today_rows["Client Name"].tolist(), ["Today"])
        self.assertEqual(seven_day_rows["Client Name"].tolist(), ["Today", "Seven Days"])
        self.assertEqual(thirty_day_rows["Client Name"].tolist(), ["Today", "Seven Days", "Thirty Days"])
        self.assertEqual(len(all_time_rows), 4)

    def test_reminder_outcomes_use_actioned_date_as_sent_date_for_historical_backtests(self):
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
        self.assertEqual(str(row["Reminder Date"].date()), "2025-05-01")
        self.assertEqual(str(row["Sent Date"].date()), "2026-05-18")
        self.assertEqual(str(row["Actioned Date"].date()), "2026-05-18")
        self.assertEqual(int(row["Success Gap Days"]), 376)

    def test_outcome_sent_display_columns_start_with_audit_trail_dates(self):
        self.assertEqual(
            self.app.OUTCOME_SENT_DISPLAY_COLUMNS[:7],
            [
                "Charge Date",
                "Reminder Date",
                "Sent Date",
                "Due Date",
                "Window Starts",
                "Window Ends",
                "Next Purchase Date",
            ],
        )

    def test_reminder_outcomes_search_around_due_date_even_before_reminder_date(self):
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
                    "ChargeDate": "2026-04-30",
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
        self.assertEqual(str(row["Window Starts"].date()), "2026-04-26")
        self.assertEqual(str(row["Success Date"].date()), "2026-04-30")
        self.assertEqual(float(row["Revenue"]), 50.0)

    def test_reminder_outcomes_match_overdue_reminder_purchase_around_due_date(self):
        actions = [
            {
                "Reminder Date": "30 Jun 2026",
                "Due Date": "10 May 2026",
                "Charge Date": "10 May 2025",
                "Client Name": "Client A",
                "Animal Name": "Pet A",
                "Plan Item": "Rabies Vaccine",
                "Action": self.app.REMINDER_ACTION_SENT,
                "ActionedAt": "2026-06-30T09:00:00",
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
            today=date(2026, 7, 15),
            rules={},
        )

        row = outcomes.iloc[0]
        self.assertEqual(row["Outcome"], "Reminder Success")
        self.assertEqual(str(row["Window Starts"].date()), "2026-04-10")
        self.assertEqual(str(row["Success Date"].date()), "2026-05-12")

    def test_reminder_outcomes_do_not_count_original_billed_charge_as_success(self):
        actions = [
            {
                "Reminder Date": "01 May 2026",
                "Due Date": "31 May 2026",
                "Charge Date": "01 May 2026",
                "Client Name": "Client A",
                "Animal Name": "Pet A",
                "Plan Item": "Caniverm",
                "Action": self.app.REMINDER_ACTION_SENT,
                "ActionedAt": "2026-05-01T09:00:00",
                "Actioned By": "Nurse A",
            }
        ]
        sales = pd.DataFrame(
            [
                {
                    "ChargeDate": "2026-05-01",
                    "Client Name": "Client A",
                    "Animal Name": "Pet A",
                    "Item Name": "Caniverm",
                    "Amount": 50,
                },
                {
                    "ChargeDate": "2026-05-31",
                    "Client Name": "Client A",
                    "Animal Name": "Pet A",
                    "Item Name": "Caniverm",
                    "Amount": 60,
                },
            ]
        )

        outcomes = self.app.build_reminder_outcomes(
            actions,
            sales,
            due_date_window_days=30,
            today=date(2026, 7, 1),
            rules={},
        )

        row = outcomes.iloc[0]
        self.assertEqual(row["Outcome"], "Reminder Success")
        self.assertEqual(str(row["Window Starts"].date()), "2026-05-02")
        self.assertEqual(str(row["Success Date"].date()), "2026-05-31")
        self.assertEqual(float(row["Revenue"]), 60.0)

    def test_reminder_outcomes_use_exact_item_before_overlapping_search_terms(self):
        actions = [
            {
                "Reminder Date": "18 Mar 2026",
                "Due Date": "01 Apr 2026",
                "Charge Date": "01 Jan 2026",
                "Client Name": "Client A",
                "Animal Name": "Pet A",
                "Plan Item": "Bravecto Large Dog 20-40kg",
                "Action": self.app.REMINDER_ACTION_SENT,
                "ActionedAt": "2026-03-18T09:00:00",
                "Actioned By": "Nurse A",
                "ReminderDetails": [
                    {
                        "Reminder Date": "18 Mar 2026",
                        "Due Date": "01 Apr 2026",
                        "Charge Date": "01 Jan 2026",
                        "Animal Name": "Pet A",
                        "Plan Item": "Bravecto Large Dog 20-40kg",
                        "Search Terms": "bravecto",
                    }
                ],
            },
            {
                "Reminder Date": "15 Feb 2026",
                "Due Date": "01 Mar 2026",
                "Charge Date": "01 Jan 2026",
                "Client Name": "Client A",
                "Animal Name": "Pet A",
                "Plan Item": "Bravecto Plus Cat",
                "Action": self.app.REMINDER_ACTION_SENT,
                "ActionedAt": "2026-02-15T09:00:00",
                "Actioned By": "Nurse A",
                "ReminderDetails": [
                    {
                        "Reminder Date": "15 Feb 2026",
                        "Due Date": "01 Mar 2026",
                        "Charge Date": "01 Jan 2026",
                        "Animal Name": "Pet A",
                        "Plan Item": "Bravecto Plus Cat",
                        "Search Terms": "bravecto | bravecto plus",
                    }
                ],
            },
        ]
        sales = pd.DataFrame(
            [
                {
                    "ChargeDate": "2026-01-01",
                    "Client Name": "Client A",
                    "Animal Name": "Pet A",
                    "Item Name": "Bravecto Large Dog 20-40kg",
                    "Amount": 100,
                },
                {
                    "ChargeDate": "2026-06-01",
                    "Client Name": "Client A",
                    "Animal Name": "Pet A",
                    "Item Name": "Bravecto Large Dog 20-40kg",
                    "Amount": 100,
                },
                {
                    "ChargeDate": "2026-01-01",
                    "Client Name": "Client A",
                    "Animal Name": "Pet A",
                    "Item Name": "Bravecto Plus Cat",
                    "Amount": 80,
                },
                {
                    "ChargeDate": "2026-03-05",
                    "Client Name": "Client A",
                    "Animal Name": "Pet A",
                    "Item Name": "Bravecto Plus Cat",
                    "Amount": 80,
                },
                {
                    "ChargeDate": "2026-04-01",
                    "Client Name": "Client A",
                    "Animal Name": "Pet A",
                    "Item Name": "Bravecto Plus Cat",
                    "Amount": 80,
                },
            ]
        )

        outcomes = self.app.build_reminder_outcomes(
            actions,
            sales,
            due_date_window_days=14,
            today=date(2026, 7, 1),
            rules={
                "bravecto plus": {"days": 60, "visible_text": "Bravecto Plus"},
                "bravecto": {"days": 90, "visible_text": "Bravecto"},
            },
        )

        rows = {row["Item"]: row for row in outcomes.to_dict("records")}
        dog_row = rows["Bravecto Large Dog 20-40kg"]
        plus_row = rows["Bravecto Plus Cat"]
        self.assertEqual(dog_row["Outcome"], "No Match")
        self.assertEqual(int(dog_row["Avg Item Purchase Gap Days"]), 151)
        self.assertEqual(int(dog_row["Overall Repeat Purchases"]), 1)
        self.assertEqual(int(dog_row["Overall Purchases"]), 2)
        self.assertEqual(float(dog_row["Repeat Purchase %"]), 0.5)
        self.assertEqual(int(dog_row["Desired Gap Days"]), 90)
        self.assertEqual(plus_row["Outcome"], "Reminder Success")
        self.assertEqual(str(plus_row["Success Date"].date()), "2026-03-05")
        self.assertEqual(int(plus_row["Desired Gap Days"]), 60)
        self.assertEqual(int(plus_row["Success Gap Days"]), 63)
        self.assertEqual(int(plus_row["Overall Repeat Purchases"]), 2)
        self.assertEqual(int(plus_row["Overall Purchases"]), 3)
        self.assertAlmostEqual(float(plus_row["Repeat Purchase %"]), 2 / 3)
        self.assertEqual(self.app.outcome_search_terms_for_record(actions[1], "Bravecto Plus Cat", {}), ["bravecto plus"])

    def test_reminder_outcomes_exact_variant_allows_extra_sale_item_words(self):
        actions = [
            {
                "Reminder Date": "18 Mar 2025",
                "Due Date": "01 Apr 2025",
                "Charge Date": "01 Jan 2025",
                "Client Name": "Client A",
                "Animal Name": "Pet A",
                "Plan Item": "Bravecto 112.5mg 2-4.5kg",
                "Action": self.app.REMINDER_ACTION_SENT,
                "ActionedAt": "2026-05-18T09:00:00",
                "Actioned By": "Nurse A",
                "ReminderDetails": [
                    {
                        "Reminder Date": "18 Mar 2025",
                        "Due Date": "01 Apr 2025",
                        "Charge Date": "01 Jan 2025",
                        "Animal Name": "Pet A",
                        "Plan Item": "Bravecto 112.5mg 2-4.5kg",
                        "Search Terms": "bravecto",
                    }
                ],
            }
        ]
        sales = pd.DataFrame(
            [
                {
                    "ChargeDate": "2025-01-01",
                    "Client Name": "Client A",
                    "Animal Name": "Pet A",
                    "Item Name": "Bravecto 112.5mg 2-4.5kg",
                    "Amount": 80,
                },
                {
                    "ChargeDate": "2025-04-02",
                    "Client Name": "Client A",
                    "Animal Name": "Pet A",
                    "Item Name": "Bravecto 112.5mg 2-4.5kg DOG",
                    "Amount": 90,
                },
            ]
        )

        outcomes = self.app.build_reminder_outcomes(
            actions,
            sales,
            due_date_window_days=14,
            today=date(2025, 5, 1),
            rules={"bravecto": {"days": 90, "visible_text": "Bravecto"}},
        )

        self.assertEqual(outcomes.iloc[0]["Outcome"], "Reminder Success")
        self.assertEqual(outcomes.iloc[0]["Matched Item"], "Bravecto 112.5mg 2-4.5kg Dog")
        self.assertEqual(float(outcomes.iloc[0]["Revenue"]), 90.0)

    def test_reminder_outcomes_counts_success_inside_user_defined_window(self):
        actions = [
            {
                "Reminder Date": "18 Mar 2025",
                "Due Date": "01 Apr 2025",
                "Charge Date": "01 Jan 2025",
                "Client Name": "Client A",
                "Animal Name": "Pet A",
                "Plan Item": "Bravecto",
                "Days": "90",
                "Action": self.app.REMINDER_ACTION_SENT,
                "ActionedAt": "2026-05-18T09:00:00",
                "Actioned By": "Nurse A",
            }
        ]
        sales = pd.DataFrame(
            [
                {
                    "ChargeDate": "2025-01-01",
                    "Client Name": "Client A",
                    "Animal Name": "Pet A",
                    "Item Name": "Bravecto",
                    "Amount": 80,
                },
                {
                    "ChargeDate": "2025-04-01",
                    "Client Name": "Client A",
                    "Animal Name": "Pet A",
                    "Item Name": "Bravecto",
                    "Amount": 90,
                },
            ]
        )

        outcomes = self.app.build_reminder_outcomes(
            actions,
            sales,
            due_date_window_days=14,
            rules={"bravecto": {"days": 90, "visible_text": "Bravecto"}},
        )

        self.assertEqual(outcomes.iloc[0]["Outcome"], "Reminder Success")
        self.assertEqual(str(outcomes.iloc[0]["Success Date"].date()), "2025-04-01")
        self.assertEqual(int(outcomes.iloc[0]["Success Gap Days"]), 90)
        self.assertEqual(float(outcomes.iloc[0]["Revenue"]), 90.0)

    def test_reminder_outcomes_prefers_sent_days_over_base_rule_days_for_quantity_rules(self):
        actions = [
            {
                "Reminder Date": "16 Jun 2025",
                "Due Date": "30 Jun 2025",
                "Charge Date": "01 Jan 2025",
                "Client Name": "Client A",
                "Animal Name": "Pet A",
                "Plan Item": "Bravecto",
                "Days": "180",
                "Action": self.app.REMINDER_ACTION_SENT,
                "ActionedAt": "2025-06-16T09:00:00",
                "Actioned By": "Nurse A",
            }
        ]
        sales = pd.DataFrame(
            [
                {
                    "ChargeDate": "2025-01-01",
                    "Client Name": "Client A",
                    "Animal Name": "Pet A",
                    "Item Name": "Bravecto",
                    "Amount": 80,
                },
                {
                    "ChargeDate": "2025-06-30",
                    "Client Name": "Client A",
                    "Animal Name": "Pet A",
                    "Item Name": "Bravecto",
                    "Amount": 90,
                },
            ]
        )

        outcomes = self.app.build_reminder_outcomes(
            actions,
            sales,
            due_date_window_days=14,
            today=date(2025, 7, 20),
            rules={"bravecto": {"days": 90, "use_qty": True, "visible_text": "Bravecto"}},
        )

        row = outcomes.iloc[0]
        self.assertEqual(row["Outcome"], "Reminder Success")
        self.assertEqual(int(row["Desired Gap Days"]), 180)
        self.assertEqual(int(row["Success Gap Days"]), 180)

    def test_reminder_outcomes_counts_first_future_purchase_gap_as_success(self):
        actions = [
            {
                "Reminder Date": "18 Mar 2025",
                "Due Date": "15 Apr 2025",
                "Charge Date": "01 Jan 2025",
                "Client Name": "Client A",
                "Animal Name": "Pet A",
                "Plan Item": "Bravecto Large Dog 20-40kg",
                "Days": "90",
                "Action": self.app.REMINDER_ACTION_SENT,
                "ActionedAt": "2026-05-18T09:00:00",
                "Actioned By": "Nurse A",
            }
        ]
        sales = pd.DataFrame(
            [
                {
                    "ChargeDate": "2025-01-01",
                    "Client Name": "Client A",
                    "Animal Name": "Pet A",
                    "Item Name": "Bravecto Large Dog 20-40kg",
                    "Amount": 80,
                },
                {
                    "ChargeDate": "2025-04-01",
                    "Client Name": "Client A",
                    "Animal Name": "Pet A",
                    "Item Name": "Bravecto Large Dog 20-40kg",
                    "Amount": 90,
                },
            ]
        )

        outcomes = self.app.build_reminder_outcomes(
            actions,
            sales,
            due_date_window_days=14,
            rules={"bravecto": {"days": 90, "visible_text": "Bravecto"}},
        )

        self.assertEqual(outcomes.iloc[0]["Outcome"], "Reminder Success")
        self.assertEqual(str(outcomes.iloc[0]["Next Purchase Date"].date()), "2025-04-01")
        self.assertEqual(int(outcomes.iloc[0]["Next Purchase Gap Days"]), 90)
        self.assertEqual(str(outcomes.iloc[0]["Success Date"].date()), "2025-04-01")

    def test_reminder_outcomes_do_not_skip_first_future_purchase_for_later_window_match(self):
        actions = [
            {
                "Reminder Date": "18 Mar 2025",
                "Due Date": "01 Apr 2025",
                "Charge Date": "01 Jan 2025",
                "Client Name": "Client A",
                "Animal Name": "Pet A",
                "Plan Item": "Bravecto",
                "Days": "90",
                "Action": self.app.REMINDER_ACTION_SENT,
                "ActionedAt": "2026-05-18T09:00:00",
                "Actioned By": "Nurse A",
            }
        ]
        sales = pd.DataFrame(
            [
                {
                    "ChargeDate": "2025-01-01",
                    "Client Name": "Client A",
                    "Animal Name": "Pet A",
                    "Item Name": "Bravecto",
                    "Amount": 80,
                },
                {
                    "ChargeDate": "2025-02-01",
                    "Client Name": "Client A",
                    "Animal Name": "Pet A",
                    "Item Name": "Bravecto",
                    "Amount": 70,
                },
                {
                    "ChargeDate": "2025-04-01",
                    "Client Name": "Client A",
                    "Animal Name": "Pet A",
                    "Item Name": "Bravecto",
                    "Amount": 90,
                },
            ]
        )

        outcomes = self.app.build_reminder_outcomes(
            actions,
            sales,
            due_date_window_days=14,
            today=date(2025, 5, 1),
            rules={"bravecto": {"days": 90, "visible_text": "Bravecto"}},
        )

        self.assertEqual(outcomes.iloc[0]["Outcome"], "No Match")
        self.assertEqual(str(outcomes.iloc[0]["Next Purchase Date"].date()), "2025-02-01")
        self.assertEqual(int(outcomes.iloc[0]["Next Purchase Gap Days"]), 31)
        self.assertTrue(pd.isna(outcomes.iloc[0]["Success Date"]))

    def test_historical_reminder_generation_can_count_future_purchase_success(self):
        state = self.app.st.session_state
        state["clinic_id"] = "clinic-historical-outcomes"
        state["user_name"] = "Nurse A"
        rules = {"bravecto": {"days": 90, "visible_text": "Bravecto"}}
        sales = pd.DataFrame(
            [
                {
                    "ChargeDate": "2025-01-01",
                    "Client Name": "Client A",
                    "Animal Name": "Pet A",
                    "Item Name": "Bravecto Large Dog 20-40kg",
                    "Amount": 80,
                },
                {
                    "ChargeDate": "2025-04-01",
                    "Client Name": "Client A",
                    "Animal Name": "Pet A",
                    "Item Name": "Bravecto Large Dog 20-40kg",
                    "Amount": 90,
                },
            ]
        )

        historical_source = self.app.filter_sales_as_of_date(sales, date(2025, 3, 31))
        prepared = self.app.build_prepared_reminder_rows(historical_source, rules)
        due_rows = prepared.loc[
            pd.to_datetime(prepared["ReminderDateTs"], errors="coerce").dt.date == date(2025, 4, 1)
        ]
        grouped = self.app.bundle_client_reminders_by_window(due_rows, window_days=0, rules=rules)
        values = self.app.action_tracker_row_values(
            grouped.iloc[0].to_dict(),
            self.app.REMINDER_ACTION_SENT,
            now=self.app.datetime(2025, 3, 31, 9, 0, 0),
        )
        actions = [self.app.action_tracker_values_to_record(self.app.ACTION_TRACKER_HEADERS, values)]

        outcomes = self.app.build_reminder_outcomes(
            actions,
            sales,
            due_date_window_days=14,
            rules=rules,
        )

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes.iloc[0]["Outcome"], "Reminder Success")
        self.assertEqual(str(outcomes.iloc[0]["Charge Date"].date()), "2025-01-01")
        self.assertEqual(str(outcomes.iloc[0]["Due Date"].date()), "2025-04-01")
        self.assertEqual(str(outcomes.iloc[0]["Success Date"].date()), "2025-04-01")
        self.assertEqual(int(outcomes.iloc[0]["Success Gap Days"]), 90)

    def test_grouped_reminder_outcomes_count_each_detail_as_own_instance(self):
        actions = [
            {
                "Reminder Date": "08 Mar 2026 | 09 Mar 2026",
                "Due Date": "08 Mar 2026 | 09 Mar 2026",
                "Charge Date": "09 Jan 2026",
                "Client Name": "Client A",
                "Animal Name": "Chester",
                "Plan Item": "Dermosc... and Revolution",
                "Action": self.app.REMINDER_ACTION_SENT,
                "ActionedAt": "2026-03-08T09:00:00",
                "Actioned By": "Nurse A",
                "ReminderDetails": [
                    {
                        "Reminder Date": "08 Mar 2026",
                        "Due Date": "08 Mar 2026",
                        "Charge Date": "09 Jan 2026",
                        "Animal Name": "Chester",
                        "Plan Item": "Dermosc...",
                        "Qty": "1",
                        "Days": "30",
                    },
                    {
                        "Reminder Date": "09 Mar 2026",
                        "Due Date": "09 Mar 2026",
                        "Charge Date": "09 Jan 2026",
                        "Animal Name": "Chester",
                        "Plan Item": "Revolution",
                        "Qty": "1",
                        "Days": "30",
                    },
                ],
            }
        ]
        sales = pd.DataFrame(
            [
                {
                    "ChargeDate": "2026-03-09",
                    "Client Name": "Client A",
                    "Animal Name": "Chester",
                    "Item Name": "Dermosc...",
                    "Amount": 40,
                },
                {
                    "ChargeDate": "2026-03-10",
                    "Client Name": "Client A",
                    "Animal Name": "Chester",
                    "Item Name": "Revolution",
                    "Amount": 60,
                },
            ]
        )

        outcomes = self.app.build_reminder_outcomes(
            actions,
            sales,
            due_date_window_days=14,
            today=date(2026, 4, 1),
        )

        self.assertEqual(len(outcomes), 2)
        rows = {row["Item"]: row for row in outcomes.to_dict("records")}
        self.assertEqual(set(rows), {"Dermosc...", "Revolution"})
        self.assertEqual(rows["Dermosc..."]["Outcome"], "Reminder Success")
        self.assertEqual(rows["Revolution"]["Outcome"], "Reminder Success")
        self.assertEqual(float(outcomes["Revenue"].sum()), 100.0)

    def test_outcomes_count_multiple_sent_steps_for_same_purchase_once(self):
        actions = [
            {
                "Reminder Date": "18 Mar 2025",
                "Due Date": "01 Apr 2025",
                "Charge Date": "01 Jan 2025",
                "Client Name": "Client A",
                "Animal Name": "Pet A",
                "Plan Item": "Bravecto",
                "Days": "90",
                "Action": self.app.REMINDER_ACTION_SENT,
                "ActionedAt": "2025-03-18T09:00:00",
                "Actioned By": "Nurse A",
            },
            {
                "Reminder Date": "25 Mar 2025",
                "Due Date": "01 Apr 2025",
                "Charge Date": "01 Jan 2025",
                "Client Name": "Client A",
                "Animal Name": "Pet A",
                "Plan Item": "Bravecto",
                "Days": "90",
                "Action": self.app.REMINDER_ACTION_SENT,
                "ActionedAt": "2025-03-25T09:00:00",
                "Actioned By": "Nurse B",
            },
            {
                "Reminder Date": "08 Apr 2025",
                "Due Date": "01 Apr 2025",
                "Charge Date": "01 Jan 2025",
                "Client Name": "Client A",
                "Animal Name": "Pet A",
                "Plan Item": "Bravecto",
                "Days": "90",
                "Action": self.app.REMINDER_ACTION_SENT,
                "ActionedAt": "2025-04-08T09:00:00",
                "Actioned By": "Nurse C",
            },
        ]
        sales = pd.DataFrame(
            [
                {
                    "ChargeDate": "2025-01-01",
                    "Client Name": "Client A",
                    "Animal Name": "Pet A",
                    "Item Name": "Bravecto",
                    "Amount": 80,
                },
                {
                    "ChargeDate": "2025-04-01",
                    "Client Name": "Client A",
                    "Animal Name": "Pet A",
                    "Item Name": "Bravecto",
                    "Amount": 95,
                },
            ]
        )

        outcomes = self.app.build_reminder_outcomes(
            actions,
            sales,
            due_date_window_days=14,
            today=date(2025, 5, 1),
        )
        summary = self.app.summarize_outcomes(outcomes)

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(summary["sent"], 1)
        self.assertEqual(summary["successes"], 1)
        self.assertEqual(summary["success_rate"], 1.0)
        self.assertEqual(float(summary["revenue"]), 95.0)
        self.assertEqual(outcomes.iloc[0]["Sender"], "Nurse A")
        self.assertEqual(str(outcomes.iloc[0]["Reminder Date"].date()), "2025-03-18")

    def test_action_tracker_preserves_grouped_reminder_details(self):
        row = {
            "Reminder Date": "08 Mar 2026 | 09 Mar 2026",
            "Due Date": "08 Mar 2026 | 09 Mar 2026",
            "Charge Date": "09 Jan 2026",
            "Client Name": "Client A",
            "Animal Name": "Chester",
            "Plan Item": "Dermosc... and Revolution",
            "Qty": "NA",
            "Days": "NA",
            "ReminderDetails": [
                {"Reminder Date": "08 Mar 2026", "Due Date": "08 Mar 2026", "Animal Name": "Chester", "Plan Item": "Dermosc..."},
                {"Reminder Date": "09 Mar 2026", "Due Date": "09 Mar 2026", "Animal Name": "Chester", "Plan Item": "Revolution"},
            ],
        }

        values = self.app.action_tracker_row_values(row, self.app.REMINDER_ACTION_SENT, now=self.app.datetime(2026, 3, 8, 9, 0, 0))
        record = self.app.action_tracker_values_to_record(self.app.ACTION_TRACKER_HEADERS, values)

        self.assertEqual(len(record["ReminderDetails"]), 2)
        self.assertEqual(record["ReminderDetails"][0]["Plan Item"], "Dermosc...")
        self.assertEqual(record["ReminderDetails"][1]["Plan Item"], "Revolution")

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

    def test_reminder_outcomes_match_truncated_display_item_to_raw_sale_item(self):
        actions = [
            {
                "Reminder Date": "01 May 2026",
                "Due Date": "10 May 2026",
                "Charge Date": "01 May 2025",
                "Client Name": "Client A",
                "Animal Name": "Pet A",
                "Plan Item": "Dermosc...",
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
                    "Item Name": "Dermoscent Essential 6 Spot-On",
                    "Amount": 75,
                }
            ]
        )

        outcomes = self.app.build_reminder_outcomes(
            actions,
            sales,
            due_date_window_days=30,
            today=date(2026, 6, 1),
        )

        self.assertEqual(outcomes.iloc[0]["Outcome"], "Reminder Success")
        self.assertEqual(float(outcomes.iloc[0]["Revenue"]), 75.0)

    def test_reminder_outcomes_match_visible_text_to_search_term_raw_sale_item(self):
        actions = [
            {
                "Reminder Date": "01 May 2026",
                "Due Date": "10 May 2026",
                "Charge Date": "01 May 2025",
                "Client Name": "Client\u00a0A",
                "Animal Name": "Pet A",
                "Plan Item": "Revolution",
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
                    "Item Name": "Selamectin spot-on",
                    "Amount": 125,
                }
            ]
        )
        rules = {"selamectin": {"days": 30, "visible_text": "Revolution"}}

        outcomes = self.app.build_reminder_outcomes(
            actions,
            sales,
            due_date_window_days=30,
            today=date(2026, 6, 1),
            rules=rules,
        )

        self.assertEqual(outcomes.iloc[0]["Outcome"], "Reminder Success")
        self.assertEqual(outcomes.iloc[0]["Matched Item"], "Selamectin spot-on")

    def test_reminder_outcomes_use_stored_search_term_not_display_item(self):
        actions = [
            {
                "Reminder Date": "01 May 2026",
                "Due Date": "10 May 2026",
                "Charge Date": "01 May 2025",
                "Client Name": "Client A",
                "Animal Name": "Pet A",
                "Plan Item": "Annual Vaccine Reminder",
                "Action": self.app.REMINDER_ACTION_SENT,
                "ActionedAt": "2026-05-01T09:00:00",
                "Actioned By": "Nurse A",
                "ReminderDetails": [
                    {
                        "Reminder Date": "01 May 2026",
                        "Due Date": "10 May 2026",
                        "Charge Date": "01 May 2025",
                        "Animal Name": "Pet A",
                        "Plan Item": "Annual Vaccine Reminder",
                        "Search Terms": "rabies",
                    }
                ],
            }
        ]
        sales = pd.DataFrame(
            [
                {
                    "ChargeDate": "2026-05-12",
                    "Client Name": "Client A",
                    "Animal Name": "Pet A",
                    "Item Name": "Nobivac Rabies 3 Year",
                    "Amount": 150,
                }
            ]
        )

        outcomes = self.app.build_reminder_outcomes(
            actions,
            sales,
            due_date_window_days=30,
            today=date(2026, 6, 1),
        )

        self.assertEqual(outcomes.iloc[0]["Outcome"], "Reminder Success")
        self.assertEqual(outcomes.iloc[0]["Matched Item"], "Nobivac Rabies 3 Year")
        self.assertEqual(float(outcomes.iloc[0]["Revenue"]), 150.0)

    def test_reminder_outcomes_match_action_tracker_roundtrip_search_term(self):
        state = self.app.st.session_state
        state["clinic_id"] = "clinic-outcome-roundtrip"
        state["user_name"] = "Nurse A"
        reminder_row = {
            "Reminder Date": "01 May 2026",
            "Due Date": "10 May 2026",
            "Charge Date": "01 May 2025",
            "Client Name": "Client A",
            "Animal Name": "Pet A",
            "Plan Item": "Rabies Vaccine",
            "Qty": "1",
            "Days": "365",
            "ReminderDetails": [
                {
                    "Reminder Date": "01 May 2026",
                    "Due Date": "10 May 2026",
                    "Charge Date": "01 May 2025",
                    "Animal Name": "Pet A",
                    "Plan Item": "Rabies Vaccine",
                    "Search Terms": "rabies",
                }
            ],
        }
        values = self.app.action_tracker_row_values(
            reminder_row,
            self.app.REMINDER_ACTION_SENT,
            now=self.app.datetime(2026, 5, 1, 9, 0, 0),
        )
        actions = [self.app.action_tracker_values_to_record(self.app.ACTION_TRACKER_HEADERS, values)]
        sales = pd.DataFrame(
            [
                {
                    "ChargeDate": "2026-05-12",
                    "Client Name": "Client A",
                    "Animal Name": "Pet A",
                    "Item Name": "Nobivac Rabies 3 Year",
                    "Amount": 150,
                }
            ]
        )

        outcomes = self.app.build_reminder_outcomes(
            actions,
            sales,
            due_date_window_days=30,
            today=date(2026, 6, 1),
            rules={"rabies": {"days": 365, "visible_text": "Rabies Vaccine"}},
        )

        self.assertEqual(outcomes.iloc[0]["Outcome"], "Reminder Success")
        self.assertEqual(outcomes.iloc[0]["Matched Item"], "Nobivac Rabies 3 Year")

    def test_reminder_outcomes_match_legacy_visible_item_using_current_rule_term(self):
        actions = [
            {
                "Reminder Date": "01 May 2026",
                "Due Date": "10 May 2026",
                "Charge Date": "01 May 2025",
                "Client Name": "Client A",
                "Animal Name": "Pet A",
                "Plan Item": "Rabies Vaccine",
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
                    "Item Name": "Nobivac Rabies 3 Year",
                    "Amount": 150,
                }
            ]
        )

        outcomes = self.app.build_reminder_outcomes(
            actions,
            sales,
            due_date_window_days=30,
            today=date(2026, 6, 1),
            rules={"rabies": {"days": 365, "visible_text": "Rabies Vaccine"}},
        )

        self.assertEqual(outcomes.iloc[0]["Outcome"], "Reminder Success")
        self.assertEqual(outcomes.iloc[0]["Matched Item"], "Nobivac Rabies 3 Year")

    def test_reminder_outcomes_match_legacy_visible_item_without_saved_rule(self):
        actions = [
            {
                "Reminder Date": "01 May 2026",
                "Due Date": "10 May 2026",
                "Charge Date": "01 May 2025",
                "Client Name": "Client A",
                "Animal Name": "Pet A",
                "Plan Item": "Rabies Vaccine",
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
                    "Item Name": "Nobivac Rabies 3 Year",
                    "Amount": 150,
                }
            ]
        )

        outcomes = self.app.build_reminder_outcomes(
            actions,
            sales,
            due_date_window_days=30,
            today=date(2026, 6, 1),
            rules={},
        )

        self.assertEqual(outcomes.iloc[0]["Outcome"], "Reminder Success")
        self.assertEqual(outcomes.iloc[0]["Matched Item"], "Nobivac Rabies 3 Year")

    def test_outcome_group_frame_summarizes_success_rates(self):
        outcomes = pd.DataFrame(
            [
                {"Sender": "Nurse A", "Item": "Rabies", "Outcome": "Reminder Success", "Success Gap Days": 365, "Desired Gap Days": 365, "Avg Item Purchase Gap Days": 370, "Overall Repeat Purchases": 3, "Overall Purchases": 4, "Revenue": 120},
                {"Sender": "Nurse A", "Item": "Rabies", "Outcome": "No Match", "Success Gap Days": None, "Desired Gap Days": 365, "Avg Item Purchase Gap Days": 370, "Overall Repeat Purchases": 3, "Overall Purchases": 4, "Revenue": 0},
                {"Sender": "Nurse A", "Item": "Rabies", "Outcome": "Pending", "Success Gap Days": None, "Desired Gap Days": 365, "Avg Item Purchase Gap Days": 370, "Overall Repeat Purchases": 3, "Overall Purchases": 4, "Revenue": 0},
                {"Sender": "Nurse A", "Item": "Rabies", "Outcome": "Not Measurable", "Success Gap Days": None, "Desired Gap Days": 365, "Avg Item Purchase Gap Days": 370, "Overall Repeat Purchases": 3, "Overall Purchases": 4, "Revenue": 0},
                {"Sender": "Nurse B", "Item": "Bravecto", "Outcome": "Reminder Success", "Success Gap Days": 95, "Desired Gap Days": 90, "Avg Item Purchase Gap Days": 120, "Overall Repeat Purchases": 2, "Overall Purchases": 5, "Revenue": 80},
            ]
        )

        grouped = self.app.build_outcome_group_frame(outcomes, "Sender")
        rows = {row["Sender"]: row for row in grouped.to_dict("records")}

        self.assertEqual(rows["Nurse A"]["Sent"], 4)
        self.assertEqual(rows["Nurse A"]["Successes"], 1)
        self.assertEqual(rows["Nurse A"]["Pending"], 1)
        self.assertEqual(rows["Nurse A"]["No Match"], 2)
        self.assertEqual(rows["Nurse A"]["Success Rate"], 1 / 4)
        self.assertEqual(rows["Nurse A"]["Avg Success Gap Days"], 365)
        self.assertEqual(rows["Nurse A"]["Overall Repeat Purchases"], 3)
        self.assertEqual(rows["Nurse A"]["Overall Purchases"], 4)
        self.assertEqual(rows["Nurse A"]["Repeat Purchase %"], 0.75)
        self.assertEqual(rows["Nurse B"]["Desired Gap Days"], 90)
        self.assertEqual(rows["Nurse B"]["Overall Repeat Purchases"], 2)
        self.assertEqual(rows["Nurse B"]["Overall Purchases"], 5)
        self.assertEqual(rows["Nurse B"]["Repeat Purchase %"], 0.4)
        self.assertLess(
            self.app.OUTCOME_ITEM_GROUP_COLUMNS.index("Avg Item Purchase Gap Days"),
            self.app.OUTCOME_ITEM_GROUP_COLUMNS.index("Overall Repeat Purchases"),
        )
        self.assertLess(
            self.app.OUTCOME_ITEM_GROUP_COLUMNS.index("Overall Repeat Purchases"),
            self.app.OUTCOME_ITEM_GROUP_COLUMNS.index("Overall Purchases"),
        )
        self.assertLess(
            self.app.OUTCOME_ITEM_GROUP_COLUMNS.index("Overall Purchases"),
            self.app.OUTCOME_ITEM_GROUP_COLUMNS.index("Repeat Purchase %"),
        )
        self.assertLess(
            self.app.OUTCOME_ITEM_GROUP_COLUMNS.index("Repeat Purchase %"),
            self.app.OUTCOME_ITEM_GROUP_COLUMNS.index("Revenue"),
        )

    def test_render_outcome_dataframe_uses_native_sortable_dataframe_for_summary_rows(self):
        frame = pd.DataFrame([
            {
                "Item": "Rabies",
                "Sent": 4,
                "Successes": 1,
                "Pending": 1,
                "No Match": 2,
                "Success Rate": 0.25,
                "Desired Gap Days": 365,
                "Avg Item Purchase Gap Days": 370,
                "Overall Repeat Purchases": 3,
                "Overall Purchases": 4,
                "Repeat Purchase %": 0.75,
                "Revenue": 120,
            }
        ])

        with (
            mock.patch.object(self.app.st, "markdown") as markdown,
            mock.patch.object(self.app.st, "button") as button,
            mock.patch.object(self.app.st, "dataframe") as dataframe,
        ):
            self.app.render_outcome_dataframe(frame, table_key="outcomes_by_item")

        dataframe.assert_called_once()
        markdown.assert_not_called()
        button.assert_not_called()
        rendered_frame = dataframe.call_args.args[0]
        column_config = dataframe.call_args.kwargs["column_config"]
        self.assertIn("Overall Avg Purchase Gap Days", rendered_frame.columns)
        self.assertIn("Overall Repeat Purchases", rendered_frame.columns)
        self.assertIn("Overall Purchases", rendered_frame.columns)
        self.assertIn("Repeat Purchase %", rendered_frame.columns)
        self.assertIn("Success Rate", column_config)
        self.assertIn("Repeat Purchase %", column_config)
        self.assertEqual(column_config["Overall Avg Purchase Gap Days"]["type_config"]["format"], "%.0f")
        self.assertEqual(column_config["Repeat Purchase %"]["type_config"]["format"], "percent")
        self.assertIn("average repeat-purchase gap", column_config["Overall Avg Purchase Gap Days"]["help"])
        self.assertIn("share of matching purchases", column_config["Repeat Purchase %"]["help"])
        self.assertIn("Whether the reminder is successful", column_config["Outcome"]["help"])
        self.assertNotIn("Avg Item Purchase Gap Days", rendered_frame.columns)

    def test_prepare_outcome_dataframe_for_display_formats_dates_without_time(self):
        frame = pd.DataFrame(
            [
                {
                    "Reminder Date": pd.Timestamp("2024-01-10"),
                    "Sent Date": pd.Timestamp("2024-01-13 00:00:00"),
                    "Actioned Date": "2024-02-14 09:30:00",
                    "Charge Date": pd.Timestamp("2024-01-01"),
                    "Due Date": pd.NaT,
                    "Window Starts": pd.Timestamp("2024-01-01"),
                    "Success Date": pd.Timestamp("2024-03-05"),
                    "Window Ends": pd.Timestamp("2024-04-30"),
                    "Next Purchase Date": pd.Timestamp("2024-03-06"),
                    "Avg Item Purchase Gap Days": 370,
                    "Overall Repeat Purchases": 3,
                    "Overall Purchases": 4,
                    "Repeat Purchase %": 0.75,
                    "Client Name": "Client A",
                }
            ]
        )

        display_frame = self.app.prepare_outcome_dataframe_for_display(frame)

        self.assertEqual(display_frame.iloc[0]["Sent Date"], "Jan-13-2024")
        self.assertEqual(display_frame.iloc[0]["Actioned Date"], "Feb-14-2024")
        self.assertEqual(display_frame.iloc[0]["Billed Date"], "Jan-01-2024")
        self.assertEqual(display_frame.iloc[0]["Reminder Date"], "Jan-10-2024")
        self.assertNotIn("Charge Date", display_frame.columns)
        self.assertIn("Overall Avg Purchase Gap Days", display_frame.columns)
        self.assertIn("Overall Repeat Purchases", display_frame.columns)
        self.assertIn("Overall Purchases", display_frame.columns)
        self.assertIn("Repeat Purchase %", display_frame.columns)
        self.assertEqual(display_frame.iloc[0]["Repeat Purchase %"], 0.75)
        self.assertNotIn("Avg Item Purchase Gap Days", display_frame.columns)
        self.assertEqual(display_frame.iloc[0]["Due Date"], "")
        self.assertEqual(display_frame.iloc[0]["Next Purchase Date"], "Mar-06-2024")
        self.assertEqual(display_frame.iloc[0]["Window Ends"], "Apr-30-2024")
        self.assertEqual(str(frame.iloc[0]["Sent Date"]), "2024-01-13 00:00:00")


if __name__ == "__main__":
    unittest.main()
