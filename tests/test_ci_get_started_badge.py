import contextlib
import importlib
import io
import unittest
from unittest import mock

import pandas as pd


class GetStartedBadgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            cls.app = importlib.import_module("reminders_app_v3")

    def setUp(self):
        state = self.app.st.session_state
        for key in list(state.keys()):
            del state[key]

    def test_badge_count_matches_incomplete_setup_actions(self):
        self.assertEqual(self.app.get_started_incomplete_count(), 6)
        self.assertIn("setup steps remaining", self.app.get_started_badge_label())

        state = self.app.st.session_state
        state["working_df"] = pd.DataFrame({"ChargeDate": pd.to_datetime(["2026-05-01"])})
        state["shared_dataset_updated_at"] = "2026-05-01T10:00:00"
        state["search_term_added"] = True
        state["search_term_added_at"] = "2026-05-01T10:01:00"
        state["user_name"] = "Clinic Team"
        state["user_name_updated_at"] = "2026-05-01T10:02:00"
        state["wa_template_updated"] = True
        state["wa_template_updated_at"] = "2026-05-01T10:03:00"
        state["wa_reminder_log"] = [{"Client Name": "A Client", "RemindedAt": "2026-05-01T10:04:00"}]
        state["deleted_reminders"] = [{"Action": self.app.REMINDER_ACTION_DECLINED, "ActionedAt": "2026-05-01T10:05:00"}]

        self.assertEqual(self.app.get_started_incomplete_count(), 0)
        self.assertEqual(self.app.get_started_badge_label(), "Get Started")

    def test_get_started_steps_include_template_guidance(self):
        steps = self.app.get_setup_checklist_steps()
        step_titles = [step["title"] for step in steps]
        template_step = next(step for step in steps if step["number"] == 4)

        self.assertIn("Review message templates", step_titles)
        self.assertIn("Add extra templates", template_step["copy"])

    def test_stats_tab_shows_new_badge(self):
        label = self.app.main_section_tab_label("Stats")

        self.assertIn("Stats", label)
        self.assertIn("New Stats tab", label)
        self.assertIn("data:image/svg+xml;base64", label)

    def test_new_account_welcome_copy_is_clear_and_actionable(self):
        html = self.app.new_account_welcome_dialog_html()

        self.assertIn("Set up your first reminders", html)
        self.assertIn("Four calm steps", html)
        self.assertIn("Upload your data", html)
        self.assertIn("Set your reminder rules", html)
        self.assertIn("Prepare your message", html)
        self.assertIn("Clear the list as you work", html)
        self.assertIn("sales export from your PMS", html)
        self.assertIn("search terms and template work are not lost", html)
        self.assertNotIn("<h3>Welcome to Clinic Reminders</h3>", html)
        self.assertNotIn("\n    <section", html)
        self.assertNotIn("\n        <section", html)
        self.assertNotIn("I'll explore first", html)

    def test_new_account_welcome_pending_flag_is_session_scoped(self):
        self.app.mark_new_account_welcome_pending()
        self.assertTrue(self.app.st.session_state["show_new_account_welcome_dialog"])

        self.app.close_new_account_welcome_dialog()
        self.assertFalse(self.app.st.session_state["show_new_account_welcome_dialog"])

    def test_welcome_get_started_navigation_targets_upload_data(self):
        with mock.patch.object(self.app, "set_query_param") as set_query_param:
            self.app.navigate_main_section_tab("Upload Data")

        self.assertEqual(self.app.st.session_state["main_section_tab"], "Upload Data")
        set_query_param.assert_called_once_with(
            self.app.MAIN_SECTION_TAB_QUERY_PARAM,
            "upload-data",
        )

    def test_late_main_section_tab_update_is_deferred(self):
        app = self.app

        class LockedMainTabState(dict):
            def __setitem__(self, key, value):
                if key == "main_section_tab":
                    raise app.st.errors.StreamlitAPIException("Widget key already exists")
                super().__setitem__(key, value)

        locked_state = LockedMainTabState()

        with mock.patch.object(app.st, "session_state", locked_state):
            app.set_main_section_tab("Upload Data")

        self.assertNotIn("main_section_tab", locked_state)
        self.assertEqual(locked_state[app.PENDING_MAIN_SECTION_TAB_KEY], "Upload Data")

    def test_pending_main_section_tab_is_consumed_before_widget_render(self):
        self.app.st.session_state[self.app.PENDING_MAIN_SECTION_TAB_KEY] = "Upload Data"

        with mock.patch.object(self.app, "get_query_param_value", return_value=""):
            self.app.consume_main_section_tab_query_param()

        self.assertEqual(self.app.st.session_state["main_section_tab"], "Upload Data")
        self.assertNotIn(self.app.PENDING_MAIN_SECTION_TAB_KEY, self.app.st.session_state)

    def test_main_section_query_param_selects_tab_then_clears_url(self):
        with (
            mock.patch.object(self.app, "get_query_param_value", return_value="upload-data"),
            mock.patch.object(self.app, "clear_query_param") as clear_query_param,
        ):
            self.app.consume_main_section_tab_query_param()

        self.assertEqual(self.app.st.session_state["main_section_tab"], "Upload Data")
        clear_query_param.assert_called_once_with(self.app.MAIN_SECTION_TAB_QUERY_PARAM)

    def test_legacy_reporting_query_params_select_stats_tab(self):
        for slug in ["outcomes", "statistics", "stats"]:
            with self.subTest(slug=slug):
                self.app.st.session_state.pop("main_section_tab", None)
                with (
                    mock.patch.object(self.app, "get_query_param_value", return_value=slug),
                    mock.patch.object(self.app, "clear_query_param"),
                ):
                    self.app.consume_main_section_tab_query_param()

                self.assertEqual(self.app.st.session_state["main_section_tab"], "Stats")


if __name__ == "__main__":
    unittest.main()
