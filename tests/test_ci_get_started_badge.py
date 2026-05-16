import contextlib
import importlib
import io
import unittest

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


if __name__ == "__main__":
    unittest.main()
