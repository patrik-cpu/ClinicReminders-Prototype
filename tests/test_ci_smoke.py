import unittest
from pathlib import Path


class CiSmokeTests(unittest.TestCase):
    def test_app_file_exists(self):
        self.assertTrue(Path('reminders_app_v3.py').exists())


if __name__ == '__main__':
    unittest.main()
