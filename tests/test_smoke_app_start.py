import unittest


class SmokeAppStartTests(unittest.TestCase):
    def test_import_app_module(self):
        import reminders_app_v3 as app  # noqa: F401
        self.assertTrue(hasattr(app, "__name__"))


if __name__ == "__main__":
    unittest.main()
