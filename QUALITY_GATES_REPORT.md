# QUALITY_GATES_REPORT.md

## Executive summary

The repository currently has a minimal CI gate and one local script. The dependable gates today are:

- Python compile check for `reminders_app_v3.py`
- CI-pattern unit tests: `python -m unittest discover -s tests -p "test_ci_*.py"`
- Local `pip check`, which passes but is not wired into CI

The repo is not ready to fail CI on formatting, linting, mypy, Bandit, dependency audit, or secret scanning without a cleanup/configuration pass. Several tools are installed in this Codespace, but there is no repo-owned config and the raw checks fail with existing findings.

Lowest-risk first implementation:

- Add `python -m pip check` to CI after dependency install.
- Compile both source files in CI: `reminders_app_v3.py` and `settings_pointer_utils.py`.
- Update `scripts/pre_merge_check.sh` so the local script mirrors the CI/AGENTS checks and keeps the pointer-helper tests it already ran.

No formatter, linter, typechecker, security scanner, dependency audit tool, or secret scanner should be made blocking in this pass.

## Existing CI and scripts

### `.github/workflows/ci.yml`

Current steps:

- Checkout
- Set up Python 3.11
- `python -m pip install --upgrade pip`
- `pip install -r requirements.txt`
- `python -m py_compile reminders_app_v3.py`
- `python -m unittest discover -s tests -p "test_ci_*.py"`

Current status when run locally:

- `python -m py_compile reminders_app_v3.py`: passed.
- `python -m unittest discover -s tests -p "test_ci_*.py"`: passed, 84 tests. Existing `datetime.utcnow()` deprecation warnings were emitted.

Gap:

- CI does not compile `settings_pointer_utils.py`.
- CI does not run `python -m pip check`.
- CI does not run the non-CI pointer helper tests.

### `scripts/pre_merge_check.sh`

Current script:

```bash
python -m py_compile reminders_app_v3.py settings_pointer_utils.py
python -m unittest tests.test_settings_pointer_helpers tests.test_reminders_pointer_wrapper
```

Current status:

- Passed locally.
- It runs only 3 pointer-helper tests and does not run the required CI test discovery pattern from `AGENTS.md`.
- It emits noisy Streamlit bare-mode warnings because the pointer tests import the app directly.

Gap:

- Local script does not mirror CI or `AGENTS.md`.

## Gate inventory

### Format

Exists in repo:

- No.

Available locally:

- `black` is installed at `/usr/local/py-utils/bin/black`.

Check result:

- `black --check --quiet reminders_app_v3.py settings_pointer_utils.py tests` exited non-zero.

Assessment:

- Missing as a repo gate.
- Do not make blocking yet. The current code is not Black-formatted, and applying Black to the 11k-line app would create a large formatting-only diff.

Minimal future proposal:

- Add `pyproject.toml` with Black config.
- Run Black in one formatting-only PR.
- Then add CI:

```bash
black --check reminders_app_v3.py settings_pointer_utils.py tests
```

Recommendation:

- Leave missing for now.

### Lint

Exists in repo:

- No.

Available locally:

- `flake8` is installed at `/usr/local/py-utils/bin/flake8`.
- `ruff` is not installed.

Check result:

- `flake8 --count --statistics reminders_app_v3.py settings_pointer_utils.py tests` failed with 2,126 findings.
- Major categories included long lines, spacing, blank-line style, import placement, and multiple imports on one line.

Assessment:

- Missing as a repo gate.
- Do not make blocking yet. A raw Flake8 gate would fail immediately and create noise unrelated to behavior.

Minimal future proposal:

- Prefer Ruff because it can start with a narrow rule set and grow gradually.
- First lint gate should be syntax/bug-oriented only, not style-wide:

```bash
ruff check --select E9,F63,F7,F82 reminders_app_v3.py settings_pointer_utils.py tests
```

Recommendation:

- Leave missing until Ruff is added and configured in a separate PR.

### Typecheck

Exists in repo:

- No.

Available locally:

- `mypy` is installed at `/usr/local/py-utils/bin/mypy`.
- `pyright` is not installed.

Check result:

- `mypy reminders_app_v3.py settings_pointer_utils.py tests` failed with 52 errors.
- Early blockers include missing stubs for pandas/requests/Google libraries, Streamlit API typing mismatches, unannotated globals, and real typing friction in the large app module.

Assessment:

- Missing as a repo gate.
- Do not make blocking yet.

Minimal future proposal:

- Add `mypy.ini` with permissive initial config.
- Start by typechecking only small extracted pure modules after architecture refactors begin.
- Later add:

```bash
mypy clinic_app tests
```

Recommendation:

- Leave missing for now.

### Unit tests

Exists in repo:

- Yes.

CI command:

```bash
python -m unittest discover -s tests -p "test_ci_*.py"
```

Current status:

- Passed locally: 84 tests.

Coverage:

- Auth/session helpers
- Account create/update/delete characterization
- Dataset merge/update helpers
- Error-handling redaction
- Reminder grouping and badge behavior
- Settings save/action tracker behavior
- Statistics helpers
- Smoke check that the app file exists

Gaps:

- No coverage tool.
- Non-CI tests are not included in CI.

Recommendation:

- Keep as blocking.
- Align local script with this command.

### Integration tests

Exists in repo:

- Partial/local fakes only.

Evidence:

- Tests patch/fake Google Sheets and Drive helpers in several `test_ci_*.py` files.
- No real or containerized Google Sheets/Drive integration environment exists.

Assessment:

- No dedicated integration-test command.

Minimal future proposal:

- Keep Google APIs mocked.
- Add a dedicated marker/pattern later, for example:

```bash
python -m unittest discover -s tests -p "test_integration_*.py"
```

Recommendation:

- Do not add yet. Existing fake-backed tests are already in the unit suite.

### End-to-end or smoke tests

Exists in repo:

- Minimal smoke tests only.

Evidence:

- `tests/test_ci_smoke.py` checks that `reminders_app_v3.py` exists and is non-empty.

Assessment:

- No real Streamlit launch/browser smoke test.
- `streamlit` command was not found on PATH in this Codespace, even though the module imports during tests.

Minimal future proposal:

- Add a Streamlit import/startup smoke test only after deciding how to run Streamlit in CI.
- A first non-browser smoke gate could be:

```bash
python -m py_compile reminders_app_v3.py settings_pointer_utils.py
```

Recommendation:

- Treat compile as current smoke gate.

### Production build

Exists in repo:

- Not applicable.

Assessment:

- This is a Streamlit app with no package build, frontend bundle, Dockerfile, or deployment manifest in the repo.

Minimal future proposal:

- If deployment is containerized later, add a Docker build or deployment config validation.

Recommendation:

- Leave absent.

### Dependency audit

Exists in repo:

- No.

Available locally:

- `pip-audit` is not installed.
- `safety` is not installed.

Related check:

- `python -m pip check` passed locally.
- `DEPENDENCY_AUDIT.md` already documents OSV findings and recommends upgrading `authlib`.

Assessment:

- No vulnerability audit gate exists.
- `pip check` is not a vulnerability audit, but it is a low-risk dependency consistency gate.

Minimal future proposal:

- Add `pip-audit` in a separate tooling PR with an initial allowlist/ignore plan if needed.
- Later CI step:

```bash
python -m pip_audit -r requirements.txt
```

Recommendation:

- Add `python -m pip check` now.
- Do not add vulnerability audit yet.

### Static security scan

Exists in repo:

- No.

Available locally:

- `bandit` is installed at `/usr/local/py-utils/bin/bandit`.

Check result:

- `bandit -q -r reminders_app_v3.py settings_pointer_utils.py tests` failed with 16 findings.
- Findings include MD5 usage, `try/except/pass`, hardcoded password-column names false positives, and non-crypto random jitter.

Assessment:

- Do not make Bandit blocking yet.
- Several findings need triage and targeted suppressions or fixes.

Minimal future proposal:

- Add `bandit.yaml` after triage.
- Start with high-confidence/high-severity findings only after MD5 cache fingerprints and legacy password compatibility are addressed or suppressed.

Recommendation:

- Leave missing for now.

### Secret scanning

Exists in repo:

- No.

Available locally:

- `gitleaks`: missing.
- `detect-secrets`: missing.
- `trufflehog`: missing.
- `pre-commit`: missing.

Assessment:

- No secret scanning gate is available in this environment or wired in CI.

Minimal future proposal:

- Prefer GitHub secret scanning if available in the repository settings.
- Otherwise add Gitleaks in CI in a separate PR:

```bash
gitleaks detect --source . --no-git --redact
```

Recommendation:

- Leave missing for now.

## Implement now

Lowest-risk changes:

1. Add dependency consistency check to CI:

```bash
python -m pip check
```

2. Compile both source files in CI:

```bash
python -m py_compile reminders_app_v3.py settings_pointer_utils.py
```

3. Update `scripts/pre_merge_check.sh` to run:

```bash
python -m py_compile reminders_app_v3.py settings_pointer_utils.py
python -m pip check
python -m unittest discover -s tests -p "test_ci_*.py"
python -m unittest tests.test_settings_pointer_helpers tests.test_reminders_pointer_wrapper
```

Why these first:

- They require no new dependencies.
- They already pass locally.
- They align local checks with `AGENTS.md` and CI.
- They avoid broad formatting/lint/type/security cleanup.

## Implemented in this pass

Implemented:

- CI now runs `python -m pip check` after installing dependencies.
- CI now compiles both `reminders_app_v3.py` and `settings_pointer_utils.py`.
- `scripts/pre_merge_check.sh` now runs dependency consistency, CI-discovered unit tests, and the existing pointer-helper tests.

Validation after implementation:

```bash
python -m py_compile reminders_app_v3.py settings_pointer_utils.py
python -m pip check
python -m unittest discover -s tests -p "test_ci_*.py"
bash scripts/pre_merge_check.sh
```

Results:

- Compile passed.
- `pip check` passed with "No broken requirements found."
- CI-discovered unit tests passed: 84 tests.
- Local pre-merge script passed.
- Existing `datetime.utcnow()` deprecation warnings and Streamlit bare-mode warnings still appear; they are not new failures.

## Defer

- Formatting gate until a formatting-only PR.
- Lint gate until a narrow Ruff config is added.
- Typecheck until pure modules exist or permissive config is introduced.
- Dependency vulnerability audit until `pip-audit` is added and `authlib` advisory is addressed.
- Bandit/static security scan until findings are triaged.
- Secret scanning until a scanner is installed or GitHub secret scanning is confirmed.
