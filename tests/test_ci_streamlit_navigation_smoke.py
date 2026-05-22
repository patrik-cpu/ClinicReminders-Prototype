import os
import subprocess
import sys
import unittest
from pathlib import Path


class StreamlitNavigationSmokeTests(unittest.TestCase):
    def test_authenticated_main_tabs_render_without_uncaught_exception(self):
        repo_root = Path(__file__).resolve().parents[1]
        script = """
import os
from pathlib import Path
from streamlit.testing.v1 import AppTest

os.environ["CLINIC_REMINDERS_E2E_SEARCH_TERMS_LAYOUT"] = "1"

app = AppTest.from_file(str(Path("reminders_app_v3.py").resolve()))
app.run(timeout=10)

tab_button_keys = [
    "main_section_nav_reminders",
    "main_section_nav_search_terms",
    "main_section_nav_exclusions",
    "main_section_nav_identify",
    "main_section_nav_stats",
    "main_section_nav_upload_data",
    "main_section_nav_get_started",
]

for key in tab_button_keys:
    app.button(key=key).click().run(timeout=10)
    exceptions = list(app.exception)
    if exceptions:
        raise AssertionError(f"{key} raised Streamlit exception(s): {exceptions}")
"""

        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=repo_root,
            text=True,
            capture_output=True,
            timeout=45,
        )

        self.assertEqual(
            result.returncode,
            0,
            result.stdout + result.stderr,
        )


if __name__ == "__main__":
    unittest.main()
