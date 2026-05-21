import contextlib
import importlib
import io
import unittest
from unittest.mock import patch

import pandas as pd


class ReminderGroupingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            cls.app = importlib.import_module("reminders_app_v3")

    def make_due_df(self):
        return pd.DataFrame(
            {
                "ReminderDate": pd.to_datetime(["2025-10-04", "2025-10-05", "2025-10-06"]),
                "ReminderDateFmt": ["04 Oct 2025", "05 Oct 2025", "06 Oct 2025"],
                "DueDateFmt": ["14 Oct 2025", "15 Oct 2025", "16 Oct 2025"],
                "ChargeDate": pd.to_datetime(["2025-09-04", "2025-09-05", "2025-09-06"]),
                "ChargeDateFmt": ["04 Sep 2025", "05 Sep 2025", "06 Sep 2025"],
                "Client Name": ["Same Client", "Same Client", "Same Client"],
                "Animal Name": ["Alpha", "Bravo", "Charlie"],
                "Item Name": ["Item A", "Item B", "Item C"],
                "MatchedItems": [["Item A"], ["Item B"], ["Item C"]],
                "Qty": [1, 1, 1],
                "IntervalDays": [30, 30, 30],
                "BaseIntervalDays": [30, 30, 30],
            }
        )

    def test_top_unreminded_items_rank_uncovered_items(self):
        state = self.app.st.session_state
        for key in list(state.keys()):
            del state[key]
        state["exclusions"] = ["food"]
        sales = pd.DataFrame(
            {
                "Item Name": [
                    "Rabies Vaccine",
                    "Nail Clip",
                    "Nail Clip",
                    "Dental Scale",
                    "Food Bag",
                    "Food Bag",
                    "Food Bag",
                ],
                "Qty": [1, 1, 1, 1, 1, 1, 1],
                "Amount": [40, 12, 15, 220, 30, 35, 40],
            }
        )
        rules = {"rabies": {"days": 365, "use_qty": False}}

        by_count, by_revenue = self.app.build_top_unreminded_items(sales, rules)

        self.assertEqual(by_count.iloc[0]["Item Name"], "Nail Clip")
        self.assertEqual(int(by_count.iloc[0]["Count"]), 2)
        self.assertNotIn("Rabies Vaccine", set(by_count["Item Name"]))
        self.assertNotIn("Food Bag", set(by_count["Item Name"]))
        self.assertEqual(by_revenue.iloc[0]["Item Name"], "Dental Scale")
        self.assertEqual(float(by_revenue.iloc[0]["Revenue"]), 220.0)

    def test_excluding_top_unreminded_item_adds_general_item_exclusion(self):
        state = self.app.st.session_state
        for key in list(state.keys()):
            del state[key]
        state["exclusions"] = []
        state["_top_unreminded_items_cache"] = {"key": ("old",)}

        with (
            patch.object(self.app, "save_settings_quietly", return_value=True),
            patch.object(self.app, "record_settings_audit_event"),
        ):
            self.app.exclude_top_unreminded_item("Nail Clip")

        self.assertEqual(state["exclusions"], ["nail clip"])
        self.assertNotIn("_top_unreminded_items_cache", state)

    def test_excluding_multiple_top_unreminded_items_saves_once_and_dedupes(self):
        state = self.app.st.session_state
        for key in list(state.keys()):
            del state[key]
        state["exclusions"] = ["existing item"]
        state["_top_unreminded_items_cache"] = {"key": ("old",)}

        with (
            patch.object(self.app, "save_settings_quietly", return_value=True) as save_settings,
            patch.object(self.app, "record_settings_audit_event") as audit_event,
        ):
            added = self.app.exclude_top_unreminded_items([
                "Nail Clip",
                " existing item ",
                "Dental Scale",
                "Nail   Clip",
                "",
            ])

        self.assertEqual(added, 2)
        self.assertEqual(state["exclusions"], ["existing item", "nail clip", "dental scale"])
        save_settings.assert_called_once()
        self.assertEqual(audit_event.call_count, 2)
        self.assertNotIn("_top_unreminded_items_cache", state)

    def test_zero_disables_grouping(self):
        grouped = self.app.bundle_client_reminders_by_window(self.make_due_df(), window_days=0)
        self.assertEqual(len(grouped), 3)

    def test_one_groups_same_day_only(self):
        due_df = self.make_due_df()
        due_df.loc[1, "ReminderDate"] = pd.Timestamp("2025-10-04")
        due_df.loc[1, "ReminderDateFmt"] = "04 Oct 2025"

        grouped = self.app.bundle_client_reminders_by_window(due_df, window_days=1)

        self.assertEqual(len(grouped), 2)
        self.assertIn("Alpha and Bravo", set(grouped["Animal Name"]))

    def test_two_groups_adjacent_dates(self):
        grouped = self.app.bundle_client_reminders_by_window(self.make_due_df(), window_days=2)

        self.assertEqual(len(grouped), 2)
        self.assertIn("04 Oct 2025 | 05 Oct 2025", set(grouped["Reminder Date"]))

    def test_patient_exclusions_apply_before_grouping(self):
        due_df = self.make_due_df()
        due_df.loc[1, "ReminderDate"] = pd.Timestamp("2025-10-04")
        due_df.loc[1, "ReminderDateFmt"] = "04 Oct 2025"
        self.app.st.session_state["client_exclusions"] = []
        self.app.st.session_state["patient_exclusions"] = [
            {"client": "Same Client", "patient": "Alpha"}
        ]
        self.app.st.session_state["client_item_exclusions"] = []
        self.app.st.session_state["automatic_patient_exclusions"] = []
        self.app.st.session_state["exclusions"] = []

        filtered = self.app.apply_reminder_exclusion_filters(due_df, self.app.DEFAULT_RULES)
        grouped = self.app.bundle_client_reminders_by_window(filtered, window_days=1)

        self.assertNotIn("Alpha", " ".join(grouped["Animal Name"].astype(str)))
        self.assertIn("Bravo", " ".join(grouped["Animal Name"].astype(str)))

    def test_automatic_patient_exclusions_apply_like_patient_exclusions(self):
        due_df = self.make_due_df()
        self.app.st.session_state["client_exclusions"] = []
        self.app.st.session_state["patient_exclusions"] = []
        self.app.st.session_state["client_item_exclusions"] = []
        self.app.st.session_state["automatic_patient_exclusions"] = [
            {"client": "Same Client", "patient": "Bravo"}
        ]
        self.app.st.session_state["exclusions"] = []

        filtered = self.app.apply_reminder_exclusion_filters(due_df, self.app.DEFAULT_RULES)

        self.assertNotIn("Bravo", " ".join(filtered["Animal Name"].astype(str)))
        self.assertIn("Alpha", " ".join(filtered["Animal Name"].astype(str)))

    def test_client_item_exclusions_only_hide_matching_item_for_that_client(self):
        due_df = pd.DataFrame(
            {
                "Client Name": ["Client A", "Client A", "Client B"],
                "Animal Name": ["Alpha", "Alpha", "Bravo"],
                "Item Name": ["Dental Descale", "Rabies Vaccine", "Dental Descale"],
                "ReminderDate": pd.to_datetime(["2026-05-01", "2026-05-01", "2026-05-01"]),
            }
        )
        self.app.st.session_state["client_exclusions"] = []
        self.app.st.session_state["patient_exclusions"] = []
        self.app.st.session_state["client_item_exclusions"] = [
            {"client": "Client A", "item": "dental"}
        ]
        self.app.st.session_state["automatic_patient_exclusions"] = []
        self.app.st.session_state["exclusions"] = []

        filtered = self.app.apply_reminder_exclusion_filters(due_df, self.app.DEFAULT_RULES)

        remaining = set(zip(filtered["Client Name"], filtered["Item Name"]))
        self.assertNotIn(("Client A", "Dental Descale"), remaining)
        self.assertIn(("Client A", "Rabies Vaccine"), remaining)
        self.assertIn(("Client B", "Dental Descale"), remaining)

    def test_passaway_keywords_create_automatic_patient_exclusions_from_upload(self):
        state = self.app.st.session_state
        state["patient_passaway_keywords"] = ["euthanasia", "pentobarb"]
        state["automatic_patient_exclusions"] = [
            {"client": "Existing Client", "patient": "Existing Pet"}
        ]
        upload_df = pd.DataFrame(
            {
                "Client Name": ["Client A", "Client B", "Client A", "Client C"],
                "Animal Name": ["Pet A", "Pet B", "Pet A", "Pet C"],
                "Item Name": ["Euthanasia consult", "Rabies", "Pentobarb injection", "Dental"],
            }
        )

        added = self.app.add_automatic_patient_exclusions_from_upload(upload_df)

        self.assertEqual(added, 1)
        self.assertIn(
            {"client": "Client A", "patient": "Pet A"},
            state["automatic_patient_exclusions"],
        )
        self.assertIn(
            {"client": "Existing Client", "patient": "Existing Pet"},
            state["automatic_patient_exclusions"],
        )

    def test_overdue_reminder_adds_extra_reminder_without_changing_due_date(self):
        df = pd.DataFrame(
            {
                "ChargeDate": pd.to_datetime(["2025-01-01"]),
                "Client Name": ["A Client"],
                "Animal Name": ["A Patient"],
                "Item Name": ["Overdue Item"],
                "Qty": [1],
                "Amount": [100],
            }
        )
        rules = {
            "overdue item": {
                "days": 90,
                "overdue_reminder": 100,
                "use_qty": False,
                "visible_text": "Overdue Item",
            }
        }

        prepared = self.app.ensure_reminder_columns(df, rules)
        expanded = self.app.expand_reminder_dates(prepared)

        self.assertEqual(sorted(expanded["ReminderDays"].astype(int)), [90, 100])
        self.assertEqual(set(expanded["DueDateFmt"]), {"01 Apr 2025"})
        self.assertEqual(set(expanded["ReminderDateFmt"]), {"01 Apr 2025", "11 Apr 2025"})

    def test_interval_mapping_handles_non_contiguous_filtered_index(self):
        df = pd.DataFrame(
            {
                "ChargeDate": pd.to_datetime(["2025-01-01", "2025-01-02"]),
                "Client Name": ["A Client", "B Client"],
                "Animal Name": ["A Patient", "B Patient"],
                "Item Name": ["Rabies Vaccine", "Dental Exam"],
                "Qty": [1, 1],
                "Amount": [100, 200],
            },
            index=[5, 9],
        )
        rules = {
            "rabies": {
                "days": 365,
                "use_qty": False,
                "visible_text": "Rabies Vaccine",
            }
        }

        mapped = self.app.map_intervals_vec(df, rules)

        self.assertEqual(mapped.at[5, "MatchedItems"], ["Rabies Vaccine"])
        self.assertEqual(mapped.at[5, "MatchedSearchTerms"], ["rabies"])
        self.assertEqual(int(mapped.at[5, "IntervalDays"]), 365)
        self.assertTrue(pd.isna(mapped.at[9, "IntervalDays"]))

    def test_loading_clinic_without_dataset_clears_stale_session_data(self):
        dataset_file_id_col = self.app.SHEET_COL_DATASET_FILE_ID
        dataset_file_name_col = self.app.SHEET_COL_DATASET_FILE_NAME

        class FakeSheet:
            def get_all_records(self):
                return [
                    {
                        "ClinicID": "Fresh Clinic",
                        dataset_file_id_col: "",
                        dataset_file_name_col: "",
                    }
                ]

        stale_keys = [
            "working_df",
            "prepared_df",
            "bundle",
            "bundle_key",
            "prepared_key",
            "shared_dataset_loaded",
            "shared_dataset_name",
            "shared_dataset_error",
        ]
        self.app.st.session_state["clinic_id"] = "Fresh Clinic"
        self.app.st.session_state["logged_in"] = True
        self.app.st.session_state["working_df"] = pd.DataFrame({"old": [1]})
        self.app.st.session_state["prepared_df"] = pd.DataFrame({"old": [1]})
        self.app.st.session_state["shared_dataset_loaded"] = True
        self.app.st.session_state["shared_dataset_name"] = "old_clinic.csv"

        with patch.object(self.app, "get_settings_sheet", return_value=FakeSheet()):
            self.app.load_shared_dataset_for_clinic()

        for key in stale_keys:
            self.assertNotIn(key, self.app.st.session_state)

    def test_clear_account_session_state_clears_critical_clinic_state(self):
        state = self.app.st.session_state
        previous_uploader_version = state.get("file_uploader_reset_version", 0)
        seeded_keys = {
            "logged_in": True,
            "clinic_id": "Old Clinic",
            "working_df": pd.DataFrame({"old": [1]}),
            "rules": {"old rule": {"days": 30}},
            "dataset_upload_history": [{"file_name": "old.csv"}],
            "wa_reminder_log": [{"client": "Old"}],
            "deleted_reminders": [{"client": "Old"}],
            "last_uploaded_files": ["old.csv"],
            "last_saved_upload_key": "abc",
            "pending_overlap_upload_key": "abc",
            "_settings_row_cache": {"clinic_key": "old clinic"},
            "_remote_settings_cache": {"clinic_key": "old clinic", "settings": {}},
        }
        for key, value in seeded_keys.items():
            state[key] = value

        self.app.clear_account_session_state()

        self.assertFalse(state["logged_in"])
        self.assertFalse(state["show_create_account"])
        self.assertFalse(state["show_top_change_password"])
        self.assertGreater(state["file_uploader_reset_version"], previous_uploader_version)
        for key in seeded_keys:
            if key != "logged_in":
                self.assertNotIn(key, state)


if __name__ == "__main__":
    unittest.main()
