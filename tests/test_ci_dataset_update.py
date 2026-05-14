import contextlib
import importlib
import io
import unittest

import pandas as pd


class DatasetUpdateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            cls.app = importlib.import_module("reminders_app_v3")

    def test_replace_overlapping_upload_date_range(self):
        existing = pd.DataFrame(
            {
                "ChargeDate": pd.to_datetime(["2025-01-15", "2025-02-10", "2025-03-05"]),
                "Client Name": ["Jan", "Old Feb", "Mar"],
                "Animal Name": ["A", "B", "C"],
                "Item Name": ["Consult", "Old vaccine", "Consult"],
                "Qty": [1, 1, 1],
                "Amount": [10, 20, 30],
            }
        )
        new = pd.DataFrame(
            {
                "ChargeDate": pd.to_datetime(["2025-02-01", "2025-02-28"]),
                "Client Name": ["New Feb 1", "New Feb 2"],
                "Animal Name": ["D", "E"],
                "Item Name": ["Vaccine", "Consult"],
                "Qty": [1, 1],
                "Amount": [40, 50],
            }
        )

        merged = self.app.merge_dataset_update(existing, new, replace_overlapping_dates=True)

        self.assertEqual(
            list(merged["Client Name"]),
            ["Jan", "New Feb 1", "New Feb 2", "Mar"],
        )

    def test_append_non_overlapping_upload(self):
        existing = pd.DataFrame({"ChargeDate": pd.to_datetime(["2025-01-15"]), "Client Name": ["Jan"]})
        new = pd.DataFrame({"ChargeDate": pd.to_datetime(["2025-02-15"]), "Client Name": ["Feb"]})

        merged = self.app.merge_dataset_update(existing, new, replace_overlapping_dates=False)

        self.assertEqual(list(merged["Client Name"]), ["Jan", "Feb"])


if __name__ == "__main__":
    unittest.main()
