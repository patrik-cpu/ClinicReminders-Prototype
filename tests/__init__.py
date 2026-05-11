"""CI test package configuration.

Limit CI discovery to lightweight smoke tests so CI remains stable while
legacy/integration tests are migrated.
"""


def load_tests(loader, tests, pattern):
    return loader.discover(start_dir="tests", pattern="test_ci_*.py")
