import unittest
import subprocess
import sys
from pathlib import Path


class StreamlitLoginRenderTests(unittest.TestCase):
    def test_app_renders_login_screen_without_uncaught_exception(self):
        repo_root = Path(__file__).resolve().parents[1]
        script = """
from pathlib import Path
from streamlit.testing.v1 import AppTest

app_path = Path("reminders_app_v3.py").resolve()
app = AppTest.from_file(str(app_path))
app.run(timeout=10)

exceptions = list(app.exception)
if exceptions:
    raise AssertionError(exceptions)

markdown_values = [element.value for element in app.markdown]
if "<div class='login-title'>Clinic Login</div>" not in markdown_values:
    raise AssertionError(markdown_values[:10])
if len(app.text_input) < 2:
    raise AssertionError(f"Expected at least 2 text inputs, found {len(app.text_input)}")
if len(app.button) < 2:
    raise AssertionError(f"Expected at least 2 buttons, found {len(app.button)}")
"""

        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=repo_root,
            text=True,
            capture_output=True,
            timeout=20,
        )

        self.assertEqual(
            result.returncode,
            0,
            result.stdout + result.stderr,
        )


if __name__ == "__main__":
    unittest.main()
