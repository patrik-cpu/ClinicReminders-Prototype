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
        self.assertIn("3 active reminders in the look-back window", label)
        self.assertIn("data:image/svg+xml;base64", label)

    def test_default_lookback_days_is_two(self):
        self.assertEqual(self.app.DEFAULT_REMINDER_LOOKBACK_DAYS, 2)
        self.assertEqual(self.app.normalized_reminder_lookback_days(), 2)
        self.assertEqual(self.app.normalized_reminder_lookback_days("bad"), 2)

    def test_reminder_filter_controls_preserve_session_values(self):
        state = self.app.st.session_state
        state["reminders_start_date"] = date(2026, 5, 10)
        state[self.app.REMINDERS_START_DATE_INPUT_KEY] = date(2026, 5, 11)
        state["reminder_lookback_days"] = 9
        state["reminder_window_days"] = 8
        state["client_group_days"] = 3
        state["reminder_warning_days"] = 4

        selected = self.app.initialize_reminder_filter_controls(date(2026, 5, 18))

        self.assertEqual(selected, date(2026, 5, 11))
        self.assertEqual(state["reminders_start_date"], date(2026, 5, 11))
        self.assertEqual(state["reminder_lookback_days"], 9)
        self.assertEqual(state["reminder_window_days"], 8)
        self.assertEqual(state["client_group_days"], 3)
        self.assertEqual(state["reminder_warning_days"], 4)

    def test_today_button_updates_stable_reminder_date_keys(self):
        with mock.patch.object(self.app, "user_today", return_value=date(2026, 5, 18)):
            self.app.set_reminders_start_date_to_today()

        self.assertTrue(self.app.st.session_state["_reminders_start_date_today_requested"])
        self.assertEqual(self.app.st.session_state["reminders_start_date"], date(2026, 5, 18))
        self.assertEqual(
            self.app.st.session_state[self.app.REMINDERS_START_DATE_INPUT_KEY],
            date(2026, 5, 18),
        )

    def test_badge_count_includes_lookback_days_and_excludes_actioned_rows(self):
        today_row = {
            "Reminder Date": "16 May 2026",
            "Due Date": "16 May 2026",
            "Client Name": "Client A",
            "Animal Name": "Pet A",
            "Plan Item": "Rabies",
        }
        lookback_row = {
            "Reminder Date": "11 May 2026",
            "Due Date": "11 May 2026",
            "Client Name": "Client D",
            "Animal Name": "Pet D",
            "Plan Item": "Dental",
        }
        actioned_today_row = {
            "Reminder Date": "16 May 2026",
            "Due Date": "16 May 2026",
            "Client Name": "Client B",
            "Animal Name": "Pet B",
            "Plan Item": "Librela",
        }
        outside_lookback_row = {
            "Reminder Date": "10 May 2026",
            "Due Date": "10 May 2026",
            "Client Name": "Client E",
            "Animal Name": "Pet E",
            "Plan Item": "Nail Clip",
        }
        tomorrow_row = {
            "Reminder Date": "17 May 2026",
            "Due Date": "17 May 2026",
            "Client Name": "Client C",
            "Animal Name": "Pet C",
            "Plan Item": "Annual Exam",
        }
        prepared = pd.DataFrame({
            "ReminderDateTs": pd.to_datetime(["2026-05-11", "2026-05-16", "2026-05-17"]),
            "NextDueDate": pd.to_datetime(["2026-05-11", "2026-05-16", "2026-05-17"]),
        })
        grouped = pd.DataFrame([today_row, lookback_row, actioned_today_row, outside_lookback_row, tomorrow_row])

        state = self.app.st.session_state
        state["working_df"] = pd.DataFrame({"row": [1]})
        state["reminder_lookback_days"] = 5
        state["deleted_reminders"] = [
            {**actioned_today_row, "Action": self.app.REMINDER_ACTION_SENT},
        ]
        mock_bundle = mock.Mock(return_value=grouped)
        rules = {"rabies": {"days": 365}}

        with (
            mock.patch.object(self.app, "get_applied_reminder_rules", return_value=rules),
            mock.patch.object(self.app, "get_prepared_df", return_value=prepared),
            mock.patch.object(self.app, "bundle_client_reminders_by_window", mock_bundle),
        ):
            count = self.app.get_active_reminder_badge_count(today=date(2026, 5, 16))

        due_df = mock_bundle.call_args.args[0]
        self.assertEqual(due_df["ReminderDateTs"].min(), pd.Timestamp("2026-05-11"))
        self.assertEqual(due_df["ReminderDateTs"].max(), pd.Timestamp("2026-05-16"))
        self.assertEqual(count, 2)

    def test_badge_count_reuses_grouped_window_after_action_state_changes(self):
        reminder_row = {
            "Reminder Date": "16 May 2026",
            "Due Date": "16 May 2026",
            "Client Name": "Client A",
            "Animal Name": "Pet A",
            "Plan Item": "Rabies",
        }
        prepared = pd.DataFrame({
            "ReminderDateTs": pd.to_datetime(["2026-05-16"]),
            "NextDueDate": pd.to_datetime(["2026-05-16"]),
        })
        grouped = pd.DataFrame([reminder_row])

        state = self.app.st.session_state
        state["working_df"] = pd.DataFrame({"row": [1]})
        state["reminder_lookback_days"] = 0
        state["client_group_days"] = 1
        mock_bundle = mock.Mock(return_value=grouped)
        rules = {"rabies": {"days": 365}}

        with (
            mock.patch.object(self.app, "get_applied_reminder_rules", return_value=rules),
            mock.patch.object(self.app, "get_prepared_df", return_value=prepared),
            mock.patch.object(self.app, "bundle_client_reminders_by_window", mock_bundle),
        ):
            first_count = self.app.get_active_reminder_badge_count(today=date(2026, 5, 16))
            second_count = self.app.get_active_reminder_badge_count(today=date(2026, 5, 16))
            state["deleted_reminders"] = [
                {**reminder_row, "Action": self.app.REMINDER_ACTION_SENT, "ActionedAt": "2026-05-16T10:00:00"},
            ]
            third_count = self.app.get_active_reminder_badge_count(today=date(2026, 5, 16))

        self.assertEqual(first_count, 1)
        self.assertEqual(second_count, 1)
        self.assertEqual(third_count, 0)
        self.assertEqual(mock_bundle.call_count, 1)

    def test_badge_count_without_rules_skips_prepared_dataframe_work(self):
        state = self.app.st.session_state
        state["working_df"] = pd.DataFrame({"row": [1]})

        with (
            mock.patch.object(self.app, "get_applied_reminder_rules", return_value={}),
            mock.patch.object(self.app, "get_prepared_df", side_effect=AssertionError("no rules should not prepare reminders")),
        ):
            count = self.app.get_active_reminder_badge_count(today=date(2026, 5, 16))

        self.assertEqual(count, 0)

    def test_hidden_reminders_index_invalidates_after_in_place_key_change(self):
        record = {
            "Reminder Date": "16 May 2026",
            "Due Date": "16 May 2026",
            "Client Name": "Client A",
            "Animal Name": "Pet A",
            "Plan Item": "Rabies",
        }
        state = self.app.st.session_state
        state["deleted_reminders"] = [record]

        original_index = self.app.get_hidden_reminders_index()
        self.assertIn(self.app.hidden_reminder_key(record), original_index)

        original_key = self.app.hidden_reminder_key(record)
        record["Client Name"] = "Client B"
        updated_key = self.app.hidden_reminder_key(record)
        updated_index = self.app.get_hidden_reminders_index()

        self.assertNotIn(original_key, updated_index)
        self.assertIn(updated_key, updated_index)

    def test_hidden_reminder_record_uses_provided_index(self):
        row = {
            "Reminder Date": "16 May 2026",
            "Due Date": "16 May 2026",
            "Client Name": "Client A",
            "Animal Name": "Pet A",
            "Plan Item": "Rabies",
        }
        record = {**row, "Action": self.app.REMINDER_ACTION_SENT}
        hidden_index = {self.app.hidden_reminder_key(row): record}

        with mock.patch.object(
            self.app,
            "get_hidden_reminders_index",
            side_effect=AssertionError("provided hidden index should be reused"),
        ):
            self.assertIs(self.app.get_hidden_reminder_record(row, hidden_index=hidden_index), record)

    def test_active_reminder_window_reuses_filter_exclusion_and_grouping_work(self):
        prepared = pd.DataFrame({
            "ReminderDateTs": pd.to_datetime(["2026-05-15", "2026-05-16", "2026-05-20"]),
            "NextDueDate": pd.to_datetime(["2026-05-15", "2026-05-16", "2026-05-20"]),
            "Client Name": ["Client A", "Client B", "Client C"],
            "Animal Name": ["Pet A", "Pet B", "Pet C"],
            "Plan Item": ["Rabies", "Dental", "Nails"],
        })
        grouped = pd.DataFrame([
            {
                "Reminder Date": "15 May 2026",
                "Due Date": "15 May 2026",
                "Client Name": "Client A",
                "Animal Name": "Pet A",
                "Plan Item": "Rabies",
            },
            {
                "Reminder Date": "16 May 2026",
                "Due Date": "16 May 2026",
                "Client Name": "Client B",
                "Animal Name": "Pet B",
                "Plan Item": "Dental",
            },
        ])
        mock_bundle = mock.Mock(return_value=grouped)

        with mock.patch.object(self.app, "bundle_client_reminders_by_window", mock_bundle):
            first_grouped, first_before_exclusions = self.app.build_active_reminder_window(
                prepared,
                {},
                date(2026, 5, 15),
                date(2026, 5, 16),
                1,
            )
            second_grouped, second_before_exclusions = self.app.build_active_reminder_window(
                prepared,
                {},
                date(2026, 5, 15),
                date(2026, 5, 16),
                1,
            )

        self.assertEqual(first_before_exclusions, 2)
        self.assertEqual(second_before_exclusions, 2)
        pd.testing.assert_frame_equal(first_grouped, grouped)
        pd.testing.assert_frame_equal(second_grouped, grouped)
        self.assertEqual(mock_bundle.call_count, 1)
        due_df = mock_bundle.call_args.args[0]
        self.assertEqual(list(due_df["Client Name"]), ["Client A", "Client B"])

    def test_caught_up_banner_copy_only_when_notification_count_is_zero(self):
        self.assertIsNone(self.app.reminders_caught_up_banner_copy(active_count=2, lookback_days=5))

        title, body = self.app.reminders_caught_up_banner_copy(active_count=0, lookback_days=5)

        self.assertEqual(title, "Good job! All due reminders have been actioned.")
        self.assertIn("today and the previous 5 days", body)

    def test_caught_up_banner_period_copy_handles_short_windows(self):
        self.assertEqual(self.app.reminders_caught_up_period_text(0), "today")
        self.assertEqual(self.app.reminders_caught_up_period_text(1), "today and yesterday")

    def test_no_reminders_info_is_hidden_when_caught_up_banner_is_visible(self):
        self.assertFalse(self.app.should_show_no_reminders_info(0, 0))
        self.assertFalse(self.app.should_show_no_reminders_info(0, None))
        self.assertTrue(self.app.should_show_no_reminders_info(0, 2))
        self.assertTrue(self.app.should_show_no_reminders_info(1, 0))


if __name__ == "__main__":
    unittest.main()
