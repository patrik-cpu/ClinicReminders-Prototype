import contextlib
import importlib
import io
import unittest
from datetime import date
from pathlib import Path
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

    def legacy_statistics_row_in_reminder_period(self, row, period, today=None):
        dates = self.app.statistics_row_dates(row)
        return any(self.app.statistics_date_in_period(value_date, period, today) for value_date in dates)

    def legacy_filter_actions_by_reminder_period(self, action_records, period, today=None):
        return [
            dict(record) for record in action_records
            if self.legacy_statistics_row_in_reminder_period(record, period, today)
        ]

    def legacy_expand_rows_for_statistics_item_period(self, rows, period, today=None):
        expanded_rows = self.app.expand_grouped_action_records(rows)
        return [
            dict(row) for row in expanded_rows
            if self.legacy_statistics_row_in_reminder_period(row, period, today)
        ]

    def legacy_statistics_summary_for_period(self, generated_df, action_records, period, today=None):
        mask = [
            self.legacy_statistics_row_in_reminder_period(row, period, today)
            for row in generated_df.to_dict("records")
        ]
        generated_period = generated_df.loc[mask].copy()
        generated_keys = {
            self.app.statistics_row_key(row)
            for row in generated_period.to_dict("records")
            if any(self.app.statistics_row_key(row))
        }
        actioned_by_key = {}
        for record in self.legacy_filter_actions_by_reminder_period(action_records, period, today):
            key = self.app.statistics_row_key(record)
            if not any(key) or key not in generated_keys:
                continue
            actioned_by_key[key] = record

        sent = sum(
            1 for record in actioned_by_key.values()
            if str(record.get("Action", "")).strip().lower() == self.app.REMINDER_ACTION_SENT
        )
        declined = sum(
            1 for record in actioned_by_key.values()
            if str(record.get("Action", "")).strip().lower() == self.app.REMINDER_ACTION_DECLINED
        )
        generated_count = len(generated_period.index)
        actioned_count = sent + declined
        return {
            "generated": generated_count,
            "actioned": actioned_count,
            "sent": sent,
            "declined": declined,
            "remaining": max(generated_count - actioned_count, 0),
            "completion_rate": (actioned_count / generated_count) if generated_count else 0.0,
        }

    def legacy_statistics_daily_frame(self, generated_df, action_records, period, today=None):
        today = today or self.app.user_today()
        generated_counts = {}
        mask = [
            self.legacy_statistics_row_in_reminder_period(row, period, today)
            for row in generated_df.to_dict("records")
        ]
        for row in generated_df.loc[mask].copy().to_dict("records"):
            row_date = self.app.statistics_primary_reminder_date(row)
            if row_date is not None:
                generated_counts[row_date] = generated_counts.get(row_date, 0) + 1

        action_counts = {}
        for record in self.legacy_filter_actions_by_reminder_period(action_records, period, today):
            row_date = self.app.statistics_primary_reminder_date(record)
            if row_date is None:
                continue
            action = str(record.get("Action", "")).strip().lower()
            counts = action_counts.setdefault(row_date, {"Sent": 0, "Declined": 0})
            if action == self.app.REMINDER_ACTION_SENT:
                counts["Sent"] += 1
            elif action == self.app.REMINDER_ACTION_DECLINED:
                counts["Declined"] += 1

        all_dates = sorted(set(generated_counts) | set(action_counts))
        start = self.app.statistics_period_start(period, today)
        if start is not None:
            all_dates = [day for day in all_dates if start <= day <= today]
        rows = []
        for row_date in all_dates:
            sent = action_counts.get(row_date, {}).get("Sent", 0)
            declined = action_counts.get(row_date, {}).get("Declined", 0)
            generated = generated_counts.get(row_date, 0)
            rows.append({
                "Date": pd.Timestamp(row_date),
                "Generated": generated,
                "Actioned": sent + declined,
                "Sent": sent,
                "Declined": declined,
                "Remaining": max(generated - sent - declined, 0),
            })
        return pd.DataFrame(rows)

    def legacy_statistics_item_frame(self, generated_df, action_records, period, today=None):
        generated_source_rows = (
            generated_df.to_dict("records")
            if generated_df is not None and not getattr(generated_df, "empty", True)
            else []
        )
        generated_rows = self.legacy_expand_rows_for_statistics_item_period(generated_source_rows, period, today)
        generated_rows = self.app.dedupe_statistics_item_cycle_rows(generated_rows)
        generated_counts = {}
        for row in generated_rows:
            item = self.app.normalize_display_case(str(row.get("Plan Item", "") or "Unknown").strip() or "Unknown")
            generated_counts[item] = generated_counts.get(item, 0) + 1

        action_counts = {}
        action_rows = self.legacy_expand_rows_for_statistics_item_period(action_records, period, today)
        for record in self.app.dedupe_statistics_item_cycle_rows(action_rows, latest_action=True):
            item = self.app.normalize_display_case(str(record.get("Plan Item", "") or "Unknown").strip() or "Unknown")
            counts = action_counts.setdefault(item, {"Sent": 0, "Declined": 0})
            action = str(record.get("Action", "")).strip().lower()
            if action == self.app.REMINDER_ACTION_SENT:
                counts["Sent"] += 1
            elif action == self.app.REMINDER_ACTION_DECLINED:
                counts["Declined"] += 1

        rows = []
        for item in sorted(set(generated_counts) | set(action_counts)):
            sent = action_counts.get(item, {}).get("Sent", 0)
            declined = action_counts.get(item, {}).get("Declined", 0)
            rows.append({
                "Item": item,
                "Generated": generated_counts.get(item, 0),
                "Actioned": sent + declined,
                "Sent": sent,
                "Declined": declined,
            })
        return (
            pd.DataFrame(rows).sort_values(["Generated", "Actioned"], ascending=False)
            if rows
            else pd.DataFrame(columns=["Item", "Generated", "Actioned", "Sent", "Declined"])
        )

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

    def test_statistics_period_refactor_matches_legacy_summary_daily_and_item_outputs(self):
        generated = pd.concat(
            [
                self.make_generated_rows(),
                pd.DataFrame([
                    {
                        "Reminder Date": "not a date",
                        "Due Date": "not a date",
                        "Charge Date": "16 May 2025",
                        "Client Name": "Client Invalid",
                        "Animal Name": "Pet Invalid",
                        "Plan Item": "Invalid",
                        "Qty": 1,
                        "Days": 365,
                    }
                ]),
            ],
            ignore_index=True,
        )
        actions = [
            *self.make_action_records(),
            {
                "Reminder Date": "not a date",
                "Due Date": "not a date",
                "Charge Date": "16 May 2025",
                "Client Name": "Client Invalid",
                "Animal Name": "Pet Invalid",
                "Plan Item": "Invalid",
                "Action": self.app.REMINDER_ACTION_SENT,
                "ActionedAt": "2026-05-16T11:00:00",
                "Actioned By": "Nurse Invalid",
            },
        ]

        for period in ("Today", "All time"):
            with self.subTest(period=period):
                today = date(2026, 5, 16)
                self.assertEqual(
                    self.app.statistics_summary_for_period(generated, actions, period, today=today),
                    self.legacy_statistics_summary_for_period(generated, actions, period, today=today),
                )
                pd.testing.assert_frame_equal(
                    self.app.build_statistics_daily_frame(generated, actions, period, today=today).reset_index(drop=True),
                    self.legacy_statistics_daily_frame(generated, actions, period, today=today).reset_index(drop=True),
                )
                pd.testing.assert_frame_equal(
                    self.app.build_statistics_item_frame(generated, actions, period, today=today).reset_index(drop=True),
                    self.legacy_statistics_item_frame(generated, actions, period, today=today).reset_index(drop=True),
                )

    def test_all_time_reminder_period_filter_avoids_per_date_period_checks(self):
        row = {"Reminder Date": "16 May 2026"}

        with mock.patch.object(
            self.app,
            "statistics_date_in_period",
            side_effect=AssertionError("all-time row filtering should not call per-date helper"),
        ):
            self.assertTrue(
                self.app.statistics_row_in_reminder_period(row, "All time", today=date(2026, 5, 16))
            )

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

    def test_statistics_team_frame_precomputed_action_rows_match_default_path(self):
        actions = [
            *self.make_action_records(),
            {
                "Reminder Date": "10 May 2026",
                "Due Date": "10 May 2026",
                "Charge Date": "10 May 2025",
                "Client Name": "Client C",
                "Animal Name": "Pet C",
                "Plan Item": "Rabies",
                "Action": self.app.REMINDER_ACTION_SENT,
                "ActionedAt": "2026-05-10T11:00:00",
                "Actioned By": "Nurse A",
            },
            {
                "Reminder Date": "16 May 2026",
                "Due Date": "16 May 2026",
                "Charge Date": "16 May 2025",
                "Client Name": "Client Invalid",
                "Animal Name": "Pet Invalid",
                "Plan Item": "Invalid",
                "Action": self.app.REMINDER_ACTION_SENT,
                "ActionedAt": "not a date",
                "Actioned By": "Nurse Invalid",
            },
        ]
        today = date(2026, 5, 16)
        action_rows = self.app.filter_actions_by_actioned_period(
            actions,
            "Last 7 days",
            today=today,
            include_parsed=True,
        )

        default_frame = self.app.build_statistics_team_frame(
            actions,
            "Last 7 days",
            today=today,
        )
        precomputed_frame = self.app.build_statistics_team_frame(
            actions,
            "Last 7 days",
            today=today,
            action_rows=action_rows,
        )

        pd.testing.assert_frame_equal(
            precomputed_frame.reset_index(drop=True),
            default_frame.reset_index(drop=True),
        )

    def test_statistics_item_frame_precomputed_rows_match_default_path(self):
        generated = self.make_generated_rows()
        actions = self.make_action_records()
        generated_rows = self.app.expand_rows_for_statistics_item_period(
            generated.to_dict("records"),
            "Today",
            today=date(2026, 5, 16),
        )
        action_rows = self.app.expand_rows_for_statistics_item_period(
            actions,
            "Today",
            today=date(2026, 5, 16),
        )

        default_frame = self.app.build_statistics_item_frame(
            generated,
            actions,
            "Today",
            today=date(2026, 5, 16),
        )
        precomputed_frame = self.app.build_statistics_item_frame(
            generated,
            actions,
            "Today",
            today=date(2026, 5, 16),
            generated_rows=generated_rows,
            action_rows=action_rows,
        )

        pd.testing.assert_frame_equal(
            precomputed_frame.reset_index(drop=True),
            default_frame.reset_index(drop=True),
        )

    def test_reminder_outcomes_precomputed_reduced_actions_match_default_path(self):
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
            },
            {
                "Reminder Date": "02 May 2026",
                "Due Date": "10 May 2026",
                "Charge Date": "01 May 2025",
                "Client Name": "Client B",
                "Animal Name": "Pet B",
                "Plan Item": "Librela",
                "Action": self.app.REMINDER_ACTION_DECLINED,
                "ActionedAt": "2026-05-02T09:00:00",
                "Actioned By": "Nurse B",
            },
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
        reduced_actions = self.app.reduce_action_tracker_records(actions)
        expanded_sent = self.app.expand_grouped_action_records([
            record for record in reduced_actions
            if str(record.get("Action", "")).strip().lower() == self.app.REMINDER_ACTION_SENT
        ])

        default_outcomes = self.app.build_reminder_outcomes(
            actions,
            sales,
            due_date_window_days=30,
            post_reminder_window_days=7,
            today=date(2026, 6, 1),
        )
        precomputed_outcomes = self.app.build_reminder_outcomes(
            reduced_actions,
            sales,
            due_date_window_days=30,
            post_reminder_window_days=7,
            today=date(2026, 6, 1),
            action_records_reduced=True,
            expanded_sent_records=expanded_sent,
        )

        pd.testing.assert_frame_equal(precomputed_outcomes, default_outcomes)

    def test_reminder_outcomes_without_sent_actions_skip_sales_preparation(self):
        actions = [
            {
                "Reminder Date": "02 May 2026",
                "Due Date": "10 May 2026",
                "Charge Date": "01 May 2025",
                "Client Name": "Client B",
                "Animal Name": "Pet B",
                "Plan Item": "Librela",
                "Action": self.app.REMINDER_ACTION_DECLINED,
                "ActionedAt": "2026-05-02T09:00:00",
                "Actioned By": "Nurse B",
            },
        ]
        sales = pd.DataFrame(
            [
                {
                    "ChargeDate": "2026-05-12",
                    "Client Name": "Client B",
                    "Animal Name": "Pet B",
                    "Item Name": "Librela",
                    "Amount": 100,
                }
            ]
        )

        with mock.patch.object(
            self.app,
            "prepare_sales_for_outcomes",
            side_effect=AssertionError("declined-only actions should not prepare sales"),
        ):
            outcomes = self.app.build_reminder_outcomes(
                actions,
                sales,
                today=date(2026, 6, 1),
            )

        pd.testing.assert_frame_equal(outcomes, self.app.empty_outcome_frame())

    def test_statistics_item_frame_splits_grouped_reminder_details(self):
        reminder_details = [
            {
                "Reminder Date": "16 May 2026",
                "Due Date": "16 May 2026",
                "Charge Date": "16 May 2025",
                "Animal Name": "Pet A",
                "Plan Item": "Rabies Vaccine",
                "Qty": "1",
                "Days": "365",
            },
            {
                "Reminder Date": "16 May 2026",
                "Due Date": "16 May 2026",
                "Charge Date": "16 May 2025",
                "Animal Name": "Pet A",
                "Plan Item": "Tricat Vaccine",
                "Qty": "1",
                "Days": "365",
            },
        ]
        grouped_row = {
            "Reminder Date": "16 May 2026",
            "Due Date": "16 May 2026",
            "Charge Date": "16 May 2025",
            "Client Name": "Client A",
            "Animal Name": "Pet A",
            "Plan Item": "Rabies and Tricat Vaccines",
            "Qty": "NA",
            "Days": "NA",
            "ReminderDetails": reminder_details,
        }
        generated = pd.DataFrame([grouped_row])
        actions = [
            {
                **grouped_row,
                "Action": self.app.REMINDER_ACTION_SENT,
                "ActionedAt": "2026-05-16T09:00:00",
                "Actioned By": "Nurse A",
            }
        ]

        items = self.app.build_statistics_item_frame(generated, actions, "Today", today=date(2026, 5, 16))
        item_rows = {row["Item"]: row for row in items.to_dict("records")}

        self.assertNotIn("Rabies and Tricat Vaccines", item_rows)
        self.assertEqual(item_rows["Rabies Vaccine"]["Generated"], 1)
        self.assertEqual(item_rows["Rabies Vaccine"]["Sent"], 1)
        self.assertEqual(item_rows["Tricat Vaccine"]["Generated"], 1)
        self.assertEqual(item_rows["Tricat Vaccine"]["Sent"], 1)

    def test_statistics_item_frame_dedupes_multiple_steps_for_same_purchase_cycle(self):
        first_step = {
            "Reminder Date": "01 May 2026",
            "Due Date": "31 May 2026",
            "Charge Date": "31 May 2025",
            "Client Name": "Client A",
            "Animal Name": "Pet A",
            "Plan Item": "Rabies Vaccine",
            "Qty": "1",
            "Days": "365",
        }
        second_step = {
            **first_step,
            "Reminder Date": "15 May 2026",
        }
        generated = pd.DataFrame([first_step, second_step])
        actions = [
            {
                **first_step,
                "Action": self.app.REMINDER_ACTION_SENT,
                "ActionedAt": "2026-05-01T09:00:00",
                "Actioned By": "Nurse A",
            },
            {
                **second_step,
                "Action": self.app.REMINDER_ACTION_SENT,
                "ActionedAt": "2026-05-15T09:00:00",
                "Actioned By": "Nurse A",
            },
        ]

        items = self.app.build_statistics_item_frame(generated, actions, "All time", today=date(2026, 5, 16))
        row = items.loc[items["Item"] == "Rabies Vaccine"].iloc[0]

        self.assertEqual(row["Generated"], 1)
        self.assertEqual(row["Actioned"], 1)
        self.assertEqual(row["Sent"], 1)
        self.assertEqual(row["Declined"], 0)

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
                    "Revenue": 120.4,
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
        self.assertEqual(rows["Nurse A"]["Revenue"], 120)
        self.assertEqual(rows["Nurse A"]["Actioned"], 1)
        self.assertEqual(rows["Nurse A"]["Sent Actions"], 1)
        self.assertEqual(rows["Nurse A"]["Sent %"], 1)
        self.assertEqual(rows["Nurse B"]["Sent Reminders"], 0)
        self.assertEqual(rows["Nurse B"]["Declined Actions"], 1)
        self.assertEqual(rows["Nurse B"]["Sent %"], 0)

    def test_stats_actioning_column_configs_explain_headers(self):
        item_config = self.app.stats_item_actioning_column_config()
        self.app.st.session_state["user_country"] = "United Kingdom"
        team_config = self.app.stats_team_column_config()

        for column in ["Item", "Scheduled reminders", "Actioned", "Actioned %", "Sent", "Declined", "Sent %"]:
            with self.subTest(column=column):
                self.assertIn(column, item_config)
                self.assertTrue(item_config[column]["help"])

        expected_team_columns = [
            "Revenue from Successes" if column == "Revenue" else column
            for column in self.app.STATS_TEAM_COLUMNS
        ]
        self.assertNotIn("Pending", expected_team_columns)
        self.assertNotIn("No Match", expected_team_columns)
        for column in expected_team_columns:
            with self.subTest(column=column):
                self.assertIn(column, team_config)
                self.assertTrue(team_config[column]["help"])
        self.assertEqual(team_config["Revenue from Successes"]["type_config"]["format"], "£%,.0f")

        self.assertNotIn("Pending", team_config)
        self.assertNotIn("No Match", team_config)

        self.assertIn("Unique item purchase cycles", item_config["Scheduled reminders"]["help"])
        self.assertIn("sent or declined", item_config["Actioned"]["help"])
        self.assertIn("Actioned item purchase cycles divided", item_config["Actioned %"]["help"])
        self.assertIn("Sent item purchase cycles divided", item_config["Sent %"]["help"])
        self.assertEqual(item_config["Actioned %"]["type_config"]["format"], "%.0f%%")
        self.assertEqual(item_config["Sent %"]["type_config"]["format"], "%.0f%%")
        self.assertIn("outcome matching", team_config["Sent Reminders"]["help"])
        self.assertIn("sent or declined", team_config["Actioned"]["help"])
        self.assertEqual(team_config["Success Rate"]["type_config"]["format"], "%.0f%%")

    def test_currency_format_uses_clinic_country_for_display(self):
        self.app.st.session_state["user_country"] = "United Arab Emirates"
        self.assertEqual(self.app.clinic_currency_number_format(), "AED %,.0f")
        self.assertEqual(self.app.format_outcome_currency(13051), "AED 13,051")

        self.app.st.session_state["user_country"] = "United States"
        self.assertEqual(self.app.clinic_currency_number_format(), "$%,.0f")
        self.assertEqual(self.app.format_outcome_currency(13051), "$13,051")

    def test_top_team_member_metric_uses_highest_success_revenue(self):
        self.app.st.session_state["user_country"] = "United Arab Emirates"
        sender_frame = pd.DataFrame(
            [
                {"Sender": "Nurse B", "Revenue": 2500, "Successes": 2},
                {"Sender": "Nurse A", "Revenue": 5000, "Successes": 1},
                {"Sender": "Nurse C", "Revenue": 0, "Successes": 8},
            ]
        )

        self.assertEqual(
            self.app.top_team_member_summary(sender_frame),
            ("Nurse A", 5000.0),
        )
        self.assertEqual(
            self.app.format_top_team_member_metric(sender_frame),
            "❤️ Nurse A · AED 5,000",
        )

    def test_top_team_member_metric_handles_no_success_revenue(self):
        sender_frame = pd.DataFrame(
            [
                {"Sender": "Nurse A", "Revenue": 0, "Successes": 0},
            ]
        )

        self.assertIsNone(self.app.top_team_member_summary(sender_frame))
        self.assertEqual(self.app.format_top_team_member_metric(sender_frame), "❤️ No successes yet")

    def test_all_paged_tables_use_50_rows(self):
        self.assertEqual(self.app.TABLE_PAGE_SIZE, 50)
        self.assertEqual(self.app.REMINDER_TABLE_PAGE_SIZE, 50)
        self.assertEqual(self.app.STATS_TABLE_PAGE_SIZE, 50)
        self.assertEqual(self.app.OUTCOME_SENT_PAGE_SIZE, 50)

    def test_pagination_caption_says_50_per_page(self):
        class FakeColumn:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        frame = pd.DataFrame({"Item": [f"Item {idx}" for idx in range(55)]})

        with (
            mock.patch.object(self.app.st, "caption") as caption,
            mock.patch.object(self.app.st, "columns", return_value=[FakeColumn(), FakeColumn(), FakeColumn()]),
            mock.patch.object(self.app.st, "button", return_value=False),
        ):
            paged = self.app.paginate_dataframe(frame, "stats_test", 50, "test rows")

        self.assertEqual(len(paged), 50)
        caption.assert_called_once_with("Showing 1-50 of 55 test rows (50 per page).")

    def test_paginate_sequence_caps_rows_and_keeps_absolute_indexes(self):
        class FakeColumn:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        rows = [{"row": idx} for idx in range(120)]
        self.app.st.session_state["actioned_test_page"] = 2

        with (
            mock.patch.object(self.app.st, "caption") as caption,
            mock.patch.object(self.app.st, "columns", return_value=[FakeColumn(), FakeColumn(), FakeColumn()]),
            mock.patch.object(self.app.st, "button", return_value=False),
        ):
            paged = self.app.paginate_sequence(rows, "actioned_test", 50, "actioned reminders")

        self.assertEqual(len(paged), 20)
        self.assertEqual(paged[0], (100, {"row": 100}))
        self.assertEqual(paged[-1], (119, {"row": 119}))
        caption.assert_called_once_with("Showing 101-120 of 120 actioned reminders (50 per page).")

    def test_actioned_reminder_sort_resets_actioned_page(self):
        self.app.st.session_state["reminders_actioned_reminders_page"] = 3

        self.app.set_actioned_reminder_sort("reminders", "Client Name")

        self.assertEqual(self.app.st.session_state["reminders_actioned_reminders_page"], 0)

    def test_reminder_action_button_static_css_is_table_scoped(self):
        css = self.app.reminder_action_button_static_css("daily")

        self.assertIn('[class*="st-key-daily_wa_"] button::before', css)
        self.assertIn(self.app.WHATSAPP_ICON_MASK_DATA_URI, css)
        self.assertIn('[class*="st-key-daily_sent_"] button p', css)
        self.assertIn('[class*="st-key-daily_decline_"] button p', css)

    def test_reminder_action_button_state_css_is_row_scoped_only(self):
        css = self.app.reminder_action_button_state_css(
            "daily_sent_7",
            "daily_decline_7",
            self.app.REMINDER_ACTION_SENT,
        )

        self.assertIn(".st-key-daily_sent_7 button", css)
        self.assertIn(".st-key-daily_decline_7 button", css)
        self.assertIn("background: #dcfce7", css)
        self.assertIn("opacity: 0.12", css)
        self.assertNotIn(self.app.WHATSAPP_ICON_MASK_DATA_URI, css)
        self.assertNotIn('[class*="st-key-daily_wa_"]', css)

    def test_reminder_action_button_state_css_batch_uses_one_style_block(self):
        css = self.app.reminder_action_button_state_css_batch([
            ("daily_sent_7", "daily_decline_7", self.app.REMINDER_ACTION_SENT),
            ("daily_sent_8", "daily_decline_8", self.app.REMINDER_ACTION_DECLINED),
        ])

        self.assertEqual(css.count("<style>"), 1)
        self.assertEqual(css.count("</style>"), 1)
        self.assertIn(".st-key-daily_sent_7 button", css)
        self.assertIn(".st-key-daily_decline_8 button", css)
        self.assertIn("background: #dcfce7", css)
        self.assertIn("background: #fee2e2", css)
        self.assertNotIn(self.app.WHATSAPP_ICON_MASK_DATA_URI, css)

    def test_render_outcome_dataframe_sorts_all_rows_before_pagination_without_global_controls(self):
        frame = pd.DataFrame(
            [
                {
                    "Item": f"Item {idx:02d}",
                    "Sent": 1,
                    "Capturable Revenue per Year": idx,
                }
                for idx in range(66)
            ]
        )
        self.app.st.session_state["stats_items_page"] = 1

        with (
            mock.patch.object(self.app.st, "selectbox") as selectbox,
            mock.patch.object(self.app.st, "radio") as radio,
            mock.patch.object(self.app.st, "caption"),
            mock.patch.object(self.app.st, "button", return_value=False),
            mock.patch.object(self.app.st, "dataframe") as dataframe,
        ):
            self.app.render_outcome_dataframe(
                frame,
                table_key="stats_items",
                default_sort_column="Capturable Revenue per Year",
                item_label="item rows",
            )

        rendered_frame = dataframe.call_args.args[0]
        self.assertEqual(len(rendered_frame), 16)
        self.assertEqual(rendered_frame.iloc[0]["Capturable Revenue per Year"], 15)
        self.assertEqual(rendered_frame.iloc[-1]["Capturable Revenue per Year"], 0)
        selectbox.assert_not_called()
        radio.assert_not_called()

    def test_stats_revenue_display_columns_keep_revenue_metrics_only(self):
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
                "Median Item Purchase Gap Days": 120,
                "Gap Day % to Desired": 370 / 365,
                "Overall Repeat Purchases": 3,
                "Overall Purchases": 4,
                "Unique Repeat Purchasing Patients": 2,
                "Unique Purchasing Patients": 3,
                "Repeat Purchase %": 0.75,
                "Revenue per Item": 120.4,
                "Revenue": 120.4,
                "Revenue per Year": 300.6,
                "Theoretical Max Revenue": 600.2,
                "Capturable Revenue per Year": 299.6,
                "Captured Revenue %": 0.5,
            }
        ])

        with (
            mock.patch.object(self.app.st, "caption"),
            mock.patch.object(self.app.st, "button", return_value=False),
            mock.patch.object(self.app.st, "dataframe") as dataframe,
        ):
            self.app.render_outcome_dataframe(
                frame,
                columns=self.app.STATS_REVENUE_DISPLAY_COLUMNS,
                table_key="stats_items",
                default_sort_column="Capturable Revenue per Year",
                item_label="item rows",
                display_column_labels=self.app.STATS_ITEMS_DISPLAY_COLUMN_LABELS,
        )

        rendered_frame = dataframe.call_args.args[0]
        self.assertEqual(
            rendered_frame.columns.tolist(),
            [
                "Item",
                "Potential Annual Revenue Lift",
                "Max Annual Revenue",
                "Current Annual Revenue",
                "Current Revenue Capture %",
                "Revenue per Item",
                "Desired Gap Days",
                "Actual Median Gap Days",
                "Annual Repeat Difference",
                "Unique Purchasing Patients",
                "Unique Repeat Purchasing Patients",
            ],
        )
        self.assertNotIn("Sent Reminders", rendered_frame.columns)
        self.assertNotIn("Successes", rendered_frame.columns)
        self.assertNotIn("Success Rate", rendered_frame.columns)
        self.assertNotIn("Revenue from Successes", rendered_frame.columns)
        self.assertNotIn("Calculated Revenue per Year", rendered_frame.columns)
        self.assertNotIn("Capturable Revenue Potential per Year", rendered_frame.columns)
        self.assertNotIn("Captured Revenue %", rendered_frame.columns)
        self.assertNotIn("Total Purchases", rendered_frame.columns)
        self.assertNotIn("Total Repeat Purchases", rendered_frame.columns)
        self.assertNotIn("Repeat Purchase %", rendered_frame.columns)
        self.assertIn("Desired Gap Days", rendered_frame.columns)
        self.assertIn("Actual Median Gap Days", rendered_frame.columns)
        self.assertIn("Annual Repeat Difference", rendered_frame.columns)
        self.assertIn("Unique Purchasing Patients", rendered_frame.columns)
        self.assertIn("Unique Repeat Purchasing Patients", rendered_frame.columns)
        self.assertNotIn("Sent", rendered_frame.columns)
        self.assertNotIn("Pending", rendered_frame.columns)
        self.assertNotIn("No Match", rendered_frame.columns)
        self.assertNotIn("Overall Avg Purchase Gap Days", rendered_frame.columns)
        self.assertNotIn("Gap Day % to Desired", rendered_frame.columns)
        self.assertNotIn("Overall Repeat Purchases", rendered_frame.columns)
        self.assertNotIn("Overall Purchases", rendered_frame.columns)
        self.assertIn("Max Annual Revenue", rendered_frame.columns)
        self.assertNotIn("Theoretical Max Revenue", rendered_frame.columns)
        self.assertEqual(rendered_frame.iloc[0]["Desired Gap Days"], 365)
        self.assertEqual(rendered_frame.iloc[0]["Actual Median Gap Days"], 120)
        self.assertAlmostEqual(rendered_frame.iloc[0]["Annual Repeat Difference"], (370 / 365) * 100)

    def test_stats_revenue_display_columns_include_median_gap_when_source_schema_is_old(self):
        frame = pd.DataFrame([
            {
                "Item": "Rabies",
                "Desired Gap Days": 365,
                "Avg Item Purchase Gap Days": 370,
                "Gap Day % to Desired": 370 / 365,
                "Revenue per Item": 120.4,
                "Revenue per Year": 300.6,
                "Theoretical Max Revenue": 600.2,
                "Capturable Revenue per Year": 299.6,
                "Captured Revenue %": 0.5,
            }
        ])

        normalized = self.app.ensure_stats_revenue_display_columns(frame)
        with (
            mock.patch.object(self.app.st, "caption"),
            mock.patch.object(self.app.st, "button", return_value=False),
            mock.patch.object(self.app.st, "dataframe") as dataframe,
        ):
            self.app.render_outcome_dataframe(
                normalized,
                columns=self.app.STATS_REVENUE_DISPLAY_COLUMNS,
                table_key="stats_items",
                default_sort_column="Capturable Revenue per Year",
                item_label="item rows",
                display_column_labels=self.app.STATS_ITEMS_DISPLAY_COLUMN_LABELS,
            )

        rendered_frame = dataframe.call_args.args[0]
        self.assertIn("Actual Median Gap Days", rendered_frame.columns)
        desired_index = rendered_frame.columns.get_loc("Desired Gap Days")
        self.assertEqual(rendered_frame.columns[desired_index + 1], "Actual Median Gap Days")
        self.assertEqual(rendered_frame.iloc[0]["Actual Median Gap Days"], 370)

    def test_stats_items_display_columns_keep_activity_and_receive_moved_outcome_metrics(self):
        actioning_frame = pd.DataFrame([
            {
                "Item": "Rabies",
                "Generated": 5,
                "Actioned": 3,
                "Sent": 2,
                "Declined": 1,
            }
        ])
        outcome_frame = pd.DataFrame([
            {
                "Item": "Rabies",
                "Sent": 4,
                "Successes": 1,
                "Success Rate": 0.25,
                "Revenue": 120.4,
                "Overall Purchases": 4,
                "Overall Repeat Purchases": 3,
                "Repeat Purchase %": 0.75,
                "Revenue per Year": 300.6,
                "Capturable Revenue per Year": 299.6,
            }
        ])

        rendered_frame = self.app.build_stats_items_display_frame(actioning_frame, outcome_frame)

        self.assertEqual(
            rendered_frame.columns.tolist(),
            [
                "Item",
                "Scheduled reminders",
                "Actioned",
                "Actioned %",
                "Sent Actions",
                "Declined Actions",
                "Sent %",
                "Sent Reminders",
                "Successes",
                "Success Rate",
                "Revenue from Successes",
                "Total Purchases",
                "Total Repeat Purchases",
                "Repeat Purchase %",
            ],
        )
        self.assertNotIn("Calculated Revenue per Year", rendered_frame.columns)
        self.assertNotIn("Capturable Revenue Potential per Year", rendered_frame.columns)
        self.assertEqual(rendered_frame.iloc[0]["Scheduled reminders"], 5)
        self.assertEqual(rendered_frame.iloc[0]["Actioned"], 3)
        self.assertEqual(rendered_frame.iloc[0]["Sent Actions"], 2)
        self.assertEqual(rendered_frame.iloc[0]["Declined Actions"], 1)
        self.assertAlmostEqual(rendered_frame.iloc[0]["Actioned %"], 60)
        self.assertAlmostEqual(rendered_frame.iloc[0]["Sent %"], 2 / 3 * 100)
        self.assertEqual(rendered_frame.iloc[0]["Sent Reminders"], 4)
        self.assertEqual(rendered_frame.iloc[0]["Success Rate"], 25)
        self.assertEqual(rendered_frame.iloc[0]["Revenue from Successes"], 120)
        self.assertEqual(rendered_frame.iloc[0]["Repeat Purchase %"], 75)

    def test_stats_sent_reminders_display_puts_sent_date_first(self):
        self.assertEqual(self.app.OUTCOME_SENT_DISPLAY_COLUMNS[0], "Sent Date")

    def test_stats_tabs_separate_all_time_revenue_from_period_tabs(self):
        self.assertEqual(self.app.STATS_REVENUE_SUBTAB, "Revenue")
        self.assertEqual(self.app.stats_subtab_display_label("Revenue"), "Revenue (All-time only)")
        self.assertEqual(self.app.stats_subtab_display_label("Reminders"), "Reminder Outcomes")
        self.assertEqual(self.app.STATS_PERIOD_FILTERED_SUBTABS, ["Items", "Successes", "Reminders", "Team"])
        self.assertEqual(self.app.STATS_SUBTABS, ["Revenue", "Items", "Successes", "Reminders", "Team"])

    def test_stats_sent_reminders_defaults_to_today_without_caption(self):
        source = Path(self.app.__file__).read_text(encoding="utf-8")
        selector_start = source.index("def render_stats_sent_reminders_period_selector")
        selector_end = source.index("def render_stats_successes_period_selector", selector_start)
        sent_tab_start = source.index('elif active_stats_subtab == "Reminders":')
        sent_tab_end = source.index('elif active_stats_subtab == "Team":', sent_tab_start)

        self.assertIn('default_period="Today"', source[selector_start:selector_end])
        self.assertNotIn("stats_sent_period_caption", source[sent_tab_start:sent_tab_end])

    def test_stats_items_highlight_styles_capturable_revenue_column(self):
        display_frame = pd.DataFrame(
            [
                {
                    "Item": "Rabies",
                    "Capturable Revenue per Year": 300,
                }
            ]
        )

        styled = self.app.style_outcome_dataframe_for_display(
            display_frame,
            highlight_column="Capturable Revenue per Year",
        )
        html = styled.to_html()

        self.assertIn("background-color: #e8f7ee", html)
        self.assertIn("font-weight: 700", html)

    def test_prepare_stats_team_display_frame_formats_success_rate_as_whole_percent(self):
        frame = pd.DataFrame([{"Team Member": "Nurse A", "Success Rate": 1 / 3, "Sent %": 0.5, "Revenue": 120}])

        display_frame = self.app.prepare_stats_team_display_frame(frame)

        self.assertAlmostEqual(display_frame.iloc[0]["Success Rate"], 100 / 3)
        self.assertEqual(display_frame.iloc[0]["Sent %"], 50)
        self.assertIn("Revenue from Successes", display_frame.columns)
        self.assertNotIn("Revenue", display_frame.columns)
        self.assertEqual(display_frame.iloc[0]["Revenue from Successes"], 120)
        self.assertAlmostEqual(frame.iloc[0]["Success Rate"], 1 / 3)

    def test_outcome_column_config_explains_every_stats_table_header(self):
        config = self.app.outcome_display_column_config()
        stats_column_sets = [
            self.app.OUTCOME_ITEM_GROUP_COLUMNS,
            self.app.OUTCOME_SENT_DISPLAY_COLUMNS,
            self.app.OUTCOME_SENDER_GROUP_COLUMNS,
        ]

        for columns in stats_column_sets:
            for column in columns:
                display_column = self.app.OUTCOME_DISPLAY_COLUMN_LABELS.get(column, column)
                with self.subTest(column=display_column):
                    self.assertIn(display_column, config)
                    self.assertTrue(config[display_column]["help"])

        self.assertIn("Percentage of sent reminders", config["Success Rate"]["help"])
        self.assertIn("Overall average purchase gap compared with the desired gap", config["Gap Day % to Desired"]["help"])
        self.assertIn("Repeat purchases (same client, animal, and item)", config["Overall Repeat Purchases"]["help"])
        self.assertIn("Percentage of matching purchases", config["Repeat Purchase %"]["help"])
        self.assertEqual(config["Sent"]["type_config"]["format"], "%d")
        self.assertEqual(config["No Match"]["type_config"]["format"], "%d")

    def test_stats_summary_cards_have_user_friendly_tooltips(self):
        expected_labels = [
            "Total Reminded Items",
            "Total Reminder Successes",
            "Total Success Rate",
            "Total Revenue from Successes",
            "Top Team Member",
        ]

        for label in expected_labels:
            with self.subTest(label=label):
                self.assertIn(label, self.app.STATS_SUMMARY_CARD_HELP)
                self.assertTrue(self.app.STATS_SUMMARY_CARD_HELP[label])

        with mock.patch.object(self.app.st, "markdown") as markdown:
            self.app.render_statistics_metric_card(
                "Total Reminded Items",
                "879",
                self.app.STATS_SUMMARY_CARD_HELP["Total Reminded Items"],
            )

        html = markdown.call_args.args[0]
        self.assertIn("Total Reminded Items", html)
        self.assertIn("column-help", html)
        self.assertIn("Unique reminded item purchase cycles", html)
        self.assertNotIn(">Sent<", html)

    def test_statistics_display_frame_renames_generated_and_adds_actioning_rates(self):
        frame = pd.DataFrame([{"Generated": 4, "Actioned": 2, "Sent": 1, "Declined": 1}])

        display_frame = self.app.prepare_statistics_display_frame(frame)

        self.assertEqual(
            display_frame.columns.tolist(),
            ["Scheduled reminders", "Actioned", "Actioned %", "Sent", "Declined", "Sent %"],
        )
        self.assertNotIn("Generated", display_frame.columns)
        self.assertEqual(display_frame.iloc[0]["Scheduled reminders"], 4)
        self.assertEqual(display_frame.iloc[0]["Actioned %"], 50)
        self.assertEqual(display_frame.iloc[0]["Sent %"], 50)

    def test_stats_export_csv_uses_display_frame_and_requested_columns(self):
        frame = pd.DataFrame(
            [
                {
                    "Item": "Rabies",
                    "Sent": 1,
                    "Success Rate": 0.026315,
                    "Desired Gap Days": 95.9,
                    "Revenue": 1257.4,
                    "Ignored": "not exported",
                },
                {
                    "Item": "Tricat",
                    "Sent": 2,
                    "Success Rate": 0.25,
                    "Desired Gap Days": 365,
                    "Revenue": 80.2,
                    "Ignored": "not exported",
                },
            ]
        )

        with mock.patch.object(self.app.st, "download_button") as download_button:
            self.app.render_stats_csv_export(
                frame,
                "Stats Items",
                "stats_items",
                columns=["Item", "Sent", "Success Rate", "Desired Gap Days", "Revenue"],
                display_preparer=self.app.prepare_outcome_dataframe_for_display,
            )

        download_button.assert_called_once()
        kwargs = download_button.call_args.kwargs
        exported = pd.read_csv(io.BytesIO(kwargs["data"]), dtype=str)

        self.assertEqual(download_button.call_args.args[0], "Export as CSV")
        self.assertEqual(kwargs["mime"], "text/csv")
        self.assertTrue(kwargs["file_name"].startswith("stats-items-"))
        self.assertEqual(
            exported.columns.tolist(),
            ["Item", "Sent", "Success Rate", "Desired Gap Days", "Revenue from Successes"],
        )
        self.assertEqual(len(exported), 2)
        self.assertEqual(exported.iloc[0]["Success Rate"], "0.03")
        self.assertEqual(exported.iloc[0]["Desired Gap Days"], "96")
        self.assertEqual(exported.iloc[0]["Revenue from Successes"], "1,257")
        self.assertNotIn("Ignored", exported.columns)

    def test_stats_export_csv_skips_empty_frames(self):
        with mock.patch.object(self.app.st, "download_button") as download_button:
            self.app.render_stats_csv_export(pd.DataFrame(), "Stats Items", "stats_items")

        download_button.assert_not_called()

    def test_stats_export_csv_reuses_cached_bytes_for_same_frame(self):
        frame = pd.DataFrame(
            [
                {"Item": "Rabies", "Sent": 1, "Success Rate": 0.25},
                {"Item": "Tricat", "Sent": 2, "Success Rate": 0.5},
            ]
        )
        real_csv_bytes = self.app.stats_export_csv_bytes

        with mock.patch.object(self.app, "stats_export_csv_bytes", wraps=real_csv_bytes) as csv_bytes:
            first = self.app.stats_export_csv_bytes_for_render(
                frame,
                "Stats Items",
                columns=["Item", "Sent", "Success Rate"],
                display_preparer=self.app.prepare_outcome_dataframe_for_display,
            )
            second = self.app.stats_export_csv_bytes_for_render(
                frame.copy(),
                "Stats Items",
                columns=["Item", "Sent", "Success Rate"],
                display_preparer=self.app.prepare_outcome_dataframe_for_display,
            )

        self.assertEqual(first, second)
        self.assertEqual(csv_bytes.call_count, 1)

    def test_stats_export_csv_cache_keeps_multiple_views(self):
        first_frame = pd.DataFrame(
            [
                {"Item": "Rabies", "Sent": 1, "Success Rate": 0.25},
                {"Item": "Tricat", "Sent": 2, "Success Rate": 0.5},
            ]
        )
        second_frame = pd.DataFrame(
            [
                {"Team Member": "Nurse A", "Sent Reminders": 3, "Success Rate": 1 / 3},
                {"Team Member": "Nurse B", "Sent Reminders": 1, "Success Rate": 0},
            ]
        )
        real_csv_bytes = self.app.stats_export_csv_bytes

        with mock.patch.object(self.app, "stats_export_csv_bytes", wraps=real_csv_bytes) as csv_bytes:
            first = self.app.stats_export_csv_bytes_for_render(
                first_frame,
                "Stats Items",
                columns=["Item", "Sent", "Success Rate"],
                display_preparer=self.app.prepare_outcome_dataframe_for_display,
            )
            second = self.app.stats_export_csv_bytes_for_render(
                second_frame,
                "Stats Team",
                columns=["Team Member", "Sent Reminders", "Success Rate"],
                display_preparer=self.app.prepare_stats_team_display_frame,
            )
            first_again = self.app.stats_export_csv_bytes_for_render(
                first_frame.copy(),
                "Stats Items",
                columns=["Item", "Sent", "Success Rate"],
                display_preparer=self.app.prepare_outcome_dataframe_for_display,
            )

        self.assertEqual(first_again, first)
        self.assertNotEqual(second, first)
        self.assertEqual(csv_bytes.call_count, 2)
        self.assertEqual(len(self.app.st.session_state["_stats_export_csv_cache"]["entries"]), 2)

    def test_statistics_exclusion_fingerprint_tracks_filter_changes(self):
        state = self.app.st.session_state
        state["exclusions"] = ["Rabies"]
        state["client_exclusions"] = ["Client A"]
        state["patient_exclusions"] = [{"client": "Client B", "patient": "Pet B"}]
        state["client_item_exclusions"] = [{"client": "Client C", "item": "Dental"}]
        original_fp = self.app.statistics_exclusion_fp()

        state["client_item_exclusions"] = [{"client": "Client C", "item": "Rabies"}]
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

    def test_stats_outcome_as_of_date_is_never_before_today(self):
        sales = pd.DataFrame(
            [
                {"ChargeDate": "2026-04-22"},
                {"ChargeDate": ""},
            ]
        )

        self.assertEqual(
            self.app.stats_outcome_as_of_date(sales, today=date(2026, 5, 20)),
            date(2026, 5, 20),
        )

    def test_stats_outcome_as_of_date_keeps_later_upload_date(self):
        sales = pd.DataFrame(
            [
                {"ChargeDate": "2026-06-01"},
            ]
        )

        self.assertEqual(
            self.app.stats_outcome_as_of_date(sales, today=date(2026, 5, 20)),
            date(2026, 6, 1),
        )

    def test_stats_outcomes_keep_today_sent_reminder_pending_when_upload_is_older(self):
        actions = [
            {
                "Reminder Date": "17 May 2024",
                "Due Date": "17 May 2024",
                "Charge Date": "17 Feb 2024",
                "Client Name": "Client A",
                "Animal Name": "Pet A",
                "Plan Item": "Deworm",
                "Action": self.app.REMINDER_ACTION_SENT,
                "ActionedAt": "2026-05-20T09:00:00",
                "Actioned By": "Nurse A",
            }
        ]
        sales = pd.DataFrame(
            [
                {
                    "ChargeDate": "2026-04-22",
                    "Client Name": "Other Client",
                    "Animal Name": "Other Pet",
                    "Item Name": "Deworm",
                    "Amount": 100,
                }
            ]
        )

        outcomes = self.app.build_reminder_outcomes(
            actions,
            sales,
            due_date_window_days=14,
            post_reminder_window_days=7,
            today=self.app.stats_outcome_as_of_date(sales, today=date(2026, 5, 20)),
            rules={},
        )

        self.assertEqual(outcomes.iloc[0]["Outcome"], "Pending")

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

    def test_sent_reminders_custom_period_filters_sent_date_range(self):
        outcomes = pd.DataFrame(
            [
                {"Sent Date": pd.Timestamp("2025-09-30"), "Outcome": "No Match", "Client Name": "Later"},
                {"Sent Date": pd.Timestamp("2025-09-24"), "Outcome": "No Match", "Client Name": "Inside"},
                {"Sent Date": pd.Timestamp("2025-09-01"), "Outcome": "No Match", "Client Name": "Earlier"},
            ]
        )

        rows = self.app.filter_sent_outcomes_for_period(
            outcomes,
            "Custom",
            today=date(2025, 9, 30),
            custom_range=(date(2025, 9, 20), date(2025, 9, 25)),
        )

        self.assertEqual(rows["Client Name"].tolist(), ["Inside"])

    def test_stats_custom_range_selection_detects_half_selected_range(self):
        self.assertTrue(self.app.stats_custom_range_selection_in_progress((date(2025, 9, 20),)))
        self.assertFalse(
            self.app.stats_custom_range_selection_in_progress(
                (date(2025, 9, 20), date(2025, 9, 25))
            )
        )

    def test_stats_date_range_selection_in_progress_checks_custom_widgets(self):
        self.app.st.session_state["stats_sent_reminders_period"] = "Custom"
        self.app.st.session_state["stats_sent_reminders_custom_range"] = (date(2025, 9, 20),)

        self.assertTrue(self.app.stats_date_range_selection_in_progress())

        self.app.st.session_state["stats_sent_reminders_custom_range"] = (
            date(2025, 9, 20),
            date(2025, 9, 25),
        )

        self.assertFalse(self.app.stats_date_range_selection_in_progress())

    def test_stats_custom_range_uses_separate_stored_completed_range(self):
        source = Path(self.app.__file__).read_text(encoding="utf-8")
        selector_start = source.index("def render_stats_period_selector")
        selector_end = source.index("def stats_sent_rows_for_render", selector_start)

        self.assertIn("stats_custom_range_storage_key(range_key)", source[selector_start:selector_end])
        self.assertIn("stored_range or (today_value, today_value)", source[selector_start:selector_end])
        self.assertIn("st.session_state[storage_key] = custom_range", source[selector_start:selector_end])

    def test_stats_custom_range_keeps_new_completed_widget_range(self):
        range_key = "stats_successes_custom_range"
        storage_key = self.app.stats_custom_range_storage_key(range_key)
        new_widget_range = (date(2026, 5, 20), date(2026, 5, 20))
        saved_range = (date(2026, 5, 10), date(2026, 5, 15))
        self.app.st.session_state["stats_successes_period"] = "Custom"
        self.app.st.session_state[range_key] = new_widget_range
        self.app.st.session_state[storage_key] = saved_range

        with (
            mock.patch.object(
                self.app.st,
                "segmented_control",
                return_value="Custom",
            ),
            mock.patch.object(
                self.app.st,
                "date_input",
                side_effect=lambda *_args, value=None, **_kwargs: value,
            ) as date_input,
        ):
            selected_period, custom_range = self.app.render_stats_period_selector(
                label="Successes period",
                filter_key="stats_successes_period",
                range_key=range_key,
                on_change=lambda: None,
            )

        self.assertEqual(selected_period, "Custom")
        self.assertEqual(custom_range, new_widget_range)
        self.assertEqual(self.app.st.session_state[range_key], new_widget_range)
        self.assertEqual(self.app.st.session_state[storage_key], new_widget_range)
        self.assertEqual(date_input.call_args.kwargs["value"], new_widget_range)

    def test_stats_custom_range_keeps_partial_widget_range_while_selecting(self):
        range_key = "stats_successes_custom_range"
        storage_key = self.app.stats_custom_range_storage_key(range_key)
        partial_widget_range = (date(2026, 5, 20),)
        saved_range = (date(2026, 5, 10), date(2026, 5, 15))
        self.app.st.session_state["stats_successes_period"] = "Custom"
        self.app.st.session_state[range_key] = partial_widget_range
        self.app.st.session_state[storage_key] = saved_range

        with (
            mock.patch.object(
                self.app.st,
                "segmented_control",
                return_value="Custom",
            ),
            mock.patch.object(
                self.app.st,
                "date_input",
                side_effect=lambda *_args, value=None, **_kwargs: value,
            ) as date_input,
        ):
            selected_period, custom_range = self.app.render_stats_period_selector(
                label="Successes period",
                filter_key="stats_successes_period",
                range_key=range_key,
                on_change=lambda: None,
            )

        self.assertEqual(selected_period, "Custom")
        self.assertIsNone(custom_range)
        self.assertEqual(self.app.st.session_state[range_key], partial_widget_range)
        self.assertEqual(self.app.st.session_state[storage_key], saved_range)
        self.assertEqual(date_input.call_args.kwargs["value"], partial_widget_range)

    def test_stats_custom_range_rehydrates_last_completed_range_when_missing(self):
        range_key = "reminders_actioned_custom_range"
        storage_key = self.app.stats_custom_range_storage_key(range_key)
        saved_range = (date(2026, 5, 10), date(2026, 5, 15))
        self.app.st.session_state["reminders_actioned_period"] = "Custom"
        self.app.st.session_state[storage_key] = saved_range

        with (
            mock.patch.object(
                self.app.st,
                "segmented_control",
                return_value="Custom",
            ),
            mock.patch.object(
                self.app.st,
                "date_input",
                side_effect=lambda *_args, value=None, **_kwargs: value,
            ) as date_input,
        ):
            selected_period, custom_range = self.app.render_stats_period_selector(
                label="Actioned reminder period",
                filter_key="reminders_actioned_period",
                range_key=range_key,
                on_change=lambda: None,
                default_period="Today",
            )

        self.assertEqual(selected_period, "Custom")
        self.assertEqual(custom_range, saved_range)
        self.assertEqual(self.app.st.session_state[range_key], saved_range)
        self.assertEqual(date_input.call_args.kwargs["value"], saved_range)

    def test_stats_custom_range_storage_keys_are_account_scoped(self):
        self.assertIn("stats_period", self.app.ACCOUNT_SCOPED_SESSION_KEYS)
        self.assertIn("stats_custom_range", self.app.ACCOUNT_SCOPED_SESSION_KEYS)
        self.assertIn("stats_custom_range_last_complete", self.app.ACCOUNT_SCOPED_SESSION_KEYS)
        self.assertIn("stats_sent_reminders_custom_range_last_complete", self.app.ACCOUNT_SCOPED_SESSION_KEYS)
        self.assertIn("stats_successes_custom_range_last_complete", self.app.ACCOUNT_SCOPED_SESSION_KEYS)
        self.assertIn("reminders_actioned_custom_range_last_complete", self.app.ACCOUNT_SCOPED_SESSION_KEYS)
        self.assertIn("stats_period_calendar_year", self.app.ACCOUNT_SCOPED_SESSION_KEYS)
        self.assertIn("stats_period_rolling_more", self.app.ACCOUNT_SCOPED_SESSION_KEYS)
        self.assertIn("reminders_actioned_period_calendar_month", self.app.ACCOUNT_SCOPED_SESSION_KEYS)

    def test_stats_shared_custom_range_selection_in_progress(self):
        self.app.st.session_state["stats_period"] = "Custom"
        self.app.st.session_state["stats_custom_range"] = (date(2026, 5, 20),)

        self.assertTrue(self.app.stats_date_range_selection_in_progress())

        self.app.st.session_state["stats_custom_range"] = (date(2026, 5, 20), date(2026, 5, 21))

        self.assertFalse(self.app.stats_date_range_selection_in_progress())

    def test_stats_calendar_options_run_from_uploaded_start_year_to_today(self):
        state = self.app.st.session_state
        state["working_df"] = pd.DataFrame({
            "ChargeDate": pd.to_datetime(["2024-01-01", "2025-08-15"]),
        })

        with mock.patch.object(self.app, "user_today", return_value=date(2026, 5, 22)):
            years = self.app.stats_calendar_year_options()
            months_2026 = self.app.stats_calendar_month_options(2026)
            quarters_2026 = self.app.stats_calendar_quarter_options(2026)
            q1_range = self.app.stats_calendar_range(2026, "Quarter", 1)
            may_range = self.app.stats_calendar_range(2025, "Month", 5)

        self.assertEqual(years, [2024, 2025, 2026])
        self.assertEqual(months_2026, [1, 2, 3, 4, 5])
        self.assertEqual(quarters_2026, [1, 2])
        self.assertEqual(q1_range, (date(2026, 1, 1), date(2026, 3, 31)))
        self.assertEqual(may_range, (date(2025, 5, 1), date(2025, 5, 31)))

    def test_stats_calendar_range_clips_start_and_current_year_to_available_window(self):
        state = self.app.st.session_state
        state["working_df"] = pd.DataFrame({
            "ChargeDate": pd.to_datetime(["2024-03-15", "2025-08-15"]),
        })

        with mock.patch.object(self.app, "user_today", return_value=date(2026, 5, 22)):
            first_year = self.app.stats_calendar_range(2024, "Year")
            current_year = self.app.stats_calendar_range(2026, "Year")
            month_options_2024 = self.app.stats_calendar_month_options(2024)

        self.assertEqual(first_year, (date(2024, 3, 15), date(2024, 12, 31)))
        self.assertEqual(current_year, (date(2026, 1, 1), date(2026, 5, 22)))
        self.assertEqual(month_options_2024, list(range(3, 13)))

    def test_stats_period_start_supports_expanded_rolling_presets(self):
        today = date(2026, 5, 22)

        self.assertEqual(self.app.statistics_period_start("Past week", today), date(2026, 5, 16))
        self.assertEqual(self.app.statistics_period_start("Past month", today), date(2026, 4, 23))
        self.assertEqual(self.app.statistics_period_start("Past 3 months", today), date(2026, 2, 23))
        self.assertEqual(self.app.statistics_period_start("Past 6 months", today), date(2025, 11, 23))
        self.assertEqual(self.app.statistics_period_start("Past year", today), date(2025, 5, 23))
        self.assertEqual(self.app.statistics_period_start("Past 2 years", today), date(2024, 5, 23))

    def test_stats_calendar_selector_returns_custom_range(self):
        class FakeColumn:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        state = self.app.st.session_state
        state["working_df"] = pd.DataFrame({
            "ChargeDate": pd.to_datetime(["2024-01-01", "2025-08-15"]),
        })
        state["stats_period_calendar_year"] = 2025
        state["stats_period_calendar_period"] = "Month"
        state["stats_period_calendar_month"] = 5

        def fake_selectbox(label, options, index=0, **kwargs):
            return options[index]

        with (
            mock.patch.object(self.app, "user_today", return_value=date(2026, 5, 22)),
            mock.patch.object(self.app.st, "segmented_control", return_value="Calendar"),
            mock.patch.object(self.app.st, "columns", return_value=[FakeColumn(), FakeColumn(), FakeColumn()]),
            mock.patch.object(self.app.st, "selectbox", side_effect=fake_selectbox),
            mock.patch.object(self.app.st, "caption") as caption,
        ):
            selected_period, custom_range = self.app.render_stats_period_selector(
                label="Stats period",
                filter_key="stats_period",
                range_key="stats_custom_range",
                on_change=lambda: None,
            )

        self.assertEqual(selected_period, "Custom")
        self.assertEqual(custom_range, (date(2025, 5, 1), date(2025, 5, 31)))
        caption.assert_called_once_with("Showing 01 May 2025 to 31 May 2025")

    def test_stats_period_reset_callbacks_keep_stats_main_tab_active(self):
        self.app.st.session_state["main_section_tab"] = "Reminders"

        self.app.reset_stats_sent_reminders_page()
        self.assertEqual(self.app.st.session_state["main_section_tab"], "Stats")

        self.app.st.session_state["main_section_tab"] = "Reminders"
        self.app.reset_stats_successes_page()
        self.assertEqual(self.app.st.session_state["main_section_tab"], "Stats")

        self.app.st.session_state["main_section_tab"] = "Reminders"
        self.app.reset_stats_shared_period_pages()
        self.assertEqual(self.app.st.session_state["main_section_tab"], "Stats")

    def test_stats_subtab_clicks_keep_stats_main_tab_active(self):
        self.app.st.session_state["main_section_tab"] = "Reminders"

        self.app.set_active_stats_subtab("Reminders")

        self.assertEqual(self.app.st.session_state["main_section_tab"], "Stats")
        self.assertEqual(self.app.st.session_state["stats_active_subtab"], "Reminders")

    def test_open_reminder_outcomes_tab_sets_stats_subtab(self):
        self.app.st.session_state["main_section_tab"] = "Reminders"
        self.app.st.session_state["stats_active_subtab"] = "Items"

        self.app.open_reminder_outcomes_tab()

        self.assertEqual(self.app.st.session_state["main_section_tab"], "Stats")
        self.assertEqual(self.app.st.session_state["stats_active_subtab"], "Reminders")

    def test_stats_render_reuses_matching_calculation_cache_without_custom_range_partial(self):
        source = Path(self.app.__file__).read_text(encoding="utf-8")
        render_start = source.index("def render_stats_tab")
        render_end = source.index("def render_search_terms_editor", render_start)
        render_stats_source = source[render_start:render_end]

        self.assertIn(
            "use_cached_stats = isinstance(stats_cache, dict) and stats_cache.get(\"signature\") == cache_signature",
            render_stats_source,
        )
        self.assertNotIn("stats_date_range_selection_in_progress()\n        and isinstance(stats_cache, dict)", render_stats_source)

    def test_refresh_stats_clears_session_calculation_cache(self):
        state = self.app.st.session_state
        state["_stats_calculation_cache"] = {"signature": "old"}
        state["_stats_export_csv_cache"] = {"entries": {}}

        with (
            mock.patch.object(self.app.build_reminder_outcomes, "clear"),
            mock.patch.object(self.app.cached_statistics_generated_rows, "clear"),
            mock.patch.object(self.app, "search_criteria_have_pending_changes", return_value=False),
        ):
            self.app.refresh_outcome_results_state(sync_remote=False)

        self.assertNotIn("_stats_calculation_cache", state)
        self.assertNotIn("_stats_export_csv_cache", state)

    def test_stats_header_sections_are_visually_separated(self):
        source = Path(self.app.__file__).read_text(encoding="utf-8")
        render_start = source.index("def render_stats_tab")
        render_end = source.index("def render_search_terms_editor", render_start)
        render_stats_source = source[render_start:render_end]

        self.assertIn(".stats-section-divider", source)
        self.assertIn("border-top: 1px solid var(--cr-border);", source)
        self.assertIn(
            "st.markdown(\"<div class='stats-section-divider' aria-hidden='true'></div>\", unsafe_allow_html=True)\n"
            "    selected_stats_period, stats_custom_range = render_shared_stats_period_selector()\n"
            "    st.markdown(\"<div class='stats-section-divider' aria-hidden='true'></div>\", unsafe_allow_html=True)",
            render_stats_source,
        )

    def test_stats_items_shared_custom_filter_uses_scheduled_reminder_date(self):
        generated = pd.DataFrame(
            [
                {"Reminder Date": "20 May 2026", "Plan Item": "Inside"},
                {"Reminder Date": "24 May 2026", "Plan Item": "Outside"},
            ]
        )

        rows = self.app.statistics_generated_records_for_period_filter(
            generated,
            "Custom",
            (date(2026, 5, 20), date(2026, 5, 21)),
        )

        self.assertEqual([row["Plan Item"] for row in rows], ["Inside"])

    def test_stats_team_shared_custom_filter_uses_actioned_date(self):
        actions = [
            {"ActionedAt": "2026-05-20T09:00:00", "Action": self.app.REMINDER_ACTION_SENT, "Plan Item": "Inside"},
            {"ActionedAt": "2026-05-24T09:00:00", "Action": self.app.REMINDER_ACTION_SENT, "Plan Item": "Outside"},
        ]

        rows = self.app.statistics_action_records_for_actioned_period_filter(
            actions,
            "Custom",
            (date(2026, 5, 20), date(2026, 5, 21)),
        )

        self.assertEqual([row["Plan Item"] for row in rows], ["Inside"])

    def test_successes_custom_period_filters_success_date_range(self):
        outcomes = pd.DataFrame(
            [
                {
                    "Success Date": pd.Timestamp("2025-09-30"),
                    "Outcome": "Reminder Success",
                    "Client Name": "Later",
                },
                {
                    "Success Date": pd.Timestamp("2025-09-24"),
                    "Outcome": "Reminder Success",
                    "Client Name": "Inside",
                },
                {
                    "Success Date": pd.Timestamp("2025-09-24"),
                    "Outcome": "No Match",
                    "Client Name": "Not A Success",
                },
                {
                    "Success Date": pd.Timestamp("2025-09-01"),
                    "Outcome": "Reminder Success",
                    "Client Name": "Earlier",
                },
            ]
        )

        rows = self.app.filter_stats_success_tab_rows(
            outcomes,
            "Custom",
            custom_range=(date(2025, 9, 20), date(2025, 9, 25)),
        )

        self.assertEqual(rows["Client Name"].tolist(), ["Inside"])

    def test_stats_sent_tab_period_filter_uses_user_today_not_sales_as_of_date(self):
        outcomes = pd.DataFrame(
            [
                {"Sent Date": pd.Timestamp("2026-05-19"), "Outcome": "No Match", "Client Name": "Sent Today"},
                {"Sent Date": pd.Timestamp("2026-05-13"), "Outcome": "No Match", "Client Name": "Sent Seven Days"},
                {"Sent Date": pd.Timestamp("2026-04-20"), "Outcome": "No Match", "Client Name": "Sent Thirty Days"},
                {"Sent Date": pd.Timestamp("2026-04-19"), "Outcome": "No Match", "Client Name": "Older"},
            ]
        )

        with mock.patch.object(self.app, "user_today", return_value=date(2026, 5, 19)):
            today_rows = self.app.filter_stats_sent_tab_rows(outcomes, "Today")
            seven_day_rows = self.app.filter_stats_sent_tab_rows(outcomes, "Previous 7 days")
            thirty_day_rows = self.app.filter_stats_sent_tab_rows(outcomes, "Previous 30 days")

        self.assertEqual(today_rows["Client Name"].tolist(), ["Sent Today"])
        self.assertEqual(seven_day_rows["Client Name"].tolist(), ["Sent Today", "Sent Seven Days"])
        self.assertEqual(thirty_day_rows["Client Name"].tolist(), ["Sent Today", "Sent Seven Days", "Sent Thirty Days"])

    def test_stats_sent_rows_for_render_skips_sort_for_empty_period(self):
        outcomes = pd.DataFrame(
            [
                {"Sent Date": pd.Timestamp("2026-05-12"), "Outcome": "No Match", "Client Name": "Older"},
            ]
        )

        with mock.patch.object(self.app, "user_today", return_value=date(2026, 5, 19)):
            rows = self.app.stats_sent_rows_for_render(outcomes, "Today")

        self.assertTrue(rows.empty)

    def test_stats_sent_rows_for_render_sort_earliest_first(self):
        outcomes = pd.DataFrame(
            [
                {
                    "Sent Date": pd.Timestamp("2026-05-18"),
                    "Success Date": pd.Timestamp("2026-05-20"),
                    "Outcome": "Reminder Success",
                    "Client Name": "Client B",
                },
                {
                    "Sent Date": pd.Timestamp("2026-05-19"),
                    "Success Date": pd.Timestamp("2026-05-19"),
                    "Outcome": "No Match",
                    "Client Name": "Client C",
                },
                {
                    "Sent Date": pd.Timestamp("2026-05-18"),
                    "Success Date": pd.Timestamp("2026-05-21"),
                    "Outcome": "Reminder Success",
                    "Client Name": "Client A",
                },
            ]
        )

        sent_rows = self.app.stats_sent_rows_for_render(outcomes, "All-time")

        self.assertEqual(sent_rows["Client Name"].tolist(), ["Client A", "Client B", "Client C"])

    def test_stats_success_rows_for_render_preserve_sort_order(self):
        outcomes = pd.DataFrame(
            [
                {
                    "Sent Date": pd.Timestamp("2026-05-18"),
                    "Success Date": pd.Timestamp("2026-05-20"),
                    "Outcome": "Reminder Success",
                    "Client Name": "Client B",
                },
                {
                    "Sent Date": pd.Timestamp("2026-05-19"),
                    "Success Date": pd.Timestamp("2026-05-19"),
                    "Outcome": "No Match",
                    "Client Name": "Client C",
                },
                {
                    "Sent Date": pd.Timestamp("2026-05-18"),
                    "Success Date": pd.Timestamp("2026-05-21"),
                    "Outcome": "Reminder Success",
                    "Client Name": "Client A",
                },
            ]
        )

        success_rows = self.app.stats_success_rows_for_render(outcomes)

        self.assertEqual(success_rows["Client Name"].tolist(), ["Client A", "Client B"])

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
                "Sent Date",
                "Charge Date",
                "Reminder Date",
                "Due Date",
                "Window Starts",
                "Window Ends",
                "Next Purchase Date",
            ],
        )

    def test_outcome_success_display_columns_start_with_success_date(self):
        self.assertEqual(
            self.app.OUTCOME_SUCCESS_DISPLAY_COLUMNS[:7],
            [
                "Success Date",
                "Charge Date",
                "Reminder Date",
                "Sent Date",
                "Due Date",
                "Window Starts",
                "Window Ends",
            ],
        )
        self.assertNotIn("Next Purchase Date", self.app.OUTCOME_SUCCESS_DISPLAY_COLUMNS)

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
        self.assertEqual(int(outcomes.iloc[0]["Overall Purchases"]), 2)
        self.assertEqual(int(outcomes.iloc[0]["Overall Repeat Purchases"]), 1)
        self.assertEqual(int(outcomes.iloc[0]["Unique Purchasing Patients"]), 1)
        self.assertEqual(int(outcomes.iloc[0]["Unique Repeat Purchasing Patients"]), 1)
        self.assertEqual(int(outcomes.iloc[0]["Avg Item Purchase Gap Days"]), 91)
        self.assertEqual(float(outcomes.iloc[0]["Revenue per Item"]), 85.0)
        self.assertAlmostEqual(float(outcomes.iloc[0]["Revenue per Year"]), 85 * 1 * (365 / 91))
        self.assertAlmostEqual(float(outcomes.iloc[0]["Theoretical Max Revenue"]), 85 * 1 * (365 / 90))
        self.assertAlmostEqual(
            float(outcomes.iloc[0]["Capturable Revenue per Year"]),
            (85 * 1 * (365 / 90)) - (85 * 1 * (365 / 91)),
        )
        self.assertAlmostEqual(
            float(outcomes.iloc[0]["Captured Revenue %"]),
            (85 * 1 * (365 / 91)) / (85 * 1 * (365 / 90)),
        )

    def test_stats_revenue_uses_desired_gap_and_actual_median_gap_days(self):
        actions = [
            {
                "Reminder Date": "18 Mar 2025",
                "Due Date": "01 Apr 2025",
                "Charge Date": "01 Jan 2025",
                "Client Name": "Client A",
                "Animal Name": "Pet A",
                "Plan Item": "Bravecto",
                "Action": self.app.REMINDER_ACTION_SENT,
                "ActionedAt": "2026-05-18T09:00:00",
                "Actioned By": "Nurse A",
            }
        ]
        sales = pd.DataFrame(
            [
                {"ChargeDate": "2025-01-01", "Client Name": "Client A", "Animal Name": "Pet A", "Item Name": "Bravecto", "Amount": 80},
                {"ChargeDate": "2025-01-31", "Client Name": "Client A", "Animal Name": "Pet A", "Item Name": "Bravecto", "Amount": 80},
                {"ChargeDate": "2025-04-01", "Client Name": "Client A", "Animal Name": "Pet A", "Item Name": "Bravecto", "Amount": 80},
                {"ChargeDate": "2026-01-26", "Client Name": "Client A", "Animal Name": "Pet A", "Item Name": "Bravecto", "Amount": 80},
            ]
        )

        outcomes = self.app.build_reminder_outcomes(
            actions,
            sales,
            due_date_window_days=14,
            today=date(2026, 6, 1),
            rules={"bravecto": {"days": 90, "visible_text": "Bravecto"}},
        )
        grouped = self.app.build_outcome_group_frame(outcomes, "Item")
        display_frame = self.app.prepare_outcome_dataframe_for_display(
            grouped[self.app.STATS_REVENUE_DISPLAY_COLUMNS],
            column_labels=self.app.STATS_ITEMS_DISPLAY_COLUMN_LABELS,
        )

        self.assertEqual(int(outcomes.iloc[0]["Avg Item Purchase Gap Days"]), 130)
        self.assertEqual(int(outcomes.iloc[0]["Median Item Purchase Gap Days"]), 60)
        self.assertEqual(display_frame.iloc[0]["Desired Gap Days"], 90)
        self.assertEqual(display_frame.iloc[0]["Actual Median Gap Days"], 60)

    def test_reminder_outcomes_exact_variant_matches_sales_with_spaced_units(self):
        actions = [
            {
                "Reminder Date": "18 Mar 2025",
                "Due Date": "01 Apr 2025",
                "Charge Date": "01 Jan 2025",
                "Client Name": "Client A",
                "Animal Name": "Pet A",
                "Plan Item": "Bravecto Spot-On Cats 0.89mL 2.8-6.25kg",
                "Action": self.app.REMINDER_ACTION_SENT,
                "ActionedAt": "2026-05-18T09:00:00",
                "Actioned By": "Nurse A",
                "ReminderDetails": [
                    {
                        "Reminder Date": "18 Mar 2025",
                        "Due Date": "01 Apr 2025",
                        "Charge Date": "01 Jan 2025",
                        "Animal Name": "Pet A",
                        "Plan Item": "Bravecto Spot-On Cats 0.89mL 2.8-6.25kg",
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
                    "Item Name": "Bravecto Spot On Cats 0.89 ml 2.8 - 6.25 kg",
                    "Amount": 80,
                },
                {
                    "ChargeDate": "2025-04-02",
                    "Client Name": "Client A",
                    "Animal Name": "Pet A",
                    "Item Name": "Bravecto Spot On Cats 0.89 ml 2.8 - 6.25 kg",
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

        row = outcomes.iloc[0]
        self.assertEqual(row["Outcome"], "Reminder Success")
        self.assertEqual(int(row["Overall Purchases"]), 2)
        self.assertEqual(int(row["Overall Repeat Purchases"]), 1)
        self.assertEqual(int(row["Unique Purchasing Patients"]), 1)
        self.assertEqual(int(row["Unique Repeat Purchasing Patients"]), 1)
        self.assertEqual(int(row["Avg Item Purchase Gap Days"]), 91)
        self.assertEqual(float(row["Revenue per Item"]), 85.0)
        self.assertAlmostEqual(float(row["Revenue per Year"]), 85 * 1 * (365 / 91))
        self.assertAlmostEqual(float(row["Theoretical Max Revenue"]), 85 * 1 * (365 / 90))
        self.assertAlmostEqual(
            float(row["Capturable Revenue per Year"]),
            (85 * 1 * (365 / 90)) - (85 * 1 * (365 / 91)),
        )
        self.assertEqual(row["Matched Item"], "Bravecto Spot On Cats 0.89 ml 2.8 - 6.25 kg")

    def test_revenue_opportunity_max_uses_faster_actual_or_desired_gap(self):
        actions = [
            {
                "Reminder Date": "02 Dec 2025",
                "Due Date": "01 Jan 2026",
                "Charge Date": "01 Jan 2025",
                "Client Name": "Client A",
                "Animal Name": "Pet A",
                "Plan Item": "Rabies Vaccine",
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
                    "Item Name": "Rabies Vaccine",
                    "Amount": 100,
                },
                {
                    "ChargeDate": "2025-01-23",
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
            rules={"rabies": {"days": 365, "visible_text": "Rabies"}},
        )

        row = outcomes.iloc[0]
        self.assertEqual(int(row["Avg Item Purchase Gap Days"]), 22)
        self.assertEqual(int(row["Unique Purchasing Patients"]), 1)
        self.assertEqual(int(row["Unique Repeat Purchasing Patients"]), 1)
        self.assertAlmostEqual(float(row["Revenue per Year"]), 100 * 1 * (365 / 22))
        self.assertAlmostEqual(float(row["Theoretical Max Revenue"]), 100 * 1 * (365 / 22))
        self.assertAlmostEqual(float(row["Capturable Revenue per Year"]), 0)
        self.assertLessEqual(float(row["Revenue per Year"]), float(row["Theoretical Max Revenue"]))
        self.assertAlmostEqual(float(row["Captured Revenue %"]), 1.0)

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

    def test_reminder_outcomes_counts_early_purchase_after_sent_date(self):
        actions = [
            {
                "Reminder Date": "20 Apr 2025",
                "Due Date": "20 May 2025",
                "Charge Date": "20 May 2024",
                "Client Name": "Client A",
                "Animal Name": "Pet A",
                "Plan Item": "Rabies Vaccine",
                "Days": "365",
                "Action": self.app.REMINDER_ACTION_SENT,
                "ActionedAt": "2025-04-20T09:00:00",
                "Actioned By": "Nurse A",
            }
        ]
        sales = pd.DataFrame(
            [
                {
                    "ChargeDate": "2024-05-20",
                    "Client Name": "Client A",
                    "Animal Name": "Pet A",
                    "Item Name": "Rabies Vaccine",
                    "Amount": 80,
                },
                {
                    "ChargeDate": "2025-04-22",
                    "Client Name": "Client A",
                    "Animal Name": "Pet A",
                    "Item Name": "Rabies Vaccine",
                    "Amount": 90,
                },
            ]
        )

        outcomes = self.app.build_reminder_outcomes(
            actions,
            sales,
            due_date_window_days=14,
            post_reminder_window_days=7,
            today=date(2025, 6, 10),
            rules={"rabies": {"days": 365, "visible_text": "Rabies"}},
        )

        row = outcomes.iloc[0]
        self.assertEqual(row["Outcome"], "Reminder Success")
        self.assertEqual(str(row["Success Date"].date()), "2025-04-22")
        self.assertEqual(row["Success Basis"], "After sent date")
        self.assertEqual(float(row["Revenue"]), 90.0)

    def test_reminder_outcomes_counts_overdue_purchase_after_sent_date(self):
        actions = [
            {
                "Reminder Date": "01 Mar 2025",
                "Due Date": "01 Mar 2025",
                "Charge Date": "01 Mar 2024",
                "Client Name": "Client A",
                "Animal Name": "Pet A",
                "Plan Item": "Rabies Vaccine",
                "Days": "365",
                "Action": self.app.REMINDER_ACTION_SENT,
                "ActionedAt": "2025-05-20T09:00:00",
                "Actioned By": "Nurse A",
            }
        ]
        sales = pd.DataFrame(
            [
                {
                    "ChargeDate": "2024-03-01",
                    "Client Name": "Client A",
                    "Animal Name": "Pet A",
                    "Item Name": "Rabies Vaccine",
                    "Amount": 80,
                },
                {
                    "ChargeDate": "2025-05-24",
                    "Client Name": "Client A",
                    "Animal Name": "Pet A",
                    "Item Name": "Rabies Vaccine",
                    "Amount": 95,
                },
            ]
        )

        outcomes = self.app.build_reminder_outcomes(
            actions,
            sales,
            due_date_window_days=14,
            post_reminder_window_days=7,
            today=date(2025, 6, 10),
            rules={"rabies": {"days": 365, "visible_text": "Rabies"}},
        )

        row = outcomes.iloc[0]
        self.assertEqual(row["Outcome"], "Reminder Success")
        self.assertEqual(str(row["Success Date"].date()), "2025-05-24")
        self.assertEqual(row["Success Basis"], "After sent date")
        self.assertEqual(float(row["Revenue"]), 95.0)

    def test_reminder_outcomes_keep_pending_until_post_sent_window_closes(self):
        actions = [
            {
                "Reminder Date": "01 Mar 2025",
                "Due Date": "01 Mar 2025",
                "Charge Date": "01 Mar 2024",
                "Client Name": "Client A",
                "Animal Name": "Pet A",
                "Plan Item": "Rabies Vaccine",
                "Days": "365",
                "Action": self.app.REMINDER_ACTION_SENT,
                "ActionedAt": "2025-05-20T09:00:00",
                "Actioned By": "Nurse A",
            }
        ]
        sales = pd.DataFrame(
            [
                {
                    "ChargeDate": "2024-03-01",
                    "Client Name": "Client A",
                    "Animal Name": "Pet A",
                    "Item Name": "Rabies Vaccine",
                    "Amount": 80,
                },
            ]
        )

        outcomes = self.app.build_reminder_outcomes(
            actions,
            sales,
            due_date_window_days=14,
            post_reminder_window_days=7,
            today=date(2025, 5, 24),
            rules={"rabies": {"days": 365, "visible_text": "Rabies"}},
        )

        self.assertEqual(outcomes.iloc[0]["Outcome"], "Pending")

    def test_reminder_outcomes_counts_later_sent_step_after_sent_date_once(self):
        actions = [
            {
                "Reminder Date": "01 Apr 2025",
                "Due Date": "01 May 2025",
                "Charge Date": "01 May 2024",
                "Client Name": "Client A",
                "Animal Name": "Pet A",
                "Plan Item": "Rabies Vaccine",
                "Days": "365",
                "Action": self.app.REMINDER_ACTION_SENT,
                "ActionedAt": "2025-04-01T09:00:00",
                "Actioned By": "Nurse A",
            },
            {
                "Reminder Date": "20 May 2025",
                "Due Date": "01 May 2025",
                "Charge Date": "01 May 2024",
                "Client Name": "Client A",
                "Animal Name": "Pet A",
                "Plan Item": "Rabies Vaccine",
                "Days": "365",
                "Action": self.app.REMINDER_ACTION_SENT,
                "ActionedAt": "2025-05-20T09:00:00",
                "Actioned By": "Nurse B",
            },
        ]
        sales = pd.DataFrame(
            [
                {
                    "ChargeDate": "2024-05-01",
                    "Client Name": "Client A",
                    "Animal Name": "Pet A",
                    "Item Name": "Rabies Vaccine",
                    "Amount": 80,
                },
                {
                    "ChargeDate": "2025-05-24",
                    "Client Name": "Client A",
                    "Animal Name": "Pet A",
                    "Item Name": "Rabies Vaccine",
                    "Amount": 95,
                },
            ]
        )

        outcomes = self.app.build_reminder_outcomes(
            actions,
            sales,
            due_date_window_days=14,
            post_reminder_window_days=7,
            today=date(2025, 6, 10),
            rules={"rabies": {"days": 365, "visible_text": "Rabies"}},
        )
        summary = self.app.summarize_outcomes(outcomes)

        self.assertEqual(len(outcomes), 1)
        row = outcomes.iloc[0]
        self.assertEqual(summary["sent"], 1)
        self.assertEqual(summary["successes"], 1)
        self.assertEqual(row["Outcome"], "Reminder Success")
        self.assertEqual(str(row["Success Date"].date()), "2025-05-24")
        self.assertEqual(row["Success Basis"], "After sent date")
        self.assertEqual(float(row["Revenue"]), 95.0)
        self.assertEqual(row["Sender"], "Nurse A")
        self.assertEqual(str(row["Sent Date"].date()), "2025-04-01")

    def test_reminder_outcomes_keep_pending_until_later_sent_window_closes(self):
        actions = [
            {
                "Reminder Date": "01 Apr 2025",
                "Due Date": "01 May 2025",
                "Charge Date": "01 May 2024",
                "Client Name": "Client A",
                "Animal Name": "Pet A",
                "Plan Item": "Rabies Vaccine",
                "Days": "365",
                "Action": self.app.REMINDER_ACTION_SENT,
                "ActionedAt": "2025-04-01T09:00:00",
                "Actioned By": "Nurse A",
            },
            {
                "Reminder Date": "20 May 2025",
                "Due Date": "01 May 2025",
                "Charge Date": "01 May 2024",
                "Client Name": "Client A",
                "Animal Name": "Pet A",
                "Plan Item": "Rabies Vaccine",
                "Days": "365",
                "Action": self.app.REMINDER_ACTION_SENT,
                "ActionedAt": "2025-05-20T09:00:00",
                "Actioned By": "Nurse B",
            },
        ]
        sales = pd.DataFrame(
            [
                {
                    "ChargeDate": "2024-05-01",
                    "Client Name": "Client A",
                    "Animal Name": "Pet A",
                    "Item Name": "Rabies Vaccine",
                    "Amount": 80,
                },
            ]
        )

        outcomes = self.app.build_reminder_outcomes(
            actions,
            sales,
            due_date_window_days=14,
            post_reminder_window_days=7,
            today=date(2025, 5, 24),
            rules={"rabies": {"days": 365, "visible_text": "Rabies"}},
        )

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes.iloc[0]["Outcome"], "Pending")
        self.assertEqual(str(outcomes.iloc[0]["Sent Date"].date()), "2025-04-01")

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

    def test_grouped_reminder_outcomes_count_later_sent_step_post_reminder_successes(self):
        actions = [
            {
                "Reminder Date": "01 Apr 2025 | 01 Apr 2025",
                "Due Date": "01 May 2025 | 01 May 2025",
                "Charge Date": "01 May 2024",
                "Client Name": "Client A",
                "Animal Name": "Pet A",
                "Plan Item": "Rabies and Tricat",
                "Action": self.app.REMINDER_ACTION_SENT,
                "ActionedAt": "2025-04-01T09:00:00",
                "Actioned By": "Nurse A",
                "ReminderDetails": [
                    {
                        "Reminder Date": "01 Apr 2025",
                        "Due Date": "01 May 2025",
                        "Charge Date": "01 May 2024",
                        "Animal Name": "Pet A",
                        "Plan Item": "Rabies Vaccine",
                        "Qty": "1",
                        "Days": "365",
                    },
                    {
                        "Reminder Date": "01 Apr 2025",
                        "Due Date": "01 May 2025",
                        "Charge Date": "01 May 2024",
                        "Animal Name": "Pet A",
                        "Plan Item": "Tricat Vaccine",
                        "Qty": "1",
                        "Days": "365",
                    },
                ],
            },
            {
                "Reminder Date": "20 May 2025 | 20 May 2025",
                "Due Date": "01 May 2025 | 01 May 2025",
                "Charge Date": "01 May 2024",
                "Client Name": "Client A",
                "Animal Name": "Pet A",
                "Plan Item": "Rabies and Tricat",
                "Action": self.app.REMINDER_ACTION_SENT,
                "ActionedAt": "2025-05-20T09:00:00",
                "Actioned By": "Nurse B",
                "ReminderDetails": [
                    {
                        "Reminder Date": "20 May 2025",
                        "Due Date": "01 May 2025",
                        "Charge Date": "01 May 2024",
                        "Animal Name": "Pet A",
                        "Plan Item": "Rabies Vaccine",
                        "Qty": "1",
                        "Days": "365",
                    },
                    {
                        "Reminder Date": "20 May 2025",
                        "Due Date": "01 May 2025",
                        "Charge Date": "01 May 2024",
                        "Animal Name": "Pet A",
                        "Plan Item": "Tricat Vaccine",
                        "Qty": "1",
                        "Days": "365",
                    },
                ],
            },
        ]
        sales = pd.DataFrame(
            [
                {
                    "ChargeDate": "2024-05-01",
                    "Client Name": "Client A",
                    "Animal Name": "Pet A",
                    "Item Name": "Rabies Vaccine",
                    "Amount": 80,
                },
                {
                    "ChargeDate": "2024-05-01",
                    "Client Name": "Client A",
                    "Animal Name": "Pet A",
                    "Item Name": "Tricat Vaccine",
                    "Amount": 70,
                },
                {
                    "ChargeDate": "2025-05-24",
                    "Client Name": "Client A",
                    "Animal Name": "Pet A",
                    "Item Name": "Rabies Vaccine",
                    "Amount": 95,
                },
                {
                    "ChargeDate": "2025-05-25",
                    "Client Name": "Client A",
                    "Animal Name": "Pet A",
                    "Item Name": "Tricat Vaccine",
                    "Amount": 85,
                },
            ]
        )

        outcomes = self.app.build_reminder_outcomes(
            actions,
            sales,
            due_date_window_days=14,
            post_reminder_window_days=7,
            today=date(2025, 6, 10),
            rules={
                "rabies": {"days": 365, "visible_text": "Rabies"},
                "tricat": {"days": 365, "visible_text": "Tricat"},
            },
        )
        summary = self.app.summarize_outcomes(outcomes)

        self.assertEqual(len(outcomes), 2)
        rows = {row["Item"]: row for row in outcomes.to_dict("records")}
        self.assertEqual(set(rows), {"Rabies Vaccine", "Tricat Vaccine"})
        self.assertEqual(summary["sent"], 2)
        self.assertEqual(summary["successes"], 2)
        self.assertEqual(summary["success_rate"], 1.0)
        self.assertEqual(rows["Rabies Vaccine"]["Outcome"], "Reminder Success")
        self.assertEqual(rows["Rabies Vaccine"]["Success Basis"], "After sent date")
        self.assertEqual(str(rows["Rabies Vaccine"]["Success Date"].date()), "2025-05-24")
        self.assertEqual(rows["Tricat Vaccine"]["Outcome"], "Reminder Success")
        self.assertEqual(rows["Tricat Vaccine"]["Success Basis"], "After sent date")
        self.assertEqual(str(rows["Tricat Vaccine"]["Success Date"].date()), "2025-05-25")

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
                {"Sender": "Nurse A", "Item": "Rabies", "Outcome": "Reminder Success", "Success Gap Days": 365, "Desired Gap Days": 365, "Avg Item Purchase Gap Days": 370, "Overall Repeat Purchases": 3, "Overall Purchases": 4, "Revenue per Item": 150, "Revenue": 120, "Revenue per Year": 300, "Theoretical Max Revenue": 600},
                {"Sender": "Nurse A", "Item": "Rabies", "Outcome": "No Match", "Success Gap Days": None, "Desired Gap Days": 365, "Avg Item Purchase Gap Days": 370, "Overall Repeat Purchases": 3, "Overall Purchases": 4, "Revenue per Item": 150, "Revenue": 0, "Revenue per Year": 300, "Theoretical Max Revenue": 600},
                {"Sender": "Nurse A", "Item": "Rabies", "Outcome": "Pending", "Success Gap Days": None, "Desired Gap Days": 365, "Avg Item Purchase Gap Days": 370, "Overall Repeat Purchases": 3, "Overall Purchases": 4, "Revenue per Item": 150, "Revenue": 0, "Revenue per Year": 300, "Theoretical Max Revenue": 600},
                {"Sender": "Nurse A", "Item": "Rabies", "Outcome": "Not Measurable", "Success Gap Days": None, "Desired Gap Days": 365, "Avg Item Purchase Gap Days": 370, "Overall Repeat Purchases": 3, "Overall Purchases": 4, "Revenue per Item": 150, "Revenue": 0, "Revenue per Year": 300, "Theoretical Max Revenue": 600},
                {"Sender": "Nurse B", "Item": "Bravecto", "Outcome": "Reminder Success", "Success Gap Days": 95, "Desired Gap Days": 90, "Avg Item Purchase Gap Days": 120, "Overall Repeat Purchases": 2, "Overall Purchases": 5, "Revenue per Item": 100, "Revenue": 80, "Revenue per Year": 200, "Theoretical Max Revenue": 500},
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
        self.assertAlmostEqual(rows["Nurse A"]["Gap Day % to Desired"], 370 / 365)
        self.assertEqual(rows["Nurse A"]["Overall Repeat Purchases"], 3)
        self.assertEqual(rows["Nurse A"]["Overall Purchases"], 4)
        self.assertEqual(rows["Nurse A"]["Repeat Purchase %"], 0.75)
        self.assertEqual(rows["Nurse A"]["Revenue per Item"], 150)
        self.assertEqual(rows["Nurse A"]["Revenue per Year"], 300)
        self.assertEqual(rows["Nurse A"]["Theoretical Max Revenue"], 600)
        self.assertEqual(rows["Nurse A"]["Capturable Revenue per Year"], 300)
        self.assertEqual(rows["Nurse A"]["Captured Revenue %"], 0.5)
        self.assertEqual(rows["Nurse B"]["Desired Gap Days"], 90)
        self.assertEqual(rows["Nurse B"]["Gap Day % to Desired"], 120 / 90)
        self.assertEqual(rows["Nurse B"]["Overall Repeat Purchases"], 2)
        self.assertEqual(rows["Nurse B"]["Overall Purchases"], 5)
        self.assertEqual(rows["Nurse B"]["Repeat Purchase %"], 0.4)
        self.assertLess(
            self.app.OUTCOME_ITEM_GROUP_COLUMNS.index("Avg Item Purchase Gap Days"),
            self.app.OUTCOME_ITEM_GROUP_COLUMNS.index("Gap Day % to Desired"),
        )
        self.assertLess(
            self.app.OUTCOME_ITEM_GROUP_COLUMNS.index("Gap Day % to Desired"),
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
            self.app.OUTCOME_ITEM_GROUP_COLUMNS.index("Revenue per Item"),
        )
        self.assertLess(
            self.app.OUTCOME_ITEM_GROUP_COLUMNS.index("Revenue per Item"),
            self.app.OUTCOME_ITEM_GROUP_COLUMNS.index("Revenue"),
        )
        self.assertLess(
            self.app.OUTCOME_ITEM_GROUP_COLUMNS.index("Revenue"),
            self.app.OUTCOME_ITEM_GROUP_COLUMNS.index("Revenue per Year"),
        )
        self.assertLess(
            self.app.OUTCOME_ITEM_GROUP_COLUMNS.index("Revenue per Year"),
            self.app.OUTCOME_ITEM_GROUP_COLUMNS.index("Theoretical Max Revenue"),
        )
        self.assertLess(
            self.app.OUTCOME_ITEM_GROUP_COLUMNS.index("Theoretical Max Revenue"),
            self.app.OUTCOME_ITEM_GROUP_COLUMNS.index("Capturable Revenue per Year"),
        )
        self.assertLess(
            self.app.OUTCOME_ITEM_GROUP_COLUMNS.index("Capturable Revenue per Year"),
            self.app.OUTCOME_ITEM_GROUP_COLUMNS.index("Captured Revenue %"),
        )

    def test_outcome_summary_precomputed_numeric_columns_preserve_group_metrics(self):
        outcomes = pd.DataFrame(
            [
                {"Sender": "Nurse A", "Item": "Rabies", "Outcome": "Reminder Success", "Success Gap Days": "365", "Desired Gap Days": "365", "Avg Item Purchase Gap Days": "370", "Overall Repeat Purchases": "3", "Overall Purchases": "4", "Revenue per Item": "150", "Revenue": "120", "Revenue per Year": "300", "Theoretical Max Revenue": "600"},
                {"Sender": "Nurse A", "Item": "Rabies", "Outcome": "Pending", "Success Gap Days": "", "Desired Gap Days": "365", "Avg Item Purchase Gap Days": "370", "Overall Repeat Purchases": "3", "Overall Purchases": "4", "Revenue per Item": "150", "Revenue": "0", "Revenue per Year": "300", "Theoretical Max Revenue": "600"},
                {"Sender": "Nurse B", "Item": "Bravecto", "Outcome": "No Match", "Success Gap Days": "", "Desired Gap Days": "90", "Avg Item Purchase Gap Days": "120", "Overall Repeat Purchases": "2", "Overall Purchases": "5", "Revenue per Item": "100", "Revenue": "0", "Revenue per Year": "200", "Theoretical Max Revenue": "500"},
            ]
        )

        raw_summary = self.app.summarize_outcomes(outcomes)
        prepared = self.app.outcome_summary_precompute_numeric_columns(outcomes.copy())
        prepared_summary = self.app.summarize_outcomes(prepared)

        self.assertEqual(raw_summary.keys(), prepared_summary.keys())
        for key in raw_summary:
            raw_value = raw_summary[key]
            prepared_value = prepared_summary[key]
            if pd.isna(raw_value) and pd.isna(prepared_value):
                continue
            self.assertEqual(raw_value, prepared_value)

        with mock.patch.object(
            self.app,
            "outcome_summary_precompute_numeric_columns",
            wraps=self.app.outcome_summary_precompute_numeric_columns,
        ) as precompute:
            grouped = self.app.build_outcome_group_frame(outcomes, "Sender")

        precompute.assert_called_once()
        rows = {row["Sender"]: row for row in grouped.to_dict("records")}
        self.assertEqual(rows["Nurse A"]["Sent"], 2)
        self.assertEqual(rows["Nurse A"]["Successes"], 1)
        self.assertEqual(rows["Nurse A"]["Revenue"], 120)
        self.assertEqual(rows["Nurse B"]["Overall Repeat Purchases"], 2)

    def test_outcome_group_frame_precomputed_numeric_path_matches_default(self):
        outcomes = pd.DataFrame(
            [
                {"Sender": "Nurse A", "Item": "Rabies", "Outcome": "Reminder Success", "Success Gap Days": "365", "Desired Gap Days": "365", "Avg Item Purchase Gap Days": "370", "Overall Repeat Purchases": "3", "Overall Purchases": "4", "Revenue per Item": "150", "Revenue": "120", "Revenue per Year": "300", "Theoretical Max Revenue": "600"},
                {"Sender": "Nurse A", "Item": "Rabies", "Outcome": "Pending", "Success Gap Days": "", "Desired Gap Days": "365", "Avg Item Purchase Gap Days": "370", "Overall Repeat Purchases": "3", "Overall Purchases": "4", "Revenue per Item": "150", "Revenue": "0", "Revenue per Year": "300", "Theoretical Max Revenue": "600"},
                {"Sender": "Nurse B", "Item": "Bravecto", "Outcome": "No Match", "Success Gap Days": "", "Desired Gap Days": "90", "Avg Item Purchase Gap Days": "120", "Overall Repeat Purchases": "2", "Overall Purchases": "5", "Revenue per Item": "100", "Revenue": "0", "Revenue per Year": "200", "Theoretical Max Revenue": "500"},
            ]
        )

        default_group = self.app.build_outcome_group_frame(outcomes, "Sender", self.app.OUTCOME_SENDER_GROUP_COLUMNS)
        prepared = self.app.outcome_summary_precompute_numeric_columns(outcomes.copy())
        precomputed_group = self.app.build_outcome_group_frame(
            prepared,
            "Sender",
            self.app.OUTCOME_SENDER_GROUP_COLUMNS,
            numeric_precomputed=True,
        )

        pd.testing.assert_frame_equal(
            precomputed_group.reset_index(drop=True),
            default_group.reset_index(drop=True),
        )

    def test_render_outcome_dataframe_uses_native_sortable_dataframe_for_summary_rows(self):
        self.app.st.session_state["user_country"] = "United Arab Emirates"
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
                "Gap Day % to Desired": 370 / 365,
                "Overall Repeat Purchases": 3,
                "Overall Purchases": 4,
                "Unique Repeat Purchasing Patients": 2,
                "Unique Purchasing Patients": 3,
                "Repeat Purchase %": 0.75,
                "Revenue per Item": 120.4,
                "Revenue": 120.4,
                "Revenue per Year": 300.6,
                "Theoretical Max Revenue": 600.2,
                "Capturable Revenue per Year": 299.6,
                "Captured Revenue %": 0.5,
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
        self.assertEqual(dataframe.call_args.kwargs["height"], self.app.STATS_TABLE_HEIGHT)
        self.assertIn("Overall Avg Purchase Gap Days", rendered_frame.columns)
        self.assertIn("Gap Day % to Desired", rendered_frame.columns)
        self.assertIn("Overall Repeat Purchases", rendered_frame.columns)
        self.assertIn("Overall Purchases", rendered_frame.columns)
        self.assertIn("Repeat Purchase %", rendered_frame.columns)
        self.assertIn("Revenue per Item", rendered_frame.columns)
        self.assertIn("Revenue from Successes", rendered_frame.columns)
        self.assertIn("Revenue per Year", rendered_frame.columns)
        self.assertIn("Theoretical Max Revenue", rendered_frame.columns)
        self.assertIn("Capturable Revenue per Year", rendered_frame.columns)
        self.assertIn("Captured Revenue %", rendered_frame.columns)
        self.assertIn("Success Rate", column_config)
        self.assertIn("Repeat Purchase %", column_config)
        self.assertIn("Revenue from Successes", column_config)
        self.assertEqual(column_config["Success Rate"]["type_config"]["format"], "%.0f%%")
        self.assertEqual(column_config["Success Rate"]["type_config"]["min_value"], 0)
        self.assertEqual(column_config["Success Rate"]["type_config"]["max_value"], 100)
        self.assertEqual(column_config["Overall Avg Purchase Gap Days"]["type_config"]["format"], "%.0f")
        self.assertEqual(column_config["Gap Day % to Desired"]["type_config"]["format"], "%.0f%%")
        self.assertEqual(column_config["Repeat Purchase %"]["type_config"]["format"], "%.0f%%")
        self.assertEqual(column_config["Current Revenue Capture %"]["type_config"]["format"], "%.0f%%")
        self.assertEqual(column_config["Captured Revenue %"]["type_config"]["format"], "%.0f%%")
        self.assertEqual(column_config["Revenue per Item"]["type_config"]["format"], "AED %,.0f")
        self.assertEqual(column_config["Revenue from Successes"]["type_config"]["format"], "AED %,.0f")
        self.assertEqual(column_config["Current Annual Revenue"]["type_config"]["format"], "AED %,.0f")
        self.assertEqual(column_config["Calculated Revenue per Year"]["type_config"]["format"], "AED %,.0f")
        self.assertEqual(column_config["Max Annual Revenue"]["type_config"]["format"], "AED %,.0f")
        self.assertEqual(column_config["Theoretical Max Revenue"]["type_config"]["format"], "AED %,.0f")
        self.assertEqual(column_config["Potential Annual Revenue Lift"]["type_config"]["format"], "AED %,.0f")
        self.assertEqual(column_config["Capturable Revenue Potential per Year"]["type_config"]["format"], "AED %,.0f")
        self.assertEqual(column_config["Revenue from Successes"]["label"], "Revenue from\nSuccesses")
        self.assertEqual(column_config["Revenue per Item"]["label"], "Revenue\nper Item")
        self.assertEqual(column_config["Current Annual Revenue"]["label"], "Current Annual\nRevenue")
        self.assertEqual(column_config["Max Annual Revenue"]["label"], "Max Annual\nRevenue")
        self.assertEqual(column_config["Potential Annual Revenue Lift"]["label"], "Potential Annual\nRevenue Lift")
        self.assertEqual(column_config["Current Revenue Capture %"]["label"], "Current Revenue\nCapture %")
        self.assertEqual(column_config["Calculated Revenue per Year"]["label"], "Calculated Revenue\nper Year")
        self.assertEqual(column_config["Capturable Revenue Potential per Year"]["label"], "Capturable Revenue\nPotential per Year")
        self.assertEqual(column_config["Potential Annual Revenue Lift"]["width"], "small")
        self.assertEqual(column_config["Capturable Revenue Potential per Year"]["width"], "small")
        self.assertEqual(column_config["Current Annual Revenue"]["width"], "small")
        self.assertEqual(column_config["Current Revenue Capture %"]["width"], "small")
        self.assertEqual(column_config["Calculated Revenue per Year"]["width"], "small")
        self.assertEqual(column_config["Max Annual Revenue"]["width"], "small")
        self.assertEqual(column_config["Theoretical Max Revenue"]["width"], "small")
        self.assertEqual(column_config["Total Repeat Purchases"]["width"], "small")
        self.assertEqual(column_config["Unique Purchasing Patients"]["width"], "small")
        self.assertEqual(column_config["Unique Repeat Purchasing Patients"]["width"], "small")
        self.assertEqual(column_config["Overall Avg Purchase Gap Days"]["label"], "Overall Avg\nPurchase Gap\nDays")
        self.assertEqual(rendered_frame.iloc[0]["Success Rate"], 25)
        self.assertEqual(round(rendered_frame.iloc[0]["Gap Day % to Desired"]), 101)
        self.assertEqual(rendered_frame.iloc[0]["Repeat Purchase %"], 75)
        self.assertEqual(rendered_frame.iloc[0]["Captured Revenue %"], 50)
        self.assertEqual(rendered_frame.iloc[0]["Revenue per Item"], 120)
        self.assertEqual(rendered_frame.iloc[0]["Revenue from Successes"], 120)
        self.assertEqual(rendered_frame.iloc[0]["Revenue per Year"], 301)
        self.assertEqual(rendered_frame.iloc[0]["Theoretical Max Revenue"], 600)
        self.assertEqual(rendered_frame.iloc[0]["Capturable Revenue per Year"], 300)
        self.assertIn("Average gap", column_config["Overall Avg Purchase Gap Days"]["help"])
        self.assertIn("Overall average purchase gap compared with the desired gap", column_config["Gap Day % to Desired"]["help"])
        self.assertIn("Percentage of matching purchases", column_config["Repeat Purchase %"]["help"])
        self.assertIn("Average revenue per matching purchase", column_config["Revenue per Item"]["help"])
        self.assertIn("Revenue from repeat purchases", column_config["Revenue from Successes"]["help"])
        self.assertIn("Unique Repeat Purchasing Patients x (365 / Actual Median Gap Days) x Revenue per Item", column_config["Current Annual Revenue"]["help"])
        self.assertIn("Unique Purchasing Patients x (365 / Desired Gap Days) x Revenue per Item", column_config["Max Annual Revenue"]["help"])
        self.assertIn("Max Annual Revenue - Current Annual Revenue", column_config["Potential Annual Revenue Lift"]["help"])
        self.assertIn("Current Annual Revenue divided by Max Annual Revenue", column_config["Current Revenue Capture %"]["help"])
        self.assertIn("Current result", column_config["Outcome"]["help"])
        self.assertNotIn("Avg Item Purchase Gap Days", rendered_frame.columns)
        self.assertNotIn("Revenue", rendered_frame.columns)

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
                    "Desired Gap Days": 365,
                    "Avg Item Purchase Gap Days": 370,
                    "Gap Day % to Desired": 370 / 365,
                    "Overall Repeat Purchases": 3,
                    "Overall Purchases": 4,
                    "Unique Repeat Purchasing Patients": 2,
                    "Unique Purchasing Patients": 3,
                    "Repeat Purchase %": 0.75,
                    "Success Rate": 0.25,
                    "Revenue per Item": 120.4,
                    "Revenue": 120.4,
                    "Revenue per Year": 300.6,
                    "Theoretical Max Revenue": 600.2,
                    "Capturable Revenue per Year": 299.6,
                    "Captured Revenue %": 0.5,
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
        self.assertIn("Gap Day % to Desired", display_frame.columns)
        self.assertIn("Overall Repeat Purchases", display_frame.columns)
        self.assertIn("Overall Purchases", display_frame.columns)
        self.assertIn("Repeat Purchase %", display_frame.columns)
        self.assertIn("Revenue per Item", display_frame.columns)
        self.assertIn("Revenue from Successes", display_frame.columns)
        self.assertIn("Revenue per Year", display_frame.columns)
        self.assertIn("Theoretical Max Revenue", display_frame.columns)
        self.assertIn("Capturable Revenue per Year", display_frame.columns)
        self.assertIn("Captured Revenue %", display_frame.columns)
        self.assertEqual(display_frame.iloc[0]["Success Rate"], 25)
        self.assertEqual(round(display_frame.iloc[0]["Gap Day % to Desired"]), 101)
        self.assertEqual(display_frame.iloc[0]["Repeat Purchase %"], 75)
        self.assertEqual(display_frame.iloc[0]["Captured Revenue %"], 50)
        self.assertEqual(display_frame.iloc[0]["Revenue per Item"], 120)
        self.assertEqual(display_frame.iloc[0]["Revenue from Successes"], 120)
        self.assertEqual(display_frame.iloc[0]["Revenue per Year"], 301)
        self.assertEqual(display_frame.iloc[0]["Theoretical Max Revenue"], 600)
        self.assertEqual(display_frame.iloc[0]["Capturable Revenue per Year"], 300)
        self.assertNotIn("Revenue", display_frame.columns)
        self.assertNotIn("Avg Item Purchase Gap Days", display_frame.columns)
        self.assertEqual(display_frame.iloc[0]["Due Date"], "")
        self.assertEqual(display_frame.iloc[0]["Next Purchase Date"], "Mar-06-2024")
        self.assertEqual(display_frame.iloc[0]["Window Ends"], "Apr-30-2024")
        self.assertEqual(str(frame.iloc[0]["Sent Date"]), "2024-01-13 00:00:00")


if __name__ == "__main__":
    unittest.main()
