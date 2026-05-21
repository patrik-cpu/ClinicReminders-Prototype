import os
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class PilotReleaseScriptTests(unittest.TestCase):
    def test_pilot_release_check_script_exists_and_is_executable(self):
        script = REPO_ROOT / "scripts" / "pilot_release_check.sh"

        self.assertTrue(script.exists())
        self.assertTrue(os.access(script, os.X_OK))

    def test_pilot_release_check_mentions_live_google_smoke_and_auth_audit(self):
        script = REPO_ROOT / "scripts" / "pilot_release_check.sh"
        content = script.read_text()

        self.assertIn("live_google_smoke_check.py", content)
        self.assertIn("auth_legacy_audit.py", content)
        self.assertIn("--fail-on-risk", content)
        self.assertIn("PILOT_TEST_CLINIC_ID", content)

    def test_dependency_security_audit_command_is_repo_owned(self):
        script = REPO_ROOT / "scripts" / "dependency_security_audit.sh"
        content = script.read_text()
        dev_requirements = (REPO_ROOT / "requirements-dev.txt").read_text()
        pilot_content = (REPO_ROOT / "scripts" / "pilot_release_check.sh").read_text()

        self.assertTrue(script.exists())
        self.assertTrue(os.access(script, os.X_OK))
        self.assertIn("python -m pip_audit -r requirements.txt", content)
        self.assertIn("pip-audit", dev_requirements)
        self.assertIn("dependency_security_audit.sh", pilot_content)


if __name__ == "__main__":
    unittest.main()
