# DEPENDENCY_AUDIT.md

## Executive summary

This repo has a small Python dependency list but no lockfile. The highest-priority supply-chain issue is `authlib==1.6.11`, which is currently pinned to a version with a published advisory. The second major issue is reproducibility: most dependencies are broad or unpinned, so a clean install on May 17, 2026 resolves to very new major versions such as `pandas==3.0.3` and `numpy==2.4.5` without an explicit migration plan.

No upgrades or removals were performed.

Top recommendations:

- Patch upgrade `authlib` from `1.6.11` to at least `1.6.12`.
- Add a lockfile or fully pinned requirements output after validating a clean install.
- Remove direct `chardet` if upload tests pass without it.
- Migrate off `oauth2client` if the hidden feedback helper is kept; otherwise delete the hidden feedback code and remove `oauth2client`.
- Keep `openpyxl` because Excel uploads need it through pandas.
- Leave `google-auth-oauthlib` installed because `gspread` requires it, even though app code does not import it directly.

## Scope and commands

Inspected:

- `requirements.txt`
- Python imports across `*.py`
- lockfile/project metadata presence
- current local environment
- dry-run dependency resolution from `requirements.txt`
- OSV vulnerability data for the resolved PyPI packages
- PyPI metadata for direct dependencies

Commands used:

```bash
sed -n '1,120p' requirements.txt
find . -maxdepth 3 -type f \( -name '*lock*' -o -name 'pyproject.toml' -o -name 'setup.py' -o -name 'setup.cfg' -o -name 'Pipfile*' -o -name 'poetry.lock' -o -name 'uv.lock' \) -print | sort
python -m pip check
python -m pip freeze --all
python -m pip install --dry-run --ignore-installed --report /tmp/clinic_req_report.json -r requirements.txt
python -m pip_audit --version
```

Notes:

- `python -m pip check` passed in the current local environment.
- `pip-audit` is not installed in this environment, so I queried OSV directly instead of installing new tooling.
- No lockfile or package project file was found.
- The local environment does not exactly match `requirements.txt`; for example local has `streamlit==1.57.0`, `Authlib==1.7.2`, and `httpx==0.28.1`, while `requirements.txt` pins older versions.

Sources:

- OSV API query for `GHSA-r95x-qfjj-fjj2`: https://api.osv.dev/v1/vulns/GHSA-r95x-qfjj-fjj2
- GitHub advisory reference from OSV: https://github.com/authlib/authlib/security/advisories/GHSA-r95x-qfjj-fjj2
- PyPI JSON metadata, for example: https://pypi.org/pypi/authlib/json

## Direct dependency inventory

| Requirement | Dry-run resolved version | Current latest from PyPI | App usage | Recommendation |
| --- | ---: | ---: | --- | --- |
| `streamlit==1.56.0` | `1.56.0` | `1.57.0` | Main app framework; `st.login`, `st.cache_*`, UI | Minor upgrade after smoke test |
| `pandas>=1.5` | `3.0.3` | `3.0.3` | Core upload/data/reminder/statistics logic | Leave as-is short term; lock/pin after validation |
| `numpy` | `2.4.5` | `2.4.5` | Reminder/statistics numeric handling | Leave as-is short term; lock/pin after validation |
| `altair` | `6.1.0` | `6.1.0` | Statistics charts | Leave as-is |
| `openpyxl` | `3.1.5` | `3.1.5` | Indirect engine for `.xlsx` reads via `pd.read_excel` | Leave as-is |
| `gspread` | `6.2.1` | `6.2.1` | Google Sheets reads/writes | Leave as-is |
| `oauth2client` | `4.1.3` | `4.1.3` | Used only by hidden feedback sheet helper | Major migration requiring migration plan, or remove with feedback code |
| `chardet>=5.1.0` | `7.4.3` | `7.4.3` | No direct import found | Remove after clean upload tests |
| `google-api-python-client` | `2.196.0` | `2.196.0` | Google Drive API | Leave as-is |
| `google-auth` | `2.53.0` | `2.53.0` | Service account credentials for Drive | Leave as-is |
| `google-auth-httplib2` | `0.4.0` | `0.4.0` | Transitive requirement of Google API client | Leave as-is; optionally remove direct line once locked |
| `google-auth-oauthlib` | `1.4.0` | `1.4.0` | Not directly imported, but required by `gspread` | Leave as-is; optionally remove direct line once locked |
| `authlib==1.6.11` | `1.6.11` | `1.7.2` | Checked by `authlib_available`; supports Streamlit Google auth | Patch upgrade |
| `httpx==0.27.2` | `0.27.2` | `0.28.1` | No direct import; likely Streamlit/Authlib auth stack support | Minor upgrade only with Google login validation |

## Transitive resolution snapshot

A clean dry-run install on May 17, 2026 resolved 64 packages:

```text
streamlit==1.56.0
Authlib==1.6.11
httpx==0.27.2
pandas==3.0.3
numpy==2.4.5
altair==6.1.0
blinker==1.9.0
cachetools==7.1.2
click==8.4.0
GitPython==3.1.50
gitdb==4.0.12
httpcore==1.0.9
pillow==12.2.0
protobuf==7.34.1
pydeck==0.9.2
requests==2.34.2
charset-normalizer==3.4.7
idna==3.15
smmap==5.0.3
tenacity==9.1.4
toml==0.10.2
tornado==6.5.5
typing_extensions==4.15.0
urllib3==2.7.0
watchdog==6.0.0
openpyxl==3.1.5
gspread==6.2.1
oauth2client==4.1.3
chardet==7.4.3
google-api-python-client==2.196.0
google-auth==2.53.0
google-auth-httplib2==0.4.0
google-api-core==2.30.3
googleapis-common-protos==1.75.0
httplib2==0.31.2
proto-plus==1.28.0
pyparsing==3.3.2
uritemplate==4.2.0
google-auth-oauthlib==1.4.0
certifi==2026.4.22
cryptography==48.0.0
cffi==2.0.0
h11==0.16.0
Jinja2==3.1.6
jsonschema==4.26.0
attrs==26.1.0
jsonschema-specifications==2025.9.1
MarkupSafe==3.0.3
narwhals==2.21.2
packaging==26.2
pyarrow==24.0.0
pyasn1==0.6.3
pyasn1_modules==0.4.2
python-dateutil==2.9.0.post0
referencing==0.37.0
requests-oauthlib==2.0.0
oauthlib==3.3.1
rpds-py==0.30.0
rsa==4.9.1
six==1.17.0
anyio==4.13.0
et_xmlfile==2.0.0
pycparser==3.0
sniffio==1.3.1
```

## Vulnerability report

OSV result for the dry-run-resolved package set:

- `Authlib==1.6.11`
  - Advisory: `GHSA-r95x-qfjj-fjj2`
  - Alias: `CVE-2026-44681`
  - Summary: Authlib OIDC Implicit/Hybrid authorization open redirect.
  - Affected ranges include `<= 1.6.11` and `1.7.0`.
  - Fixed versions include `1.6.12` and `1.7.1`.
  - App-specific note: this app appears to use Authlib through Streamlit as an OIDC client, not as an Authlib OIDC provider registering implicit/hybrid grants. Direct exploitability is not proven here, but the dependency is auth-adjacent and pinned to an affected version.
  - Recommendation: patch upgrade to `authlib==1.6.12` first; consider minor upgrade to `1.7.2` only after Google login validation.

No other OSV advisories were returned for the 64-package dry-run resolution. This is not a substitute for a locked, repeatable `pip-audit` or equivalent CI step because the unpinned dependencies can resolve differently over time.

## Unused and questionable dependencies

### `chardet`

Evidence:

- Direct requirement: `chardet>=5.1.0`
- No direct app import found.
- `requests` resolves with `charset-normalizer`, not `chardet`.

Recommendation:

- Remove.

Validation plan:

```bash
python -m pip install --dry-run --ignore-installed -r requirements.txt
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

Also manually test CSV uploads with representative encodings if non-UTF-8 exports are expected.

### `oauth2client`

Evidence:

- Direct import: `from oauth2client.service_account import ServiceAccountCredentials` at `reminders_app_v3.py:11`.
- Used in the hidden feedback helper around `reminders_app_v3.py:10659`.
- Core Drive and settings paths already use newer Google auth libraries elsewhere.
- `oauth2client` latest is still `4.1.3`, indicating no newer maintained line to upgrade to.

Recommendation:

- Major upgrade requiring migration plan if feedback is kept: replace with `google.oauth2.service_account.Credentials` / modern gspread auth.
- Remove if hidden feedback integration is deleted.

Validation plan:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

Then manually validate feedback sheet behavior if it is still a product feature.

### `google-auth-oauthlib`

Evidence:

- No direct app import found.
- `gspread 6.2.1` declares `google-auth-oauthlib>=0.4.1`.

Recommendation:

- Leave as-is as an installed package.
- Optionally remove the direct line from `requirements.txt` after introducing a lockfile, because `gspread` will still bring it transitively.

Validation plan:

```bash
python -m pip install --dry-run --ignore-installed -r requirements.txt
python -m pip check
python -m unittest discover -s tests -p "test_ci_*.py"
```

### `google-auth-httplib2`

Evidence:

- No direct app import found.
- `google-api-python-client 2.196.0` declares `google-auth-httplib2`.

Recommendation:

- Leave as-is as an installed package.
- Optionally remove the direct line from `requirements.txt` after introducing a lockfile, because `google-api-python-client` will still bring it transitively.

## Duplicate or overlapping packages

### Google auth stack overlap

The app uses two credential approaches:

- Modern Drive path: `google.oauth2.service_account.Credentials`
- Feedback path: `oauth2client.service_account.ServiceAccountCredentials`

Recommendation:

- Major upgrade requiring migration plan: standardize on `google-auth` and remove `oauth2client` once feedback is migrated or deleted.

### Character encoding packages

Dry-run resolution includes both:

- `charset-normalizer` from `requests`
- direct `chardet`

Recommendation:

- Remove direct `chardet` if upload encoding tests pass.

## Packages used only once or for narrow functionality

- `openpyxl`: used indirectly by pandas for Excel uploads. Recommendation: leave as-is.
- `oauth2client`: narrow hidden feedback helper only. Recommendation: migrate/remove as above.
- `authlib` / `httpx`: auth support for Streamlit login. Recommendation: keep, but patch/minor upgrade carefully.
- `altair`: statistics charts. Recommendation: leave as-is.

## Outdated versions and upgrade recommendations

### Patch upgrade

- `authlib==1.6.11` -> `authlib==1.6.12`
  - Reason: fixes published advisory while staying on the same minor line.
  - Required validation: Google login flow, `authlib_available`, session creation, logout.

### Minor upgrade

- `streamlit==1.56.0` -> `streamlit==1.57.0`
  - Reason: local environment already has `1.57.0` and tests passed previously under it, but deployment should still validate UI/auth behavior.

- `httpx==0.27.2` -> `httpx==0.28.1`
  - Reason: newer minor available, no direct app import.
  - Required validation: Google login via Streamlit/Authlib.

### Major upgrade requiring migration

- `oauth2client` -> modern `google-auth`
  - Reason: old compatibility library, used only in hidden feedback integration.

### Leave as-is, but lock

- `pandas`, `numpy`, `altair`, `gspread`, Google client libraries
  - Reason: broad/unpinned specs resolve to current latest majors. Do not upgrade blindly; lock after a clean install passes tests and upload/login smoke checks.

## Lockfile consistency

No lockfile was found:

- no `requirements.lock`
- no `pyproject.toml`
- no `poetry.lock`
- no `uv.lock`
- no `Pipfile.lock`

Risk:

- CI and deployment can change without code changes because many requirements are unpinned.
- A clean dry-run currently resolves `pandas==3.0.3`, `numpy==2.4.5`, `protobuf==7.34.1`, and other major versions.
- The current local environment differs from declared pins, which can hide dependency problems.

Recommendation:

- Add a lockfile or generated fully pinned constraints file after validation.
- Category: patch-level process fix.

Suggested validation:

```bash
python -m pip install --dry-run --ignore-installed -r requirements.txt
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
```

Then perform manual smoke checks for:

- password login
- Google login
- CSV upload
- XLSX upload
- Drive save/load
- settings save/load

## Risky postinstall scripts

No npm/yarn/pnpm package manager files were found, and this is not a client-bundled JavaScript app.

For Python packages:

- The dry-run selected wheels for the main packages where metadata was available.
- Python wheels do not expose npm-style postinstall scripts.
- I did not unpack every wheel/sdist, so this is not a full package-forensics review.

Recommendation:

- Leave as-is.
- Add hash-locked installs if supply-chain integrity becomes a deployment requirement.

## Client-side exposure

No server-only Python packages are bundled to the browser as packages. Streamlit runs Python server-side. The app does embed small HTML/JS snippets through `components.html`, but those are app code, not package bundles.

Recommendation:

- Leave as-is from a dependency exposure perspective.
- Continue security review of `unsafe_allow_html` and embedded JS separately.

## License concerns

Detected metadata from PyPI is mostly permissive:

- BSD-style: pandas, altair, authlib, httpx
- MIT-style: openpyxl, gspread
- Apache-2.0-style: oauth2client, Google libraries

Notes:

- `streamlit`, `numpy`, and `chardet` did not expose a concise OSI classifier in the queried PyPI metadata output. They may still have license files in distributions, but this audit did not unpack wheels to verify.
- Since `chardet` is unused, the lowest-risk license action is to remove it rather than review it deeply.

Recommendation:

- Leave as-is for used packages.
- Remove `chardet` if upload validation passes without it.
- If formal compliance is needed, add a license scanner step.

## Recommended sequence

1. Patch upgrade: `authlib==1.6.12`, with Google login validation.
2. Remove: `chardet`, with CSV upload encoding smoke tests.
3. Patch process fix: create a lockfile or constraints file from a known-good clean install.
4. Major migration: replace `oauth2client` in the hidden feedback helper or delete the hidden feedback integration.
5. Minor upgrades: evaluate `streamlit==1.57.0` and `httpx==0.28.1` together with auth smoke tests.

## Baseline validation commands

For dependency changes:

```bash
python -m py_compile reminders_app_v3.py
python -m unittest discover -s tests -p "test_ci_*.py"
python -m pip check
```

For vulnerability checking after adding tooling:

```bash
python -m pip_audit -r requirements.txt
```
