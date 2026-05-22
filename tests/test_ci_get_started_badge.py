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
        reminder_items = next(module for module in modules if module["tab"] == "Send Reminders")["items"]
        configure_items = next(module for module in modules if module["tab"] == "Configure Reminders")["items"]
        exclusion_items = next(module for module in modules if module["tab"] == "Exclusions")["items"]
        identify_items = next(module for module in modules if module["tab"] == "Identify")["items"]

        self.assertEqual(
            module_titles,
            [
                "Send Reminders",
                "Configure Reminders",
                "Exclusions",
                "Identify",
                "Track",
                "Upload Data",
            ],
        )
        self.assertIn("Review the General WhatsApp template", [item["label"] for item in reminder_items])
        self.assertNotIn("Action a reminder as declined", [item["label"] for item in reminder_items])
        self.assertIn("Add first, second, or overdue reminder timing", [item["label"] for item in configure_items])
        self.assertIn("Review Top Unreminded Items", [item["label"] for item in configure_items])
        self.assertIn("Review automatic death keywords", [item["label"] for item in exclusion_items])
        self.assertEqual(
            [item["label"] for item in identify_items],
            ["Review total potential annual revenue lift", "Review top revenue lift items"],
        )
        self.assertFalse(any(item["auto_done"] for item in identify_items))
        self.assertNotIn("Account", module_titles)

    def test_get_started_reminder_timing_auto_completes_from_rules(self):
        state = self.app.st.session_state
        state["rules"] = self.app.normalize_search_term_rules(
            {
                "bravecto": {
                    "category": "Medications",
                    "days": 90,
                    "use_qty": False,
                },
            }
        )

        timing_item = next(
            item
            for module in self.app.get_setup_checklist_modules()
            for item in module["items"]
            if item["id"] == "check_rule_days"
        )
        self.assertFalse(timing_item["done"])

        state["rules"]["bravecto"]["reminder_1"] = 80
        timing_item = next(
            item
            for module in self.app.get_setup_checklist_modules()
            for item in module["items"]
            if item["id"] == "check_rule_days"
        )
        self.assertTrue(timing_item["done"])

        state["get_started_done_check_rule_days"] = False
        self.app.update_get_started_manual_item("check_rule_days", auto_done=True)
        timing_item = next(
            item
            for module in self.app.get_setup_checklist_modules()
            for item in module["items"]
            if item["id"] == "check_rule_days"
        )
        self.assertFalse(timing_item["done"])

        state["rules"]["bravecto"]["overdue_reminder"] = 100
        timing_item = next(
            item
            for module in self.app.get_setup_checklist_modules()
            for item in module["items"]
            if item["id"] == "check_rule_days"
        )
        self.assertTrue(timing_item["done"])

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

    def test_reset_get_started_checklist_clears_manual_and_review_progress(self):
        state = self.app.st.session_state
        state["working_df"] = pd.DataFrame({"ChargeDate": pd.to_datetime(["2026-05-01"])})
        state["client_exclusions"] = ["Client A"]
        state["patient_exclusions"] = [{"client": "Client A", "patient": "Pet A"}]
        state["exclusions"] = ["admin fee"]
        state["client_item_exclusions"] = [{"client": "Client A", "item": "Item A"}]
        state["patient_passaway_keywords"] = ["passed away"]
        state["outcome_due_date_window_days"] = 30
        state["outcome_post_reminder_window_days"] = 10
        state[self.app.GET_STARTED_MANUAL_DONE_KEY] = {
            "review_search_terms": True,
            "add_search_term": True,
        }
        state[self.app.GET_STARTED_MANUAL_OFF_KEY] = {"upload_data": "2026-05-01T10:00:00"}
        state[self.app.GET_STARTED_VISITED_TABS_KEY] = ["Search Terms", "Stats", "Upload Data"]
        state["search_terms_reviewed"] = True
        state["wa_template_reviewed"] = True
        state["get_started_done_review_search_terms"] = True
        state["get_started_done_review_top_unreminded_items"] = True

        self.assertTrue(
            next(
                item
                for module in self.app.get_setup_checklist_modules()
                for item in module["items"]
                if item["id"] == "review_search_terms"
            )["done"]
        )
        for item_id in (
            "add_client_exclusion",
            "add_patient_exclusion",
            "add_item_exclusion",
            "add_client_item_exclusion",
            "review_death_keywords",
        ):
            self.assertTrue(
                next(
                    item
                    for module in self.app.get_setup_checklist_modules()
                    for item in module["items"]
                    if item["id"] == item_id
                )["done"],
                item_id,
            )
        self.assertTrue(
            next(
                item
                for module in self.app.get_setup_checklist_modules()
                for item in module["items"]
                if item["id"] == "add_patient_exclusion"
            )["done"]
        )
        self.assertTrue(
            next(
                item
                for module in self.app.get_setup_checklist_modules()
                for item in module["items"]
                if item["id"] == "test_success_windows"
            )["done"]
        )

        self.app.reset_get_started_checklist_state()

        self.assertEqual(state[self.app.GET_STARTED_MANUAL_DONE_KEY], {})
        self.assertEqual(state[self.app.GET_STARTED_MANUAL_OFF_KEY], {})
        self.assertEqual(state[self.app.GET_STARTED_VISITED_TABS_KEY], [])
        self.assertFalse(state["search_terms_reviewed"])
        self.assertFalse(state["wa_template_reviewed"])
        self.assertNotIn("get_started_done_review_search_terms", state)
        self.assertNotIn("get_started_done_review_top_unreminded_items", state)
        self.assertFalse(
            next(
                item
                for module in self.app.get_setup_checklist_modules()
                for item in module["items"]
                if item["id"] == "review_search_terms"
            )["done"]
        )
        self.assertFalse(
            next(
                item
                for module in self.app.get_setup_checklist_modules()
                for item in module["items"]
                if item["id"] == "review_top_unreminded_items"
            )["done"]
        )
        for item_id in (
            "add_client_exclusion",
            "add_patient_exclusion",
            "add_item_exclusion",
            "add_client_item_exclusion",
            "review_death_keywords",
        ):
            self.assertFalse(
                next(
                    item
                    for module in self.app.get_setup_checklist_modules()
                    for item in module["items"]
                    if item["id"] == item_id
                )["done"],
                item_id,
            )
        self.assertFalse(
            next(
                item
                for module in self.app.get_setup_checklist_modules()
                for item in module["items"]
                if item["id"] == "test_success_windows"
            )["done"]
        )

        state["client_exclusions"].append("Client B")
        state["patient_exclusions"].append({"client": "Client B", "patient": "Pet B"})
        state["exclusions"].append("dispensing fee")
        state["client_item_exclusions"].append({"client": "Client B", "item": "Item B"})
        state["patient_passaway_keywords"].append("deceased")
        state["outcome_due_date_window_days"] = 45
        for item_id in (
            "add_client_exclusion",
            "add_patient_exclusion",
            "add_item_exclusion",
            "add_client_item_exclusion",
            "review_death_keywords",
        ):
            self.assertTrue(
                next(
                    item
                    for module in self.app.get_setup_checklist_modules()
                    for item in module["items"]
                    if item["id"] == item_id
                )["done"],
                item_id,
            )
        self.assertTrue(
            next(
                item
                for module in self.app.get_setup_checklist_modules()
                for item in module["items"]
                if item["id"] == "test_success_windows"
            )["done"]
        )

    def test_stats_tab_shows_track_without_new_badge(self):
        label = self.app.main_section_tab_label("Stats")

        self.assertEqual(label, "Track")
        self.assertNotIn("New Stats tab", label)
        self.assertNotIn("data:image/svg+xml;base64", label)
        self.assertEqual(self.app.main_section_tab_label("Identify"), "Identify")

    def test_inactive_reminders_badge_uses_cached_count_only(self):
        state = self.app.st.session_state
        state["working_df"] = pd.DataFrame({"ChargeDate": pd.to_datetime(["2026-05-01"])})
        state["applied_rules"] = self.app.clone_reminder_rules(self.app.DEFAULT_RULES)
        cache_key = self.app.active_reminder_badge_cache_key(
            self.app.user_today(),
            state["applied_rules"],
        )
        state["_active_reminder_badge_cache"] = {"key": cache_key, "count": 7}

        with mock.patch.object(self.app, "get_active_reminder_badge_count", side_effect=AssertionError("expensive badge count")):
            self.assertEqual(self.app.main_section_tab_badge_count("Reminders", allow_expensive_counts=False), 7)

        state["_active_reminder_badge_cache"] = {"key": ("stale",), "count": 7}
        with mock.patch.object(self.app, "get_active_reminder_badge_count", side_effect=AssertionError("expensive badge count")):
            self.assertEqual(self.app.main_section_tab_badge_count("Reminders", allow_expensive_counts=False), 0)

    def test_inactive_upload_data_badge_uses_session_only_count(self):
        state = self.app.st.session_state
        state["dataset_upload_history"] = [
            {
                "file_name": "recent.csv",
                "pms": "Test",
                "rows": 10,
                "from": "2026-05-01",
                "to": "2026-05-10",
                "status": "Saved",
            }
        ]

        with mock.patch.object(self.app, "get_saved_dataset_summary_rows", side_effect=AssertionError("expensive upload badge")):
            self.assertEqual(self.app.main_section_tab_badge_count("Upload Data", allow_expensive_counts=False), 1)

    def test_main_tab_badge_svg_has_optical_vertical_centering(self):
        label = self.app.tab_badge_label_text("Stats", "New", "New Stats tab", fill="#23513a")
        encoded = re.search(r"base64,([A-Za-z0-9+/=]+)", label).group(1)
        svg = base64.b64decode(encoded).decode("utf-8")

        self.assertIn('dy="0.08em"', svg)
        self.assertIn('alignment-baseline="middle"', svg)

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
        with mock.patch.object(self.app, "set_query_param") as set_query_param:
            self.app.mark_new_account_welcome_pending()

        self.assertTrue(self.app.st.session_state["show_new_account_welcome_dialog"])
        self.assertEqual(self.app.st.session_state["main_section_tab"], "Upload Data")
        self.assertTrue(self.app.st.session_state[self.app.SCROLL_TO_PAGE_TOP_KEY])
        set_query_param.assert_called_once_with(
            self.app.MAIN_SECTION_TAB_QUERY_PARAM,
            "upload-data",
        )

        self.app.close_new_account_welcome_dialog()
        self.assertFalse(self.app.st.session_state["show_new_account_welcome_dialog"])

    def test_pending_page_top_scroll_is_one_shot(self):
        self.app.queue_scroll_to_page_top()

        with mock.patch.object(self.app.components, "html") as html:
            self.app.render_pending_page_top_scroll()

        self.assertNotIn(self.app.SCROLL_TO_PAGE_TOP_KEY, self.app.st.session_state)
        html.assert_called_once()
        scroll_script = html.call_args.args[0]
        self.assertIn("scrollTo({top: 0", scroll_script)
        self.assertIn('data-testid="stAppViewContainer"', scroll_script)
        self.assertEqual(html.call_args.kwargs["height"], 0)

        with mock.patch.object(self.app.components, "html") as html:
            self.app.render_pending_page_top_scroll()

        html.assert_not_called()

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
