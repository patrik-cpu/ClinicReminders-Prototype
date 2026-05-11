import unittest
from pathlib import Path


class CiSmokeTests(unittest.TestCase):
    def test_app_file_exists(self):
        app_file = Path('reminders_app_v3.py')
        self.assertTrue(app_file.exists())

    def test_app_file_is_non_empty(self):
        app_file = Path('reminders_app_v3.py')
        self.assertGreater(app_file.stat().st_size, 0)


if __name__ == '__main__':
    unittest.main()
