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
        self.assertEqual(self.app.reminders_badge_label(count=0), "Send Reminders")

        label = self.app.reminders_badge_label(count=3)

        self.assertIn("Send Reminders", label)
        self.assertIn("3 active reminders in the look-back window", label)
        self.assertIn("data:image/svg+xml;base64", label)

    def test_default_reminder_filter_days_match_send_reminders_defaults(self):
        self.assertEqual(self.app.DEFAULT_REMINDER_LOOKBACK_DAYS, 1)
        self.assertEqual(self.app.DEFAULT_REMINDER_WINDOW_DAYS, 0)
        self.assertEqual(self.app.DEFAULT_REMINDER_GROUP_DAYS, 3)
        self.assertEqual(self.app.DEFAULT_REMINDER_WARNING_DAYS, 7)
        self.assertEqual(self.app.normalized_reminder_lookback_days(), 1)
        self.assertEqual(self.app.normalized_reminder_window_days(), 0)
        self.assertEqual(self.app.normalized_reminder_group_days(), 3)
        self.assertEqual(self.app.normalized_reminder_warning_days(), 7)
        self.assertEqual(self.app.normalized_reminder_lookback_days("bad"), 1)

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
        self.assertEqual(state[self.app.REMINDER_LOOKBACK_DAYS_WIDGET_KEY], 9)
        self.assertEqual(state[self.app.REMINDER_WINDOW_DAYS_WIDGET_KEY], 8)
        self.assertEqual(state[self.app.REMINDER_GROUP_DAYS_WIDGET_KEY], 3)
        self.assertEqual(state[self.app.REMINDER_WARNING_DAYS_WIDGET_KEY], 4)

    def test_reminder_filter_controls_restore_widgets_from_durable_settings_after_tab_navigation(self):
        state = self.app.st.session_state
        state["reminder_lookback_days"] = 6
        state["reminder_window_days"] = 2
        state["client_group_days"] = 4
        state["reminder_warning_days"] = 10

        self.app.initialize_reminder_filter_controls(date(2026, 5, 18))

        self.assertEqual(state["reminder_lookback_days"], 6)
        self.assertEqual(state["reminder_window_days"], 2)
        self.assertEqual(state["client_group_days"], 4)
        self.assertEqual(state["reminder_warning_days"], 10)
        self.assertEqual(state[self.app.REMINDER_LOOKBACK_DAYS_WIDGET_KEY], 6)
        self.assertEqual(state[self.app.REMINDER_WINDOW_DAYS_WIDGET_KEY], 2)
        self.assertEqual(state[self.app.REMINDER_GROUP_DAYS_WIDGET_KEY], 4)
        self.assertEqual(state[self.app.REMINDER_WARNING_DAYS_WIDGET_KEY], 10)

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

    def test_send_reminders_prepared_rows_are_cached_by_selected_date(self):
        state = self.app.st.session_state
        state["data_version"] = 1
        sales = pd.DataFrame({
            "ChargeDate": pd.to_datetime(["2026-05-15", "2026-05-17"]),
            "Item Name": ["Rabies", "Dental"],
        })
        rules = {"rabies": {"days": 365}}
        built_frames = []

        def build_side_effect(frame, _rules):
            built_frames.append(frame.copy())
            return pd.DataFrame({
                "ReminderDateTs": pd.to_datetime(["2026-05-16"]),
                "NextDueDate": pd.to_datetime(["2026-05-16"]),
                "BaseIntervalDays": [365],
            })

        with mock.patch.object(self.app, "build_prepared_reminder_rows", side_effect=build_side_effect) as build:
            first = self.app.get_prepared_reminder_rows_for_date(sales, rules, date(2026, 5, 16))
            second = self.app.get_prepared_reminder_rows_for_date(sales, rules, date(2026, 5, 16))

        self.assertIs(first, second)
        self.assertEqual(build.call_count, 1)
        self.assertEqual(list(built_frames[0]["Item Name"]), ["Rabies"])
        self.assertIs(self.app.get_cached_prepared_reminder_rows_for_date(sales, rules, date(2026, 5, 16)), first)

    def test_active_reminder_window_cache_probe_matches_build_cache(self):
        prepared = pd.DataFrame({
            "ReminderDateTs": pd.to_datetime(["2026-05-16"]),
            "NextDueDate": pd.to_datetime(["2026-05-16"]),
            "Client Name": ["Client A"],
            "Animal Name": ["Pet A"],
            "Item Name": ["Rabies"],
            "MatchedItems": [["rabies"]],
        })
        grouped = pd.DataFrame([{
            "Reminder Date": "16 May 2026",
            "Due Date": "16 May 2026",
            "Client Name": "Client A",
            "Animal Name": "Pet A",
            "Plan Item": "Rabies",
        }])
        rules = {"rabies": {"days": 365}}

        self.assertFalse(
            self.app.active_reminder_window_is_cached(
                prepared,
                rules,
                date(2026, 5, 16),
                date(2026, 5, 16),
                1,
            )
        )
        with mock.patch.object(self.app, "bundle_client_reminders_by_window", return_value=grouped):
            self.app.build_active_reminder_window(
                prepared,
                rules,
                date(2026, 5, 16),
                date(2026, 5, 16),
                1,
            )

        self.assertTrue(
            self.app.active_reminder_window_is_cached(
                prepared,
                rules,
                date(2026, 5, 16),
                date(2026, 5, 16),
                1,
            )
        )

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

    def test_active_reminders_nav_uses_cached_badge_without_expensive_count(self):
        class FakeColumn:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        button_labels = []

        def fake_button(label, *args, **kwargs):
            button_labels.append(label)
            return False

        with (
            mock.patch.object(self.app, "cached_upload_data_needs_initial_upload", return_value=False),
            mock.patch.object(self.app, "get_cached_active_reminder_badge_count", return_value=4),
            mock.patch.object(self.app, "get_active_reminder_badge_count", side_effect=AssertionError("active nav should not derive badge")),
            mock.patch.object(self.app, "get_started_incomplete_count", return_value=0),
            mock.patch.object(self.app, "cached_upload_data_badge_count", return_value=0),
            mock.patch.object(self.app.st, "markdown"),
            mock.patch.object(self.app.st, "columns", return_value=[FakeColumn() for _ in self.app.MAIN_SECTION_TABS]),
            mock.patch.object(self.app.st, "button", side_effect=fake_button),
        ):
            self.app.render_main_section_nav("Reminders")

        self.assertTrue(any("4 active reminders in the look-back window" in label for label in button_labels))

    def test_badge_count_can_be_derived_and_cached_from_visible_window(self):
        today_row = {
            "Reminder Date": "16 May 2026",
            "Due Date": "16 May 2026",
            "Client Name": "Client A",
            "Animal Name": "Pet A",
            "Plan Item": "Rabies",
        }
        lookback_row = {
            "Reminder Date": "14 May 2026",
            "Due Date": "14 May 2026",
            "Client Name": "Client B",
            "Animal Name": "Pet B",
            "Plan Item": "Dental",
        }
        future_row = {
            "Reminder Date": "18 May 2026",
            "Due Date": "18 May 2026",
            "Client Name": "Client C",
            "Animal Name": "Pet C",
            "Plan Item": "Annual Exam",
        }
        actioned_row = {
            "Reminder Date": "15 May 2026",
            "Due Date": "15 May 2026",
            "Client Name": "Client D",
            "Animal Name": "Pet D",
            "Plan Item": "Librela",
        }
        grouped = pd.DataFrame([today_row, lookback_row, future_row, actioned_row])
        rules = {"rabies": {"days": 365}}
        state = self.app.st.session_state
        state["working_df"] = pd.DataFrame({"row": [1]})
        state["reminder_lookback_days"] = 2
        state["client_group_days"] = 1
        state["deleted_reminders"] = [
            {**actioned_row, "Action": self.app.REMINDER_ACTION_SENT, "ActionedAt": "2026-05-16T10:00:00"},
        ]

        count = self.app.derive_active_reminder_badge_count_from_window(
            grouped,
            date(2026, 5, 14),
            date(2026, 5, 16),
        )
        self.app.cache_active_reminder_badge_count(count, date(2026, 5, 16), rules)

        self.assertEqual(count, 2)
        with mock.patch.object(self.app, "get_applied_reminder_rules", return_value=rules):
            self.assertEqual(self.app.get_cached_active_reminder_badge_count(date(2026, 5, 16)), 2)

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
