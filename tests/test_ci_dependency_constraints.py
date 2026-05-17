import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def requirement_name(line: str) -> str:
    line = line.strip()
    if not line or line.startswith("#") or line.startswith("-"):
        return ""
    return re.split(r"\s*(?:==|>=|<=|~=|!=|>|<|;|\[)", line, maxsplit=1)[0].strip().lower()


class DependencyConstraintTests(unittest.TestCase):
    def test_requirements_use_constraints_file(self):
        requirements = (REPO_ROOT / "requirements.txt").read_text().splitlines()

        self.assertIn("--constraint requirements-constraints.txt", requirements)

    def test_direct_requirements_are_present_in_constraints(self):
        requirements = (REPO_ROOT / "requirements.txt").read_text().splitlines()
        constraints = (REPO_ROOT / "requirements-constraints.txt").read_text().splitlines()
        constrained_names = {
            line.split("==", 1)[0].strip().lower()
            for line in constraints
            if "==" in line and not line.strip().startswith("#")
        }
        direct_names = {
            name
            for name in (requirement_name(line) for line in requirements)
            if name
        }

        self.assertTrue(direct_names)
        self.assertFalse(direct_names - constrained_names)


if __name__ == "__main__":
    unittest.main()
