import contextlib
import base64
import importlib
import io
import re
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
        incomplete_count = self.app.get_started_incomplete_count()
        self.assertGreater(incomplete_count, 6)
        badge_label = self.app.get_started_badge_label()
        self.assertIn(f"{incomplete_count} setup steps remaining", badge_label)
        self.assertIn(str(incomplete_count), badge_label)

        state = self.app.st.session_state
        state[self.app.GET_STARTED_MANUAL_DONE_KEY] = {
            entry["id"]: True
            for module in self.app.get_setup_checklist_modules()
            for entry in module["items"]
        }

        self.assertEqual(self.app.get_started_incomplete_count(), 0)
        self.assertEqual(self.app.get_started_badge_label(), "Get Started")

    def test_get_started_modules_include_tab_feature_guidance(self):
        modules = self.app.get_setup_checklist_modules()
        module_titles = [module["tab"] for module in modules]
        reminder_items = next(module for module in modules if module["tab"] == "Reminders")["items"]
        exclusion_items = next(module for module in modules if module["tab"] == "Exclusions")["items"]

        self.assertIn("Upload Data", module_titles)
        self.assertIn("Search Terms", module_titles)
        self.assertIn("Reminders", module_titles)
        self.assertIn("Exclusions", module_titles)
        self.assertIn("Stats", module_titles)
        self.assertIn("Create a new WhatsApp template", [item["label"] for item in reminder_items])
        self.assertIn("Review automatic death keywords", [item["label"] for item in exclusion_items])

    def test_auto_completed_get_started_item_can_be_manually_turned_off(self):
        state = self.app.st.session_state
        state["working_df"] = pd.DataFrame({"ChargeDate": pd.to_datetime(["2026-05-01"])})
        state["shared_dataset_updated_at"] = "2026-05-01T10:00:00"
        self.assertTrue(
            next(
                item
                for module in self.app.get_setup_checklist_modules()
                for item in module["items"]
                if item["id"] == "upload_data"
            )["done"]
        )

        state["get_started_done_upload_data"] = False
        self.app.update_get_started_manual_item("upload_data", auto_done=True)

        self.assertFalse(
            next(
                item
                for module in self.app.get_setup_checklist_modules()
                for item in module["items"]
                if item["id"] == "upload_data"
            )["done"]
        )

        state[self.app.GET_STARTED_MANUAL_OFF_KEY] = {}
        self.assertTrue(
            next(
                item
                for module in self.app.get_setup_checklist_modules()
                for item in module["items"]
                if item["id"] == "upload_data"
            )["done"]
        )

    def test_stats_tab_shows_new_badge(self):
        label = self.app.main_section_tab_label("Stats")

        self.assertIn("Stats", label)
        self.assertIn("New Stats tab", label)
        self.assertIn("data:image/svg+xml;base64", label)

    def test_graphs_tab_shows_coming_soon_badge(self):
        label = self.app.main_section_tab_label("Graphs")

        self.assertIn("Graphs", label)
        self.assertIn("Graphs coming soon", label)
        self.assertIn("data:image/svg+xml;base64", label)

    def test_main_tab_badge_svg_has_optical_vertical_centering(self):
        label = self.app.tab_badge_label_text("Stats", "New", "New Stats tab", fill="#23513a")
        encoded = re.search(r"base64,([A-Za-z0-9+/=]+)", label).group(1)
        svg = base64.b64decode(encoded).decode("utf-8")

        self.assertIn('dy="0.08em"', svg)
        self.assertIn('alignment-baseline="middle"', svg)

    def test_new_and_soon_badges_use_normal_text_weight(self):
        for label in (self.app.stats_badge_label(), self.app.graphs_badge_label()):
            encoded = re.search(r"base64,([A-Za-z0-9+/=]+)", label).group(1)
            svg = base64.b64decode(encoded).decode("utf-8")

            self.assertIn('font-weight="400"', svg)

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
