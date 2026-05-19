import pandas as pd
import altair as alt
import importlib.util
import unicodedata
import streamlit as st
import re
import json, os, time
import streamlit.components.v1 as components
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import date, datetime, timedelta, timezone
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from functools import lru_cache
import hashlib
import base64
import hmac
import uuid
from urllib.parse import urlparse
from typing import Iterable
import numpy as np
from gspread.exceptions import APIError
import random
import html as html_lib
import textwrap
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    from streamlit.runtime.scriptrunner import RerunException
    from streamlit.runtime.scriptrunner_utils.script_requests import RerunData
    from streamlit.runtime.scriptrunner import get_script_run_ctx
except Exception:
    RerunException = None
    RerunData = None
    get_script_run_ctx = None

def rerun_app():
    if hasattr(st, "experimental_rerun"):
        st.experimental_rerun()
    elif RerunException is not None and RerunData is not None:
        raise RerunException(RerunData())
    else:
        raise RuntimeError("This Streamlit environment does not support rerun.")

#Saving data set
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from google.oauth2.service_account import Credentials
from googleapiclient.errors import HttpError
from io import BytesIO
PREPARED_SCHEMA_VERSION = 5
SESSION_BUNDLE_SCHEMA_VERSION = 1
STATISTICS_GENERATED_SCHEMA_VERSION = 1
PRECOMPUTE_ANALYTICS_BUNDLE = False
UPLOAD_SUMMARY_SCHEMA_VERSION = 2
DEFAULT_REMINDER_LOOKBACK_DAYS = 2
DRIVE_SCOPE = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]

_SPACE_RX = re.compile(r"\s+")
_CURRENCY_RX = re.compile(r"[^\d.\-]")
MAIN_SECTION_TABS = ["Reminders", "Get Started", "Upload Data", "Search Terms", "Exclusions", "Stats"]
MAIN_SECTION_TAB_QUERY_PARAM = "section"
PENDING_MAIN_SECTION_TAB_KEY = "_pending_main_section_tab"
MAIN_SECTION_TAB_SLUGS = {
    "reminders": "Reminders",
    "stats": "Stats",
    "outcomes": "Stats",
    "get-started": "Get Started",
    "upload-data": "Upload Data",
    "search-terms": "Search Terms",
    "exclusions": "Exclusions",
    "statistics": "Stats",
}
MAIN_SECTION_TAB_TO_SLUG = {
    "Reminders": "reminders",
    "Get Started": "get-started",
    "Upload Data": "upload-data",
    "Search Terms": "search-terms",
    "Exclusions": "exclusions",
    "Stats": "stats",
}
REMINDERS_START_DATE_INPUT_KEY = "reminders_start_date_input"
OUTCOME_DUE_DATE_WINDOW_DIRTY_KEY = "_outcome_due_date_window_days_dirty"
OUTCOME_DUE_DATE_WINDOW_LOADED_KEY = "_outcome_due_date_window_days_loaded"


def canonical_main_section_tab(tab_name: str) -> str:
    legacy = {
        "Outcomes": "Stats",
        "Statistics": "Stats",
    }
    return legacy.get(str(tab_name or "").strip(), str(tab_name or "").strip())


def set_main_section_tab(tab_name: str):
    tab_name = canonical_main_section_tab(tab_name)
    if tab_name in MAIN_SECTION_TABS:
        try:
            st.session_state["main_section_tab"] = tab_name
        except st.errors.StreamlitAPIException:
            st.session_state[PENDING_MAIN_SECTION_TAB_KEY] = tab_name


def navigate_main_section_tab(tab_name: str):
    set_main_section_tab(tab_name)
    slug = MAIN_SECTION_TAB_TO_SLUG.get(tab_name)
    if slug:
        set_query_param(MAIN_SECTION_TAB_QUERY_PARAM, slug)


def consume_main_section_tab_query_param():
    pending_tab = st.session_state.pop(PENDING_MAIN_SECTION_TAB_KEY, "")
    pending_tab = canonical_main_section_tab(pending_tab)
    if pending_tab in MAIN_SECTION_TABS:
        set_main_section_tab(pending_tab)
    tab_slug = get_query_param_value(MAIN_SECTION_TAB_QUERY_PARAM).strip().lower()
    if not tab_slug:
        return
    tab_name = MAIN_SECTION_TAB_SLUGS.get(tab_slug)
    if tab_name:
        set_main_section_tab(tab_name)
    clear_query_param(MAIN_SECTION_TAB_QUERY_PARAM)


def get_query_param_value(key: str) -> str:
    value = st.query_params.get(key, "")
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return str(value or "")


def authlib_available() -> bool:
    return importlib.util.find_spec("authlib") is not None


def read_raw_config_entry(container, name: str, default=""):
    try:
        if hasattr(container, "get"):
            value = container.get(name, default)
        else:
            value = getattr(container, name, default)
    except Exception:
        value = default
    return value


def read_config_entry(container, name: str, default: str = "") -> str:
    value = read_raw_config_entry(container, name, default)
    return str(value or "").strip()


def config_value(name: str, default: str) -> str:
    env_value = os.environ.get(name)
    if str(env_value or "").strip():
        return str(env_value).strip()

    try:
        secret_value = read_config_entry(st.secrets, name)
        if secret_value:
            return secret_value

        google_resources = read_raw_config_entry(st.secrets, "google_resources", {})
        nested_value = read_config_entry(google_resources, name)
        if nested_value:
            return nested_value
    except Exception:
        pass

    return default


def suffixed_name(base_name: str, suffix: str) -> str:
    suffix = str(suffix or "").strip()
    return f"{base_name}{suffix}" if suffix else base_name


def default_worksheet_name_suffix() -> str:
    """Use live worksheet tabs automatically for the production Streamlit URL."""
    try:
        auth_config = read_raw_config_entry(st.secrets, "auth", {})
        redirect_uri = read_config_entry(auth_config, "redirect_uri")
    except Exception:
        redirect_uri = ""

    try:
        host = urlparse(redirect_uri).netloc.lower()
    except Exception:
        host = ""
    if host == "clinic-reminders.streamlit.app":
        return "-live"
    return ""

# --------------------------------
# Title (retention change))
# --------------------------------
title_col, tut_col = st.columns([5,1])
with title_col:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Nunito:wght@700;800&display=swap');
        div[data-testid="stHorizontalBlock"]:has(.cr-brand-card) {
            align-items: flex-start;
            background: #ffffff;
            border: 1px solid rgba(41, 210, 114, 0.10);
            border-radius: 16px;
            box-shadow: 0 12px 34px rgba(15, 23, 42, 0.045);
            margin-bottom: 0.45rem;
            padding: 0.95rem 1rem;
        }
        div[data-testid="stHorizontalBlock"]:has(.cr-brand-card) div[data-testid="stPopover"] {
            display: flex;
            justify-content: flex-end;
            padding-top: 0.25rem;
        }
        div[data-testid="stHorizontalBlock"]:has(.cr-brand-card) div[data-testid="stPopover"] button {
            background: #ffffff !important;
            border: 1px solid #d0d7e2 !important;
            border-radius: 8px !important;
            color: #101828 !important;
            min-width: 7.5rem;
            width: auto !important;
        }
        div[data-testid="stHorizontalBlock"]:has(.cr-brand-card) div[data-testid="stPopover"] button p {
            color: #101828 !important;
            font-weight: 700 !important;
            margin: 0 !important;
        }
        .cr-brand-card {
            background: transparent;
            border: 0;
            border-radius: 0;
            box-shadow: none;
            margin-bottom: 0.45rem;
            max-width: 560px;
            padding: 0;
        }
        .cr-brand-logo {
            align-items: center;
            column-gap: 0;
            display: grid;
            grid-template-columns: 168px 1fr;
            grid-template-rows: auto auto;
            position: relative;
        }
        .cr-brand-line {
            height: 118px;
            left: 0;
            pointer-events: none;
            position: absolute;
            top: 0;
            width: 100%;
            z-index: 0;
        }
        .cr-brand-pulse {
            grid-row: 1 / 3;
            grid-column: 1;
            height: 118px;
            opacity: 0;
            width: 168px;
        }
        .cr-brand-word {
            color: #10162f;
            font-family: "Nunito", "Avenir Next Rounded Std", "Arial Rounded MT Bold", "Trebuchet MS", Arial, sans-serif;
            letter-spacing: 0;
            line-height: 1;
            position: relative;
            transform: translate(15px, 9px);
            z-index: 1;
        }
        .cr-brand-word.clinic {
            align-self: end;
            font-size: 2.55rem;
            font-weight: 700;
            margin-bottom: 0.22rem;
        }
        .cr-brand-word.reminders {
            align-self: start;
            font-size: 3.25rem;
            font-weight: 800;
            margin-top: 0.28rem;
        }
        .cr-brand-subtitle {
            color: #5f6f67;
            font-size: 1.1rem;
            line-height: 1.45;
            margin: 0.4rem 0 0;
        }
        </style>
        <div class="cr-brand-card">
            <div class="cr-brand-logo" aria-label="Clinic Reminders">
                <svg class="cr-brand-line" viewBox="0 0 560 118" preserveAspectRatio="none" role="img" aria-hidden="true">
                    <path
                        d="M8 64 H72 L88 29 L106 96 L126 12 L140 108 L158 32 L174 64 H545"
                        fill="none"
                        stroke="#29D272"
                        stroke-width="7"
                        stroke-linecap="round"
                        stroke-linejoin="round"
                    />
                </svg>
                <svg class="cr-brand-pulse" viewBox="0 0 168 118" role="img" aria-hidden="true">
                    <path
                        d="M8 64 H72 L88 29 L106 96 L126 12 L140 108 L158 32 L168 64"
                        fill="none"
                        stroke="#29D272"
                        stroke-width="9"
                        stroke-linecap="round"
                        stroke-linejoin="round"
                    />
                </svg>
                <div class="cr-brand-word clinic">Clinic</div>
                <div class="cr-brand-word reminders">Reminders</div>
            </div>
        </div>
        <p class="cr-brand-subtitle">Turn sales data into clear follow-up reminders and prepare WhatsApp messages in a few clicks.</p>
        """,
        unsafe_allow_html=True,
    )
top_account_slot = tut_col.empty()

# === Drive folder where canonical datasets live ===
DEFAULT_DATASETS_FOLDER_ID = "1omuJfEmo_nuntr5uQBJhil_Q8ZNa2Lpr"  # from Drive folder URL
DATASETS_FOLDER_ID = config_value("DATASETS_FOLDER_ID", DEFAULT_DATASETS_FOLDER_ID)

# === Sheet columns you created ===
WORKSHEET_NAME_SUFFIX = config_value("WORKSHEET_NAME_SUFFIX", default_worksheet_name_suffix())
BASE_SETTINGS_WORKSHEET_NAME = "Clinic settings"
SETTINGS_WORKSHEET_NAME = suffixed_name(BASE_SETTINGS_WORKSHEET_NAME, WORKSHEET_NAME_SUFFIX)
LEGACY_SETTINGS_WORKSHEET_NAMES = ("Sheet1",)
SHEET_COL_CLINIC_ID = "ClinicID"
SHEET_COL_PLAIN_PASSWORD = "PlainPassword"
SHEET_COL_PASSWORD_HASH = "PasswordHash"
SHEET_COL_SETTINGS_JSON = "SettingsJSON"
SHEET_COL_UPDATED_AT = "UpdatedAt"
SHEET_COL_DATASET_FILE_ID = "DatasetFileId"
SHEET_COL_DATASET_FILE_NAME = "DatasetFileName"
SHEET_COL_DATASET_UPDATED_AT = "DatasetUpdatedAt"
SHEET_COL_AUTH_PROVIDER = "AuthProvider"
SHEET_COL_GOOGLE_EMAIL = "GoogleEmail"
SHEET_COL_GOOGLE_SUBJECT = "GoogleSubject"
SHEET_COL_GOOGLE_NAME = "GoogleName"
SHEET_COL_COUNTRY = "Country"
SHEET_COL_CREATED_AT_GST = "CreatedAtGST"
SHEET_COL_LAST_LOGIN_AT_GST = "LastLoginAtGST"
SHEET_COL_LAST_LOGIN_PROVIDER = "LastLoginProvider"
SHEET_COL_ACCOUNT_STATUS = "AccountStatus"
GOOGLE_AUTH_PROVIDER = "google"
SETTINGS_BASE_COLUMNS = [
    SHEET_COL_CLINIC_ID,
    SHEET_COL_PASSWORD_HASH,
    SHEET_COL_SETTINGS_JSON,
    SHEET_COL_UPDATED_AT,
]
DATASET_POINTER_COLUMNS = [
    SHEET_COL_DATASET_FILE_ID,
    SHEET_COL_DATASET_FILE_NAME,
    SHEET_COL_DATASET_UPDATED_AT,
]
GOOGLE_ACCOUNT_COLUMNS = [
    SHEET_COL_AUTH_PROVIDER,
    SHEET_COL_GOOGLE_EMAIL,
    SHEET_COL_GOOGLE_SUBJECT,
    SHEET_COL_GOOGLE_NAME,
]
ACCOUNT_METADATA_COLUMNS = [
    SHEET_COL_COUNTRY,
    SHEET_COL_CREATED_AT_GST,
    SHEET_COL_LAST_LOGIN_AT_GST,
    SHEET_COL_LAST_LOGIN_PROVIDER,
    SHEET_COL_ACCOUNT_STATUS,
]
SETTINGS_REQUIRED_COLUMNS = SETTINGS_BASE_COLUMNS + DATASET_POINTER_COLUMNS + GOOGLE_ACCOUNT_COLUMNS + ACCOUNT_METADATA_COLUMNS
DEFAULT_USER_TIMEZONE = "UTC"
GST_TZ = ZoneInfo("Asia/Dubai")
BASE_ACTION_TRACKER_WORKSHEET = "Action tracker"
WA_TRACKER_WORKSHEET = "WA button tracker"  # Legacy sheet name; kept for backwards compatibility.
BASE_USER_TRACKER_WORKSHEET = "User tracker"
BASE_DATASET_TRACKER_WORKSHEET = "Dataset tracker"
BASE_SETTINGS_AUDIT_WORKSHEET = "Settings audit"
BASE_ERROR_TRACKER_WORKSHEET = "Error tracker"
BASE_PERFORMANCE_TRACKER_WORKSHEET = "Performance tracker"
BASE_ACCOUNT_LIFECYCLE_WORKSHEET = "Account lifecycle"
ACTION_TRACKER_WORKSHEET = suffixed_name(BASE_ACTION_TRACKER_WORKSHEET, WORKSHEET_NAME_SUFFIX)
USER_TRACKER_WORKSHEET = suffixed_name(BASE_USER_TRACKER_WORKSHEET, WORKSHEET_NAME_SUFFIX)
DATASET_TRACKER_WORKSHEET = suffixed_name(BASE_DATASET_TRACKER_WORKSHEET, WORKSHEET_NAME_SUFFIX)
SETTINGS_AUDIT_WORKSHEET = suffixed_name(BASE_SETTINGS_AUDIT_WORKSHEET, WORKSHEET_NAME_SUFFIX)
ERROR_TRACKER_WORKSHEET = suffixed_name(BASE_ERROR_TRACKER_WORKSHEET, WORKSHEET_NAME_SUFFIX)
PERFORMANCE_TRACKER_WORKSHEET = suffixed_name(BASE_PERFORMANCE_TRACKER_WORKSHEET, WORKSHEET_NAME_SUFFIX)
ACCOUNT_LIFECYCLE_WORKSHEET = suffixed_name(BASE_ACCOUNT_LIFECYCLE_WORKSHEET, WORKSHEET_NAME_SUFFIX)
ACTION_TRACKER_HEADERS = [
    "DateTimeGST",
    "ActionedAtUTC",
    "ClinicID",
    "YourNameClinic",
    "Action",
    "ClientName",
    "AnimalNames",
    "Items",
    "ReminderDate",
    "DueDate",
    "ChargeDate",
    "Qty",
    "Days",
    "MessageCreated",
    "Source",
    "ReminderKey",
    "ReminderDetailsJSON",
]
WA_TRACKER_HEADERS = [
    "DateTimeGST",
    "ClinicID",
    "YourNameClinic",
    "ClientName",
    "AnimalNames",
    "Items",
    "DueDate",
    "ChargeDate",
    "MessageCreated",
    "Source",
]
USER_TRACKER_HEADERS = [
    "ClinicID",
    "Country",
    "CreatedAtGST",
    "LastUpdatedAtGST",
    "LastLoginAtGST",
    "AccountStatus",
    "LastEvent",
]
DATASET_TRACKER_HEADERS = [
    "DateTimeGST",
    "Event",
    "Status",
    "ClinicID",
    "YourNameClinic",
    "FileName",
    "PMS",
    "Rows",
    "FromDate",
    "ToDate",
    "ReplaceOverlappingDates",
    "DriveFileId",
    "DriveFileName",
    "Message",
    "Source",
    "OperationId",
]
SETTINGS_AUDIT_HEADERS = [
    "DateTimeGST",
    "ClinicID",
    "YourNameClinic",
    "Event",
    "Area",
    "Item",
    "Field",
    "OldValue",
    "NewValue",
    "Source",
]
ERROR_TRACKER_HEADERS = [
    "DateTimeGST",
    "ClinicID",
    "YourNameClinic",
    "Event",
    "Stage",
    "ErrorType",
    "Message",
    "Source",
]
PERFORMANCE_TRACKER_HEADERS = [
    "DateTimeGST",
    "ClinicID",
    "YourNameClinic",
    "Event",
    "DurationMs",
    "Rows",
    "Status",
    "Message",
    "Source",
]
ACCOUNT_LIFECYCLE_HEADERS = [
    "DateTimeGST",
    "Event",
    "Status",
    "ClinicRef",
    "ClinicName",
    "AuthProvider",
    "Country",
    "DeletedRows",
    "TrashedDataFile",
    "Message",
    "Source",
]
ACCOUNT_LIFECYCLE_AUTH_PROVIDERS = {"", "google", "password", "legacy", "manual"}
TRACKER_SHEET_DEFINITIONS = [
    (USER_TRACKER_WORKSHEET, USER_TRACKER_HEADERS),
    (ACTION_TRACKER_WORKSHEET, ACTION_TRACKER_HEADERS),
    (DATASET_TRACKER_WORKSHEET, DATASET_TRACKER_HEADERS),
    (SETTINGS_AUDIT_WORKSHEET, SETTINGS_AUDIT_HEADERS),
    (ERROR_TRACKER_WORKSHEET, ERROR_TRACKER_HEADERS),
    (PERFORMANCE_TRACKER_WORKSHEET, PERFORMANCE_TRACKER_HEADERS),
    (ACCOUNT_LIFECYCLE_WORKSHEET, ACCOUNT_LIFECYCLE_HEADERS),
]
TRACKER_CELL_TEXT_LIMIT = 500
PERFORMANCE_TRACKER_SLOW_LOAD_MS = 3000
COUNTRY_OPTIONS = [
    "United Arab Emirates", "Saudi Arabia", "Qatar", "Bahrain", "Kuwait", "Oman",
    "United Kingdom", "Ireland", "United States", "Canada", "Australia", "New Zealand",
    "South Africa", "India", "Pakistan", "Philippines", "Sri Lanka", "Nepal",
    "Afghanistan", "Albania", "Algeria", "Andorra", "Angola", "Argentina", "Armenia",
    "Austria", "Azerbaijan", "Bangladesh", "Belgium", "Brazil", "Bulgaria", "Chile",
    "China", "Colombia", "Croatia", "Cyprus", "Czechia", "Denmark", "Egypt", "Estonia",
    "Finland", "France", "Georgia", "Germany", "Ghana", "Greece", "Hong Kong", "Hungary",
    "Indonesia", "Iran", "Iraq", "Israel", "Italy", "Japan", "Jordan", "Kenya",
    "Lebanon", "Malaysia", "Malta", "Mexico", "Morocco", "Netherlands", "Nigeria",
    "Norway", "Poland", "Portugal", "Romania", "Russia", "Serbia", "Singapore",
    "South Korea", "Spain", "Sweden", "Switzerland", "Thailand", "Turkey", "Ukraine",
    "Vietnam", "Zimbabwe", "Other",
]

def reset_file_uploader_selection():
    """Force Streamlit's file uploader to remount without stale selected files."""
    uploader_keys = [
        key for key in list(st.session_state.keys())
        if str(key).startswith("file_uploader_main_")
    ]
    st.session_state["file_uploader_reset_version"] = st.session_state.get("file_uploader_reset_version", 0) + 1
    st.session_state["last_uploaded_files"] = []
    st.session_state.pop("last_saved_upload_key", None)
    st.session_state.pop("pending_overlap_upload_key", None)
    for key in uploader_keys:
        st.session_state.pop(key, None)


def reset_uploaded_data_state(clear_cache: bool = True, reset_uploader: bool = False):
    """Single reset helper used by upload/reset flows."""
    for key in [
        "working_df",
        "prepared_df",
        "bundle",
        "bundle_key",
        "prepared_key",
        "shared_dataset_loaded",
        "shared_dataset_name",
        "shared_dataset_updated_at",
        "shared_dataset_error",
    ]:
        st.session_state.pop(key, None)
    if reset_uploader:
        reset_file_uploader_selection()
    if clear_cache:
        st.cache_data.clear()


ACCOUNT_SCOPED_SESSION_KEYS = [
    "clinic_id",
    "rules",
    "applied_rules",
    "exclusions",
    "client_exclusions",
    "patient_exclusions",
    "automatic_patient_exclusions",
    "patient_passaway_keywords",
    "user_name",
    "user_template",
    "wa_template",
    "reminders_start_date",
    REMINDERS_START_DATE_INPUT_KEY,
    "_reminders_start_date_today_requested",
    "_reminders_start_date_key_seed",
    "client_group_days",
    "reminder_window_days",
    "reminder_lookback_days",
    "reminder_warning_days",
    "outcome_due_date_window_days",
    "wa_reminder_log",
    "deleted_reminders",
    "dataset_upload_history",
    "user_country",
    "auth_provider",
    "google_email",
    "google_subject",
    "get_started_reset_at",
    "search_terms_reviewed",
    "search_term_added",
    "search_term_added_at",
    "user_name_updated_at",
    "wa_template_reviewed",
    "wa_template_updated",
    "wa_template_updated_at",
    "action_tracker_migrated_at",
    "data_version",
    "last_saved_upload_key",
    "pending_overlap_upload_key",
    "_shared_dataset_load_attempted_for",
    "_row_count_repair_load_attempted_for",
    "last_uploaded_files",
    "confirm_reset_dataset",
    "show_clear_clinic_data_confirm",
    "form_version",
    "new_rule_counter",
    "search_criteria_changed",
    "_search_criteria_refreshed",
    "_search_terms_autosave_error",
    "_pending_recent_reminder_warning",
    "_replace_deleted_reminders_once",
    "_replace_wa_reminder_log_once",
    "_deleted_reminder_remove_keys_once",
    "_wa_reminder_remove_keys_once",
    "_replace_search_settings_once",
    "show_data_privacy_dialog",
    "show_profile_dialog",
    "show_delete_account_dialog",
    "show_new_account_welcome_dialog",
    "show_upload_sales_data_help_dialog",
    "delete_account_confirm_text",
    "_scroll_to_whatsapp_composer",
    "_settings_row_cache",
    "_remote_settings_cache",
    "_tracker_sheet_cache",
    "_hidden_reminders_index_cache",
    "pending_google_signup",
    "google_onboarding_mode",
    "google_signup_error",
    "google_onboarding_clinic_name",
    "google_onboarding_country",
    "llm_payload",
    "llm_zip_bytes",
    "llm_built_at",
]


def clear_account_session_state(reset_uploader: bool = True, preserve_keys: set[str] | None = None):
    """Clear clinic-specific session state when a user leaves an account."""
    preserve_keys = preserve_keys or set()
    reset_uploaded_data_state(clear_cache=False, reset_uploader=reset_uploader)
    for key in ACCOUNT_SCOPED_SESSION_KEYS:
        if key in preserve_keys:
            continue
        st.session_state.pop(key, None)
    st.session_state["logged_in"] = False
    st.session_state["show_create_account"] = False
    st.session_state["show_top_change_password"] = False


def drop_duplicate_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Drop duplicate columns after normalizing header text.
    Keeps the first occurrence.
    """
    if df is None:
        return df

    df = df.copy()

    def _norm_col(c):
        if not isinstance(c, str):
            c = str(c)
        c = unicodedata.normalize("NFKC", c).replace("\u00a0", " ").replace("\ufeff", "")
        c = _SPACE_RX.sub(" ", c).strip().lower()
        return c

    norm_cols = pd.Index([_norm_col(c) for c in df.columns])
    df = df.loc[:, ~norm_cols.duplicated()].copy()
    return df
    
def clear_clinic_dataset_pointer(clinic_id: str):
    clinic_id = require_authenticated_tenant_access(clinic_id)
    update_authorized_settings_row_fields(
        clinic_id,
        {
            SHEET_COL_DATASET_FILE_ID: "",
            SHEET_COL_DATASET_FILE_NAME: "",
            SHEET_COL_DATASET_UPDATED_AT: "",
        },
        SETTINGS_REQUIRED_COLUMNS,
    )
    update_cached_settings_row_fields(
        clinic_id,
        {
            SHEET_COL_DATASET_FILE_ID: "",
            SHEET_COL_DATASET_FILE_NAME: "",
            SHEET_COL_DATASET_UPDATED_AT: "",
        },
    )

def _settings_col_index(headers, name: str) -> int:
    return headers.index(name) + 1


def _column_number_to_letter(col_num: int) -> str:
    letters = ""
    while col_num > 0:
        col_num, remainder = divmod(col_num - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _row_range_a1(row_idx: int, first_col_idx: int, last_col_idx: int) -> str:
    return f"{_column_number_to_letter(first_col_idx)}{row_idx}:{_column_number_to_letter(last_col_idx)}{row_idx}"


def update_dataset_pointer_cells(
    *,
    sheet,
    headers,
    row_idx: int,
    file_id: str,
    filename: str,
    updated_at: str,
    dataset_file_id_col: str,
    dataset_updated_at_col: str,
    retry_fn,
):
    values = [[file_id, filename, updated_at]]
    rng = _row_range_a1(
        row_idx,
        _settings_col_index(headers, dataset_file_id_col),
        _settings_col_index(headers, dataset_updated_at_col),
    )
    retry_fn(
        sheet.batch_update,
        [{"range": rng, "values": values}],
        value_input_option="RAW",
    )


def settings_row_values(headers: list[str], values_by_header: dict[str, object]) -> list[str]:
    row_values = [""] * len(headers)
    for header, value in values_by_header.items():
        if header in headers:
            row_values[headers.index(header)] = value
    return row_values


def ensure_settings_sheet_columns(
    sheet=None,
    headers: list[str] | None = None,
    required_columns: list[str] | None = None,
) -> list[str]:
    sheet = sheet or get_settings_sheet()
    if headers is None:
        all_vals = _gspread_retry(sheet.get_all_values) or []
        headers = list(all_vals[0]) if all_vals else list(SETTINGS_REQUIRED_COLUMNS)
    else:
        headers = list(headers)

    missing = [col for col in (required_columns or []) if col not in headers]
    if not missing:
        return headers

    updated_headers = headers + missing
    end_col = _column_number_to_letter(len(updated_headers))
    _gspread_retry(sheet.update, values=[updated_headers], range_name=f"A1:{end_col}1")
    st.session_state.pop("_settings_row_cache", None)
    return updated_headers


def clear_legacy_plain_password_column(sheet=None, headers: list[str] | None = None) -> int:
    sheet = sheet or get_settings_sheet()
    values = _gspread_retry(sheet.get_all_values) or []
    if headers is None:
        headers = list(values[0]) if values else []
    else:
        headers = list(headers)

    if SHEET_COL_PLAIN_PASSWORD not in headers:
        return 0

    plain_password_idx = _settings_col_index(headers, SHEET_COL_PLAIN_PASSWORD)
    updates = []
    for row_idx, row in enumerate(values[1:], start=2):
        current = row[plain_password_idx - 1] if len(row) >= plain_password_idx else ""
        if str(current or "").strip():
            updates.append({
                "range": _row_range_a1(row_idx, plain_password_idx, plain_password_idx),
                "values": [[""]],
            })

    if updates:
        _gspread_retry(sheet.batch_update, updates)
        st.session_state.pop("_settings_row_cache", None)
    return len(updates)


def worksheet_values_have_settings_schema(values: list[list[str]] | None) -> bool:
    if not values:
        return False
    headers = list(values[0] or [])
    return SHEET_COL_CLINIC_ID in headers and SHEET_COL_SETTINGS_JSON in headers


def copy_worksheet_values(destination, values: list[list[str]]) -> None:
    values = values or [list(SETTINGS_REQUIRED_COLUMNS)]
    max_cols = max(len(SETTINGS_REQUIRED_COLUMNS), max((len(row) for row in values), default=0), 8)
    max_rows = max(len(values), 1000)
    padded_values = [list(row) + [""] * max(0, max_cols - len(row)) for row in values]
    try:
        _gspread_retry(destination.resize, rows=max_rows, cols=max_cols)
    except Exception:
        pass
    end_col = _column_number_to_letter(max_cols)
    _gspread_retry(destination.update, values=padded_values, range_name=f"A1:{end_col}{len(padded_values)}")


def get_or_create_settings_worksheet(spreadsheet):
    try:
        worksheet = spreadsheet.worksheet(SETTINGS_WORKSHEET_NAME)
    except Exception:
        worksheet = spreadsheet.add_worksheet(
            title=SETTINGS_WORKSHEET_NAME,
            rows=1000,
            cols=max(len(SETTINGS_REQUIRED_COLUMNS), 8),
        )

    values = _gspread_retry(worksheet.get_all_values) or []
    if not worksheet_values_have_settings_schema(values):
        legacy_values = []
        if not WORKSHEET_NAME_SUFFIX:
            for legacy_name in LEGACY_SETTINGS_WORKSHEET_NAMES:
                try:
                    legacy = spreadsheet.worksheet(legacy_name)
                    if legacy.title != SETTINGS_WORKSHEET_NAME:
                        legacy_values = _gspread_retry(legacy.get_all_values) or []
                except Exception:
                    legacy_values = []
                if worksheet_values_have_settings_schema(legacy_values):
                    break
            if not worksheet_values_have_settings_schema(legacy_values):
                try:
                    legacy = spreadsheet.sheet1
                    if legacy.title != SETTINGS_WORKSHEET_NAME:
                        legacy_values = _gspread_retry(legacy.get_all_values) or []
                except Exception:
                    legacy_values = []
        if worksheet_values_have_settings_schema(legacy_values):
            copy_worksheet_values(worksheet, legacy_values)
            values = legacy_values
        elif not values or WORKSHEET_NAME_SUFFIX:
            copy_worksheet_values(worksheet, [list(SETTINGS_REQUIRED_COLUMNS)])
            values = [list(SETTINGS_REQUIRED_COLUMNS)]

    headers = list(values[0]) if values else list(SETTINGS_REQUIRED_COLUMNS)
    ensure_settings_sheet_columns(worksheet, headers, SETTINGS_REQUIRED_COLUMNS)
    clear_legacy_plain_password_column(worksheet, headers)
    return worksheet


def user_timezone_name() -> str:
    try:
        browser_timezone = getattr(st.context, "timezone", None)
    except Exception:
        browser_timezone = None
    browser_timezone = str(browser_timezone or "").strip()
    return browser_timezone or DEFAULT_USER_TIMEZONE


def user_timezone() -> ZoneInfo:
    try:
        return ZoneInfo(user_timezone_name())
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_USER_TIMEZONE)


def utc_now(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc).replace(tzinfo=None)
    if now.tzinfo is None:
        return now
    return now.astimezone(timezone.utc).replace(tzinfo=None)


def user_now(now: datetime | None = None) -> datetime:
    utc_value = utc_now(now).replace(tzinfo=timezone.utc)
    return utc_value.astimezone(user_timezone()).replace(tzinfo=None)


def user_today(now: datetime | None = None) -> date:
    return user_now(now).date()


def user_now_iso(now: datetime | None = None) -> str:
    return user_now(now).strftime("%Y-%m-%d %H:%M:%S")


def utc_now_iso(now: datetime | None = None) -> str:
    return utc_now(now).isoformat()


def gst_now(now: datetime | None = None) -> datetime:
    return user_now(now)


def gst_now_iso(now: datetime | None = None) -> str:
    return user_now_iso(now)


def _update_dataset_pointer_cells(sheet, headers, row_idx, file_id, filename, updated_at):
    update_dataset_pointer_cells(
        sheet=sheet,
        headers=headers,
        row_idx=row_idx,
        file_id=file_id,
        filename=filename,
        updated_at=updated_at,
        dataset_file_id_col=SHEET_COL_DATASET_FILE_ID,
        dataset_updated_at_col=SHEET_COL_DATASET_UPDATED_AT,
        retry_fn=_gspread_retry,
    )


def _update_settings_cells(sheet, headers, row_idx, settings_json, updated_at):
    first_idx = _settings_col_index(headers, "SettingsJSON")
    last_idx = _settings_col_index(headers, "UpdatedAt")
    payload = [{
        "range": _row_range_a1(row_idx, first_idx, last_idx),
        "values": [[settings_json, updated_at]],
    }]
    _gspread_retry(sheet.batch_update, payload)


def _update_password_cells(sheet, headers, row_idx, plain_password, password_hash, updated_at):
    updates = []
    for col_name, value in (
        (SHEET_COL_PLAIN_PASSWORD, plain_password),
        (SHEET_COL_PASSWORD_HASH, password_hash),
        (SHEET_COL_UPDATED_AT, updated_at),
    ):
        if col_name in headers:
            col_idx = _settings_col_index(headers, col_name)
            updates.append({
                "range": _row_range_a1(row_idx, col_idx, col_idx),
                "values": [[value]],
            })
    if updates:
        _gspread_retry(sheet.batch_update, updates)


def _get_settings_row_for_clinic(clinic_id: str):
    clinic_key = normalize_clinic_id_key(clinic_id)
    cached = st.session_state.get("_settings_row_cache")
    if isinstance(cached, dict) and cached.get("clinic_key") == clinic_key:
        return get_settings_sheet(), list(cached.get("headers", [])), int(cached.get("row_idx"))

    sheet = get_settings_sheet()
    all_vals = _gspread_retry(sheet.get_all_values)
    headers = all_vals[0]
    clinic_col = _settings_col_index(headers, "ClinicID")
    row_idx = None
    for i, r in enumerate(all_vals[1:], start=2):
        if len(r) >= clinic_col and normalize_clinic_id_key(r[clinic_col - 1]) == clinic_key:
            row_idx = i
            break

    if row_idx is None:
        raise ValueError("ClinicID not found in settings sheet")
    st.session_state["_settings_row_cache"] = {
        "clinic_key": clinic_key,
        "headers": list(headers),
        "row_idx": row_idx,
        "row_values": list(all_vals[row_idx - 1]) if len(all_vals) >= row_idx else [],
    }
    return sheet, headers, row_idx


def get_cached_settings_row_values(clinic_id: str) -> list[str] | None:
    cached = st.session_state.get("_settings_row_cache")
    clinic_key = normalize_clinic_id_key(clinic_id)
    if isinstance(cached, dict) and cached.get("clinic_key") == clinic_key and "row_values" in cached:
        return list(cached.get("row_values") or [])
    return None


def update_cached_settings_row_fields(clinic_id: str, values_by_header: dict[str, str]) -> None:
    cached = st.session_state.get("_settings_row_cache")
    clinic_key = normalize_clinic_id_key(clinic_id)
    if not isinstance(cached, dict) or cached.get("clinic_key") != clinic_key:
        return
    headers = list(cached.get("headers") or [])
    row_values = list(cached.get("row_values") or [])
    if len(row_values) < len(headers):
        row_values.extend([""] * (len(headers) - len(row_values)))
    for header, value in values_by_header.items():
        if header in headers:
            row_values[headers.index(header)] = value
    cached["row_values"] = row_values


def _raw_update_settings_row_fields(
    clinic_id: str,
    values_by_header: dict[str, object],
    required_columns: list[str] | None = None,
) -> tuple[object, list[str], int]:
    sheet, headers, row_idx = _get_settings_row_for_clinic(clinic_id)
    headers = ensure_settings_sheet_columns(sheet, headers, required_columns or [])
    updates = []
    for header, value in values_by_header.items():
        if header in headers:
            col_idx = _settings_col_index(headers, header)
            updates.append({
                "range": _row_range_a1(row_idx, col_idx, col_idx),
                "values": [[value]],
            })
    if updates:
        _gspread_retry(sheet.batch_update, updates)
    st.session_state.pop("_settings_row_cache", None)
    return sheet, headers, row_idx


class SettingsRepository:
    def get_fresh_row_values(self, clinic_id: str) -> tuple[object, list[str], int, list[str]]:
        sheet, headers, row_idx = _get_settings_row_for_clinic(clinic_id)
        row_values = list(_gspread_retry(sheet.row_values, row_idx))
        clinic_key = normalize_clinic_id_key(clinic_id)
        st.session_state["_settings_row_cache"] = {
            "clinic_key": clinic_key,
            "headers": list(headers),
            "row_idx": row_idx,
            "row_values": list(row_values),
        }
        return sheet, list(headers), row_idx, row_values

    def get_authorized_fresh_row_values(self, clinic_id: str) -> tuple[object, list[str], int, list[str]]:
        clinic_id = require_authenticated_tenant_access(clinic_id)
        return self.get_fresh_row_values(clinic_id)

    def update_fields(
        self,
        clinic_id: str,
        values_by_header: dict[str, object],
        required_columns: list[str] | None = None,
    ) -> tuple[object, list[str], int]:
        return _raw_update_settings_row_fields(clinic_id, values_by_header, required_columns)

    def update_authorized_fields(
        self,
        clinic_id: str,
        values_by_header: dict[str, object],
        required_columns: list[str] | None = None,
    ) -> tuple[object, list[str], int]:
        clinic_id = require_authenticated_tenant_access(clinic_id)
        return self.update_fields(clinic_id, values_by_header, required_columns)


def settings_repository() -> SettingsRepository:
    return SettingsRepository()


def update_settings_row_fields(
    clinic_id: str,
    values_by_header: dict[str, object],
    required_columns: list[str] | None = None,
) -> tuple[object, list[str], int]:
    return settings_repository().update_fields(clinic_id, values_by_header, required_columns)


def update_authorized_settings_row_fields(
    clinic_id: str,
    values_by_header: dict[str, object],
    required_columns: list[str] | None = None,
) -> tuple[object, list[str], int]:
    return settings_repository().update_authorized_fields(clinic_id, values_by_header, required_columns)


def get_fresh_settings_row_values(clinic_id: str) -> tuple[object, list[str], int, list[str]]:
    """Read the clinic row directly from Sheets and refresh the session cache."""
    return settings_repository().get_fresh_row_values(clinic_id)


def get_authorized_fresh_settings_row_values(clinic_id: str) -> tuple[object, list[str], int, list[str]]:
    """Read the signed-in clinic row directly from Sheets and refresh the session cache."""
    return settings_repository().get_authorized_fresh_row_values(clinic_id)




def _copy_settings_dict(settings: dict | None) -> dict:
    try:
        return json.loads(json.dumps(settings or {}))
    except Exception:
        return dict(settings or {})


def cache_remote_settings(clinic_id: str, settings: dict | None) -> None:
    st.session_state["_remote_settings_cache"] = {
        "clinic_key": str(clinic_id or "").strip().lower(),
        "settings": _copy_settings_dict(settings),
    }


def get_cached_remote_settings(clinic_id: str) -> dict:
    cached = st.session_state.get("_remote_settings_cache")
    clinic_key = str(clinic_id or "").strip().lower()
    if isinstance(cached, dict) and cached.get("clinic_key") == clinic_key:
        return _copy_settings_dict(cached.get("settings", {}))
    return {}


TENANT_AUTHORIZATION_MESSAGE = "This action is not authorized for the signed-in clinic."


class TenantAuthorizationError(PermissionError):
    pass


class SettingsFreshReadError(RuntimeError):
    pass


def require_authenticated_tenant_access(clinic_id: str) -> str:
    target_clinic_id = str(clinic_id or "").strip()
    current_clinic_id = str(st.session_state.get("clinic_id", "") or "").strip()
    if (
        not target_clinic_id
        or not st.session_state.get("logged_in")
        or normalize_clinic_id_key(current_clinic_id) != normalize_clinic_id_key(target_clinic_id)
    ):
        raise TenantAuthorizationError(TENANT_AUTHORIZATION_MESSAGE)
    return target_clinic_id


def drive_file_owner_key(file_id: str) -> str:
    if not file_id:
        return ""
    service = get_drive_service()
    metadata = service.files().get(
        fileId=file_id,
        fields="id,appProperties",
        supportsAllDrives=True,
    ).execute()
    app_properties = metadata.get("appProperties", {}) or {}
    return normalize_clinic_id_key(
        app_properties.get("clinic_id")
        or app_properties.get("ClinicID")
        or app_properties.get("clinicId")
        or ""
    )


def require_clinic_dataset_file_access(
    clinic_id: str,
    file_id: str,
    current_file_id: str | None = None,
) -> str:
    clinic_id = require_authenticated_tenant_access(clinic_id)
    file_id = str(file_id or "").strip()
    if not file_id:
        return clinic_id

    if current_file_id is None:
        current_file_id, _ = get_existing_dataset_pointer(clinic_id)
    current_file_id = str(current_file_id or "").strip()
    if current_file_id and str(current_file_id).strip() != file_id:
        raise TenantAuthorizationError(TENANT_AUTHORIZATION_MESSAGE)

    owner_key = drive_file_owner_key(file_id)
    if owner_key and owner_key != normalize_clinic_id_key(clinic_id):
        raise TenantAuthorizationError(TENANT_AUTHORIZATION_MESSAGE)
    return clinic_id


def drive_trash_file(file_id: str, clinic_id: str | None = None, current_file_id: str | None = None):
    if not file_id:
        return
    if clinic_id is not None:
        require_clinic_dataset_file_access(clinic_id, file_id, current_file_id=current_file_id)
    service = get_drive_service()
    service.files().update(
        fileId=file_id,
        body={"trashed": True},
        supportsAllDrives=True
    ).execute()


def drive_rename_file(file_id: str, filename: str, clinic_id: str | None = None, current_file_id: str | None = None):
    if not file_id or not filename:
        return
    if clinic_id is not None:
        require_clinic_dataset_file_access(clinic_id, file_id, current_file_id=current_file_id)
    service = get_drive_service()
    service.files().update(
        fileId=file_id,
        body={"name": filename},
        supportsAllDrives=True,
    ).execute()

# -----------------------
# Keyword Definitions
# -----------------------
CONSULT_KEYWORDS = [
    "consult","examination", "checkup", "check-up",
    "recheck", "re-check", "follow-up", "follow up",
    "visit", "clinical assessment",
    "physical exam", "emergency"
]
CONSULT_EXCLUSIONS = [
    "fecal","blood","smear","faecal","urine","x-ray","xray","ultrasound","afast","tfast","a-fast","t-fast",
    "sitting","IDEXX","VHN"
]
DENTAL_KEYWORDS = ["dental","tooth","extraction","scale and polish","scale & polish","dentistry"]
DENTAL_EXCLUSIONS = ["Cataract","Oxyfresh","Healthy Bites","Healthy Bites","my beau"]

GROOM_KEYWORDS = ["groom","nail clip","nail trim","ear clean","ear flush","medicated bath"]
GROOM_EXCLUSIONS = ["Oxyfresh"]

BOARDING_KEYWORDS = ["board","sitting"]
BOARDING_EXCLUSIONS = ["Cardboard"]

FEE_KEYWORDS = ["fee"]
FEE_EXCLUSIONS = [
    "Hospitalization","hospitalisation","Examination","Consultation","Feed","Feel","House Call",
    
]

FLEA_WORM_KEYWORDS = [
    "bravecto", "revolution", "deworm","de-worm","frontline", "milbe", "milpro","advantix","advocate",
    "interceptor","stronghold","drontal","frontpro","credelio","caniverm","Selamectin",
    "nexgard", "simparica", "advocate", "worm", "prazi", "fenbend","popantel","panacur",
    "broadline","profender","comfortis","endecto","Fipronil","fiprotec","Fluralaner",
    
]
FLEA_WORM_EXCLUSIONS = ["felv","fiv","antigen","antibody","wild catz","ringworm"]

FOOD_KEYWORDS = [
    "hill's", "hills", "royal canin", "purina", "proplan", "iams", "eukanuba",
    "orijen", "acana", "farmina", "vetlife", "wellness", "taste of the wild",
    "nutro", "pouch", "canned", "wet", "dry", "kibble","fcn","hair & skin","hair&skin",
    "tuna", "chicken", "beef", "salmon", "lamb", "duck", "senior", "diet", "food", 
    "grain", "rc","bhn","vet diet","prescription diet","trovet","vhn","vcn","shn","fhn",
    "ccn","applaws","Feline Health Nutrition","satiety","Inaba Churu","Inaba Ciao",
    "Instinctive","thrive","Vet Diet","Moderate Calorie"
]
FOOD_EXCLUSIONS = [
    "caniverm","deworm","caninsulin","referral","endoscopy","colonoscopy","In-patient","Cat Sitting",
    "Selamectin","Thromboplastin","Injection Fee"
]                

XRAY_KEYWORDS = ["xray", "x-ray", "radiograph", "radiology"]
XRAY_EXCLUSIONS = []

ULTRASOUND_KEYWORDS = ["ultrasound", "echo", "afast", "tfast", "a-fast", "t-fast","cardiac scan","abdo scan","abdominal scan"]
ULTRASOUND_EXCLUSIONS = []

LABWORK_KEYWORDS = [
    "cbc", "blood test", "lab", "biochemistry", "haematology", "urinalysis", "labwork", "idexx", "ghp",
    "chem", "felv", "fiv", "urine", "cytology", "smear", "faecal", "fecal", "microscopic", "slide", "bun",
    "crea", "phosphate", "cpl", "cpli", "lipase", "amylase", "pancreatic", "cortisol","sdma","t4","tsh",
    "electrolyte","thyroid","snap","bilirubin","acth","Alanine","Aminotranserase","bast","bile acid",
    "creatinine","CRP","catalyst","tbil","total protein","microscope","fna","fine needle","floatation",
    "Parasitology","giardia","pcv","hct","haematocrit","hematocrit","corona","cystocentesis","aPTT",
    "coag","smear","Fructosamine","UPPC","UPC","protein creatinine","Immunohistochemistry","MRSA","PARR",
    "Culture & Sensitivity","C&S","swab","Immunology","favn","antibody","antigen","elisa","skin scrap"
]
LABWORK_EXCLUSIONS = ["cream","labrador","cremation","enema","prednisolone"]

ANAESTHETIC_KEYWORDS = [
    "anaesthesia", "anesthesia", "spay", "neuter", "castrate", "surgery","enucleation","laparotomy",
    "isoflurane", "propofol", "alfaxan", "alfaxalone","pyometra","cryptorch","endoscop","colonosc",
    "isoflo","Debride","induce","induction","graft","Exploratory","Laparoscopy","Myringotomy",
    "Otoendoscopy","castration","Amputation","amputate","Cystotomy","Diaphragmatic","Entropion",
    "Lump Removal","Urethrostomy","Tarsorrhaphy","3rd eye"
]
ANAESTHETIC_EXCLUSIONS = ["satiety","balance","vhn","royal canin","food","examination"]

HOSPITALISATION_KEYWORDS = ["hospitalisation", "hospitalization"]
HOSPITALISATION_EXCLUSIONS = []

VACCINE_KEYWORDS = [
    "vaccine", "vaccination", "booster", "rabies", "dhpp", "tricat","FIV",
    "pch", "pcl", "leukemia", "kennel cough","lepto","leukaemia","felv","bordatella"
]
VACCINE_EXCLUSIONS = ["test", "titre", "antibody","bites","book","idexx","elisa","SNAP"]

DEATH_KEYWORDS = ["euthanasia", "pentobarb", "cremation", "burial", "disposal"]
DEATH_EXCLUSIONS = []
PATIENT_PASSAWAY_KEYWORDS_DEFAULT = DEATH_KEYWORDS.copy()

NEUTER_KEYWORDS = ["spay", "castrate", "castration", "desex", "de-sex","cryptorch","ovariohyst","TNR"]
NEUTER_EXCLUSIONS = ["adult", "food", "diet", "canin", "purina", "proplan"]

PATIENT_VISIT_KEYWORDS = (
    XRAY_KEYWORDS
    + ULTRASOUND_KEYWORDS
    + ANAESTHETIC_KEYWORDS
    + HOSPITALISATION_KEYWORDS
    + VACCINE_KEYWORDS
    + DEATH_KEYWORDS
    + NEUTER_KEYWORDS
    + DENTAL_KEYWORDS
    + CONSULT_KEYWORDS
    + GROOM_KEYWORDS
)

PATIENT_VISIT_EXCLUSIONS = (
    XRAY_EXCLUSIONS
    + ULTRASOUND_EXCLUSIONS
    + ANAESTHETIC_EXCLUSIONS
    + HOSPITALISATION_EXCLUSIONS
    + VACCINE_EXCLUSIONS
    + DEATH_EXCLUSIONS
    + NEUTER_EXCLUSIONS
    + DENTAL_EXCLUSIONS
    + CONSULT_EXCLUSIONS
    + GROOM_EXCLUSIONS
    
)

# Optionally, add your own custom visit-only indicators here
PATIENT_VISIT_KEYWORDS += [
    "flush","nail clip","nail trim","injection","blood glucose","blood pressure","blood sampl","woods lamp",
    "wound clean", "bandage", "biopsy","sedation","anal gland","cystocentesis","ketamin","inj",
    "admit", "discharge", "inpatient", "in patient","in-patient","abscess","draining","eye pressure","tonometry",
    "ocular pressure","stt","Fluorescein","oxygen","overnight","Schirmer","fluid","catheter","Thoracocentesis",
    
]
PATIENT_VISIT_EXCLUSIONS += []

#########
# VetPORT fixing
#########
VETPORT_PATRIKEDIT_COLS = [
    "Planitem Performed", "Client Name", "Client ID", "Patient Name",
    "Patient ID", "Plan Item ID", "Plan Item Name", "Plan Item Quantity",
    "Performed Staff", "Plan Item Amount", "Returned Quantity",
    "Returned Date", "Invoice No"
]

def _norm_header_key(h: str) -> str:
    """Normalize header for matching (case/spacing/unicode)."""
    if not isinstance(h, str):
        h = str(h)
    h = unicodedata.normalize("NFKC", h).replace("\u00a0", " ").replace("\ufeff", "")
    h = _SPACE_RX.sub(" ", h).strip().lower()
    return h

def _to_patrik_num_str(x) -> str:
    """
    Make numeric strings match PatrikEdit formatting:
    - strip whitespace
    - remove trailing zeros (106.10 -> 106.1, 52.00 -> 52)
    - keep '-' and '' as-is
    """
    if x is None:
        return ""
    s = str(x).strip()
    if s == "" or s == "-" or s.lower() == "nan":
        return "" if s.lower() == "nan" else s
    s = s.replace(",", "")
    try:
        d = Decimal(s)
    except (InvalidOperation, ValueError):
        return s
    # normalize removes trailing zeros; format(...,'f') avoids scientific notation
    d = d.normalize()
    return format(d, "f")

def normalize_vetport_to_patrikedit(df: pd.DataFrame) -> pd.DataFrame:
    """
    Force any Vetport-shaped dataset into EXACTLY the PatrikEdit format:
    - exact column names (case)
    - exact column order
    - whitespace-stripped cells
    - numeric formatting normalized for Qty/Amount/IDs where applicable
    """
    df = df.copy()

    # 1) Build a rename map from whatever headers we received -> canonical PatrikEdit headers
    #    Works even if input has leading/trailing spaces or different casing.
    canon_by_norm = {_norm_header_key(c): c for c in VETPORT_PATRIKEDIT_COLS}

    rename_map = {}
    for c in df.columns:
        nk = _norm_header_key(c)
        if nk in canon_by_norm:
            rename_map[c] = canon_by_norm[nk]

    df = df.rename(columns=rename_map)

    # 2) Ensure all PatrikEdit columns exist (even if missing in input)
    for c in VETPORT_PATRIKEDIT_COLS:
        if c not in df.columns:
            df[c] = ""

    # 3) Reorder columns to EXACT PatrikEdit order (+ keep any extras at the end)
    extras = [c for c in df.columns if c not in VETPORT_PATRIKEDIT_COLS]
    df = df[VETPORT_PATRIKEDIT_COLS + extras]

    # 4) Strip whitespace from all PatrikEdit columns (critical: removes leading spaces from CSVs)
    for c in VETPORT_PATRIKEDIT_COLS:
        df[c] = df[c].astype(str).str.strip().replace({"nan": ""})

    # 5) Normalize numeric-looking fields to PatrikEdit style
    #    (IDs often come in with leading spaces; amounts/qty may have .0 or .00)
    num_cols = ["Plan Item Quantity", "Plan Item Amount", "Returned Quantity", "Invoice No"]
    for c in num_cols:
        if c in df.columns:
            df[c] = df[c].apply(_to_patrik_num_str)

    # 6) Also strip Planitem Performed again (some files have leading spaces there)
    df["Planitem Performed"] = df["Planitem Performed"].astype(str).str.strip()

    return df

# --------------------------------
# Keyword Mask Helper (Global)
# --------------------------------
def make_mask(df, include_words, exclude_words=None):
    """Returns a boolean mask matching include_words but excluding exclude_words."""
    if df.empty or "Item Name" not in df.columns:
        return pd.Series(False, index=df.index)

    include_rx = re.compile("|".join(map(re.escape, include_words)), re.I)
    mask = df["Item Name"].astype(str).str.contains(include_rx, na=False)

    if exclude_words:
        exclude_rx = re.compile("|".join(map(re.escape, exclude_words)), re.I)
        mask &= ~df["Item Name"].astype(str).str.contains(exclude_rx, na=False)

    return mask


def normalize_passaway_keywords(keywords) -> list[str]:
    normalized = []
    seen = set()
    for keyword in keywords or []:
        cleaned = _SPACE_RX.sub(" ", str(keyword or "").strip()).lower()
        if not cleaned or cleaned in seen:
            continue
        normalized.append(cleaned)
        seen.add(cleaned)
    return normalized


def normalize_patient_exclusions(exclusions) -> list[dict]:
    normalized = []
    seen = set()
    for item in exclusions or []:
        if not isinstance(item, dict):
            continue
        client = _SPACE_RX.sub(" ", str(item.get("client", "") or "").strip())
        patient = _SPACE_RX.sub(" ", str(item.get("patient", "") or "").strip())
        if not client or not patient:
            continue
        key = (client.lower(), patient.lower())
        if key in seen:
            continue
        normalized.append({"client": client, "patient": patient})
        seen.add(key)
    return normalized


def combined_patient_exclusions() -> list[dict]:
    return normalize_patient_exclusions(
        st.session_state.get("patient_exclusions", [])
    ) + normalize_patient_exclusions(
        st.session_state.get("automatic_patient_exclusions", [])
    )


def find_patient_passaway_exclusions(df: pd.DataFrame, keywords=None) -> list[dict]:
    if df is None or df.empty:
        return []
    required_columns = {"Client Name", "Animal Name", "Item Name"}
    if not required_columns.issubset(df.columns):
        return []

    normalized_keywords = normalize_passaway_keywords(
        keywords if keywords is not None else PATIENT_PASSAWAY_KEYWORDS_DEFAULT
    )
    if not normalized_keywords:
        return []

    pattern = "|".join(map(re.escape, normalized_keywords))
    matched = df[
        df["Item Name"].astype(str).str.lower().str.contains(pattern, regex=True, na=False)
    ]
    exclusions = [
        {"client": row.get("Client Name", ""), "patient": row.get("Animal Name", "")}
        for row in matched.to_dict("records")
    ]
    return normalize_patient_exclusions(exclusions)


def add_automatic_patient_exclusions_from_upload(df: pd.DataFrame) -> int:
    found_exclusions = find_patient_passaway_exclusions(
        df,
        st.session_state.get("patient_passaway_keywords", PATIENT_PASSAWAY_KEYWORDS_DEFAULT),
    )
    if not found_exclusions:
        return 0

    existing = normalize_patient_exclusions(st.session_state.get("automatic_patient_exclusions", []))
    existing_keys = {
        (_exclusion_key(item.get("client", "")), _exclusion_key(item.get("patient", "")))
        for item in existing
    }
    added = []
    for item in found_exclusions:
        key = (_exclusion_key(item.get("client", "")), _exclusion_key(item.get("patient", "")))
        if key in existing_keys:
            continue
        existing.append(item)
        existing_keys.add(key)
        added.append(item)

    if added:
        st.session_state["automatic_patient_exclusions"] = existing
    return len(added)

# --------------------------------
# CSS Styling
# --------------------------------
st.markdown(
    '''
    <style>
    :root {
        --cr-primary: #29D272;
        --cr-primary-dark: #1DA759;
        --cr-primary-soft: #dcf8e8;
        --cr-primary-quiet: #f1fbf6;
        --cr-app-bg: #f6faf7;
        --cr-surface: #ffffff;
        --cr-surface-muted: #eff7f3;
        --cr-sidebar-bg: #eef7f2;
        --cr-sidebar-account-bg: #eef7f2;
        --cr-text: #101828;
        --cr-muted: #60746a;
        --cr-border: #dbe9e1;
        --cr-link: #168a4c;
        --cr-link-hover: #0f6f3d;
        --cr-chip-bg: rgba(41, 210, 114, 0.11);
        --cr-step-bg: #fbfdfc;
        --cr-step-complete-bg: #e4f9ee;
        --cr-step-complete-border: rgba(41, 210, 114, 0.52);
        --cr-step-current-bg: #dff8ea;
        --cr-step-current-border: #29D272;
        --cr-step-optional-bg: #fff7df;
        --cr-step-optional-border: #f4c95d;
    }
    [data-theme="light"], [data-baseweb-theme="light"] {
        --cr-primary: #29D272;
        --cr-primary-dark: #1DA759;
        --cr-primary-soft: #dcf8e8;
        --cr-primary-quiet: #f1fbf6;
        --cr-app-bg: #f6faf7;
        --cr-surface: #ffffff;
        --cr-surface-muted: #eff7f3;
        --cr-sidebar-bg: #eef7f2;
        --cr-sidebar-account-bg: #eef7f2;
        --cr-text: #101828;
        --cr-muted: #60746a;
        --cr-border: #dbe9e1;
        --cr-link: #168a4c;
        --cr-link-hover: #0f6f3d;
        --cr-chip-bg: rgba(41, 210, 114, 0.11);
        --cr-step-bg: #fbfdfc;
        --cr-step-complete-bg: #e4f9ee;
        --cr-step-complete-border: rgba(41, 210, 114, 0.52);
        --cr-step-current-bg: #dff8ea;
        --cr-step-current-border: #29D272;
        --cr-step-optional-bg: #fff7df;
        --cr-step-optional-border: #f4c95d;
    }
    [data-theme="dark"], [data-baseweb-theme="dark"] {
        --cr-primary: #29D272;
        --cr-primary-dark: #1DA759;
        --cr-primary-soft: rgba(41, 210, 114, 0.14);
        --cr-primary-quiet: rgba(41, 210, 114, 0.08);
        --cr-app-bg: #0e1117;
        --cr-surface: #161b22;
        --cr-surface-muted: rgba(255,255,255,0.035);
        --cr-sidebar-bg: #262730;
        --cr-sidebar-account-bg: #262730;
        --cr-text: #f8fafc;
        --cr-muted: rgba(255,255,255,0.72);
        --cr-border: rgba(255,255,255,0.12);
        --cr-link: #29D272;
        --cr-link-hover: #6EE7A3;
        --cr-chip-bg: rgba(255,255,255,0.10);
        --cr-step-bg: rgba(255,255,255,0.035);
        --cr-step-complete-bg: rgba(16, 185, 129, 0.10);
        --cr-step-complete-border: rgba(52, 211, 153, 0.45);
        --cr-step-current-bg: rgba(41, 210, 114, 0.12);
        --cr-step-current-border: rgba(41, 210, 114, 0.50);
        --cr-step-optional-bg: rgba(245, 158, 11, 0.08);
        --cr-step-optional-border: rgba(245, 158, 11, 0.35);
    }
    .stApp, [data-testid="stAppViewContainer"] {
        background: var(--cr-app-bg) !important;
        color-scheme: light !important;
        color: var(--cr-text);
    }
    html, body, [data-testid="stAppViewContainer"], [data-testid="stApp"], [data-baseweb] {
        color-scheme: light !important;
    }
    header[data-testid="stHeader"],
    [data-testid="stHeader"],
    [data-testid="stToolbar"],
    [data-testid="stDecoration"] {
        background: var(--cr-app-bg) !important;
    }
    section[data-testid="stSidebar"] {
        background: var(--cr-sidebar-bg) !important;
    }
    section[data-testid="stSidebar"] [data-testid="stSidebarContent"] {
        background: var(--cr-sidebar-bg) !important;
    }
    .block-container h1, .block-container h2, .block-container h3 { margin-top: 0.2rem; }
    div[data-testid="stButton"] { min-height: 0px !important; height: auto !important; }
    .block-container { max-width: 100% !important; padding-left: 2rem; padding-right: 2rem; padding-bottom: max(7rem, 42vh) !important; }
    h2[id] { scroll-margin-top: 80px; }
    .anchor-offset { position: relative; top: -100px; height: 0; }
    .sidebar-clinic-block {
        font-size: 15px;
        line-height: 1.5;
        margin-bottom: 1.1rem;
    }
    .sidebar-clinic-name {
        color: var(--cr-muted);
        word-break: break-word;
    }
    section[data-testid="stSidebar"] a {
        color: var(--cr-link) !important;
    }
    section[data-testid="stSidebar"] a:hover {
        color: var(--cr-link-hover) !important;
    }
    section[data-testid="stSidebar"] div[data-testid="stButton"] {
        width: 100% !important;
    }
    section[data-testid="stSidebar"] div[data-testid="stButton"] button {
        display: block !important;
        justify-content: flex-start !important;
        align-items: center !important;
        text-align: left !important;
        border: 0 !important;
        background: transparent !important;
        box-shadow: none !important;
        padding: 0.05rem 0 !important;
        min-height: 1.85rem;
        width: 100% !important;
    }
    section[data-testid="stSidebar"] div[data-testid="stButton"] button:hover {
        color: var(--cr-link);
        border: 0 !important;
        background: transparent !important;
    }
    section[data-testid="stSidebar"] div[data-testid="stButton"] button div[data-testid="stMarkdownContainer"] {
        display: block !important;
        width: 100% !important;
        text-align: left !important;
    }
    section[data-testid="stSidebar"] div[data-testid="stButton"] button div[data-testid="stMarkdownContainer"] p {
        margin: 0 !important;
        text-align: left !important;
    }
    .st-key-sidebar_account_actions {
        background: var(--cr-sidebar-account-bg);
        border-top: 1px solid var(--cr-border);
        bottom: 1rem;
        left: 1rem;
        max-height: 70vh;
        overflow-y: auto;
        padding: 0.25rem 0;
        position: fixed;
        width: 14rem;
        z-index: 100;
    }
    .st-key-sidebar_account_actions div[data-testid="stButton"] button {
        display: flex !important;
        justify-content: center !important;
        text-align: center !important;
    }
    .st-key-sidebar_account_actions div[data-testid="stButton"] button div[data-testid="stMarkdownContainer"],
    .st-key-sidebar_account_actions div[data-testid="stButton"] button div[data-testid="stMarkdownContainer"] p {
        text-align: center !important;
        width: 100% !important;
    }
    section[data-testid="stSidebar"] div[data-testid="stFormSubmitButton"] button {
        justify-content: center !important;
        text-align: center !important;
        min-height: 2.4rem;
    }
    section[data-testid="stSidebar"] div[data-testid="stFormSubmitButton"] button p {
        text-align: center !important;
    }
    div[data-testid="InputInstructions"] {
        display: none !important;
    }
    [data-baseweb="input"],
    [data-baseweb="base-input"],
    [data-baseweb="textarea"],
    [data-baseweb="select"] > div {
        background-color: #ffffff !important;
        border-color: #d0d7e2 !important;
        color: #101828 !important;
        box-shadow: none !important;
    }
    [data-baseweb="input"] *,
    [data-baseweb="base-input"] *,
    [data-baseweb="textarea"] *,
    [data-baseweb="select"] *,
    [data-baseweb="checkbox"] * {
        color-scheme: light !important;
    }
    [data-baseweb="input"] input,
    [data-baseweb="base-input"] input,
    [data-baseweb="textarea"] textarea {
        background-color: transparent !important;
        color: #101828 !important;
        -webkit-text-fill-color: #101828 !important;
    }
    [data-baseweb="input"] input::placeholder,
    [data-baseweb="base-input"] input::placeholder,
    [data-baseweb="textarea"] textarea::placeholder {
        color: #667085 !important;
        -webkit-text-fill-color: #667085 !important;
        opacity: 1 !important;
    }
    [data-baseweb="checkbox"] {
        color: #101828 !important;
        background: transparent !important;
        color-scheme: light !important;
    }
    [data-baseweb="checkbox"] input[type="checkbox"] {
        accent-color: #29D272 !important;
        color-scheme: light !important;
    }
    div[data-testid="stTextInput"] [data-baseweb="input"],
    div[data-testid="stTextInput"] [data-baseweb="base-input"],
    div[data-testid="stNumberInput"] [data-baseweb="input"],
    div[data-testid="stNumberInput"] [data-baseweb="base-input"],
    div[data-testid="stDateInput"] [data-baseweb="input"],
    div[data-testid="stDateInput"] [data-baseweb="base-input"],
    div[data-testid="stTextArea"] [data-baseweb="textarea"],
    div[data-testid="stSelectbox"] [data-baseweb="select"] > div {
        background: #ffffff !important;
        border-color: #d0d7e2 !important;
        color: #101828 !important;
        box-shadow: none !important;
    }
    div[data-testid="stTextInput"] input,
    div[data-testid="stNumberInput"] input,
    div[data-testid="stDateInput"] input,
    div[data-testid="stTextArea"] textarea,
    div[data-testid="stSelectbox"] div,
    div[data-testid="stSelectbox"] span {
        color: #101828 !important;
        -webkit-text-fill-color: #101828 !important;
    }
    div[data-testid="stTextInput"] input::placeholder,
    div[data-testid="stNumberInput"] input::placeholder,
    div[data-testid="stDateInput"] input::placeholder,
    div[data-testid="stTextArea"] textarea::placeholder {
        color: #667085 !important;
        -webkit-text-fill-color: #667085 !important;
        opacity: 1 !important;
    }
    div[data-testid="stNumberInput"] button {
        background: #ffffff !important;
        border-color: #d0d7e2 !important;
        color: #334155 !important;
    }
    div[data-testid="stNumberInput"] button svg {
        color: #334155 !important;
        fill: #334155 !important;
    }
    div[data-testid="stCheckbox"] label,
    div[data-testid="stCheckbox"] label p {
        color: #101828 !important;
        -webkit-text-fill-color: #101828 !important;
    }
    div[data-testid="stCheckbox"] label p,
    div[data-testid="stCheckbox"] label div[data-testid="stMarkdownContainer"] {
        background: transparent !important;
    }
    div[data-testid="stCheckbox"] label,
    div[data-testid="stCheckbox"] [data-baseweb="checkbox"] {
        background: transparent !important;
    }
    div[data-testid="stFileUploader"] section[data-testid="stFileUploaderDropzone"] {
        background: #ffffff !important;
        border: 1px dashed #b8c7d3 !important;
        color: #101828 !important;
    }
    div[data-testid="stFileUploader"] section[data-testid="stFileUploaderDropzone"] button {
        background: #ffffff !important;
        border: 1px solid #d0d7e2 !important;
        color: #101828 !important;
    }
    div[data-testid="stFileUploader"] section[data-testid="stFileUploaderDropzone"] button p,
    div[data-testid="stFileUploader"] section[data-testid="stFileUploaderDropzone"] p,
    div[data-testid="stFileUploader"] section[data-testid="stFileUploaderDropzone"] span {
        color: #101828 !important;
        -webkit-text-fill-color: #101828 !important;
    }
    div[data-testid="stFileUploader"] section[data-testid="stFileUploaderDropzone"] svg {
        color: #29D272 !important;
        fill: #29D272 !important;
    }
    div[data-testid="stFormSubmitButton"] button[kind="primary"],
    div[data-testid="stButton"] button[kind="primary"] {
        background: var(--cr-primary) !important;
        border-color: var(--cr-primary) !important;
        color: #062d19 !important;
    }
    div[data-testid="stFormSubmitButton"] button[kind="primary"]:hover,
    div[data-testid="stButton"] button[kind="primary"]:hover {
        background: var(--cr-primary-dark) !important;
        border-color: var(--cr-primary-dark) !important;
        color: #ffffff !important;
    }
    .cr-page-hero {
        background: linear-gradient(135deg, rgba(41, 210, 114, 0.14), rgba(255, 255, 255, 0.98));
        border: 1px solid rgba(29, 167, 89, 0.22);
        border-radius: 8px;
        box-shadow: 0 12px 34px rgba(15, 23, 42, 0.05);
        margin: 0.1rem 0 1rem;
        padding: 1.05rem 1.1rem;
    }
    .cr-page-kicker {
        color: #15803d;
        font-size: 0.78rem;
        font-weight: 850;
        letter-spacing: 0.08em;
        margin: 0 0 0.38rem;
        text-transform: uppercase;
    }
    .cr-page-hero h2 {
        color: #082f1f;
        font-size: 1.65rem;
        font-weight: 900;
        letter-spacing: 0;
        line-height: 1.16;
        margin: 0 0 0.38rem !important;
    }
    .cr-page-hero p {
        color: #475569;
        font-size: 0.96rem;
        line-height: 1.45;
        margin: 0;
        max-width: 54rem;
    }
    .cr-section-card {
        background: #ffffff;
        border: 1px solid rgba(15, 23, 42, 0.10);
        border-radius: 8px;
        box-shadow: 0 8px 24px rgba(15, 23, 42, 0.04);
        margin: 0.85rem 0;
        padding: 1rem 1rem 0.9rem;
    }
    .cr-section-title {
        color: #0f172a;
        font-size: 1.02rem;
        font-weight: 850;
        line-height: 1.25;
        margin: 0 0 0.28rem;
    }
    .cr-section-copy {
        color: #64748b;
        font-size: 0.92rem;
        line-height: 1.42;
        margin: 0 0 0.7rem;
    }
    .cr-field-intro {
        margin-bottom: 0.8rem;
    }
    .cr-field-intro .cr-section-copy {
        margin-bottom: 0;
    }
    .cr-field-footnote {
        color: #64748b;
        font-size: 0.88rem;
        line-height: 1.4;
        margin: 0.35rem 0 0;
    }
    .cr-field-danger-note {
        background: #fff7f7;
        border: 1px solid rgba(248, 113, 113, 0.24);
        border-radius: 8px;
        color: #7f1d1d;
        font-size: 0.9rem;
        line-height: 1.4;
        margin: 0.15rem 0 0.75rem;
        padding: 0.65rem 0.75rem;
    }
    .cr-danger-card {
        background: #fffafa;
        border-color: rgba(248, 113, 113, 0.24);
    }
    .cr-danger-card .cr-section-title {
        color: #7f1d1d;
    }
    .cr-upload-help-actions {
        margin: -0.15rem 0 0.85rem;
    }
    .st-key-open_upload_sales_data_help button,
    .st-key-close_upload_sales_data_help_dialog button,
    .st-key-close_data_privacy_dialog_button button,
    .st-key-new_account_welcome_get_started button {
        border-radius: 8px !important;
        font-weight: 800 !important;
        min-height: 2.55rem !important;
    }
    .st-key-open_upload_sales_data_help button {
        background: #ffffff !important;
        border: 1px solid rgba(22, 138, 76, 0.28) !important;
        box-shadow: 0 8px 20px rgba(15, 23, 42, 0.04) !important;
        color: #0f5130 !important;
        width: auto !important;
    }
    .st-key-open_upload_sales_data_help button:hover {
        background: #f1fbf6 !important;
        border-color: rgba(22, 138, 76, 0.48) !important;
        color: #0b3d26 !important;
    }
    .st-key-top_account_profile button,
    .st-key-top_account_data_privacy button,
    .st-key-top_account_show_change_password button,
    .st-key-top_account_delete button,
    .st-key-top_account_logout button {
        background: #ffffff !important;
        border: 1px solid rgba(15, 23, 42, 0.11) !important;
        border-radius: 8px !important;
        box-shadow: 0 6px 18px rgba(15, 23, 42, 0.035) !important;
        color: #0f172a !important;
        font-weight: 750 !important;
        min-height: 2.45rem !important;
    }
    .st-key-top_account_profile button:hover,
    .st-key-top_account_data_privacy button:hover,
    .st-key-top_account_show_change_password button:hover,
    .st-key-top_account_logout button:hover {
        background: #f8fafc !important;
        border-color: rgba(41, 210, 114, 0.36) !important;
        color: #0b3d26 !important;
    }
    .st-key-top_account_delete button {
        background: #fff7f7 !important;
        border-color: rgba(248, 113, 113, 0.28) !important;
        color: #9f1239 !important;
    }
    .st-key-top_account_delete button:hover {
        background: #fff1f2 !important;
        border-color: rgba(244, 63, 94, 0.42) !important;
        color: #881337 !important;
    }
    .st-key-google_signup_button button,
    .st-key-toggle_create_account button {
        min-height: 2.75rem !important;
        width: 100% !important;
    }
    .login-title {
        color: var(--cr-text);
        font-size: 1.75rem;
        font-weight: 800;
        line-height: 1.25;
        margin: 0 0 1.55rem 15px;
    }
    div[data-testid="stForm"]:has(.login-form-marker) {
        background: transparent !important;
        border: 0 !important;
        border-radius: 0 !important;
        box-shadow: none !important;
        padding: 0 15px !important;
    }
    .login-form-marker {
        display: none;
    }
    div[data-testid="stHorizontalBlock"]:has(.st-key-google_signup_button) {
        padding-left: 15px !important;
        padding-right: 15px !important;
    }
    .st-key-google_signup_button,
    .st-key-toggle_create_account {
        width: 100% !important;
    }
    .st-key-login_username_input,
    .st-key-login_password_input {
        width: 100% !important;
    }
    .st-key-login_username_input label,
    .st-key-login_password_input label,
    .st-key-login_username_input label p,
    .st-key-login_password_input label p {
        color: var(--cr-text) !important;
        font-size: 0.9rem !important;
        font-weight: 700 !important;
        margin-bottom: 0.3rem !important;
    }
    .st-key-login_username_input [data-baseweb="input"],
    .st-key-login_username_input [data-baseweb="base-input"],
    .st-key-login_password_input [data-baseweb="input"],
    .st-key-login_password_input [data-baseweb="base-input"] {
        align-items: center !important;
        background: #f8fafc !important;
        border: 1px solid #d9e3ec !important;
        border-radius: 8px !important;
        box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04) !important;
        min-height: 2.75rem !important;
        overflow: hidden !important;
        width: 100% !important;
    }
    .st-key-login_username_input input,
    .st-key-login_password_input input {
        background: transparent !important;
        border: 0 !important;
        box-shadow: none !important;
        color: #101828 !important;
        height: 2.75rem !important;
        outline: 0 !important;
        padding-left: 0.85rem !important;
        padding-right: 0.85rem !important;
        -webkit-text-fill-color: #101828 !important;
        width: 100% !important;
    }
    .st-key-login_password_input input {
        -webkit-text-security: disc !important;
        text-security: disc !important;
    }
    .st-key-login_password_input [data-baseweb="input"] > div,
    .st-key-login_password_input [data-baseweb="base-input"] > div {
        background: transparent !important;
        border: 0 !important;
        box-shadow: none !important;
        min-width: 0 !important;
    }
    .st-key-login_password_input button {
        display: none !important;
    }
    .st-key-login_username_input [data-baseweb="input"]:focus-within,
    .st-key-login_username_input [data-baseweb="base-input"]:focus-within,
    .st-key-login_password_input [data-baseweb="input"]:focus-within,
    .st-key-login_password_input [data-baseweb="base-input"]:focus-within {
        background: #ffffff !important;
        border-color: #29D272 !important;
        box-shadow: 0 0 0 2px rgba(41, 210, 114, 0.16) !important;
    }
    .st-key-google_signup_button button {
        background: #ffffff !important;
        border: 1.5px solid #4285f4 !important;
        box-shadow: 0 8px 20px rgba(66, 133, 244, 0.18) !important;
        color: #12243f !important;
        font-weight: 800 !important;
    }
    .st-key-google_signup_button button:hover {
        background: #f7fbff !important;
        border-color: #1a73e8 !important;
        box-shadow: 0 10px 24px rgba(26, 115, 232, 0.24) !important;
        color: #0b1f3a !important;
    }
    .st-key-google_signup_button button::before {
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 18 18'%3E%3Cpath fill='%234285F4' d='M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84c-.21 1.12-.84 2.07-1.79 2.71v2.25h2.9c1.7-1.56 2.69-3.86 2.69-6.6z'/%3E%3Cpath fill='%2334A853' d='M9 18c2.43 0 4.47-.8 5.96-2.19l-2.9-2.25c-.8.54-1.82.86-3.06.86-2.35 0-4.34-1.58-5.05-3.71H.96v2.33C2.44 15.98 5.49 18 9 18z'/%3E%3Cpath fill='%23FBBC05' d='M3.95 10.71c-.18-.54-.28-1.11-.28-1.71s.1-1.17.28-1.71V4.96H.96C.35 6.17 0 7.54 0 9s.35 2.83.96 4.04l2.99-2.33z'/%3E%3Cpath fill='%23EA4335' d='M9 3.58c1.32 0 2.51.45 3.44 1.35l2.58-2.58C13.46.9 11.43 0 9 0 5.49 0 2.44 2.02.96 4.96l2.99 2.33C4.66 5.16 6.65 3.58 9 3.58z'/%3E%3C/svg%3E");
        background-position: center;
        background-repeat: no-repeat;
        background-size: 1.15rem 1.15rem;
        content: "";
        display: inline-block;
        height: 1.15rem;
        margin-right: 0.5rem;
        width: 1.15rem;
    }
    .st-key-google_signup_button button p,
    .st-key-toggle_create_account button p {
        font-weight: inherit !important;
        margin: 0 !important;
    }
    .st-key-toggle_create_account button {
        background: #ffffff !important;
        border: 1px solid #d0d7e2 !important;
        color: #101828 !important;
        font-weight: 700 !important;
    }
    .st-key-toggle_create_account button:hover {
        background: #f8fafc !important;
        border-color: #98a2b3 !important;
        color: #101828 !important;
    }
    .dataset-summary {
        background: var(--cr-primary-soft);
        border: 1px solid rgba(41, 210, 114, 0.22);
        border-radius: 6px;
        color: #126b3d;
        margin: 0.35rem 0 0.85rem;
        padding: 0.85rem 1rem;
    }
    .st-key-dataset_summary_box {
        background: var(--cr-primary-soft);
        border: 1px solid rgba(41, 210, 114, 0.22);
        border-radius: 6px;
        color: #126b3d;
        margin: 0.35rem 0 0.4rem;
        padding: 0.9rem 1rem 0.75rem;
    }
    .reminders-caught-up-banner {
        align-items: center;
        background: linear-gradient(135deg, rgba(41, 210, 114, 0.18), rgba(255, 255, 255, 0.92));
        border: 1px solid rgba(29, 167, 89, 0.32);
        border-radius: 8px;
        box-shadow: 0 8px 22px rgba(15, 23, 42, 0.05);
        color: #0f5130;
        display: flex;
        gap: 0.8rem;
        margin: 0.35rem 0 0.95rem;
        padding: 0.85rem 1rem;
    }
    .reminders-caught-up-icon {
        align-items: center;
        background: var(--cr-primary);
        border-radius: 999px;
        color: #062d19;
        display: inline-flex;
        flex: 0 0 auto;
        font-size: 1rem;
        font-weight: 900;
        height: 2rem;
        justify-content: center;
        width: 2rem;
    }
    .reminders-caught-up-title {
        color: #0b3d26;
        font-size: 1rem;
        font-weight: 800;
        line-height: 1.25;
        margin: 0;
    }
    .reminders-caught-up-copy {
        color: #37624b;
        font-size: 0.9rem;
        line-height: 1.35;
        margin: 0.18rem 0 0;
    }
    .st-key-dataset_summary_box [data-testid="stVerticalBlock"] {
        gap: 0.35rem !important;
    }
    .st-key-dataset_summary_box [data-testid="stHorizontalBlock"]:last-child {
        margin-bottom: 0 !important;
        padding-bottom: 0 !important;
    }
    .st-key-dataset_summary_box [data-testid="stMarkdownContainer"] p {
        margin-bottom: 0 !important;
    }
    .dataset-summary-title {
        color: #0f5130;
        font-size: 1rem;
        font-weight: 700;
        margin-bottom: 0.4rem;
    }
    .dataset-summary-grid {
        display: grid;
        gap: 0.35rem 1.25rem;
        grid-template-columns: repeat(3, minmax(150px, 1fr));
    }
    .dataset-summary-table {
        display: grid;
        gap: 0.35rem;
    }
    .dataset-summary-header,
    .dataset-summary-row {
        align-items: start;
        display: grid;
        gap: 0.35rem 1.25rem;
        grid-template-columns: minmax(220px, 2fr) minmax(95px, 0.55fr) minmax(90px, 0.45fr) minmax(170px, 1fr) minmax(70px, 0.35fr);
    }
    .dataset-summary-row + .dataset-summary-row {
        border-top: 1px solid rgba(41, 210, 114, 0.18);
        padding-top: 0.35rem;
    }
    .dataset-summary-label {
        color: var(--cr-muted);
        font-size: 0.78rem;
        font-weight: 600;
        text-transform: uppercase;
    }
    .dataset-summary-value {
        color: var(--cr-text);
        font-size: 0.95rem;
        font-weight: 650;
        overflow-wrap: anywhere;
    }
    .dataset-summary-remove {
        color: #e11d48;
        font-size: 1.15rem;
        font-weight: 800;
        line-height: 1;
        text-decoration: none;
    }
    [class*="remove_dataset_upload_button"] button,
    [class*="remove-dataset-upload-button"] button {
        background: rgba(225, 29, 72, 0.06) !important;
        border: 1px solid rgba(225, 29, 72, 0.24) !important;
        border-radius: 6px !important;
        box-shadow: none !important;
        color: #e11d48 !important;
        font-weight: 750 !important;
        line-height: 1.1 !important;
        min-height: 2.1rem !important;
        padding: 0.25rem 0.55rem !important;
    }
    [class*="remove_dataset_upload_button"] button p,
    [class*="remove-dataset-upload-button"] button p {
        color: #e11d48 !important;
        font-size: 0.88rem !important;
        font-weight: 750 !important;
        margin: 0 !important;
    }
    div[data-testid="stFileUploader"] {
        margin-bottom: 0 !important;
    }
    div[data-testid="stFileUploader"] section[data-testid="stFileUploaderDropzone"] {
        min-height: 3rem !important;
        padding: 0.45rem 0.75rem !important;
    }
    div[data-testid="stFileUploader"] [data-testid="stFileUploaderDropzoneInstructions"] {
        display: none !important;
    }
    .dataset-check-grid {
        display: grid;
        gap: 0.6rem;
        grid-template-columns: repeat(3, minmax(180px, 1fr));
        margin: 0 1rem 0.9rem;
    }
    .dataset-check {
        border-radius: 8px;
        font-size: 0.92rem;
        font-weight: 650;
        line-height: 1.3;
        padding: 0.6rem 0.7rem;
    }
    .dataset-check.good {
        background: #dcfce7;
        border: 1px solid rgba(34, 197, 94, 0.45);
        color: #14532d;
    }
    .dataset-check.bad {
        background: #fff1f2;
        border: 1px solid rgba(248, 113, 113, 0.45);
        color: #9f1239;
    }
    .data-assurance-box {
        background: #ecfdf3;
        border: 1px solid rgba(22, 163, 74, 0.28);
        border-radius: 8px;
        color: #14532d;
        margin: 0.75rem 0 1rem;
        padding: 0.9rem 1rem;
    }
    .data-assurance-box strong {
        color: #052e16;
    }
    .data-assurance-box ul {
        margin: 0.45rem 0 0;
        padding-left: 1.15rem;
    }
    .data-assurance-box li {
        margin: 0.2rem 0;
    }
    .field-examples {
        color: var(--cr-muted);
        font-size: 0.95rem;
        font-style: italic;
        line-height: 1.45;
        margin-top: 0.45rem;
    }
    .field-examples.use-qty-examples {
        margin-top: 0.85rem;
    }
    .field-examples div + div {
        margin-top: 0.2rem;
    }
    .setup-panel {
        border: 1px solid var(--cr-border);
        border-radius: 8px;
        padding: 1rem;
        margin: 0.75rem 0 1.25rem;
        background: var(--cr-surface);
    }
    .setup-panel h3 {
        margin: 0 0 0.25rem !important;
    }
    .setup-panel p {
        margin: 0 0 0.85rem;
        color: var(--cr-muted);
    }
    .setup-intro {
        margin: 0 0 0.65rem !important;
        color: var(--cr-muted);
    }
    .setup-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(180px, 1fr));
        gap: 0.75rem;
        padding-bottom: 1rem;
    }
    .setup-step {
        border: 1px solid var(--cr-border);
        border-radius: 8px;
        padding: 0.8rem;
        min-height: 150px;
        display: flex;
        flex-direction: column;
        gap: 0.45rem;
        background: var(--cr-step-bg);
    }
    .setup-step.complete {
        border-color: var(--cr-step-complete-border);
        background: var(--cr-step-complete-bg);
    }
    .setup-step.todo {
        border-color: rgba(248, 113, 113, 0.42);
        background: #fff1f2;
    }
    .setup-step.current {
        border-color: var(--cr-step-current-border);
        box-shadow: 0 0 0 1px rgba(41, 210, 114, 0.18), 0 10px 22px rgba(29, 167, 89, 0.10);
        background: var(--cr-step-current-bg);
    }
    .setup-step.optional {
        border-color: var(--cr-step-optional-border);
        background: var(--cr-step-optional-bg);
    }
    .setup-status {
        width: fit-content;
        border-radius: 999px;
        padding: 0.1rem 0.45rem;
        font-size: 0.78rem;
        font-weight: 700;
        background: var(--cr-chip-bg);
        color: var(--cr-text);
    }
    .setup-step.current .setup-status {
        background: var(--cr-primary);
        color: #062d19;
    }
    .setup-step.todo .setup-status {
        background: #ffe4e6;
        color: #9f1239;
    }
    .setup-title {
        font-weight: 700;
        font-size: 1rem;
    }
    .setup-copy {
        color: var(--cr-muted);
        font-size: 0.92rem;
        line-height: 1.35;
        flex: 1;
    }
    .setup-where {
        color: var(--cr-link);
        display: inline-block;
        font-size: 0.9rem;
        font-weight: 700;
        margin-top: 0.2rem;
    }
    [class*="st-key-reset_get_started_checklist"] button {
        min-width: 13rem;
    }
    [class*="st-key-del_client_excl_"] button,
    [class*="st-key-del_patient_excl_"] button,
    [class*="st-key-del_excl_"] button,
    [class*="st-key-del_auto_patient_excl_"] button {
        background: transparent !important;
        border: 0 !important;
        box-shadow: none !important;
        color: #d92d20 !important;
        min-height: 2rem !important;
        min-width: 2rem !important;
        padding: 0 0.35rem !important;
    }
    [class*="st-key-del_client_excl_"] button:hover,
    [class*="st-key-del_patient_excl_"] button:hover,
    [class*="st-key-del_excl_"] button:hover,
    [class*="st-key-del_auto_patient_excl_"] button:hover {
        background: rgba(217, 45, 32, 0.08) !important;
        border-radius: 999px !important;
    }
    [class*="st-key-del_client_excl_"] button p,
    [class*="st-key-del_patient_excl_"] button p,
    [class*="st-key-del_excl_"] button p,
    [class*="st-key-del_auto_patient_excl_"] button p {
        color: #d92d20 !important;
        font-size: 1.55rem !important;
        font-weight: 700 !important;
        line-height: 1 !important;
        margin: 0 !important;
    }
    .auto-death-keyword-panel-title {
        color: var(--cr-text);
        font-weight: 800;
        margin-bottom: 0.18rem;
    }
    .auto-death-keyword-panel-copy {
        color: var(--cr-muted);
        font-size: 0.9rem;
        margin-bottom: 0.65rem;
    }
    .auto-death-keyword-chip {
        display: inline-flex;
        align-items: center;
        border: 1px solid rgba(41, 210, 114, 0.28);
        border-radius: 999px;
        background: #ecfdf3;
        color: #05603a;
        font-size: 0.92rem;
        font-weight: 700;
        line-height: 1.2;
        margin-top: 0.32rem;
        padding: 0.38rem 0.62rem;
    }
    .auto-death-patient-section-title {
        border-top: 1px solid var(--cr-border);
        color: var(--cr-text);
        font-weight: 800;
        margin-top: 1.25rem;
        padding-top: 1rem;
    }
    [class*="st-key-del_passaway_keyword_"] button {
        background: #ecfdf3 !important;
        border: 1px solid rgba(41, 210, 114, 0.28) !important;
        border-radius: 999px !important;
        box-shadow: none !important;
        color: #05603a !important;
        min-height: 1.9rem !important;
        min-width: 1.9rem !important;
        padding: 0 0.4rem !important;
    }
    [class*="st-key-del_passaway_keyword_"] button:hover {
        background: #d1fadf !important;
        border-color: rgba(29, 167, 89, 0.42) !important;
    }
    [class*="st-key-del_passaway_keyword_"] button p {
        color: #05603a !important;
        font-size: 1.05rem !important;
        font-weight: 800 !important;
        line-height: 1 !important;
        margin: 0 !important;
    }
    @media (max-width: 1100px) {
        .setup-grid { grid-template-columns: repeat(2, minmax(180px, 1fr)); }
    }
    @media (max-width: 700px) {
        .setup-grid { grid-template-columns: 1fr; }
    }
    .template-helper {
        border: 1px solid var(--cr-border);
        border-radius: 8px;
        padding: 1rem;
        margin: 0.75rem 0;
        background: var(--cr-surface);
    }
    .template-helper h4 {
        margin: 0 0 0.35rem !important;
    }
    .template-helper p {
        color: var(--cr-muted);
        margin: 0 0 0.65rem;
    }
    .placeholder-grid {
        display: grid;
        grid-template-columns: repeat(5, minmax(120px, 1fr));
        gap: 0.5rem;
    }
    .placeholder-chip {
        border: 1px solid var(--cr-step-current-border);
        border-radius: 8px;
        padding: 0.55rem;
        background: var(--cr-step-current-bg);
        font-size: 0.9rem;
    }
    .placeholder-chip code {
        display: block;
        margin-bottom: 0.25rem;
        color: var(--cr-link);
        font-weight: 700;
    }
    .column-help {
        color: var(--cr-muted);
        cursor: help;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        position: relative;
        width: 0.95rem;
        height: 0.95rem;
        border: 1px solid var(--cr-muted);
        border-radius: 999px;
        font-size: 0.68rem;
        font-weight: 700;
        line-height: 1;
        margin-left: 0.25rem;
        vertical-align: 0.05rem;
    }
    .column-help::after {
        background: #ffffff;
        border: 1px solid rgba(15,23,42,0.14);
        border-radius: 8px;
        box-shadow: 0 10px 24px rgba(15,23,42,0.18);
        color: #111827;
        content: attr(data-tooltip);
        display: none;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        font-size: 0.8rem;
        font-weight: 500;
        left: 50%;
        line-height: 1.35;
        max-width: 27rem;
        min-width: 15rem;
        padding: 0.55rem 0.7rem;
        position: absolute;
        text-align: left;
        bottom: calc(100% + 0.45rem);
        transform: translateX(-50%);
        white-space: normal;
        z-index: 9999;
    }
    .column-help:hover::after {
        display: block;
    }
    .field-label {
        font-size: 0.9rem;
        font-weight: 600;
        margin-bottom: 0.35rem;
    }
    .reminder-control-label {
        align-items: flex-start;
        display: flex;
        min-height: 2.25rem;
    }
    .cr-today-button-spacer {
        height: 2.6rem;
    }
    .st-key-reminders_jump_to_today button {
        height: 2.625rem;
        min-height: 2.625rem;
        min-width: 5.25rem;
        padding: 0 0.95rem;
        width: 5.25rem;
    }
    @media (max-width: 900px) {
        .reminder-control-label {
            min-height: auto;
        }
        .cr-today-button-spacer {
            height: 0;
        }
    }
    .cr-busy-overlay {
        align-items: center;
        background: rgba(246, 250, 247, 0.72);
        backdrop-filter: blur(2px);
        display: flex;
        inset: 0;
        justify-content: center;
        position: fixed;
        z-index: 2147483000;
    }
    .cr-busy-card {
        align-items: center;
        background: #ffffff;
        border: 1px solid rgba(41, 210, 114, 0.24);
        border-radius: 14px;
        box-shadow: 0 20px 56px rgba(15, 23, 42, 0.14);
        color: var(--cr-text);
        display: flex;
        flex-direction: column;
        gap: 0.75rem;
        min-width: min(22rem, calc(100vw - 2rem));
        padding: 1.25rem 1.45rem;
        text-align: center;
    }
    .cr-busy-spinner {
        animation: cr-spin 0.85s linear infinite;
        border: 4px solid rgba(41, 210, 114, 0.18);
        border-radius: 999px;
        border-top-color: var(--cr-primary);
        height: 2.75rem;
        width: 2.75rem;
    }
    .cr-busy-title {
        font-size: 1rem;
        font-weight: 800;
        line-height: 1.25;
    }
    .cr-busy-copy {
        color: var(--cr-muted);
        font-size: 0.88rem;
        line-height: 1.35;
        max-width: 19rem;
    }
    @keyframes cr-spin {
        to { transform: rotate(360deg); }
    }
    </style>
    ''',
    unsafe_allow_html=True,
)
st.markdown("""
<style>
.block-container {
    padding-top: 7rem !important;
}
</style>
""", unsafe_allow_html=True)


def render_busy_overlay(target, message: str, detail: str = ""):
    safe_message = html_lib.escape(str(message or "Working..."))
    safe_detail = html_lib.escape(str(detail or ""))
    detail_html = f"<div class='cr-busy-copy'>{safe_detail}</div>" if safe_detail else ""
    target.markdown(
        f"""
        <div class="cr-busy-overlay" role="status" aria-live="polite">
          <div class="cr-busy-card">
            <div class="cr-busy-spinner"></div>
            <div class="cr-busy-title">{safe_message}</div>
            {detail_html}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


@contextmanager
def busy_overlay(message: str, detail: str = ""):
    overlay_slot = st.empty()
    render_busy_overlay(overlay_slot, message, detail)
    try:
        yield overlay_slot
    finally:
        overlay_slot.empty()


def render_field_label(container, label: str, help_text: str, class_name: str = ""):
    safe_label = html_lib.escape(label)
    safe_help = html_lib.escape(help_text)
    safe_class = html_lib.escape(str(class_name or ""))
    classes = "field-label" + (f" {safe_class}" if safe_class else "")
    container.markdown(
        f"<div class='{classes}'>{safe_label} <span class='column-help' data-tooltip='{safe_help}'>?</span></div>",
        unsafe_allow_html=True,
    )


def safe_html_text(value) -> str:
    return html_lib.escape(str(value or ""))


def padded_html_text(value) -> str:
    return f"<div style='padding-top:8px;'>{safe_html_text(value)}</div>"


def patient_exclusion_label_html(client_name: str, patient_name: str) -> str:
    return (
        f"<div style='padding-top:8px;'>{safe_html_text(client_name)}"
        f" - {safe_html_text(patient_name)}</div>"
    )

# --------------------------------
# Defaults
# --------------------------------
DEFAULT_RULES = {
    "rabies": {"days": 365, "use_qty": False, "visible_text": "Rabies Vaccine"},
    "pch": {"days": 365, "use_qty": False, "visible_text": "Tricat Vaccine"},
    "dhppil": {"days": 365, "use_qty": False, "visible_text": "DHPPIL Vaccine"},
    "leukemia": {"days": 365, "use_qty": False, "visible_text": "Leukemia Vaccine"},
    "tricat": {"days": 365, "use_qty": False, "visible_text": "Tricat Vaccine"},
    "dental cat": {"days": 365, "use_qty": False, "visible_text": "Dental exam"},
    "groom": {"days": 90, "use_qty": False, "visible_text": "Groom"},
    "feliway": {"days": 60, "use_qty": True, "visible_text": "Feliway"},
    "dermoscent": {"days": 30, "use_qty": True, "visible_text": "Dermoscent"},
    "dental dog": {"days": 365, "use_qty": False, "visible_text": "Dental exam"},
    "dental descale": {"days": 365, "use_qty": False, "visible_text": "Dental exam"},
    "dental package": {"days": 365, "use_qty": False, "visible_text": "Dental exam"},
    "dental scale and polish": {"days": 365, "use_qty": False, "visible_text": "Dental exam"},
    "cardiac ultrasound": {"days": 365, "use_qty": False, "visible_text": "Repeat heart scan"},
    "ultrasound - cardiac": {"days": 365, "use_qty": False, "visible_text": "Repeat heart scan"},
    "caniverm": {"days": 90, "use_qty": False, "visible_text": "Caniverm"},
    "deworm": {"days": 90, "use_qty": False, "visible_text": "Deworming"},
    "milpro": {"days": 90, "use_qty": True, "visible_text": "Deworming"},
    "bravecto plus": {"days": 60, "use_qty": True, "visible_text": "Bravecto Plus"},
    "bravecto": {"days": 90, "use_qty": True, "visible_text": "Bravecto"},
    "frontline": {"days": 30, "use_qty": True, "visible_text": "Frontline"},
    "cardisure": {"days": 30, "use_qty": False, "visible_text": "Cardisure"},
    "vaccination": {"days": 365, "use_qty": False, "visible_text": "Vaccine(s)"},
    "revolution": {"days": 30, "use_qty": True, "visible_text": "Revolution"},
    "librela": {"days": 30, "use_qty": False, "visible_text": "Librela"},
    "cytopoint": {"days": 30, "use_qty": False, "visible_text": "Cytopoint"},
    "solensia": {"days": 30, "use_qty": False, "visible_text": "Solensia"},
    "samylin": {"days": 30, "use_qty": True, "visible_text": "Samylin"},
    "cystaid": {"days": 30, "use_qty": False, "visible_text": "Cystaid"},
    "kennel cough": {"days": 365, "use_qty": False, "visible_text": "Kennel Cough Vaccine"},
}

# Global default WA template (single source of truth)
DEFAULT_WA_TEMPLATE = (
    "Hi [Client Name], this is [Your Name] reminding you that "
    "[Pet Name] is due for their [Item] on the [Due Date]. "
    "Get in touch with us any time, and we look forward to hearing from you soon!"
)

# --------------------------------
# 🔐 Login authorisation & per-clinic settings persistence (Google Sheets)
# --------------------------------

# === CONFIGURATION ===
DEFAULT_SETTINGS_SHEET_ID = "1JQgF268JyHZZRHg0V-p3chBu5jhANIMnUvkb7M0Fxs8"  # ClinicReminders_Settings_Master Sheet ID
SETTINGS_SHEET_ID = config_value("SETTINGS_SHEET_ID", DEFAULT_SETTINGS_SHEET_ID)
SETTINGS_SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
REMEMBER_LOGIN_DAYS = 30
REMEMBER_LOGIN_QUERY_PARAM = "remember"
PASSWORD_HASH_ALGORITHM = "pbkdf2_sha256"
PASSWORD_HASH_ITERATIONS = 260_000
PASSWORD_SALT_BYTES = 16
PASSWORD_MIN_LENGTH = 12
COMMON_PASSWORD_KEYS = {
    "123456789012",
    "admin123456",
    "changeme123456",
    "clinicreminders",
    "letmein123456",
    "password",
    "password123",
    "password1234",
    "password12345",
    "password123456",
    "qwerty123456",
    "welcome123456",
}
LOGIN_TRACKER_EVENTS = {"login", "google_login", "remembered_login"}
AUTH_ABUSE_STATE_KEY = "_auth_abuse_controls"
LOGIN_FAILURE_LIMIT = 5
LOGIN_FAILURE_WINDOW_SECONDS = 10 * 60
LOGIN_LOCKOUT_SECONDS = 15 * 60
SIGNUP_ATTEMPT_LIMIT = 3
SIGNUP_ATTEMPT_WINDOW_SECONDS = 60 * 60
SIGNUP_LOCKOUT_SECONDS = 60 * 60

# === DEV AUTO-LOGIN ===
DEV_AUTO_LOGIN = False
DEV_AUTO_LOGIN_CREDENTIALS = ("", "")
AUTO_LOGIN_ALLOWED_USERNAME = "PatTest"


def auto_login_allowed(username: str) -> bool:
    return (
        str(username or "").strip().lower()
        == AUTO_LOGIN_ALLOWED_USERNAME.lower()
    )


def _auth_abuse_state(state=None) -> dict:
    state = st.session_state if state is None else state
    return state.setdefault(
        AUTH_ABUSE_STATE_KEY,
        {
            "login": {},
            "signup": {"attempts": [], "locked_until": 0.0},
        },
    )


def _timestamp(now=None) -> float:
    if now is None:
        return time.time()
    if isinstance(now, datetime):
        return now.timestamp()
    return float(now)


def _retry_after_seconds(locked_until: float, now: float) -> int:
    return max(0, int(locked_until - now + 0.999))


def _recent_timestamps(
    values: list,
    now: float,
    window_seconds: int,
) -> list[float]:
    cutoff = now - window_seconds
    return [float(value) for value in values if float(value) >= cutoff]


def login_attempt_allowed(
    username: str,
    now=None,
    state=None,
) -> tuple[bool, int]:
    abuse_state = _auth_abuse_state(state)
    key = normalize_clinic_id_key(username) or "<blank>"
    entry = abuse_state["login"].setdefault(
        key,
        {"failures": [], "locked_until": 0.0},
    )
    current = _timestamp(now)
    locked_until = float(entry.get("locked_until", 0.0) or 0.0)
    if locked_until > current:
        return False, _retry_after_seconds(locked_until, current)

    entry["failures"] = _recent_timestamps(
        entry.get("failures", []),
        current,
        LOGIN_FAILURE_WINDOW_SECONDS,
    )
    return True, 0


def record_failed_login_attempt(username: str, now=None, state=None) -> None:
    abuse_state = _auth_abuse_state(state)
    key = normalize_clinic_id_key(username) or "<blank>"
    entry = abuse_state["login"].setdefault(
        key,
        {"failures": [], "locked_until": 0.0},
    )
    current = _timestamp(now)
    failures = _recent_timestamps(
        entry.get("failures", []),
        current,
        LOGIN_FAILURE_WINDOW_SECONDS,
    )
    failures.append(current)
    entry["failures"] = failures
    if len(failures) >= LOGIN_FAILURE_LIMIT:
        entry["locked_until"] = current + LOGIN_LOCKOUT_SECONDS


def record_successful_login_attempt(username: str, state=None) -> None:
    abuse_state = _auth_abuse_state(state)
    abuse_state["login"].pop(
        normalize_clinic_id_key(username) or "<blank>",
        None,
    )


def signup_attempt_allowed(now=None, state=None) -> tuple[bool, int]:
    abuse_state = _auth_abuse_state(state)
    entry = abuse_state.setdefault(
        "signup",
        {"attempts": [], "locked_until": 0.0},
    )
    current = _timestamp(now)
    locked_until = float(entry.get("locked_until", 0.0) or 0.0)
    if locked_until > current:
        return False, _retry_after_seconds(locked_until, current)

    attempts = _recent_timestamps(
        entry.get("attempts", []),
        current,
        SIGNUP_ATTEMPT_WINDOW_SECONDS,
    )
    entry["attempts"] = attempts
    if len(attempts) >= SIGNUP_ATTEMPT_LIMIT:
        entry["locked_until"] = current + SIGNUP_LOCKOUT_SECONDS
        return False, SIGNUP_LOCKOUT_SECONDS
    return True, 0


def record_signup_attempt(now=None, state=None) -> None:
    abuse_state = _auth_abuse_state(state)
    entry = abuse_state.setdefault(
        "signup",
        {"attempts": [], "locked_until": 0.0},
    )
    current = _timestamp(now)
    attempts = _recent_timestamps(
        entry.get("attempts", []),
        current,
        SIGNUP_ATTEMPT_WINDOW_SECONDS,
    )
    attempts.append(current)
    entry["attempts"] = attempts


def auth_retry_message(action: str, retry_after_seconds: int) -> str:
    minutes = max(1, int((retry_after_seconds + 59) / 60))
    unit = "minute" if minutes == 1 else "minutes"
    return f"Too many {action} attempts. Try again in about {minutes} {unit}."

# === GOOGLE DRIVE CONFIG ===
@st.cache_resource(show_spinner=False)
def get_drive_service():
    # Use Streamlit secrets first, fallback to local json file
    try:
        creds_dict = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=DRIVE_SCOPE)
    except Exception:
        creds = Credentials.from_service_account_file("google-credentials.json", scopes=DRIVE_SCOPE)

    return build("drive", "v3", credentials=creds)

def drive_download_bytes(file_id: str, clinic_id: str | None = None, current_file_id: str | None = None) -> bytes:
    if clinic_id is not None:
        require_clinic_dataset_file_access(clinic_id, file_id, current_file_id=current_file_id)
    service = get_drive_service()
    try:
        request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
        fh = BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return fh.getvalue()
    except HttpError as e:
        record_error_tracker_event(
            "drive_download_failed",
            stage="drive_download_bytes",
            error=e,
            source="drive_download_bytes",
        )
        st.error("Drive download failed. Please try again or contact support.")
        raise

def drive_query_literal(value: str) -> str:
    escaped = str(value or "").replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"

def drive_find_file_id_by_name(filename: str, folder_id: str) -> str:
    if not filename or not folder_id:
        return ""
    service = get_drive_service()
    query = (
        f"name = {drive_query_literal(filename)} "
        f"and {drive_query_literal(folder_id)} in parents "
        "and trashed = false"
    )
    response = service.files().list(
        q=query,
        fields="files(id,name,modifiedTime)",
        orderBy="modifiedTime desc",
        pageSize=1,
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()
    files = response.get("files", []) or []
    return str(files[0].get("id", "")).strip() if files else ""
        
def ensure_min_canonical_schema(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col, default in {
        "ChargeDate": pd.NaT,
        "Client Name": "",
        "Animal Name": "",
        "Item Name": "",
        "Qty": 1,
        "Amount": 0,
    }.items():
        if col not in df.columns:
            df[col] = default
    return df
    
def normalize_key_series(s, index=None) -> pd.Series:
    """
    Robust text normalisation for key columns.
    Avoids Arrow-backed .str.replace(regex=True) issues by using Python regex per cell.
    """
    if isinstance(s, pd.DataFrame):
        s = s.iloc[:, 0]
    if s is None:
        s = pd.Series("", index=index)

    s = pd.Series(s, index=getattr(s, "index", index), copy=False)

    def _clean_one(x):
        if pd.isna(x):
            return ""
        x = unicodedata.normalize("NFKC", str(x)).lower()
        x = re.sub(r"[\u00A0\u200B]", "", x)
        x = re.sub(r"\s+", " ", x).strip()
        return x

    return s.map(_clean_one)


def billed_item_duplicate_identity(df: pd.DataFrame) -> tuple[pd.DataFrame | None, pd.Series]:
    key_columns = ["ChargeDate", "Client Name", "Animal Name", "Item Name"]
    if df is None or getattr(df, "empty", True) or any(col not in df.columns for col in key_columns):
        return None, pd.Series(False, index=getattr(df, "index", pd.Index([])), dtype=bool)

    charge_dates = parse_dates(df["ChargeDate"]).dt.normalize()
    identity = pd.DataFrame(
        {
            "ChargeDate": charge_dates.dt.strftime("%Y-%m-%d").fillna(""),
            "Client Name": normalize_key_series(df["Client Name"], index=df.index),
            "Animal Name": normalize_key_series(df["Animal Name"], index=df.index),
            "Item Name": normalize_key_series(df["Item Name"], index=df.index),
        },
        index=df.index,
    )
    complete = charge_dates.notna()
    for col in ["Client Name", "Animal Name", "Item Name"]:
        complete = complete & identity[col].ne("")
    return identity, complete.fillna(False)


def drop_duplicate_billed_item_rows(df: pd.DataFrame, keep: str = "last") -> pd.DataFrame:
    """
    Collapse duplicate billed-item rows across overlapping uploads.
    A duplicate is the same billed date, owner, animal, and item.
    """
    if df is None or getattr(df, "empty", True):
        return df

    identity, complete = billed_item_duplicate_identity(df)
    if identity is None or not complete.any():
        return df.copy()

    drop_rows = np.zeros(len(df), dtype=bool)
    complete_values = complete.to_numpy(dtype=bool)
    drop_rows[complete_values] = identity.loc[complete].duplicated(keep=keep).to_numpy(dtype=bool)
    if not drop_rows.any():
        return df.copy()
    return df.loc[~drop_rows].copy().reset_index(drop=True)


def sanitize_working_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Single entry-point sanitiser for any dataframe entering app state.
    """
    if df is None:
        return df

    df = df.copy()
    df = drop_duplicate_columns(df)
    df = ensure_min_canonical_schema(df)

    # force plain pandas/object-safe strings for key columns
    for col in ["Client Name", "Animal Name", "Item Name"]:
        if col in df.columns:
            if isinstance(df[col], pd.DataFrame):
                df[col] = df[col].iloc[:, 0]
            df[col] = df[col].astype("string[python]").fillna("")

    if "ChargeDate" in df.columns:
        df["ChargeDate"] = parse_dates(df["ChargeDate"])

    if "Qty" in df.columns:
        df["Qty"] = pd.to_numeric(df["Qty"], errors="coerce").fillna(1).astype(int)

    if "Amount" in df.columns:
        df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce").fillna(0)

    return drop_duplicate_billed_item_rows(df)
    
def load_shared_dataset_for_clinic():
    """
    If the clinic has a DatasetFileId stored in the settings sheet,
    download it from Drive, process it, and set st.session_state['working_df'].
    """
    reset_uploaded_data_state(clear_cache=False)
    clinic_id = st.session_state.get("clinic_id")
    if not clinic_id:
        return
    clinic_id = require_authenticated_tenant_access(clinic_id)

    rec = None
    try:
        sheet, headers, row_idx, row_values = get_fresh_settings_row_values(clinic_id)
        rec = {
            header: row_values[idx] if idx < len(row_values) else ""
            for idx, header in enumerate(headers)
        }
    except Exception:
        sheet = get_settings_sheet()
        records = sheet.get_all_records()
        clinic_key = normalize_clinic_id_key(clinic_id)
        rec = next((r for r in records if normalize_clinic_id_key(r.get("ClinicID", "")) == clinic_key), None)
    if not rec:
        return

    file_id = str(rec.get(SHEET_COL_DATASET_FILE_ID, "")).strip()
    if not file_id:
        history = normalize_dataset_upload_history(st.session_state.get("dataset_upload_history", []))
        if history:
            recovered_name = str(rec.get(SHEET_COL_DATASET_FILE_NAME, "")).strip() or f"{clinic_id}_shared_dataset.csv"
            try:
                recovered_file_id = drive_find_file_id_by_name(recovered_name, DATASETS_FOLDER_ID)
            except Exception as e:
                recovered_file_id = ""
                record_error_tracker_event(
                    "shared_dataset_pointer_recovery_failed",
                    stage="load_shared_dataset_for_clinic",
                    error=e,
                    source="load_shared_dataset_for_clinic",
                )
            if recovered_file_id:
                try:
                    update_clinic_dataset_pointer(clinic_id, recovered_file_id, recovered_name)
                    file_id = recovered_file_id
                    rec[SHEET_COL_DATASET_FILE_ID] = recovered_file_id
                    rec[SHEET_COL_DATASET_FILE_NAME] = recovered_name
                    st.session_state["shared_dataset_error"] = None
                    record_dataset_tracker_event(
                        "dataset_pointer_recovered",
                        "success",
                        file_name=recovered_name,
                        drive_file_id=recovered_file_id,
                        message="Recovered missing saved dataset pointer from Drive",
                        source="load_shared_dataset_for_clinic",
                    )
                except Exception as e:
                    file_id = ""
                    record_error_tracker_event(
                        "shared_dataset_pointer_recovery_failed",
                        stage="load_shared_dataset_for_clinic",
                        error=e,
                        source="load_shared_dataset_for_clinic",
                    )
            if not file_id:
                st.session_state["shared_dataset_loaded"] = False
                st.session_state["shared_dataset_error"] = (
                    "The saved data record is missing its file link. Clear clinic data or upload the file again."
                )
                return
        else:
            return  # no shared dataset published yet

    load_started = time.perf_counter()
    try:
        with busy_overlay("Loading saved clinic data", "Getting the latest saved data for this clinic."):
            file_bytes = drive_download_bytes(file_id, clinic_id=clinic_id, current_file_id=file_id)

            # Reuse your existing pipeline so schema normalization still happens
            # Filename is just for detect logic; use stored name if present, else default
            filename = rec.get(SHEET_COL_DATASET_FILE_NAME, "shared_dataset.csv") or "shared_dataset.csv"
            df, pms_name, amount_col = process_file(file_bytes, filename)

            st.session_state["working_df"] = sanitize_working_df(df)
            st.session_state["data_version"] = st.session_state.get("data_version", 0) + 1  # invalidate downstream caches
            st.session_state["shared_dataset_loaded"] = True
            st.session_state["shared_dataset_name"] = filename
            st.session_state["shared_dataset_updated_at"] = rec.get(SHEET_COL_DATASET_UPDATED_AT, "")
            remember_shared_dataset_loaded_for_current_pointer(clinic_id)
            load_duration_ms = (time.perf_counter() - load_started) * 1000
            if load_duration_ms >= PERFORMANCE_TRACKER_SLOW_LOAD_MS:
                record_performance_tracker_event(
                    "shared_dataset_load",
                    load_duration_ms,
                    rows=len(df),
                    status="slow",
                    message=filename,
                    source="load_shared_dataset_for_clinic",
                )

    except Exception as e:
        st.session_state["shared_dataset_loaded"] = False
        st.session_state["shared_dataset_error"] = "Please try again or contact support."
        record_error_tracker_event(
            "shared_dataset_load_failed",
            stage="load_shared_dataset_for_clinic",
            error=e,
            source="load_shared_dataset_for_clinic",
        )
        record_performance_tracker_event(
            "shared_dataset_load",
            (time.perf_counter() - load_started) * 1000,
            status="error",
            message=str(e),
            source="load_shared_dataset_for_clinic",
        )


def shared_dataset_load_attempt_token(clinic_id: str) -> str:
    """Tokenize the saved-data state so a newly uploaded dataset can be loaded in this session."""
    history = st.session_state.get("dataset_upload_history", [])
    try:
        history = normalize_dataset_upload_history(history)
    except Exception:
        pass
    history_blob = json.dumps(history, sort_keys=True, default=str)
    pointer_blob = ""
    try:
        sheet, headers, _ = _get_settings_row_for_clinic(clinic_id)
        row_values = get_cached_settings_row_values(clinic_id)
        if row_values:
            file_id_idx = headers.index(SHEET_COL_DATASET_FILE_ID)
            name_idx = headers.index(SHEET_COL_DATASET_FILE_NAME)
            updated_idx = headers.index(SHEET_COL_DATASET_UPDATED_AT)
            pointer_blob = "|".join(
                str(row_values[idx]).strip() if idx < len(row_values) else ""
                for idx in (file_id_idx, name_idx, updated_idx)
            )
    except Exception:
        pointer_blob = ""
    token = hashlib.md5(f"{history_blob}|{pointer_blob}".encode("utf-8")).hexdigest()
    return f"{clinic_id}:{token}"


def ensure_shared_dataset_loaded_for_session():
    clinic_id = st.session_state.get("clinic_id")
    if not clinic_id or not st.session_state.get("logged_in") or st.session_state.get("working_df") is not None:
        return
    attempt_token = shared_dataset_load_attempt_token(clinic_id)
    if st.session_state.get("_shared_dataset_load_attempted_for") == attempt_token:
        return
    st.session_state["_shared_dataset_load_attempted_for"] = attempt_token
    load_shared_dataset_for_clinic()


def remember_shared_dataset_loaded_for_current_pointer(clinic_id: str) -> None:
    try:
        st.session_state["_shared_dataset_loaded_for"] = shared_dataset_load_attempt_token(clinic_id)
    except Exception:
        st.session_state.pop("_shared_dataset_loaded_for", None)


def shared_dataset_reload_needed_for_clinic(clinic_id: str) -> bool:
    if not clinic_id or st.session_state.get("working_df") is None:
        return True
    try:
        current_token = shared_dataset_load_attempt_token(clinic_id)
    except Exception:
        return False
    return st.session_state.get("_shared_dataset_loaded_for") != current_token

def drive_upsert_csv_bytes(
    file_bytes: bytes,
    filename: str,
    folder_id: str,
    existing_file_id: str | None,
    clinic_id: str | None = None,
) -> str:
    """
    If existing_file_id is provided -> update that file in-place.
    Else -> create a new file in folder_id.
    Uses resumable upload to reduce BrokenPipe issues.
    Returns the fileId.
    """
    if clinic_id is not None:
        require_authenticated_tenant_access(clinic_id)
        if existing_file_id:
            require_clinic_dataset_file_access(clinic_id, existing_file_id)
    service = get_drive_service()
    media = MediaIoBaseUpload(BytesIO(file_bytes), mimetype="text/csv", resumable=True)

    if existing_file_id:
        update_body: dict[str, object] = {}
        if clinic_id is not None:
            update_body["appProperties"] = {"clinic_id": require_authenticated_tenant_access(clinic_id)}
        req = service.files().update(
            fileId=existing_file_id,
            body=update_body,
            media_body=media,
            supportsAllDrives=True,
        )
    else:
        create_body: dict[str, object] = {"name": filename, "parents": [folder_id]}
        if clinic_id is not None:
            create_body["appProperties"] = {"clinic_id": require_authenticated_tenant_access(clinic_id)}
        req = service.files().create(
            body=create_body,
            media_body=media,
            fields="id",
            supportsAllDrives=True,
        )

    resp = None
    while resp is None:
        status, resp = req.next_chunk()

    return resp["id"]

def drive_check_folder_access(folder_id: str):
    service = get_drive_service()
    try:
        meta = service.files().get(
            fileId=folder_id,
            fields="id,name,mimeType,driveId",
            supportsAllDrives=True,
        ).execute()
        st.success(f"Drive folder OK: {meta.get('name')} ({meta.get('id')})")

        # List children as a stronger check
        resp = service.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            fields="files(id,name,mimeType), nextPageToken",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
            pageSize=5,
        ).execute()
        st.caption(f"Folder children visible: {len(resp.get('files', []))}")
    except HttpError as e:
        record_error_tracker_event(
            "drive_folder_access_failed",
            stage="drive_check_folder_access",
            error=e,
            source="drive_check_folder_access",
        )
        st.error("Cannot access the Drive folder. Please check configuration or contact support.")
        raise
        
def get_drive_service_uncached():
    try:
        creds_dict = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=DRIVE_SCOPE)
    except Exception:
        creds = Credentials.from_service_account_file("google-credentials.json", scopes=DRIVE_SCOPE)

    return build("drive", "v3", credentials=creds, cache_discovery=False)

def build_vetport_rowkey(df: pd.DataFrame) -> pd.Series:
    # Build after Vetport normalization (so 1 vs 1.0 etc is stable)
    key_cols = [
        "Invoice No",
        "Plan Item ID",
        "ChargeDate",
        "Client ID",
        "Patient ID",
        "Plan Item Amount",
        "Plan Item Quantity",
    ]
    for c in key_cols:
        if c not in df.columns:
            df[c] = ""
    return df[key_cols].astype(str).agg("|".join, axis=1)

def merge_dedupe(existing_df: pd.DataFrame, new_df: pd.DataFrame) -> pd.DataFrame:
    # Only Vetport for now (since that’s your current real use case)
    ex = existing_df.copy()
    nw = new_df.copy()

    ex["_RowKey"] = build_vetport_rowkey(ex)
    nw["_RowKey"] = build_vetport_rowkey(nw)

    merged = pd.concat([ex, nw], ignore_index=True)
    merged = merged.drop_duplicates(subset=["_RowKey"], keep="last").drop(columns=["_RowKey"])

    # Recompute ChargeDate if needed (it should already exist)
    return merged

def update_clinic_dataset_pointer(clinic_id: str, file_id: str, filename: str):
    clinic_id = require_authenticated_tenant_access(clinic_id)
    updated_at = utc_now_iso()
    update_authorized_settings_row_fields(
        clinic_id,
        {
            SHEET_COL_DATASET_FILE_ID: file_id,
            SHEET_COL_DATASET_FILE_NAME: filename,
            SHEET_COL_DATASET_UPDATED_AT: updated_at,
        },
        SETTINGS_REQUIRED_COLUMNS,
    )
    _, fresh_headers, _, fresh_row = get_authorized_fresh_settings_row_values(clinic_id)
    file_id_idx = fresh_headers.index(SHEET_COL_DATASET_FILE_ID)
    saved_file_id = str(fresh_row[file_id_idx]).strip() if len(fresh_row) > file_id_idx else ""
    if saved_file_id != str(file_id).strip():
        raise RuntimeError("Saved dataset could not be linked to this clinic. Please try the upload again.")
    update_cached_settings_row_fields(
        clinic_id,
        {
            SHEET_COL_DATASET_FILE_ID: file_id,
            SHEET_COL_DATASET_FILE_NAME: filename,
            SHEET_COL_DATASET_UPDATED_AT: updated_at,
        },
    )
    return updated_at

# ============================================================
# ✅ Dataset Publishing (Refactor #1)
#   - Single orchestrator for publishing clinic datasets
#   - Helpers to fetch existing pointer + load existing dataset
# ============================================================
def gspread_api_error_status(error) -> int | None:
    status = getattr(error, "code", None)
    if status is None:
        status = getattr(getattr(error, "response", None), "status_code", None)
    if status is None:
        status = getattr(getattr(error, "resp", None), "status", None)
    try:
        return int(status)
    except (TypeError, ValueError):
        return None

def _gspread_retry(fn, *args, **kwargs):
    """
    Retries common transient Google Sheets errors (429/500/502/503/504).
    Keeps other errors as-is so you still see real permission/config issues.
    """
    max_tries = 3
    for attempt in range(max_tries):
        try:
            return fn(*args, **kwargs)
        except APIError as e:
            status = gspread_api_error_status(e)

            # Retry only transient/quota-ish errors
            if status in (429, 500, 502, 503, 504):
                sleep = min(4, (0.75 * (2 ** attempt)) + random.random())
                time.sleep(sleep)
                continue

            # Not transient -> raise (likely 403 perms, 400 bad request, etc.)
            raise

    # If we exhausted retries, raise last error
    return fn(*args, **kwargs)

def get_existing_dataset_pointer(clinic_id: str) -> tuple[str, str]:
    """
    Returns (existing_file_id, existing_filename) using a single row read.
    """
    try:
        sheet, headers, row_idx = _get_settings_row_for_clinic(clinic_id)
        headers = ensure_settings_sheet_columns(sheet, headers, SETTINGS_REQUIRED_COLUMNS)
        current_row = _gspread_retry(sheet.row_values, row_idx)
        clinic_ix = headers.index("ClinicID")
        fileid_ix = headers.index(SHEET_COL_DATASET_FILE_ID)
        fname_ix  = headers.index(SHEET_COL_DATASET_FILE_NAME)
    except (ValueError, IndexError):
        return "", ""

    if len(current_row) <= max(clinic_ix, fileid_ix, fname_ix):
        return "", ""
    if str(current_row[clinic_ix]).strip().lower() != str(clinic_id or "").strip().lower():
        return "", ""
    return str(current_row[fileid_ix]).strip(), str(current_row[fname_ix]).strip()

def load_existing_shared_df(file_id: str, filename: str, clinic_id: str | None = None) -> pd.DataFrame | None:
    """
    Loads an existing shared dataset from Drive (if file_id exists),
    then normalizes it through process_file so schema matches.
    Returns None if no file_id.
    """
    if not file_id:
        return None

    existing_bytes = drive_download_bytes(file_id, clinic_id=clinic_id, current_file_id=file_id)

    # Normalize through your pipeline to guarantee canonical columns
    df_existing, _, _ = process_file(existing_bytes, filename or "shared_dataset.csv")
    df_existing = sanitize_working_df(df_existing)

    # Optional: drop debug columns if present
    df_existing = df_existing.drop(columns=["_ChargeDate_raw"], errors="ignore")

    # If it loads but is empty, treat as None for merge logic
    if df_existing is None or getattr(df_existing, "empty", True):
        return None

    return df_existing

def dataset_date_bounds(df: pd.DataFrame) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    if df is None or getattr(df, "empty", True) or "ChargeDate" not in df.columns:
        return None, None

    dates = parse_dates(df["ChargeDate"])
    dmin = dates.min()
    dmax = dates.max()
    if pd.isna(dmin) or pd.isna(dmax):
        return None, None
    return dmin, dmax

def format_date_bound(d: pd.Timestamp | None) -> str:
    return d.strftime("%d %b %Y") if d is not None and pd.notna(d) else "-"

def parse_history_date(value) -> pd.Timestamp | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.normalize()

def parse_history_int(value) -> int:
    if value in (None, ""):
        return 0
    try:
        if pd.isna(value):
            return 0
    except (TypeError, ValueError):
        pass
    try:
        return int(value)
    except (TypeError, ValueError):
        pass
    try:
        return int(float(str(value).strip().replace(",", "")))
    except (TypeError, ValueError):
        return 0


def parse_history_row_count(entry: dict) -> int:
    if not isinstance(entry, dict):
        return 0
    candidates = [
        parse_history_int(entry.get(key))
        for key in ("rows", "Rows", "row_count", "RowCount", "Row Count")
        if key in entry
    ]
    for count in candidates:
        if count > 0:
            return count
    return candidates[0] if candidates else 0


def format_pms_display_name(value) -> str:
    name = str(value or "").strip()
    if not name:
        return "-"
    display_names = {
        "vetport": "VetPORT",
        "ezyvet": "ezyVet",
        "xpress": "Xpress",
        "canonical csv": "Canonical CSV",
    }
    return display_names.get(name.lower(), name)

def normalize_dataset_upload_history(history) -> list[dict]:
    rows = []
    if not isinstance(history, list):
        return rows
    for entry in history:
        if not isinstance(entry, dict):
            continue
        file_name = str(entry.get("file_name") or entry.get("File name") or entry.get("Dataset") or "").strip()
        if not file_name:
            continue
        from_date = parse_history_date(entry.get("from") or entry.get("From"))
        to_date = parse_history_date(entry.get("to") or entry.get("To"))
        rows.append({
            "file_name": file_name,
            "pms": format_pms_display_name(entry.get("pms") or entry.get("PMS") or "-"),
            "rows": parse_history_row_count(entry),
            "from": from_date.strftime("%Y-%m-%d") if from_date is not None else "",
            "to": to_date.strftime("%Y-%m-%d") if to_date is not None else "",
            "status": str(entry.get("status") or entry.get("Status") or "Saved").strip() or "Saved",
        })
    return rows

def upload_summary_rows_to_history(summary_rows: list[dict], status: str = "Saved") -> list[dict]:
    return normalize_dataset_upload_history([
        {
            "file_name": row.get("File name", ""),
            "pms": row.get("PMS", ""),
            "rows": row.get("Rows", 0),
            "from": row.get("From", ""),
            "to": row.get("To", ""),
            "status": status,
        }
        for row in summary_rows
    ])

def merge_dataset_upload_history(
    existing_history,
    new_history,
    replace_overlapping_dates: bool,
    upload_min: pd.Timestamp | None,
    upload_max: pd.Timestamp | None,
) -> list[dict]:
    existing = normalize_dataset_upload_history(existing_history)
    incoming = normalize_dataset_upload_history(new_history)
    if replace_overlapping_dates and upload_min is not None and upload_max is not None:
        existing = [
            row for row in existing
            if not date_ranges_overlap(
                parse_history_date(row.get("from")),
                parse_history_date(row.get("to")),
                upload_min,
                upload_max,
            )
        ]
    merged = existing + incoming
    deduped: list[dict] = []
    seen_keys: set[tuple[str, str, str, str]] = set()
    for row in reversed(merged):
        key = (
            str(row.get("file_name", "")).strip().casefold(),
            str(row.get("pms", "")).strip().casefold(),
            str(row.get("from", "")).strip(),
            str(row.get("to", "")).strip(),
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(row)
    return list(reversed(deduped))

def dataset_history_date_bounds(rows: list[dict]) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    starts = [parse_history_date(row.get("from")) for row in rows]
    ends = [parse_history_date(row.get("to")) for row in rows]
    starts = [d for d in starts if d is not None]
    ends = [d for d in ends if d is not None]
    if not starts or not ends:
        return None, None
    return min(starts), max(ends)

def max_missing_days_between_uploads(rows: list[dict]) -> int:
    ranges = []
    for row in rows:
        start = parse_history_date(row.get("from"))
        end = parse_history_date(row.get("to"))
        if start is None or end is None:
            continue
        ranges.append((start, end))
    if len(ranges) < 2:
        return 0

    ranges.sort(key=lambda item: item[0])
    _, current_end = ranges[0]
    max_gap = 0
    for start, end in ranges[1:]:
        gap_days = (start - current_end).days - 1
        if gap_days > max_gap:
            max_gap = gap_days
        if end > current_end:
            current_end = end
    return max(0, max_gap)

def date_ranges_cover_window(
    rows: list[dict],
    required_start: pd.Timestamp,
    required_end: pd.Timestamp,
) -> bool:
    ranges = []
    for row in rows:
        start = parse_history_date(row.get("from"))
        end = parse_history_date(row.get("to"))
        if start is None or end is None:
            continue
        ranges.append((start, end))
    if not ranges:
        return False

    ranges.sort(key=lambda item: item[0])
    covered_until = required_start - pd.Timedelta(days=1)
    for start, end in ranges:
        if end < required_start:
            continue
        if start > covered_until + pd.Timedelta(days=1):
            return False
        if end > covered_until:
            covered_until = end
        if covered_until >= required_end:
            return True
    return False

def dataset_summary_checks(rows: list[dict]) -> list[dict]:
    normalized_rows = normalize_dataset_upload_history(rows)
    pms_values = [str(row.get("pms", "")).strip() for row in normalized_rows if str(row.get("pms", "")).strip()]
    unsupported_pms = {"", "-", "unknown", "undetected", "csv"}
    supported_pms = bool(pms_values) and all(pms.lower() not in unsupported_pms for pms in pms_values)
    same_pms = len({pms.lower() for pms in pms_values}) <= 1
    today = pd.Timestamp(user_today())
    impact_start = today - pd.Timedelta(days=365)
    impact_end = today - pd.Timedelta(days=29)
    has_impact_window = date_ranges_cover_window(normalized_rows, impact_start, impact_end)
    max_gap = max_missing_days_between_uploads(normalized_rows)
    no_large_gaps = max_gap < 3
    return [
        {
            "good": supported_pms and same_pms,
            "text": "Same supported PMS" if supported_pms and same_pms else "Upload formats need attention",
        },
        {
            "good": has_impact_window,
            "text": (
                "30-365 day reminder window covered"
                if has_impact_window
                else "30-365 day reminder window needs data"
            ),
        },
        {
            "good": no_large_gaps,
            "text": "No 3+ day gaps between uploads" if no_large_gaps else f"{max_gap} day gap between uploads",
        },
    ]


def dataset_summary_issue_count(rows: list[dict]) -> int:
    normalized_rows = normalize_dataset_upload_history(rows)
    if not normalized_rows:
        return 0
    return sum(1 for check in dataset_summary_checks(normalized_rows) if not check.get("good"))


def dataset_summary_checks_html(rows: list[dict]) -> str:
    checks = dataset_summary_checks(rows)
    check_items = []
    for check in checks:
        status_class = "good" if check.get("good") else "bad"
        icon = "✅" if check.get("good") else "⚠️"
        text = html_lib.escape(str(check.get("text", "")))
        check_items.append(
            f"<div class='dataset-check {status_class}'>{icon} {text}</div>"
        )
    return f"<div class='dataset-check-grid'>{''.join(check_items)}</div>"


def render_dataset_summary_checks(rows: list[dict]):
    normalized_rows = normalize_dataset_upload_history(rows)
    if not normalized_rows:
        return
    st.markdown(dataset_summary_checks_html(normalized_rows), unsafe_allow_html=True)


def date_ranges_overlap(
    first_min: pd.Timestamp | None,
    first_max: pd.Timestamp | None,
    second_min: pd.Timestamp | None,
    second_max: pd.Timestamp | None,
) -> bool:
    if any(d is None or pd.isna(d) for d in [first_min, first_max, second_min, second_max]):
        return False
    return first_min <= second_max and second_min <= first_max


def dataset_history_row_overlaps_other(rows: list[dict], row_idx: int) -> bool:
    normalized_rows = normalize_dataset_upload_history(rows)
    if row_idx < 0 or row_idx >= len(normalized_rows):
        return False
    target = normalized_rows[row_idx]
    target_start = parse_history_date(target.get("from"))
    target_end = parse_history_date(target.get("to"))
    if target_start is None or target_end is None:
        return False
    for idx, other in enumerate(normalized_rows):
        if idx == row_idx:
            continue
        if date_ranges_overlap(
            target_start,
            target_end,
            parse_history_date(other.get("from")),
            parse_history_date(other.get("to")),
        ):
            return True
    return False

def merge_dataset_update(
    existing_df: pd.DataFrame | None,
    new_df: pd.DataFrame,
    replace_overlapping_dates: bool = False,
) -> pd.DataFrame:
    if existing_df is None or getattr(existing_df, "empty", True):
        return drop_duplicate_billed_item_rows(new_df)

    existing = existing_df.copy()
    new = new_df.copy()

    if replace_overlapping_dates:
        new_min, new_max = dataset_date_bounds(new)
        if new_min is not None and new_max is not None and "ChargeDate" in existing.columns:
            existing_dates = parse_dates(existing["ChargeDate"])
            keep_existing = existing_dates.isna() | (existing_dates < new_min) | (existing_dates > new_max)
            existing = existing.loc[keep_existing].copy()

    merged = pd.concat([existing, new], ignore_index=True, sort=False)
    merged = drop_duplicate_billed_item_rows(merged, keep="last")
    if "ChargeDate" in merged.columns:
        merged["_sort_charge_date"] = parse_dates(merged["ChargeDate"])
        merged = (
            merged.sort_values("_sort_charge_date", kind="mergesort")
            .drop(columns=["_sort_charge_date"])
            .reset_index(drop=True)
        )
    return merged


def publish_dataset_for_clinic(
    clinic_id: str,
    new_df: pd.DataFrame,
    datasets_folder_id: str,
    replace_overlapping_dates: bool = False,
    existing_file_id: str | None = None,
    existing_name: str | None = None,
    existing_df: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, str, str]:
    """
    Save an upload for the whole clinic:
      1) fetch existing dataset pointer from settings sheet
      2) load existing shared dataset from Drive (if any)
      3) append new dates, or replace the uploaded date range when confirmed
      4) upload merged CSV to Drive (new file each publish)
      5) update dataset pointer columns in settings sheet

    Returns:
      (merged_df, new_file_id, out_name)
    """
    clinic_id = require_authenticated_tenant_access(clinic_id)

    # 1) Get current pointer (if any)
    if existing_file_id is None or existing_name is None:
        existing_file_id, existing_name = get_existing_dataset_pointer(clinic_id)
    if existing_file_id:
        require_clinic_dataset_file_access(clinic_id, existing_file_id)

    # 2) Load existing dataset if present
    if existing_df is None:
        try:
            existing_df = load_existing_shared_df(existing_file_id, existing_name, clinic_id=clinic_id)
        except Exception:
            # show signal but still allow publish
            st.warning("Could not load the saved clinic data, so this upload will be saved as a new copy.")
            existing_df = None

    # 3) Merge according to the clinic update rule
    merged_df = merge_dataset_update(
        existing_df=existing_df,
        new_df=new_df,
        replace_overlapping_dates=replace_overlapping_dates,
    )

    # 4) Upload merged dataset to Drive
    out_name  = f"{clinic_id}_shared_dataset.csv"
    out_bytes = merged_df.to_csv(index=False).encode("utf-8")

    operation_id = make_dataset_publish_operation_id()
    record_dataset_tracker_event(
        "dataset_publish",
        "started",
        operation_id=operation_id,
        file_name=out_name,
        rows=len(merged_df),
        replace_overlapping_dates=replace_overlapping_dates,
        drive_file_id=existing_file_id or "",
        drive_file_name=existing_name or "",
        message="stage=drive_upload",
        source="publish_dataset_for_clinic",
    )

    new_file_id = ""
    stage = "drive_upload"
    try:
        # ✅ Update existing file if it exists; otherwise create first time
        new_file_id = drive_upsert_csv_bytes(
            file_bytes=out_bytes,
            filename=out_name,
            folder_id=datasets_folder_id,
            existing_file_id=(existing_file_id or None),
            clinic_id=clinic_id,
        )

        # ✅ Only update pointer after upload success
        stage = "settings_pointer_update"
        dataset_updated_at = update_clinic_dataset_pointer(clinic_id, new_file_id, out_name)
    except Exception as e:
        record_dataset_tracker_event(
            "dataset_publish",
            "error",
            operation_id=operation_id,
            file_name=out_name,
            rows=len(merged_df),
            replace_overlapping_dates=replace_overlapping_dates,
            drive_file_id=new_file_id or existing_file_id or "",
            drive_file_name=out_name,
            message=f"stage={stage}; {e}",
            source="publish_dataset_for_clinic",
        )
        raise

    record_dataset_tracker_event(
        "dataset_publish",
        "success",
        operation_id=operation_id,
        file_name=out_name,
        rows=len(merged_df),
        replace_overlapping_dates=replace_overlapping_dates,
        drive_file_id=new_file_id,
        drive_file_name=out_name,
        message="stage=complete",
        source="publish_dataset_for_clinic",
    )
    st.session_state["shared_dataset_updated_at"] = dataset_updated_at
    st.session_state.pop("_shared_dataset_load_attempted_for", None)
    remember_shared_dataset_loaded_for_current_pointer(clinic_id)


    return merged_df, new_file_id, out_name

# --------------------------------
# 💾 Per-clinic settings persistence via Google Sheets
# --------------------------------
def load_settings():
    """Load settings for the current clinic from the Google Sheet."""
    clinic_id = st.session_state.get("clinic_id")
    if not clinic_id:
        st.warning("Please log in first.")
        return

    rec = None
    try:
        sheet, headers, row_idx = _get_settings_row_for_clinic(clinic_id)
        row_values = get_cached_settings_row_values(clinic_id) or _gspread_retry(sheet.row_values, row_idx)
        rec = {
            header: row_values[idx] if idx < len(row_values) else ""
            for idx, header in enumerate(headers)
        }
    except Exception:
        sheet = get_settings_sheet()
        records = sheet.get_all_records()
        clinic_key = normalize_clinic_id_key(clinic_id)
        rec = next((r for r in records if normalize_clinic_id_key(r.get("ClinicID", "")) == clinic_key), None)

    if rec and rec.get(SHEET_COL_SETTINGS_JSON):
        try:
            settings = json.loads(rec.get(SHEET_COL_SETTINGS_JSON, "{}"))
        except Exception:
            settings = {}
        cache_remote_settings(clinic_id, settings)
        st.session_state["rules"] = settings.get("rules", DEFAULT_RULES.copy())
        st.session_state["exclusions"] = settings.get("exclusions", [])
        st.session_state["client_exclusions"] = settings.get("client_exclusions", [])
        st.session_state["patient_exclusions"] = normalize_patient_exclusions(settings.get("patient_exclusions", []))
        st.session_state["automatic_patient_exclusions"] = normalize_patient_exclusions(settings.get("automatic_patient_exclusions", []))
        st.session_state["patient_passaway_keywords"] = normalize_passaway_keywords(
            settings.get("patient_passaway_keywords", PATIENT_PASSAWAY_KEYWORDS_DEFAULT)
        )
        st.session_state["user_name"] = settings.get("user_name", "")
        st.session_state["user_template"] = settings.get("user_template", DEFAULT_WA_TEMPLATE)
        st.session_state["client_group_days"] = max(0, int(settings.get("client_group_days", 1) or 0))
        raw_window_days = settings.get("reminder_window_days", 1)
        try:
            st.session_state["reminder_window_days"] = max(0, int(raw_window_days if raw_window_days not in (None, "") else 1))
        except (TypeError, ValueError):
            st.session_state["reminder_window_days"] = 1
        raw_lookback_days = settings.get("reminder_lookback_days", DEFAULT_REMINDER_LOOKBACK_DAYS)
        try:
            st.session_state["reminder_lookback_days"] = max(0, int(raw_lookback_days if raw_lookback_days not in (None, "") else DEFAULT_REMINDER_LOOKBACK_DAYS))
        except (TypeError, ValueError):
            st.session_state["reminder_lookback_days"] = DEFAULT_REMINDER_LOOKBACK_DAYS
        st.session_state["reminder_warning_days"] = int(settings.get("reminder_warning_days", 0) or 0)
        load_outcome_due_date_window_days(settings)
        migrated_legacy_actions = False
        legacy_wa_log = settings.get("wa_reminder_log", [])
        legacy_deleted_reminders = settings.get("deleted_reminders", [])
        if legacy_deleted_reminders and not settings.get("action_tracker_migrated_at"):
            if migrate_legacy_actions_to_tracker(clinic_id, legacy_deleted_reminders):
                settings["action_tracker_migrated_at"] = utc_now_iso()
                migrated_legacy_actions = True
        tracked_actions = load_action_tracker_records_for_clinic(clinic_id)
        st.session_state["deleted_reminders"] = merge_deleted_reminders(legacy_deleted_reminders, tracked_actions)
        st.session_state["wa_reminder_log"] = merge_wa_reminder_logs(legacy_wa_log, action_records_to_wa_log(st.session_state["deleted_reminders"]))
        st.session_state["search_terms_reviewed"] = bool(settings.get("search_terms_reviewed", False))
        st.session_state["search_term_added"] = bool(settings.get("search_term_added", False))
        st.session_state["wa_template_reviewed"] = bool(settings.get("wa_template_reviewed", False))
        st.session_state["wa_template_updated"] = bool(settings.get("wa_template_updated", False))
        st.session_state["get_started_reset_at"] = settings.get("get_started_reset_at", "")
        st.session_state["search_term_added_at"] = settings.get("search_term_added_at", "")
        st.session_state["user_name_updated_at"] = settings.get("user_name_updated_at", "")
        st.session_state["wa_template_updated_at"] = settings.get("wa_template_updated_at", "")
        st.session_state["dataset_upload_history"] = normalize_dataset_upload_history(settings.get("dataset_upload_history", []))
        st.session_state["user_country"] = settings.get("country", "")
        st.session_state["action_tracker_migrated_at"] = settings.get("action_tracker_migrated_at", "")
        if migrated_legacy_actions:
            save_settings_quietly(refresh_remote=False)
    else:
        # Defaults for new clinics
        settings = default_settings_for_country("")
        cache_remote_settings(clinic_id, settings)
        st.session_state["rules"] = DEFAULT_RULES.copy()
        st.session_state["exclusions"] = []
        st.session_state["client_exclusions"] = []
        st.session_state["patient_exclusions"] = []
        st.session_state["automatic_patient_exclusions"] = []
        st.session_state["patient_passaway_keywords"] = PATIENT_PASSAWAY_KEYWORDS_DEFAULT.copy()
        st.session_state["user_name"] = ""
        st.session_state["user_template"] = DEFAULT_WA_TEMPLATE
        st.session_state["client_group_days"] = 1
        st.session_state["reminder_window_days"] = 1
        st.session_state["reminder_lookback_days"] = DEFAULT_REMINDER_LOOKBACK_DAYS
        st.session_state["reminder_warning_days"] = 0
        load_outcome_due_date_window_days(settings)
        st.session_state["wa_reminder_log"] = []
        st.session_state["deleted_reminders"] = []
        st.session_state["search_terms_reviewed"] = False
        st.session_state["search_term_added"] = False
        st.session_state["wa_template_reviewed"] = False
        st.session_state["wa_template_updated"] = False
        st.session_state["get_started_reset_at"] = ""
        st.session_state["search_term_added_at"] = ""
        st.session_state["user_name_updated_at"] = ""
        st.session_state["wa_template_updated_at"] = ""
        st.session_state["dataset_upload_history"] = []
        st.session_state["user_country"] = ""
        st.session_state["action_tracker_migrated_at"] = ""


_SETTING_MISSING = object()


def _settings_copy(value):
    try:
        return json.loads(json.dumps(value))
    except Exception:
        return value


def _settings_equal(left, right) -> bool:
    try:
        return json.dumps(left, sort_keys=True, default=str) == json.dumps(right, sort_keys=True, default=str)
    except Exception:
        return left == right


def _merged_scalar_setting(key: str, default, base_settings: dict, remote_settings: dict):
    if key not in st.session_state:
        return _settings_copy(remote_settings.get(key, default))
    local_value = st.session_state[key]
    base_value = base_settings.get(key, _SETTING_MISSING)
    remote_value = remote_settings.get(key, _SETTING_MISSING)
    if (
        base_value is not _SETTING_MISSING
        and remote_value is not _SETTING_MISSING
        and _settings_equal(local_value, base_value)
        and not _settings_equal(remote_value, base_value)
    ):
        return _settings_copy(remote_value)
    if (
        base_value is not _SETTING_MISSING
        and remote_value is _SETTING_MISSING
        and _settings_equal(local_value, base_value)
    ):
        return _settings_copy(default)
    return _settings_copy(local_value)


def merge_rule_settings_for_save(base_rules, remote_rules, local_rules) -> dict:
    base_rules = base_rules if isinstance(base_rules, dict) else {}
    remote_rules = remote_rules if isinstance(remote_rules, dict) else {}
    local_rules = local_rules if isinstance(local_rules, dict) else {}
    merged = {}

    for rule in sorted(set(base_rules) | set(remote_rules) | set(local_rules)):
        base_present = rule in base_rules
        remote_present = rule in remote_rules
        local_present = rule in local_rules
        base_value = base_rules.get(rule, _SETTING_MISSING)
        remote_value = remote_rules.get(rule, _SETTING_MISSING)
        local_value = local_rules.get(rule, _SETTING_MISSING)

        if not local_present:
            if not base_present and remote_present:
                merged[rule] = _settings_copy(remote_value)
            continue
        if not remote_present:
            if base_present and _settings_equal(local_value, base_value):
                continue
            merged[rule] = _settings_copy(local_value)
            continue
        if not base_present:
            merged[rule] = _settings_copy(local_value if not _settings_equal(local_value, remote_value) else remote_value)
            continue
        if _settings_equal(local_value, base_value) and not _settings_equal(remote_value, base_value):
            merged[rule] = _settings_copy(remote_value)
        else:
            merged[rule] = _settings_copy(local_value)
    return merged


def _text_list_key(value) -> str:
    return _SPACE_RX.sub(" ", str(value or "").strip()).lower()


def _patient_exclusion_key(value) -> str:
    if not isinstance(value, dict):
        return ""
    client = _text_list_key(value.get("client", ""))
    patient = _text_list_key(value.get("patient", ""))
    return f"{client}|{patient}" if client or patient else ""


def merge_keyed_list_setting_for_save(base_list, remote_list, local_list, key_fn) -> list:
    base_items = base_list if isinstance(base_list, list) else []
    remote_items = remote_list if isinstance(remote_list, list) else []
    local_items = local_list if isinstance(local_list, list) else []

    def keyed(items):
        order = []
        values = {}
        for item in items:
            key = key_fn(item)
            if not key:
                continue
            if key not in values:
                order.append(key)
            values[key] = item
        return order, values

    _, base_map = keyed(base_items)
    remote_order, remote_map = keyed(remote_items)
    local_order, local_map = keyed(local_items)

    result_order = list(remote_order)
    result = {key: _settings_copy(value) for key, value in remote_map.items()}

    for key in base_map:
        if key not in local_map:
            result.pop(key, None)
            if key in result_order:
                result_order.remove(key)

    for key in local_order:
        local_value = local_map[key]
        if key in base_map and key not in remote_map and _settings_equal(local_value, base_map[key]):
            result.pop(key, None)
            if key in result_order:
                result_order.remove(key)
            continue
        if (
            key in base_map
            and key in remote_map
            and _settings_equal(local_value, base_map[key])
            and not _settings_equal(remote_map[key], base_map[key])
        ):
            continue
        if key not in result_order:
            result_order.append(key)
        result[key] = _settings_copy(local_value)

    return [result[key] for key in result_order if key in result]


def save_settings(track_user: bool = True, refresh_remote: bool = True):
    """Save current clinic’s settings back to the Google Sheet."""
    clinic_id = st.session_state.get("clinic_id")
    if not clinic_id:
        return

    row = None
    headers = []
    sheet = None
    try:
        sheet, headers, row = _get_settings_row_for_clinic(clinic_id)
    except ValueError:
        sheet = get_settings_sheet()

    base_settings = get_cached_remote_settings(clinic_id)
    remote_settings = (
        read_remote_settings_for_save(sheet=sheet, headers=headers, row=row)
        if refresh_remote and row
        else base_settings
    )
    if not remote_settings and base_settings:
        remote_settings = base_settings

    wa_remove_keys = {
        tuple(key)
        for key in st.session_state.pop("_wa_reminder_remove_keys_once", [])
        if isinstance(key, (list, tuple)) and any(key)
    }
    replace_wa_log = st.session_state.pop("_replace_wa_reminder_log_once", False)
    if replace_wa_log and not wa_remove_keys:
        wa_reminder_log = st.session_state.get("wa_reminder_log", [])
    else:
        wa_reminder_log = merge_wa_reminder_logs(
            remote_settings.get("wa_reminder_log", []),
            st.session_state.get("wa_reminder_log", []),
        )
        if wa_remove_keys:
            wa_reminder_log = [
                entry for entry in wa_reminder_log
                if tuple(entry.get("ReminderKey", [])) not in wa_remove_keys
            ]
    st.session_state["wa_reminder_log"] = wa_reminder_log

    deleted_remove_keys = {
        tuple(key)
        for key in st.session_state.pop("_deleted_reminder_remove_keys_once", [])
        if isinstance(key, (list, tuple)) and any(key)
    }
    replace_deleted_reminders = st.session_state.pop("_replace_deleted_reminders_once", False)
    if replace_deleted_reminders and not deleted_remove_keys:
        deleted_reminders = st.session_state.get("deleted_reminders", [])
    else:
        deleted_reminders = merge_deleted_reminders(
            remote_settings.get("deleted_reminders", []),
            st.session_state.get("deleted_reminders", []),
        )
        if deleted_remove_keys:
            deleted_reminders = [
                entry for entry in deleted_reminders
                if hidden_reminder_key(entry) not in deleted_remove_keys
            ]
        st.session_state["deleted_reminders"] = deleted_reminders

    def int_setting_for_save(key: str, default: int) -> int:
        value = _merged_scalar_setting(key, default, base_settings, remote_settings)
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def setting_for_save(key: str, default):
        return _merged_scalar_setting(key, default, base_settings, remote_settings)

    replace_search_settings = st.session_state.pop("_replace_search_settings_once", False)
    if replace_search_settings:
        rules_for_save = setting_for_save("rules", DEFAULT_RULES.copy())
        exclusions_for_save = setting_for_save("exclusions", [])
        client_exclusions_for_save = setting_for_save("client_exclusions", [])
        patient_exclusions_for_save = setting_for_save("patient_exclusions", [])
        automatic_patient_exclusions_for_save = setting_for_save("automatic_patient_exclusions", [])
        patient_passaway_keywords_for_save = setting_for_save("patient_passaway_keywords", PATIENT_PASSAWAY_KEYWORDS_DEFAULT.copy())
    else:
        rules_for_save = merge_rule_settings_for_save(
            base_settings.get("rules", {}),
            remote_settings.get("rules", {}),
            setting_for_save("rules", DEFAULT_RULES.copy()),
        )
        exclusions_for_save = merge_keyed_list_setting_for_save(
            base_settings.get("exclusions", []),
            remote_settings.get("exclusions", []),
            setting_for_save("exclusions", []),
            _text_list_key,
        )
        client_exclusions_for_save = merge_keyed_list_setting_for_save(
            base_settings.get("client_exclusions", []),
            remote_settings.get("client_exclusions", []),
            setting_for_save("client_exclusions", []),
            _text_list_key,
        )
        patient_exclusions_for_save = merge_keyed_list_setting_for_save(
            base_settings.get("patient_exclusions", []),
            remote_settings.get("patient_exclusions", []),
            setting_for_save("patient_exclusions", []),
            _patient_exclusion_key,
        )
        automatic_patient_exclusions_for_save = merge_keyed_list_setting_for_save(
            base_settings.get("automatic_patient_exclusions", []),
            remote_settings.get("automatic_patient_exclusions", []),
            setting_for_save("automatic_patient_exclusions", []),
            _patient_exclusion_key,
        )
        patient_passaway_keywords_for_save = merge_keyed_list_setting_for_save(
            base_settings.get("patient_passaway_keywords", PATIENT_PASSAWAY_KEYWORDS_DEFAULT.copy()),
            remote_settings.get("patient_passaway_keywords", PATIENT_PASSAWAY_KEYWORDS_DEFAULT.copy()),
            setting_for_save("patient_passaway_keywords", PATIENT_PASSAWAY_KEYWORDS_DEFAULT.copy()),
            _text_list_key,
        )

    # Build the JSON blob for settings
    settings_data = {
        "rules": rules_for_save,
        "exclusions": exclusions_for_save,
        "client_exclusions": client_exclusions_for_save,
        "patient_exclusions": normalize_patient_exclusions(patient_exclusions_for_save),
        "automatic_patient_exclusions": normalize_patient_exclusions(automatic_patient_exclusions_for_save),
        "patient_passaway_keywords": normalize_passaway_keywords(patient_passaway_keywords_for_save),
        "user_name": setting_for_save("user_name", ""),
        "user_template": setting_for_save("user_template", DEFAULT_WA_TEMPLATE),
        "client_group_days": max(0, int_setting_for_save("client_group_days", 1)),
        "reminder_window_days": max(0, int_setting_for_save("reminder_window_days", 1)),
        "reminder_lookback_days": max(0, int_setting_for_save("reminder_lookback_days", DEFAULT_REMINDER_LOOKBACK_DAYS)),
        "reminder_warning_days": max(0, int_setting_for_save("reminder_warning_days", 0)),
        "outcome_due_date_window_days": normalized_outcome_due_date_window_days(
            int_setting_for_save("outcome_due_date_window_days", DEFAULT_OUTCOME_DUE_DATE_WINDOW_DAYS)
        ),
        "search_terms_reviewed": bool(setting_for_save("search_terms_reviewed", False)),
        "search_term_added": bool(setting_for_save("search_term_added", False)),
        "wa_template_reviewed": bool(setting_for_save("wa_template_reviewed", False)),
        "wa_template_updated": bool(setting_for_save("wa_template_updated", False)),
        "get_started_reset_at": setting_for_save("get_started_reset_at", ""),
        "search_term_added_at": setting_for_save("search_term_added_at", ""),
        "user_name_updated_at": setting_for_save("user_name_updated_at", ""),
        "wa_template_updated_at": setting_for_save("wa_template_updated_at", ""),
        "dataset_upload_history": normalize_dataset_upload_history(setting_for_save("dataset_upload_history", [])),
        "country": setting_for_save("user_country", remote_settings.get("country", "")),
        "action_tracker_migrated_at": setting_for_save("action_tracker_migrated_at", remote_settings.get("action_tracker_migrated_at", "")),
    }
    settings_json = json.dumps(settings_data)
    updated_at = utc_now_iso()

    # Update existing row or append a new one
    if row:
        if callable(globals().get("_update_settings_cells", None)):
            _update_settings_cells(sheet, headers, row, settings_json, updated_at)
        else:
            first_idx = _settings_col_index(headers, "SettingsJSON")
            last_idx = _settings_col_index(headers, "UpdatedAt")
            payload = [{
                "range": _row_range_a1(row, first_idx, last_idx),
                "values": [[settings_json, updated_at]],
            }]
            _gspread_retry(sheet.batch_update, payload)
        if settings_data.get("country"):
            update_settings_row_fields(
                clinic_id,
                {
                    SHEET_COL_COUNTRY: settings_data.get("country", ""),
                    SHEET_COL_ACCOUNT_STATUS: "active",
                },
                SETTINGS_REQUIRED_COLUMNS,
            )
    else:
        headers = ensure_settings_sheet_columns(sheet, headers, SETTINGS_REQUIRED_COLUMNS)
        _gspread_retry(
            sheet.append_row,
            settings_row_values(
                headers,
                {
                    SHEET_COL_CLINIC_ID: clinic_id,
                    SHEET_COL_PASSWORD_HASH: "",
                    SHEET_COL_SETTINGS_JSON: settings_json,
                    SHEET_COL_UPDATED_AT: updated_at,
                    SHEET_COL_COUNTRY: settings_data.get("country", ""),
                    SHEET_COL_ACCOUNT_STATUS: "active",
                },
            ),
            value_input_option="USER_ENTERED",
        )
    update_cached_settings_row_fields(
        clinic_id,
        {
            SHEET_COL_SETTINGS_JSON: settings_json,
            SHEET_COL_UPDATED_AT: updated_at,
            SHEET_COL_COUNTRY: settings_data.get("country", ""),
            SHEET_COL_ACCOUNT_STATUS: "active",
        },
    )
    cache_remote_settings(clinic_id, settings_data)
    saved_outcome_due_date_window_days = normalized_outcome_due_date_window_days(
        settings_data.get("outcome_due_date_window_days")
    )
    if (
        "outcome_due_date_window_days" in st.session_state
        and normalized_outcome_due_date_window_days() == saved_outcome_due_date_window_days
    ):
        st.session_state[OUTCOME_DUE_DATE_WINDOW_DIRTY_KEY] = False
        st.session_state[OUTCOME_DUE_DATE_WINDOW_LOADED_KEY] = saved_outcome_due_date_window_days
    if track_user:
        upsert_user_tracker(clinic_id, country=st.session_state.get("user_country", ""), event="settings_saved")


def remember_settings_save_failure(error) -> None:
    status = gspread_api_error_status(error) if isinstance(error, APIError) else None
    detail = f" Google returned {status}." if status else ""
    st.session_state["_pending_settings_sync_warning"] = (
        "Google Sheets was busy, so the last change may not be synced yet."
        f"{detail} If the change does not stick after a refresh, try it again."
    )


def remember_settings_preservation_warning(error) -> None:
    remember_settings_save_failure(error)
    st.session_state["_pending_settings_sync_warning"] = (
        "The latest saved clinic settings could not be checked, so this change was not written. "
        "This protects saved search terms and exclusions from being overwritten by an older browser session. "
        "Please try again."
    )


def save_settings_quietly(refresh_remote: bool = True) -> bool:
    try:
        save_settings(track_user=False, refresh_remote=refresh_remote)
        return True
    except APIError as e:
        remember_settings_save_failure(e)
        return False
    except SettingsFreshReadError as e:
        remember_settings_preservation_warning(e)
        return False


def show_pending_settings_sync_warning():
    warning = st.session_state.pop("_pending_settings_sync_warning", "")
    if warning:
        st.warning(warning)
# --------------------------------


def remember_action_tracker_save_failure() -> None:
    st.session_state["_pending_action_sync_warning"] = (
        "That reminder action was not saved, so the reminder state was not changed. "
        "Please try again before leaving this page."
    )


def show_pending_action_sync_warning() -> None:
    warning = st.session_state.pop("_pending_action_sync_warning", "")
    if warning:
        st.warning(warning)


def _reminder_client_key(client_name: str) -> str:
    return _SPACE_RX.sub(" ", str(client_name or "").strip()).lower()

def _parse_reminder_log_time(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _user_local_time_from_utc_log(value) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None
    return user_now(parsed)


def action_tracker_user_local_time(row: dict) -> str:
    local_actioned_at = _user_local_time_from_utc_log(row.get("ActionedAtUTC", ""))
    if local_actioned_at:
        return local_actioned_at.isoformat()
    return str(row.get("DateTimeGST", "") or "").strip()

def _days_ago_text(then: datetime, now: datetime) -> str:
    days = max(0, (now.date() - then.date()).days)
    if days == 0:
        return "today"
    if days == 1:
        return "1 day ago"
    return f"{days} days ago"

def read_remote_settings_from_row(sheet, headers, row) -> dict:
    current_row = _gspread_retry(sheet.row_values, row)
    settings_idx = _settings_col_index(headers, "SettingsJSON") - 1
    if len(current_row) <= settings_idx or not current_row[settings_idx]:
        return {}
    return json.loads(current_row[settings_idx])


def read_remote_settings_for_save(sheet, headers, row) -> dict:
    try:
        settings = read_remote_settings_from_row(sheet, headers, row)
    except Exception as e:
        raise SettingsFreshReadError("Could not read latest clinic settings before saving.") from e
    clinic_id = st.session_state.get("clinic_id")
    if clinic_id:
        cache_remote_settings(clinic_id, settings)
    return settings


def get_remote_settings(sheet=None, headers=None, row=None) -> dict:
    clinic_id = st.session_state.get("clinic_id")
    if not clinic_id:
        return {}

    try:
        if not (sheet and headers and row):
            sheet, headers, row = _get_settings_row_for_clinic(clinic_id)
        settings = read_remote_settings_from_row(sheet, headers, row)
        cache_remote_settings(clinic_id, settings)
        return settings
    except Exception:
        return {}

def get_remote_wa_reminder_log(sheet=None, headers=None, row=None) -> list:
    clinic_id = st.session_state.get("clinic_id", "")
    tracked_actions = load_action_tracker_records_for_clinic(clinic_id)
    return merge_wa_reminder_logs(
        get_remote_settings(sheet=sheet, headers=headers, row=row).get("wa_reminder_log", []),
        action_records_to_wa_log(tracked_actions),
    )

def merge_wa_reminder_logs(*logs):
    merged = {}
    for log in logs:
        if not isinstance(log, list):
            continue
        for entry in log:
            if not isinstance(entry, dict):
                continue
            client_name = str(entry.get("Client Name", "")).strip()
            reminded_at = str(entry.get("RemindedAt", "")).strip()
            if not client_name or not reminded_at:
                continue
            merged_entry = dict(entry)
            merged_entry["Client Name"] = client_name
            merged_entry["RemindedAt"] = reminded_at
            merged[(client_name, reminded_at)] = merged_entry

    return sorted(
        merged.values(),
        key=lambda entry: _parse_reminder_log_time(entry.get("RemindedAt", "")) or datetime.min,
    )[-MAX_SETTINGS_LOG_ENTRIES:]

HIDDEN_REMINDER_KEY_FIELDS = ("Client Name", "Animal Name", "Plan Item", "Due Date", "Reminder Date")
REMINDER_ACTION_SENT = "sent"
REMINDER_ACTION_DECLINED = "declined"
MAX_SETTINGS_LOG_ENTRIES = 1000
WHATSAPP_ICON_MASK_DATA_URI = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E"
    "%3Cpath d='M9 57l4.2-15.2A24.2 24.2 0 0 1 10 29.8C10 16.7 20.7 6 33.8 6"
    "S57.5 16.7 57.5 29.8 46.9 53.5 33.8 53.5c-4 0-7.9-1-11.3-2.9L9 57z"
    "M24.6 18.3c-.6-1.4-1.1-1.4-1.7-1.4h-1.4c-.5 0-1.3.2-2 1-.7.8-2.6 2.6-2.6 6.2"
    "s2.7 7.2 3.1 7.7c.4.5 5.2 8.3 12.9 11.3 6.4 2.5 7.7 2 9.1 1.9 1.4-.1 4.5-1.8 5.1-3.6"
    ".6-1.8.6-3.3.4-3.6-.2-.3-.7-.5-1.5-.9l-5.4-2.7c-.8-.4-1.4-.6-2 .4-.6.9-2.3 2.7-2.8 3.3"
    "-.5.6-1 .7-1.8.2-.8-.4-3.5-1.3-6.7-4.1-2.5-2.2-4.1-5-4.6-5.8-.5-.8-.1-1.3.3-1.7"
    ".4-.4.8-1 1.2-1.5.4-.5.5-.9.8-1.5.3-.6.1-1.1-.1-1.5l-2.4-5.8z'/%3E%3C/svg%3E"
)


def _hidden_reminder_key_part(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return _SPACE_RX.sub(" ", str(value).strip()).lower()


def hidden_reminder_key(row) -> tuple[str, ...]:
    return tuple(_hidden_reminder_key_part(row.get(field, "")) for field in HIDDEN_REMINDER_KEY_FIELDS)


def normalize_reminder_details_for_storage(details) -> list[dict]:
    if not isinstance(details, list):
        return []
    normalized = []
    fields = ("Animal Name", "Plan Item", "Due Date", "Reminder Date", "Charge Date", "Qty", "Days", "Search Terms")
    for detail in details:
        if not isinstance(detail, dict):
            continue
        clean_detail = {}
        for field in fields:
            value = detail.get(field, "")
            try:
                if pd.isna(value):
                    value = ""
            except (TypeError, ValueError):
                pass
            clean_detail[field] = str(value or "").strip()
        if any(clean_detail.values()):
            normalized.append(clean_detail)
    return normalized


def reminder_details_json(row) -> str:
    details = normalize_reminder_details_for_storage(row.get("ReminderDetails", []))
    return json.dumps(details, ensure_ascii=True) if details else ""


def get_hidden_reminders_index() -> dict[tuple[str, ...], dict]:
    deleted = st.session_state.get("deleted_reminders", [])
    cache_key = (id(deleted), len(deleted))
    cached = st.session_state.get("_hidden_reminders_index_cache")
    if isinstance(cached, dict) and cached.get("cache_key") == cache_key:
        return cached.get("index", {})

    index = {}
    for entry in deleted:
        if not isinstance(entry, dict):
            continue
        key = hidden_reminder_key(entry)
        if any(key):
            index[key] = entry
    st.session_state["_hidden_reminders_index_cache"] = {
        "cache_key": cache_key,
        "index": index,
    }
    return index


def _hidden_reminder_action_time(entry) -> datetime:
    return (
        _parse_reminder_log_time(entry.get("ActionedAt", ""))
        or _parse_reminder_log_time(entry.get("DeletedAt", ""))
        or datetime.min
    )


def merge_deleted_reminders(*logs):
    merged = {}
    for log in logs:
        if not isinstance(log, list):
            continue
        for entry in log:
            if not isinstance(entry, dict):
                continue
            key = hidden_reminder_key(entry)
            if not any(key):
                continue
            existing = merged.get(key)
            if existing is None or _hidden_reminder_action_time(entry) >= _hidden_reminder_action_time(existing):
                merged[key] = dict(entry)
    return sorted(merged.values(), key=_hidden_reminder_action_time)[-MAX_SETTINGS_LOG_ENTRIES:]


def _action_tracker_time(entry: dict) -> datetime:
    return (
        _parse_reminder_log_time(entry.get("ActionedAt", ""))
        or _parse_reminder_log_time(entry.get("DeletedAt", ""))
        or datetime.min
    )


def action_tracker_row_values(row, action: str, message: str = "", source: str = "", now: datetime | None = None) -> list[str]:
    event_now = now or utc_now()
    reminder_key = list(hidden_reminder_key(row))
    return [
        gst_now_iso(event_now),
        utc_now_iso(event_now),
        str(st.session_state.get("clinic_id", "")).strip(),
        str(st.session_state.get("user_name", "")).strip(),
        str(action or "").strip().lower(),
        normalize_display_case(row.get("Client Name", "")),
        normalize_display_case(row.get("Animal Name", "")),
        normalize_display_case(row.get("Plan Item", "")),
        str(row.get("Reminder Date", "")).strip(),
        str(row.get("Due Date", "")).strip(),
        str(row.get("Charge Date", "")).strip(),
        str(row.get("Qty", "")).strip(),
        str(row.get("Days", "")).strip(),
        str(message or "").strip(),
        str(source or "").strip(),
        json.dumps(reminder_key),
        reminder_details_json(row),
    ]


def action_tracker_values_to_record(headers: list[str], values: list[str]) -> dict | None:
    row = {
        header: values[idx] if idx < len(values) else ""
        for idx, header in enumerate(headers)
    }
    action = str(row.get("Action", "")).strip().lower()
    if action not in {REMINDER_ACTION_SENT, REMINDER_ACTION_DECLINED, "active", "undo"}:
        return None
    actioned_at_local = action_tracker_user_local_time(row)
    rec = {
        "Reminder Date": row.get("ReminderDate", ""),
        "Due Date": row.get("DueDate", ""),
        "Charge Date": row.get("ChargeDate", ""),
        "Client Name": row.get("ClientName", ""),
        "Animal Name": row.get("AnimalNames", ""),
        "Plan Item": row.get("Items", ""),
        "Qty": row.get("Qty", ""),
        "Days": row.get("Days", ""),
        "Action": action,
        "DeletedAt": actioned_at_local,
        "ActionedAt": actioned_at_local,
        "ActionedAtUTC": row.get("ActionedAtUTC", ""),
        "Actioned By": row.get("YourNameClinic", ""),
        "MessageCreated": row.get("MessageCreated", ""),
        "Source": row.get("Source", ""),
    }
    details_raw = str(row.get("ReminderDetailsJSON", "") or "").strip()
    if details_raw:
        try:
            rec["ReminderDetails"] = normalize_reminder_details_for_storage(json.loads(details_raw))
        except (TypeError, ValueError, json.JSONDecodeError):
            rec["ReminderDetails"] = []
    return rec


def reduce_action_tracker_records(records: list[dict]) -> list[dict]:
    latest_by_key = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        key = hidden_reminder_key(record)
        if not any(key):
            continue
        existing = latest_by_key.get(key)
        if existing is None or _action_tracker_time(record) >= _action_tracker_time(existing):
            latest_by_key[key] = dict(record)

    actioned = [
        record for record in latest_by_key.values()
        if str(record.get("Action", "")).strip().lower() in {REMINDER_ACTION_SENT, REMINDER_ACTION_DECLINED}
    ]
    return sorted(actioned, key=_action_tracker_time)[-MAX_SETTINGS_LOG_ENTRIES:]


def action_records_to_wa_log(records: list[dict]) -> list[dict]:
    wa_log = []
    for record in records:
        if str(record.get("Action", "")).strip().lower() != REMINDER_ACTION_SENT:
            continue
        reminded_at = record.get("ActionedAt", "") or record.get("DeletedAt", "")
        if not reminded_at:
            continue
        wa_log.append({
            "Client Name": record.get("Client Name", ""),
            "RemindedAt": reminded_at,
            "ReminderKey": list(hidden_reminder_key(record)),
        })
    return merge_wa_reminder_logs(wa_log)


def load_action_tracker_records_for_clinic(clinic_id: str) -> list[dict]:
    clinic_id = str(clinic_id or "").strip()
    if not clinic_id:
        return []
    clinic_key = clinic_id.lower()
    timezone_key = user_timezone_name()
    cache = st.session_state.get("_action_tracker_records_cache")
    if isinstance(cache, dict) and cache.get("clinic_key") == clinic_key and cache.get("timezone_key") == timezone_key:
        return [dict(record) for record in cache.get("records", []) if isinstance(record, dict)]
    try:
        sheet = get_or_create_tracker_sheet(ACTION_TRACKER_WORKSHEET, ACTION_TRACKER_HEADERS)
        values = _gspread_retry(sheet.get_all_values) or []
    except Exception:
        return []
    if not values:
        return []
    headers = values[0]
    clinic_ix = headers.index("ClinicID") if "ClinicID" in headers else -1
    records = []
    for raw in values[1:]:
        if clinic_ix >= 0 and (len(raw) <= clinic_ix or str(raw[clinic_ix]).strip().lower() != clinic_id.lower()):
            continue
        rec = action_tracker_values_to_record(headers, raw)
        if rec:
            records.append(rec)
    reduced = reduce_action_tracker_records(records)
    st.session_state["_action_tracker_records_cache"] = {
        "clinic_key": clinic_key,
        "timezone_key": timezone_key,
        "records": [dict(record) for record in reduced],
    }
    return reduced


def invalidate_action_tracker_records_cache() -> None:
    st.session_state.pop("_action_tracker_records_cache", None)


def migrate_legacy_actions_to_tracker(clinic_id: str, legacy_deleted: list[dict]) -> bool:
    if not legacy_deleted:
        return False
    rows = []
    for entry in legacy_deleted:
        if not isinstance(entry, dict):
            continue
        action = str(entry.get("Action", "")).strip().lower()
        if action not in {REMINDER_ACTION_SENT, REMINDER_ACTION_DECLINED}:
            continue
        actioned_at = _hidden_reminder_action_time(entry)
        if actioned_at == datetime.min:
            actioned_at = utc_now()
        rows.append(action_tracker_row_values(
            entry,
            action,
            message=entry.get("MessageCreated", ""),
            source="legacy_settings_migration",
            now=actioned_at,
        ))
    return append_tracker_rows(ACTION_TRACKER_WORKSHEET, ACTION_TRACKER_HEADERS, rows)


def get_hidden_reminder_record(row) -> dict | None:
    target_key = hidden_reminder_key(row)
    if not any(target_key):
        return None
    return get_hidden_reminders_index().get(target_key)


def upsert_hidden_reminder(row, action: str, message: str = "", now: datetime | None = None) -> dict:
    now = user_now(now)
    actioned_by = str(st.session_state.get("user_name", "") or "").strip()
    rec = {
        "Reminder Date": row.get("Reminder Date", ""),
        "Due Date": row.get("Due Date", ""),
        "Charge Date": row.get("Charge Date", ""),
        "Client Name": row.get("Client Name", ""),
        "Animal Name": row.get("Animal Name", ""),
        "Plan Item": row.get("Plan Item", ""),
        "Qty": row.get("Qty", ""),
        "Days": row.get("Days", ""),
        "Action": action,
        "DeletedAt": now.isoformat(),
        "ActionedAt": now.isoformat(),
        "Actioned By": actioned_by,
    }
    if message:
        rec["MessageCreated"] = str(message or "").strip()
    details = normalize_reminder_details_for_storage(row.get("ReminderDetails", []))
    if details:
        rec["ReminderDetails"] = details

    target_key = hidden_reminder_key(rec)
    reminders = [
        existing for existing in st.session_state.get("deleted_reminders", [])
        if not (isinstance(existing, dict) and hidden_reminder_key(existing) == target_key)
    ]
    reminders.append(rec)
    st.session_state["deleted_reminders"] = reminders[-MAX_SETTINGS_LOG_ENTRIES:]
    return rec


def filter_hidden_reminders(reminders_df: pd.DataFrame) -> pd.DataFrame:
    deleted = st.session_state.get("deleted_reminders", [])
    if reminders_df.empty or not deleted:
        return reminders_df

    deleted_keys = {hidden_reminder_key(d) for d in deleted if isinstance(d, dict)}
    if not deleted_keys:
        return reminders_df

    key_parts = []
    for field in HIDDEN_REMINDER_KEY_FIELDS:
        if field in reminders_df.columns:
            values = reminders_df[field]
        else:
            values = pd.Series("", index=reminders_df.index)
        key_parts.append(values.map(_hidden_reminder_key_part))

    keep_mask = [key not in deleted_keys for key in zip(*key_parts)]
    return reminders_df.loc[keep_mask].copy()


def remove_actioned_reminder(row) -> None:
    target_key = hidden_reminder_key(row)
    if not any(target_key):
        return
    st.session_state["deleted_reminders"] = [
        entry for entry in st.session_state.get("deleted_reminders", [])
        if not (isinstance(entry, dict) and hidden_reminder_key(entry) == target_key)
    ]
    remove_keys = st.session_state.setdefault("_deleted_reminder_remove_keys_once", [])
    remove_keys.append(list(target_key))


def get_recent_reminder_warning(client_name: str, now: datetime | None = None, sync_remote: bool = False) -> str | None:
    warning_days = int(st.session_state.get("reminder_warning_days", 0) or 0)
    if warning_days <= 0:
        return None

    now = user_now(now)
    if sync_remote:
        st.session_state["wa_reminder_log"] = merge_wa_reminder_logs(
            get_remote_wa_reminder_log(),
            st.session_state.get("wa_reminder_log", []),
        )
    client_key = _reminder_client_key(client_name)
    latest = None
    for entry in st.session_state.get("wa_reminder_log", []):
        if _reminder_client_key(entry.get("Client Name", "")) != client_key:
            continue
        reminded_at = _parse_reminder_log_time(entry.get("RemindedAt", ""))
        if reminded_at and (latest is None or reminded_at > latest):
            latest = reminded_at

    if latest and now - latest <= timedelta(days=warning_days):
        display_name = normalize_display_case(client_name)
        return f"Reminder: {display_name} got a reminder {_days_ago_text(latest, now)}."
    return None

def record_wa_reminder_click(client_name: str, now: datetime | None = None, row=None, save: bool = True):
    now = user_now(now)
    entry = {
        "Client Name": str(client_name or "").strip(),
        "RemindedAt": now.isoformat(),
    }
    if row is not None:
        entry["ReminderKey"] = list(hidden_reminder_key(row))
    log = list(st.session_state.get("wa_reminder_log", []))
    log.append(entry)
    st.session_state["wa_reminder_log"] = log[-MAX_SETTINGS_LOG_ENTRIES:]
    if save:
        save_settings_quietly()


def remove_wa_reminder_click_for_row(row, queue_settings_removal: bool = True):
    target_key = list(hidden_reminder_key(row))
    if not any(target_key):
        return
    st.session_state["wa_reminder_log"] = [
        entry for entry in st.session_state.get("wa_reminder_log", [])
        if not (isinstance(entry, dict) and entry.get("ReminderKey") == target_key)
    ]
    if queue_settings_removal:
        remove_keys = st.session_state.setdefault("_wa_reminder_remove_keys_once", [])
        remove_keys.append(target_key)


def record_action_tracker(row, action: str, message: str = "", source: str = "", now: datetime | None = None):
    return append_tracker_row(
        ACTION_TRACKER_WORKSHEET,
        ACTION_TRACKER_HEADERS,
        action_tracker_row_values(row, action, message=message, source=source, now=now),
    )


def record_wa_button_tracker(row, message: str, source: str, now: datetime | None = None):
    """Legacy wrapper; new writes go to Action tracker."""
    record_action_tracker(row, REMINDER_ACTION_SENT, message=message, source=source, now=now)


def show_recent_reminder_warning(message: str, key: str):
    if hasattr(st, "dialog"):
        @st.dialog("Reminder warning")
        def _warning_dialog():
            st.write(message)
            st.button("OK", key=key)
        _warning_dialog()
    elif hasattr(st, "experimental_dialog"):
        @st.experimental_dialog("Reminder warning")
        def _warning_dialog():
            st.write(message)
            st.button("OK", key=key)
        _warning_dialog()
    else:
        st.warning(message)


def data_privacy_policy_content() -> dict:
    return {
        "headline": "Your clinic data stays your clinic data.",
        "intro": (
            "Clinic Reminders uses uploaded sales exports only to run the workflows your clinic chooses: "
            "reminders, statistics, setup checks, saved search terms, exclusions, and templates. Sales, "
            "client, patient, item, date, quantity, and amount fields are treated as sensitive clinic operations data."
        ),
        "sections": [
            {
                "title": "What the app stores",
                "body": (
                    "The app saves a clinic-level working dataset so your team can return to the same reminders "
                    "and statistics. It also saves clinic settings, search terms, exclusions, WhatsApp templates, "
                    "and reminder action history so your workflow is not lost between sessions."
                ),
            },
            {
                "title": "Where it is kept",
                "body": (
                    "Saved datasets are stored in the app's managed Google Drive storage. Clinic settings, audit "
                    "events, reminder actions, and upload history are stored in managed Google Sheets used by the app."
                ),
            },
            {
                "title": "How it is used",
                "body": (
                    "Data is used to calculate reminders, show clinic statistics, prevent duplicate reminder work, "
                    "and record actions such as sent or declined reminders. Clinic financial data is not sold, "
                    "used for advertising, used to train AI models, or used for unrelated product work."
                ),
            },
            {
                "title": "Who can see it",
                "body": (
                    "People signed into the same clinic account can see that clinic's saved data, settings, "
                    "reminders, and statistics. Keep clinic logins and linked Google accounts limited to team members "
                    "who should have access."
                ),
            },
            {
                "title": "Your control",
                "body": (
                    "Use Clear Clinic Data on the Upload Data tab to remove the active saved clinic data while keeping "
                    "clinic settings and search terms. Account > Delete account and data removes the clinic account, "
                    "saved settings, action history, and uploaded clinic data file."
                ),
            },
            {
                "title": "Practical upload guidance",
                "body": (
                    "Upload only the sales and reminder data your clinic needs for this tool. Avoid uploading unrelated "
                    "medical notes, payment card numbers, government IDs, or files that are not needed for reminders."
                ),
            },
            {
                "title": "Backups and support",
                "body": (
                    "The app is designed to preserve saved settings and avoid silent overwrites. If your clinic needs "
                    "help with export, recovery, retention, or permanent deletion, contact support before making manual sheet changes."
                ),
            },
        ],
        "footer": (
            "The aim is simple: keep clinic data tied to the clinic account, use it only for the reminder workflow, "
            "and make deletion and support paths clear."
        ),
    }


def data_assurance_box_html() -> str:
    return ""


def upload_sales_data_help_html() -> str:
    return textwrap.dedent("""
    <style>
      .cr-upload-help {
        color: #0f172a;
      }
      .cr-upload-help-hero {
        background: linear-gradient(135deg, rgba(41, 210, 114, 0.16), rgba(255, 255, 255, 0.98));
        border: 1px solid rgba(29, 167, 89, 0.24);
        border-radius: 8px;
        margin-bottom: 0.85rem;
        padding: 1rem 1.05rem;
      }
      .cr-upload-help-hero h3 {
        color: #082f1f;
        font-size: 1.25rem;
        font-weight: 850;
        letter-spacing: 0;
        line-height: 1.2;
        margin: 0 0 0.45rem;
      }
      .cr-upload-help-hero p,
      .cr-upload-help-rule p,
      .cr-upload-help-caption {
        color: #475569;
        font-size: 0.94rem;
        line-height: 1.45;
        margin: 0;
      }
      .cr-upload-help-rules {
        display: grid;
        gap: 0.65rem;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        margin-bottom: 0.75rem;
      }
      @media (max-width: 720px) {
        .cr-upload-help-rules {
          grid-template-columns: 1fr;
        }
      }
      .cr-upload-help-rule,
      .cr-upload-help-table {
        background: #ffffff;
        border: 1px solid rgba(15, 23, 42, 0.11);
        border-radius: 8px;
        box-shadow: 0 8px 24px rgba(15, 23, 42, 0.045);
      }
      .cr-upload-help-rule {
        padding: 0.82rem 0.9rem;
      }
      .cr-upload-help-rule strong {
        color: #0f172a;
        display: block;
        font-size: 0.98rem;
        margin-bottom: 0.3rem;
      }
      .cr-upload-help-table {
        overflow: hidden;
      }
      .cr-upload-help-row {
        display: grid;
        grid-template-columns: 1.1fr 1fr 1fr 1.7fr;
      }
      .cr-upload-help-row > div {
        border-right: 1px solid rgba(15, 23, 42, 0.08);
        padding: 0.62rem 0.7rem;
      }
      .cr-upload-help-row > div:last-child {
        border-right: 0;
      }
      .cr-upload-help-head {
        background: #f1f5f9;
        color: #334155;
        font-size: 0.78rem;
        font-weight: 850;
        text-transform: uppercase;
      }
      .cr-upload-help-body {
        color: #0f172a;
        font-size: 0.9rem;
      }
      .cr-upload-help-caption {
        margin-top: 0.65rem;
      }
    </style>
    <div class="cr-upload-help">
      <div class="cr-upload-help-hero">
        <h3>What should uploaded sales data look like?</h3>
        <p>Exports look different across PMSs. Clinic Reminders only needs the information required to find reminder dates.</p>
      </div>
      <div class="cr-upload-help-rules">
        <div class="cr-upload-help-rule">
          <strong>One row per billed item</strong>
          <p>Each row should be a single billed product or service, such as a vaccine, medication, food item, or consultation.</p>
        </div>
        <div class="cr-upload-help-rule">
          <strong>Four required fields</strong>
          <p>The upload needs the billed date, client name, animal name, and billed product or service.</p>
        </div>
      </div>
      <div class="cr-upload-help-table">
        <div class="cr-upload-help-row cr-upload-help-head">
          <div>Date billed</div>
          <div>Client name</div>
          <div>Animal name</div>
          <div>Billed product or service</div>
        </div>
        <div class="cr-upload-help-row cr-upload-help-body">
          <div>02 Jan 2024</div>
          <div>Alexandra Field</div>
          <div>Sausage</div>
          <div>Kennel cough and rabies vaccine</div>
        </div>
        <div class="cr-upload-help-row cr-upload-help-body">
          <div>08 Jan 2024</div>
          <div>Nicole Mansour</div>
          <div>Fluffy</div>
          <div>Bravecto tablet</div>
        </div>
      </div>
      <p class="cr-upload-help-caption">Extra columns are fine. The app ignores columns it does not need.</p>
    </div>
    """).strip()


def new_account_welcome_dialog_html() -> str:
    steps = [
        (
            "1",
            "Upload your data",
            "Start with a recent sales export from your PMS. About a year of history is ideal.",
            "Upload Data",
        ),
        (
            "2",
            "Set your reminder rules",
            "Add the products or services you want to remind clients about, and choose when each reminder should go out.",
            "Search Terms",
        ),
        (
            "3",
            "Prepare your message",
            "Enter your name, review the WhatsApp template, then use the WhatsApp button to create each message.",
            "Reminders",
        ),
        (
            "4",
            "Clear the list as you work",
            "Mark reminders as sent or declined so completed items leave the active list.",
            "Reminders",
        ),
    ]
    step_cards = []
    for number, title, body, tab_name in steps:
        step_cards.append(
            textwrap.dedent("""
            <section class="cr-welcome-step">
              <div class="cr-welcome-step-top">
                <span class="cr-welcome-number">{number}</span>
                <span class="cr-welcome-tab">{tab_name}</span>
              </div>
              <h4>{title}</h4>
              <p>{body}</p>
            </section>
            """).strip().format(
                number=html_lib.escape(number),
                title=html_lib.escape(title),
                body=html_lib.escape(body),
                tab_name=html_lib.escape(tab_name),
            )
        )

    step_cards_html = "\n".join(step_cards)
    return textwrap.dedent("""
    <style>
      .cr-welcome-dialog {{
        color: #0f172a;
      }}
      .cr-welcome-hero {{
        background: linear-gradient(135deg, rgba(41, 210, 114, 0.16), rgba(255, 255, 255, 0.98));
        border: 1px solid rgba(29, 167, 89, 0.24);
        border-radius: 8px;
        margin-bottom: 0.9rem;
        padding: 1rem 1.05rem;
      }}
      .cr-welcome-kicker {{
        color: #15803d;
        font-size: 0.78rem;
        font-weight: 850;
        letter-spacing: 0.08em;
        margin: 0 0 0.35rem;
        text-transform: uppercase;
      }}
      .cr-welcome-hero h3 {{
        color: #082f1f;
        font-size: 1.35rem;
        font-weight: 900;
        letter-spacing: 0;
        line-height: 1.18;
        margin: 0 0 0.45rem;
      }}
      .cr-welcome-hero p,
      .cr-welcome-step p,
      .cr-welcome-note {{
        color: #475569;
        font-size: 0.94rem;
        line-height: 1.45;
        margin: 0;
      }}
      .cr-welcome-grid {{
        display: grid;
        gap: 0.65rem;
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }}
      @media (max-width: 700px) {{
        .cr-welcome-grid {{
          grid-template-columns: 1fr;
        }}
      }}
      .cr-welcome-step {{
        background: #ffffff;
        border: 1px solid rgba(15, 23, 42, 0.11);
        border-radius: 8px;
        box-shadow: 0 8px 24px rgba(15, 23, 42, 0.045);
        min-height: 9.2rem;
        padding: 0.85rem 0.9rem;
      }}
      .cr-welcome-step-top {{
        align-items: center;
        display: flex;
        justify-content: space-between;
        gap: 0.6rem;
        margin-bottom: 0.55rem;
      }}
      .cr-welcome-number {{
        align-items: center;
        background: #29d272;
        border-radius: 999px;
        color: #ffffff;
        display: inline-flex;
        font-size: 0.82rem;
        font-weight: 900;
        height: 1.65rem;
        justify-content: center;
        width: 1.65rem;
      }}
      .cr-welcome-tab {{
        background: #f1f5f9;
        border: 1px solid rgba(15, 23, 42, 0.08);
        border-radius: 999px;
        color: #475569;
        font-size: 0.76rem;
        font-weight: 750;
        padding: 0.18rem 0.48rem;
      }}
      .cr-welcome-step h4 {{
        color: #0f172a;
        font-size: 1rem;
        font-weight: 850;
        letter-spacing: 0;
        margin: 0 0 0.32rem;
      }}
      .cr-welcome-note {{
        background: #f8fafc;
        border: 1px solid rgba(15, 23, 42, 0.08);
        border-radius: 8px;
        margin-top: 0.75rem;
        padding: 0.78rem 0.85rem;
      }}
    </style>
    <div class="cr-welcome-dialog">
      <div class="cr-welcome-hero">
        <p class="cr-welcome-kicker">New account</p>
        <h3>Set up your first reminders</h3>
        <p>Four calm steps get the clinic from upload to ready-to-send reminders. You can change everything later.</p>
      </div>
      <div class="cr-welcome-grid">{step_cards_html}</div>
      <div class="cr-welcome-note">Start with Upload Data. The app will save your setup as you go, so your search terms and template work are not lost between sessions.</div>
    </div>
    """).strip().format(step_cards_html=step_cards_html)


def data_privacy_dialog_html(content: dict | None = None) -> str:
    content = content or data_privacy_policy_content()
    sections_html = []
    for section in content.get("sections", []):
        sections_html.append(
            "<section class='cr-privacy-card'>"
            f"<h4>{html_lib.escape(section.get('title', ''))}</h4>"
            f"<p>{html_lib.escape(section.get('body', ''))}</p>"
            "</section>"
        )
    return f"""
    <style>
      .cr-privacy-dialog {{
        color: #0f172a;
      }}
      .cr-privacy-hero {{
        background: linear-gradient(135deg, rgba(41, 210, 114, 0.16), rgba(255, 255, 255, 0.96));
        border: 1px solid rgba(29, 167, 89, 0.26);
        border-radius: 8px;
        margin-bottom: 0.9rem;
        padding: 1rem 1.05rem;
      }}
      .cr-privacy-hero h3 {{
        color: #082f1f;
        font-size: 1.25rem;
        font-weight: 850;
        letter-spacing: 0;
        line-height: 1.2;
        margin: 0 0 0.45rem;
      }}
      .cr-privacy-hero p,
      .cr-privacy-card p,
      .cr-privacy-footer {{
        color: #475569;
        font-size: 0.94rem;
        line-height: 1.45;
        margin: 0;
      }}
      .cr-privacy-grid {{
        display: grid;
        gap: 0.65rem;
        grid-template-columns: repeat(4, minmax(0, 1fr));
      }}
      @media (max-width: 980px) {{
        .cr-privacy-grid {{
          grid-template-columns: repeat(2, minmax(0, 1fr));
        }}
      }}
      @media (max-width: 620px) {{
        .cr-privacy-grid {{
          grid-template-columns: 1fr;
        }}
      }}
      .cr-privacy-card {{
        background: #ffffff;
        border: 1px solid rgba(15, 23, 42, 0.11);
        border-radius: 8px;
        box-shadow: 0 8px 24px rgba(15, 23, 42, 0.045);
        padding: 0.8rem 0.85rem;
      }}
      .cr-privacy-card h4 {{
        color: #0f172a;
        font-size: 0.98rem;
        font-weight: 800;
        letter-spacing: 0;
        margin: 0 0 0.32rem;
      }}
      .cr-privacy-footer {{
        background: #f8fafc;
        border: 1px solid rgba(15, 23, 42, 0.08);
        border-radius: 8px;
        margin-bottom: 0.85rem;
        margin-top: 0.75rem;
        padding: 0.78rem 0.85rem;
      }}
    </style>
    <div class='cr-privacy-dialog'>
      <div class='cr-privacy-hero'>
        <h3>{html_lib.escape(content.get('headline', ''))}</h3>
        <p>{html_lib.escape(content.get('intro', ''))}</p>
      </div>
      <div class='cr-privacy-grid'>
        {''.join(sections_html)}
      </div>
      <div class='cr-privacy-footer'>{html_lib.escape(content.get('footer', ''))}</div>
    </div>
    """


def close_data_privacy_dialog():
    st.session_state["show_data_privacy_dialog"] = False


def close_new_account_welcome_dialog():
    st.session_state["show_new_account_welcome_dialog"] = False


def close_upload_sales_data_help_dialog():
    st.session_state["show_upload_sales_data_help_dialog"] = False


def mark_new_account_welcome_pending():
    st.session_state["show_new_account_welcome_dialog"] = True


def render_new_account_welcome_dialog():
    if not st.session_state.get("show_new_account_welcome_dialog", False):
        return

    def _render_dialog_body():
        welcome_html = new_account_welcome_dialog_html()
        if hasattr(st, "html"):
            st.html(welcome_html)
        else:
            st.markdown(welcome_html, unsafe_allow_html=True)
        if st.button("Get started", key="new_account_welcome_get_started", type="primary", use_container_width=True):
            close_new_account_welcome_dialog()
            navigate_main_section_tab("Upload Data")
            st.rerun()

    if hasattr(st, "dialog"):
        @st.dialog("Welcome to Clinic Reminders", width="large", on_dismiss=close_new_account_welcome_dialog)
        def _welcome_dialog():
            _render_dialog_body()
        _welcome_dialog()
    elif hasattr(st, "experimental_dialog"):
        @st.experimental_dialog("Welcome to Clinic Reminders")
        def _welcome_dialog():
            _render_dialog_body()
        _welcome_dialog()
    else:
        with st.expander("Welcome to Clinic Reminders", expanded=True):
            _render_dialog_body()


def render_upload_sales_data_help_dialog():
    if not st.session_state.get("show_upload_sales_data_help_dialog", False):
        return

    def _render_dialog_body():
        help_html = upload_sales_data_help_html()
        if hasattr(st, "html"):
            st.html(help_html)
        else:
            st.markdown(help_html, unsafe_allow_html=True)
        if st.button("Close", key="close_upload_sales_data_help_dialog", use_container_width=True):
            close_upload_sales_data_help_dialog()
            st.rerun()

    if hasattr(st, "dialog"):
        @st.dialog("Uploaded sales data", width="large", on_dismiss=close_upload_sales_data_help_dialog)
        def _upload_help_dialog():
            _render_dialog_body()
        _upload_help_dialog()
    elif hasattr(st, "experimental_dialog"):
        @st.experimental_dialog("Uploaded sales data")
        def _upload_help_dialog():
            _render_dialog_body()
        _upload_help_dialog()
    else:
        with st.expander("Uploaded sales data", expanded=True):
            _render_dialog_body()


ACCOUNT_DIALOG_STATE_KEYS = (
    "show_profile_dialog",
    "show_data_privacy_dialog",
    "show_delete_account_dialog",
)


def close_account_dialogs():
    for key in ACCOUNT_DIALOG_STATE_KEYS:
        st.session_state[key] = False


def account_dialog_is_open() -> bool:
    return any(st.session_state.get(key, False) for key in ACCOUNT_DIALOG_STATE_KEYS)


def upload_widget_has_files() -> bool:
    for key, value in st.session_state.items():
        if not str(key).startswith("file_uploader_main_"):
            continue
        if isinstance(value, (list, tuple)):
            if len(value) > 0:
                return True
        elif value:
            return True
    return bool(st.session_state.get("last_uploaded_files"))


def open_account_dialog(dialog_name: str):
    if dialog_name == "delete":
        st.session_state.pop("delete_account_confirm_text", None)
    st.session_state["show_profile_dialog"] = dialog_name == "profile"
    st.session_state["show_data_privacy_dialog"] = dialog_name == "privacy"
    st.session_state["show_delete_account_dialog"] = dialog_name == "delete"


def render_data_privacy_dialog():
    if not st.session_state.get("show_data_privacy_dialog", False):
        return

    def _render_dialog_body():
        st.markdown(data_privacy_dialog_html(), unsafe_allow_html=True)
        if st.button("Close", key="close_data_privacy_dialog_button", use_container_width=True):
            close_data_privacy_dialog()
            st.rerun()

    if hasattr(st, "dialog"):
        @st.dialog("Data & Privacy", width="large", on_dismiss=close_data_privacy_dialog)
        def _privacy_dialog():
            _render_dialog_body()
        _privacy_dialog()
    elif hasattr(st, "experimental_dialog"):
        @st.experimental_dialog("Data & Privacy")
        def _privacy_dialog():
            _render_dialog_body()
        _privacy_dialog()
    else:
        with st.expander("Data & Privacy", expanded=True):
            _render_dialog_body()

# --------------------------------
# PMS definitions
# --------------------------------
PMS_DEFINITIONS = {
    "VETport": {
        "columns": [
            "Planitem Performed", "Client Name", "Client ID", "Patient Name",
            "Patient ID", "Plan Item ID", "Plan Item Name", "Plan Item Quantity",
            "Performed Staff", "Plan Item Amount", "Returned Quantity",
            "Returned Date", "Invoice No"
        ],
        "mappings": {
            "date": "Planitem Performed",
            "client": "Client Name",
            "animal": "Patient Name",
            "item": "Plan Item Name",
            "qty": "Plan Item Quantity",
            "amount": "Plan Item Amount"
        }
    },
    "Xpress": {
        "columns": [
            "Date", "Client ID", "Client Name", "SLNo", "Doctor",
            "Animal Name", "Item Name", "Item ID", "Qty", "Rate", "Amount"
        ],
        "mappings": {
            "date": "Date",
            "client": "Client Name",
            "animal": "Animal Name",
            "item": "Item Name",
            "qty": "Qty",
            "amount": "Amount"
        }
    },
    "ezyVet": {
        "columns": [
            "Invoice #", "Invoice Date", "Type", "Parent Line ID",
            "Invoice Line Date: Created", "Invoice Line Time: Created",
            "Created By", "Invoice Line Date: Last Modified",
            "Invoice Line Time: Last Modified", "Last Modified By",
            "Invoice Line Date", "Invoice Line Time", "Department ID",
            "Department", "Inventory Location", "Client Contact Code",
            "Business Name", "First Name", "Last Name", "Email",
            "Animal Code", "Patient Name", "Species", "Breed",
            "Invoice Line ID", "Invoice Line Reference", "Product Code",
            "Product Name", "Product Description", "Account", "Product Cost",
            "Product Group", "Staff Member ID", "Staff Member",
            "Salesperson is Vet", "Consult ID", "Consult Number",
            "Case Owner", "Qty", "Standard Price(incl)", "Discount(%)",
            "Discount(د.إ)", "User Reason", "Surcharge Adjustment",
            "Surcharge Name", "Discount Adjustment", "Discount Name",
            "Rounding Adjustment", "Rounding Name",
            "Price After Discount(excl)", "Tax per Qty After Discount",
            "Price After Discount(incl)", "Total Invoiced (excl)",
            "Total Tax Amount", "Total Invoiced (incl)",
            "Total Earned(excl)", "Total Earned(incl)", "Payment Terms"
        ],
        "mappings": {
            "date": "Invoice Date",
            "client_first": "First Name",
            "client_last": "Last Name",
            "animal": "Patient Name",
            "item": "Product Name",
            "qty": "Qty",
            "amount": "Total Invoiced (excl)"
        }
    }
}

def normalize_columns(cols):
    cleaned = []
    for c in cols:
        if not isinstance(c, str):
            c = str(c)
        c = c.replace("\u00a0", " ").replace("\ufeff", "")
        c = _SPACE_RX.sub(" ", c).strip().lower()
        cleaned.append(c)
    return cleaned

def detect_pms(df: pd.DataFrame) -> str:
    normalized_cols = set(normalize_columns(df.columns))
    v_keys = {"plan item amount"}
    v_date_keys = {"planitem performed", "plan item performed", "datetime"}
    if v_keys.issubset(normalized_cols) and len(v_date_keys.intersection(normalized_cols)) > 0:
        return "VETport"
    x_keys = {"date", "animal name", "amount", "item name"}
    e_keys = {"invoice date", "total invoiced (excl)", "product name", "first name", "last name"}
    if e_keys.issubset(normalized_cols): return "ezyVet"
    if x_keys.issubset(normalized_cols): return "Xpress"
    for pms_name, definition in PMS_DEFINITIONS.items():
        required = set(normalize_columns(definition["columns"]))
        if required.issubset(normalized_cols):
            return pms_name
    return None
def clean_revenue_column(series: pd.Series) -> pd.Series:
    return (
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace(_CURRENCY_RX, "", regex=True)
        .pipe(pd.to_numeric, errors="coerce")
        .fillna(0)
    )

def parse_dates(series: pd.Series) -> pd.Series:
    if series is None:
        return pd.Series(dtype="datetime64[ns]")
    series = pd.Series(series, copy=False)
    if pd.api.types.is_datetime64_any_dtype(series):
        return pd.to_datetime(series.dt.date, errors="coerce")
    s = series.astype(str).str.strip()
    s = s.str.extract(
        r"(\d{1,2}[\s/-][A-Za-z]{3}[\s/-]\d{4}|\d{1,2}[\s/-]\d{1,2}[\s/-]\d{4}|\d{4}[\s/-]\d{1,2}[\s/-]\d{1,2})"
    )[0]
    parsed_dates = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
    numeric = pd.to_numeric(s, errors="coerce")
    if numeric.notna().sum() > 0:
        base_1900 = pd.Timestamp("1899-12-30")
        dt_1900 = base_1900 + pd.to_timedelta(numeric, unit="D")
        base_1904 = pd.Timestamp("1904-01-01")
        dt_1904 = base_1904 + pd.to_timedelta(numeric, unit="D")
        valid_1900 = dt_1900.dt.year.between(1990, 2100)
        valid_1904 = dt_1904.dt.year.between(1990, 2100)
        parsed_numeric = (dt_1904 if valid_1904.sum() > valid_1900.sum() else dt_1900).dt.normalize()
        parsed_dates.loc[numeric.notna()] = parsed_numeric.loc[numeric.notna()]
    formats = [
        "%d/%b/%Y", "%d-%b-%Y", "%d %b %Y",
        "%d/%m/%Y", "%m/%d/%Y", "%d %m %Y", "%m %d %Y",
        "%Y-%m-%d", "%Y/%m/%d", "%Y %m %d", "%Y.%m.%d"
    ]
    for fmt in formats:
        parsed = pd.to_datetime(s, format=fmt, errors="coerce")
        fill_mask = parsed_dates.isna() & parsed.notna()
        if fill_mask.any():
            parsed_dates.loc[fill_mask] = parsed.loc[fill_mask].dt.normalize()
    fill_mask = parsed_dates.isna() & s.notna()
    if fill_mask.any():
        parsed = pd.to_datetime(s.loc[fill_mask], errors="coerce", dayfirst=True)
        parsed_dates.loc[fill_mask] = parsed.dt.normalize()
    return parsed_dates.dt.normalize()


class UploadValidationError(ValueError):
    pass


class UploadResourceLimitError(UploadValidationError):
    pass


REQUIRED_UPLOAD_COLUMNS = ["ChargeDate", "Client Name", "Animal Name", "Item Name"]
MAX_UPLOAD_FILES = 5
MAX_UPLOAD_FILE_BYTES = 25 * 1024 * 1024
MAX_UPLOAD_ROWS = 250_000
MAX_UPLOAD_COLUMNS = 200
USER_FACING_COLUMN_LABELS = {
    "ChargeDate": "Billed Date",
    "Charge Date": "Billed Date",
}
GENERIC_UPLOAD_ALIAS_COLUMNS = {
    "BilledDate": "ChargeDate",
    "Billed Date": "ChargeDate",
    "Billed On": "ChargeDate",
    "Bill Date": "ChargeDate",
    "Charge Date": "ChargeDate",
}
DATE_COLUMN_CANDIDATES = [
    "ChargeDate", "BilledDate", "Billed Date", "Billed On", "Bill Date",
    "DateTime", "Date Time", "Date", "Invoice Date",
    "Planitem Performed", "PlanItem Performed", "Plan Item Performed",
    "planitem performed",
]
VETPORT_ALIAS_COLUMNS = {
    "DateTime": "Planitem Performed",
    "Date Time": "Planitem Performed",
    "Patient Name": "Patient Name",
    "Animal Name": "Patient Name",
    "Item Name": "Plan Item Name",
    "Plan Item Name": "Plan Item Name",
    "Item Qty": "Plan Item Quantity",
    "Qty": "Plan Item Quantity",
    "Quantity": "Plan Item Quantity",
    "Plan Item Quantity": "Plan Item Quantity",
    "Item ID": "Plan Item ID",
    "Plan Item ID": "Plan Item ID",
}


def format_file_size(num_bytes: int) -> str:
    mb = num_bytes / (1024 * 1024)
    return f"{mb:.0f} MB" if mb >= 10 else f"{mb:.1f} MB"


def validate_upload_file_size(file_bytes, filename: str) -> None:
    size = len(file_bytes or b"")
    if size > MAX_UPLOAD_FILE_BYTES:
        raise UploadResourceLimitError(
            f"{filename} is too large. Maximum upload size is "
            f"{format_file_size(MAX_UPLOAD_FILE_BYTES)} per file."
        )


def validate_upload_file_collection(file_blobs) -> None:
    if len(file_blobs or []) > MAX_UPLOAD_FILES:
        raise UploadResourceLimitError(
            f"Upload at most {MAX_UPLOAD_FILES} files at a time."
        )
    for fb in file_blobs or []:
        validate_upload_file_size(fb.get("bytes", b""), fb.get("name", "upload"))


def validate_upload_dataframe_limits(df: pd.DataFrame, filename: str) -> None:
    row_count = len(df.index)
    column_count = len(df.columns)
    if row_count > MAX_UPLOAD_ROWS:
        raise UploadResourceLimitError(
            f"{filename} has too many rows. Maximum is {MAX_UPLOAD_ROWS:,} rows."
        )
    if column_count > MAX_UPLOAD_COLUMNS:
        raise UploadResourceLimitError(
            f"{filename} has too many columns. Maximum is "
            f"{MAX_UPLOAD_COLUMNS:,} columns."
        )


def find_column_ci(columns, candidates):
    normalized = {str(c).strip().lower(): c for c in columns}
    for candidate in candidates:
        match = normalized.get(str(candidate).strip().lower())
        if match is not None:
            return match
    return None


def user_facing_column_label(column: str) -> str:
    return USER_FACING_COLUMN_LABELS.get(str(column), str(column))


def format_missing_upload_columns(missing_columns: list[str]) -> str:
    return ", ".join(user_facing_column_label(col) for col in missing_columns)


def apply_generic_upload_alias_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for source, target in GENERIC_UPLOAD_ALIAS_COLUMNS.items():
        source_col = find_column_ci(df.columns, [source])
        target_col = find_column_ci(df.columns, [target])
        if source_col is not None and target_col is None:
            df[target] = df[source_col]
    return df


def apply_vetport_alias_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for source, target in VETPORT_ALIAS_COLUMNS.items():
        source_col = find_column_ci(df.columns, [source])
        target_col = find_column_ci(df.columns, [target])
        if source_col is not None and target_col is None:
            df[target] = df[source_col]
    return df


def validate_upload_dataframe(df: pd.DataFrame, filename: str):
    validate_upload_dataframe_limits(df, filename)
    missing = [col for col in REQUIRED_UPLOAD_COLUMNS if col not in df.columns]
    if missing:
        raise UploadValidationError(
            f"{filename} is missing required column(s): {format_missing_upload_columns(missing)}."
        )
    if "ChargeDate" not in df.columns or parse_dates(df["ChargeDate"]).notna().sum() == 0:
        raise UploadValidationError(
            f"{filename} needs a readable date column for Billed Date, DateTime, Date, Invoice Date, or Planitem Performed."
        )
    if df.empty:
        raise UploadValidationError(f"{filename} does not contain any usable rows.")


def has_readable_canonical_upload_schema(df: pd.DataFrame) -> bool:
    if df is None or getattr(df, "empty", True):
        return False
    if any(col not in df.columns for col in REQUIRED_UPLOAD_COLUMNS):
        return False
    return parse_dates(df["ChargeDate"]).notna().sum() > 0


def finalize_processed_upload_df(df: pd.DataFrame, filename: str) -> pd.DataFrame:
    df = sanitize_working_df(df)
    validate_upload_dataframe_limits(df, filename)
    validate_upload_dataframe(df, filename)
    df["_client_lower"] = df["Client Name"].astype(str).str.lower()
    df["_animal_lower"] = df["Animal Name"].astype(str).str.lower()
    df["_item_lower"] = df["Item Name"].astype(str).str.lower()
    return df

# --------------------------------
# File processing (decoupled from rules)
# --------------------------------
@st.cache_data(show_spinner=False)
def process_file(file_bytes, filename):
    """
    Load and normalize uploaded data files across supported PMS types.
    Automatically detects PMS and applies schema normalization.
    ✅ Vetport: immediately reorders columns to the canonical order
    so all downstream logic behaves identically regardless of column order.
    """

    from io import BytesIO
    validate_upload_file_size(file_bytes, filename)
    file = BytesIO(file_bytes)
    lowerfn = filename.lower()

    # --- 1️⃣ Load file ---
    if lowerfn.endswith(".csv"):
        df = pd.read_csv(
            file,
            dtype=str,
            keep_default_na=False,
            index_col=False,
            skip_blank_lines=True,
        )
    elif lowerfn.endswith((".xls", ".xlsx")):
        df = pd.read_excel(file, dtype=str)
    else:
        raise ValueError("Unsupported file type")
    validate_upload_dataframe_limits(df, filename)
    
    # Drop rows that are completely empty or whitespace-only
    df = df.replace(r"^\s*$", "", regex=True)
    df = df.dropna(how="all")
    df = df.loc[~(df.eq("").all(axis=1))].copy()

    # --- Clean up column headers early (strip ALL whitespace and normalize unicode) ---
    def clean_header(h):
        if not isinstance(h, str):
            h = str(h)
        return unicodedata.normalize("NFKC", h).replace("\u00a0", " ").replace("\ufeff", "").strip()

    df.columns = [clean_header(c) for c in df.columns]
    df = drop_duplicate_columns(df)
    df = apply_generic_upload_alias_columns(df)

    if has_readable_canonical_upload_schema(df):
        return finalize_processed_upload_df(df, filename), "Canonical CSV", None

    # --- 4️⃣ Detect PMS ---
    pms_name = detect_pms(df)
    if not pms_name:
        return df, None, None

    # --- 5️⃣ Vetport: FORCE PatrikEdit format BEFORE proceeding further ---
    if pms_name == "VETport":
        df = apply_vetport_alias_columns(df)
        df = normalize_vetport_to_patrikedit(df)


    # --- 6️⃣ Apply PMS mappings ---
    mappings = PMS_DEFINITIONS[pms_name]["mappings"]
    rename_map = {}

    def get_col_ci(target: str):
        """Case-insensitive column name lookup."""
        for c in df.columns:
            if c.lower() == target.lower():
                return c
        return None

    date_col = get_col_ci(mappings.get("date", ""))
    client_col = get_col_ci(mappings.get("client", ""))
    animal_col = get_col_ci(mappings.get("animal", ""))
    item_col = get_col_ci(mappings.get("item", ""))
    qty_col = get_col_ci(mappings.get("qty", ""))
    amount_col = get_col_ci(mappings.get("amount", ""))

    if date_col:
        rename_map[date_col] = "ChargeDate"
    if client_col:
        rename_map[client_col] = "Client Name"
    if animal_col:
        rename_map[animal_col] = "Animal Name"
    if item_col:
        rename_map[item_col] = "Item Name"

    df = df.rename(columns=rename_map)
    df = drop_duplicate_columns(df)

    # --- 7️⃣ Clean revenue column ---
    if amount_col and amount_col in df.columns:
        df["Amount"] = clean_revenue_column(df[amount_col])
    else:
        df["Amount"] = 0

    # --- 8️⃣ ezyVet: merge first + last name ---
    if pms_name == "ezyVet":
        cf = mappings.get("client_first")
        cl = mappings.get("client_last")
        if cf and cl and cf in df.columns and cl in df.columns:
            df["Client Name"] = (
                df[cf].fillna("").astype(str).str.strip() + " " +
                df[cl].fillna("").astype(str).str.strip()
            ).str.strip()

    # --- 9️⃣ Quantity handling ---
    if qty_col and qty_col in df.columns:
        df["Qty"] = pd.to_numeric(df[qty_col], errors="coerce").fillna(1).astype(int)
    else:
        fallback_qty_cols = ["Qty", "Quantity", "Plan Item Quantity"]
        found = False
        for c in fallback_qty_cols:
            if c in df.columns:
                df["Qty"] = pd.to_numeric(df[c], errors="coerce").fillna(1).astype(int)
                found = True
                break
        if not found:
            df["Qty"] = 1

    # --- 🔟 Ensure ChargeDate exists and is parsed correctly ---
    if "ChargeDate" not in df.columns:
        date_fallback = find_column_ci(df.columns, DATE_COLUMN_CANDIDATES)
        if date_fallback:
            df["ChargeDate"] = df[date_fallback]
    
    # Keep raw date strings for debugging
    if "ChargeDate" in df.columns:
        df["ChargeDate"] = parse_dates(df["ChargeDate"]).dt.normalize()
    else:
        df["ChargeDate"] = pd.NaT

    # --- 11️⃣ Add lowercase helper columns for search and reminders ---
    df = finalize_processed_upload_df(df, filename)

    # --- ✅ Return normalized data ---
    return df, pms_name, amount_col
    
# === GOOGLE SHEETS CONNECTION ===
@st.cache_resource(show_spinner=False)
def get_settings_spreadsheet():
    """Connect to the shared ClinicReminders settings spreadsheet."""
    try:
        creds_dict = st.secrets["gcp_service_account"]
    except Exception:
        with open("google-credentials.json", "r") as f:
            creds_dict = json.load(f)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SETTINGS_SCOPE)
    client = gspread.authorize(creds)
    return client.open_by_key(SETTINGS_SHEET_ID)


@st.cache_resource(show_spinner=False)
def get_settings_sheet():
    """Connect to the shared ClinicReminders_Settings_Master sheet."""
    return get_or_create_settings_worksheet(get_settings_spreadsheet())


def get_or_create_tracker_sheet(title: str, headers: list[str]):
    cache_key = (str(title), tuple(headers))
    tracker_cache = st.session_state.setdefault("_tracker_sheet_cache", {})
    if cache_key in tracker_cache:
        return tracker_cache[cache_key]

    spreadsheet = get_settings_spreadsheet()
    try:
        worksheet = spreadsheet.worksheet(title)
    except Exception:
        worksheet = spreadsheet.add_worksheet(title=title, rows=1000, cols=max(len(headers), 8))

    first_row = worksheet.row_values(1)
    if first_row[:len(headers)] != headers:
        end_col = _column_number_to_letter(len(headers))
        _gspread_retry(worksheet.update, values=[headers], range_name=f"A1:{end_col}1")
    tracker_cache[cache_key] = worksheet
    return worksheet


def append_tracker_row(title: str, headers: list[str], row_values: list[str]):
    try:
        worksheet = get_or_create_tracker_sheet(title, headers)
        _gspread_retry(worksheet.append_row, row_values, value_input_option="USER_ENTERED")
        if title == ACTION_TRACKER_WORKSHEET:
            invalidate_action_tracker_records_cache()
        return True
    except Exception:
        return False


def append_tracker_rows(title: str, headers: list[str], rows: list[list[str]]):
    rows = [row for row in rows if row]
    if not rows:
        return False
    try:
        worksheet = get_or_create_tracker_sheet(title, headers)
        if hasattr(worksheet, "append_rows"):
            _gspread_retry(worksheet.append_rows, rows, value_input_option="USER_ENTERED")
        else:
            for row in rows:
                _gspread_retry(worksheet.append_row, row, value_input_option="USER_ENTERED")
        if title == ACTION_TRACKER_WORKSHEET:
            invalidate_action_tracker_records_cache()
        return True
    except Exception:
        return False


def tracker_cell_value(value, limit: int = TRACKER_CELL_TEXT_LIMIT) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        try:
            value = json.dumps(value, ensure_ascii=False, default=str)
        except TypeError:
            value = str(value)
    value = str(value).strip()
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)] + "..."


_SENSITIVE_DIAGNOSTIC_KEYS = (
    "access_token",
    "api_key",
    "apikey",
    "client_secret",
    "credential",
    "credentials",
    "password",
    "passwd",
    "pwd",
    "refresh_token",
    "remember",
    "secret",
    "signature",
    "token",
)
_SENSITIVE_DIAGNOSTIC_KEY_PATTERN = "|".join(re.escape(key) for key in _SENSITIVE_DIAGNOSTIC_KEYS)
_SENSITIVE_QUOTED_KV_RX = re.compile(
    rf"(?i)([\"']?(?:{_SENSITIVE_DIAGNOSTIC_KEY_PATTERN})[\"']?\s*[:=]\s*[\"'])([^\"']*)([\"'])"
)
_SENSITIVE_BARE_KV_RX = re.compile(
    rf"(?i)\b((?:{_SENSITIVE_DIAGNOSTIC_KEY_PATTERN})\s*[:=]\s*)([^,\s;&\]\}}]+)"
)
_AUTHORIZATION_BEARER_RX = re.compile(r"(?i)\b(Authorization\s*[:=]\s*)Bearer\s+[A-Za-z0-9._~+/=-]+")
_AUTHORIZATION_VALUE_RX = re.compile(r"(?i)\b(Authorization\s*[:=]\s*)(?!Bearer\b)[^,\s;&\]\}}]+")
_BEARER_TOKEN_RX = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_EMAIL_DIAGNOSTIC_RX = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_LONG_OPAQUE_DIAGNOSTIC_RX = re.compile(r"\b[A-Za-z0-9_-]{20,}\b")


def sanitize_diagnostic_message(value, limit: int = TRACKER_CELL_TEXT_LIMIT) -> str:
    message = tracker_cell_value(value, limit=max(limit * 2, limit))
    if not message:
        return ""

    message = _SENSITIVE_QUOTED_KV_RX.sub(r"\1[redacted]\3", message)
    message = _SENSITIVE_BARE_KV_RX.sub(r"\1[redacted]", message)
    message = _AUTHORIZATION_BEARER_RX.sub(r"\1Bearer [redacted]", message)
    message = _AUTHORIZATION_VALUE_RX.sub(r"\1[redacted]", message)
    message = _BEARER_TOKEN_RX.sub("Bearer [redacted]", message)
    message = _EMAIL_DIAGNOSTIC_RX.sub("[redacted-email]", message)
    message = _LONG_OPAQUE_DIAGNOSTIC_RX.sub("[redacted]", message)
    return tracker_cell_value(message, limit=limit)


def record_dataset_tracker_event(
    event: str,
    status: str,
    file_name: str = "",
    pms: str = "",
    rows: int | str = "",
    from_date: str = "",
    to_date: str = "",
    replace_overlapping_dates: bool | str = "",
    drive_file_id: str = "",
    drive_file_name: str = "",
    message: str = "",
    source: str = "",
    operation_id: str = "",
    now: datetime | None = None,
) -> bool:
    now = now or utc_now()
    safe_drive_file_id = sanitize_diagnostic_message(drive_file_id)
    safe_message = sanitize_diagnostic_message(message)
    return append_tracker_row(DATASET_TRACKER_WORKSHEET, DATASET_TRACKER_HEADERS, [
        gst_now_iso(now),
        tracker_cell_value(event),
        tracker_cell_value(status),
        tracker_cell_value(st.session_state.get("clinic_id", "")),
        tracker_cell_value(st.session_state.get("user_name", "")),
        tracker_cell_value(file_name),
        tracker_cell_value(pms),
        tracker_cell_value(rows),
        tracker_cell_value(from_date),
        tracker_cell_value(to_date),
        tracker_cell_value(replace_overlapping_dates),
        tracker_cell_value(safe_drive_file_id),
        tracker_cell_value(drive_file_name),
        tracker_cell_value(safe_message),
        tracker_cell_value(source),
        tracker_cell_value(operation_id),
    ])


def record_settings_audit_event(
    event: str,
    area: str,
    item: str = "",
    field: str = "",
    old_value="",
    new_value="",
    source: str = "",
    now: datetime | None = None,
) -> bool:
    now = now or utc_now()
    return append_tracker_row(SETTINGS_AUDIT_WORKSHEET, SETTINGS_AUDIT_HEADERS, [
        gst_now_iso(now),
        tracker_cell_value(st.session_state.get("clinic_id", "")),
        tracker_cell_value(st.session_state.get("user_name", "")),
        tracker_cell_value(event),
        tracker_cell_value(area),
        tracker_cell_value(item),
        tracker_cell_value(field),
        tracker_cell_value(old_value),
        tracker_cell_value(new_value),
        tracker_cell_value(source),
    ])


def make_dataset_publish_operation_id() -> str:
    return f"dataset-publish-{uuid.uuid4().hex[:12]}"


def record_error_tracker_event(
    event: str,
    stage: str = "",
    error: Exception | None = None,
    message: str = "",
    source: str = "",
    now: datetime | None = None,
) -> bool:
    now = now or utc_now()
    error_type = type(error).__name__ if error is not None else ""
    error_message = sanitize_diagnostic_message(message or (str(error) if error is not None else ""))
    return append_tracker_row(ERROR_TRACKER_WORKSHEET, ERROR_TRACKER_HEADERS, [
        gst_now_iso(now),
        tracker_cell_value(st.session_state.get("clinic_id", "")),
        tracker_cell_value(st.session_state.get("user_name", "")),
        tracker_cell_value(event),
        tracker_cell_value(stage),
        tracker_cell_value(error_type),
        tracker_cell_value(error_message),
        tracker_cell_value(source),
    ])


def record_performance_tracker_event(
    event: str,
    duration_ms: int | float,
    rows: int | str = "",
    status: str = "success",
    message: str = "",
    source: str = "",
    now: datetime | None = None,
) -> bool:
    now = now or utc_now()
    try:
        duration_value = str(int(round(float(duration_ms))))
    except (TypeError, ValueError):
        duration_value = tracker_cell_value(duration_ms)
    safe_message = sanitize_diagnostic_message(message)
    return append_tracker_row(PERFORMANCE_TRACKER_WORKSHEET, PERFORMANCE_TRACKER_HEADERS, [
        gst_now_iso(now),
        tracker_cell_value(st.session_state.get("clinic_id", "")),
        tracker_cell_value(st.session_state.get("user_name", "")),
        tracker_cell_value(event),
        duration_value,
        tracker_cell_value(rows),
        tracker_cell_value(status),
        tracker_cell_value(safe_message),
        tracker_cell_value(source),
    ])


def account_lifecycle_clinic_ref(clinic_id: str) -> str:
    clinic_key = normalize_clinic_id_key(clinic_id)
    if not clinic_key:
        return ""
    digest = hmac.new(
        str(SETTINGS_SHEET_ID or "clinic-reminders").encode("utf-8"),
        clinic_key.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return digest[:16]


def record_account_lifecycle_event(
    clinic_id: str,
    event: str,
    status: str = "success",
    clinic_name: str = "",
    auth_provider: str = "",
    country: str = "",
    deleted_rows: int | str = "",
    trashed_data_file: bool | str = "",
    message: str = "",
    source: str = "",
    now: datetime | None = None,
) -> bool:
    clinic_ref = account_lifecycle_clinic_ref(clinic_id)
    if not clinic_ref:
        return False
    now = now or utc_now()
    return append_tracker_row(ACCOUNT_LIFECYCLE_WORKSHEET, ACCOUNT_LIFECYCLE_HEADERS, [
        gst_now_iso(now),
        tracker_cell_value(event),
        tracker_cell_value(status),
        tracker_cell_value(clinic_ref),
        tracker_cell_value(clinic_name or clinic_id),
        tracker_cell_value(auth_provider),
        tracker_cell_value(country),
        tracker_cell_value(deleted_rows),
        tracker_cell_value(trashed_data_file),
        tracker_cell_value(sanitize_diagnostic_message(message)),
        tracker_cell_value(source),
    ])


def account_lifecycle_clinic_name_map_from_values(
    settings_values: list[list[str]] | None = None,
    user_tracker_values: list[list[str]] | None = None,
) -> dict[str, str]:
    clinic_names_by_ref: dict[str, str] = {}

    settings_headers = list((settings_values or [[]])[0] or [])
    if SHEET_COL_CLINIC_ID in settings_headers:
        clinic_id_idx = settings_headers.index(SHEET_COL_CLINIC_ID)
        for values in (settings_values or [])[1:]:
            if not values:
                continue
            clinic_id = str(values[clinic_id_idx] if len(values) > clinic_id_idx else "").strip()
            if clinic_id:
                clinic_ref = account_lifecycle_clinic_ref(clinic_id)
                if clinic_ref:
                    clinic_names_by_ref[clinic_ref] = clinic_id

    if user_tracker_values:
        headers = list(user_tracker_values[0] or [])
        if SHEET_COL_CLINIC_ID in headers:
            clinic_id_idx = headers.index(SHEET_COL_CLINIC_ID)
            for values in user_tracker_values[1:]:
                clinic_id = str(values[clinic_id_idx] if len(values) > clinic_id_idx else "").strip()
                if clinic_id:
                    clinic_ref = account_lifecycle_clinic_ref(clinic_id)
                    if clinic_ref:
                        clinic_names_by_ref.setdefault(clinic_ref, clinic_id)

    return clinic_names_by_ref


def is_legacy_account_lifecycle_row(row: list[str]) -> bool:
    padded = list(row) + [""] * len(ACCOUNT_LIFECYCLE_HEADERS)
    auth_candidate = str(padded[4] or "").strip().lower()
    return len(row) <= len(ACCOUNT_LIFECYCLE_HEADERS) - 1 and auth_candidate in ACCOUNT_LIFECYCLE_AUTH_PROVIDERS


def normalize_account_lifecycle_row(row: list[str], clinic_names_by_ref: dict[str, str] | None = None) -> list[str]:
    clinic_names_by_ref = clinic_names_by_ref or {}
    padded = list(row) + [""] * len(ACCOUNT_LIFECYCLE_HEADERS)
    clinic_ref = str(padded[3] or "").strip()

    if is_legacy_account_lifecycle_row(row):
        return [
            padded[0],
            padded[1],
            padded[2],
            padded[3],
            clinic_names_by_ref.get(clinic_ref, ""),
            padded[4],
            padded[5],
            padded[6],
            padded[7],
            padded[8],
            padded[9],
        ]

    normalized = padded[:len(ACCOUNT_LIFECYCLE_HEADERS)]
    if not str(normalized[4] or "").strip() and clinic_ref in clinic_names_by_ref:
        normalized[4] = clinic_names_by_ref[clinic_ref]
    return normalized


def repair_account_lifecycle_rows(worksheet, clinic_names_by_ref: dict[str, str] | None = None) -> int:
    values = _gspread_retry(worksheet.get_all_values) or []
    if len(values) <= 1:
        return 0

    updates = []
    end_col = _column_number_to_letter(len(ACCOUNT_LIFECYCLE_HEADERS))
    for row_idx, row in enumerate(values[1:], start=2):
        normalized = normalize_account_lifecycle_row(row, clinic_names_by_ref)
        current = (list(row) + [""] * len(ACCOUNT_LIFECYCLE_HEADERS))[:len(ACCOUNT_LIFECYCLE_HEADERS)]
        if normalized != current:
            updates.append({
                "range": f"A{row_idx}:{end_col}{row_idx}",
                "values": [normalized],
            })

    if updates:
        _gspread_retry(worksheet.batch_update, updates)
    return len(updates)


def repair_account_lifecycle_sheet(spreadsheet, worksheet) -> int:
    values = _gspread_retry(worksheet.get_all_values) or []
    if len(values) <= 1:
        return 0

    needs_repair = False
    needs_backfill = False
    for row in values[1:]:
        normalized_without_backfill = normalize_account_lifecycle_row(row, {})
        current = (list(row) + [""] * len(ACCOUNT_LIFECYCLE_HEADERS))[:len(ACCOUNT_LIFECYCLE_HEADERS)]
        if normalized_without_backfill != current:
            needs_repair = True
            break
        if str(current[3] or "").strip() and not str(current[4] or "").strip():
            needs_backfill = True

    if not needs_repair and not needs_backfill:
        return 0

    settings_values = []
    user_tracker_values = []
    try:
        settings_values = _gspread_retry(get_or_create_settings_worksheet(spreadsheet).get_all_values) or []
    except Exception:
        settings_values = []
    try:
        user_tracker_values = _gspread_retry(spreadsheet.worksheet(USER_TRACKER_WORKSHEET).get_all_values) or []
    except Exception:
        user_tracker_values = []

    clinic_names_by_ref = account_lifecycle_clinic_name_map_from_values(settings_values, user_tracker_values)
    return repair_account_lifecycle_rows(worksheet, clinic_names_by_ref)


@st.cache_resource(show_spinner=False)
def ensure_tracking_sheets_once():
    spreadsheet = get_settings_spreadsheet()
    existing = {worksheet.title: worksheet for worksheet in spreadsheet.worksheets()}
    for title, headers in TRACKER_SHEET_DEFINITIONS:
        worksheet = existing.get(title)
        if worksheet is None:
            worksheet = spreadsheet.add_worksheet(title=title, rows=1000, cols=max(len(headers), 8))
        first_row = worksheet.row_values(1)
        if first_row[:len(headers)] != headers:
            end_col = _column_number_to_letter(len(headers))
            _gspread_retry(worksheet.update, values=[headers], range_name=f"A1:{end_col}1")
        if title == ACCOUNT_LIFECYCLE_WORKSHEET:
            try:
                repair_account_lifecycle_sheet(spreadsheet, worksheet)
            except Exception:
                pass
    return True


def ensure_tracking_sheets():
    if not st.session_state.get("clinic_id"):
        return
    try:
        ensure_tracking_sheets_once()
    except Exception:
        return


# === LOGIN HELPER FUNCTIONS ===
def hash_pw(pw: str):
    """Return the legacy MD5 hash used by older clinic rows."""
    return hashlib.md5(str(pw or "").encode("utf-8")).hexdigest()


def password_hash_for_storage(password: str) -> str:
    """Return a salted password hash for new/changed clinic passwords."""
    salt = base64.urlsafe_b64encode(os.urandom(PASSWORD_SALT_BYTES)).decode("ascii").rstrip("=")
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        str(password or "").encode("utf-8"),
        salt.encode("utf-8"),
        PASSWORD_HASH_ITERATIONS,
    )
    digest_b64 = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return f"{PASSWORD_HASH_ALGORITHM}${PASSWORD_HASH_ITERATIONS}${salt}${digest_b64}"


def verify_password(password: str, stored_hash: str) -> bool:
    stored_hash = str(stored_hash or "").strip()
    if not stored_hash:
        return False

    parts = stored_hash.split("$")
    if len(parts) == 4 and parts[0] == PASSWORD_HASH_ALGORITHM:
        try:
            iterations = int(parts[1])
            salt = parts[2]
            expected = parts[3]
        except (TypeError, ValueError):
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            str(password or "").encode("utf-8"),
            salt.encode("utf-8"),
            iterations,
        )
        digest_b64 = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        return hmac.compare_digest(digest_b64, expected)

    return hmac.compare_digest(stored_hash, hash_pw(password))


def password_policy_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def password_policy_error(password: str, clinic_id: str = "") -> str:
    password_text = str(password or "")
    if len(password_text) < PASSWORD_MIN_LENGTH:
        return f"Password must be at least {PASSWORD_MIN_LENGTH} characters."

    password_key = password_policy_key(password_text)
    if not password_key:
        return "Password must include letters or numbers."

    for common_key in COMMON_PASSWORD_KEYS:
        if password_key == common_key or password_key.startswith(common_key):
            return "Choose a less common password."

    clinic_key = password_policy_key(clinic_id)
    if len(clinic_key) >= 4 and clinic_key in password_key:
        return "Password cannot include the clinic name."

    return ""


def validate_password_policy(password: str, clinic_id: str = "") -> None:
    error = password_policy_error(password, clinic_id)
    if error:
        raise ValueError(error)


def normalize_email(value: str) -> str:
    return str(value or "").strip().lower()


def normalize_clinic_id_key(value) -> str:
    if value is None:
        return ""
    try:
        if bool(value != value):
            return ""
    except Exception:
        pass
    return str(value).strip().lower()


def get_google_user_info(user_info=None) -> dict:
    user_info = st.user if user_info is None else user_info
    is_logged_in_attr = getattr(user_info, "is_logged_in", False)
    try:
        data = dict(user_info)
    except Exception:
        data = {}

    email = normalize_email(data.get("email", ""))
    subject = str(data.get("sub") or data.get("user_id") or "").strip()
    name = str(data.get("name") or data.get("given_name") or email).strip()
    has_google_identity = bool(email or subject)
    is_logged_in = has_google_identity and (is_logged_in_attr is True or data.get("is_logged_in") is True)
    return {
        "is_logged_in": is_logged_in,
        "email": email,
        "subject": subject,
        "name": name,
    }


def begin_google_login():
    try:
        st.login(GOOGLE_AUTH_PROVIDER)
    except Exception:
        st.session_state["google_signup_error"] = (
            "Google sign-up is not configured yet. Please use Sign Up or contact support."
        )


def google_identity_matches_row(row: dict, google_user: dict) -> bool:
    row_subject = str(row.get(SHEET_COL_GOOGLE_SUBJECT, "")).strip()
    row_email = normalize_email(row.get(SHEET_COL_GOOGLE_EMAIL, ""))
    google_subject = str(google_user.get("subject", "")).strip()
    google_email = normalize_email(google_user.get("email", ""))
    if row_subject:
        return bool(google_subject and hmac.compare_digest(row_subject, google_subject))
    return bool(row_email and google_email and hmac.compare_digest(row_email, google_email))


def authenticate_user(username, password):
    """Check username/password pair against the sheet."""
    sheet = get_settings_sheet()
    records = sheet.get_all_records()
    username_key = normalize_clinic_id_key(username)
    for r in records:
        if normalize_clinic_id_key(r.get("ClinicID", "")) == username_key:
            if verify_password(password, r.get("PasswordHash", "")):
                return r
    return None

def get_clinic_row(username):
    """Return a clinic row by ClinicID without checking password."""
    sheet = get_settings_sheet()
    records = sheet.get_all_records()
    username_key = normalize_clinic_id_key(username)
    for r in records:
        if normalize_clinic_id_key(r.get("ClinicID", "")) == username_key:
            return r
    return None


def get_clinic_row_by_google_identity(google_user: dict):
    if not google_user.get("is_logged_in"):
        return None
    sheet = get_settings_sheet()
    records = sheet.get_all_records()
    for row in records:
        if google_identity_matches_row(row, google_user):
            return row
    return None


def _remember_login_signature(clinic_id: str, expires_at: int, password_hash: str) -> str:
    payload = f"{clinic_id.strip().lower()}|{expires_at}"
    return hmac.new(
        str(password_hash or "").encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _legacy_remember_login_signature(clinic_id: str, expires_at: int, password_hash: str) -> str:
    payload = f"{clinic_id.strip().lower()}|{expires_at}|{password_hash}"
    return hmac.new(
        str(SETTINGS_SHEET_ID).encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def create_remember_login_token(clinic_id: str, user_row: dict | None = None, days: int = REMEMBER_LOGIN_DAYS) -> str:
    clinic_id = str(clinic_id or "").strip()
    user_row = user_row or get_clinic_row(clinic_id)
    password_hash = str((user_row or {}).get("PasswordHash", "")).strip()
    if not clinic_id or not password_hash:
        return ""

    expires_at = int(time.time() + days * 24 * 60 * 60)
    signature = _remember_login_signature(clinic_id, expires_at, password_hash)
    raw = json.dumps({"clinic_id": clinic_id, "expires_at": expires_at, "signature": signature}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def validate_remember_login_token(token: str) -> str | None:
    try:
        raw = base64.urlsafe_b64decode(str(token or "").encode("ascii")).decode("utf-8")
        payload = json.loads(raw)
    except Exception:
        return None

    clinic_id = str(payload.get("clinic_id", "")).strip()
    expires_at = int(payload.get("expires_at", 0) or 0)
    signature = str(payload.get("signature", "")).strip()
    if not clinic_id or not signature or expires_at < int(time.time()):
        return None

    user_row = get_clinic_row(clinic_id)
    password_hash = str((user_row or {}).get("PasswordHash", "")).strip()
    if not password_hash:
        return None

    expected = _remember_login_signature(clinic_id, expires_at, password_hash)
    legacy_expected = _legacy_remember_login_signature(clinic_id, expires_at, password_hash)
    if hmac.compare_digest(signature, expected) or hmac.compare_digest(signature, legacy_expected):
        return clinic_id
    return None


def get_query_param(name: str) -> str:
    try:
        value = st.query_params.get(name, "")
    except Exception:
        value = (st.experimental_get_query_params().get(name, [""]) or [""])[0]
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return str(value or "")


def set_query_param(name: str, value: str):
    try:
        st.query_params[name] = value
    except Exception:
        params = st.experimental_get_query_params()
        params[name] = [value]
        st.experimental_set_query_params(**params)


def clear_query_param(name: str):
    try:
        if name in st.query_params:
            del st.query_params[name]
    except Exception:
        params = st.experimental_get_query_params()
        params.pop(name, None)
        st.experimental_set_query_params(**params)


def set_remember_login_token(token: str):
    """Legacy compatibility wrapper. Remember tokens must not be stored in URLs."""
    clear_remember_login_token()


def clear_remember_login_token():
    clear_query_param(REMEMBER_LOGIN_QUERY_PARAM)


def discard_remember_login_query_param() -> bool:
    if get_query_param(REMEMBER_LOGIN_QUERY_PARAM):
        clear_remember_login_token()
        return True
    return False


def default_settings_for_country(country: str = "") -> dict:
    return {
        "rules": DEFAULT_RULES.copy(),
        "exclusions": [],
        "client_exclusions": [],
        "patient_exclusions": [],
        "automatic_patient_exclusions": [],
        "patient_passaway_keywords": PATIENT_PASSAWAY_KEYWORDS_DEFAULT.copy(),
        "user_name": "",
        "user_template": DEFAULT_WA_TEMPLATE,
        "client_group_days": 1,
        "reminder_window_days": 1,
        "reminder_lookback_days": DEFAULT_REMINDER_LOOKBACK_DAYS,
        "reminder_warning_days": 0,
        "outcome_due_date_window_days": DEFAULT_OUTCOME_DUE_DATE_WINDOW_DAYS,
        "action_tracker_migrated_at": "",
        "search_terms_reviewed": False,
        "search_term_added": False,
        "wa_template_reviewed": False,
        "wa_template_updated": False,
        "get_started_reset_at": "",
        "search_term_added_at": "",
        "user_name_updated_at": "",
        "wa_template_updated_at": "",
        "dataset_upload_history": [],
        "country": country,
    }


def upsert_user_tracker(clinic_id: str, country: str = "", event: str = "updated", now: datetime | None = None):
    clinic_id = str(clinic_id or "").strip()
    if not clinic_id:
        return

    timestamp = gst_now_iso(now)
    country = str(country or "").strip()
    try:
        sheet = get_or_create_tracker_sheet(USER_TRACKER_WORKSHEET, USER_TRACKER_HEADERS)
        rows = _gspread_retry(sheet.get_all_values) or []
        headers = rows[0] if rows else USER_TRACKER_HEADERS
        clinic_ix = headers.index("ClinicID")
        row_idx = None
        for i, row in enumerate(rows[1:], start=2):
            if len(row) > clinic_ix and str(row[clinic_ix]).strip().lower() == clinic_id.lower():
                row_idx = i
                break

        existing = {}
        if row_idx and len(rows) >= row_idx:
            existing = {
                header: rows[row_idx - 1][idx] if idx < len(rows[row_idx - 1]) else ""
                for idx, header in enumerate(headers)
            }

        created_at = existing.get("CreatedAtGST") or timestamp
        last_login = timestamp if event in LOGIN_TRACKER_EVENTS else existing.get("LastLoginAtGST", "")
        values_by_header = {
            "ClinicID": clinic_id,
            "Country": country or existing.get("Country", ""),
            "CreatedAtGST": created_at,
            "LastUpdatedAtGST": timestamp,
            "LastLoginAtGST": last_login,
            "AccountStatus": existing.get("AccountStatus") or "active",
            "LastEvent": event,
        }
        row_values = [values_by_header.get(header, "") for header in USER_TRACKER_HEADERS]

        if row_idx:
            end_col = _column_number_to_letter(len(USER_TRACKER_HEADERS))
            _gspread_retry(sheet.update, values=[row_values], range_name=f"A{row_idx}:{end_col}{row_idx}")
        else:
            _gspread_retry(sheet.append_row, row_values, value_input_option="USER_ENTERED")
    except Exception:
        return


def record_settings_account_event(
    clinic_id: str,
    event: str,
    auth_provider: str = "",
    country: str = "",
    now: datetime | None = None,
) -> None:
    clinic_id = str(clinic_id or "").strip()
    if not clinic_id:
        return

    values_by_header = {SHEET_COL_ACCOUNT_STATUS: "active"}
    country = str(country or "").strip()
    if country:
        values_by_header[SHEET_COL_COUNTRY] = country
    if event in LOGIN_TRACKER_EVENTS:
        values_by_header[SHEET_COL_LAST_LOGIN_AT_GST] = gst_now_iso(now)
        values_by_header[SHEET_COL_LAST_LOGIN_PROVIDER] = auth_provider or event
    if not values_by_header:
        return

    try:
        update_settings_row_fields(clinic_id, values_by_header, SETTINGS_REQUIRED_COLUMNS)
    except Exception:
        return


def create_clinic_account(clinic_id: str, country: str, password: str):
    clinic_id = str(clinic_id or "").strip()
    country = str(country or "").strip()
    password = str(password or "")
    if not clinic_id:
        raise ValueError("Enter a clinic name.")
    validate_password_policy(password, clinic_id)
    if get_clinic_row(clinic_id):
        raise ValueError("That clinic name is already registered.")

    sheet = get_settings_sheet()
    all_vals = _gspread_retry(sheet.get_all_values)
    headers = all_vals[0] if all_vals else list(SETTINGS_REQUIRED_COLUMNS)
    headers = ensure_settings_sheet_columns(sheet, headers, SETTINGS_REQUIRED_COLUMNS)
    settings_json = json.dumps(default_settings_for_country(country))
    password_hash = password_hash_for_storage(password)
    created_at_gst = gst_now_iso()
    values_by_header = {
        SHEET_COL_CLINIC_ID: clinic_id,
        SHEET_COL_PASSWORD_HASH: password_hash,
        SHEET_COL_SETTINGS_JSON: settings_json,
        SHEET_COL_UPDATED_AT: utc_now_iso(),
        SHEET_COL_COUNTRY: country,
        SHEET_COL_CREATED_AT_GST: created_at_gst,
        SHEET_COL_LAST_LOGIN_AT_GST: created_at_gst,
        SHEET_COL_LAST_LOGIN_PROVIDER: "password",
        SHEET_COL_ACCOUNT_STATUS: "active",
    }
    _gspread_retry(sheet.append_row, settings_row_values(headers, values_by_header), value_input_option="USER_ENTERED")
    upsert_user_tracker(clinic_id, country=country, event="created")
    record_account_lifecycle_event(
        clinic_id,
        "created",
        clinic_name=clinic_id,
        auth_provider="password",
        country=country,
        source="password_signup",
    )
    return password_hash


def create_google_clinic_account(clinic_id: str, country: str, google_user: dict):
    clinic_id = str(clinic_id or "").strip()
    country = str(country or "").strip()
    google_user = google_user or {}
    email = normalize_email(google_user.get("email", ""))
    if not clinic_id:
        raise ValueError("Enter a clinic name.")
    if not email:
        raise ValueError("Google did not return an email address. Please try again.")
    if get_clinic_row(clinic_id):
        raise ValueError("That clinic name is already registered.")

    existing_google_row = get_clinic_row_by_google_identity({
        **google_user,
        "is_logged_in": True,
        "email": email,
    })
    if existing_google_row:
        raise ValueError("That Google account is already linked to a clinic.")

    sheet = get_settings_sheet()
    all_vals = _gspread_retry(sheet.get_all_values)
    headers = all_vals[0] if all_vals else list(SETTINGS_REQUIRED_COLUMNS)
    headers = ensure_settings_sheet_columns(sheet, headers, SETTINGS_REQUIRED_COLUMNS)
    settings_json = json.dumps(default_settings_for_country(country))
    created_at_gst = gst_now_iso()
    values_by_header = {
        SHEET_COL_CLINIC_ID: clinic_id,
        SHEET_COL_PASSWORD_HASH: "",
        SHEET_COL_SETTINGS_JSON: settings_json,
        SHEET_COL_UPDATED_AT: utc_now_iso(),
        SHEET_COL_AUTH_PROVIDER: GOOGLE_AUTH_PROVIDER,
        SHEET_COL_GOOGLE_EMAIL: email,
        SHEET_COL_GOOGLE_SUBJECT: str(google_user.get("subject", "")).strip(),
        SHEET_COL_GOOGLE_NAME: str(google_user.get("name", "")).strip(),
        SHEET_COL_COUNTRY: country,
        SHEET_COL_CREATED_AT_GST: created_at_gst,
        SHEET_COL_LAST_LOGIN_AT_GST: created_at_gst,
        SHEET_COL_LAST_LOGIN_PROVIDER: GOOGLE_AUTH_PROVIDER,
        SHEET_COL_ACCOUNT_STATUS: "active",
    }
    _gspread_retry(sheet.append_row, settings_row_values(headers, values_by_header), value_input_option="USER_ENTERED")
    upsert_user_tracker(clinic_id, country=country, event="google_created")
    record_account_lifecycle_event(
        clinic_id,
        "created",
        clinic_name=clinic_id,
        auth_provider=GOOGLE_AUTH_PROVIDER,
        country=country,
        source="google_signup",
    )
    return values_by_header


def google_onboarding_dialog_html(google_user: dict, mode: str = "signup") -> str:
    email = normalize_email(google_user.get("email", ""))
    if mode == "recreate_after_delete":
        title = "Your clinic account was deleted"
        body = (
            f"You're still signed in with Google{f' as {html_lib.escape(email)}' if email else ''}. "
            "Add a clinic name and country to create a fresh clinic account."
        )
        note = "The previous clinic account and saved data were removed. Next time, use Continue with Google to return to the new clinic account."
    else:
        title = "Welcome to Clinic Reminders!"
        body = (
            f"You're signed in with Google{f' as {html_lib.escape(email)}' if email else ''}. "
            "Add your clinic name and country to create your clinic account."
        )
        note = "Next time, use Continue with Google. Your Google password is never entered or stored in Clinic Reminders."
    return f"""
    <style>
      .google-onboarding-hero {{
        background: linear-gradient(135deg, #e8fff2 0%, #ffffff 100%);
        border: 1px solid rgba(41, 210, 114, 0.28);
        border-radius: 8px;
        margin-bottom: 1rem;
        padding: 1rem 1.05rem;
      }}
      .google-onboarding-hero h3 {{
        color: #101828;
        font-size: 1.25rem;
        font-weight: 850;
        letter-spacing: 0;
        line-height: 1.2;
        margin: 0 0 0.35rem;
      }}
      .google-onboarding-hero p {{
        color: #40566b;
        font-size: 0.98rem;
        line-height: 1.45;
        margin: 0;
      }}
      .google-onboarding-note {{
        background: #f8fafc;
        border: 1px solid rgba(15, 23, 42, 0.08);
        border-radius: 8px;
        color: #526174;
        font-size: 0.9rem;
        line-height: 1.45;
        margin-top: 0.8rem;
        padding: 0.75rem 0.85rem;
      }}
    </style>
    <div class="google-onboarding-hero">
      <h3>{title}</h3>
      <p>{body}</p>
    </div>
    <div class="google-onboarding-note">{note}</div>
    """


def render_google_onboarding_dialog(google_user: dict):
    onboarding_mode = st.session_state.get("google_onboarding_mode", "signup")
    submit_label = "Create new clinic account" if onboarding_mode == "recreate_after_delete" else "Create clinic account"

    def _render_dialog_body():
        st.markdown(google_onboarding_dialog_html(google_user, onboarding_mode), unsafe_allow_html=True)
        with st.form("google_onboarding_form"):
            default_clinic_name = st.session_state.get("google_onboarding_clinic_name", "")
            google_clinic = st.text_input("Clinic name", value=default_clinic_name, key="google_onboarding_clinic_name").strip()
            google_country = st.selectbox("Country", COUNTRY_OPTIONS, key="google_onboarding_country")
            google_submitted = st.form_submit_button(submit_label, type="primary", use_container_width=True)

        if google_submitted:
            signup_allowed, retry_after = signup_attempt_allowed()
            if not signup_allowed:
                st.error(auth_retry_message("sign-up", retry_after))
            else:
                record_signup_attempt()
                try:
                    create_google_clinic_account(google_clinic, google_country, google_user)
                    st.session_state["user_country"] = google_country
                    st.session_state.pop("pending_google_signup", None)
                    st.session_state.pop("google_onboarding_mode", None)
                    finish_authenticated_session(
                        google_clinic,
                        event="google_login",
                        auth_provider=GOOGLE_AUTH_PROVIDER,
                        google_user=google_user,
                    )
                    mark_new_account_welcome_pending()
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))
                except Exception:
                    st.error("Could not create your clinic account. Please try again or contact support.")

        if st.button("Use another Google account", key="google_onboarding_logout", use_container_width=True):
            st.session_state.pop("pending_google_signup", None)
            st.session_state.pop("google_onboarding_mode", None)
            if callable(getattr(st, "logout", None)):
                st.logout()
            else:
                st.rerun()

    if hasattr(st, "dialog"):
        @st.dialog("Set up your clinic")
        def _google_onboarding_dialog():
            _render_dialog_body()
        _google_onboarding_dialog()
    elif hasattr(st, "experimental_dialog"):
        @st.experimental_dialog("Set up your clinic")
        def _google_onboarding_dialog():
            _render_dialog_body()
        _google_onboarding_dialog()
    else:
        with st.expander("Set up your clinic", expanded=True):
            _render_dialog_body()


def get_clinic_profile(clinic_id: str) -> dict:
    row = get_clinic_row(clinic_id) or {}
    return {
        "clinic_id": str(row.get("ClinicID") or clinic_id or "").strip(),
        "email": normalize_email(row.get(SHEET_COL_GOOGLE_EMAIL, "")),
        "auth_provider": str(row.get(SHEET_COL_AUTH_PROVIDER, "")).strip(),
    }


def update_rows_with_clinic_id(old_clinic_id: str, new_clinic_id: str) -> int:
    old_key = str(old_clinic_id or "").strip().lower()
    new_clinic_id = str(new_clinic_id or "").strip()
    if not old_key or not new_clinic_id:
        return 0

    updated = 0
    spreadsheet = get_settings_spreadsheet()
    for worksheet in spreadsheet.worksheets():
        values = _gspread_retry(worksheet.get_all_values) or []
        if not values or "ClinicID" not in values[0]:
            continue
        headers = values[0]
        clinic_col = headers.index("ClinicID") + 1
        updates = []
        for row_idx, row_values in enumerate(values[1:], start=2):
            current = row_values[clinic_col - 1] if len(row_values) >= clinic_col else ""
            if str(current or "").strip().lower() == old_key:
                updates.append({
                    "range": _row_range_a1(row_idx, clinic_col, clinic_col),
                    "values": [[new_clinic_id]],
                })
        if updates:
            _gspread_retry(worksheet.batch_update, updates)
            updated += len(updates)
    st.session_state.pop("_settings_row_cache", None)
    return updated


def update_clinic_profile(old_clinic_id: str, new_clinic_id: str, email: str) -> dict:
    old_clinic_id = str(old_clinic_id or "").strip()
    new_clinic_id = str(new_clinic_id or "").strip()
    email = normalize_email(email)
    if not new_clinic_id:
        raise ValueError("Enter a clinic name.")
    if email and ("@" not in email or "." not in email.split("@")[-1]):
        raise ValueError("Enter a valid email address.")

    existing = get_clinic_row(new_clinic_id)
    if existing and new_clinic_id.lower() != old_clinic_id.lower():
        raise ValueError("That clinic name is already registered.")

    old_clinic_id = require_authenticated_tenant_access(old_clinic_id)
    old_row = get_clinic_row(old_clinic_id) or {}
    stored_auth_provider = str(old_row.get(SHEET_COL_AUTH_PROVIDER, "")).strip()
    stored_google_subject = str(old_row.get(SHEET_COL_GOOGLE_SUBJECT, "")).strip()
    stored_google_email = normalize_email(old_row.get(SHEET_COL_GOOGLE_EMAIL, ""))
    google_identity_locked = stored_auth_provider == GOOGLE_AUTH_PROVIDER or bool(stored_google_subject)
    if google_identity_locked:
        if email and email != stored_google_email:
            raise ValueError("Google sign-in email is managed by Google and cannot be changed here.")
        email = stored_google_email
    updated_at = utc_now_iso()
    values_by_header = {
        "ClinicID": new_clinic_id,
        "UpdatedAt": updated_at,
    }
    if not google_identity_locked:
        values_by_header[SHEET_COL_GOOGLE_EMAIL] = email
    file_id = str(old_row.get(SHEET_COL_DATASET_FILE_ID, "")).strip()
    if file_id and new_clinic_id.lower() != old_clinic_id.lower():
        new_filename = f"{new_clinic_id}_shared_dataset.csv"
        try:
            require_clinic_dataset_file_access(old_clinic_id, file_id)
            drive_rename_file(
                file_id,
                new_filename,
                clinic_id=old_clinic_id,
                current_file_id=file_id,
            )
            require_clinic_dataset_file_access(old_clinic_id, file_id)
            values_by_header[SHEET_COL_DATASET_FILE_NAME] = new_filename
        except Exception as e:
            raise RuntimeError(
                "Could not update the saved clinic data for this clinic. "
                "Please try again before changing the clinic name."
            ) from e

    update_settings_row_fields(old_clinic_id, values_by_header, GOOGLE_ACCOUNT_COLUMNS)
    if new_clinic_id.lower() != old_clinic_id.lower():
        update_rows_with_clinic_id(old_clinic_id, new_clinic_id)
    return {"clinic_id": new_clinic_id, "email": email}


def delete_rows_matching_clinic_id(worksheet, clinic_ids: set[str]) -> int:
    clinic_keys = {str(value or "").strip().lower() for value in clinic_ids if str(value or "").strip()}
    if not clinic_keys:
        return 0

    values = _gspread_retry(worksheet.get_all_values) or []
    if not values or "ClinicID" not in values[0]:
        return 0
    clinic_col = values[0].index("ClinicID") + 1
    rows_to_delete = []
    for row_idx, row_values in enumerate(values[1:], start=2):
        current = row_values[clinic_col - 1] if len(row_values) >= clinic_col else ""
        if str(current or "").strip().lower() in clinic_keys:
            rows_to_delete.append(row_idx)

    row_ranges = compact_row_ranges_for_delete(rows_to_delete)
    delete_worksheet_row_ranges(worksheet, row_ranges)
    return len(rows_to_delete)


def compact_row_ranges_for_delete(row_indexes: list[int]) -> list[tuple[int, int]]:
    """Return 1-based inclusive row ranges, ordered bottom-up for safe deletion."""
    sorted_rows = sorted({int(row) for row in row_indexes if int(row) > 1})
    if not sorted_rows:
        return []

    ranges: list[tuple[int, int]] = []
    start = end = sorted_rows[0]
    for row_idx in sorted_rows[1:]:
        if row_idx == end + 1:
            end = row_idx
            continue
        ranges.append((start, end))
        start = end = row_idx
    ranges.append((start, end))
    return list(reversed(ranges))


def delete_worksheet_row_ranges(worksheet, row_ranges: list[tuple[int, int]]) -> None:
    if not row_ranges:
        return

    sheet_id = getattr(worksheet, "id", None)
    spreadsheet_id = getattr(worksheet, "spreadsheet_id", None)
    client = getattr(worksheet, "client", None)
    if sheet_id is not None and spreadsheet_id and client is not None and hasattr(client, "batch_update"):
        requests = [
            {
                "deleteDimension": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "ROWS",
                        "startIndex": start - 1,
                        "endIndex": end,
                    }
                }
            }
            for start, end in row_ranges
        ]
        _gspread_retry(client.batch_update, spreadsheet_id, {"requests": requests})
        return

    for start, end in row_ranges:
        if start == end:
            _gspread_retry(worksheet.delete_rows, start)
        else:
            _gspread_retry(worksheet.delete_rows, start, end)


def delete_clinic_account_and_data(clinic_id: str) -> dict:
    clinic_id = str(clinic_id or "").strip()
    if not clinic_id:
        raise ValueError("No clinic is currently signed in.")
    clinic_id = require_authenticated_tenant_access(clinic_id)

    row = get_clinic_row(clinic_id)
    if not row:
        raise ValueError("This clinic account could not be found.")

    file_id = str(row.get(SHEET_COL_DATASET_FILE_ID, "")).strip()
    auth_provider = str(row.get(SHEET_COL_LAST_LOGIN_PROVIDER) or row.get(SHEET_COL_AUTH_PROVIDER) or "").strip()
    country = str(row.get(SHEET_COL_COUNTRY, "")).strip()
    if file_id:
        require_clinic_dataset_file_access(clinic_id, file_id, current_file_id=file_id)
    spreadsheet = get_settings_spreadsheet()
    deleted_rows = 0
    for worksheet in spreadsheet.worksheets():
        deleted_rows += delete_rows_matching_clinic_id(worksheet, {clinic_id})

    if file_id:
        drive_trash_file(file_id, clinic_id=clinic_id, current_file_id=file_id)

    record_account_lifecycle_event(
        clinic_id,
        "deleted",
        clinic_name=clinic_id,
        auth_provider=auth_provider,
        country=country,
        deleted_rows=deleted_rows,
        trashed_data_file=bool(file_id),
        source="delete_account_and_data",
    )

    st.session_state.pop("_settings_row_cache", None)
    st.session_state.pop("_remote_settings_cache", None)
    st.session_state.pop("_tracker_sheet_cache", None)
    return {"deleted_rows": deleted_rows, "trashed_dataset": bool(file_id)}


def profile_dialog_html(profile: dict) -> str:
    provider = str(profile.get("auth_provider", "")).strip()
    sign_in_copy = (
        "This clinic signs in with Google. Use Continue with Google next time; your Google password is never entered here. "
        "The Google sign-in email is read-only here, managed by Google, and cannot be changed in this profile."
        if provider == GOOGLE_AUTH_PROVIDER
        else "This clinic can sign in with its clinic username and password."
    )
    return f"""
    <style>
      .profile-dialog-note {{
        background: #f8fafc;
        border: 1px solid rgba(15, 23, 42, 0.08);
        border-radius: 8px;
        color: #526174;
        font-size: 0.92rem;
        line-height: 1.45;
        margin-bottom: 0.95rem;
        padding: 0.8rem 0.9rem;
      }}
    </style>
    <div class="profile-dialog-note">{html_lib.escape(sign_in_copy)}</div>
    """


def close_profile_dialog():
    st.session_state["show_profile_dialog"] = False


def render_profile_dialog():
    if not st.session_state.get("show_profile_dialog", False):
        return

    clinic_id = st.session_state.get("clinic_id", "")
    profile = get_clinic_profile(clinic_id)

    def _render_dialog_body():
        st.markdown(profile_dialog_html(profile), unsafe_allow_html=True)
        google_profile = profile.get("auth_provider") == GOOGLE_AUTH_PROVIDER
        with st.form("profile_form"):
            new_clinic_id = st.text_input("Clinic name", value=profile.get("clinic_id", ""))
            google_email = profile.get("email", "")
            new_email = st.text_input(
                "Google sign-in email (read-only)" if google_profile else "Email",
                value=google_email if google_profile else profile.get("email", ""),
                disabled=google_profile,
                help="Managed by Google and read-only in this profile." if google_profile else None,
            )
            if google_profile:
                new_email = google_email
                st.caption("Managed by Google. Changing clinic details here will not change the Google sign-in email.")
            submitted = st.form_submit_button("Save profile", type="primary", use_container_width=True)

        if submitted:
            try:
                updated = update_clinic_profile(clinic_id, new_clinic_id, new_email)
                st.session_state["clinic_id"] = updated["clinic_id"]
                if st.session_state.get("auth_provider") != GOOGLE_AUTH_PROVIDER:
                    clear_remember_login_token()
                load_settings()
                close_profile_dialog()
                st.success("Profile updated.")
                st.rerun()
            except ValueError as e:
                st.error(str(e))
            except Exception:
                st.error("Could not update profile. Please try again or contact support.")

        if st.button("Close", key="profile_dialog_close", use_container_width=True):
            close_profile_dialog()
            st.rerun()

    if hasattr(st, "dialog"):
        @st.dialog("Profile", on_dismiss=close_profile_dialog)
        def _profile_dialog():
            _render_dialog_body()
        _profile_dialog()
    elif hasattr(st, "experimental_dialog"):
        @st.experimental_dialog("Profile")
        def _profile_dialog():
            _render_dialog_body()
        _profile_dialog()
    else:
        with st.expander("Profile", expanded=True):
            _render_dialog_body()


def delete_account_dialog_html(clinic_id: str) -> str:
    return f"""
    <style>
      .delete-account-warning {{
        background: #fff1f2;
        border: 1px solid #fda4af;
        border-radius: 8px;
        color: #7f1d1d;
        line-height: 1.45;
        margin-bottom: 1rem;
        padding: 1rem;
      }}
      .delete-account-warning h3 {{
        color: #7f1d1d;
        font-size: 1.1rem;
        font-weight: 850;
        margin: 0 0 0.35rem;
      }}
      .delete-account-warning p {{
        margin: 0.35rem 0 0;
      }}
      .st-key-delete_account_form div[data-testid="stFormSubmitButton"] button {{
        background: #dc2626 !important;
        border-color: #dc2626 !important;
        color: #ffffff !important;
      }}
      .st-key-delete_account_form div[data-testid="stFormSubmitButton"] button:hover {{
        background: #b91c1c !important;
        border-color: #b91c1c !important;
        color: #ffffff !important;
      }}
    </style>
    <div class="delete-account-warning">
      <h3>This is permanent.</h3>
      <p>Deleting <strong>{html_lib.escape(clinic_id)}</strong> removes the clinic account, Google sign-in link, saved settings, reminder history, and uploaded clinic data file.</p>
      <p>This is the full in-app deletion path for a clinic that wants everything removed from the active account. It cannot be undone from the app.</p>
    </div>
    """


def close_delete_account_dialog():
    st.session_state["show_delete_account_dialog"] = False


def render_delete_account_dialog():
    if not st.session_state.get("show_delete_account_dialog", False):
        return

    clinic_id = str(st.session_state.get("clinic_id", "")).strip()
    confirmation = f"DELETE {clinic_id}"

    def _render_dialog_body():
        st.markdown(delete_account_dialog_html(clinic_id), unsafe_allow_html=True)
        with st.form("delete_account_form"):
            st.caption(f"Type `{confirmation}` to confirm.")
            typed = st.text_input("Confirmation", key="delete_account_confirm_text")
            submitted = st.form_submit_button("Delete account and data", type="primary", use_container_width=True)

        if submitted:
            if typed.strip() != confirmation:
                st.error("Confirmation did not match. Nothing was deleted.")
                return
            try:
                with busy_overlay("Deleting account and data", "Removing clinic records, reminder history, and uploaded data."):
                    delete_clinic_account_and_data(clinic_id)
            except Exception as e:
                record_error_tracker_event(
                    "delete_account_failed",
                    stage="delete_account_dialog",
                    error=e,
                    source="delete_account_and_data",
                )
                st.error("Could not delete the account. Please try again or contact support before retrying.")
                return

            try:
                google_session_active = get_google_user_info().get("is_logged_in", False)
            except Exception as e:
                google_session_active = False
                record_error_tracker_event(
                    "delete_account_cleanup_failed",
                    stage="delete_account_google_state",
                    error=e,
                    source="delete_account_and_data",
                )
            try:
                clear_remember_login_token()
            except Exception as e:
                record_error_tracker_event(
                    "delete_account_cleanup_failed",
                    stage="delete_account_remember_token",
                    error=e,
                    source="delete_account_and_data",
                )
            try:
                clear_account_session_state(
                    reset_uploader=False,
                    preserve_keys={"delete_account_confirm_text"},
                )
            except Exception as e:
                record_error_tracker_event(
                    "delete_account_cleanup_failed",
                    stage="delete_account_session_state",
                    error=e,
                    source="delete_account_and_data",
                )
                st.session_state["logged_in"] = False
                st.session_state.pop("clinic_id", None)
            st.session_state["logout_notice"] = "The clinic account and saved data were deleted."
            st.session_state["pending_google_signup"] = google_session_active
            if google_session_active:
                st.session_state["google_onboarding_mode"] = "recreate_after_delete"
            close_delete_account_dialog()
            st.rerun()

        if st.button("Cancel", key="delete_account_cancel", use_container_width=True):
            close_delete_account_dialog()
            st.rerun()

    if hasattr(st, "dialog"):
        @st.dialog("Delete Account And Data")
        def _delete_dialog():
            _render_dialog_body()
        _delete_dialog()
    elif hasattr(st, "experimental_dialog"):
        @st.experimental_dialog("Delete Account And Data")
        def _delete_dialog():
            _render_dialog_body()
        _delete_dialog()
    else:
        with st.expander("Delete Account And Data", expanded=True):
            _render_dialog_body()


def update_clinic_password(clinic_id: str, new_password: str):
    """Update the password hash for the current clinic login."""
    validate_password_policy(new_password, clinic_id)
    sheet, headers, row_idx = _get_settings_row_for_clinic(clinic_id)
    password_hash = password_hash_for_storage(new_password)
    updated_at = utc_now_iso()
    if callable(globals().get("_update_password_cells", None)):
        _update_password_cells(sheet, headers, row_idx, "", password_hash, updated_at)
    else:
        password_col = _settings_col_index(headers, "PasswordHash")
        _gspread_retry(sheet.update_cell, row_idx, password_col, password_hash)
    update_cached_settings_row_fields(
        clinic_id,
        {
            SHEET_COL_PLAIN_PASSWORD: "",
            SHEET_COL_PASSWORD_HASH: password_hash,
            SHEET_COL_UPDATED_AT: updated_at,
        },
    )
    return password_hash

def _to_blob(uploaded):
    # Deterministic blob for caching; avoids .read() side effects
    declared_size = getattr(uploaded, "size", None)
    if declared_size is not None and int(declared_size) > MAX_UPLOAD_FILE_BYTES:
        raise UploadResourceLimitError(
            f"{uploaded.name} is too large. Maximum upload size is "
            f"{format_file_size(MAX_UPLOAD_FILE_BYTES)} per file."
        )
    b = uploaded.getvalue()
    validate_upload_file_size(b, uploaded.name)
    return {"name": uploaded.name, "bytes": b}

def upload_fingerprint(file_blobs) -> str:
    validate_upload_file_collection(file_blobs)
    h = hashlib.sha256()
    for fb in file_blobs:
        h.update(str(fb["name"]).encode("utf-8"))
        h.update(b"\0")
        h.update(fb["bytes"])
        h.update(b"\0")
    return h.hexdigest()


def upload_save_can_be_skipped(current_upload_key: str, last_saved_upload_key: str, upload_history) -> bool:
    """Only skip publishing when this upload key already has a saved history row."""
    if not current_upload_key or current_upload_key != str(last_saved_upload_key or ""):
        return False
    return bool(normalize_dataset_upload_history(upload_history))


def finish_authenticated_session(
    clinic_id: str,
    event: str,
    auth_provider: str = "password",
    google_user: dict | None = None,
):
    clinic_id = str(clinic_id or "").strip()
    close_account_dialogs()
    st.session_state["clinic_id"] = clinic_id
    st.session_state["logged_in"] = True
    st.session_state["show_top_change_password"] = False
    st.session_state["auth_provider"] = auth_provider
    if google_user:
        st.session_state["google_email"] = google_user.get("email", "")
        st.session_state["google_subject"] = google_user.get("subject", "")

    reset_uploaded_data_state(clear_cache=False, reset_uploader=True)
    load_settings()
    load_shared_dataset_for_clinic()
    record_settings_account_event(
        clinic_id,
        event=event,
        auth_provider=auth_provider,
        country=st.session_state.get("user_country", ""),
    )
    upsert_user_tracker(
        clinic_id,
        country=st.session_state.get("user_country", ""),
        event=event,
    )


@st.cache_data(show_spinner=False)
def summarize_uploads(file_blobs, cache_version: int = UPLOAD_SUMMARY_SCHEMA_VERSION):
    validate_upload_file_collection(file_blobs)
    datasets, summary_rows = [], []
    for fb in file_blobs:
        df, pms_name, amount_col = process_file(fb["bytes"], fb["name"])
        validate_upload_dataframe(df, fb["name"])
        pms_name = pms_name or "Canonical CSV"
        charge_dates = parse_dates(df["ChargeDate"])
        from_date = charge_dates.min()
        to_date = charge_dates.max()
        summary_rows.append({
            "File name": fb["name"],
            "Rows": int(len(df.index)),
            "PMS": pms_name,
            "From": from_date.strftime("%d %b %Y") if pd.notna(from_date) else "-",
            "To":   to_date.strftime("%d %b %Y")   if pd.notna(to_date)   else "-"
        })
        datasets.append((pms_name, df))
    return datasets, summary_rows

@st.cache_data(show_spinner=False)
def prepare_session_bundle(df: pd.DataFrame, cache_key: str):
    """
    Build a single, reusable bundle for the whole app:
      - Normalized keys & core date fields
      - Precomputed boolean masks for ALL categories (incl. PATIENT_VISIT)
      - VisitFlag column
      - Transactions (client- & patient-level) using 'Block' segmentation
      - patients_per_month series
    cache_key is an explicit cache invalidator for schema changes. Reminder rules
    are intentionally excluded because this bundle only uses fixed analytics masks.
    """
    if df is None or len(df) == 0:
        # Return empty structures but correct shapes to avoid downstream errors
        empty = df if isinstance(df, pd.DataFrame) else pd.DataFrame()
        return (
            empty.copy(),
            {},  # masks
            pd.DataFrame(columns=["ClientKey","Block","StartDate","EndDate","Patients","Amount","Client Name"]),
            pd.DataFrame(columns=["ClientKey","AnimalKey","Block","StartDate","EndDate","Amount"]),
            pd.Series(dtype="int64", name="AnimalKey"),
        )
    df = sanitize_working_df(df)

    # ---- Core columns/prep (once) ----
    df["ChargeDate"] = parse_dates(df["ChargeDate"])
    df["DateOnly"]   = df["ChargeDate"].dt.normalize()
    df["Month"]      = df["ChargeDate"].dt.to_period("M")
    df["Year"]       = df["ChargeDate"].dt.year
    df["MonthNum"]   = df["ChargeDate"].dt.month

    df["ClientKey"] = normalize_key_series(df.get("Client Name"), index=df.index)
    df["AnimalKey"] = normalize_key_series(df.get("Animal Name"), index=df.index)
    df["ItemNorm"]  = normalize_key_series(df.get("Item Name"), index=df.index)

    # ---- Regex/mask helpers ----
    def _rx(includes):
        return re.compile("|".join(map(re.escape, includes)), re.I) if includes else None

    def _mask(inc, exc):
        if len(df) == 0:
            return pd.Series(False, index=df.index)
        inc_rx = _rx(inc)
        m = df["ItemNorm"].str.contains(inc_rx) if inc_rx else pd.Series(False, index=df.index)
        if exc:
            exc_rx = _rx(exc)
            m &= ~df["ItemNorm"].str.contains(exc_rx)
        return m.fillna(False)

    # ---- ALL keyword masks (including new groups not yet used in UI) ----
    masks = {
        "CONSULT":        _mask(CONSULT_KEYWORDS,         CONSULT_EXCLUSIONS),
        "FEE":            _mask(FEE_KEYWORDS,             FEE_EXCLUSIONS),
        "GROOMING":       _mask(GROOM_KEYWORDS,           GROOM_EXCLUSIONS),
        "BOARDING":       _mask(BOARDING_KEYWORDS,        BOARDING_EXCLUSIONS),
        "DENTAL":         _mask(DENTAL_KEYWORDS,          DENTAL_EXCLUSIONS),
        "FLEA_WORM":      _mask(FLEA_WORM_KEYWORDS,       FLEA_WORM_EXCLUSIONS),
        "FOOD":           _mask(FOOD_KEYWORDS,            FOOD_EXCLUSIONS),
        "XRAY":           _mask(XRAY_KEYWORDS,            XRAY_EXCLUSIONS),
        "ULTRASOUND":     _mask(ULTRASOUND_KEYWORDS,      ULTRASOUND_EXCLUSIONS),
        "LABWORK":        _mask(LABWORK_KEYWORDS,         LABWORK_EXCLUSIONS),
        "ANAESTHETIC":    _mask(ANAESTHETIC_KEYWORDS,     ANAESTHETIC_EXCLUSIONS),
        "HOSPITAL":       _mask(HOSPITALISATION_KEYWORDS, HOSPITALISATION_EXCLUSIONS),
        "VACCINE":        _mask(VACCINE_KEYWORDS,         VACCINE_EXCLUSIONS),
        "DEATH":          _mask(DEATH_KEYWORDS,           DEATH_EXCLUSIONS),
        "NEUTER":         _mask(NEUTER_KEYWORDS,          NEUTER_EXCLUSIONS),
        # Composite for visits (used widely across app)
        "PATIENT_VISIT":  _mask(PATIENT_VISIT_KEYWORDS,   PATIENT_VISIT_EXCLUSIONS),
    }

    # VisitFlag used throughout
    df["VisitFlag"] = masks["PATIENT_VISIT"]

    # ---- Transactions (blocks) once ----
    df_sorted = df.sort_values(["ClientKey", "DateOnly"])
    daydiff   = df_sorted.groupby("ClientKey", dropna=False)["DateOnly"].diff().dt.days.fillna(1)
    block     = (daydiff > 1).groupby(df_sorted["ClientKey"], dropna=False).cumsum()
    df_sorted["Block"] = block
    
    # ✅ robust propagation back to df using index alignment
    df = df.join(df_sorted[["Block"]])

    # Client-level transactions (one row per contiguous block)
    tx_client = (
        df_sorted.groupby(["ClientKey","Block"], dropna=False)
                 .agg(StartDate=("DateOnly","min"),
                      EndDate=("DateOnly","max"),
                      Patients=("AnimalKey", lambda x: set(x.astype(str))),
                      Amount=("Amount","sum"))
                 .reset_index()
    )

    # attach a display client name (first seen)
    first_names = (
        df_sorted.groupby("ClientKey", dropna=False)["Client Name"]
                 .first()
                 .rename("Client Name")
                 .reset_index()
    )
    tx_client = tx_client.merge(first_names, on="ClientKey", how="left")

    # Patient-level transactions (client+animal per block)
    tx_patient = (
        df_sorted.groupby(["ClientKey","AnimalKey","Block"], dropna=False)
                 .agg(StartDate=("DateOnly","min"),
                      EndDate=("DateOnly","max"),
                      Amount=("Amount","sum"))
                 .reset_index()
    )

    # Monthly denominator: unique animals per month (on the full df)
    patients_per_month = df.groupby("Month")["AnimalKey"].nunique()

    return df, masks, tx_client, tx_patient, patients_per_month

# === LOGIN FORM ===
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

if "auto_login_attempted" not in st.session_state:
    st.session_state["auto_login_attempted"] = False
st.session_state.setdefault("show_top_change_password", False)
google_user = get_google_user_info()

discard_remember_login_query_param()

if google_user.get("is_logged_in") and not st.session_state["logged_in"]:
    try:
        google_clinic_row = get_clinic_row_by_google_identity(google_user)
    except Exception:
        google_clinic_row = None
    if google_clinic_row:
        st.session_state.pop("pending_google_signup", None)
        st.session_state.pop("google_onboarding_mode", None)
        finish_authenticated_session(
            str(google_clinic_row.get("ClinicID", "")).strip(),
            event="google_login",
            auth_provider=GOOGLE_AUTH_PROVIDER,
            google_user=google_user,
        )
        rerun_app()
    else:
        st.session_state["pending_google_signup"] = True
        st.session_state.setdefault("google_onboarding_mode", "signup")
elif st.session_state.get("pending_google_signup"):
    st.session_state.pop("pending_google_signup", None)
    st.session_state.pop("google_onboarding_mode", None)

default_username, default_password = DEV_AUTO_LOGIN_CREDENTIALS

if (
    get_script_run_ctx is not None
    and get_script_run_ctx() is not None
    and not st.session_state["logged_in"]
    and DEV_AUTO_LOGIN
    and auto_login_allowed(default_username)
    and not st.session_state["auto_login_attempted"]
):
    st.session_state["auto_login_attempted"] = True
    user_row = get_clinic_row(default_username)
    if user_row:
        close_account_dialogs()
        st.session_state["clinic_id"] = default_username
        st.session_state["logged_in"] = True
        st.session_state["show_top_change_password"] = False
        reset_uploaded_data_state(clear_cache=False, reset_uploader=True)
        load_settings()
        load_shared_dataset_for_clinic()
        record_settings_account_event(
            default_username,
            event="login",
            auth_provider="dev_auto_login",
            country=st.session_state.get("user_country", ""),
        )
        rerun_app()

pending_google_signup = bool(st.session_state.get("pending_google_signup") and google_user.get("is_logged_in"))

if pending_google_signup and not st.session_state["logged_in"]:
    onboarding_mode = st.session_state.get("google_onboarding_mode", "signup")
    pending_title = "Create a new clinic account" if onboarding_mode == "recreate_after_delete" else "Finishing your Google sign-up"
    pending_body = "Your previous clinic was deleted. A quick setup window will open so you can start fresh." if onboarding_mode == "recreate_after_delete" else "A quick setup window will open so we can create your clinic account."
    st.markdown(
        f"""
        <div style="max-width: 42rem; margin: 2rem 0 0 2rem; color: #40566b;">
          <h3 style="color: #101828; margin-bottom: 0.35rem;">{pending_title}</h3>
          <p style="margin: 0;">{pending_body}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    render_google_onboarding_dialog(google_user)
    st.stop()

if not st.session_state["logged_in"]:
    login_col, _ = st.columns([0.36, 0.64])
    with login_col:
        st.markdown("<div class='login-title'>Clinic Login</div>", unsafe_allow_html=True)
        logout_notice = st.session_state.pop("logout_notice", "")
        if logout_notice:
            st.success(logout_notice)
        with st.form("clinic_login_form"):
            st.markdown("<span class='login-form-marker'></span>", unsafe_allow_html=True)
            username = st.text_input("Clinic ID / Username", value=DEV_AUTO_LOGIN_CREDENTIALS[0], key="login_username_input")
            password = st.text_input("Password", value="", type="password", key="login_password_input")
            login_submitted = st.form_submit_button("Login", type="primary", use_container_width=True)

        google_auth_ready = authlib_available()
        google_signup_error = st.session_state.pop("google_signup_error", "")
        if google_signup_error:
            st.warning(google_signup_error)
        google_signup_col, manual_signup_col = st.columns(2, gap="small")
        with google_signup_col:
            st.button(
                "Continue with Google",
                key="google_signup_button",
                use_container_width=True,
                disabled=not google_auth_ready,
                on_click=begin_google_login,
            )
        with manual_signup_col:
            if "show_create_account" not in st.session_state:
                st.session_state["show_create_account"] = False
            if st.button(
                "Sign Up",
                key="toggle_create_account",
                use_container_width=True,
            ):
                st.session_state["show_create_account"] = (
                    not st.session_state["show_create_account"]
                )
        if not google_auth_ready:
            st.warning(
                "Google sign-up needs the Authlib package. Run `pip install -r requirements.txt` "
                "and restart Streamlit."
            )

        if login_submitted:
            login_allowed, retry_after = login_attempt_allowed(
                username,
            )
            if not login_allowed:
                st.error(auth_retry_message("login", retry_after))
            else:
                user_row = authenticate_user(username, password)
                if user_row:
                    record_successful_login_attempt(username)
                    close_account_dialogs()
                    st.session_state["clinic_id"] = username
                    st.session_state["logged_in"] = True
                    st.session_state["show_top_change_password"] = False
                    clear_remember_login_token()

                    reset_uploaded_data_state(clear_cache=False, reset_uploader=True)
                    load_settings()
                    # ✅ Auto-load shared dataset from Drive into working_df
                    load_shared_dataset_for_clinic()
                    record_settings_account_event(
                        username,
                        event="login",
                        auth_provider="password",
                        country=st.session_state.get("user_country", ""),
                    )
                    upsert_user_tracker(
                        username,
                        country=st.session_state.get("user_country", ""),
                        event="login",
                    )

                    st.success(f"✅ Welcome, {username}!")
                    st.rerun()
                else:
                    record_failed_login_attempt(username)
                    st.error("❌ Invalid username or password.")

        if st.session_state["show_create_account"]:
            st.markdown("### Sign Up")
            with st.form("create_account_form"):
                new_clinic = st.text_input("Clinic Name (username)").strip()
                country = st.selectbox("Country", COUNTRY_OPTIONS)
                new_password = st.text_input("Set password", type="password")
                confirm_password = st.text_input("Confirm password", type="password")
                create_submitted = st.form_submit_button(
                    "Sign Up",
                    type="primary",
                    use_container_width=True,
                )

            if create_submitted:
                if not new_clinic or not new_password or not confirm_password:
                    st.error("Enter a clinic name and password twice.")
                elif password_policy_error(new_password, new_clinic):
                    st.error(password_policy_error(new_password, new_clinic))
                elif new_password != confirm_password:
                    st.error("Passwords do not match.")
                else:
                    signup_allowed, retry_after = signup_attempt_allowed()
                    if not signup_allowed:
                        st.error(auth_retry_message("sign-up", retry_after))
                    else:
                        record_signup_attempt()
                        try:
                            password_hash = create_clinic_account(
                                new_clinic,
                                country,
                                new_password,
                            )
                            close_account_dialogs()
                            st.session_state["clinic_id"] = new_clinic
                            st.session_state["logged_in"] = True
                            st.session_state["show_top_change_password"] = False
                            clear_remember_login_token()
                            reset_uploaded_data_state(
                                clear_cache=False,
                                reset_uploader=True,
                            )
                            load_settings()
                            st.session_state["user_country"] = country
                            mark_new_account_welcome_pending()
                            st.success(
                                f"✅ Account created. Welcome, {new_clinic}!"
                            )
                            st.rerun()
                        except ValueError as e:
                            st.error(str(e))
                        except Exception:
                            st.error("Could not create account. Please try again or contact support.")
else:
    clinic_id = st.session_state.get("clinic_id", "")
    with top_account_slot.container():
        with st.popover("Account", use_container_width=False):
            if st.button("Profile", key="top_account_profile", use_container_width=True):
                open_account_dialog("profile")

            if st.button("Data & Privacy", key="top_account_data_privacy", use_container_width=True):
                open_account_dialog("privacy")

            if st.session_state.get("auth_provider") != GOOGLE_AUTH_PROVIDER:
                if st.button("Change password", key="top_account_show_change_password", use_container_width=True):
                    st.session_state["show_top_change_password"] = not st.session_state.get("show_top_change_password", False)

            if st.button("Delete account and data", key="top_account_delete", use_container_width=True):
                open_account_dialog("delete")

            if st.button("Logout", key="top_account_logout", use_container_width=True):
                google_session_active = get_google_user_info().get("is_logged_in", False)
                clear_remember_login_token()
                clear_account_session_state()
                st.session_state["logout_notice"] = "You have been logged out."
                if google_session_active and callable(getattr(st, "logout", None)):
                    st.logout()
                else:
                    st.rerun()

            if st.session_state.get("show_top_change_password", False):
                st.markdown("#### Change password")
                with st.form("change_password_form"):
                    current_password = st.text_input("Current password", type="password")
                    new_password = st.text_input("New password", type="password")
                    confirm_password = st.text_input("Confirm new password", type="password")
                    submitted = st.form_submit_button("Change password")

                if submitted:
                    if not current_password or not new_password or not confirm_password:
                        st.error("Enter the current password and the new password twice.")
                    elif new_password != confirm_password:
                        st.error("New passwords do not match.")
                    elif password_policy_error(new_password, clinic_id):
                        st.error(password_policy_error(new_password, clinic_id))
                    elif not authenticate_user(clinic_id, current_password):
                        st.error("Current password is incorrect.")
                    else:
                        password_hash = update_clinic_password(clinic_id, new_password)
                        clear_remember_login_token()
                        upsert_user_tracker(
                            clinic_id,
                            country=st.session_state.get("user_country", ""),
                            event="password_changed",
                        )
                        st.session_state["show_top_change_password"] = False
                        st.success("Password updated.")

if upload_widget_has_files() and account_dialog_is_open():
    close_account_dialogs()

if st.session_state.get("show_delete_account_dialog", False):
    render_delete_account_dialog()
elif st.session_state.get("show_profile_dialog", False):
    render_profile_dialog()
elif st.session_state.get("show_data_privacy_dialog", False):
    render_data_privacy_dialog()
elif st.session_state.get("show_new_account_welcome_dialog", False):
    render_new_account_welcome_dialog()
elif st.session_state.get("show_upload_sales_data_help_dialog", False):
    render_upload_sales_data_help_dialog()

# Block access to rest of app until logged in
if not st.session_state["logged_in"]:
    st.stop()

if "rules" not in st.session_state:
    load_settings()
ensure_tracking_sheets()
ensure_shared_dataset_loaded_for_session()
show_pending_settings_sync_warning()
show_pending_action_sync_warning()


def get_setup_checklist_steps() -> list[dict]:
    df_w = st.session_state.get("working_df")
    has_data = df_w is not None and not getattr(df_w, "empty", True)
    search_term_added = bool(st.session_state.get("search_term_added", False))
    has_sender_name = bool(str(st.session_state.get("user_name", "")).strip())
    template_updated = bool(st.session_state.get("wa_template_updated", False))
    reset_at = _parse_reminder_log_time(st.session_state.get("get_started_reset_at", ""))

    def happened_after_reset(timestamp: str) -> bool:
        if not reset_at:
            return True
        happened_at = _parse_reminder_log_time(timestamp)
        return bool(happened_at and happened_at > reset_at)

    def action_after_reset(action_name: str) -> bool:
        for entry in st.session_state.get("deleted_reminders", []):
            if not isinstance(entry, dict):
                continue
            if str(entry.get("Action", "")).strip().lower() == action_name and happened_after_reset(entry.get("ActionedAt", "") or entry.get("DeletedAt", "")):
                return True
        return False

    def sent_after_reset() -> bool:
        for entry in st.session_state.get("wa_reminder_log", []):
            if isinstance(entry, dict) and happened_after_reset(entry.get("RemindedAt", "")):
                return True
        return action_after_reset(REMINDER_ACTION_SENT)

    steps = [
        {
            "number": 1,
            "done": has_data and happened_after_reset(st.session_state.get("shared_dataset_updated_at", "")),
            "title": "Upload data",
            "copy": "Upload a sales export from your practice system. One year of data is ideal so yearly reminders can be found reliably.",
            "where": "Where: Upload Data tab",
        },
        {
            "number": 2,
            "done": search_term_added and happened_after_reset(st.session_state.get("search_term_added_at", "")),
            "title": "Add new search term",
            "copy": "Add at least one clinic-specific product or service so reminders match your clinic language.",
            "where": "Where: Search Terms tab",
        },
        {
            "number": 3,
            "done": has_sender_name and happened_after_reset(st.session_state.get("user_name_updated_at", "")),
            "title": "Set sender name",
            "copy": "This fills [Your Name] in WhatsApp messages. Example: Mary from Bob's Test Vet Clinic.",
            "where": "Where: Reminders tab, above the reminder list",
        },
        {
            "number": 4,
            "done": template_updated and happened_after_reset(st.session_state.get("wa_template_updated_at", "")),
            "title": "Update template",
            "copy": "Save the WhatsApp template once so it matches your clinic tone and wording.",
            "where": "Where: Template Editor in the Reminders tab",
        },
        {
            "number": 5,
            "done": sent_after_reset(),
            "title": "Send your first reminder",
            "copy": "Open Reminders, prepare a WhatsApp message, then mark it Sent once the client has been contacted.",
            "where": "Where: Reminders tab",
        },
        {
            "number": 6,
            "done": action_after_reset(REMINDER_ACTION_DECLINED),
            "title": "Decline your first reminder",
            "copy": "Tick the red X to decline sending this reminder while still marking it actioned.",
            "where": "Where: Reminders tab",
        },
    ]
    for step in steps:
        step["class_name"] = "complete" if step["done"] else "todo"
        step["status"] = "Done" if step["done"] else "To do"
    return steps


def get_started_incomplete_count() -> int:
    return sum(1 for step in get_setup_checklist_steps() if not step["done"])


def tab_badge_label_text(tab_name: str, badge_text: str, alt_text: str, fill: str = "#dc2626") -> str:
    badge_text = str(badge_text or "").strip()
    if not badge_text:
        return tab_name
    width = max(26, 18 + (len(badge_text) * 8))
    text_x = width / 2
    badge_svg = f"""
    <svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="22" viewBox="0 0 {width} 22">
      <rect x="1" y="2" width="{width - 2}" height="18" rx="9" fill="{fill}"/>
      <text x="{text_x}" y="15" fill="#fff" font-family="Arial, sans-serif" font-size="13" font-weight="700" text-anchor="middle">{html_lib.escape(badge_text)}</text>
    </svg>
    """
    encoded_badge = base64.b64encode(badge_svg.encode("utf-8")).decode("ascii")
    return f"{tab_name} ![{alt_text}](data:image/svg+xml;base64,{encoded_badge})"


def tab_badge_label(tab_name: str, count: int, alt_text: str) -> str:
    count = int(count or 0)
    if count <= 0:
        return tab_name
    return tab_badge_label_text(tab_name, str(count), alt_text)


def get_started_badge_label(count: int | None = None) -> str:
    count = get_started_incomplete_count() if count is None else int(count or 0)
    if count <= 0:
        return "Get Started"
    count = max(1, min(6, count))
    return tab_badge_label("Get Started", count, f"{count} setup steps remaining")


def upload_data_badge_count(rows: list[dict] | None = None) -> int:
    rows = get_saved_dataset_summary_rows() if rows is None else rows
    return dataset_summary_issue_count(rows)


def upload_data_badge_label(count: int | None = None) -> str:
    count = upload_data_badge_count() if count is None else int(count or 0)
    if count <= 0:
        return "Upload Data"
    return tab_badge_label("Upload Data", count, f"{count} upload data checks need attention")


def stats_badge_label() -> str:
    return tab_badge_label_text("Stats", "New", "New Stats tab")


def main_section_tab_label(tab_name: str) -> str:
    if tab_name == "Reminders":
        return reminders_badge_label()
    if tab_name == "Get Started":
        return get_started_badge_label()
    if tab_name == "Upload Data":
        return upload_data_badge_label()
    if tab_name == "Stats":
        return stats_badge_label()
    return tab_name


def main_section_tab_badge_count(tab_name: str) -> int:
    try:
        if tab_name == "Reminders":
            return max(0, int(get_active_reminder_badge_count()))
        if tab_name == "Get Started":
            return max(0, int(get_started_incomplete_count()))
        if tab_name == "Upload Data":
            return max(0, int(upload_data_badge_count()))
    except Exception:
        return 0
    return 0


def main_section_nav_button_key(tab_name: str) -> str:
    slug = MAIN_SECTION_TAB_TO_SLUG.get(tab_name, tab_name.lower().replace(" ", "-"))
    return f"main_section_nav_{slug.replace('-', '_')}"


def render_main_section_nav(active_tab: str) -> None:
    active_button_key = main_section_nav_button_key(active_tab)
    st.markdown(
        f"""
        <style>
          .st-key-{active_button_key} button {{
            background: var(--cr-primary) !important;
            border-color: var(--cr-primary-dark) !important;
            box-shadow: inset 0 4px 0 var(--cr-primary-dark), 0 1px 0 var(--cr-primary) !important;
            color: #062d19 !important;
            position: relative !important;
            z-index: 1 !important;
          }}
          .st-key-{active_button_key} button:hover {{
            background: var(--cr-primary) !important;
            border-color: var(--cr-primary-dark) !important;
            color: #062d19 !important;
          }}
          .st-key-{active_button_key} button p,
          .st-key-{active_button_key} button span {{
            color: #062d19 !important;
          }}
        </style>
        """,
        unsafe_allow_html=True,
    )
    widths = []
    for tab_name in MAIN_SECTION_TABS:
        count = main_section_tab_badge_count(tab_name)
        widths.append(max(1.2, min(2.6, len(tab_name) / 8 + (0.35 if count > 0 else 0))))
    nav_spacer_width = 7.8
    columns = st.columns([*widths, nav_spacer_width], gap="small")[:len(MAIN_SECTION_TABS)]
    for column, tab_name in zip(columns, MAIN_SECTION_TABS):
        with column:
            st.button(
                main_section_tab_label(tab_name),
                key=main_section_nav_button_key(tab_name),
                on_click=set_main_section_tab,
                args=(tab_name,),
                type="secondary",
                use_container_width=True,
            )
    st.markdown(
        '<div class="cr-main-section-nav-rule" aria-hidden="true"></div>',
        unsafe_allow_html=True,
    )


def clone_reminder_rules(rules: dict | None) -> dict:
    return json.loads(json.dumps(rules or {}))


def _rules_fp(rules: dict) -> str:
    return hashlib.md5(json.dumps(rules or {}, sort_keys=True).encode()).hexdigest()


def get_applied_reminder_rules() -> dict:
    if "applied_rules" not in st.session_state:
        st.session_state["applied_rules"] = clone_reminder_rules(st.session_state.get("rules", DEFAULT_RULES.copy()))
    return st.session_state["applied_rules"]


def search_criteria_have_pending_changes() -> bool:
    return _rules_fp(st.session_state.get("rules", {})) != _rules_fp(get_applied_reminder_rules())


def apply_search_criteria_changes():
    st.session_state["applied_rules"] = clone_reminder_rules(st.session_state.get("rules", DEFAULT_RULES.copy()))
    st.session_state.pop("prepared_df", None)
    st.session_state.pop("prepared_key", None)
    st.session_state["_search_criteria_refreshed"] = True


# === Optional analytics bundle creation ===
bundle_key = (st.session_state.get("data_version", 0), SESSION_BUNDLE_SCHEMA_VERSION)

if st.session_state.get("working_df") is not None:
    # The active reminder workflow does not use this heavier analytics bundle.
    if PRECOMPUTE_ANALYTICS_BUNDLE and st.session_state.get("bundle_key") != bundle_key:
        df_full, masks, tx_client, tx_patient, patients_per_month = prepare_session_bundle(
            st.session_state["working_df"], str(SESSION_BUNDLE_SCHEMA_VERSION)
        )
        st.session_state["bundle"] = (df_full, masks, tx_client, tx_patient, patients_per_month)
        st.session_state["bundle_key"] = bundle_key
    elif not PRECOMPUTE_ANALYTICS_BUNDLE:
        st.session_state.pop("bundle", None)
        st.session_state.pop("bundle_key", None)
else:
    # No data → clear any stale bundle so downstream checks can bail gracefully
    st.session_state.pop("bundle", None)
    st.session_state.pop("bundle_key", None)

# === What data is uploaded
def has_working_dataset() -> bool:
    df_w = st.session_state.get("working_df")
    return df_w is not None and not getattr(df_w, "empty", True)


def render_dataset_status(saved_rows: list[dict] | None = None):
    pending_success = st.session_state.pop("_pending_dataset_success", "")
    if pending_success:
        st.success(pending_success)
    pending_warning = st.session_state.pop("_pending_dataset_warning", "")
    if pending_warning:
        st.warning(pending_warning)
    if st.session_state.get("shared_dataset_error"):
        error_text = str(st.session_state["shared_dataset_error"])
        if "missing its file link" in error_text:
            st.warning(f"⚠️ {error_text}")
        else:
            st.warning("⚠️ Could not load clinic data. Please try again or contact support.")
    elif not saved_rows and not has_working_dataset() and not st.session_state.get("shared_dataset_loaded"):
        st.caption("No clinic data saved yet — upload a file to start.")


def format_dataset_saved_summary(row_count: int, start_date, end_date) -> str:
    try:
        rows_text = f"{int(row_count):,}"
    except (TypeError, ValueError):
        rows_text = "0"

    if start_date is None or end_date is None or pd.isna(start_date) or pd.isna(end_date):
        date_range = "Dates not detected"
    else:
        start_ts = pd.Timestamp(start_date)
        end_ts = pd.Timestamp(end_date)
        date_range = f"{start_ts:%d %b %Y} → {end_ts:%d %b %Y}"

    return (
        f"**Total rows:** {rows_text}  \n"
        f"**Total date range (all uploads):** {date_range}"
    )

def get_dataset_date_range(df: pd.DataFrame) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    if df is None or df.empty:
        return None, None

    s = df.get("ChargeDate")
    if s is None:
        return None, None

    if pd.api.types.is_datetime64_any_dtype(s):
        dt = pd.to_datetime(s, errors="coerce").dt.normalize()
    else:
        dt = parse_dates(s).dt.normalize()

    dmin = dt.min()
    dmax = dt.max()
    if pd.isna(dmin) or pd.isna(dmax):
        return None, None
    return dmin, dmax

def render_dataset_summary_box(title: str, rows: list[dict]):
    normalized_rows = normalize_dataset_upload_history(rows)
    if not normalized_rows:
        return

    def formatted_history_range(row: dict) -> str:
        from_date = parse_history_date(row.get("from"))
        to_date = parse_history_date(row.get("to"))
        if from_date is not None and to_date is not None:
            return f"{from_date:%d %b %Y} → {to_date:%d %b %Y}"
        return "Dates not detected"

    col_widths = [2.0, 0.55, 0.45, 1.0, 0.35]
    with st.container(key="dataset_summary_box"):
        st.markdown(f"<div class='dataset-summary-title'>{html_lib.escape(title)}</div>", unsafe_allow_html=True)
        header_cols = st.columns(col_widths, gap="small")
        for col, label in zip(header_cols, ["Data", "PMS", "Rows", "Date range", "Remove"]):
            col.markdown(f"<div class='dataset-summary-label'>{label}</div>", unsafe_allow_html=True)

        for idx, row in enumerate(normalized_rows):
            row_cols = st.columns(col_widths, gap="small")
            row_count = f"{int(row.get('rows') or 0):,}"
            row_cols[0].markdown(f"<div class='dataset-summary-value'>{html_lib.escape(row.get('file_name', ''))}</div>", unsafe_allow_html=True)
            row_cols[1].markdown(f"<div class='dataset-summary-value'>{html_lib.escape(row.get('pms', '-'))}</div>", unsafe_allow_html=True)
            row_cols[2].markdown(f"<div class='dataset-summary-value'>{html_lib.escape(row_count)}</div>", unsafe_allow_html=True)
            row_cols[3].markdown(f"<div class='dataset-summary-value'>{html_lib.escape(formatted_history_range(row))}</div>", unsafe_allow_html=True)
            row_key = hashlib.md5(json.dumps(row, sort_keys=True).encode("utf-8")).hexdigest()[:10]
            if row_cols[4].button(
                "Remove",
                key=f"remove_dataset_upload_button_{idx}_{row_key}",
                help="Remove this data file",
            ):
                set_main_section_tab("Upload Data")
                with busy_overlay("Removing saved data file", "Updating the clinic dataset."):
                    remove_dataset_upload_at_index(idx)
                st.rerun()


def repair_history_row_counts_from_df(history: list[dict], df_w: pd.DataFrame | None) -> tuple[list[dict], bool]:
    rows = normalize_dataset_upload_history(history)
    if not rows or df_w is None or getattr(df_w, "empty", True):
        return rows, False

    charge_dates = (
        parse_dates(df_w["ChargeDate"])
        if "ChargeDate" in df_w.columns
        else pd.Series(pd.NaT, index=df_w.index)
    )
    changed = False
    repaired = []
    for row in rows:
        fixed = dict(row)
        if parse_history_int(fixed.get("rows")) <= 0:
            start = parse_history_date(fixed.get("from"))
            end = parse_history_date(fixed.get("to"))
            if start is not None and end is not None:
                count = int(((charge_dates >= start) & (charge_dates <= end)).sum())
            else:
                count = 0
            if count <= 0 and len(rows) == 1:
                count = int(len(df_w.index))
            if count > 0:
                fixed["rows"] = count
                changed = True
        repaired.append(fixed)
    return repaired, changed


def get_saved_dataset_summary_rows() -> list[dict]:
    history = normalize_dataset_upload_history(st.session_state.get("dataset_upload_history", []))
    df_w = st.session_state.get("working_df")
    if history:
        if any(parse_history_int(row.get("rows")) <= 0 for row in history) and (
            df_w is None or getattr(df_w, "empty", True)
        ):
            clinic_id = st.session_state.get("clinic_id", "")
            attempt_key = f"{clinic_id}:{hashlib.md5(json.dumps(history, sort_keys=True).encode('utf-8')).hexdigest()}"
            if st.session_state.get("_row_count_repair_load_attempted_for") != attempt_key:
                st.session_state["_row_count_repair_load_attempted_for"] = attempt_key
                load_shared_dataset_for_clinic()
                df_w = st.session_state.get("working_df")
        repaired_history, changed = repair_history_row_counts_from_df(history, df_w)
        if changed:
            st.session_state["dataset_upload_history"] = repaired_history
            save_settings_quietly()
        return repaired_history

    df_w = drop_duplicate_columns(df_w) if df_w is not None else None
    if df_w is None or getattr(df_w, "empty", True):
        return []

    dmin, dmax = get_dataset_date_range(df_w)
    return [{
        "file_name": "Saved clinic data",
        "pms": "Unknown",
        "rows": len(df_w),
        "from": dmin.strftime("%Y-%m-%d") if dmin is not None else "",
        "to": dmax.strftime("%Y-%m-%d") if dmax is not None else "",
        "status": "Saved",
    }]

def dataset_history_needs_metadata_repair(history) -> bool:
    rows = normalize_dataset_upload_history(history)
    if not rows:
        return True
    for row in rows:
        file_name = str(row.get("file_name", "")).strip()
        pms = str(row.get("pms", "")).strip().lower()
        has_usable_range = bool(row.get("from")) and bool(row.get("to"))
        has_rows = parse_history_int(row.get("rows")) > 0
        if "<div" in file_name.lower() or file_name == "Saved clinic data":
            return True
        if pms in {"", "-", "unknown"} and (not has_usable_range or not has_rows):
            return True
    return False

def repair_dataset_upload_history_from_rows(summary_rows: list[dict]) -> bool:
    upload_history = upload_summary_rows_to_history(summary_rows, status="Saved")
    if not upload_history:
        return False
    st.session_state["dataset_upload_history"] = upload_history
    save_settings_quietly()
    return True

def render_dataset_date_range(extra_rows: list[dict] | None = None, saved_rows: list[dict] | None = None):
    rows = (saved_rows if saved_rows is not None else get_saved_dataset_summary_rows()) + normalize_dataset_upload_history(extra_rows or [])
    render_dataset_summary_box("Saved clinic data", rows)

def date_mask_covered_by_history(charge_dates: pd.Series, history_rows: list[dict]) -> pd.Series:
    covered = pd.Series(False, index=charge_dates.index)
    for row in normalize_dataset_upload_history(history_rows):
        start = parse_history_date(row.get("from"))
        end = parse_history_date(row.get("to"))
        if start is None or end is None:
            continue
        covered = covered | ((charge_dates >= start) & (charge_dates <= end))
    return covered

def remove_dataset_upload_at_index(remove_idx: int):
    clinic_id = st.session_state.get("clinic_id")
    if not clinic_id:
        st.error("Not logged in.")
        st.stop()
    clinic_id = require_authenticated_tenant_access(clinic_id)

    history = normalize_dataset_upload_history(st.session_state.get("dataset_upload_history", []))
    using_history = bool(history)
    rows = history or get_saved_dataset_summary_rows()
    if remove_idx < 0 or remove_idx >= len(rows):
        return

    target = rows[remove_idx]
    remaining_history = history[:remove_idx] + history[remove_idx + 1:] if using_history else []

    existing_file_id, existing_name = get_existing_dataset_pointer(clinic_id)

    current_df = st.session_state.get("working_df")
    if (current_df is None or getattr(current_df, "empty", True)) and existing_file_id:
        current_df = load_existing_shared_df(existing_file_id, existing_name, clinic_id=clinic_id)

    target_start = parse_history_date(target.get("from"))
    target_end = parse_history_date(target.get("to"))
    remaining_df = pd.DataFrame()
    if current_df is not None and not getattr(current_df, "empty", True) and "ChargeDate" in current_df.columns:
        source_df = current_df.copy()
        charge_dates = parse_dates(source_df["ChargeDate"])
        if target_start is not None and target_end is not None:
            target_mask = (charge_dates >= target_start) & (charge_dates <= target_end)
            covered_by_remaining_upload = date_mask_covered_by_history(charge_dates, remaining_history)
            keep_mask = charge_dates.isna() | ~target_mask | (target_mask & covered_by_remaining_upload)
        else:
            keep_mask = pd.Series(bool(remaining_history), index=source_df.index)
        remaining_df = source_df.loc[keep_mask].copy()

    if remaining_df.empty:
        clear_clinic_dataset_pointer(clinic_id)
        st.session_state.pop("working_df", None)
        st.session_state["shared_dataset_loaded"] = False
        st.session_state["shared_dataset_name"] = None
        st.session_state["shared_dataset_updated_at"] = ""
        st.session_state.pop("_shared_dataset_loaded_for", None)
    else:
        out_name = existing_name or f"{clinic_id}_shared_dataset.csv"
        out_bytes = remaining_df.drop(columns=["_ChargeDate_raw"], errors="ignore").to_csv(index=False).encode("utf-8")
        new_file_id = drive_upsert_csv_bytes(
            file_bytes=out_bytes,
            filename=out_name,
            folder_id=DATASETS_FOLDER_ID,
            existing_file_id=(existing_file_id or None),
            clinic_id=clinic_id,
        )
        updated_at = update_clinic_dataset_pointer(clinic_id, new_file_id, out_name)
        st.session_state["working_df"] = sanitize_working_df(remaining_df)
        st.session_state["data_version"] = st.session_state.get("data_version", 0) + 1
        st.session_state["shared_dataset_loaded"] = True
        st.session_state["shared_dataset_name"] = out_name
        st.session_state["shared_dataset_updated_at"] = updated_at
        remember_shared_dataset_loaded_for_current_pointer(clinic_id)

    st.session_state["dataset_upload_history"] = remaining_history
    reset_file_uploader_selection()
    save_settings_quietly()
    record_dataset_tracker_event(
        "dataset_file_removed",
        "success",
        file_name=target.get("file_name", ""),
        pms=target.get("pms", ""),
        rows=target.get("rows", ""),
        from_date=target.get("from", ""),
        to_date=target.get("to", ""),
        drive_file_id=existing_file_id,
        drive_file_name=existing_name,
        message=f"Remaining saved ranges: {len(remaining_history)}",
        source="remove_dataset_upload",
    )

def consume_dataset_upload_removal():
    remove_idx_raw = get_query_param_value("remove_dataset_upload")
    if remove_idx_raw == "":
        return
    clear_query_param("remove_dataset_upload")
    st.rerun()

def render_setup_checklist():
    steps = get_setup_checklist_steps()

    try:
        setup_panel = st.container(border=True)
    except TypeError:
        setup_panel = st.container()

    with setup_panel:
        st.markdown(
            '<p class="setup-intro">Six quick checks before you start using reminders.</p>',
            unsafe_allow_html=True,
        )
        step_cards = []
        for step in steps:
            step_cards.append(
                f"""
            <div class="setup-step {html_lib.escape(step["class_name"])}">
              <div class="setup-status">{html_lib.escape(step["status"])}</div>
              <div class="setup-title">{step["number"]}. {html_lib.escape(step["title"])}</div>
              <div class="setup-copy">{html_lib.escape(step["copy"])}</div>
              <div class="setup-where">{html_lib.escape(step["where"])}</div>
            </div>
            """
            )
        st.markdown(
            f"""
          <div class="setup-grid">
            {''.join(step_cards)}
          </div>
        """,
            unsafe_allow_html=True,
        )

    reset_col, _ = st.columns([0.85, 5], gap="small")
    with reset_col:
        if st.button("↻ Reset", key="reset_get_started_checklist", help="Reset only this guide. Clinic data and settings are not deleted."):
            st.session_state["get_started_reset_at"] = user_now().isoformat()
            save_settings_quietly()
            st.success("Get Started guide reset.")
            st.rerun()

# --------------------------------
# Session state init
# --------------------------------
if "rules" not in st.session_state:
    load_settings()
st.session_state.setdefault("weekly_message", "")
st.session_state.setdefault("search_message", "")
st.session_state.setdefault("new_rule_counter", 0)
st.session_state.setdefault("form_version", 0)
st.session_state.setdefault("deleted_reminders", [])
st.session_state.setdefault("search_terms_reviewed", False)
st.session_state.setdefault("search_term_added", False)
st.session_state.setdefault("wa_template_reviewed", False)
st.session_state.setdefault("wa_template_updated", False)
st.session_state.setdefault("get_started_reset_at", "")
st.session_state.setdefault("search_term_added_at", "")
st.session_state.setdefault("user_name_updated_at", "")
st.session_state.setdefault("wa_template_updated_at", "")
st.session_state.setdefault("dataset_upload_history", [])
st.session_state.setdefault("automatic_patient_exclusions", [])
st.session_state.setdefault("patient_passaway_keywords", PATIENT_PASSAWAY_KEYWORDS_DEFAULT.copy())

# --------------------------------
# Helpers
# -------------------------------
    
def simplify_vaccine_text(text: str) -> str:
    if not isinstance(text, str):
        return text
    parts = [p.strip() for p in text.replace(" and ", ",").split(",") if p.strip()]
    cleaned = [p.strip() for p in parts if p]
    if not cleaned:
        return text
    cleaned_lower = [c.lower() for c in cleaned]
    if "vaccination" in cleaned_lower and len(cleaned) > 1:
        cleaned = [c for c in cleaned if c.lower() != "vaccination"]
    def is_vaccine_item(s):
        s = s.lower()
        return s.endswith("vaccine") or s.endswith("vaccines") or s in ["vaccination", "vaccine(s)"]
    all_vaccines = all(is_vaccine_item(c) for c in cleaned)
    if all_vaccines:
        stripped = []
        for c in cleaned:
            tokens = c.split()
            if tokens and tokens[-1].lower().startswith("vaccine"):
                tokens = tokens[:-1]
            stripped.append(" ".join(tokens).strip())
        stripped = [s for s in stripped if s]
        if not stripped:
            return "Vaccines" if len(cleaned) > 1 else cleaned[0]
        if len(stripped) == 1:
            return stripped[0] + " Vaccine"
        elif len(stripped) == 2:
            return f"{stripped[0]} and {stripped[1]} Vaccines"
        else:
            return f"{', '.join(stripped[:-1])} and {stripped[-1]} Vaccines"
    if len(cleaned) == 1:
        return cleaned[0]
    elif len(cleaned) == 2:
        return f"{cleaned[0]} and {cleaned[1]}"
    else:
        return f"{', '.join(cleaned[:-1])} and {cleaned[-1]}"

def format_items(item_list):
    items = [str(x).strip() for x in item_list if str(x).strip()]
    if not items: return ""
    if len(items) == 1: return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]

def format_due_date(date_str: str) -> str:
    try:
        dt = pd.to_datetime(date_str, errors="coerce")
        if pd.isna(dt):
            return str(date_str or "")
        return f"{dt.strftime('%b')} {dt.day}, {dt.year}"
    except Exception:
        return str(date_str or "")


def get_visible_plan_item(item_name: str, rules: dict) -> str:
    if not isinstance(item_name, str):
        return item_name
    n = item_name.lower()
    for rule_text, settings in rules.items():
        if rule_text in n:
            vis = settings.get("visible_text")
            return vis if vis and vis.strip() else item_name
    return item_name

def normalize_item_name(name: str) -> str:
    if not isinstance(name, str):
        return ""
    name = unicodedata.normalize("NFKC", name).lower()
    name = re.sub(r"[\u00a0\ufeff]", " ", name)
    name = re.sub(r"[-+/().,]", " ", name)
    return re.sub(r"\s+", " ", name).strip()

# -------------------------
# Vectorized interval mapping
# -------------------------
@st.cache_data(show_spinner=False)

def format_due_dates_for_message(due_date_value: str) -> str:
    raw = str(due_date_value or "").strip()
    if not raw:
        return "soon"
    parts = [p.strip() for p in re.split(r"\s*[|,]\s*", raw) if p.strip()]
    if len(parts) <= 1:
        return format_due_date(raw)
    parsed = []
    for part in parts:
        dt = pd.to_datetime(part, errors="coerce")
        parsed.append((dt, part))
    parsed.sort(key=lambda x: (pd.isna(x[0]), x[0] if not pd.isna(x[0]) else pd.Timestamp.max))
    labels = [format_due_date(orig) for _, orig in parsed]
    labels = [x for x in labels if x]
    if not labels:
        return raw
    if len(labels) == 2:
        return f"{labels[0]} and {labels[1]}"
    return ", ".join(labels[:-1]) + f", and {labels[-1]}"


def build_grouped_reminder_summary(details: list[dict]) -> str:
    if not details:
        return ""

    animal_map: dict[str, dict[str, list[str]]] = {}
    for det in details:
        animal = normalize_display_case(str(det.get("Animal Name", "")).strip()) or "your pet"
        item = normalize_display_case(str(det.get("Plan Item", "")).strip()) or "treatment"
        due = str(det.get("Due Date", "")).strip()
        animal_map.setdefault(animal, {}).setdefault(due, []).append(item)

    animal_phrases = []
    for animal in sorted(animal_map, key=lambda x: x.lower()):
        date_groups = animal_map[animal]
        sorted_dates = sorted(
            date_groups.keys(),
            key=lambda x: pd.to_datetime(x, errors="coerce") if str(x).strip() else pd.Timestamp.max,
        )

        due_phrases = []
        for due in sorted_dates:
            items = format_items(sorted(set(date_groups[due])))
            due_fmt = format_due_date(due)
            due_phrases.append(f"their {items} on {due_fmt}")

        if len(due_phrases) == 1:
            animal_phrases.append(f"{animal} is due {due_phrases[0]}")
        else:
            animal_phrases.append(f"{animal} is due {', and '.join(due_phrases)}")

    return ". ".join(animal_phrases)


def _summarize_client_cluster(cluster_df: pd.DataFrame, client_name: str, rules: dict | None = None):
    return _summarize_client_cluster_records(cluster_df.to_dict("records"), client_name, rules)


def _summarize_client_cluster_records(records: list[dict], client_name: str, rules: dict | None = None):
    due_dates = set()
    reminder_dates = set()
    animals = set()
    all_items = []
    reminder_details = []
    qty_sum = 0.0
    qty_seen = False
    interval_min = None
    charge_dates = []

    def coerce_number(value):
        if value is None:
            return None
        try:
            if pd.isna(value):
                return None
        except (TypeError, ValueError):
            pass
        value_text = str(value).strip()
        if not value_text:
            return None
        try:
            return float(value_text.replace(",", ""))
        except (TypeError, ValueError):
            return None

    for row in records:
        due_date = str(row.get("DueDateFmt", "")).strip()
        if due_date:
            due_dates.add(due_date)

        reminder_date = str(row.get("ReminderDateFmt", "")).strip()
        if reminder_date:
            reminder_dates.add(reminder_date)

        animal = str(row.get("Animal Name", "")).strip()
        if animal:
            animals.add(animal)

        val = row.get("MatchedItems", [])
        if isinstance(val, list):
            all_items.extend([str(x).strip() for x in val if str(x).strip()])
        else:
            s = str(val).strip()
            if s:
                all_items.append(s)

        q = coerce_number(row.get("Qty"))
        if q is not None:
            qty_sum += q
            qty_seen = True

        interval = coerce_number(row.get("IntervalDays"))
        if interval is not None:
            interval_min = interval if interval_min is None else min(interval_min, interval)

        charge_date = str(row.get("ChargeDateFmt", "")).strip()
        if charge_date:
            charge_dates.append(charge_date)

        detail_animal = animal or "your pet"
        item_name = str(row.get("Item Name", "")).strip()
        if not item_name and isinstance(row.get("MatchedItems"), list):
            item_name = format_items([str(x).strip() for x in row.get("MatchedItems", []) if str(x).strip()])
        raw_search_terms = row.get("MatchedSearchTerms", [])
        if isinstance(raw_search_terms, list):
            search_terms = sorted({str(x).strip() for x in raw_search_terms if str(x).strip()})
        else:
            search_terms = [str(raw_search_terms).strip()] if str(raw_search_terms or "").strip() else []
        item_name = simplify_vaccine_text(item_name or "treatment")
        due_value = str(row.get("DueDateFmt") or row.get("NextDueDate") or row.get("Due Date") or "").strip()
        reminder_details.append({
            "Animal Name": detail_animal,
            "Plan Item": item_name,
            "Due Date": due_value,
            "Reminder Date": reminder_date,
            "Charge Date": charge_date,
            "Qty": str(row.get("Qty", "") or "").strip(),
            "Days": str(row.get("IntervalDays", "") or "").strip(),
            "Search Terms": " | ".join(search_terms),
        })

    animals = sorted(animals)
    due_dates = sorted(due_dates)
    reminder_dates = sorted(reminder_dates)
    items_text = simplify_vaccine_text(format_items(sorted(set(all_items))))

    n_animals = len(animals)
    n_items = len(set(all_items))
    is_grouped = len(records) > 1 or (n_animals > 1) or (n_items > 1) or (len(due_dates) > 1)

    days_qty = int(interval_min) if interval_min is not None else ""
    qty_value = qty_sum if qty_seen else np.nan

    return {
        "Reminder Date": " | ".join(reminder_dates),
        "Due Date": " | ".join(due_dates),
        "Charge Date": max(charge_dates) if charge_dates else "",
        "Client Name": client_name,
        "Animal Name": format_items(animals),
        "Plan Item": items_text,
        "Qty": "NA" if is_grouped else qty_value,
        "Days": "NA" if is_grouped else days_qty,
        "ReminderDetails": reminder_details,
    }

def bundle_client_reminders_by_window(due_df: pd.DataFrame, window_days: int = 5, rules: dict | None = None) -> pd.DataFrame:
    if due_df.empty:
        return pd.DataFrame(columns=["Reminder Date", "Due Date", "Charge Date", "Client Name", "Animal Name", "Plan Item", "Qty", "Days", "ReminderDetails"])

    out_rows = []
    work = due_df.copy()
    reminder_col = "ReminderDate" if "ReminderDate" in work.columns else "NextDueDate"
    work["_ReminderDateTs"] = pd.to_datetime(work[reminder_col], errors="coerce")
    work["_ClientSortKey"] = work["Client Name"].astype(str).fillna("")
    sorted_records = work.sort_values(
        ["_ClientSortKey", "_ReminderDateTs", "ChargeDate"],
        ascending=[True, True, True],
        na_position="last",
    ).to_dict("records")

    if window_days <= 0:
        for row in sorted_records:
            out_rows.append(_summarize_client_cluster_records([row], row.get("Client Name", ""), rules))
        grouped = pd.DataFrame(out_rows)
        if grouped.empty:
            return pd.DataFrame(columns=["Reminder Date", "Due Date", "Charge Date", "Client Name", "Animal Name", "Plan Item", "Qty", "Days"])
        grouped["Qty"] = grouped["Qty"].where(
            grouped["Qty"].astype(str) == "NA",
            pd.to_numeric(grouped["Qty"], errors="coerce").fillna(0).astype(int)
        )
        return grouped[["Reminder Date", "Due Date", "Charge Date", "Client Name", "Animal Name", "Plan Item", "Qty", "Days", "ReminderDetails"]]

    def client_group_key(value) -> str:
        if pd.isna(value):
            return ""
        return str(value)

    max_gap_days = max(int(window_days) - 1, 0)
    current_client_key = None
    current_client_name = ""
    cluster = []
    anchor = None

    for row in sorted_records:
        row_client_name = row.get("Client Name", "")
        row_client_key = client_group_key(row_client_name)
        reminder_ts = row.get("_ReminderDateTs")

        if current_client_key is None or row_client_key != current_client_key:
            if cluster:
                out_rows.append(_summarize_client_cluster_records(cluster, current_client_name, rules))
            current_client_key = row_client_key
            current_client_name = row_client_name
            cluster = [row]
            anchor = reminder_ts
            continue

        same_cluster = pd.notna(reminder_ts) and pd.notna(anchor) and abs((reminder_ts - anchor).days) <= max_gap_days
        if same_cluster:
            cluster.append(row)
        else:
            out_rows.append(_summarize_client_cluster_records(cluster, current_client_name, rules))
            cluster = [row]
            anchor = reminder_ts

    if cluster:
        out_rows.append(_summarize_client_cluster_records(cluster, current_client_name, rules))

    grouped = pd.DataFrame(out_rows)
    if grouped.empty:
        return pd.DataFrame(columns=["Reminder Date", "Due Date", "Charge Date", "Client Name", "Animal Name", "Plan Item", "Qty", "Days"])

    grouped["Qty"] = grouped["Qty"].where(
        grouped["Qty"].astype(str) == "NA",
        pd.to_numeric(grouped["Qty"], errors="coerce").fillna(0).astype(int)
    )
    return grouped[["Reminder Date", "Due Date", "Charge Date", "Client Name", "Animal Name", "Plan Item", "Qty", "Days", "ReminderDetails"]]
def _positive_int_or_na(value):
    try:
        if value is None or str(value).strip() == "":
            return pd.NA
        parsed = int(str(value).strip())
        return parsed if parsed > 0 else pd.NA
    except (TypeError, ValueError):
        return pd.NA


def map_intervals_vec(df, rules):
    df = df.copy()
    if "ItemNorm" not in df.columns:
        def _norm(name):
            if not isinstance(name, str): return ""
            s = unicodedata.normalize("NFKC", name).lower()
            s = re.sub(r"[\u00a0\ufeff]", " ", s)
            s = re.sub(r"[-+/().,]", " ", s)
            return re.sub(r"\s+", " ", s).strip()
        df["ItemNorm"] = df["Item Name"].astype(str).map(_norm)

    n = len(df)

    # IntervalDays = may use qty (existing behaviour)
    interval_qty = pd.Series(pd.NA, index=df.index, dtype="Float64")

    # BaseIntervalDays = NEVER uses qty (new)
    interval_base = pd.Series(pd.NA, index=df.index, dtype="Float64")
    reminder_1 = pd.Series(pd.NA, index=df.index, dtype="Float64")
    reminder_2 = pd.Series(pd.NA, index=df.index, dtype="Float64")
    overdue_reminder = pd.Series(pd.NA, index=df.index, dtype="Float64")

    matched = pd.Series([[] for _ in range(n)], index=df.index, dtype=object)
    matched_search_terms = pd.Series([[] for _ in range(n)], index=df.index, dtype=object)

    item_norm = df["ItemNorm"].astype(str)

    for rule_text, settings in rules.items():
        term = str(rule_text or "").lower().strip()
        if not term:
            continue
        mask = item_norm.str.contains(term, regex=False, na=False)
        if not mask.any():
            continue

        days = int(settings["days"])

        # Base is always just 'days'
        base_cand = pd.Series(days, index=df.index)[mask]
        interval_base = interval_base.where(~mask, pd.concat([interval_base[mask], base_cand], axis=1).min(axis=1))
        reminder_1_days = _positive_int_or_na(settings.get("reminder_1"))
        reminder_2_days = _positive_int_or_na(settings.get("reminder_2"))
        overdue_reminder_days = _positive_int_or_na(settings.get("overdue_reminder"))
        if pd.notna(reminder_1_days):
            reminder_1_cand = pd.Series(int(reminder_1_days), index=df.index)[mask]
            reminder_1 = reminder_1.where(~mask, pd.concat([reminder_1[mask], reminder_1_cand], axis=1).min(axis=1))
        if pd.notna(reminder_2_days):
            reminder_2_cand = pd.Series(int(reminder_2_days), index=df.index)[mask]
            reminder_2 = reminder_2.where(~mask, pd.concat([reminder_2[mask], reminder_2_cand], axis=1).min(axis=1))
        if pd.notna(overdue_reminder_days):
            overdue_cand = pd.Series(int(overdue_reminder_days), index=df.index)[mask]
            overdue_reminder = overdue_reminder.where(~mask, pd.concat([overdue_reminder[mask], overdue_cand], axis=1).min(axis=1))

        # Qty interval uses qty only if rule says so
        if settings.get("use_qty"):
            qty = pd.to_numeric(df.loc[mask, "Qty"], errors="coerce").fillna(1).astype(int).clip(lower=1)
            qty_cand = qty * days
        else:
            qty_cand = pd.Series(days, index=df.index)[mask]

        interval_qty = interval_qty.where(~mask, pd.concat([interval_qty[mask], qty_cand], axis=1).min(axis=1))

        # Matched visible items
        vis = settings.get("visible_text", "").strip()
        idxs = df.index[mask]
        if vis:
            for i in idxs: matched.at[i].append(vis)
        else:
            for i in idxs: matched.at[i].append(df.at[i, "Item Name"])
        for i in idxs:
            matched_search_terms.at[i].append(rule_text)

    df["MatchedItems"] = [list({x.strip() for x in lst if str(x).strip()}) for lst in matched.tolist()]
    df["MatchedSearchTerms"] = [list({str(x).strip() for x in lst if str(x).strip()}) for lst in matched_search_terms.tolist()]
    df["IntervalDays"] = interval_qty
    df["BaseIntervalDays"] = interval_base
    df["Reminder1Days"] = reminder_1
    df["Reminder2Days"] = reminder_2
    df["OverdueReminderDays"] = overdue_reminder
    return df


def expand_reminder_dates(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df

    day_cols = ["Reminder1Days", "Reminder2Days", "OverdueReminderDays", "IntervalDays"]
    day_frame = pd.DataFrame(index=df.index)
    for col in day_cols:
        if col in df.columns:
            day_frame[col] = pd.to_numeric(df[col], errors="coerce")
        else:
            day_frame[col] = np.nan

    valid_mask = day_frame.gt(0).any(axis=1)
    if not valid_mask.any():
        return df.iloc[0:0].copy()

    work = df.loc[valid_mask].copy()
    day_frame = day_frame.loc[valid_mask]
    out = []
    for rec, day_values in zip(work.to_dict("records"), day_frame.itertuples(index=False, name=None)):
        reminder_days = sorted({
            int(value)
            for value in day_values
            if pd.notna(value) and int(value) > 0
        })

        for reminder_day in reminder_days:
            expanded = rec.copy()
            expanded["ReminderDays"] = reminder_day
            expanded["ReminderDate"] = expanded.get("ChargeDate") + pd.to_timedelta(reminder_day, unit="D")
            expanded["ReminderDateTs"] = pd.to_datetime(expanded.get("ReminderDate"), errors="coerce")
            expanded["ReminderDateFmt"] = (
                expanded["ReminderDateTs"].strftime("%d %b %Y")
                if pd.notna(expanded["ReminderDateTs"])
                else ""
            )
            out.append(expanded)

    if not out:
        return df.iloc[0:0].copy()
    return pd.DataFrame(out).reset_index(drop=True)

@st.cache_data(show_spinner=False)
def ensure_reminder_columns(df: pd.DataFrame, rules: dict) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=[
            "ReminderDateFmt", "DueDateFmt", "Client Name", "ChargeDateFmt", "Animal Name",
            "MatchedItems", "MatchedSearchTerms", "Qty", "IntervalDays", "BaseIntervalDays", "Reminder1Days", "Reminder2Days", "OverdueReminderDays",
            "NextDueDate", "NextDueDateBase", "NextDueDateTs", "ReminderDate", "ReminderDateTs", "ChargeDate"
        ])

    df = df.copy()
    for col, default in [
        ("ChargeDate", pd.NaT),
        ("Client Name", ""),
        ("Animal Name", ""),
        ("Item Name", ""),
        ("Qty", 1),
        ("Amount", 0),
    ]:
        if col not in df.columns:
            df[col] = default

    if not pd.api.types.is_datetime64_any_dtype(df["ChargeDate"]):
        df["ChargeDate"] = parse_dates(df["ChargeDate"])

    # ✅ this creates BOTH IntervalDays and BaseIntervalDays
    df = map_intervals_vec(df, rules)

    days_qty  = pd.to_numeric(df.get("IntervalDays"), errors="coerce")
    days_base = pd.to_numeric(df.get("BaseIntervalDays"), errors="coerce")

    df["NextDueDate"]      = df["ChargeDate"] + pd.to_timedelta(days_qty, unit="D")
    df["NextDueDateBase"]  = df["ChargeDate"] + pd.to_timedelta(days_base, unit="D")
    df["NextDueDateTs"]    = pd.to_datetime(df["NextDueDate"], errors="coerce")

    df["ChargeDateFmt"] = pd.to_datetime(df["ChargeDate"]).dt.strftime("%d %b %Y")
    df["DueDateFmt"]    = df["NextDueDateTs"].dt.strftime("%d %b %Y")

    df["MatchedItems"] = df["MatchedItems"].apply(
        lambda v: [str(x).strip() for x in v] if isinstance(v, list) else ([str(v)] if pd.notna(v) else [])
    )

    # ✅ hard guarantee column exists even if something upstream changes
    if "BaseIntervalDays" not in df.columns:
        df["BaseIntervalDays"] = pd.NA
    for col in ["Reminder1Days", "Reminder2Days", "OverdueReminderDays"]:
        if col not in df.columns:
            df[col] = pd.NA

    return df

def drop_early_duplicates_fast(df: pd.DataFrame) -> pd.DataFrame:
    """
    Keeps only the most recent treatment record per client–animal–item combination
    before the next treatment occurs, even if that next treatment happens early.
    In effect:
      - Each new treatment resets the due date.
      - Any previous record with the same item before that new charge is dropped.
    """
    if df.empty:
        return df

    df = df.copy()
    df["MatchedItems_str"] = df["MatchedItems"].apply(
        lambda x: ", ".join(sorted(x)) if isinstance(x, list) else str(x)
    )

    # Sort chronologically within each client–animal–item
    df.sort_values(
        ["Client Name", "Animal Name", "MatchedItems_str", "ChargeDate"],
        inplace=True,
        ignore_index=True
    )

    # Within each animal+item, find the next charge date
    g = df.groupby(["Client Name", "Animal Name", "MatchedItems_str"], dropna=False)
    next_charge = g["ChargeDate"].shift(-1)

    # Rule:
    #  - Drop any row that has a later charge for the same item, regardless of early/late.
    #  - Keep only the last one (most recent) before the next charge.
    keep = next_charge.isna()

    return df.loc[keep].drop(columns=["MatchedItems_str"]).reset_index(drop=True)


def _exclusion_key(value) -> str:
    return _SPACE_RX.sub(" ", str(value or "").strip()).lower()


def apply_reminder_exclusion_filters(df: pd.DataFrame, rules: dict) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    if "Item Name" in df.columns:
        df["Plan Item"] = df["Item Name"].apply(
            lambda x: simplify_vaccine_text(get_visible_plan_item(x, rules))
        )
    elif "Plan Item" not in df.columns:
        df["Plan Item"] = ""
    client_exclusions = st.session_state.get("client_exclusions", [])
    if client_exclusions and "Client Name" in df.columns:
        excluded_clients = {
            _exclusion_key(name)
            for name in client_exclusions
            if str(name or "").strip()
        }
        if excluded_clients:
            client_keys = df["Client Name"].map(_exclusion_key)
            df = df[~client_keys.isin(excluded_clients)]
    patient_exclusions = combined_patient_exclusions()
    if patient_exclusions and {"Client Name", "Animal Name"}.issubset(df.columns):
        excluded_patient_pairs = {
            (
                _exclusion_key(item.get("client", "")),
                _exclusion_key(item.get("patient", "")),
            )
            for item in patient_exclusions
            if isinstance(item, dict) and str(item.get("client", "") or "").strip() and str(item.get("patient", "") or "").strip()
        }
        if excluded_patient_pairs:
            row_pairs = list(zip(
                df["Client Name"].map(_exclusion_key),
                df["Animal Name"].map(_exclusion_key),
            ))
            df = df[[pair not in excluded_patient_pairs for pair in row_pairs]]
    item_exclusions = [str(term or "").strip().lower() for term in st.session_state.get("exclusions", []) if str(term or "").strip()]
    if item_exclusions:
        excl_pattern = "|".join(map(re.escape, item_exclusions))
        target_col = "Item Name" if "Item Name" in df.columns else "Plan Item"
        df = df[~df[target_col].astype(str).str.lower().str.contains(excl_pattern, regex=True, na=False)]
    return df


def build_prepared_reminder_rows(working_df: pd.DataFrame, rules: dict) -> pd.DataFrame:
    prepared = ensure_reminder_columns(working_df, rules)
    prepared = drop_early_duplicates_fast(prepared)
    prepared = expand_reminder_dates(prepared)
    return prepared


def filter_sales_as_of_date(working_df: pd.DataFrame, as_of_date: date | None) -> pd.DataFrame:
    if working_df is None:
        return pd.DataFrame()
    if working_df.empty or as_of_date is None or "ChargeDate" not in working_df.columns:
        return working_df.copy()

    charge_dates = parse_dates(working_df["ChargeDate"])
    cutoff = pd.Timestamp(as_of_date).normalize()
    keep_mask = charge_dates.isna() | (charge_dates <= cutoff)
    return working_df.loc[keep_mask].copy()


def get_prepared_df(working_df: pd.DataFrame, rules: dict) -> pd.DataFrame:
    key = (st.session_state.get("data_version", 0), _rules_fp(rules), PREPARED_SCHEMA_VERSION)
    if st.session_state.get("prepared_key") != key:
        prepared = build_prepared_reminder_rows(working_df, rules)

        st.session_state["prepared_df"] = prepared
        st.session_state["prepared_key"] = key

    return st.session_state["prepared_df"]


def parse_reminder_date_parts(value) -> list[date]:
    if value is None:
        return []
    if isinstance(value, datetime):
        return [value.date()]
    if isinstance(value, date):
        return [value]
    parsed_dates = []
    for part in str(value or "").split("|"):
        part = part.strip()
        if not part:
            continue
        parsed = pd.to_datetime(part, errors="coerce")
        if pd.notna(parsed):
            parsed_dates.append(parsed.date())
    return parsed_dates


def reminder_row_dates(row: dict) -> list[date]:
    return parse_reminder_date_parts(row.get("Reminder Date", "") or row.get("ReminderDate", ""))


def reminder_row_has_date(row: dict, target_date: date) -> bool:
    return target_date in reminder_row_dates(row)


def normalized_reminder_window_days(value=None) -> int:
    value = st.session_state.get("reminder_window_days", 1) if value is None else value
    try:
        return min(30, max(0, int(value)))
    except (TypeError, ValueError):
        return 1


def normalized_reminder_lookback_days(value=None) -> int:
    value = st.session_state.get("reminder_lookback_days", DEFAULT_REMINDER_LOOKBACK_DAYS) if value is None else value
    try:
        return min(30, max(0, int(value)))
    except (TypeError, ValueError):
        return DEFAULT_REMINDER_LOOKBACK_DAYS


def normalized_reminder_group_days(value=None) -> int:
    value = st.session_state.get("client_group_days", 1) if value is None else value
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 1


def normalized_reminder_warning_days(value=None) -> int:
    value = st.session_state.get("reminder_warning_days", 0) if value is None else value
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def normalized_outcome_due_date_window_days(value=None) -> int:
    value = (
        st.session_state.get("outcome_due_date_window_days", DEFAULT_OUTCOME_DUE_DATE_WINDOW_DAYS)
        if value is None
        else value
    )
    try:
        return min(1095, max(0, int(value)))
    except (TypeError, ValueError):
        return DEFAULT_OUTCOME_DUE_DATE_WINDOW_DAYS


def load_outcome_due_date_window_days(settings: dict) -> None:
    raw_value = settings.get("outcome_due_date_window_days", _SETTING_MISSING)
    has_current_value = "outcome_due_date_window_days" in st.session_state
    current_value = (
        normalized_outcome_due_date_window_days()
        if has_current_value
        else DEFAULT_OUTCOME_DUE_DATE_WINDOW_DAYS
    )
    loaded_value = st.session_state.get(OUTCOME_DUE_DATE_WINDOW_LOADED_KEY, _SETTING_MISSING)

    if raw_value is _SETTING_MISSING or raw_value in (None, ""):
        if has_current_value:
            st.session_state["outcome_due_date_window_days"] = current_value
            return
        st.session_state["outcome_due_date_window_days"] = DEFAULT_OUTCOME_DUE_DATE_WINDOW_DAYS
        st.session_state[OUTCOME_DUE_DATE_WINDOW_LOADED_KEY] = DEFAULT_OUTCOME_DUE_DATE_WINDOW_DAYS
        st.session_state[OUTCOME_DUE_DATE_WINDOW_DIRTY_KEY] = False
        return

    saved_value = normalized_outcome_due_date_window_days(raw_value)
    if has_current_value and st.session_state.get(OUTCOME_DUE_DATE_WINDOW_DIRTY_KEY):
        if current_value == saved_value:
            st.session_state[OUTCOME_DUE_DATE_WINDOW_DIRTY_KEY] = False
            st.session_state[OUTCOME_DUE_DATE_WINDOW_LOADED_KEY] = saved_value
        else:
            st.session_state["outcome_due_date_window_days"] = current_value
        return

    if has_current_value and loaded_value is not _SETTING_MISSING:
        loaded_value = normalized_outcome_due_date_window_days(loaded_value)
        if current_value != loaded_value and current_value != saved_value:
            st.session_state["outcome_due_date_window_days"] = current_value
            st.session_state[OUTCOME_DUE_DATE_WINDOW_DIRTY_KEY] = True
            return

    st.session_state["outcome_due_date_window_days"] = saved_value
    st.session_state[OUTCOME_DUE_DATE_WINDOW_LOADED_KEY] = saved_value
    st.session_state[OUTCOME_DUE_DATE_WINDOW_DIRTY_KEY] = False


def save_outcome_due_date_window_days() -> None:
    value = normalized_outcome_due_date_window_days()
    st.session_state["outcome_due_date_window_days"] = value
    st.session_state[OUTCOME_DUE_DATE_WINDOW_DIRTY_KEY] = True
    if save_settings_quietly():
        st.session_state[OUTCOME_DUE_DATE_WINDOW_DIRTY_KEY] = False
        st.session_state[OUTCOME_DUE_DATE_WINDOW_LOADED_KEY] = value


def normalized_reminders_start_date(value=None, default_date: date | None = None) -> date:
    default_date = default_date or user_today()
    value = default_date if value is None else value
    try:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            return default_date
        return parsed.date()
    except Exception:
        return default_date


def initialize_reminder_filter_controls(default_start: date | None = None) -> date:
    default_start = default_start or user_today()
    if st.session_state.pop("_reminders_start_date_today_requested", False):
        st.session_state["reminders_start_date"] = default_start
        st.session_state[REMINDERS_START_DATE_INPUT_KEY] = default_start
    else:
        remembered_start = normalized_reminders_start_date(
            st.session_state.get("reminders_start_date", st.session_state.get(REMINDERS_START_DATE_INPUT_KEY)),
            default_start,
        )
        widget_start = normalized_reminders_start_date(
            st.session_state.get(REMINDERS_START_DATE_INPUT_KEY, remembered_start),
            default_start,
        )
        st.session_state["reminders_start_date"] = widget_start
        st.session_state[REMINDERS_START_DATE_INPUT_KEY] = widget_start

    st.session_state["reminder_window_days"] = normalized_reminder_window_days()
    st.session_state["reminder_lookback_days"] = normalized_reminder_lookback_days()
    st.session_state["client_group_days"] = normalized_reminder_group_days()
    st.session_state["reminder_warning_days"] = normalized_reminder_warning_days()
    return st.session_state[REMINDERS_START_DATE_INPUT_KEY]


def reminder_row_in_date_range(row: dict, start_date: date, end_date: date) -> bool:
    return any(start_date <= reminder_date <= end_date for reminder_date in reminder_row_dates(row))


def get_active_reminder_badge_count(today: date | None = None) -> int:
    working_df = st.session_state.get("working_df")
    if working_df is None or getattr(working_df, "empty", True):
        return 0
    today = today or user_today()
    lookback_start_date = today - timedelta(days=normalized_reminder_lookback_days())
    try:
        rules = get_applied_reminder_rules()
        prepared = get_prepared_df(working_df, rules)
        reminder_ts = prepared.get("ReminderDateTs")
        if reminder_ts is None:
            reminder_ts = prepared.get("NextDueDateTs")
        if reminder_ts is None:
            reminder_ts = pd.to_datetime(prepared["NextDueDate"], errors="coerce")

        start_ts = pd.Timestamp(lookback_start_date)
        end_ts = pd.Timestamp(today)
        due = prepared[(reminder_ts >= start_ts) & (reminder_ts <= end_ts)].copy()
        due = apply_reminder_exclusion_filters(due, rules)
        if due.empty:
            return 0

        grouped = bundle_client_reminders_by_window(due, window_days=normalized_reminder_group_days(), rules=rules)
        if grouped.empty:
            return 0
        grouped_badge_range = grouped[
            [reminder_row_in_date_range(row, lookback_start_date, today) for row in grouped.to_dict("records")]
        ].copy()
        active_badge_range = filter_hidden_reminders(grouped_badge_range)
        return len(active_badge_range.index)
    except Exception:
        return 0


def get_today_active_reminder_count(today: date | None = None) -> int:
    return get_active_reminder_badge_count(today=today)


def reminders_badge_label(count: int | None = None) -> str:
    count = get_active_reminder_badge_count() if count is None else int(count or 0)
    if count <= 0:
        return "Reminders"
    return tab_badge_label("Reminders", count, f"{count} active reminders in the look-back window")


def reminders_caught_up_period_text(lookback_days: int) -> str:
    try:
        lookback_days = max(0, int(lookback_days))
    except (TypeError, ValueError):
        lookback_days = DEFAULT_REMINDER_LOOKBACK_DAYS
    if lookback_days == 0:
        return "today"
    if lookback_days == 1:
        return "today and yesterday"
    return f"today and the previous {lookback_days} days"


def reminders_caught_up_banner_copy(active_count: int, lookback_days: int) -> tuple[str, str] | None:
    try:
        active_count = int(active_count or 0)
    except (TypeError, ValueError):
        active_count = 0
    if active_count > 0:
        return None
    return (
        "Good job! All due reminders have been actioned.",
        f"Your Reminders notification is clear for {reminders_caught_up_period_text(lookback_days)}.",
    )


def should_show_no_reminders_info(reminders_before_exclusions: int, active_count: int | None) -> bool:
    if reminders_before_exclusions:
        return True
    try:
        return int(active_count or 0) > 0
    except (TypeError, ValueError):
        return False


def render_reminders_caught_up_banner(active_count: int | None = None, lookback_days: int | None = None):
    count = get_active_reminder_badge_count() if active_count is None else active_count
    lookback = normalized_reminder_lookback_days() if lookback_days is None else lookback_days
    copy = reminders_caught_up_banner_copy(count, lookback)
    if not copy:
        return
    title, body = copy
    st.markdown(
        f"""
        <div class="reminders-caught-up-banner">
          <div class="reminders-caught-up-icon">&#10003;</div>
          <div>
            <p class="reminders-caught-up-title">{html_lib.escape(title)}</p>
            <p class="reminders-caught-up-copy">{html_lib.escape(body)}</p>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


st.markdown(
    """
    <style>
      div[data-testid="stTabs"] div[role="tablist"] button,
      div[data-testid="stTabs"] div[role="tablist"] button p,
      div[data-testid="stTabs"] div[role="tablist"] [role="tab"],
      div[data-testid="stTabs"] div[role="tablist"] [role="tab"] p,
      button[data-baseweb="tab"],
      button[data-baseweb="tab"] p {
        font-size: 1rem !important;
        font-weight: 600 !important;
        line-height: 1.2 !important;
      }
      div[data-testid="stHorizontalBlock"]:has([class*="st-key-main_section_nav_"]) {
        align-items: flex-end;
        column-gap: 0.2rem !important;
        justify-content: flex-start !important;
        margin: 0.35rem 0 0 !important;
      }
      div[data-testid="stHorizontalBlock"]:has([class*="st-key-main_section_nav_"]) > div[data-testid="column"] {
        flex: 0 0 auto !important;
        min-width: fit-content !important;
        width: auto !important;
      }
      .cr-main-section-nav-rule {
        border-bottom: 1px solid var(--cr-border);
        margin: -1px 0 1rem;
      }
      [class*="st-key-main_section_nav_"] button {
        background: var(--cr-primary-quiet);
        border: 1px solid var(--cr-border);
        border-bottom: 0;
        border-radius: 8px 8px 0 0;
        box-shadow: inset 0 -1px 0 var(--cr-border);
        color: #23513a !important;
        display: inline-flex;
        font-size: 1.08rem;
        font-weight: 800;
        gap: 0.35rem;
        justify-content: center;
        line-height: 1.2;
        margin: 0 0 -1px;
        min-height: 2.55rem;
        padding: 0.45rem 0.75rem;
        text-decoration: none !important;
        white-space: nowrap;
      }
      [class*="st-key-main_section_nav_"] button:hover {
        background: var(--cr-primary-soft);
        border-color: var(--cr-border);
        color: #062d19 !important;
        text-decoration: none !important;
      }
      [class*="st-key-main_section_nav_"] button p,
      [class*="st-key-main_section_nav_"] button span {
        color: #23513a !important;
        font-size: 1.08rem !important;
        font-weight: 800 !important;
        line-height: 1.2 !important;
      }
      [class*="st-key-main_section_nav_"] button img {
        display: inline-block !important;
        height: 1.1rem !important;
        margin-left: 0.25rem !important;
        max-width: none !important;
        vertical-align: -0.15rem !important;
      }
      [class*="st-key-main_section_nav_"] button:focus {
        box-shadow: inset 0 -1px 0 var(--cr-border), 0 0 0 2px rgba(34, 197, 94, 0.25) !important;
      }
      .st-key-main_section_tab {
        border-bottom: 1px solid var(--cr-border);
        margin: 0.35rem 0 1rem;
        overflow: visible !important;
        padding-top: 0.15rem;
      }
      .st-key-main_section_tab [data-testid="stSegmentedControl"],
      .st-key-main_section_tab div[role="radiogroup"] {
        align-items: flex-end !important;
        display: flex !important;
        flex-wrap: wrap !important;
        gap: 0.2rem !important;
        overflow: visible !important;
      }
      .st-key-main_section_tab [role="radio"],
      .st-key-main_section_tab button,
      .st-key-main_section_tab label {
        background: var(--cr-primary-quiet) !important;
        border: 1px solid var(--cr-border) !important;
        border-bottom: 0 !important;
        border-radius: 8px 8px 0 0 !important;
        box-shadow: inset 0 -1px 0 var(--cr-border) !important;
        color: #23513a !important;
        font-size: 1.35rem !important;
        font-weight: 800 !important;
        line-height: 1.2 !important;
        margin: 0 0 -1px !important;
        min-height: 3rem !important;
        padding: 0.55rem 0.9rem !important;
        white-space: nowrap !important;
      }
      .st-key-main_section_tab [role="radio"] p,
      .st-key-main_section_tab [role="radio"] span,
      .st-key-main_section_tab button p,
      .st-key-main_section_tab button span,
      .st-key-main_section_tab label p,
      .st-key-main_section_tab label span {
        color: #23513a !important;
        font-size: 1.35rem !important;
        font-weight: 800 !important;
        line-height: 1.2 !important;
      }
      .st-key-main_section_tab [role="radio"]:hover,
      .st-key-main_section_tab button:hover,
      .st-key-main_section_tab label:hover {
        background: var(--cr-primary-soft) !important;
        color: #062d19 !important;
      }
      .st-key-main_section_tab [role="radio"][aria-checked="true"],
      .st-key-main_section_tab [role="radio"][aria-selected="true"],
      .st-key-main_section_tab [data-baseweb="button-group"] [aria-checked="true"],
      .st-key-main_section_tab [data-baseweb="button"][aria-checked="true"],
      .st-key-main_section_tab [aria-checked="true"],
      .st-key-main_section_tab button[aria-pressed="true"],
      .st-key-main_section_tab button[aria-selected="true"],
      .st-key-main_section_tab label:has(input:checked) {
        background: var(--cr-surface) !important;
        border-color: var(--cr-primary-dark) !important;
        box-shadow: inset 0 4px 0 var(--cr-primary-dark), 0 1px 0 var(--cr-surface) !important;
        color: #062d19 !important;
        position: relative !important;
        z-index: 1 !important;
      }
      .st-key-main_section_tab [aria-checked="true"] p,
      .st-key-main_section_tab [aria-checked="true"] span,
      .st-key-main_section_tab [data-baseweb="button-group"] [aria-checked="true"] p,
      .st-key-main_section_tab [data-baseweb="button-group"] [aria-checked="true"] span,
      .st-key-main_section_tab [aria-selected="true"] p,
      .st-key-main_section_tab [aria-selected="true"] span,
      .st-key-main_section_tab button[aria-pressed="true"] p,
      .st-key-main_section_tab button[aria-pressed="true"] span,
      .st-key-main_section_tab label:has(input:checked) p,
      .st-key-main_section_tab label:has(input:checked) span {
        color: #062d19 !important;
      }
      .st-key-main_section_tab [aria-checked="true"]:hover,
      .st-key-main_section_tab [data-baseweb="button-group"] [aria-checked="true"]:hover,
      .st-key-main_section_tab [data-baseweb="button"][aria-checked="true"]:hover {
        background: var(--cr-surface) !important;
        border-color: var(--cr-primary-dark) !important;
      }
      div[data-testid="stTabs"] div[role="tablist"] {
        align-items: flex-end !important;
        border-bottom: 1px solid var(--cr-border) !important;
        flex-wrap: nowrap !important;
        gap: 0.2rem !important;
        margin-bottom: 1rem !important;
        overflow-x: auto !important;
        scrollbar-width: thin !important;
      }
      div[data-testid="stTabs"] div[role="tablist"] button,
      div[data-testid="stTabs"] div[role="tablist"] [role="tab"],
      button[data-baseweb="tab"] {
        background: var(--cr-primary-quiet) !important;
        border: 1px solid var(--cr-border) !important;
        border-bottom: 0 !important;
        border-radius: 8px 8px 0 0 !important;
        box-shadow: inset 0 -1px 0 var(--cr-border) !important;
        margin: 0 0 -1px !important;
        min-height: 2.3rem !important;
        padding: 0.35rem 0.7rem !important;
        white-space: nowrap !important;
      }
      div[data-testid="stTabs"] div[role="tablist"] button img,
      div[data-testid="stTabs"] div[role="tablist"] [role="tab"] img,
      button[data-baseweb="tab"] img {
        display: inline-block !important;
        height: 1.1rem !important;
        margin-left: 0.25rem !important;
        max-width: none !important;
        vertical-align: -0.15rem !important;
      }
      div[data-testid="stTabs"] div[role="tablist"] button[aria-selected="true"],
      div[data-testid="stTabs"] div[role="tablist"] [role="tab"][aria-selected="true"],
      button[data-baseweb="tab"][aria-selected="true"] {
        background: var(--cr-primary) !important;
        border-color: var(--cr-primary) !important;
        box-shadow: 0 1px 0 var(--cr-primary) !important;
        position: relative !important;
        z-index: 1 !important;
      }
      div[data-testid="stTabs"] div[role="tablist"] button:hover,
      div[data-testid="stTabs"] div[role="tablist"] [role="tab"]:hover,
      button[data-baseweb="tab"]:hover {
        background: var(--cr-primary-soft) !important;
      }
      div[data-testid="stTabs"] div[role="tablist"] button[aria-selected="true"]:hover,
      div[data-testid="stTabs"] div[role="tablist"] [role="tab"][aria-selected="true"]:hover,
      button[data-baseweb="tab"][aria-selected="true"]:hover {
        background: var(--cr-primary) !important;
      }
      div[data-testid="stTabs"] div[role="tablist"] button p,
      div[data-testid="stTabs"] div[role="tablist"] [role="tab"] p {
        color: #23513a !important;
      }
      div[data-testid="stTabs"] div[role="tablist"] button[aria-selected="true"],
      div[data-testid="stTabs"] div[role="tablist"] [role="tab"][aria-selected="true"] {
        filter: saturate(1.08) brightness(1.03) !important;
      }
      div[data-testid="stTabs"] div[role="tablist"] button[aria-selected="true"] p,
      div[data-testid="stTabs"] div[role="tablist"] [role="tab"][aria-selected="true"] p {
        color: #062d19 !important;
      }
      div[data-testid="stTabs"] div[data-testid="stTabs"] div[role="tablist"] button,
      div[data-testid="stTabs"] div[data-testid="stTabs"] div[role="tablist"] button p,
      div[data-testid="stTabs"] div[data-testid="stTabs"] div[role="tablist"] [role="tab"],
      div[data-testid="stTabs"] div[data-testid="stTabs"] div[role="tablist"] [role="tab"] p {
        color: var(--cr-text) !important;
        font-size: 1rem !important;
        font-weight: 500 !important;
      }
      div[data-testid="stTabs"] div[data-testid="stTabs"] div[role="tablist"] button[aria-selected="true"],
      div[data-testid="stTabs"] div[data-testid="stTabs"] div[role="tablist"] [role="tab"][aria-selected="true"],
      div[data-testid="stTabs"] div[data-testid="stTabs"] button[data-baseweb="tab"][aria-selected="true"] {
        background: var(--cr-surface) !important;
        border-color: var(--cr-border) !important;
        box-shadow: 0 1px 0 var(--cr-surface) !important;
        filter: none !important;
        font-weight: 600 !important;
      }
      div[data-testid="stTabs"] div[data-testid="stTabs"] div[role="tablist"] button,
      div[data-testid="stTabs"] div[data-testid="stTabs"] div[role="tablist"] [role="tab"],
      div[data-testid="stTabs"] div[data-testid="stTabs"] button[data-baseweb="tab"] {
        background: var(--cr-surface-muted) !important;
        filter: none !important;
        min-height: 2.15rem !important;
        padding: 0.35rem 0.8rem !important;
      }
      @media (max-width: 900px) {
        [class*="st-key-main_section_nav_"] button {
          min-height: 2.65rem;
          padding: 0.45rem 0.65rem;
        }
        [class*="st-key-main_section_nav_"] button p,
        [class*="st-key-main_section_nav_"] button span {
          font-size: 1.05rem !important;
        }
        .st-key-main_section_tab [role="radio"],
        .st-key-main_section_tab button,
        .st-key-main_section_tab label,
        .st-key-main_section_tab [role="radio"] p,
        .st-key-main_section_tab [role="radio"] span,
        .st-key-main_section_tab button p,
        .st-key-main_section_tab button span,
        .st-key-main_section_tab label p,
        .st-key-main_section_tab label span {
          font-size: 1.05rem !important;
        }
        .st-key-main_section_tab [role="radio"],
        .st-key-main_section_tab button,
        .st-key-main_section_tab label {
          min-height: 2.65rem !important;
          padding: 0.45rem 0.65rem !important;
        }
        div[data-testid="stTabs"] div[role="tablist"] button,
        div[data-testid="stTabs"] div[role="tablist"] button p,
        div[data-testid="stTabs"] div[role="tablist"] [role="tab"],
        div[data-testid="stTabs"] div[role="tablist"] [role="tab"] p,
        button[data-baseweb="tab"],
        button[data-baseweb="tab"] p {
          font-size: 0.95rem !important;
        }
        div[data-testid="stTabs"] div[role="tablist"] button,
        div[data-testid="stTabs"] div[role="tablist"] [role="tab"],
        button[data-baseweb="tab"] {
          padding: 0.38rem 0.55rem !important;
        }
      }
      @media (max-width: 640px) {
        [class*="st-key-main_section_nav_"] button p,
        [class*="st-key-main_section_nav_"] button span {
          font-size: 0.98rem !important;
        }
        .st-key-main_section_tab [role="radio"],
        .st-key-main_section_tab button,
        .st-key-main_section_tab label,
        .st-key-main_section_tab [role="radio"] p,
        .st-key-main_section_tab [role="radio"] span,
        .st-key-main_section_tab button p,
        .st-key-main_section_tab button span,
        .st-key-main_section_tab label p,
        .st-key-main_section_tab label span {
          font-size: 0.98rem !important;
        }
        div[data-testid="stTabs"] div[role="tablist"] button,
        div[data-testid="stTabs"] div[role="tablist"] button p,
        div[data-testid="stTabs"] div[role="tablist"] [role="tab"],
        div[data-testid="stTabs"] div[role="tablist"] [role="tab"] p,
        button[data-baseweb="tab"],
        button[data-baseweb="tab"] p {
          font-size: 0.9rem !important;
        }
      }
    </style>
    """,
    unsafe_allow_html=True,
)
consume_main_section_tab_query_param()
default_main_section_tab = canonical_main_section_tab(st.session_state.get("main_section_tab", "Reminders"))
if default_main_section_tab not in MAIN_SECTION_TABS:
    default_main_section_tab = "Reminders"
st.session_state["main_section_tab"] = default_main_section_tab
active_main_section = default_main_section_tab
render_main_section_nav(active_main_section)
if active_main_section not in MAIN_SECTION_TABS:
    active_main_section = "Reminders"
    set_main_section_tab(active_main_section)

# --- Data section ---
if active_main_section == "Get Started":
    st.markdown("<div id='getting-started' class='anchor-offset'></div>", unsafe_allow_html=True)
    st.markdown("## ✅ Get Started")
    render_setup_checklist()

if active_main_section == "Upload Data":
    st.markdown("<div id='data-upload' class='anchor-offset'></div>", unsafe_allow_html=True)
    st.markdown(
        """
        <section class="cr-page-hero">
          <p class="cr-page-kicker">Upload Data</p>
          <h2>Keep your reminder data current</h2>
          <p>Upload one or more sales exports from your PMS. Clinic Reminders saves the active clinic dataset and keeps your search terms, exclusions, templates, and action history separate.</p>
        </section>
        """,
        unsafe_allow_html=True,
    )
    saved_dataset_rows = get_saved_dataset_summary_rows()
    render_dataset_status(saved_dataset_rows)
    dataset_summary_slot = st.empty()
    with dataset_summary_slot.container():
        render_dataset_date_range(saved_rows=saved_dataset_rows)
        render_dataset_summary_checks(saved_dataset_rows)
    datasets = []
    summary_rows = []
    working_df = None

    # File uploader
    # --------------------------------
    with st.container(border=True):
        st.markdown(
            """
            <div class="cr-field-intro">
              <div class="cr-section-title">Upload files</div>
              <p class="cr-section-copy">Choose recent sales exports. The app will check the format, merge valid files, and save the result for this clinic account.</p>
              <p class="cr-field-footnote">Supported systems: VETport, ezyVet, Xpress, or a clean sales export.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("What should uploaded sales data look like?", key="open_upload_sales_data_help"):
            st.session_state["show_upload_sales_data_help_dialog"] = True
            st.rerun()
        render_field_label(
            st,
            "Upload sales data files",
            "Upload one or more sales exports. Valid uploads are saved for everyone using this clinic login."
        )
        files = st.file_uploader(
            "Upload sales data files",
            type=["csv", "xls", "xlsx"],
            accept_multiple_files=True,
            key=f"file_uploader_main_{st.session_state.get('file_uploader_reset_version', 0)}",
            label_visibility="collapsed",
        )
    
    # --------------------------------
    # Cache invalidation logic — clear when files added/removed/renamed
    # --------------------------------
    if "last_uploaded_files" not in st.session_state:
        st.session_state["last_uploaded_files"] = []
    
    current_files = [f.name for f in files] if files else []
    
    # Detect any file addition, deletion, or rename
    if set(current_files) != set(st.session_state["last_uploaded_files"]):
        set_main_section_tab("Upload Data")
        st.toast("Files changed - refreshing upload.")

        close_account_dialogs()
        close_upload_sales_data_help_dialog()
        st.session_state["last_uploaded_files"] = current_files
        st.session_state["data_version"] = st.session_state.get("data_version", 0) + 1
        reset_uploaded_data_state(clear_cache=False)
        if not current_files:
            load_shared_dataset_for_clinic()
    
        st.rerun()
    
    
    # --------------------------------
    # File upload handling
    # --------------------------------
    if files:
        try:
            file_blobs = tuple(_to_blob(f) for f in files)
            current_upload_key = upload_fingerprint(file_blobs)
        except UploadResourceLimitError as e:
            record_dataset_tracker_event(
                "upload_parse_failed",
                "error",
                file_name=", ".join(current_files),
                message=str(e),
                source="file_uploader",
            )
            record_error_tracker_event(
                "upload_parse_failed",
                stage="prepare_upload_blobs",
                error=e,
                source="file_uploader",
            )
            st.toast("Upload is too large.")
            st.warning(str(e))
            st.stop()
    
        saved_upload_history = st.session_state.get("dataset_upload_history", [])
        if upload_save_can_be_skipped(
            current_upload_key,
            st.session_state.get("last_saved_upload_key", ""),
            saved_upload_history,
        ):
            try:
                _, summary_rows = summarize_uploads(file_blobs, UPLOAD_SUMMARY_SCHEMA_VERSION)
            except Exception:
                summary_rows = []
            existing_history_rows = normalize_dataset_upload_history(saved_upload_history)
            if summary_rows and not existing_history_rows:
                repair_dataset_upload_history_from_rows(summary_rows)
                st.rerun()
        else:
            # summarize_uploads is cached, so repeated reruns reuse parsed upload data.
            parse_started = time.perf_counter()
            try:
                datasets, summary_rows = summarize_uploads(file_blobs, UPLOAD_SUMMARY_SCHEMA_VERSION)
            except UploadResourceLimitError as e:
                record_dataset_tracker_event(
                    "upload_parse_failed",
                    "error",
                    file_name=", ".join(current_files),
                    message=str(e),
                    source="file_uploader",
                )
                record_error_tracker_event(
                    "upload_parse_failed",
                    stage="summarize_uploads",
                    error=e,
                    source="file_uploader",
                )
                record_performance_tracker_event(
                    "upload_parse",
                    (time.perf_counter() - parse_started) * 1000,
                    status="error",
                    message=str(e),
                    source="file_uploader",
                )
                st.toast("Upload is too large.")
                st.warning(str(e))
                st.stop()
            except UploadValidationError as e:
                record_dataset_tracker_event(
                    "upload_parse_failed",
                    "error",
                    file_name=", ".join(current_files),
                    message=str(e),
                    source="file_uploader",
                )
                record_error_tracker_event(
                    "upload_parse_failed",
                    stage="summarize_uploads",
                    error=e,
                    source="file_uploader",
                )
                record_performance_tracker_event(
                    "upload_parse",
                    (time.perf_counter() - parse_started) * 1000,
                    status="error",
                    message=str(e),
                    source="file_uploader",
                )
                st.toast("Upload needs a different format.")
                st.warning(
                    "This upload does not look like a supported sales export. "
                    + str(e)
                    + " Please upload a file with client, patient, item, sales amount or quantity, and date fields."
                )
                st.stop()
            except Exception as e:
                record_dataset_tracker_event(
                    "upload_parse_failed",
                    "error",
                    file_name=", ".join(current_files),
                    message=str(e),
                    source="file_uploader",
                )
                record_error_tracker_event(
                    "upload_parse_failed",
                    stage="summarize_uploads",
                    error=e,
                    source="file_uploader",
                )
                record_performance_tracker_event(
                    "upload_parse",
                    (time.perf_counter() - parse_started) * 1000,
                    status="error",
                    message=str(e),
                    source="file_uploader",
                )
                st.toast("Upload could not be read.")
                st.warning(
                    "This file could not be read as a supported clinic sales export. "
                    "Please check that it includes client, patient, item, sales amount or quantity, and date fields."
                )
                st.stop()
            record_performance_tracker_event(
                "upload_parse",
                (time.perf_counter() - parse_started) * 1000,
                rows=sum(len(df) for _, df in datasets),
                status="success",
                message=", ".join(current_files),
                source="file_uploader",
            )
    
            all_pms = {p for p, _ in datasets}
            # --- Case 1: All files from same PMS ---
            if len(all_pms) == 1 and "Undetected" not in all_pms:
                working_df = pd.concat([df for _, df in datasets], ignore_index=True)
                st.session_state["working_df"] = sanitize_working_df(working_df)
                st.caption(f"Files recognised as {list(all_pms)[0]} — saving automatically.")
    
            # --- Case 2: Mixed PMS or undetected but schema-compatible ---
            else:
                try:
                    cand = pd.concat([df for _, df in datasets], ignore_index=True, sort=False)
                    required_cols = ["ChargeDate", "Client Name", "Animal Name", "Item Name", "Qty", "Amount"]
    
                    if all(c in cand.columns for c in required_cols):
                        working_df = cand
                        st.session_state["working_df"] = sanitize_working_df(working_df)
                        st.caption("Files look compatible — saving automatically.")
                    else:
                        st.warning("These files do not use a supported format, so reminders cannot be generated reliably.")
    
                except Exception:
                    st.warning("These files could not be recognised, so reminders cannot be generated.")
                    st.session_state.pop("working_df", None)
    
            if st.session_state.get("working_df") is not None and not st.session_state["working_df"].empty:
                new_df = st.session_state["working_df"].copy()
                new_df = new_df.drop(columns=["_ChargeDate_raw"], errors="ignore")
                new_df = ensure_min_canonical_schema(new_df)
                upload_min, upload_max = dataset_date_bounds(new_df)
                clinic_id = st.session_state.get("clinic_id")
                if not clinic_id:
                    st.error("Not logged in.")
                    st.stop()
    
                existing_file_id, existing_name = get_existing_dataset_pointer(clinic_id)
                existing_df = None
                if existing_file_id:
                    try:
                        existing_df = load_existing_shared_df(existing_file_id, existing_name, clinic_id=clinic_id)
                    except Exception as e:
                        record_error_tracker_event(
                            "existing_dataset_load_failed",
                            stage="upload_existing_dataset_check",
                            error=e,
                            source="file_uploader",
                        )
                        record_dataset_tracker_event(
                            "upload_save_failed",
                            "error",
                            file_name=", ".join(current_files),
                            message=str(e),
                            source="file_uploader",
                        )
                        st.error(
                            "Could not load the existing clinic data, so this upload was not saved. "
                            "Please try again before replacing clinic data."
                        )
                        st.stop()
    
                def save_uploaded_dataset(replace_overlapping_dates: bool = False):
                    publish_started = time.perf_counter()
                    try:
                        merged_df, new_file_id, out_name = publish_dataset_for_clinic(
                            clinic_id=clinic_id,
                            new_df=new_df,
                            datasets_folder_id=DATASETS_FOLDER_ID,
                            replace_overlapping_dates=replace_overlapping_dates,
                            existing_file_id=existing_file_id,
                            existing_name=existing_name,
                            existing_df=existing_df,
                        )
                    except Exception as e:
                        record_dataset_tracker_event(
                            "upload_save_failed",
                            "error",
                            file_name=", ".join(current_files),
                            replace_overlapping_dates=replace_overlapping_dates,
                            message=str(e),
                            source="file_uploader",
                        )
                        record_error_tracker_event(
                            "upload_save_failed",
                            stage="publish_dataset_for_clinic",
                            error=e,
                            source="file_uploader",
                        )
                        record_performance_tracker_event(
                            "dataset_publish",
                            (time.perf_counter() - publish_started) * 1000,
                            status="error",
                            message=str(e),
                            source="file_uploader",
                        )
                        raise
    
                    st.session_state["working_df"] = sanitize_working_df(merged_df)
                    st.session_state["data_version"] = st.session_state.get("data_version", 0) + 1
                    st.session_state["shared_dataset_loaded"] = True
                    st.session_state["shared_dataset_name"] = out_name
                    remember_shared_dataset_loaded_for_current_pointer(st.session_state.get("clinic_id", ""))
                    existing_upload_history = st.session_state.get("dataset_upload_history", [])
                    st.session_state["dataset_upload_history"] = merge_dataset_upload_history(
                        existing_upload_history,
                        upload_summary_rows_to_history(summary_rows, status="Saved"),
                        replace_overlapping_dates=replace_overlapping_dates,
                        upload_min=upload_min,
                        upload_max=upload_max,
                    )
                    saved_history_rows = upload_summary_rows_to_history(summary_rows, status="Saved")
                    for summary_row in saved_history_rows:
                        record_dataset_tracker_event(
                            "upload_saved",
                            "success",
                            file_name=summary_row.get("file_name", ""),
                            pms=summary_row.get("pms", ""),
                            rows=summary_row.get("rows", ""),
                            from_date=summary_row.get("from", ""),
                            to_date=summary_row.get("to", ""),
                            replace_overlapping_dates=replace_overlapping_dates,
                            drive_file_id=new_file_id,
                            drive_file_name=out_name,
                            source="file_uploader",
                        )
                    record_performance_tracker_event(
                        "dataset_publish",
                        (time.perf_counter() - publish_started) * 1000,
                        rows=len(merged_df),
                        status="success",
                        message=out_name,
                        source="file_uploader",
                    )
                    st.session_state["last_saved_upload_key"] = current_upload_key
                    st.session_state["file_uploader_reset_version"] = st.session_state.get("file_uploader_reset_version", 0) + 1
                    st.session_state["last_uploaded_files"] = []
                    set_main_section_tab("Upload Data")
                    merged_min, merged_max = dataset_date_bounds(merged_df)
                    st.session_state["_pending_dataset_success"] = format_dataset_saved_summary(
                        len(merged_df),
                        merged_min,
                        merged_max,
                    )
                    add_automatic_patient_exclusions_from_upload(new_df)
                    save_settings_quietly()
    
                    st.rerun()
    
                with busy_overlay("Saving clinic data", "Larger exports can take a moment."):
                    save_uploaded_dataset()
    
    # -------------------------------------
    # Clear Clinic Data
    # -------------------------------------
    def clear_saved_clinic_data():
        set_main_section_tab("Upload Data")
        clinic_id = st.session_state.get("clinic_id")
        if not clinic_id:
            st.error("Not logged in.")
            st.stop()

        with busy_overlay("Clearing clinic data", "Removing the saved clinic data."):
            # Grab current pointer so we can optionally trash it
            try:
                existing_file_id, existing_name = get_existing_dataset_pointer(clinic_id)
            except Exception as e:
                existing_file_id, existing_name = "", ""
                st.warning("Could not check the saved data file, but the clinic data will still be cleared.")

            # 1) Clear pointer in settings sheet (THIS is the key)
            clear_clinic_dataset_pointer(clinic_id)

            # 2) Optional: trash the old file in Drive
            # drive_trash_file(existing_file_id)

            # 3) Clear local state so UI resets immediately
            reset_uploaded_data_state(clear_cache=False, reset_uploader=True)

            st.session_state["shared_dataset_loaded"] = False
            st.session_state["shared_dataset_name"] = None
            st.session_state["shared_dataset_error"] = None
            st.session_state["dataset_upload_history"] = []
            st.session_state.pop("_shared_dataset_loaded_for", None)
            save_settings_quietly()
            record_dataset_tracker_event(
                "dataset_cleared",
                "success",
                drive_file_id=existing_file_id,
                drive_file_name=existing_name,
                message="Clinic data cleared",
                source="clear_clinic_data",
            )

        st.rerun()

    with st.container(border=True):
        st.markdown(
            """
            <div class="cr-field-intro">
              <div class="cr-section-title">Clear Clinic Data</div>
              <p class="cr-section-copy">Remove the active saved clinic data while keeping settings, search terms, exclusions, templates, and action history. To remove the clinic account and everything attached to it, use Account > Delete account and data.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if not st.session_state.get("show_clear_clinic_data_confirm", False):
            if st.button(
                "Clear clinic data",
                key="start_clear_clinic_data",
                help="Clear clinic data so the clinic behaves like no data is saved.",
            ):
                st.session_state["show_clear_clinic_data_confirm"] = True
                st.session_state["confirm_reset_dataset"] = False
                st.rerun()
        else:
            st.markdown(
                """
                <div class="cr-field-danger-note">Please confirm this clinic data clear. Settings, search terms, exclusions, templates, and action history stay in place.</div>
                """,
                unsafe_allow_html=True,
            )
            confirm_reset = st.checkbox(
                "I understand this will remove clinic data for my clinic",
                key="confirm_reset_dataset",
            )
            confirm_col, cancel_col = st.columns([1, 1])
            with confirm_col:
                if st.button(
                    "Clear clinic data",
                    key="confirm_clear_clinic_data",
                    disabled=not confirm_reset,
                    help="Clear clinic data so the clinic behaves like no data is saved.",
                    use_container_width=True,
                ):
                    st.session_state["show_clear_clinic_data_confirm"] = False
                    clear_saved_clinic_data()
            with cancel_col:
                if st.button("Cancel", key="cancel_clear_clinic_data", use_container_width=True):
                    st.session_state["show_clear_clinic_data_confirm"] = False
                    st.session_state["confirm_reset_dataset"] = False
                    st.rerun()

# --------------------------------
# Render Tables
# --------------------------------
def render_table(df, title, key_prefix, msg_key, rules):
    if df.empty:
        st.info(f"No reminders in {title}.")
        return
    df = apply_reminder_exclusion_filters(df, rules)
    if df.empty:
        st.info("All reminders in this view are hidden by exclusions.")
        return

    show_pending_recent_reminder_warning()

    active_tab, actioned_tab = st.tabs(["Active Reminders", "Actioned Reminders"])
    with active_tab:
        active_df = filter_hidden_reminders(df)
        if active_df.empty:
            st.info("All reminders have been actioned.")
        else:
            render_table_with_buttons(active_df, key_prefix, msg_key)

    with actioned_tab:
        render_actioned_reminders_tab(key_prefix)

    render_whatsapp_tools(key_prefix, msg_key)


def render_sender_name_input(key_suffix: str):
    prev_name = st.session_state.get("user_name", "")
    render_field_label(
        st,
        "Your name / clinic",
        "This fills [Your Name] in prepared WhatsApp messages and records who actioned reminders.",
        class_name="reminder-control-label",
    )
    new_name = st.text_input(
        "Your name / clinic (appears in WhatsApp messages):",
        value=prev_name,
        key=f"user_name_input_{key_suffix}",
        placeholder="e.g. Mary from Neighbourhood Veterinary Clinic",
        label_visibility="collapsed",
    )

    if new_name != prev_name:
        st.session_state["user_name"] = new_name
        st.session_state["user_name_updated_at"] = user_now().isoformat()
        save_settings_quietly()


def build_whatsapp_message_for_row(row) -> str:
    client_name = row.get("Client Name", "")
    first_name = normalize_display_case(client_name).split()[0].strip() if client_name else "there"
    animal_name = normalize_display_case(row.get("Animal Name", "")).strip() if row.get("Animal Name") else "your pet"
    plan_for_msg = normalize_display_case(row.get("Plan Item", "")).strip()
    user = st.session_state.get("user_name", "").strip()
    due_date_fmt = format_due_dates_for_message(str(row.get("Due Date", "")))

    template = (st.session_state.get("user_template", "") or DEFAULT_WA_TEMPLATE).strip()

    def replace_case_insensitive(text, placeholder, value):
        pattern = re.compile(re.escape(placeholder), re.IGNORECASE)
        return pattern.sub(value, text)

    message = template
    message = replace_case_insensitive(message, "[Client Name]", first_name)
    message = replace_case_insensitive(message, "[Your Name]", user or "our clinic")

    reminder_details = row.get("ReminderDetails") or []
    grouped_summary = build_grouped_reminder_summary(reminder_details) if len(reminder_details) > 1 else ""

    if grouped_summary and "[ReminderSummary]" in message:
        message = replace_case_insensitive(message, "[ReminderSummary]", grouped_summary)
    elif grouped_summary:
        # Try to replace a common template clause if found
        pattern = re.compile(r"\[Pet Name\].*?\[Due Date\]", flags=re.IGNORECASE | re.DOTALL)
        if pattern.search(message):
            message = pattern.sub(grouped_summary, message)
        else:
            message = f"Hi {first_name}, this is {user or 'our clinic'}. Just reminding you that {grouped_summary}."

    if not grouped_summary:
        message = replace_case_insensitive(message, "[Pet Name]", animal_name)
        message = replace_case_insensitive(message, "[Item]", plan_for_msg)
        message = replace_case_insensitive(message, "[Due Date]", due_date_fmt)

    # Grammar fix: "<Names> is" -> "are" when multiple pets listed
    has_multiple_pets = bool(re.search(r"(?:\s+(?:and|&)\s+|,)", animal_name, flags=re.IGNORECASE))
    if has_multiple_pets:
        pattern = re.compile(rf"({re.escape(animal_name)})\s+is\b", flags=re.IGNORECASE)
        message, _ = pattern.subn(r"\1 are", message, count=1)

    return message


def hide_revealed_reminders_after_action(key_prefix: str):
    st.session_state[f"{key_prefix}_reveal_hidden_reminders"] = False


def queue_recent_reminder_warning(message: str | None, key: str):
    if message:
        st.session_state["_pending_recent_reminder_warning"] = {
            "message": message,
            "key": key,
        }


def show_pending_recent_reminder_warning():
    pending = st.session_state.pop("_pending_recent_reminder_warning", None)
    if isinstance(pending, dict):
        show_recent_reminder_warning(
            str(pending.get("message", "")),
            key=str(pending.get("key", "recent_reminder_ok")),
        )


def prepare_whatsapp_action(row_data: dict, key_prefix: str, msg_key: str, idx):
    set_main_section_tab("Reminders")
    client_name = row_data.get("Client Name", "")
    now = utc_now()
    warning_message = get_recent_reminder_warning(client_name, now=now)
    queue_recent_reminder_warning(warning_message, key=f"{key_prefix}_recent_reminder_ok_{idx}")

    message = build_whatsapp_message_for_row(row_data)
    st.session_state[msg_key] = message
    st.session_state["_scroll_to_whatsapp_composer"] = True


def mark_reminder_sent_action(row_data: dict, key_prefix: str, msg_key: str, idx):
    set_main_section_tab("Reminders")
    client_name = row_data.get("Client Name", "")
    now = utc_now()
    hidden_record = get_hidden_reminder_record(row_data)
    hidden_action = str((hidden_record or {}).get("Action", "")).strip().lower()

    warning_message = get_recent_reminder_warning(client_name, now=now)
    queue_recent_reminder_warning(warning_message, key=f"{key_prefix}_recent_sent_ok_{idx}")

    message = build_whatsapp_message_for_row(row_data)
    st.session_state[msg_key] = message
    if hidden_action != REMINDER_ACTION_SENT:
        if not record_action_tracker(row_data, REMINDER_ACTION_SENT, message=message, source=f"{key_prefix}_sent", now=now):
            remember_action_tracker_save_failure()
            return
        record_wa_reminder_click(client_name, now=now, row=row_data, save=False)
    upsert_hidden_reminder(row_data, REMINDER_ACTION_SENT, message=message, now=now)
    hide_revealed_reminders_after_action(key_prefix)


def mark_all_listed_reminders_sent_action(rows: list[dict], key_prefix: str, msg_key: str):
    with busy_overlay("Marking reminders as sent", "Saving the listed reminders and updating action history."):
        set_main_section_tab("Reminders")
        now = utc_now()
        rows_to_send = []
        messages_by_key = {}
        tracker_rows = []

        for row_data in rows or []:
            if not isinstance(row_data, dict):
                continue
            hidden_record = get_hidden_reminder_record(row_data)
            hidden_action = str((hidden_record or {}).get("Action", "")).strip().lower()
            if hidden_action == REMINDER_ACTION_SENT:
                continue
            message = build_whatsapp_message_for_row(row_data)
            tracker_rows.append(
                action_tracker_row_values(
                    row_data,
                    REMINDER_ACTION_SENT,
                    message=message,
                    source=f"{key_prefix}_send_all",
                    now=now,
                )
            )
            rows_to_send.append(row_data)
            messages_by_key[hidden_reminder_key(row_data)] = message

        if not rows_to_send:
            st.session_state["_bulk_sent_success"] = "No active reminders needed marking as sent."
            hide_revealed_reminders_after_action(key_prefix)
            return

        if not append_tracker_rows(ACTION_TRACKER_WORKSHEET, ACTION_TRACKER_HEADERS, tracker_rows):
            remember_action_tracker_save_failure()
            return

        for row_data in rows_to_send:
            message = messages_by_key.get(hidden_reminder_key(row_data), "")
            st.session_state[msg_key] = message
            record_wa_reminder_click(row_data.get("Client Name", ""), now=now, row=row_data, save=False)
            upsert_hidden_reminder(row_data, REMINDER_ACTION_SENT, message=message, now=now)

        st.session_state["_bulk_sent_success"] = f"Marked {len(rows_to_send)} reminder{'s' if len(rows_to_send) != 1 else ''} as sent."
        hide_revealed_reminders_after_action(key_prefix)


def decline_reminder_action(row_data: dict, key_prefix: str):
    set_main_section_tab("Reminders")
    now = utc_now()
    hidden_record = get_hidden_reminder_record(row_data)
    hidden_action = str((hidden_record or {}).get("Action", "")).strip().lower()
    if hidden_action != REMINDER_ACTION_DECLINED:
        if not record_action_tracker(row_data, REMINDER_ACTION_DECLINED, source=f"{key_prefix}_declined", now=now):
            remember_action_tracker_save_failure()
            return
    if hidden_action == REMINDER_ACTION_SENT:
        remove_wa_reminder_click_for_row(row_data, queue_settings_removal=False)
    upsert_hidden_reminder(row_data, REMINDER_ACTION_DECLINED, now=now)
    hide_revealed_reminders_after_action(key_prefix)


def remove_actioned_reminder_action(row_data: dict, key_prefix: str):
    set_main_section_tab("Reminders")
    hidden_record = get_hidden_reminder_record(row_data) or row_data
    hidden_action = str(hidden_record.get("Action", "")).strip().lower()
    with busy_overlay("Saving reminder action", "Returning this reminder to Active Reminders."):
        if not record_action_tracker(row_data, "active", source=f"{key_prefix}_undo", now=utc_now()):
            remember_action_tracker_save_failure()
            return
        if hidden_action == REMINDER_ACTION_SENT:
            remove_wa_reminder_click_for_row(row_data)
        remove_actioned_reminder(row_data)
        save_settings_quietly()


def render_search_criteria_refresh_notice():
    if st.session_state.pop("_search_criteria_refreshed", False):
        st.success("Reminders refreshed with the latest search criteria.")

    if not search_criteria_have_pending_changes():
        return

    notice_col, button_col = st.columns([5, 1.2], gap="small")
    with notice_col:
        st.error("Search criteria have changed. Refresh reminders to apply the latest changes.")
    with button_col:
        st.button(
            "Refresh reminders",
            type="primary",
            use_container_width=True,
            on_click=apply_search_criteria_changes,
        )


REMINDER_TABLE_SORTABLE_COLUMNS = ("Reminder Date", "Due Date", "Charge Date", "Client Name", "Animal Name", "Plan Item")
REMINDER_TABLE_HEADER_LABELS = {"Charge Date": "Billed Date", "Plan Item": "Item"}
REMINDER_TABLE_COLUMN_HELP = {
    "Actioned Date": "When this reminder was marked Sent or Declined.",
    "Actioned By": "The sender name saved in the Reminders tab when the reminder was actioned.",
    "Reminder Date": "The date this reminder is scheduled to appear in this workflow.",
    "Due Date": "The date the product, service, or vaccine is due again.",
    "Charge Date": "The original billed date from the uploaded sales data.",
    "Client Name": "The client attached to this reminder.",
    "Animal Name": "The patient or grouped patients attached to this reminder.",
    "Plan Item": "The reminder item shown in the table and inserted into WhatsApp messages.",
    "Qty": "The billed quantity. NA means the row is grouped or quantity does not apply.",
    "Days": "The reminder interval in days. NA means the row is grouped or no interval is shown.",
    "WhatsApp": "Prepare this client's message and jump to the WhatsApp Composer, where you can review and edit before sending.",
    "Sent": "Mark the reminder as sent and move it to Actioned Reminders.",
    "Decline": "Mark the reminder as declined and move it to Actioned Reminders.",
    "Action": "Shows whether the reminder was marked Sent or Declined.",
    "Undo": "Move this reminder back to Active Reminders.",
}


def reminder_header_help(column: str) -> str:
    return REMINDER_TABLE_COLUMN_HELP.get(column, f"Sort by {REMINDER_TABLE_HEADER_LABELS.get(column, column)}")


def render_column_help_icon(container, help_text: str, align: str = "left"):
    safe_help = html_lib.escape(help_text)
    container.markdown(
        f"<div style='text-align:{align}; line-height:1.6rem;'><span class='column-help' data-tooltip='{safe_help}'>?</span></div>",
        unsafe_allow_html=True,
    )


def render_sortable_reminder_header(container, label: str, help_text: str, button_kwargs: dict, width_units: float):
    base_label = re.sub(r"\s+[↑↓]$", "", str(label or "")).strip()
    label_units = min(max(0.9, len(base_label) * 0.11 + 0.25), max(0.9, width_units - 0.25))
    help_units = 0.16
    spacer_units = max(0.1, width_units - label_units - help_units)
    button_col, help_col, _ = container.columns([label_units, help_units, spacer_units], gap="small")
    button_col.button(label, **button_kwargs)
    render_column_help_icon(help_col, help_text)


def render_reminder_header_label(container, label: str, column: str, align: str = "left"):
    safe_label = html_lib.escape(label)
    safe_help = html_lib.escape(reminder_header_help(column))
    container.markdown(
        f"<div style='text-align:{align}; font-weight:600;'>{safe_label} <span class='column-help' data-tooltip='{safe_help}'>?</span></div>",
        unsafe_allow_html=True,
    )


def set_reminder_table_sort(key_prefix: str, column: str):
    state_key = f"{key_prefix}_reminder_sort"
    current = st.session_state.get(state_key)
    ascending = True
    if isinstance(current, dict) and current.get("column") == column:
        ascending = not bool(current.get("ascending", True))
    st.session_state[state_key] = {"column": column, "ascending": ascending}
    st.session_state[f"{key_prefix}_reminders_page"] = 0


def get_reminder_table_sort(key_prefix: str) -> dict:
    current = st.session_state.get(f"{key_prefix}_reminder_sort")
    if isinstance(current, dict) and current.get("column") in REMINDER_TABLE_SORTABLE_COLUMNS:
        return {"column": current["column"], "ascending": bool(current.get("ascending", True))}
    return {"column": "Reminder Date", "ascending": True}


def parse_reminder_sort_date(value):
    first_value = str(value or "").split("|", 1)[0].strip()
    return pd.to_datetime(first_value, errors="coerce", dayfirst=True)


def sort_reminder_table(df: pd.DataFrame, key_prefix: str) -> pd.DataFrame:
    sort_state = get_reminder_table_sort(key_prefix)
    sort_column = sort_state["column"]
    if sort_column not in df.columns:
        return df

    sorted_df = df.copy()
    helper_col = "__reminder_sort_value"
    if sort_column in {"Reminder Date", "Due Date", "Charge Date"}:
        sorted_df[helper_col] = sorted_df[sort_column].map(parse_reminder_sort_date)
    else:
        sorted_df[helper_col] = sorted_df[sort_column].astype(str).map(lambda value: normalize_display_case(value).casefold())

    return (
        sorted_df
        .sort_values(helper_col, ascending=sort_state["ascending"], kind="mergesort", na_position="last")
        .drop(columns=[helper_col])
    )


def paginate_dataframe(frame: pd.DataFrame, key: str, page_size: int, item_label: str) -> pd.DataFrame:
    if frame is None or frame.empty or page_size <= 0 or len(frame.index) <= page_size:
        return frame
    total_rows = len(frame.index)
    total_pages = max(1, int(np.ceil(total_rows / page_size)))
    page_key = f"{key}_page"
    try:
        current_page = int(st.session_state.get(page_key, 0) or 0)
    except (TypeError, ValueError):
        current_page = 0
    current_page = min(max(current_page, 0), total_pages - 1)
    st.session_state[page_key] = current_page

    start = current_page * page_size
    end = min(start + page_size, total_rows)
    st.caption(f"Showing {start + 1:,}-{end:,} of {total_rows:,} {item_label}.")
    prev_col, next_col, _ = st.columns([1, 1, 6])
    with prev_col:
        if st.button("Previous", key=f"{page_key}_prev", disabled=current_page <= 0):
            st.session_state[page_key] = max(0, current_page - 1)
            st.rerun()
    with next_col:
        if st.button("Next", key=f"{page_key}_next", disabled=current_page >= total_pages - 1):
            st.session_state[page_key] = min(total_pages - 1, current_page + 1)
            st.rerun()
    return frame.iloc[start:end].copy()


def render_reminder_action_button_styles(wa_key: str, sent_key: str, decline_key: str, hidden_action: str):
    sent_is_selected = hidden_action == REMINDER_ACTION_SENT
    decline_is_selected = hidden_action == REMINDER_ACTION_DECLINED
    sent_opacity = "0.12" if decline_is_selected else "1"
    decline_opacity = "0.12" if sent_is_selected else "1"
    sent_bg = "#dcfce7" if sent_is_selected else "#ffffff"
    decline_bg = "#fee2e2" if decline_is_selected else "#ffffff"
    sent_border = "#15803d" if sent_is_selected else "#d1d5db"
    decline_border = "#b91c1c" if decline_is_selected else "#d1d5db"
    sent_shadow = "0 0 0 3px rgba(21, 128, 61, 0.22)" if sent_is_selected else "none"
    decline_shadow = "0 0 0 3px rgba(185, 28, 28, 0.22)" if decline_is_selected else "none"
    st.markdown(
        f"""
        <style>
          .st-key-{wa_key} button {{
            min-height: 2.45rem !important;
            position: relative !important;
          }}
          .st-key-{wa_key} button p {{
            font-size: 0 !important;
            line-height: 1 !important;
          }}
          .st-key-{wa_key} button::before {{
            background: #128c7e;
            content: "";
            display: block;
            height: 1.55rem;
            left: 50%;
            margin: 0 !important;
            position: absolute;
            top: 50%;
            transform: translate(-50%, -50%);
            -webkit-mask: url("{WHATSAPP_ICON_MASK_DATA_URI}") center / contain no-repeat;
            mask: url("{WHATSAPP_ICON_MASK_DATA_URI}") center / contain no-repeat;
            width: 1.55rem;
          }}
          .st-key-{sent_key} div[data-testid="stButton"] button,
          .st-key-{sent_key} button {{
            background: {sent_bg} !important;
            border-color: {sent_border} !important;
            box-shadow: {sent_shadow} !important;
            color: #15803d !important;
            line-height: 1 !important;
            min-height: 2.45rem !important;
            opacity: {sent_opacity};
          }}
          .st-key-{sent_key} button p {{
            color: #15803d !important;
            font-size: 1.7rem !important;
            font-weight: 900 !important;
            line-height: 1 !important;
            opacity: {sent_opacity};
            text-shadow: 0.035em 0 currentColor, -0.035em 0 currentColor;
          }}
          .st-key-{decline_key} div[data-testid="stButton"] button,
          .st-key-{decline_key} button {{
            background: {decline_bg} !important;
            border-color: {decline_border} !important;
            box-shadow: {decline_shadow} !important;
            color: #b91c1c !important;
            line-height: 1 !important;
            min-height: 2.45rem !important;
            opacity: {decline_opacity};
          }}
          .st-key-{decline_key} button p {{
            color: #b91c1c !important;
            font-size: 1.7rem !important;
            font-weight: 900 !important;
            line-height: 1 !important;
            opacity: {decline_opacity};
            text-shadow: 0.035em 0 currentColor, -0.035em 0 currentColor;
          }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def get_actioned_reminder_datetime(row) -> datetime | None:
    if not isinstance(row, dict):
        return None
    return _parse_reminder_log_time(row.get("ActionedAt", "") or row.get("DeletedAt", ""))


def format_actioned_reminder_date(row) -> str:
    actioned_at = get_actioned_reminder_datetime(row)
    if not actioned_at:
        return ""
    return actioned_at.strftime("%d %b %Y")


def actioned_reminder_period_start(period: str, now: datetime | None = None) -> datetime | None:
    now = user_now(now)
    today_start = datetime.combine(now.date(), datetime.min.time())
    if period == "Daily":
        return today_start
    if period == "Weekly":
        return today_start - timedelta(days=6)
    if period == "Monthly":
        return today_start - timedelta(days=29)
    return None


def get_actioned_reminders_for_period(period: str) -> list[dict]:
    period_start = actioned_reminder_period_start(period)
    rows = []
    for entry in st.session_state.get("deleted_reminders", []):
        if not isinstance(entry, dict):
            continue
        action = str(entry.get("Action", "")).strip().lower()
        if action not in {REMINDER_ACTION_SENT, REMINDER_ACTION_DECLINED}:
            continue
        actioned_at = get_actioned_reminder_datetime(entry)
        if period_start and (not actioned_at or actioned_at < period_start):
            continue
        rows.append(dict(entry))
    return sorted(
        rows,
        key=lambda row: get_actioned_reminder_datetime(row) or datetime.min,
        reverse=True,
    )


ACTIONED_REMINDER_SORTABLE_COLUMNS = (
    "Actioned Date",
    "Actioned By",
    "Reminder Date",
    "Due Date",
    "Charge Date",
    "Client Name",
    "Animal Name",
    "Plan Item",
    "Action",
)


def set_actioned_reminder_sort(key_prefix: str, column: str):
    state_key = f"{key_prefix}_actioned_reminder_sort"
    current = st.session_state.get(state_key)
    ascending = column != "Actioned Date"
    if isinstance(current, dict) and current.get("column") == column:
        ascending = not bool(current.get("ascending", True))
    st.session_state[state_key] = {"column": column, "ascending": ascending}


def get_actioned_reminder_sort(key_prefix: str) -> dict:
    current = st.session_state.get(f"{key_prefix}_actioned_reminder_sort")
    if isinstance(current, dict) and current.get("column") in ACTIONED_REMINDER_SORTABLE_COLUMNS:
        return {"column": current["column"], "ascending": bool(current.get("ascending", True))}
    return {"column": "Actioned Date", "ascending": False}


def actioned_reminder_sort_value(row: dict, column: str, ascending: bool):
    missing_date = datetime.max if ascending else datetime.min
    if column == "Actioned Date":
        return get_actioned_reminder_datetime(row) or missing_date
    if column in {"Reminder Date", "Due Date", "Charge Date"}:
        parsed_date = parse_reminder_sort_date(row.get(column, ""))
        if pd.isna(parsed_date):
            return missing_date
        return parsed_date.to_pydatetime()
    if column == "Action":
        action = str(row.get("Action", "")).strip().lower()
        return "declined" if action == REMINDER_ACTION_DECLINED else "sent"
    return normalize_display_case(str(row.get(column, "") or "")).casefold()


def sort_actioned_reminders(rows: list[dict], key_prefix: str) -> list[dict]:
    sort_state = get_actioned_reminder_sort(key_prefix)
    return sorted(
        rows,
        key=lambda row: actioned_reminder_sort_value(row, sort_state["column"], sort_state["ascending"]),
        reverse=not sort_state["ascending"],
    )


def render_actioned_reminders_tab(key_prefix: str):
    options = ["Daily", "Weekly", "Monthly", "All"]
    filter_key = f"{key_prefix}_actioned_period"
    current = st.session_state.get(filter_key, "Daily")
    if current not in options:
        current = "Daily"

    if hasattr(st, "segmented_control"):
        selected_period = st.segmented_control(
            "Actioned reminder period",
            options,
            selection_mode="single",
            default=current,
            key=filter_key,
            label_visibility="collapsed",
        )
    else:
        selected_period = st.radio(
            "Actioned reminder period",
            options,
            index=options.index(current),
            horizontal=True,
            key=filter_key,
            label_visibility="collapsed",
        )
    selected_period = selected_period or "Daily"

    rows = get_actioned_reminders_for_period(selected_period)
    if not rows:
        st.info(f"No actioned reminders for {selected_period.lower()}.")
        return
    rows = sort_actioned_reminders(rows, key_prefix)

    headers = [
        "Actioned Date",
        "Actioned By",
        "Reminder Date",
        "Due Date",
        "Charge Date",
        "Client Name",
        "Animal Name",
        "Plan Item",
        "Action",
        "Undo",
    ]
    labels = {**REMINDER_TABLE_HEADER_LABELS, "Actioned Date": "Actioned Date", "Actioned By": "Actioned By"}
    col_widths = [2, 3, 2.3, 2, 2, 4, 3, 4, 1.5, 1.8]
    safe_key_prefix = re.sub(r"[^a-zA-Z0-9_-]", "_", key_prefix)
    st.markdown(
        f"""
        <style>
          [class*="st-key-{safe_key_prefix}_actioned_sort_"] button {{
            background: transparent !important;
            border: 0 !important;
            box-shadow: none !important;
            color: inherit !important;
            font-weight: 600 !important;
            justify-content: flex-start !important;
            min-height: 1.6rem !important;
            padding: 0 !important;
            text-align: left !important;
          }}
          [class*="st-key-{safe_key_prefix}_actioned_sort_"] button:hover {{
            color: var(--cr-link) !important;
          }}
          [class*="st-key-{safe_key_prefix}_actioned_sort_"] button p {{
            font-weight: 600 !important;
            margin: 0 !important;
            text-align: left !important;
            white-space: nowrap !important;
          }}
        </style>
        """,
        unsafe_allow_html=True,
    )

    sort_state = get_actioned_reminder_sort(key_prefix)
    header_cols = st.columns(col_widths)
    for idx, (col, head, width) in enumerate(zip(header_cols, headers, col_widths)):
        align = "center" if head == "Undo" else "left"
        label = labels.get(head, head)
        if head in ACTIONED_REMINDER_SORTABLE_COLUMNS:
            if sort_state["column"] == head:
                label = f"{label} {'↑' if sort_state['ascending'] else '↓'}"
            render_sortable_reminder_header(
                col,
                label,
                reminder_header_help(head),
                {
                    "key": f"{key_prefix}_actioned_sort_{idx}",
                    "on_click": set_actioned_reminder_sort,
                    "args": (key_prefix, head),
                },
                width,
            )
        else:
            render_reminder_header_label(col, label, head, align=align)

    for idx, row_data in enumerate(rows):
        row_cols = st.columns(col_widths, gap="small")
        for col_idx, head in enumerate(headers[:-1]):
            if head == "Actioned Date":
                value = format_actioned_reminder_date(row_data)
            elif head == "Action":
                action = str(row_data.get("Action", "")).strip().lower()
                value = "Declined" if action == REMINDER_ACTION_DECLINED else "Sent"
            elif head == "Actioned By":
                value = str(row_data.get("Actioned By", "") or "").strip()
            else:
                value = str(row_data.get(head, "") or "")
                if head in ["Client Name", "Animal Name", "Plan Item"]:
                    value = normalize_display_case(value)
            row_cols[col_idx].markdown(value)

        row_cols[-1].button(
            "Undo",
            key=f"{key_prefix}_actioned_remove_{idx}",
            use_container_width=True,
            help="Return this reminder to Active Reminders",
            on_click=remove_actioned_reminder_action,
            args=(row_data, key_prefix),
        )


def render_table_with_buttons(df, key_prefix, msg_key):
    df = sort_reminder_table(df, key_prefix)
    df = paginate_dataframe(df, f"{key_prefix}_reminders", REMINDER_TABLE_PAGE_SIZE, "listed reminders")
    listed_rows = [row.to_dict() for _, row in df.iterrows()]
    col_widths = [2.3, 2, 2, 5, 3, 4, 1, 1, 2, 2, 2]
    headers = ["Reminder Date", "Due Date", "Charge Date", "Client Name", "Animal Name", "Plan Item", "Qty", "Days", "WhatsApp", "Sent", "Decline"]
    safe_key_prefix = re.sub(r"[^a-zA-Z0-9_-]", "_", key_prefix)
    st.markdown(
        f"""
        <style>
          [class*="st-key-{safe_key_prefix}_sort_"] button {{
            background: transparent !important;
            border: 0 !important;
            box-shadow: none !important;
            color: inherit !important;
            font-weight: 600 !important;
            justify-content: flex-start !important;
            min-height: 1.6rem !important;
            padding: 0 !important;
            text-align: left !important;
          }}
          [class*="st-key-{safe_key_prefix}_sort_"] button:hover {{
            color: var(--cr-link) !important;
          }}
          [class*="st-key-{safe_key_prefix}_sort_"] button p {{
            font-weight: 600 !important;
            margin: 0 !important;
            text-align: left !important;
            white-space: nowrap !important;
          }}
        </style>
        """,
        unsafe_allow_html=True,
    )
    bulk_sent_success = st.session_state.pop("_bulk_sent_success", "")
    if bulk_sent_success:
        st.success(bulk_sent_success)

    # --- Header row ---
    sort_state = get_reminder_table_sort(key_prefix)
    header_cols = st.columns(col_widths)
    for idx, (c, head, width) in enumerate(zip(header_cols, headers, col_widths)):
        align = "center" if head in ["WhatsApp", "Sent", "Decline"] else "left"
        label = REMINDER_TABLE_HEADER_LABELS.get(head, head)
        if head in REMINDER_TABLE_SORTABLE_COLUMNS:
            if sort_state["column"] == head:
                label = f"{label} {'↑' if sort_state['ascending'] else '↓'}"
            render_sortable_reminder_header(
                c,
                label,
                reminder_header_help(head),
                {
                    "key": f"{key_prefix}_sort_{idx}",
                    "on_click": set_reminder_table_sort,
                    "args": (key_prefix, head),
                },
                width,
            )
        else:
            render_reminder_header_label(c, label, head, align=align)

    # --- Table rows ---
    for idx, row in df.iterrows():
        # Values for the non-action columns
        row_data = row.to_dict()
        vals = {h: str(row.get(h, "")) for h in headers[:-3]}
        hidden_record = get_hidden_reminder_record(row_data)
        hidden_action = str((hidden_record or {}).get("Action", "")).strip().lower()
        wa_key = f"{key_prefix}_wa_{idx}"
        sent_key = f"{key_prefix}_sent_{idx}"
        decline_key = f"{key_prefix}_decline_{idx}"
        render_reminder_action_button_styles(wa_key, sent_key, decline_key, hidden_action)

        row_cols = st.columns(col_widths, gap="small")

        # Print ONLY data columns (not the action columns)
        for j, h in enumerate(headers[:-3]):  # up to "Days"
            val = vals[h]
            if h in ["Client Name", "Animal Name", "Plan Item"]:
                val = normalize_display_case(val)
            row_cols[j].markdown(val)

        # --- WA button (aligned to its column, full-width) ---
        row_cols[8].button(
            "WhatsApp",
            key=wa_key,
            use_container_width=True,
            help="Prepare WhatsApp message",
            on_click=prepare_whatsapp_action,
            args=(row_data, key_prefix, msg_key, idx),
        )

        row_cols[9].button(
            "✔",
            key=sent_key,
            use_container_width=True,
            help="Mark as sent",
            on_click=mark_reminder_sent_action,
            args=(row_data, key_prefix, msg_key, idx),
        )

        row_cols[10].button(
            "✖",
            key=decline_key,
            use_container_width=True,
            help="Decline reminder",
            on_click=decline_reminder_action,
            args=(row_data, key_prefix),
        )

    footer_cols = st.columns(col_widths, gap="small")
    footer_cols[9].button(
        "Send All",
        key=f"{key_prefix}_send_all",
        use_container_width=True,
        help="Mark every currently listed active reminder as sent.",
        on_click=mark_all_listed_reminders_sent_action,
        args=(listed_rows, key_prefix, msg_key),
    )

def render_whatsapp_tools(key_prefix: str, msg_key: str):
    # --- WhatsApp Composer section (after the table) ---
    st.markdown("<div id='whatsapp-composer' class='anchor-offset'></div>", unsafe_allow_html=True)
    if st.session_state.pop("_scroll_to_whatsapp_composer", False):
        components.html(
            """
            <script>
                  function scrollComposer(attempt) {
                    const target = window.parent.document.getElementById('whatsapp-composer');
                    if (target) {
                      target.scrollIntoView({behavior: 'smooth', block: 'start'});
                      return;
                    }
                    if (attempt < 12) window.setTimeout(() => scrollComposer(attempt + 1), 120);
                  }
                  window.setTimeout(() => scrollComposer(0), 80);
            </script>
            """,
            height=0,
        )
    comp_main, comp_tip = st.columns([4, 1])
    with comp_main:
        st.write("### WhatsApp Composer")
        st.caption("Review and edit the prepared message before opening WhatsApp.")


        if msg_key not in st.session_state:
            st.session_state[msg_key] = ""

        render_field_label(
            st,
            "Message",
            "Prepared when you click WhatsApp in the reminders table. You can edit it before opening WhatsApp."
        )
        st.text_area(
            "Message:",
            key=msg_key,
            height=200,
            label_visibility="collapsed",
        )
        current_message = st.session_state.get(msg_key, "")

        components.html(
            f'''
            <html>
              <head>
                <meta charset="utf-8">
                <style>
                  .composer-wrap {{
                    display: flex; flex-direction: column; gap: 10px;
                    font-family: "Source Sans Pro", sans-serif;
                  }}
                  .button-row {{ display: flex; gap: 12px; align-items: center; margin-top: 2px; }}
                  .button-row button {{
                    height: 52px; padding: 0 20px; border: none; border-radius: 6px;
                    cursor: pointer; font-size: 18px; font-weight: 600; font-family: "Source Sans Pro", sans-serif; flex: 1;
                  }}
                  .wa-btn {{ background-color: #25D366; color: white; }}
                  .copy-btn {{ background-color: #555; color: white; }}
                  .copy-btn:active {{ transform: translateY(2px); filter: brightness(85%); }}
                </style>
              </head>
              <body>
                <div class="composer-wrap">
                  <div class="button-row">
                    <button class="wa-btn" id="waBtn">📲 Copy & Open WhatsApp</button>
                    <button class="copy-btn" id="copyBtn">📋 Copy to Clipboard</button>
                  </div>
                </div>
                <script>
                  const MESSAGE_RAW = {json.dumps(current_message)};
                  async function copyToClipboard(text) {{
                    try {{ await navigator.clipboard.writeText(text); }}
                    catch (err) {{
                      const ta = document.createElement('textarea');
                      ta.value = text; document.body.appendChild(ta);
                      ta.select(); try {{ document.execCommand('copy'); }} finally {{ document.body.removeChild(ta); }}
                    }}
                  }}
                  document.getElementById('waBtn').addEventListener('click', async function(e) {{
                    e.preventDefault();
                    await copyToClipboard(MESSAGE_RAW || '');
                    window.open("https://wa.me/", '_blank', 'noopener');
                  }});
                  document.getElementById('copyBtn').addEventListener('click', async function() {{
                    await copyToClipboard(MESSAGE_RAW || '');
                    const old = this.innerText;
                    this.innerText = '✅ Copied!';
                    setTimeout(() => this.innerText = old, 1500);
                  }});
                </script>
              </body>
            </html>
            ''',
            height=68,
        )


    # --- WhatsApp Template Editor ---
    st.markdown("<div id='wa-template-editor' class='anchor-offset'></div>", unsafe_allow_html=True)
    if st.session_state.pop("_scroll_to_wa_template_editor", False):
        components.html(
            """
            <script>
                  function scrollTemplateEditor(attempt) {
                    const target = window.parent.document.getElementById('wa-template-editor');
                    if (target) {
                      target.scrollIntoView({behavior: 'smooth', block: 'start'});
                      return;
                    }
                    if (attempt < 12) window.setTimeout(() => scrollTemplateEditor(attempt + 1), 120);
                  }
                  window.setTimeout(() => scrollTemplateEditor(0), 80);
            </script>
            """,
            height=0,
        )
    tmpl_main, _ = st.columns([4, 1])
    with tmpl_main:
        st.markdown("### 🧩 WhatsApp Template Editor")
        st.caption("Setup tool: keep the default message, or edit it when your clinic needs different wording.")
        if "wa_template" not in st.session_state or not st.session_state.get("wa_template"):
            st.session_state["wa_template"] = st.session_state.get("user_template", DEFAULT_WA_TEMPLATE) or DEFAULT_WA_TEMPLATE

        ver_key = f"{key_prefix}_tmpl_ver"
        if ver_key not in st.session_state:
            st.session_state[ver_key] = 0

        editor_key = f"wa_template_editor_{key_prefix}_{st.session_state[ver_key]}"
        render_field_label(
            st,
            "WhatsApp message template",
            "Use placeholders such as [Client Name], [Your Name], [Pet Name], [Item], and [Due Date]."
        )
        st.text_area(
            "Customize your WhatsApp message template:",
            value=st.session_state["wa_template"],
            height=200,
            key=editor_key,
            label_visibility="collapsed",
        )

        col_update, col_reset, _button_spacer = st.columns([1.1, 1.1, 2], gap="small")
        with col_update:
            if st.button("✅ Update Template", key=f"update_template_{key_prefix}", use_container_width=True):
                new_template = st.session_state.get(editor_key, "").strip()
                if new_template:
                    old_template = st.session_state.get("user_template", DEFAULT_WA_TEMPLATE)
                    st.session_state["wa_template"] = new_template
                    st.session_state["user_template"] = new_template
                    st.session_state["wa_template_reviewed"] = True
                    st.session_state["wa_template_updated"] = True
                    st.session_state["wa_template_updated_at"] = user_now().isoformat()
                    save_settings_quietly()
                    record_settings_audit_event("template_updated", "template", "whatsapp", "user_template", old_template, new_template, "reminders_tab")
                    st.success("Template updated successfully!")
                    st.rerun()
        with col_reset:
            if st.button("🗑️ Reset Template", key=f"reset_template_{key_prefix}", use_container_width=True):
                old_template = st.session_state.get("user_template", DEFAULT_WA_TEMPLATE)
                st.session_state["wa_template"] = DEFAULT_WA_TEMPLATE
                st.session_state["user_template"] = DEFAULT_WA_TEMPLATE
                st.session_state["wa_template_reviewed"] = False
                st.session_state["wa_template_updated"] = False
                st.session_state["wa_template_updated_at"] = ""
                save_settings_quietly()
                record_settings_audit_event("template_reset", "template", "whatsapp", "user_template", old_template, DEFAULT_WA_TEMPLATE, "reminders_tab")
                st.session_state[ver_key] += 1
                st.success("Template reset to default!")
                st.rerun()

        st.markdown(
            """
            <div class="template-helper">
              <h4>Template basics</h4>
              <p>Write the message once. When you click WhatsApp, the app fills in the bracketed placeholders automatically.</p>
              <div class="placeholder-grid">
                <div class="placeholder-chip"><code>[Client Name]</code>Client first name</div>
                <div class="placeholder-chip"><code>[Your Name]</code>Your saved sender name</div>
                <div class="placeholder-chip"><code>[Pet Name]</code>Patient name or names</div>
                <div class="placeholder-chip"><code>[Item]</code>Reminder item</div>
                <div class="placeholder-chip"><code>[Due Date]</code>Formatted due date</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

def normalize_display_case(text: str) -> str:
    if not isinstance(text, str):
        return text
    words = text.split()
    fixed = []
    for w in words:
        if w.isupper() and len(w) > 1:
            fixed.append(w.capitalize())
        else:
            fixed.append(w)
    return " ".join(fixed)

STATISTICS_PERIODS = ["Today", "7 days", "30 days", "All time"]
STATISTICS_GENERATED_COLUMNS = ["Reminder Date", "Due Date", "Charge Date", "Client Name", "Animal Name", "Plan Item", "Qty", "Days"]
STATISTICS_SCHEDULED_REMINDERS_LABEL = "Scheduled reminders"
OUTCOME_PERIODS = ["Today", "7 days", "30 days", "All time"]
DEFAULT_OUTCOME_DUE_DATE_WINDOW_DAYS = 14
REMINDER_TABLE_PAGE_SIZE = 50
OUTCOME_SENT_PAGE_SIZE = 100
OUTCOME_TABLE_COLUMNS = [
    "Charge Date",
    "Reminder Date",
    "Sent Date",
    "Actioned Date",
    "Due Date",
    "Window Starts",
    "Window Ends",
    "Next Purchase Date",
    "Success Date",
    "Client Name",
    "Animal Name",
    "Item",
    "Sender",
    "Outcome",
    "Desired Gap Days",
    "Success Gap Days",
    "Next Purchase Gap Days",
    "Avg Item Purchase Gap Days",
    "Overall Repeat Purchases",
    "Overall Purchases",
    "Repeat Purchase %",
    "Revenue",
    "Matched Item",
    "Next Matched Item",
]
OUTCOME_DISPLAY_DATE_COLUMNS = [
    "Charge Date",
    "Reminder Date",
    "Sent Date",
    "Actioned Date",
    "Due Date",
    "Window Starts",
    "Window Ends",
    "Next Purchase Date",
    "Success Date",
]
OUTCOME_DISPLAY_COLUMN_LABELS = {
    "Charge Date": "Billed Date",
    "Avg Item Purchase Gap Days": "Overall Avg Purchase Gap Days",
}
OUTCOME_DISPLAY_COLUMN_HELP = {
    "Billed Date": "The original sale date from the uploaded data.",
    "Reminder Date": "The date the reminder was scheduled to appear in the Reminders workflow.",
    "Sent Date": "The date the reminder was marked as sent.",
    "Actioned Date": "The date the reminder was last marked sent or declined.",
    "Due Date": "The date the client was expected to buy this item again.",
    "Window Starts": "The first purchase date that can count as a success for this reminder.",
    "Window Ends": "The last purchase date that can count as a success for this reminder.",
    "Next Purchase Date": "The next matching purchase found after the billed date.",
    "Success Date": "The matching purchase date that made this reminder successful.",
    "Client Name": "The client linked to the reminder.",
    "Animal Name": "The patient linked to the reminder.",
    "Item": "The reminded item or service.",
    "Sender": "The team member who marked the reminder as sent.",
    "Outcome": "Whether the reminder is successful, pending, or has no matching purchase.",
    "Desired Gap Days": "The expected number of days between purchases for this item.",
    "Success Gap Days": "The days between the original billed date and the successful repeat purchase.",
    "Next Purchase Gap Days": "The days between the original billed date and the next matching purchase.",
    "Avg Success Gap Days": "The average successful repeat-purchase gap for the rows in this table.",
    "Overall Avg Purchase Gap Days": "The average repeat-purchase gap across all uploaded purchases for this item.",
    "Overall Repeat Purchases": "The number of repeat purchases used to calculate the overall average gap.",
    "Overall Purchases": "The total number of matching purchases found in the uploaded data.",
    "Repeat Purchase %": "The share of matching purchases that are repeat purchases.",
    "Success Rate": "Successful reminders divided by sent reminders.",
    "Revenue": "Revenue from successful repeat purchases.",
    "Matched Item": "The purchased item that counted as the successful match.",
    "Next Matched Item": "The next matching purchased item found after the billed date.",
}
OUTCOME_SENT_DISPLAY_COLUMNS = [
    "Charge Date",
    "Reminder Date",
    "Sent Date",
    "Due Date",
    "Window Starts",
    "Window Ends",
    "Next Purchase Date",
    "Client Name",
    "Animal Name",
    "Item",
    "Sender",
    "Outcome",
]
OUTCOME_ITEM_GROUP_COLUMNS = [
    "Item",
    "Sent",
    "Successes",
    "Pending",
    "No Match",
    "Success Rate",
    "Desired Gap Days",
    "Avg Item Purchase Gap Days",
    "Overall Repeat Purchases",
    "Overall Purchases",
    "Repeat Purchase %",
    "Revenue",
]
OUTCOME_SENDER_GROUP_COLUMNS = [
    "Sender",
    "Sent",
    "Successes",
    "Pending",
    "No Match",
    "Success Rate",
    "Revenue",
]
STATS_TEAM_COLUMNS = [
    "Team Member",
    "Sent Reminders",
    "Successes",
    "Pending",
    "No Match",
    "Success Rate",
    "Revenue",
    "Actioned",
    "Sent Actions",
    "Declined Actions",
    "Last Actioned",
]
STATS_ITEM_ACTIONING_COLUMN_HELP = {
    "Item": "The generated reminder item.",
    STATISTICS_SCHEDULED_REMINDERS_LABEL: "How many reminders were scheduled for this item.",
    "Actioned": "How many scheduled reminders were marked sent or declined.",
    "Sent": "How many scheduled reminders were marked sent.",
    "Declined": "How many scheduled reminders were declined.",
}
STATS_TEAM_COLUMN_HELP = {
    "Team Member": "The team member who actioned or sent reminders.",
    "Sent Reminders": "Sent reminders included in outcome matching for this team member.",
    "Successes": "Sent reminders from this team member that led to matching repeat purchases.",
    "Pending": "Sent reminders still inside the success window.",
    "No Match": "Sent reminders with no matching repeat purchase found after the success window.",
    "Success Rate": "Successful reminders divided by sent reminders for this team member.",
    "Revenue": "Revenue from successful repeat purchases linked to this team member.",
    "Actioned": "All reminders this team member marked sent or declined.",
    "Sent Actions": "Reminders this team member marked sent.",
    "Declined Actions": "Reminders this team member declined.",
    "Last Actioned": "The latest date this team member marked a reminder sent or declined.",
}
OUTCOME_SUCCESS_METER_COLUMNS = {"Sent", "Successes", "Pending", "No Match", "Success Rate"}


def statistics_exclusion_fp() -> str:
    def normalized_text_list(values) -> list[str]:
        return sorted(
            _SPACE_RX.sub(" ", str(value or "").strip()).lower()
            for value in values or []
            if str(value or "").strip()
        )

    patient_exclusions = []
    for item in st.session_state.get("patient_exclusions", []) or []:
        if not isinstance(item, dict):
            continue
        client = _SPACE_RX.sub(" ", str(item.get("client", "") or "").strip()).lower()
        patient = _SPACE_RX.sub(" ", str(item.get("patient", "") or "").strip()).lower()
        if client and patient:
            patient_exclusions.append({"client": client, "patient": patient})

    payload = {
        "items": normalized_text_list(st.session_state.get("exclusions", [])),
        "clients": normalized_text_list(st.session_state.get("client_exclusions", [])),
        "patients": sorted(patient_exclusions, key=lambda row: (row["client"], row["patient"])),
        "automatic_patients": normalized_text_list(
            f"{item.get('client', '')}|{item.get('patient', '')}"
            for item in normalize_patient_exclusions(st.session_state.get("automatic_patient_exclusions", []))
        ),
        "patient_passaway_keywords": normalized_text_list(st.session_state.get("patient_passaway_keywords", [])),
    }
    return hashlib.md5(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def empty_statistics_generated_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=STATISTICS_GENERATED_COLUMNS)


def statistics_period_start(period: str, today: date | None = None) -> date | None:
    today = today or user_today()
    if period == "Today":
        return today
    if period == "7 days":
        return today - timedelta(days=6)
    if period == "30 days":
        return today - timedelta(days=29)
    return None


@lru_cache(maxsize=8192)
def parse_statistics_date_part(value: str) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    match = re.search(
        r"(\d{1,2}[\s/-][A-Za-z]{3}[\s/-]\d{4}|\d{1,2}[\s/-]\d{1,2}[\s/-]\d{4}|\d{4}[\s/-]\d{1,2}[\s/-]\d{1,2})",
        raw,
    )
    if not match:
        return None
    text = match.group(1)
    formats = [
        "%d/%b/%Y", "%d-%b-%Y", "%d %b %Y",
        "%d/%m/%Y", "%m/%d/%Y", "%d %m %Y", "%m %d %Y",
        "%Y-%m-%d", "%Y/%m/%d", "%Y %m %d", "%Y.%m.%d",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    parsed = pd.to_datetime(pd.Series([text]), errors="coerce", dayfirst=True).iloc[0]
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed).date()


def parse_statistics_dates(value) -> list[date]:
    if value is None:
        return []
    if isinstance(value, datetime):
        return [value.date()]
    if isinstance(value, date):
        return [value]
    parsed_dates = []
    for part in str(value or "").split("|"):
        part = part.strip()
        if not part:
            continue
        parsed = parse_statistics_date_part(part)
        if parsed:
            parsed_dates.append(parsed)
    return parsed_dates


def statistics_row_dates(row: dict) -> list[date]:
    return parse_statistics_dates(row.get("Reminder Date", "") or row.get("ReminderDate", ""))


def statistics_primary_reminder_date(row: dict) -> date | None:
    dates = statistics_row_dates(row)
    return min(dates) if dates else None


def statistics_actioned_date(row: dict) -> date | None:
    actioned_at = _parse_reminder_log_time(row.get("ActionedAt", "") or row.get("DeletedAt", ""))
    return actioned_at.date() if actioned_at else None


def statistics_date_in_period(value_date: date | None, period: str, today: date | None = None) -> bool:
    if value_date is None:
        return False
    today = today or user_today()
    start = statistics_period_start(period, today)
    if start is None:
        return True
    return start <= value_date <= today


def statistics_row_in_reminder_period(row: dict, period: str, today: date | None = None) -> bool:
    dates = statistics_row_dates(row)
    return any(statistics_date_in_period(value_date, period, today) for value_date in dates)


def statistics_row_key(row: dict) -> tuple[str, ...]:
    return hidden_reminder_key(row)


def filter_prepared_for_statistics_period(
    prepared: pd.DataFrame,
    period: str,
    today: date | None = None,
) -> pd.DataFrame:
    if prepared is None or getattr(prepared, "empty", True):
        return prepared
    start = statistics_period_start(period, today)
    if start is None:
        return prepared
    today = today or user_today()
    reminder_ts = prepared.get("ReminderDateTs")
    if reminder_ts is None:
        reminder_ts = prepared.get("NextDueDateTs")
    if reminder_ts is None:
        reminder_ts = pd.to_datetime(prepared.get("NextDueDate"), errors="coerce")
    else:
        reminder_ts = pd.to_datetime(reminder_ts, errors="coerce")
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(today)
    return prepared.loc[(reminder_ts >= start_ts) & (reminder_ts <= end_ts)].copy()


def build_statistics_generated_rows(
    prepared: pd.DataFrame,
    rules: dict,
    group_days: int | None = None,
    period: str = "All time",
    today: date | None = None,
) -> pd.DataFrame:
    if prepared is None or getattr(prepared, "empty", True):
        return empty_statistics_generated_frame()
    group_days = st.session_state.get("client_group_days", 1) if group_days is None else group_days
    try:
        group_days = max(0, int(group_days))
    except (TypeError, ValueError):
        group_days = 1
    prepared_period = filter_prepared_for_statistics_period(prepared, period, today)
    if prepared_period is None or getattr(prepared_period, "empty", True):
        return empty_statistics_generated_frame()
    filtered = apply_reminder_exclusion_filters(prepared_period, rules)
    if filtered.empty:
        return empty_statistics_generated_frame()
    return bundle_client_reminders_by_window(filtered, window_days=group_days, rules=rules)


@st.cache_data(show_spinner=False)
def cached_statistics_generated_rows(
    _prepared: pd.DataFrame,
    _rules: dict,
    group_days: int,
    period: str,
    today_iso: str,
    data_version: int,
    rules_fp: str,
    exclusion_fp: str,
    schema_version: int,
) -> pd.DataFrame:
    today = pd.to_datetime(today_iso, errors="coerce")
    today_date = today.date() if pd.notna(today) else user_today()
    return build_statistics_generated_rows(
        _prepared,
        _rules,
        group_days=group_days,
        period=period,
        today=today_date,
    )


def statistics_current_action_records() -> list[dict]:
    return reduce_action_tracker_records([
        entry for entry in st.session_state.get("deleted_reminders", [])
        if isinstance(entry, dict)
    ])


def filter_generated_for_statistics_period(generated_df: pd.DataFrame, period: str, today: date | None = None) -> pd.DataFrame:
    if generated_df is None or generated_df.empty:
        return pd.DataFrame(columns=list(generated_df.columns) if generated_df is not None else [])
    mask = [
        statistics_row_in_reminder_period(row, period, today)
        for row in generated_df.to_dict("records")
    ]
    return generated_df.loc[mask].copy()


def filter_actions_by_reminder_period(action_records: list[dict], period: str, today: date | None = None) -> list[dict]:
    return [
        dict(record) for record in action_records
        if statistics_row_in_reminder_period(record, period, today)
    ]


def filter_actions_by_actioned_period(action_records: list[dict], period: str, today: date | None = None) -> list[dict]:
    return [
        dict(record) for record in action_records
        if statistics_date_in_period(statistics_actioned_date(record), period, today)
    ]


def statistics_summary_for_period(
    generated_df: pd.DataFrame,
    action_records: list[dict],
    period: str,
    today: date | None = None,
) -> dict:
    generated_period = filter_generated_for_statistics_period(generated_df, period, today)
    generated_keys = {
        statistics_row_key(row)
        for row in generated_period.to_dict("records")
        if any(statistics_row_key(row))
    }
    actioned_by_key = {}
    for record in filter_actions_by_reminder_period(action_records, period, today):
        key = statistics_row_key(record)
        if not any(key) or key not in generated_keys:
            continue
        actioned_by_key[key] = record

    sent = sum(1 for record in actioned_by_key.values() if str(record.get("Action", "")).strip().lower() == REMINDER_ACTION_SENT)
    declined = sum(1 for record in actioned_by_key.values() if str(record.get("Action", "")).strip().lower() == REMINDER_ACTION_DECLINED)
    generated_count = len(generated_period.index)
    actioned_count = sent + declined
    remaining = max(generated_count - actioned_count, 0)
    completion_rate = (actioned_count / generated_count) if generated_count else 0.0
    return {
        "generated": generated_count,
        "actioned": actioned_count,
        "sent": sent,
        "declined": declined,
        "remaining": remaining,
        "completion_rate": completion_rate,
    }


def build_statistics_daily_frame(
    generated_df: pd.DataFrame,
    action_records: list[dict],
    period: str,
    today: date | None = None,
) -> pd.DataFrame:
    today = today or user_today()
    generated_counts = {}
    for row in filter_generated_for_statistics_period(generated_df, period, today).to_dict("records"):
        row_date = statistics_primary_reminder_date(row)
        if row_date is not None:
            generated_counts[row_date] = generated_counts.get(row_date, 0) + 1

    action_counts = {}
    for record in filter_actions_by_reminder_period(action_records, period, today):
        row_date = statistics_primary_reminder_date(record)
        if row_date is None:
            continue
        action = str(record.get("Action", "")).strip().lower()
        counts = action_counts.setdefault(row_date, {"Sent": 0, "Declined": 0})
        if action == REMINDER_ACTION_SENT:
            counts["Sent"] += 1
        elif action == REMINDER_ACTION_DECLINED:
            counts["Declined"] += 1

    all_dates = sorted(set(generated_counts) | set(action_counts))
    start = statistics_period_start(period, today)
    if start is not None:
        all_dates = [day for day in all_dates if start <= day <= today]
    rows = []
    for row_date in all_dates:
        sent = action_counts.get(row_date, {}).get("Sent", 0)
        declined = action_counts.get(row_date, {}).get("Declined", 0)
        generated = generated_counts.get(row_date, 0)
        rows.append({
            "Date": pd.Timestamp(row_date),
            "Generated": generated,
            "Actioned": sent + declined,
            "Sent": sent,
            "Declined": declined,
            "Remaining": max(generated - sent - declined, 0),
        })
    return pd.DataFrame(rows)


def build_statistics_team_frame(action_records: list[dict], period: str, today: date | None = None) -> pd.DataFrame:
    rows = filter_actions_by_actioned_period(action_records, period, today)
    if not rows:
        return pd.DataFrame(columns=["User", "Actioned", "Sent", "Declined", "Last Actioned"])
    df_actions = pd.DataFrame(rows)
    actioned_by = (
        df_actions["Actioned By"]
        if "Actioned By" in df_actions.columns
        else pd.Series("", index=df_actions.index)
    )
    action_values = (
        df_actions["Action"]
        if "Action" in df_actions.columns
        else pd.Series("", index=df_actions.index)
    )
    df_actions["User"] = actioned_by.fillna("").astype(str).str.strip().replace("", "Unknown")
    df_actions["ActionNorm"] = action_values.fillna("").astype(str).str.lower()
    df_actions["ActionedAtParsed"] = df_actions.apply(
        lambda row: _parse_reminder_log_time(row.get("ActionedAt", "") or row.get("DeletedAt", "")),
        axis=1,
    )
    grouped = df_actions.groupby("User", dropna=False)
    out = grouped.size().rename("Actioned").to_frame()
    out["Sent"] = grouped["ActionNorm"].apply(lambda values: int((values == REMINDER_ACTION_SENT).sum()))
    out["Declined"] = grouped["ActionNorm"].apply(lambda values: int((values == REMINDER_ACTION_DECLINED).sum()))
    out["Last Actioned"] = grouped["ActionedAtParsed"].max().apply(lambda value: value.strftime("%d %b %Y") if pd.notna(value) else "")
    return out.reset_index().sort_values(["Actioned", "Sent"], ascending=False)


def build_statistics_item_frame(
    generated_df: pd.DataFrame,
    action_records: list[dict],
    period: str,
    today: date | None = None,
) -> pd.DataFrame:
    generated_rows = filter_generated_for_statistics_period(generated_df, period, today).to_dict("records")
    generated_counts = {}
    for row in generated_rows:
        item = normalize_display_case(str(row.get("Plan Item", "") or "Unknown").strip() or "Unknown")
        generated_counts[item] = generated_counts.get(item, 0) + 1

    action_counts = {}
    for record in filter_actions_by_reminder_period(action_records, period, today):
        item = normalize_display_case(str(record.get("Plan Item", "") or "Unknown").strip() or "Unknown")
        counts = action_counts.setdefault(item, {"Sent": 0, "Declined": 0})
        action = str(record.get("Action", "")).strip().lower()
        if action == REMINDER_ACTION_SENT:
            counts["Sent"] += 1
        elif action == REMINDER_ACTION_DECLINED:
            counts["Declined"] += 1

    rows = []
    for item in sorted(set(generated_counts) | set(action_counts)):
        sent = action_counts.get(item, {}).get("Sent", 0)
        declined = action_counts.get(item, {}).get("Declined", 0)
        rows.append({
            "Item": item,
            "Generated": generated_counts.get(item, 0),
            "Actioned": sent + declined,
            "Sent": sent,
            "Declined": declined,
        })
    return pd.DataFrame(rows).sort_values(["Generated", "Actioned"], ascending=False) if rows else pd.DataFrame(columns=["Item", "Generated", "Actioned", "Sent", "Declined"])


def render_statistics_metric_card(label: str, value: str):
    st.metric(label, value)


def prepare_statistics_display_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or getattr(frame, "empty", True):
        return frame
    return frame.rename(columns={"Generated": STATISTICS_SCHEDULED_REMINDERS_LABEL})


def empty_outcome_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=OUTCOME_TABLE_COLUMNS)


def normalize_outcome_text(value) -> str:
    return _SPACE_RX.sub(" ", str(value or "").strip()).lower()


def normalize_outcome_item_text(value) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    text = re.sub(r"[\u00a0\u200b\ufeff]", " ", text)
    text = re.sub(r"[-+/().,]", " ", text)
    return _SPACE_RX.sub(" ", text).strip()


def normalize_outcome_identity(value) -> str:
    return normalize_key_series(pd.Series([value])).iloc[0]


def first_statistics_date(value) -> date | None:
    dates = parse_statistics_dates(value)
    return min(dates) if dates else None


OUTCOME_GENERIC_ITEM_TOKENS = {
    "and",
    "annual",
    "booster",
    "capsule",
    "capsules",
    "dose",
    "doses",
    "exam",
    "full",
    "injection",
    "injections",
    "injectable",
    "nasal",
    "oral",
    "pack",
    "spot",
    "spoton",
    "tablet",
    "tablets",
    "treatment",
    "treatments",
    "vaccine",
    "vaccines",
}


def outcome_specific_item_tokens(item_text) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", normalize_outcome_item_text(item_text))
    terms = []
    seen = set()
    for token in tokens:
        if token in seen or token in OUTCOME_GENERIC_ITEM_TOKENS:
            continue
        if len(token) < 4 or token.isdigit() or re.fullmatch(r"\d+(?:mg|kg|ml|g)?", token):
            continue
        seen.add(token)
        terms.append(token)
    return terms


def outcome_item_terms(item_text, rules: dict | None = None) -> list[str]:
    raw = normalize_outcome_item_text(item_text)
    if not raw:
        return []
    parts = re.split(r"\s*(?:\||,|/|;|\band\b|\+)\s*", str(item_text or "").strip(), flags=re.IGNORECASE)
    terms = []
    seen = set()
    for part in [raw, *parts]:
        term = normalize_outcome_item_text(part)
        if len(term) < 2 or term in seen:
            continue
        seen.add(term)
        terms.append(term)

    for rule_text, settings in (rules or {}).items():
        rule_term = normalize_outcome_item_text(rule_text)
        visible_term = normalize_outcome_item_text((settings or {}).get("visible_text", ""))
        if not rule_term or rule_term in seen:
            continue
        if (visible_term and (visible_term == raw or visible_term in raw or raw in visible_term)) or rule_term in raw:
            seen.add(rule_term)
            terms.append(rule_term)
    for token in outcome_specific_item_tokens(item_text):
        if token not in seen:
            seen.add(token)
            terms.append(token)
    return terms


def split_outcome_search_terms(value) -> list[str]:
    if isinstance(value, list):
        raw_parts = value
    else:
        raw_parts = re.split(r"\s*(?:\||,|;)\s*", str(value or ""), flags=re.IGNORECASE)
    terms = []
    seen = set()
    for part in raw_parts:
        term = normalize_outcome_item_text(part)
        if len(term) < 2 or term in seen:
            continue
        seen.add(term)
        terms.append(term)
    return terms


def prune_contained_outcome_terms(terms: list[str]) -> list[str]:
    normalized = []
    seen = set()
    for term in terms or []:
        clean = normalize_outcome_item_text(term)
        if clean and clean not in seen:
            seen.add(clean)
            normalized.append(clean)
    keep = []
    for term in sorted(normalized, key=len, reverse=True):
        if any(term != other and term in other for other in keep):
            continue
        keep.append(term)
    return sorted(keep, key=normalized.index)


def outcome_search_terms_for_record(record: dict, reminder_item, rules: dict | None = None) -> list[str]:
    terms = []
    seen = set()

    def add_term(value):
        for term in split_outcome_search_terms(value):
            if term not in seen:
                seen.add(term)
                terms.append(term)

    add_term(record.get("Search Terms", ""))
    add_term(record.get("MatchedSearchTerms", ""))
    for detail in normalize_reminder_details_for_storage(record.get("ReminderDetails", [])):
        add_term(detail.get("Search Terms", ""))

    if terms:
        return prune_contained_outcome_terms(terms)

    reminder_key = normalize_outcome_item_text(reminder_item)
    for rule_text, settings in (rules or {}).items():
        rule_term = normalize_outcome_item_text(rule_text)
        visible_term = normalize_outcome_item_text((settings or {}).get("visible_text", ""))
        if not rule_term or rule_term in seen:
            continue
        if (
            rule_term in reminder_key
            or (visible_term and (visible_term == reminder_key or visible_term in reminder_key or reminder_key in visible_term))
        ):
            seen.add(rule_term)
            terms.append(rule_term)

    if terms:
        return prune_contained_outcome_terms(terms)
    return outcome_item_terms(reminder_item, rules=None)


def outcome_exact_item_keys_for_record(record: dict, reminder_item, terms: list[str], rules: dict | None = None) -> list[str]:
    generic_keys = {normalize_outcome_item_text(term) for term in terms or [] if normalize_outcome_item_text(term)}
    generic_keys.update(
        normalize_outcome_item_text((settings or {}).get("visible_text", ""))
        for settings in (rules or {}).values()
        if normalize_outcome_item_text((settings or {}).get("visible_text", ""))
    )
    exact_keys = []
    seen = set()
    details = normalize_reminder_details_for_storage(record.get("ReminderDetails", []))
    candidates = [detail.get("Plan Item", "") for detail in details]
    for value in candidates:
        key = normalize_outcome_item_text(value)
        if not key or key in seen or key in generic_keys:
            continue
        specific_tokens = outcome_specific_item_tokens(key)
        term_matches = [term for term in generic_keys if term and term in key]
        has_variant_detail = len(specific_tokens) > 1 or bool(re.search(r"\d", key))
        if not term_matches or not has_variant_detail:
            continue
        seen.add(key)
        exact_keys.append(key)
    return exact_keys


def outcome_item_matches(reminder_item, sale_item, rules: dict | None = None, record: dict | None = None) -> bool:
    sale_key = normalize_outcome_item_text(sale_item)
    if not sale_key:
        return False
    if record is not None:
        return any(term and term in sale_key for term in outcome_search_terms_for_record(record, reminder_item, rules))
    return any(term and term in sale_key for term in outcome_item_terms(reminder_item, rules))


def split_grouped_display_parts(value) -> list[str]:
    raw = str(value or "").strip()
    if not raw:
        return []
    if "|" in raw:
        parts = raw.split("|")
    else:
        parts = re.split(r"\s*(?:,|\band\b)\s*", raw)
    return [_SPACE_RX.sub(" ", part.strip()) for part in parts if part and part.strip()]


def _broadcast_grouped_part(parts: list[str], index: int) -> str:
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    if index < len(parts):
        return parts[index]
    return parts[-1]


def expand_grouped_action_record(record: dict) -> list[dict]:
    details = normalize_reminder_details_for_storage(record.get("ReminderDetails", []))
    if details:
        expanded = []
        for detail in details:
            row = dict(record)
            row["Animal Name"] = detail.get("Animal Name", "") or row.get("Animal Name", "")
            row["Plan Item"] = detail.get("Plan Item", "") or row.get("Plan Item", "")
            row["Due Date"] = detail.get("Due Date", "") or row.get("Due Date", "")
            row["Reminder Date"] = detail.get("Reminder Date", "") or row.get("Reminder Date", "")
            row["Charge Date"] = detail.get("Charge Date", "") or row.get("Charge Date", "")
            row["Qty"] = detail.get("Qty", "") or row.get("Qty", "")
            row["Days"] = detail.get("Days", "") or row.get("Days", "")
            row["ReminderDetails"] = [detail]
            expanded.append(row)
        return expanded or [record]

    reminder_dates = split_grouped_display_parts(record.get("Reminder Date", ""))
    due_dates = split_grouped_display_parts(record.get("Due Date", ""))
    animals = split_grouped_display_parts(record.get("Animal Name", ""))
    items = split_grouped_display_parts(record.get("Plan Item", ""))
    instance_count = max(len(reminder_dates), len(due_dates), len(animals), len(items), 1)
    if instance_count <= 1:
        return [record]

    expanded = []
    for idx in range(instance_count):
        row = dict(record)
        row["Reminder Date"] = _broadcast_grouped_part(reminder_dates, idx) or row.get("Reminder Date", "")
        row["Due Date"] = _broadcast_grouped_part(due_dates, idx) or row.get("Due Date", "")
        row["Animal Name"] = _broadcast_grouped_part(animals, idx) or row.get("Animal Name", "")
        row["Plan Item"] = _broadcast_grouped_part(items, idx) or row.get("Plan Item", "")
        expanded.append(row)
    return expanded


def expand_grouped_action_records(records: list[dict]) -> list[dict]:
    expanded = []
    for record in records or []:
        if not isinstance(record, dict):
            continue
        expanded.extend(expand_grouped_action_record(record))
    return expanded


def outcome_purchase_cycle_key(record: dict) -> tuple[str, ...]:
    fields = ("Client Name", "Animal Name", "Plan Item", "Charge Date", "Due Date")
    return tuple(_hidden_reminder_key_part(record.get(field, "")) for field in fields)


def _outcome_sent_record_sort_time(record: dict) -> datetime:
    action_time = _parse_reminder_log_time(record.get("ActionedAt", "") or record.get("DeletedAt", ""))
    if action_time:
        return action_time
    reminder_date = first_statistics_date(record.get("Reminder Date", ""))
    if reminder_date:
        return datetime.combine(reminder_date, datetime.min.time())
    return datetime.max


def dedupe_outcome_sent_records(records: list[dict]) -> list[dict]:
    earliest_by_purchase: dict[tuple[str, ...], dict] = {}
    for record in records or []:
        if not isinstance(record, dict):
            continue
        key = outcome_purchase_cycle_key(record)
        if not any(key):
            key = hidden_reminder_key(record)
        existing = earliest_by_purchase.get(key)
        if existing is None or _outcome_sent_record_sort_time(record) < _outcome_sent_record_sort_time(existing):
            earliest_by_purchase[key] = dict(record)
    return sorted(earliest_by_purchase.values(), key=_outcome_sent_record_sort_time)


def prepare_sales_for_outcomes(sales_df: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "ChargeDate",
        "Client Name",
        "Animal Name",
        "Item Name",
        "Amount",
        "OutcomeChargeDate",
        "OutcomeClientKey",
        "OutcomePatientKey",
        "OutcomeItemKey",
        "OutcomeAmount",
        "OutcomeSaleID",
    ]
    if sales_df is None or getattr(sales_df, "empty", True):
        return pd.DataFrame(columns=columns)

    working = sales_df.copy()
    for required in ["ChargeDate", "Client Name", "Animal Name", "Item Name"]:
        if required not in working.columns:
            return pd.DataFrame(columns=columns)
    if "Amount" not in working.columns:
        working["Amount"] = 0

    working["OutcomeSaleID"] = np.arange(len(working))
    working["OutcomeChargeDate"] = parse_dates(working["ChargeDate"]).dt.normalize()
    working["OutcomeClientKey"] = normalize_key_series(working["Client Name"], index=working.index)
    working["OutcomePatientKey"] = normalize_key_series(working["Animal Name"], index=working.index)
    working["OutcomeItemKey"] = working["Item Name"].map(normalize_outcome_item_text)
    working["OutcomeAmount"] = pd.to_numeric(working["Amount"], errors="coerce").fillna(0)
    working = working.dropna(subset=["OutcomeChargeDate"])
    return working


def outcome_as_of_date(sales_df: pd.DataFrame | None, fallback: date | None = None) -> date:
    fallback_date = fallback or user_today()
    if sales_df is None or getattr(sales_df, "empty", True) or "ChargeDate" not in sales_df.columns:
        return fallback_date
    latest_sale_date = parse_dates(sales_df["ChargeDate"]).dropna().max()
    if pd.isna(latest_sale_date):
        return fallback_date
    return pd.Timestamp(latest_sale_date).date()


def outcome_timing_label(days_vs_due, on_time_grace_days: int) -> str:
    if days_vs_due is None or pd.isna(days_vs_due):
        return ""
    try:
        offset = int(days_vs_due)
    except (TypeError, ValueError):
        return ""
    if offset < -on_time_grace_days:
        return "Early"
    if offset <= on_time_grace_days:
        return "On time"
    return "Late"


def days_between_dates(start: date | None, end: date | None) -> int | None:
    if start is None or end is None:
        return None
    return (end - start).days


def positive_int_or_none(value) -> int | None:
    try:
        parsed = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def outcome_desired_gap_days(
    record: dict,
    terms: list[str],
    due_date: date | None,
    original_charge_date: date | None,
    rules: dict | None = None,
) -> int | None:
    direct_days = positive_int_or_none(record.get("Days", ""))
    if direct_days is not None:
        return direct_days

    for detail in normalize_reminder_details_for_storage(record.get("ReminderDetails", [])):
        detail_days = positive_int_or_none(detail.get("Days", ""))
        if detail_days is not None:
            return detail_days

    normalized_rules = {
        normalize_outcome_item_text(rule): settings
        for rule, settings in (rules or {}).items()
        if normalize_outcome_item_text(rule)
    }
    for term in terms or []:
        settings = normalized_rules.get(normalize_outcome_item_text(term))
        if isinstance(settings, dict):
            rule_days = positive_int_or_none(settings.get("days", ""))
            if rule_days is not None:
                return rule_days

    date_gap = days_between_dates(original_charge_date, due_date)
    if date_gap is not None and date_gap > 0:
        return date_gap
    return None


def average_sales_purchase_gap(sales: pd.DataFrame, exact_item_keys: list[str] | None = None, terms: list[str] | None = None) -> float | None:
    if sales is None or sales.empty:
        return None
    normalized_exact_keys = [
        normalize_outcome_item_text(key)
        for key in exact_item_keys or []
        if normalize_outcome_item_text(key)
    ]
    normalized_terms = prune_contained_outcome_terms(list(terms or []))
    if not normalized_exact_keys and not normalized_terms:
        return None

    sale_keys = sales["OutcomeItemKey"].astype(str)
    if normalized_exact_keys:
        mask = sale_keys.isin(set(normalized_exact_keys))
    else:
        mask = pd.Series(False, index=sales.index)
        for term in normalized_terms:
            mask = mask | sale_keys.str.contains(re.escape(term), regex=True, na=False)
    matched = sales.loc[
        mask
        & sales["OutcomeClientKey"].astype(str).ne("")
        & sales["OutcomePatientKey"].astype(str).ne("")
    ].copy()
    if matched.empty:
        return None

    gaps: list[int] = []
    matched = matched.dropna(subset=["OutcomeChargeDate"])
    for _, group in matched.sort_values("OutcomeChargeDate").groupby(["OutcomeClientKey", "OutcomePatientKey"], dropna=False):
        dates = pd.to_datetime(group["OutcomeChargeDate"], errors="coerce").dropna().drop_duplicates().sort_values()
        if len(dates) < 2:
            continue
        diffs = dates.diff().dt.days.dropna()
        gaps.extend(int(value) for value in diffs.tolist() if pd.notna(value) and int(value) > 0)
    if not gaps:
        return None
    return float(np.mean(gaps))


def outcome_sale_item_matches(exact_item_keys, term, sale_key: str) -> bool:
    sale_key = str(sale_key or "")
    if isinstance(exact_item_keys, list) and exact_item_keys:
        for exact_key in exact_item_keys:
            if exact_key and (sale_key == exact_key or exact_key in sale_key):
                return True
        return False
    if term is None or pd.isna(term):
        return False
    term_key = str(term or "")
    return bool(term_key and term_key in sale_key)


def outcome_next_purchase_gap_is_success(next_gap_days, desired_gap_days, due_date_window_days: int) -> bool:
    if next_gap_days is None or desired_gap_days is None:
        return False
    try:
        next_gap = float(next_gap_days)
        desired_gap = float(desired_gap_days)
    except (TypeError, ValueError):
        return False
    if pd.isna(next_gap) or pd.isna(desired_gap):
        return False
    return abs(next_gap - desired_gap) <= max(0, int(due_date_window_days))


def outcome_match_keys_for_record(exact_item_keys: list[str] | None, terms: list[str] | None) -> list[str]:
    source = exact_item_keys if exact_item_keys else terms
    keys = []
    seen = set()
    for value in source or []:
        key = normalize_outcome_item_text(value)
        if not key or key in seen:
            continue
        seen.add(key)
        keys.append(key)
    return keys


def build_outcome_item_match_map(sales: pd.DataFrame, match_keys: Iterable[str]) -> pd.DataFrame:
    columns = ["_OutcomeMatchKey", "OutcomeItemKey"]
    if sales is None or sales.empty or "OutcomeItemKey" not in sales.columns:
        return pd.DataFrame(columns=columns)

    keys = sorted({
        normalize_outcome_item_text(key)
        for key in match_keys or []
        if normalize_outcome_item_text(key)
    })
    if not keys:
        return pd.DataFrame(columns=columns)

    sale_item_keys = (
        sales["OutcomeItemKey"]
        .dropna()
        .astype(str)
        .loc[lambda values: values.str.len() > 0]
        .drop_duplicates()
        .sort_values()
    )
    if sale_item_keys.empty:
        return pd.DataFrame(columns=columns)

    mapped_frames = []
    for key in keys:
        matched_keys = sale_item_keys.loc[sale_item_keys.str.contains(key, regex=False, na=False)]
        if matched_keys.empty:
            continue
        mapped_frames.append(pd.DataFrame({"_OutcomeMatchKey": key, "OutcomeItemKey": matched_keys.to_numpy()}))
    if not mapped_frames:
        return pd.DataFrame(columns=columns)
    return pd.concat(mapped_frames, ignore_index=True).drop_duplicates(columns)


def build_average_sales_purchase_gap_map(
    sales: pd.DataFrame,
    gap_key_matches: dict[tuple[str, ...], list[str]],
    item_match_map: pd.DataFrame,
) -> dict[tuple[str, ...], dict[str, float | int | None]]:
    empty_result = {"average": None, "count": 0, "total": 0, "repeat_rate": 0.0}
    if sales is None or sales.empty or not gap_key_matches:
        return {key: dict(empty_result) for key in gap_key_matches}

    gap_lookup = {idx: key for idx, key in enumerate(gap_key_matches)}
    exact_rows = []
    term_rows = []
    for gap_id, gap_key in gap_lookup.items():
        match_keys = [
            normalize_outcome_item_text(key)
            for key in gap_key_matches.get(gap_key, [])
            if normalize_outcome_item_text(key)
        ]
        if not match_keys:
            continue
        if gap_key and gap_key[0] == "exact":
            exact_rows.extend({"_GapID": gap_id, "OutcomeItemKey": key} for key in match_keys)
        else:
            term_rows.extend({"_GapID": gap_id, "_OutcomeMatchKey": key} for key in match_keys)

    key_frames = []
    if exact_rows:
        key_frames.append(pd.DataFrame(exact_rows).drop_duplicates(["_GapID", "OutcomeItemKey"]))
    if term_rows and item_match_map is not None and not item_match_map.empty:
        term_key_frame = pd.DataFrame(term_rows).drop_duplicates(["_GapID", "_OutcomeMatchKey"]).merge(
            item_match_map,
            on="_OutcomeMatchKey",
            how="inner",
        )[["_GapID", "OutcomeItemKey"]]
        if not term_key_frame.empty:
            key_frames.append(term_key_frame.drop_duplicates(["_GapID", "OutcomeItemKey"]))
    if not key_frames:
        return {key: dict(empty_result) for key in gap_key_matches}

    gap_item_keys = pd.concat(key_frames, ignore_index=True).drop_duplicates(["_GapID", "OutcomeItemKey"])
    matched = gap_item_keys.merge(
        sales[["OutcomeItemKey", "OutcomeClientKey", "OutcomePatientKey", "OutcomeChargeDate"]],
        on="OutcomeItemKey",
        how="inner",
    )
    if matched.empty:
        return {key: dict(empty_result) for key in gap_key_matches}

    matched = matched.loc[
        matched["OutcomeClientKey"].astype(str).ne("")
        & matched["OutcomePatientKey"].astype(str).ne("")
        & pd.to_datetime(matched["OutcomeChargeDate"], errors="coerce").notna()
    ].copy()
    if matched.empty:
        return {key: dict(empty_result) for key in gap_key_matches}

    matched["OutcomeChargeDate"] = pd.to_datetime(matched["OutcomeChargeDate"], errors="coerce")
    matched = matched.drop_duplicates(["_GapID", "OutcomeClientKey", "OutcomePatientKey", "OutcomeChargeDate"])
    matched = matched.sort_values(["_GapID", "OutcomeClientKey", "OutcomePatientKey", "OutcomeChargeDate"])
    total_counts = matched.groupby("_GapID")["OutcomeChargeDate"].count()
    matched["_GapDays"] = (
        matched
        .groupby(["_GapID", "OutcomeClientKey", "OutcomePatientKey"], dropna=False)["OutcomeChargeDate"]
        .diff()
        .dt.days
    )
    positive_gaps = matched.loc[matched["_GapDays"].gt(0)]
    gap_means = positive_gaps.groupby("_GapID")["_GapDays"].mean()
    gap_counts = positive_gaps.groupby("_GapID")["_GapDays"].count()
    return {
        gap_key: {
            "average": float(gap_means.loc[gap_id]) if gap_id in gap_means.index else None,
            "count": int(gap_counts.loc[gap_id]) if gap_id in gap_counts.index else 0,
            "total": int(total_counts.loc[gap_id]) if gap_id in total_counts.index else 0,
            "repeat_rate": (
                float(gap_counts.loc[gap_id]) / float(total_counts.loc[gap_id])
                if gap_id in gap_counts.index and gap_id in total_counts.index and int(total_counts.loc[gap_id]) > 0
                else 0.0
            ),
        }
        for gap_id, gap_key in gap_lookup.items()
    }


@st.cache_data(show_spinner=False, max_entries=8)
def build_reminder_outcomes(
    action_records: list[dict],
    sales_df: pd.DataFrame,
    due_date_window_days: int = DEFAULT_OUTCOME_DUE_DATE_WINDOW_DAYS,
    on_time_grace_days: int | None = None,
    today: date | None = None,
    attribution_days: int | None = None,
    rules: dict | None = None,
) -> pd.DataFrame:
    today = today or outcome_as_of_date(sales_df)
    if attribution_days is not None:
        due_date_window_days = attribution_days
    try:
        due_date_window_days = max(0, int(due_date_window_days))
    except (TypeError, ValueError):
        due_date_window_days = DEFAULT_OUTCOME_DUE_DATE_WINDOW_DAYS

    sales = prepare_sales_for_outcomes(sales_df)
    reduced_records = reduce_action_tracker_records([
        record for record in action_records or []
        if isinstance(record, dict)
    ])
    sent_records = dedupe_outcome_sent_records(expand_grouped_action_records([
        record for record in reduced_records
        if str(record.get("Action", "")).strip().lower() == REMINDER_ACTION_SENT
    ]))
    if not sent_records:
        return empty_outcome_frame()

    rows = []
    gap_key_matches: dict[tuple[str, ...], list[str]] = {}
    all_match_keys: set[str] = set()
    for record_id, record in enumerate(sent_records):
        actioned_dt = _parse_reminder_log_time(record.get("ActionedAt", "") or record.get("DeletedAt", ""))
        actioned_date = actioned_dt.date() if actioned_dt else None
        reminder_date = first_statistics_date(record.get("Reminder Date", ""))
        sent_date = actioned_date or reminder_date
        due_date = first_statistics_date(record.get("Due Date", ""))
        original_charge_date = first_statistics_date(record.get("Charge Date", ""))
        if due_date:
            window_start = due_date - timedelta(days=due_date_window_days)
            if original_charge_date and window_start <= original_charge_date:
                window_start = original_charge_date + timedelta(days=1)
            window_end = due_date + timedelta(days=due_date_window_days)
        else:
            window_start = sent_date
            window_end = sent_date + timedelta(days=due_date_window_days) if sent_date else None
        client_name = normalize_display_case(str(record.get("Client Name", "") or "").strip())
        animal_name = normalize_display_case(str(record.get("Animal Name", "") or "").strip())
        item_name = normalize_display_case(str(record.get("Plan Item", "") or "").strip())
        sender = str(record.get("Actioned By", "") or "").strip() or "Unknown"
        terms = outcome_search_terms_for_record(record, item_name, rules)
        exact_item_keys = outcome_exact_item_keys_for_record(record, item_name, terms, rules)
        match_keys = outcome_match_keys_for_record(exact_item_keys, terms)
        desired_gap_days = outcome_desired_gap_days(record, terms, due_date, original_charge_date, rules)
        if exact_item_keys:
            gap_cache_key = ("exact", *sorted(set(exact_item_keys)))
        else:
            gap_cache_key = ("terms", *sorted({term for term in terms if term}))
        if len(gap_cache_key) > 1:
            gap_key_matches.setdefault(gap_cache_key, outcome_match_keys_for_record(exact_item_keys, terms))
            all_match_keys.update(gap_key_matches[gap_cache_key])
        all_match_keys.update(match_keys)

        if sent_date is None:
            outcome = "Not Measurable"
        elif window_end and window_end >= today:
            outcome = "Pending"
        else:
            outcome = "No Match"

        rows.append({
            "_OutcomeRecordID": record_id,
            "_OutcomeClientKey": normalize_outcome_identity(client_name),
            "_OutcomePatientKey": normalize_outcome_identity(animal_name),
            "_OutcomeTerms": terms,
            "_OutcomeExactItemKeys": exact_item_keys,
            "_OutcomeMatchKeys": match_keys,
            "_OutcomeGapCacheKey": gap_cache_key,
            "Charge Date": pd.Timestamp(original_charge_date) if original_charge_date else pd.NaT,
            "Reminder Date": pd.Timestamp(reminder_date) if reminder_date else pd.NaT,
            "Sent Date": pd.Timestamp(sent_date) if sent_date else pd.NaT,
            "Actioned Date": pd.Timestamp(actioned_date) if actioned_date else pd.NaT,
            "Due Date": pd.Timestamp(due_date) if due_date else pd.NaT,
            "Window Starts": pd.Timestamp(window_start) if window_start else pd.NaT,
            "Window Ends": pd.Timestamp(window_end) if window_end else pd.NaT,
            "Next Purchase Date": pd.NaT,
            "Success Date": pd.NaT,
            "Client Name": client_name,
            "Animal Name": animal_name,
            "Item": item_name,
            "Sender": sender,
            "Outcome": outcome,
            "Desired Gap Days": desired_gap_days,
            "Success Gap Days": None,
            "Next Purchase Gap Days": None,
            "Avg Item Purchase Gap Days": None,
            "Overall Repeat Purchases": 0,
            "Overall Purchases": 0,
            "Repeat Purchase %": 0.0,
            "Revenue": 0.0,
            "Matched Item": "",
            "Next Matched Item": "",
        })

    outcomes = pd.DataFrame(rows)
    if outcomes.empty:
        return empty_outcome_frame()

    item_match_map = build_outcome_item_match_map(sales, all_match_keys)
    if gap_key_matches:
        gap_map = build_average_sales_purchase_gap_map(sales, gap_key_matches, item_match_map)
        outcomes["Avg Item Purchase Gap Days"] = outcomes["_OutcomeGapCacheKey"].map(
            lambda key: (gap_map.get(key) or {}).get("average")
        )
        outcomes["Overall Repeat Purchases"] = outcomes["_OutcomeGapCacheKey"].map(
            lambda key: (gap_map.get(key) or {}).get("count", 0)
        )
        outcomes["Overall Purchases"] = outcomes["_OutcomeGapCacheKey"].map(
            lambda key: (gap_map.get(key) or {}).get("total", 0)
        )
        outcomes["Repeat Purchase %"] = outcomes["_OutcomeGapCacheKey"].map(
            lambda key: (gap_map.get(key) or {}).get("repeat_rate", 0.0)
        )

    measurable = outcomes.loc[
        outcomes["Sent Date"].notna()
        & outcomes["Window Starts"].notna()
        & outcomes["Window Ends"].notna()
        & outcomes["_OutcomeMatchKeys"].map(bool),
        [
            "_OutcomeRecordID",
            "_OutcomeClientKey",
            "_OutcomePatientKey",
            "_OutcomeMatchKeys",
            "Sent Date",
            "Charge Date",
            "Due Date",
            "Window Starts",
            "Window Ends",
        ],
    ]

    if not measurable.empty and not sales.empty and not item_match_map.empty:
        match_rows = measurable.explode("_OutcomeMatchKeys").rename(columns={"_OutcomeMatchKeys": "_OutcomeMatchKey"})
        match_rows = match_rows.loc[match_rows["_OutcomeMatchKey"].fillna("").astype(str).ne("")]
        if not match_rows.empty:
            matched_item_rows = match_rows.merge(
                item_match_map,
                on="_OutcomeMatchKey",
                how="inner",
            )
            merged = matched_item_rows.merge(
                sales[
                    [
                        "OutcomeClientKey",
                        "OutcomePatientKey",
                        "OutcomeChargeDate",
                        "OutcomeItemKey",
                        "OutcomeAmount",
                        "Item Name",
                        "OutcomeSaleID",
                    ]
                ],
                left_on=["_OutcomeClientKey", "_OutcomePatientKey", "OutcomeItemKey"],
                right_on=["OutcomeClientKey", "OutcomePatientKey", "OutcomeItemKey"],
                how="inner",
            )
            if not merged.empty:
                merged = merged.drop_duplicates(["_OutcomeRecordID", "OutcomeSaleID"])
                charge_dates = pd.to_datetime(merged["Charge Date"], errors="coerce")
                after_original_mask = (
                    charge_dates.isna()
                    | (merged["OutcomeChargeDate"] > charge_dates)
                )
                merged = merged.loc[after_original_mask]
            if not merged.empty:
                first_next_purchases = (
                    merged.sort_values(["_OutcomeRecordID", "OutcomeChargeDate", "OutcomeSaleID"])
                    .drop_duplicates("_OutcomeRecordID", keep="first")
                )
                if not first_next_purchases.empty:
                    record_ids = first_next_purchases["_OutcomeRecordID"].astype(int).to_numpy()
                    next_purchase_dates = pd.to_datetime(first_next_purchases["OutcomeChargeDate"], errors="coerce")
                    charge_dates = pd.to_datetime(outcomes.loc[record_ids, "Charge Date"], errors="coerce").reset_index(drop=True)
                    next_gap_days = (next_purchase_dates.reset_index(drop=True) - charge_dates).dt.days
                    matched_items = first_next_purchases["Item Name"].map(
                        lambda value: normalize_display_case(str(value or "").strip())
                    ).to_numpy()

                    outcomes.loc[record_ids, "Next Purchase Date"] = next_purchase_dates.to_numpy()
                    outcomes.loc[record_ids, "Next Purchase Gap Days"] = next_gap_days.to_numpy()
                    outcomes.loc[record_ids, "Next Matched Item"] = matched_items

                    desired_gap_days = pd.to_numeric(outcomes.loc[record_ids, "Desired Gap Days"], errors="coerce").reset_index(drop=True)
                    success_by_gap = (
                        next_gap_days.notna()
                        & desired_gap_days.notna()
                        & (next_gap_days.astype(float).sub(desired_gap_days.astype(float)).abs() <= due_date_window_days)
                    )
                    window_start = pd.to_datetime(outcomes.loc[record_ids, "Window Starts"], errors="coerce").reset_index(drop=True)
                    window_end = pd.to_datetime(outcomes.loc[record_ids, "Window Ends"], errors="coerce").reset_index(drop=True)
                    success_by_window = next_purchase_dates.reset_index(drop=True).between(window_start, window_end, inclusive="both")
                    success_mask = (success_by_gap | success_by_window).fillna(False).to_numpy()
                    success_record_ids = record_ids[success_mask]
                    if len(success_record_ids):
                        outcomes.loc[success_record_ids, "Success Date"] = next_purchase_dates.loc[success_mask].to_numpy()
                        outcomes.loc[success_record_ids, "Matched Item"] = matched_items[success_mask]
                        outcomes.loc[success_record_ids, "Revenue"] = (
                            pd.to_numeric(first_next_purchases.loc[success_mask, "OutcomeAmount"], errors="coerce")
                            .fillna(0)
                            .to_numpy()
                        )
                        outcomes.loc[success_record_ids, "Success Gap Days"] = next_gap_days.loc[success_mask].to_numpy()
                        outcomes.loc[success_record_ids, "Outcome"] = "Reminder Success"

    return outcomes[OUTCOME_TABLE_COLUMNS]


def filter_outcomes_for_period(outcomes_df: pd.DataFrame, period: str, today: date | None = None) -> pd.DataFrame:
    if outcomes_df is None or outcomes_df.empty:
        return empty_outcome_frame()
    today = today or user_today()
    start = statistics_period_start(period, today)
    if start is None:
        return outcomes_df.copy()
    sent_dates = pd.to_datetime(outcomes_df["Sent Date"], errors="coerce").dt.date
    return outcomes_df.loc[(sent_dates >= start) & (sent_dates <= today)].copy()


def summarize_outcomes(outcomes_df: pd.DataFrame) -> dict:
    if outcomes_df is None or outcomes_df.empty:
        return {
            "sent": 0,
            "successes": 0,
            "pending": 0,
            "no_match": 0,
            "success_rate": 0.0,
            "avg_success_gap_days": None,
            "avg_desired_gap_days": None,
            "avg_item_purchase_gap_days": None,
            "overall_repeat_purchases": 0,
            "overall_purchases": 0,
            "repeat_purchase_rate": 0.0,
            "revenue": 0.0,
        }
    sent = len(outcomes_df.index)
    success_mask = outcomes_df["Outcome"].eq("Reminder Success")
    successes = int(success_mask.sum())
    pending = int(outcomes_df["Outcome"].eq("Pending").sum())
    no_match = max(0, sent - successes - pending)
    success_df = outcomes_df.loc[success_mask]
    desired_gap_values = (
        pd.to_numeric(outcomes_df["Desired Gap Days"], errors="coerce")
        if "Desired Gap Days" in outcomes_df.columns
        else pd.Series(dtype=float)
    )
    success_gap_values = (
        pd.to_numeric(success_df["Success Gap Days"], errors="coerce")
        if "Success Gap Days" in success_df.columns
        else pd.Series(dtype=float)
    )
    if "Item" in outcomes_df.columns and "Avg Item Purchase Gap Days" in outcomes_df.columns:
        gap_columns = ["Item", "Avg Item Purchase Gap Days"]
        if "Overall Repeat Purchases" in outcomes_df.columns:
            gap_columns.append("Overall Repeat Purchases")
        if "Overall Purchases" in outcomes_df.columns:
            gap_columns.append("Overall Purchases")
        item_purchase_gap_frame = (
            outcomes_df[gap_columns]
            .dropna(subset=["Avg Item Purchase Gap Days"])
            .drop_duplicates("Item")
        )
        if "Overall Repeat Purchases" not in item_purchase_gap_frame.columns:
            item_purchase_gap_frame["Overall Repeat Purchases"] = 0
        item_purchase_gap_values = pd.to_numeric(
            item_purchase_gap_frame["Avg Item Purchase Gap Days"],
            errors="coerce",
        )
        item_purchase_gap_counts = pd.to_numeric(
            item_purchase_gap_frame["Overall Repeat Purchases"],
            errors="coerce",
        ).fillna(0)
        if "Overall Purchases" not in item_purchase_gap_frame.columns:
            item_purchase_gap_frame["Overall Purchases"] = 0
        item_purchase_total_counts = pd.to_numeric(
            item_purchase_gap_frame["Overall Purchases"],
            errors="coerce",
        ).fillna(0)
    else:
        item_purchase_gap_values = pd.Series(dtype=float)
        item_purchase_gap_counts = pd.Series(dtype=float)
        item_purchase_total_counts = pd.Series(dtype=float)
    overall_repeat_purchases = int(item_purchase_gap_counts.sum()) if not item_purchase_gap_counts.empty else 0
    overall_purchases = int(item_purchase_total_counts.sum()) if not item_purchase_total_counts.empty else 0
    return {
        "sent": sent,
        "successes": successes,
        "pending": pending,
        "no_match": no_match,
        "success_rate": (successes / sent) if sent else 0.0,
        "avg_success_gap_days": success_gap_values.mean() if successes else None,
        "avg_desired_gap_days": desired_gap_values.mean(),
        "avg_item_purchase_gap_days": item_purchase_gap_values.mean(),
        "overall_repeat_purchases": overall_repeat_purchases,
        "overall_purchases": overall_purchases,
        "repeat_purchase_rate": (overall_repeat_purchases / overall_purchases) if overall_purchases else 0.0,
        "revenue": float(pd.to_numeric(success_df["Revenue"], errors="coerce").fillna(0).sum()) if successes else 0.0,
    }


def build_outcome_group_frame(
    outcomes_df: pd.DataFrame,
    group_col: str,
    columns: list[str] | None = None,
) -> pd.DataFrame:
    base_columns = [
        group_col,
        "Sent",
        "Successes",
        "Pending",
        "No Match",
        "Success Rate",
        "Desired Gap Days",
        "Avg Success Gap Days",
        "Avg Item Purchase Gap Days",
        "Overall Repeat Purchases",
        "Overall Purchases",
        "Repeat Purchase %",
        "Revenue",
    ]
    columns = columns or base_columns
    if outcomes_df is None or outcomes_df.empty or group_col not in outcomes_df.columns:
        return pd.DataFrame(columns=columns)

    rows = []
    source = outcomes_df.copy()
    source[group_col] = source[group_col].fillna("").astype(str).str.strip().replace("", "Unknown")
    for group_value, group_df in source.groupby(group_col, dropna=False):
        summary = summarize_outcomes(group_df)
        rows.append({
            group_col: group_value,
            "Sent": summary["sent"],
            "Successes": summary["successes"],
            "Pending": summary["pending"],
            "No Match": summary["no_match"],
            "Success Rate": summary["success_rate"],
            "Desired Gap Days": summary["avg_desired_gap_days"],
            "Avg Success Gap Days": summary["avg_success_gap_days"],
            "Avg Item Purchase Gap Days": summary["avg_item_purchase_gap_days"],
            "Overall Repeat Purchases": summary["overall_repeat_purchases"],
            "Overall Purchases": summary["overall_purchases"],
            "Repeat Purchase %": summary["repeat_purchase_rate"],
            "Revenue": summary["revenue"],
        })
    frame = pd.DataFrame(rows, columns=base_columns)
    frame = frame[[column for column in columns if column in frame.columns]]
    return frame.sort_values(["Successes", "Sent"], ascending=False)


def build_stats_team_frame(
    outcome_sender_frame: pd.DataFrame,
    action_records: list[dict],
    period: str = "All time",
    today: date | None = None,
) -> pd.DataFrame:
    outcome_columns = [
        "Team Member",
        "Sent Reminders",
        "Successes",
        "Pending",
        "No Match",
        "Success Rate",
        "Revenue",
    ]
    action_columns = ["Team Member", "Actioned", "Sent Actions", "Declined Actions", "Last Actioned"]
    if outcome_sender_frame is None or outcome_sender_frame.empty:
        outcome_frame = pd.DataFrame(columns=outcome_columns)
    else:
        outcome_frame = outcome_sender_frame.rename(
            columns={
                "Sender": "Team Member",
                "Sent": "Sent Reminders",
            }
        )
        outcome_frame = outcome_frame[[column for column in outcome_columns if column in outcome_frame.columns]]

    action_frame = build_statistics_team_frame(action_records, period, today).rename(
        columns={
            "User": "Team Member",
            "Sent": "Sent Actions",
            "Declined": "Declined Actions",
        }
    )
    action_frame = action_frame[[column for column in action_columns if column in action_frame.columns]]

    if outcome_frame.empty and action_frame.empty:
        return pd.DataFrame(columns=STATS_TEAM_COLUMNS)
    if outcome_frame.empty:
        merged = action_frame.copy()
    elif action_frame.empty:
        merged = outcome_frame.copy()
    else:
        merged = outcome_frame.merge(action_frame, on="Team Member", how="outer")

    for column in STATS_TEAM_COLUMNS:
        if column not in merged.columns:
            merged[column] = "" if column in {"Team Member", "Last Actioned"} else 0

    numeric_columns = [
        "Sent Reminders",
        "Successes",
        "Pending",
        "No Match",
        "Success Rate",
        "Revenue",
        "Actioned",
        "Sent Actions",
        "Declined Actions",
    ]
    for column in numeric_columns:
        merged[column] = pd.to_numeric(merged[column], errors="coerce").fillna(0)
    for column in ["Sent Reminders", "Successes", "Pending", "No Match", "Actioned", "Sent Actions", "Declined Actions"]:
        merged[column] = merged[column].astype(int)
    merged["Team Member"] = merged["Team Member"].fillna("").astype(str).str.strip().replace("", "Unknown")
    merged["Last Actioned"] = merged["Last Actioned"].fillna("").astype(str)
    return (
        merged[STATS_TEAM_COLUMNS]
        .sort_values(["Actioned", "Successes", "Sent Reminders"], ascending=False)
        .reset_index(drop=True)
    )


def build_outcome_time_frame(outcomes_df: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "Sent Date",
        "Sent",
        "Successes",
        "Pending",
        "No Match",
        "Success Rate",
        "Desired Gap Days",
        "Avg Success Gap Days",
        "Avg Item Purchase Gap Days",
        "Overall Repeat Purchases",
        "Overall Purchases",
        "Repeat Purchase %",
        "Revenue",
    ]
    if outcomes_df is None or outcomes_df.empty:
        return pd.DataFrame(columns=columns)
    source = outcomes_df.copy()
    source["Sent Date"] = pd.to_datetime(source["Sent Date"], errors="coerce").dt.date
    source = source.dropna(subset=["Sent Date"])
    rows = []
    for sent_date, day_df in source.groupby("Sent Date", dropna=False):
        summary = summarize_outcomes(day_df)
        rows.append({
            "Sent Date": pd.Timestamp(sent_date),
            "Sent": summary["sent"],
            "Successes": summary["successes"],
            "Pending": summary["pending"],
            "No Match": summary["no_match"],
            "Success Rate": summary["success_rate"],
            "Desired Gap Days": summary["avg_desired_gap_days"],
            "Avg Success Gap Days": summary["avg_success_gap_days"],
            "Avg Item Purchase Gap Days": summary["avg_item_purchase_gap_days"],
            "Overall Repeat Purchases": summary["overall_repeat_purchases"],
            "Overall Purchases": summary["overall_purchases"],
            "Repeat Purchase %": summary["repeat_purchase_rate"],
            "Revenue": summary["revenue"],
        })
    return pd.DataFrame(rows, columns=columns).sort_values("Sent Date")


def format_outcome_number(value) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):.1f}"


def format_outcome_currency(value) -> str:
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        amount = 0.0
    return f"{amount:,.0f}"


def format_outcome_display_date(value) -> str:
    if value is None or pd.isna(value):
        return ""
    try:
        return pd.Timestamp(value).strftime("%b-%d-%Y")
    except (TypeError, ValueError):
        return str(value)


def prepare_outcome_dataframe_for_display(frame: pd.DataFrame) -> pd.DataFrame:
    display_frame = frame.copy()
    for column in OUTCOME_DISPLAY_DATE_COLUMNS:
        if column in display_frame.columns:
            display_frame[column] = display_frame[column].map(format_outcome_display_date)
    display_frame = display_frame.rename(columns=OUTCOME_DISPLAY_COLUMN_LABELS)
    return display_frame


def outcome_display_column_config() -> dict:
    column_config = {
        column: st.column_config.TextColumn(column, help=help_text)
        for column, help_text in OUTCOME_DISPLAY_COLUMN_HELP.items()
    }
    column_config.update({
        "Desired Gap Days": st.column_config.NumberColumn(
            "Desired Gap Days",
            help=OUTCOME_DISPLAY_COLUMN_HELP["Desired Gap Days"],
            format="%.0f",
        ),
        "Success Gap Days": st.column_config.NumberColumn(
            "Success Gap Days",
            help=OUTCOME_DISPLAY_COLUMN_HELP["Success Gap Days"],
            format="%.0f",
        ),
        "Next Purchase Gap Days": st.column_config.NumberColumn(
            "Next Purchase Gap Days",
            help=OUTCOME_DISPLAY_COLUMN_HELP["Next Purchase Gap Days"],
            format="%.0f",
        ),
        "Avg Success Gap Days": st.column_config.NumberColumn(
            "Avg Success Gap Days",
            help=OUTCOME_DISPLAY_COLUMN_HELP["Avg Success Gap Days"],
            format="%.1f",
        ),
        "Overall Avg Purchase Gap Days": st.column_config.NumberColumn(
            "Overall Avg Purchase Gap Days",
            help=OUTCOME_DISPLAY_COLUMN_HELP["Overall Avg Purchase Gap Days"],
            format="%.0f",
        ),
        "Overall Repeat Purchases": st.column_config.NumberColumn(
            "Overall Repeat Purchases",
            help=OUTCOME_DISPLAY_COLUMN_HELP["Overall Repeat Purchases"],
            format="%d",
        ),
        "Overall Purchases": st.column_config.NumberColumn(
            "Overall Purchases",
            help=OUTCOME_DISPLAY_COLUMN_HELP["Overall Purchases"],
            format="%d",
        ),
        "Repeat Purchase %": st.column_config.NumberColumn(
            "Repeat Purchase %",
            help=OUTCOME_DISPLAY_COLUMN_HELP["Repeat Purchase %"],
            format="%.0f%%",
        ),
        "Revenue": st.column_config.NumberColumn(
            "Revenue",
            help=OUTCOME_DISPLAY_COLUMN_HELP["Revenue"],
            format="localized",
        ),
        "Success Rate": st.column_config.ProgressColumn(
            "Success Rate",
            help=OUTCOME_DISPLAY_COLUMN_HELP["Success Rate"],
            format="percent",
            min_value=0,
            max_value=1,
        ),
    })
    return column_config


def stats_item_actioning_column_config() -> dict:
    return {
        "Item": st.column_config.TextColumn("Item", help=STATS_ITEM_ACTIONING_COLUMN_HELP["Item"]),
        STATISTICS_SCHEDULED_REMINDERS_LABEL: st.column_config.NumberColumn(
            STATISTICS_SCHEDULED_REMINDERS_LABEL,
            help=STATS_ITEM_ACTIONING_COLUMN_HELP[STATISTICS_SCHEDULED_REMINDERS_LABEL],
            format="%d",
        ),
        "Actioned": st.column_config.NumberColumn("Actioned", help=STATS_ITEM_ACTIONING_COLUMN_HELP["Actioned"], format="%d"),
        "Sent": st.column_config.NumberColumn("Sent", help=STATS_ITEM_ACTIONING_COLUMN_HELP["Sent"], format="%d"),
        "Declined": st.column_config.NumberColumn("Declined", help=STATS_ITEM_ACTIONING_COLUMN_HELP["Declined"], format="%d"),
    }


def stats_team_column_config() -> dict:
    return {
        "Team Member": st.column_config.TextColumn("Team Member", help=STATS_TEAM_COLUMN_HELP["Team Member"]),
        "Sent Reminders": st.column_config.NumberColumn("Sent Reminders", help=STATS_TEAM_COLUMN_HELP["Sent Reminders"], format="%d"),
        "Successes": st.column_config.NumberColumn("Successes", help=STATS_TEAM_COLUMN_HELP["Successes"], format="%d"),
        "Pending": st.column_config.NumberColumn("Pending", help=STATS_TEAM_COLUMN_HELP["Pending"], format="%d"),
        "No Match": st.column_config.NumberColumn("No Match", help=STATS_TEAM_COLUMN_HELP["No Match"], format="%d"),
        "Success Rate": st.column_config.NumberColumn("Success Rate", help=STATS_TEAM_COLUMN_HELP["Success Rate"], format="percent"),
        "Revenue": st.column_config.NumberColumn("Revenue", help=STATS_TEAM_COLUMN_HELP["Revenue"], format="localized"),
        "Actioned": st.column_config.NumberColumn("Actioned", help=STATS_TEAM_COLUMN_HELP["Actioned"], format="%d"),
        "Sent Actions": st.column_config.NumberColumn("Sent Actions", help=STATS_TEAM_COLUMN_HELP["Sent Actions"], format="%d"),
        "Declined Actions": st.column_config.NumberColumn("Declined Actions", help=STATS_TEAM_COLUMN_HELP["Declined Actions"], format="%d"),
        "Last Actioned": st.column_config.TextColumn("Last Actioned", help=STATS_TEAM_COLUMN_HELP["Last Actioned"]),
    }


def render_outcome_dataframe(
    frame: pd.DataFrame,
    columns: list[str] | None = None,
    table_key: str = "outcome_table",
    default_sort_column: str = "Successes",
    default_sort_ascending: bool = False,
):
    if columns is not None and frame is not None and not frame.empty:
        frame = frame[[column for column in columns if column in frame.columns]]
    if frame.empty:
        st.info("No outcome rows for this view yet.")
        return
    display_frame = prepare_outcome_dataframe_for_display(frame)
    st.dataframe(
        display_frame,
        hide_index=True,
        use_container_width=True,
        column_config=outcome_display_column_config(),
    )


def refresh_outcome_results_state() -> None:
    try:
        build_reminder_outcomes.clear()
    except Exception:
        pass
    clinic_id = str(st.session_state.get("clinic_id", "") or "").strip()
    if clinic_id:
        invalidate_action_tracker_records_cache()
        tracked_actions = load_action_tracker_records_for_clinic(clinic_id)
        st.session_state["deleted_reminders"] = merge_deleted_reminders(
            st.session_state.get("deleted_reminders", []),
            tracked_actions,
        )
        st.session_state["wa_reminder_log"] = merge_wa_reminder_logs(
            st.session_state.get("wa_reminder_log", []),
            action_records_to_wa_log(st.session_state["deleted_reminders"]),
        )
        if shared_dataset_reload_needed_for_clinic(clinic_id):
            st.session_state.pop("_shared_dataset_load_attempted_for", None)
            load_shared_dataset_for_clinic()
    st.session_state["_outcomes_refresh_success"] = "Stats refreshed."


def refresh_outcome_results_action() -> None:
    set_main_section_tab("Stats")
    with busy_overlay("Refreshing stats", "Re-syncing reminder actions and saved clinic data."):
        refresh_outcome_results_state()


def render_stats_tab(sales_df: pd.DataFrame, prepared: pd.DataFrame, rules: dict):
    st.markdown("<div id='stats' class='anchor-offset'></div><div id='outcomes' class='anchor-offset'></div>", unsafe_allow_html=True)
    title_col, refresh_col = st.columns([4, 1], gap="large")
    with title_col:
        st.markdown("## 📊 Stats")
    with refresh_col:
        st.markdown("<div style='height:0.35rem;'></div>", unsafe_allow_html=True)
        st.button(
            "Refresh Stats",
            key="outcomes_refresh_results",
            type="primary",
            use_container_width=True,
            help="Re-sync sent reminders and saved clinic data, then recalculate stats.",
            on_click=refresh_outcome_results_action,
        )
    st.caption(
        "See which reminders were sent, which ones led to repeat purchases, and how items and team members are performing over time."
    )
    refresh_success = st.session_state.pop("_outcomes_refresh_success", "")
    if refresh_success:
        st.success(refresh_success)

    controls = st.columns([2, 1], gap="large")
    with controls[1]:
        render_field_label(
            st,
            "Success window around due date",
            "A reminder is successful when the matching sale is within this many days before or after the due date.",
        )
        st.session_state["outcome_due_date_window_days"] = normalized_outcome_due_date_window_days()
        due_date_window_days = st.number_input(
            "Success window around due date",
            min_value=0,
            max_value=1095,
            step=1,
            key="outcome_due_date_window_days",
            on_change=save_outcome_due_date_window_days,
            label_visibility="collapsed",
        )
        due_date_window_days = normalized_outcome_due_date_window_days(due_date_window_days)
    outcomes_as_of_date = outcome_as_of_date(sales_df)
    stats_period = "All time"
    try:
        statistics_group_days = max(0, int(st.session_state.get("client_group_days", 1) or 0))
    except (TypeError, ValueError):
        statistics_group_days = 1
    try:
        statistics_data_version = int(st.session_state.get("data_version", 0) or 0)
    except (TypeError, ValueError):
        statistics_data_version = 0

    with busy_overlay("Calculating stats", "Matching sent reminders to later sales and summarising actioning."):
        action_records = statistics_current_action_records()
        outcome_rows = build_reminder_outcomes(
            action_records,
            sales_df,
            due_date_window_days=due_date_window_days,
            today=outcomes_as_of_date,
            rules=rules,
        )
        generated_df = cached_statistics_generated_rows(
            prepared,
            rules,
            group_days=statistics_group_days,
            period=stats_period,
            today_iso=user_today().isoformat(),
            data_version=statistics_data_version,
            rules_fp=_rules_fp(rules),
            exclusion_fp=statistics_exclusion_fp(),
            schema_version=STATISTICS_GENERATED_SCHEMA_VERSION,
        )
        period_rows = outcome_rows

    summary = summarize_outcomes(period_rows)
    metric_cols = st.columns(5)
    metrics = [
        ("Sent", f"{summary['sent']:,}"),
        ("Reminder Successes", f"{summary['successes']:,}"),
        ("Success Rate", f"{summary['success_rate']:.0%}"),
        ("Pending", f"{summary['pending']:,}"),
        ("Revenue", format_outcome_currency(summary["revenue"])),
    ]
    for col, (label, value) in zip(metric_cols, metrics):
        with col:
            render_statistics_metric_card(label, value)

    item_tab, item_actioning_tab, team_tab, sent_tab, success_tab = st.tabs(
        ["Items", "Item Actioning", "Team", "Sent Reminders", "Successes"]
    )

    with item_tab:
        st.caption("All time; matched sent reminders grouped by item.")
        render_outcome_dataframe(
            build_outcome_group_frame(period_rows, "Item", OUTCOME_ITEM_GROUP_COLUMNS),
            table_key="stats_items",
        )

    with item_actioning_tab:
        st.caption("All time; generated reminders and saved actions grouped by item.")
        item_actioning_frame = build_statistics_item_frame(generated_df, action_records, stats_period)
        if item_actioning_frame.empty:
            st.info("No item actioning stats yet.")
        else:
            st.dataframe(
                prepare_statistics_display_frame(item_actioning_frame),
                hide_index=True,
                use_container_width=True,
                column_config=stats_item_actioning_column_config(),
            )

    with team_tab:
        st.caption("All time; outcome results by sender plus reminder actions by actioned date.")
        team_frame = build_stats_team_frame(
            build_outcome_group_frame(period_rows, "Sender", OUTCOME_SENDER_GROUP_COLUMNS),
            action_records,
            stats_period,
        )
        if team_frame.empty:
            st.info("No team stats yet.")
        else:
            st.dataframe(
                team_frame,
                hide_index=True,
                use_container_width=True,
                column_config=stats_team_column_config(),
            )

    with sent_tab:
        st.caption("All time; individual sent reminders used by outcome matching.")
        sent_rows = period_rows.sort_values(["Sent Date", "Client Name"], ascending=[False, True])
        sent_rows = paginate_dataframe(sent_rows, "outcomes_sent", OUTCOME_SENT_PAGE_SIZE, "sent outcome rows")
        render_outcome_dataframe(sent_rows, OUTCOME_SENT_DISPLAY_COLUMNS, table_key="outcomes_sent")

    with success_tab:
        st.caption("All time; sent reminders matched to a later sale inside the success window.")
        success_rows = period_rows.loc[period_rows["Outcome"].eq("Reminder Success")].sort_values(
            ["Success Date", "Client Name"],
            ascending=[False, True],
        )
        render_outcome_dataframe(success_rows, OUTCOME_SENT_DISPLAY_COLUMNS, table_key="outcomes_successes")


def render_search_terms_editor():
    # Rules editor (unchanged UI; behavior preserved)
    st.markdown("<div id='search-terms' class='anchor-offset'></div>", unsafe_allow_html=True)
    st.markdown("## 📝 Search Terms")

    def column_header(label, help_text):
        safe_label = html_lib.escape(label)
        safe_help = html_lib.escape(help_text)
        st.markdown(
            f"**{safe_label}** <span class='column-help' data-tooltip='{safe_help}'>?</span>",
            unsafe_allow_html=True,
        )

    def invalidate_reminder_rule_cache():
        st.session_state["search_criteria_changed"] = search_criteria_have_pending_changes()

    def save_rule_days(rule, key):
        days_raw = str(st.session_state.get(key, "")).strip()
        if not days_raw.isdigit() or int(days_raw) <= 0:
            st.session_state["_search_terms_autosave_error"] = f"Reminder 3 (Due Date) must be a positive integer for: {rule}"
            return
        old_value = st.session_state["rules"][rule].get("days", "")
        st.session_state["rules"][rule]["days"] = int(days_raw)
        save_settings_quietly()
        if str(old_value) != str(int(days_raw)):
            record_settings_audit_event("search_term_changed", "search_terms", rule, "days", old_value, int(days_raw), "search_terms_tab")
        invalidate_reminder_rule_cache()

    def save_rule_reminder_day(rule, field, key):
        days_raw = str(st.session_state.get(key, "")).strip()
        old_value = st.session_state["rules"][rule].get(field, "")
        if days_raw == "":
            st.session_state["rules"][rule].pop(field, None)
            new_value = ""
        elif days_raw.isdigit() and int(days_raw) > 0:
            st.session_state["rules"][rule][field] = int(days_raw)
            new_value = int(days_raw)
        else:
            label = {
                "reminder_1": "Reminder 1",
                "reminder_2": "Reminder 2",
                "overdue_reminder": "Overdue Reminder",
            }.get(field, "Reminder")
            st.session_state["_search_terms_autosave_error"] = f"{label} must be blank or a positive integer for: {rule}"
            return
        save_settings_quietly()
        if str(old_value) != str(new_value):
            record_settings_audit_event("search_term_changed", "search_terms", rule, field, old_value, new_value, "search_terms_tab")
        invalidate_reminder_rule_cache()

    def save_rule_visible_text(rule, key):
        visible_text = str(st.session_state.get(key, "")).strip()
        old_value = st.session_state["rules"][rule].get("visible_text", "")
        if visible_text:
            st.session_state["rules"][rule]["visible_text"] = visible_text
        else:
            st.session_state["rules"][rule].pop("visible_text", None)
        save_settings_quietly()
        if str(old_value) != str(visible_text):
            record_settings_audit_event("search_term_changed", "search_terms", rule, "visible_text", old_value, visible_text, "search_terms_tab")
        invalidate_reminder_rule_cache()

    def toggle_use_qty(rule, key):
        old_value = st.session_state["rules"][rule].get("use_qty", "")
        st.session_state["rules"][rule]["use_qty"] = st.session_state[key]
        save_settings_quietly()
        if bool(old_value) != bool(st.session_state[key]):
            record_settings_audit_event("search_term_changed", "search_terms", rule, "use_qty", old_value, st.session_state[key], "search_terms_tab")
        invalidate_reminder_rule_cache()

    st.markdown("### Add New Search Term")
    row_id = st.session_state['new_rule_counter']
    rule_col_widths = [3, 1, 1, 1.35, 1.35, 0.7, 2, 0.7]
    header_cols = st.columns(rule_col_widths, gap="small")
    with header_cols[0]: column_header("Search Term", "The product or service text to match in uploaded item names, such as bravecto, rabies, or librela.")
    with header_cols[1]: column_header("Reminder 1", "Optional early reminder date, counted in days after the billed date.")
    with header_cols[2]: column_header("Reminder 2", "Optional second early reminder date, counted in days after the billed date.")
    with header_cols[3]: column_header("Reminder 3 (Due Date)", "The main due date, counted in days after the billed date.")
    with header_cols[4]: column_header("Overdue Reminder", "Optional overdue reminder date, counted in days after the billed date. Example: due at 90, overdue at 100.")
    with header_cols[5]: column_header("Use Qty", "Use quantity to extend the due date, for example 2 x 30 days becomes 60 days.")
    with header_cols[6]: column_header("Message Text (optional)", "The friendly item name clients will see in WhatsApp messages.")

    def field_examples(first_example: str, second_example: str, extra_class: str = ""):
        classes = f"field-examples {extra_class}".strip()
        st.markdown(
            f"""
            <div class="{classes}">
              <div>{first_example}</div>
              <div>{second_example}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    c1, c2, c3, c4, c5, c6, c7, c8 = st.columns(rule_col_widths, gap="small")
    with c1:
        new_rule_name = st.text_input(
            "Search Term",
            key=f"new_rule_name_{row_id}",
            label_visibility="collapsed",
            help="Text to look for in the PMS item name, such as bravecto, rabies, or librela."
        )
        field_examples(
            "Example 1: Canine Annual Vaccine Package",
            "Example 2: stride-joint-supplement-120ml-small",
        )
    with c2:
        new_rule_reminder_1 = st.text_input(
            "Reminder 1",
            key=f"new_rule_reminder_1_{row_id}",
            label_visibility="collapsed",
            help="Optional first reminder date, in days after the billed date."
        )
        field_examples("335", "blank")
    with c3:
        new_rule_reminder_2 = st.text_input(
            "Reminder 2",
            key=f"new_rule_reminder_2_{row_id}",
            label_visibility="collapsed",
            help="Optional second reminder date, in days after the billed date."
        )
        field_examples("357", "50")
    with c4:
        new_rule_days = st.text_input(
            "Reminder 3 (Due Date)",
            key=f"new_rule_days_{row_id}",
            label_visibility="collapsed",
            help="Positive integer number of days until this item should be due again."
        )
        field_examples("365", "60")
    with c5:
        new_rule_overdue = st.text_input(
            "Overdue Reminder",
            key=f"new_rule_overdue_{row_id}",
            label_visibility="collapsed",
            help="Optional overdue reminder date, counted in days after the billed date."
        )
        field_examples("375", "70")
    with c6:
        new_rule_use_qty = st.checkbox(
            "Use Qty",
            key=f"new_rule_useqty_{row_id}",
            label_visibility="collapsed",
            help="Use when quantity should extend the reminder interval."
        )
        field_examples(
            "Unticked",
            "Ticked",
            "use-qty-examples",
        )
    with c7:
        new_rule_visible = st.text_input(
            "Message Text (optional)",
            key=f"new_rule_vis_{row_id}",
            label_visibility="collapsed",
            help="Friendly wording to show users and clients, such as Bravecto Tablet."
        )
        field_examples(
            "Annual vaccination and check-up",
            "Stride joint health supplement",
        )
    with c8:
        if st.button("➕ Add", key=f"add_{row_id}"):
            safe_rule = str(new_rule_name or "").strip().lower()
            if safe_rule and str(new_rule_days).isdigit() and int(new_rule_days) > 0:
                rule_data = {"days": int(new_rule_days), "use_qty": bool(new_rule_use_qty)}
                invalid_reminder = ""
                for raw_value, field, label in [
                    (new_rule_reminder_1, "reminder_1", "Reminder 1"),
                    (new_rule_reminder_2, "reminder_2", "Reminder 2"),
                    (new_rule_overdue, "overdue_reminder", "Overdue Reminder"),
                ]:
                    raw_value = str(raw_value or "").strip()
                    if raw_value:
                        if not raw_value.isdigit() or int(raw_value) <= 0:
                            invalid_reminder = label
                            break
                        rule_data[field] = int(raw_value)
                if invalid_reminder:
                    st.error(f"{invalid_reminder} must be blank or a positive integer")
                else:
                    if new_rule_visible.strip():
                        rule_data["visible_text"] = new_rule_visible.strip()
                    if safe_rule in st.session_state["rules"]:
                        st.info("This search term already exists. Edit it in Current Search Terms.")
                    else:
                        st.session_state["rules"][safe_rule] = rule_data
                        st.session_state["search_term_added"] = True
                        st.session_state["search_term_added_at"] = user_now().isoformat()
                        save_settings_quietly()
                        record_settings_audit_event("search_term_added", "search_terms", safe_rule, "rule", "", rule_data, "search_terms_tab")
                        st.session_state["new_rule_counter"] += 1
                        invalidate_reminder_rule_cache()
                        st.rerun()
            else:
                st.error("Enter a name and valid positive integer for Reminder 3 (Due Date)")


    st.divider()
    st.markdown("### Current Search Terms")

    cols = st.columns(rule_col_widths)
    with cols[0]: column_header("Search Term", "The product or service text matched against uploaded item names.")
    with cols[1]: column_header("Reminder 1", "Optional early reminder date, counted in days after the billed date.")
    with cols[2]: column_header("Reminder 2", "Optional second early reminder date, counted in days after the billed date.")
    with cols[3]: column_header("Reminder 3 (Due Date)", "The main due date, counted in days after the billed date.")
    with cols[4]: column_header("Overdue Reminder", "Optional extra reminder after the due date, counted in days after the billed date.")
    with cols[5]: column_header("Use Qty", "When enabled, quantity extends the due date.")
    with cols[6]: column_header("Message Text", "The friendly item name shown in tables and WhatsApp messages.")
    with cols[7]: column_header("Delete", "Remove this search term from matching.")

    to_delete = []

    autosave_error = st.session_state.pop("_search_terms_autosave_error", "")
    if autosave_error:
        st.error(autosave_error)


    for rule, settings in sorted(st.session_state["rules"].items(), key=lambda x: x[0]):
        ver = st.session_state["form_version"]
        safe_rule = re.sub(r'[^a-zA-Z0-9_-]', '_', rule)
        with st.container():
            cols = st.columns(rule_col_widths, gap="small")
            with cols[0]:
                st.markdown(padded_html_text(rule), unsafe_allow_html=True)
            with cols[1]:
                st.text_input(
                    "Reminder 1", value=str(settings.get("reminder_1", "") or ""),
                    key=f"reminder_1_{safe_rule}_{ver}", label_visibility="collapsed",
                    on_change=save_rule_reminder_day,
                    args=(rule, "reminder_1", f"reminder_1_{safe_rule}_{ver}",),
                    help="Optional first reminder date, in days after the billed date."
                )
            with cols[2]:
                st.text_input(
                    "Reminder 2", value=str(settings.get("reminder_2", "") or ""),
                    key=f"reminder_2_{safe_rule}_{ver}", label_visibility="collapsed",
                    on_change=save_rule_reminder_day,
                    args=(rule, "reminder_2", f"reminder_2_{safe_rule}_{ver}",),
                    help="Optional second reminder date, in days after the billed date."
                )
            with cols[3]:
                st.text_input(
                    "Reminder 3 (Due Date)", value=str(settings["days"]),
                    key=f"days_{safe_rule}_{ver}", label_visibility="collapsed",
                    on_change=save_rule_days,
                    args=(rule, f"days_{safe_rule}_{ver}",),
                    help="Exact due date in days after the billed date. If Reminder 1 and 2 are blank, the reminder appears on this due date."
                )
            with cols[4]:
                st.text_input(
                    "Overdue Reminder", value=str(settings.get("overdue_reminder", "") or ""),
                    key=f"overdue_reminder_{safe_rule}_{ver}", label_visibility="collapsed",
                    on_change=save_rule_reminder_day,
                    args=(rule, "overdue_reminder", f"overdue_reminder_{safe_rule}_{ver}",),
                    help="Optional overdue reminder date, counted in days after the billed date."
                )
            with cols[5]:
                st.checkbox(
                    "Use Qty", value=settings["use_qty"],
                    key=f"useqty_{safe_rule}_{ver}",
                    label_visibility="collapsed",
                    on_change=toggle_use_qty,
                    args=(rule, f"useqty_{safe_rule}_{ver}",),
                )
            with cols[6]:
                st.text_input(
                    "Message Text", value=settings.get("visible_text",""),
                    key=f"vis_{safe_rule}_{ver}", label_visibility="collapsed",
                    on_change=save_rule_visible_text,
                    args=(rule, f"vis_{safe_rule}_{ver}",),
                    help="Optional friendly wording shown in tables and WhatsApp messages."
                )
            with cols[7]:
                if st.button("❌", key=f"del_{safe_rule}_{ver}"):
                    to_delete.append(rule)

    if to_delete:
        for rule in to_delete:
            old_rule = st.session_state["rules"].pop(rule, None)
            record_settings_audit_event("search_term_deleted", "search_terms", rule, "rule", old_rule, "", "search_terms_tab")
        save_settings_quietly()
        invalidate_reminder_rule_cache()
        st.rerun()

    if st.button("Reset defaults", help="Restore the default search terms and clear exclusions."):
        st.session_state["rules"] = DEFAULT_RULES.copy()
        st.session_state["exclusions"] = []
        st.session_state["client_exclusions"] = []
        st.session_state["patient_exclusions"] = []
        st.session_state["search_terms_reviewed"] = False
        st.session_state["search_term_added"] = False
        st.session_state["search_term_added_at"] = ""
        st.session_state["form_version"] += 1
        st.session_state["_replace_search_settings_once"] = True
        save_settings_quietly()
        record_settings_audit_event("search_terms_reset_defaults", "search_terms", "all", "rules", "custom", "default", "search_terms_tab")
        invalidate_reminder_rule_cache()
        st.rerun()

    # --------------------------------


def set_reminders_start_date_to_today():
    today = user_today()
    st.session_state["_reminders_start_date_today_requested"] = True
    st.session_state["reminders_start_date"] = today
    st.session_state[REMINDERS_START_DATE_INPUT_KEY] = today


# --------------------------------
# Main
# --------------------------------
if st.session_state.get("logged_in", False) and active_main_section == "Search Terms":
    render_search_terms_editor()

has_working_df = st.session_state.get("working_df") is not None
if st.session_state.get("logged_in", False):
    needs_working_df = active_main_section in {"Reminders", "Stats"}
    needs_prepared_df = active_main_section == "Stats"
    df = st.session_state["working_df"].copy() if has_working_df and needs_working_df else pd.DataFrame()
    applied_rules = get_applied_reminder_rules() if needs_working_df else {}
    prepared = (
        get_prepared_df(df, applied_rules)
        if has_working_df and needs_prepared_df
        else ensure_reminder_columns(df, applied_rules) if needs_prepared_df else pd.DataFrame()
    )

    if active_main_section == "Reminders":
        st.markdown("<div id='reminders' class='anchor-offset'></div>", unsafe_allow_html=True)
        st.markdown("## 📅 Reminders")

        sender_col, _sender_spacer = st.columns([2, 3], gap="large")
        with sender_col:
            render_sender_name_input("reminders_top")

        initialize_reminder_filter_controls(user_today())

        start_col, today_button_col, lookback_col, window_col, group_col, warning_col = st.columns([2, 0.72, 2, 2, 2, 2])
        with start_col:
            render_field_label(
                st,
                "Date",
                "Choose the anchor date to show reminders around. It defaults to today, but you can pick another date.",
                class_name="reminder-control-label",
            )
            start_date = st.date_input(
                "Date",
                key=REMINDERS_START_DATE_INPUT_KEY,
                label_visibility="collapsed",
            )
            st.session_state["reminders_start_date"] = start_date
        with today_button_col:
            st.markdown("<div class='cr-today-button-spacer'></div>", unsafe_allow_html=True)
            st.button(
                "Today",
                key="reminders_jump_to_today",
                help="Reset the reminder date to today.",
                on_click=set_reminders_start_date_to_today,
            )
        with lookback_col:
            render_field_label(
                st,
                "Days to look back",
                "0 shows the selected day only. 1 includes the selected day plus the previous day, and so on.",
                class_name="reminder-control-label",
            )
            reminder_lookback_days = st.number_input(
                "Days to look back",
                min_value=0,
                max_value=30,
                step=1,
                key="reminder_lookback_days",
                on_change=save_settings_quietly,
                label_visibility="collapsed",
            )
        with window_col:
            render_field_label(
                st,
                "Days to look ahead",
                "0 shows the selected day only. 1 includes the selected day plus the next day, and so on.",
                class_name="reminder-control-label",
            )
            reminder_window_days = st.number_input(
                "Days to look ahead",
                min_value=0,
                max_value=30,
                step=1,
                key="reminder_window_days",
                on_change=save_settings_quietly,
                label_visibility="collapsed",
            )
        with group_col:
            render_field_label(
                st,
                "Group same-client reminders",
                "Controls how many days can be combined for the same client. 0 means no grouping; 1 groups same-day reminders.",
                class_name="reminder-control-label",
            )
            group_days = st.number_input(
                "Group same-client reminders",
                min_value=0,
                step=1,
                key="client_group_days",
                on_change=save_settings_quietly,
                label_visibility="collapsed",
            )
        with warning_col:
            render_field_label(
                st,
                "Repeat warning days",
                "Warns you before preparing WhatsApp if the same client had a recent reminder. Use 0 to turn warnings off.",
                class_name="reminder-control-label",
            )
            st.number_input(
                "Repeat warning days",
                min_value=0,
                step=1,
                key="reminder_warning_days",
                on_change=save_settings_quietly,
                label_visibility="collapsed",
            )

        reminder_source_df = filter_sales_as_of_date(df, start_date)
        prepared = build_prepared_reminder_rows(reminder_source_df, applied_rules)

        # ✅ safety: if schema changed but cache is stale, rebuild
        if "BaseIntervalDays" not in prepared.columns:
            st.error("Reminders need to refresh. Rebuilding now...")
            st.session_state.pop("prepared_df", None)
            st.session_state.pop("prepared_key", None)
            # optional big hammer:
            # st.cache_data.clear()
            st.rerun()

        active_reminder_count = get_active_reminder_badge_count(today=user_today())
        render_reminders_caught_up_banner(
            active_count=active_reminder_count,
            lookback_days=reminder_lookback_days,
        )
    
        render_search_criteria_refresh_notice()
    
        lookback_start_date = start_date - timedelta(days=reminder_lookback_days)
        end_date = start_date + timedelta(days=reminder_window_days)
    
        reminder_ts = prepared.get("ReminderDateTs")
        if reminder_ts is None:
            reminder_ts = prepared.get("NextDueDateTs")
        if reminder_ts is None:
            reminder_ts = pd.to_datetime(prepared["NextDueDate"], errors="coerce")
        start_ts = pd.Timestamp(lookback_start_date)
        end_ts = pd.Timestamp(end_date)
        due2 = prepared[(reminder_ts >= start_ts) & (reminder_ts <= end_ts)].copy()
        reminders_before_exclusions = len(due2)
        due2 = apply_reminder_exclusion_filters(due2, applied_rules)
    
        if not due2.empty:
            grouped = bundle_client_reminders_by_window(due2, window_days=group_days, rules=applied_rules)
    
            render_table(grouped, f"{lookback_start_date} to {end_date}", "weekly", "weekly_message", applied_rules)
        else:
            if reminders_before_exclusions:
                st.info("All reminders in the selected date range are hidden by exclusions.")
            elif should_show_no_reminders_info(reminders_before_exclusions, active_reminder_count):
                st.info("No reminders in the selected date range.")

    if active_main_section == "Stats":
        render_stats_tab(df, prepared, applied_rules)

    if active_main_section == "Exclusions":
        # Exclusions
        # --------------------------------
        st.markdown("<div id='exclusions' class='anchor-offset'></div>", unsafe_allow_html=True)
        st.markdown("## 🚫 Exclusions")
    
        st.markdown("### Client Exclusions")
        st.caption("Hide every reminder for a specific client.")
        st.session_state.setdefault("client_exclusions", [])
        if st.session_state["client_exclusions"]:
            for client_name in sorted(st.session_state["client_exclusions"]):
                safe_client = re.sub(r'[^a-zA-Z0-9_-]', '_', client_name)
                with st.container():
                    cols = st.columns([1.4, 0.18, 6], gap="small")
                    with cols[0]:
                        st.markdown(padded_html_text(client_name), unsafe_allow_html=True)
                    with cols[1]:
                        if st.button("×", key=f"del_client_excl_{safe_client}", help="Remove client exclusion"):
                            st.session_state["client_exclusions"].remove(client_name)
                            save_settings_quietly()
                            record_settings_audit_event("exclusion_deleted", "exclusions", client_name, "client", client_name, "", "exclusions_tab")
                            st.rerun()
        else:
            st.caption("No client exclusions yet.")

        row_id = st.session_state['new_rule_counter']
        c1, c2 = st.columns([4,1], gap="small")
        with c1:
            render_field_label(
                st,
                "Add Client Exclusion",
                "Enter the client name exactly as it appears in the reminder table. All reminders for that client will be hidden."
            )
            new_client_excl = st.text_input(
                "Add Client Exclusion",
                key=f"new_client_excl_{row_id}",
                label_visibility="collapsed",
            )
        with c2:
            st.markdown("<div style='height:1.65rem;'></div>", unsafe_allow_html=True)
            if st.button("➕ Add Client", key=f"add_client_excl_{row_id}"):
                if new_client_excl and new_client_excl.strip():
                    safe_client = _SPACE_RX.sub(" ", new_client_excl.strip())
                    client_key = safe_client.lower()
                    existing_keys = {
                        _SPACE_RX.sub(" ", str(name or "").strip()).lower()
                        for name in st.session_state["client_exclusions"]
                    }
                    if client_key not in existing_keys:
                        st.session_state["client_exclusions"].append(safe_client)
                        save_settings_quietly()
                        record_settings_audit_event("exclusion_added", "exclusions", safe_client, "client", "", safe_client, "exclusions_tab")
                        st.session_state["new_rule_counter"] += 1
                        st.rerun()
                    else:
                        st.info("This client exclusion already exists.")
                else:
                    st.error("Enter a valid client name")

        st.markdown("### Patient Exclusions")
        st.caption("Hide reminders for one patient under one specific client.")
        st.session_state.setdefault("patient_exclusions", [])
        if st.session_state["patient_exclusions"]:
            sorted_patient_exclusions = sorted(
                st.session_state["patient_exclusions"],
                key=lambda item: (
                    str(item.get("client", "")).casefold() if isinstance(item, dict) else "",
                    str(item.get("patient", "")).casefold() if isinstance(item, dict) else "",
                ),
            )
            for exclusion_idx, exclusion in enumerate(sorted_patient_exclusions):
                if not isinstance(exclusion, dict):
                    continue
                client_name = _SPACE_RX.sub(" ", str(exclusion.get("client", "") or "").strip())
                patient_name = _SPACE_RX.sub(" ", str(exclusion.get("patient", "") or "").strip())
                if not client_name or not patient_name:
                    continue
                safe_pair = re.sub(r'[^a-zA-Z0-9_-]', '_', f"{client_name}_{patient_name}_{exclusion_idx}")
                with st.container():
                    cols = st.columns([1.4, 0.18, 6], gap="small")
                    with cols[0]:
                        st.markdown(patient_exclusion_label_html(client_name, patient_name), unsafe_allow_html=True)
                    with cols[1]:
                        if st.button("×", key=f"del_patient_excl_{safe_pair}", help="Remove patient exclusion"):
                            st.session_state["patient_exclusions"].remove(exclusion)
                            save_settings_quietly()
                            record_settings_audit_event("exclusion_deleted", "exclusions", f"{client_name} - {patient_name}", "patient", exclusion, "", "exclusions_tab")
                            st.rerun()
        else:
            st.caption("No patient exclusions yet.")

        pc1, pc2, pc3 = st.columns([2, 2, 1], gap="small")
        with pc1:
            render_field_label(
                st,
                "Client Name",
                "Enter the client name exactly as it appears in the reminder table."
            )
            new_patient_client = st.text_input(
                "Patient exclusion client name",
                key=f"new_patient_client_excl_{row_id}",
                label_visibility="collapsed",
            )
        with pc2:
            render_field_label(
                st,
                "Patient Name",
                "Enter the patient name exactly as it appears in the reminder table."
            )
            new_patient_name = st.text_input(
                "Patient exclusion patient name",
                key=f"new_patient_name_excl_{row_id}",
                label_visibility="collapsed",
            )
        with pc3:
            st.markdown("<div style='height:1.65rem;'></div>", unsafe_allow_html=True)
            if st.button("➕ Add Patient", key=f"add_patient_excl_{row_id}"):
                safe_client = _SPACE_RX.sub(" ", str(new_patient_client or "").strip())
                safe_patient = _SPACE_RX.sub(" ", str(new_patient_name or "").strip())
                if safe_client and safe_patient:
                    patient_key = (safe_client.lower(), safe_patient.lower())
                    existing_pairs = {
                        (
                            _SPACE_RX.sub(" ", str(item.get("client", "") or "").strip()).lower(),
                            _SPACE_RX.sub(" ", str(item.get("patient", "") or "").strip()).lower(),
                        )
                        for item in st.session_state["patient_exclusions"]
                        if isinstance(item, dict)
                    }
                    if patient_key not in existing_pairs:
                        new_patient_exclusion = {"client": safe_client, "patient": safe_patient}
                        st.session_state["patient_exclusions"].append(new_patient_exclusion)
                        save_settings_quietly()
                        record_settings_audit_event("exclusion_added", "exclusions", f"{safe_client} - {safe_patient}", "patient", "", new_patient_exclusion, "exclusions_tab")
                        st.session_state["new_rule_counter"] += 1
                        st.rerun()
                    else:
                        st.info("This patient exclusion already exists.")
                else:
                    st.error("Enter both client and patient names")

        st.markdown("### Item Exclusions")
        st.caption("Hide reminders when the item text contains a specific word or phrase.")
        if st.session_state["exclusions"]:
            for term in sorted(st.session_state["exclusions"]):
                safe_term = re.sub(r'[^a-zA-Z0-9_-]', '_', term)
                with st.container():
                    cols = st.columns([1.4, 0.18, 6], gap="small")
                    with cols[0]:
                        st.markdown(padded_html_text(term), unsafe_allow_html=True)
                    with cols[1]:
                        if st.button("×", key=f"del_excl_{safe_term}", help="Remove item exclusion"):
                            st.session_state["exclusions"].remove(term)
                            save_settings_quietly()
                            record_settings_audit_event("exclusion_deleted", "exclusions", term, "item", term, "", "exclusions_tab")
                            st.rerun()
        else:
            st.caption("No item exclusions yet.")

        row_id = st.session_state['new_rule_counter']
        c1, c2 = st.columns([4,1], gap="small")
        with c1:
            render_field_label(
                st,
                "Add Item Exclusion",
                "Enter a product, service, or wording fragment. Any reminder item containing this text will be hidden."
            )
            new_excl = st.text_input(
                "Add Item Exclusion",
                key=f"new_excl_{row_id}",
                label_visibility="collapsed",
            )
        with c2:
            st.markdown("<div style='height:1.65rem;'></div>", unsafe_allow_html=True)
            if st.button("➕ Add Item", key=f"add_excl_{row_id}"):
                if new_excl and new_excl.strip():
                    safe_term = new_excl.strip().lower()
                    if safe_term not in st.session_state["exclusions"]:
                        st.session_state["exclusions"].append(safe_term)
                        save_settings_quietly()
                        record_settings_audit_event("exclusion_added", "exclusions", safe_term, "item", "", safe_term, "exclusions_tab")
                        st.session_state["new_rule_counter"] += 1
                        st.rerun()
                    else:
                        st.info("This exclusion already exists.")
                else:
                    st.error("Enter a valid exclusion term")

        st.markdown("### Automatic Patient Death Exclusions")
        st.caption(
            "When uploaded item text contains one of these keywords, the matching client and patient are added here automatically."
        )

        st.session_state["patient_passaway_keywords"] = normalize_passaway_keywords(
            st.session_state.get("patient_passaway_keywords", PATIENT_PASSAWAY_KEYWORDS_DEFAULT)
        )
        st.session_state["automatic_patient_exclusions"] = normalize_patient_exclusions(
            st.session_state.get("automatic_patient_exclusions", [])
        )

        try:
            keyword_panel = st.container(border=True)
        except TypeError:
            keyword_panel = st.container()

        with keyword_panel:
            st.markdown(
                """
                <div class="auto-death-keyword-panel-title">Upload-check keywords</div>
                <div class="auto-death-keyword-panel-copy">These words trigger automatic patient exclusions when they appear in uploaded item text.</div>
                """,
                unsafe_allow_html=True,
            )

            if st.session_state["patient_passaway_keywords"]:
                keyword_cols = st.columns([4, 1], gap="small")
                with keyword_cols[0]:
                    st.markdown(
                        ", ".join(f"`{keyword}`" for keyword in st.session_state["patient_passaway_keywords"])
                    )
                with keyword_cols[1]:
                    if st.button(
                        "Reset keywords",
                        key=f"reset_passaway_keywords_{row_id}",
                        help="Restore the default automatic death exclusion keywords.",
                    ):
                        st.session_state["patient_passaway_keywords"] = PATIENT_PASSAWAY_KEYWORDS_DEFAULT.copy()
                        save_settings_quietly()
                        record_settings_audit_event(
                            "exclusion_keyword_reset",
                            "exclusions",
                            "automatic patient death keywords",
                            "patient_passaway_keyword",
                            "",
                            st.session_state["patient_passaway_keywords"],
                            "exclusions_tab",
                        )
                        st.rerun()
                for keyword in st.session_state["patient_passaway_keywords"]:
                    safe_keyword = re.sub(r'[^a-zA-Z0-9_-]', '_', keyword)
                    with st.container():
                        cols = st.columns([0.58, 0.18, 6.84], gap="small")
                        with cols[0]:
                            st.markdown(
                                f"<span class='auto-death-keyword-chip'>{safe_html_text(keyword)}</span>",
                                unsafe_allow_html=True,
                            )
                        with cols[1]:
                            if st.button("×", key=f"del_passaway_keyword_{safe_keyword}", help="Remove automatic keyword"):
                                st.session_state["patient_passaway_keywords"].remove(keyword)
                                save_settings_quietly()
                                record_settings_audit_event(
                                    "exclusion_keyword_deleted",
                                    "exclusions",
                                    keyword,
                                    "patient_passaway_keyword",
                                    keyword,
                                    "",
                                    "exclusions_tab",
                                )
                                st.rerun()
            else:
                st.caption("No automatic death keywords are active.")

            kw1, kw2 = st.columns([4, 1], gap="small")
            with kw1:
                render_field_label(
                    st,
                    "Add Automatic Keyword",
                    "Uploaded item names containing this word or phrase will add the matching patient to automatic exclusions."
                )
                new_passaway_keyword = st.text_input(
                    "Add Automatic Keyword",
                    key=f"new_passaway_keyword_{row_id}",
                    label_visibility="collapsed",
                )
            with kw2:
                st.markdown("<div style='height:1.65rem;'></div>", unsafe_allow_html=True)
                if st.button("➕ Add Keyword", key=f"add_passaway_keyword_{row_id}"):
                    safe_keyword = _SPACE_RX.sub(" ", str(new_passaway_keyword or "").strip()).lower()
                    if safe_keyword:
                        existing_keywords = set(st.session_state["patient_passaway_keywords"])
                        if safe_keyword not in existing_keywords:
                            st.session_state["patient_passaway_keywords"].append(safe_keyword)
                            save_settings_quietly()
                            record_settings_audit_event(
                                "exclusion_keyword_added",
                                "exclusions",
                                safe_keyword,
                                "patient_passaway_keyword",
                                "",
                                safe_keyword,
                                "exclusions_tab",
                            )
                            st.session_state["new_rule_counter"] += 1
                            st.rerun()
                        else:
                            st.info("This automatic keyword already exists.")
                    else:
                        st.error("Enter a valid keyword")

        st.markdown(
            "<div class='auto-death-patient-section-title'>Automatically added patients</div>",
            unsafe_allow_html=True,
        )
        if st.session_state["automatic_patient_exclusions"]:
            sorted_auto_exclusions = sorted(
                st.session_state["automatic_patient_exclusions"],
                key=lambda item: (
                    str(item.get("client", "")).casefold() if isinstance(item, dict) else "",
                    str(item.get("patient", "")).casefold() if isinstance(item, dict) else "",
                ),
            )
            for exclusion_idx, exclusion in enumerate(sorted_auto_exclusions):
                client_name = _SPACE_RX.sub(" ", str(exclusion.get("client", "") or "").strip())
                patient_name = _SPACE_RX.sub(" ", str(exclusion.get("patient", "") or "").strip())
                if not client_name or not patient_name:
                    continue
                safe_pair = re.sub(r'[^a-zA-Z0-9_-]', '_', f"auto_{client_name}_{patient_name}_{exclusion_idx}")
                with st.container():
                    cols = st.columns([1.4, 0.18, 6], gap="small")
                    with cols[0]:
                        st.markdown(patient_exclusion_label_html(client_name, patient_name), unsafe_allow_html=True)
                    with cols[1]:
                        if st.button("×", key=f"del_auto_patient_excl_{safe_pair}", help="Remove automatic patient exclusion"):
                            st.session_state["automatic_patient_exclusions"].remove(exclusion)
                            save_settings_quietly()
                            record_settings_audit_event(
                                "exclusion_deleted",
                                "exclusions",
                                f"{client_name} - {patient_name}",
                                "automatic_patient",
                                exclusion,
                                "",
                                "exclusions_tab",
                            )
                            st.rerun()
        else:
            st.caption("No automatic patient death exclusions yet.")

# --------------------------------
# 📊 Factoids Section (temporarily hidden)
# --------------------------------
st.session_state["factoids_unlocked"] = False

# --- Only show Factoids after unlock ---
if False and st.session_state["factoids_unlocked"]:

    # Guard: ensure the session bundle (df_full, masks, tx_client, tx_patient, patients_per_month) exists
    if "bundle" not in st.session_state:
        st.warning("Upload data first to enable Factoids.")
    else:
        df_full, masks, tx_client, tx_patient, patients_per_month = st.session_state["bundle"]
        rules_fp = _rules_fp(get_applied_reminder_rules())
        data_key = (st.session_state.get("data_version", 0), rules_fp)

        # -----------------------
        # Full-data cached builders (ghost columns precomputed via shift(12))
        # -----------------------
        @st.cache_data(show_spinner=False)
        def compute_core_metrics_full(data_key, df_full: pd.DataFrame, masks: dict, tx_client: pd.DataFrame):
            """
            Monthly clinic metrics over FULL dataset.
            Returns a DataFrame with Month (Period[M]), MonthLabel, Year, current columns,
            and Prev_<col> (t-12). NO moving-average lines here.
            """
            df = df_full
        
            # Base monthly
            g = df.groupby("Month")
            core = pd.DataFrame({
                "Total Revenue": g["Amount"].sum(),
                "Unique Clients Seen": g["ClientKey"].nunique(),
            }).reset_index()
        
            # Visit-based metrics
            vis = df.loc[masks["PATIENT_VISIT"], ["Month", "ClientKey", "AnimalKey", "DateOnly"]].dropna()
            # Consult metrics
            consult_rows = df.loc[masks["CONSULT"]].copy()
            consults_monthly = consult_rows.groupby("Month").size().rename("Number of Consults")
            consult_revenue  = consult_rows.groupby("Month")["Amount"].sum().rename("Revenue from Consult Fees")
            core = core.merge(consults_monthly, on="Month", how="left").merge(consult_revenue, on="Month", how="left")
            core[["Number of Consults", "Revenue from Consult Fees"]] = core[["Number of Consults", "Revenue from Consult Fees"]].fillna(0)

            upv = (vis.drop_duplicates(["Month", "ClientKey", "AnimalKey"])
                     .groupby("Month").size().rename("Unique Patient Visits"))
            pv  = (vis.drop_duplicates(["ClientKey", "AnimalKey", "DateOnly"])
                     .groupby("Month").size().rename("Patient Visits"))
            core = core.merge(upv, on="Month", how="left").merge(pv, on="Month", how="left").fillna(0)
        
            # Client Transactions (from blocks)
            if tx_client is not None and not tx_client.empty:
                txm = (tx_client.assign(Month=tx_client["StartDate"].dt.to_period("M"))
                                 .groupby("Month").size().rename("Client Transactions"))
                core = core.merge(txm, on="Month", how="left").fillna({"Client Transactions": 0})
            else:
                core["Client Transactions"] = 0
        
            # Flags (Deaths, Neuters)
            for key, outcol in [("DEATH", "Deaths"), ("NEUTER", "Neuters")]:
                s = df.loc[masks[key]].groupby("Month").size().rename(outcol)
                core = core.merge(s, on="Month", how="left").fillna({outcol: 0})
        
            # New Clients / New Patients (first-ever month seen)
            first_client_month = df.loc[~df["ClientKey"].isna()].groupby("ClientKey")["Month"].min()
            first_pair_month   = df.loc[~df["ClientKey"].isna() & ~df["AnimalKey"].isna()] \
                                   .groupby(["ClientKey", "AnimalKey"])["Month"].min()
        
            new_clients_monthly = first_client_month.value_counts().rename("New Clients").to_frame()
            new_clients_monthly.index.name = "Month"
            new_clients_monthly = new_clients_monthly.reset_index()
        
            new_patients_monthly = first_pair_month.value_counts().rename("New Patients").to_frame()
            new_patients_monthly.index.name = "Month"
            new_patients_monthly = new_patients_monthly.reset_index()
        
            core = core.merge(new_clients_monthly, on="Month", how="left") \
                       .merge(new_patients_monthly, on="Month", how="left") \
                       .fillna({"New Clients": 0, "New Patients": 0})
        
            # Ratios (vectorized)
            with np.errstate(divide='ignore', invalid='ignore'):
                core["Revenue per Client"]             = core["Total Revenue"] / core["Unique Clients Seen"].replace(0, np.nan)
                core["Revenue per Visiting Patient"]   = core["Total Revenue"] / core["Unique Patient Visits"].replace(0, np.nan)
                core["Revenue per Client Transaction"] = core["Total Revenue"] / core["Client Transactions"].replace(0, np.nan)
                core["Revenue per Patient Visit"]      = core["Total Revenue"] / core["Patient Visits"].replace(0, np.nan)
                core["Transactions per Client"]        = core["Client Transactions"] / core["Unique Clients Seen"].replace(0, np.nan)
                core["Visits per Patient"]             = core["Patient Visits"] / core["Unique Patient Visits"].replace(0, np.nan)
        
            core = core.fillna(0.0).sort_values("Month").reset_index(drop=True)
            core["MonthLabel"] = core["Month"].dt.strftime("%b %Y")
            core["Year"]       = core["Month"].dt.year
        
            # Ghost (prev-year) columns ready for any metric
            metric_cols = [
                "Total Revenue","Unique Clients Seen","Unique Patient Visits","Client Transactions",
                "Patient Visits","Deaths","Neuters",
                "New Clients","New Patients",
                "Revenue per Client","Revenue per Visiting Patient",
                "Revenue per Client Transaction","Revenue per Patient Visit",
                "Transactions per Client","Visits per Patient",
                "Number of Consults", "Revenue from Consult Fees"
            ]
            for col in metric_cols:
                core[f"Prev_{col}"] = core[col].shift(12)
            return core

        @st.cache_data(show_spinner=False)
        def compute_revenue_breakdown_full(data_key, df_full: pd.DataFrame, masks: dict):
            """
            Monthly revenue breakdown over FULL dataset with % of total and Prev_<col>.
            """
            total = df_full.groupby("Month")["Amount"].sum()
            out = pd.DataFrame({"Total": total})
        
            def add(label, key):
                out[label] = df_full.loc[masks[key]].groupby("Month")["Amount"].sum()
        
            # --- Revenue categories ---
            add("Revenue from Boarding", "BOARDING")
            add("Revenue from Consult Fees", "CONSULT")
            add("Revenue from Flea/Worm",    "FLEA_WORM")
            add("Revenue from Grooms, Ears & Nails", "GROOMING")
            add("Revenue from Food",         "FOOD")
            add("Revenue from Lab Work",     "LABWORK")
            add("Revenue from Neuters",      "NEUTER")
            add("Revenue from Non-consult Fees", "FEE")
            add("Revenue from Ultrasounds",  "ULTRASOUND")
            add("Revenue from X-rays",       "XRAY")
        
            # --- Clean & sort ---
            out = out.fillna(0.0).sort_values("Month").reset_index()
        
            # --- Percent-of-total columns ---
            for suff in [
                "Boarding",
                "Consult Fees",
                "Flea/Worm",
                "Food",
                "Grooms, Ears & Nails",
                "Lab Work",
                "Neuters",
                "Non-consult Fees",
                "Ultrasounds",
                "X-rays",
            ]:

                num = out[f"Revenue from {suff}"]
                den = out["Total"].replace(0, np.nan)
                out[f"Revenue from {suff} (% of total)"] = (num / den).fillna(0.0)
        
            # --- Previous-year ghost columns ---
            for col in [c for c in out.columns if c not in ("Month", "Total")]:
                out[f"Prev_{col}"] = out[col].shift(12)
        
            # --- Labels for charts ---
            out["MonthLabel"] = out["Month"].dt.strftime("%b %Y")
            out["Year"]       = out["Month"].dt.year
        
            return out

        @st.cache_data(show_spinner=False)
        def compute_patient_breakdown_pct_full(
            data_key, df_full: pd.DataFrame, masks: dict, tx_client: pd.DataFrame, patients_per_month: pd.Series
        ):
            """
            Returns a dict of { category_name: DataFrame[Month, Percent, UniquePatients, TotalPatientsMonth, PrevPercent, MonthLabel, Year] }.
            Self-heals required columns if missing (ChargeDate, ClientKey, Block).
            """
            out = {}
            if df_full is None or df_full.empty:
                return out
        
            # ---- SAFETY: ensure required columns exist on df_full ----
            df = df_full.copy()
        
            # ChargeDate
            if "ChargeDate" not in df.columns or not pd.api.types.is_datetime64_any_dtype(df["ChargeDate"]):
                df["ChargeDate"] = pd.to_datetime(df.get("ChargeDate"), errors="coerce")
        
            # DateOnly / Month (cheap if already there)
            if "DateOnly" not in df.columns:
                df["DateOnly"] = df["ChargeDate"].dt.normalize()
            if "Month" not in df.columns:
                df["Month"] = df["ChargeDate"].dt.to_period("M")
        
            # ClientKey/AnimalKey
            if "ClientKey" not in df.columns:
                df["ClientKey"] = normalize_key_series(df.get("Client Name"), index=df.index)
            if "AnimalKey" not in df.columns:
                df["AnimalKey"] = normalize_key_series(df.get("Animal Name"), index=df.index)
        
            # Block (recompute if missing)
            if "Block" not in df.columns:
                df_tmp = df.sort_values(["ClientKey", "DateOnly"])
                dd  = df_tmp.groupby("ClientKey", dropna=False)["DateOnly"].diff().dt.days.fillna(1)
                blk = (dd > 1).groupby(df_tmp["ClientKey"], dropna=False).cumsum()
                df_tmp["Block"] = blk
                df = df.join(df_tmp[["Block"]])  # align by index
        
            # Helper: compute one category
            def one_category(mask: pd.Series):
                # pick only rows that match the category AND have necessary fields
                cols_needed = ["ClientKey","Block","ChargeDate"]
                missing = [c for c in cols_needed if c not in df.columns]
                if missing:
                    # If we still somehow miss columns, bail gracefully
                    return pd.DataFrame(columns=["Month","Percent","UniquePatients","TotalPatientsMonth","PrevPercent","MonthLabel","Year"])
        
                service_rows = df.loc[mask, ["ClientKey", "Block", "ChargeDate"]].drop_duplicates()
                if service_rows.empty:
                    return pd.DataFrame(columns=["Month","Percent","UniquePatients","TotalPatientsMonth","PrevPercent","MonthLabel","Year"])
        
                # tx_client alignment (it should be built from the same bundle; still guard)
                if tx_client is None or tx_client.empty:
                    return pd.DataFrame(columns=["Month","Percent","UniquePatients","TotalPatientsMonth","PrevPercent","MonthLabel","Year"])
        
                tx = tx_client.copy()
                tx["Month"] = tx["StartDate"].dt.to_period("M")
        
                qualifying = service_rows.merge(
                    tx[["ClientKey","Block","Patients","StartDate"]],
                    on=["ClientKey","Block"], how="left"
                )
                qualifying["Month"] = qualifying["ChargeDate"].dt.to_period("M")
        
                monthly = (
                    qualifying.groupby("Month")["Patients"]
                              .apply(lambda p: len(set().union(*p)) if len(p) and isinstance(p.iloc[0], (set, list)) else 0)
                              .rename("UniquePatients")
                              .to_frame()
                              .reset_index()
                )
        
                # denominator from patients_per_month (fallback if empty)
                ppm = patients_per_month if patients_per_month is not None else df.groupby("Month")["AnimalKey"].nunique()
                monthly["TotalPatientsMonth"] = monthly["Month"].map(ppm).fillna(0).astype(int)
        
                with np.errstate(divide='ignore', invalid='ignore'):
                    monthly["Percent"] = (monthly["UniquePatients"] / monthly["TotalPatientsMonth"]).fillna(0.0)
        
                monthly = monthly.sort_values("Month")
                monthly["PrevPercent"] = monthly["Percent"].shift(12)
                monthly["MonthLabel"]  = monthly["Month"].dt.strftime("%b %Y")
                monthly["Year"]        = monthly["Month"].dt.year
                return monthly
        
            categories = {
                "Anaesthetics": "ANAESTHETIC",
                "Boarding": "BOARDING",
                "Consults": "CONSULT",
                "Dentals": "DENTAL",
                "Flea/Worm Treatments": "FLEA_WORM",
                "Food Purchases": "FOOD",
                "Grooms, Ears & Nails": "GROOMING",
                "Hospitalisations": "HOSPITAL",
                "Lab Work": "LABWORK",
                "Neuters": "NEUTER",
                "Ultrasounds": "ULTRASOUND",
                "Vaccinations": "VACCINE",
                "X-rays": "XRAY",
            }

        
            for label, key in categories.items():
                # Ensure the mask aligns to df's index
                mask = masks[key].reindex(df.index, fill_value=False) if key in masks else pd.Series(False, index=df.index)
                out[label] = one_category(mask)
        
            return out


        # ============================
        # 📈 Monthly Charts (with Previous-Year Ghost Bars)
        # ============================
        st.markdown("<div id='factoids-monthlycharts' class='anchor-offset'></div>", unsafe_allow_html=True)
        st.markdown("### 📈 Monthly Charts")

        # Build full frames once
        core_all = compute_core_metrics_full(data_key, df_full, masks, tx_client)

        if not core_all.empty:
            last_m   = core_all["Month"].max()
            current_12 = pd.period_range(last_m - 11, last_m, freq="M")
            core_win  = core_all[core_all["Month"].isin(current_12)].copy()
            
            # ---------------------------
            # Chart 1: Revenue & Transactions (bars only — current + ghost)
            # ---------------------------
            st.markdown(
                "<h4 style='font-size:17px;font-weight:700;color:var(--cr-muted);margin-top:1rem;margin-bottom:0.4rem;'>💰 Revenue & Transactions</h4>",
                unsafe_allow_html=True
            )
            
            metric_list_rev_tx = [
                "Total Revenue", "Revenue per Client", "Revenue per Visiting Patient",
                "Revenue per Client Transaction", "Revenue per Patient Visit",
                "Transactions per Client","Number of Consults"
            ]
            sel_core_rev = st.selectbox(
                "Select Metric (Revenue & Transactions):",
                metric_list_rev_tx,
                index=0,
                key="core_metric_revtx"
            )
            
            # Full-data, cached monthly metrics (w/ Prev_ cols)
            core_all = compute_core_metrics_full(data_key, df_full, masks, tx_client)
            if not core_all.empty:
                last_m    = core_all["Month"].max()
                current_12 = pd.period_range(last_m - 11, last_m, freq="M")
                core_win  = core_all[core_all["Month"].isin(current_12)].copy()
            
                safe_col = re.sub(r"[^A-Za-z0-9_]", "_", sel_core_rev)
                df_plot = core_win[["Month","MonthLabel", sel_core_rev, f"Prev_{sel_core_rev}"]].copy()
                df_plot = df_plot.rename(columns={sel_core_rev:"Cur", f"Prev_{sel_core_rev}":"Prev"})
                df_plot["has_ghost"] = df_plot["Prev"].notna()
                df_plot["MonthOnly"] = df_plot["MonthLabel"].str.split().str[0]
            
                palette = [
                    "#fb7185", "#60a5fa", "#4ade80", "#facc15",
                    "#f97316", "#fbbf24", "#a5b4fc", "#22d3ee", "#93c5fd",
                ]
                color = palette[metric_list_rev_tx.index(sel_core_rev) % len(palette)]
                y_fmt = ",.2f" if "Transactions per" in sel_core_rev else ",.0f"
            
                ghost = (
                    alt.Chart(df_plot)
                    .transform_filter("datum.Prev != null")
                    .mark_bar(size=20, color=color, opacity=0.3, xOffset=-25)
                    .encode(
                        x=alt.X("MonthLabel:N", sort=df_plot["MonthLabel"].tolist(),
                                axis=alt.Axis(title=None, labelAngle=45, labelFontSize=12, labelOffset=-15)),
                        y=alt.Y("Prev:Q", title=sel_core_rev, axis=alt.Axis(format=y_fmt)),
                        tooltip=[
                            alt.Tooltip("MonthOnly:N", title="Month"),
                            alt.Tooltip("Prev:Q", title=f"Prev {sel_core_rev}", format=y_fmt),
                        ],
                    )
                )
            
                current = (
                    alt.Chart(df_plot)
                    .mark_bar(size=20, color=color)
                    .encode(
                        x=alt.X("MonthLabel:N", sort=df_plot["MonthLabel"].tolist(),
                                axis=alt.Axis(title=None, labelAngle=45, labelFontSize=12, labelOffset=-15)),
                        y=alt.Y("Cur:Q", title=sel_core_rev, axis=alt.Axis(format=y_fmt)),
                        tooltip=[
                            alt.Tooltip("MonthOnly:N", title="Month"),
                            alt.Tooltip("Cur:Q", title=sel_core_rev, format=y_fmt),
                        ],
                    )
                    .transform_calculate(xOffset="datum.has_ghost ? 25 : 0")
                )
            
                chart_rev_tx = (
                    alt.layer(ghost, current)
                    .resolve_scale(y="shared")
                    .properties(
                        height=400, width=700,
                        title=f"{sel_core_rev} per Month (with previous-year ghost bars)"
                    )
                )
                st.altair_chart(chart_rev_tx, use_container_width=True)
            else:
                st.info("No data for this chart.")

            # ---------------------------
            # Chart 2: Clients & Patients (bars only — current + ghost)
            # ---------------------------
            st.markdown(
                "<h4 style='font-size:17px;font-weight:700;color:var(--cr-muted);margin-top:1rem;margin-bottom:0.4rem;'>👥 Clients & Patients</h4>",
                unsafe_allow_html=True
            )
            
            metric_list_cp = [
                "Unique Clients Seen", "Unique Patient Visits",
                "Client Transactions", "Patient Visits",
                "Visits per Patient",
                "New Clients", "New Patients",
                "Deaths", "Neuters"
            ]
            sel_core_cp = st.selectbox(
                "Select Metric (Clients & Patients):",
                metric_list_cp,
                index=0,
                key="core_metric_clientspatients"
            )
            
            core_all = compute_core_metrics_full(data_key, df_full, masks, tx_client)
            if not core_all.empty:
                last_m    = core_all["Month"].max()
                current_12 = pd.period_range(last_m - 11, last_m, freq="M")
                core_win  = core_all[core_all["Month"].isin(current_12)].copy()
            
                safe_col = re.sub(r"[^A-Za-z0-9_]", "_", sel_core_cp)
                df_plot = core_win[["Month","MonthLabel", sel_core_cp, f"Prev_{sel_core_cp}"]].copy()
                df_plot = df_plot.rename(columns={sel_core_cp:"Cur", f"Prev_{sel_core_cp}":"Prev"})
                df_plot["has_ghost"] = df_plot["Prev"].notna()
                df_plot["MonthOnly"] = df_plot["MonthLabel"].str.split().str[0]
            
                palette = [
                    "#f97316", "#fbbf24", "#a5b4fc", "#22d3ee", "#93c5fd",
                    "#fb7185", "#60a5fa", "#4ade80", "#facc15",
                ]
                color = palette[metric_list_cp.index(sel_core_cp) % len(palette)]
                y_fmt = ",.0f" if sel_core_cp not in ("Visits per Patient",) else ",.2f"
            
                ghost_cp = (
                    alt.Chart(df_plot)
                    .transform_filter("datum.Prev != null")
                    .mark_bar(size=20, color=color, opacity=0.3, xOffset=-25)
                    .encode(
                        x=alt.X("MonthLabel:N", sort=df_plot["MonthLabel"].tolist(),
                                axis=alt.Axis(title=None, labelAngle=45, labelFontSize=12, labelOffset=-15)),
                        y=alt.Y("Prev:Q", title=sel_core_cp, axis=alt.Axis(format=y_fmt)),
                        tooltip=[
                            alt.Tooltip("MonthOnly:N", title="Month"),
                            alt.Tooltip("Prev:Q", title=f"Prev {sel_core_cp}", format=y_fmt),
                        ],
                    )
                )
            
                current_cp = (
                    alt.Chart(df_plot)
                    .mark_bar(size=20, color=color)
                    .encode(
                        x=alt.X("MonthLabel:N", sort=df_plot["MonthLabel"].tolist(),
                                axis=alt.Axis(title=None, labelAngle=45, labelFontSize=12, labelOffset=-15)),
                        y=alt.Y("Cur:Q", title=sel_core_cp, axis=alt.Axis(format=y_fmt)),
                        tooltip=[
                            alt.Tooltip("MonthOnly:N", title="Month"),
                            alt.Tooltip("Cur:Q", title=sel_core_cp, format=y_fmt),
                        ],
                    )
                    .transform_calculate(xOffset="datum.has_ghost ? 25 : 0")
                )
            
                chart_cp = (
                    alt.layer(ghost_cp, current_cp)
                    .resolve_scale(y="shared")
                    .properties(
                        height=400, width=700,
                        title=f"{sel_core_cp} per Month (with previous-year ghost bars)"
                    )
                )
                st.altair_chart(chart_cp, use_container_width=True)
            else:
                st.info("No data for this chart.")

        # ============================
        # Chart 3: 💵 Revenue Breakdown by Month
        # ============================
        st.markdown(
            "<h4 style='font-size:17px;font-weight:700;color:var(--cr-muted);margin-top:1rem;margin-bottom:0.4rem;'>💵 Revenue Breakdown by Month</h4>",
            unsafe_allow_html=True
        )

        rev_all = compute_revenue_breakdown_full(data_key, df_full, masks)
        if not rev_all.empty:
            last_m  = rev_all["Month"].max()
            current_12 = pd.period_range(last_m - 11, last_m, freq="M")
            rev_win = rev_all[rev_all["Month"].isin(current_12)].copy()

            metrics = [
                "Revenue from Boarding",
                "Revenue from Boarding (% of total)",
                "Revenue from Consult Fees",
                "Revenue from Consult Fees (% of total)",
                "Revenue from Flea/Worm",
                "Revenue from Flea/Worm (% of total)",
                "Revenue from Food",
                "Revenue from Food (% of total)",
                "Revenue from Grooms, Ears & Nails",
                "Revenue from Grooms, Ears & Nails (% of total)",
                "Revenue from Lab Work",
                "Revenue from Lab Work (% of total)",
                "Revenue from Neuters",
                "Revenue from Neuters (% of total)",
                "Revenue from Non-consult Fees",
                "Revenue from Non-consult Fees (% of total)",
                "Revenue from Ultrasounds",
                "Revenue from Ultrasounds (% of total)",
                "Revenue from X-rays",
                "Revenue from X-rays (% of total)",
            ]

            sel = st.selectbox("Select Revenue Metric:", metrics, index=0, key="rev_breakdown_metric")

            palette = [
                "#4ade80", "#facc15", "#fbbf24", "#a5b4fc", "#93c5fd",
                "#fb7185", "#60a5fa", "#f97316", "#fbbf24", "#a5b4fc"
            ]
            color = palette[metrics.index(sel) % len(palette)]

            is_pct  = "(% of total)" in sel
            y_fmt   = ".1%" if is_pct else ",.0f"
            y_title = "% of Total" if is_pct else "Revenue (AED)"

            df_plot = rev_win[["MonthLabel", sel, f"Prev_{sel}"]].rename(columns={sel:"Cur", f"Prev_{sel}":"Prev"}).copy()
            df_plot["has_ghost"] = df_plot["Prev"].notna()

            ghost = (
                alt.Chart(df_plot)
                .transform_filter("datum.Prev != null")
                .mark_bar(size=20, color=color, opacity=0.3, xOffset=-25)
                .encode(
                    x=alt.X("MonthLabel:N", sort=df_plot["MonthLabel"].tolist(),
                            axis=alt.Axis(title=None, labelAngle=45, labelFontSize=12, labelOffset=-15)),
                    y=alt.Y("Prev:Q", title=y_title, axis=alt.Axis(format=y_fmt)),
                    tooltip=[alt.Tooltip("MonthLabel:N", title="Month"),
                             alt.Tooltip("Prev:Q", title=y_title, format=y_fmt)],
                )
            )

            current = (
                alt.Chart(df_plot)
                .mark_bar(size=20, color=color)
                .encode(
                    x=alt.X("MonthLabel:N", sort=df_plot["MonthLabel"].tolist(),
                            axis=alt.Axis(title=None, labelAngle=45, labelFontSize=12, labelOffset=-15)),
                    y=alt.Y("Cur:Q", title=y_title, axis=alt.Axis(format=y_fmt)),
                    tooltip=[alt.Tooltip("MonthLabel:N", title="Month"),
                             alt.Tooltip("Cur:Q", title=y_title, format=y_fmt)],
                )
                .transform_calculate(xOffset="datum.has_ghost ? 25 : 0")
            )

            if df_plot[["Cur", "Prev"]].fillna(0).sum().sum() == 0:
                # Show only a centered text chart if no data
                chart = alt.Chart(pd.DataFrame([{"label": "No data available for this metric"}])).mark_text(
                    align="center", baseline="middle", fontSize=18, color="gray"
                ).encode(text="label:N").properties(height=300, width=700)
            else:
                chart = (
                    alt.layer(ghost, current)
                    .resolve_scale(y="shared")
                    .properties(height=400, width=700, title=f"{sel} by Month (with previous-year ghost bars)")
                )
            
            st.altair_chart(chart, use_container_width=True)

        else:
            st.info("No data available for revenue breakdown.")

        # ============================
        # Chart 4: ⭐ Patient Breakdown %'s
        # ============================
        st.markdown(
            "<h4 style='font-size:17px;font-weight:700;color:var(--cr-muted);margin-top:1rem;margin-bottom:0.4rem;'>⭐ Patient Breakdown %'s</h4>",
            unsafe_allow_html=True
        )

        pct_all = compute_patient_breakdown_pct_full(data_key, df_full, masks, tx_client, patients_per_month)

        options = [
            "Anaesthetics",
            "Boarding",
            "Consults",                        
            "Dentals",
            "Flea/Worm Treatments",
            "Food Purchases",
            "Grooms, Ears & Nails",
            "Hospitalisations",
            "Lab Work",
            "Neuters",
            "Ultrasounds",
            "Vaccinations",
            "X-rays",
        ]

        choice = st.selectbox("Select a metric:", sorted(options), index=0, key="factoid_metric")

        monthly = pct_all.get(choice, pd.DataFrame())
        if monthly.empty:
            st.info(f"No qualifying {choice.lower()} data found.")
        else:
            last_m = monthly["Month"].max()
            month_range = pd.period_range(last_m - 11, last_m, freq="M")
            monthly_win = monthly[monthly["Month"].isin(month_range)].copy()

            color_map = {
                "Anaesthetics": "#fb7185",
                "Boarding": "#8b5cf6",
                "Consults": "#0ea5e9",       
                "Dentals": "#60a5fa",
                "Flea/Worm Treatments": "#4ade80",
                "Food Purchases": "#facc15",
                "Grooms, Ears & Nails": "#d946ef",  
                "Hospitalisations": "#f97316",
                "Lab Work": "#fbbf24",
                "Neuters": "#14b8a6",
                "Ultrasounds": "#a5b4fc",
                "Vaccinations": "#22d3ee",
                "X-rays": "#93c5fd",
            }

            color = color_map.get(choice, "#60a5fa")

            merged = monthly_win[["MonthLabel","Year","Percent","PrevPercent","UniquePatients","TotalPatientsMonth"]].copy()
            merged["has_ghost"] = merged["PrevPercent"].notna()
            merged["MonthOnly"] = merged["MonthLabel"].str.split().str[0]

            ghost = (
                alt.Chart(merged)
                .transform_filter("datum.PrevPercent != null")
                .mark_bar(size=20, color=color, opacity=0.3, xOffset=-25)
                .encode(
                    x=alt.X(
                        "MonthLabel:N",
                        sort=merged["MonthLabel"].tolist(),
                        axis=alt.Axis(title=None, labelAngle=45, labelFontSize=12, labelOffset=-15)
                    ),
                    y=alt.Y("PrevPercent:Q", title="% Patients", axis=alt.Axis(format=".1%")),
                    tooltip=[
                        alt.Tooltip("MonthOnly:N", title="Month"),
                        alt.Tooltip("PrevPercent:Q", title="%", format=".1%"),
                        alt.Tooltip("TotalPatientsMonth:Q", title="Monthly Patients", format=",.0f"),
                        alt.Tooltip("UniquePatients:Q", title=f"{choice} Patients", format=",.0f"),
                    ],
                )
            )

            current = (
                alt.Chart(merged)
                .mark_bar(size=20, color=color)
                .encode(
                    x=alt.X(
                        "MonthLabel:N",
                        sort=merged["MonthLabel"].tolist(),
                        axis=alt.Axis(title=None, labelAngle=45, labelFontSize=12, labelOffset=-15)
                    ),
                    y=alt.Y("Percent:Q", title="% Patients", axis=alt.Axis(format=".1%")),
                    tooltip=[
                        alt.Tooltip("MonthOnly:N", title="Month"),
                        alt.Tooltip("Percent:Q", title="%", format=".1%"),
                        alt.Tooltip("TotalPatientsMonth:Q", title="Monthly Patients", format=",.0f"),
                        alt.Tooltip("UniquePatients:Q", title=f"{choice} Patients", format=",.0f"),
                    ],
                )
                .transform_calculate(xOffset="datum.has_ghost ? 25 : 0")
            )

            chart = (
                alt.layer(ghost, current)
                .resolve_scale(y="shared")
                .properties(
                    height=400, width=700,
                    title=f"% of Monthly Patients Having {choice} (with previous-year ghost bars)"
                )
            )
            st.altair_chart(chart, use_container_width=True)

        # ============================
        # 📌 At a Glance (optimized, full code)
        # ============================
        st.markdown("---")
        st.markdown("<div id='factoids-ataglance' class='anchor-offset'></div>", unsafe_allow_html=True)
        st.markdown("### 📌 At a Glance")
        
        # ---- Guard: need the prepared session bundle ----
        if "bundle" not in st.session_state:
            st.warning("Upload data first to enable At a Glance.")
        else:
            df_full, masks, tx_client_full, tx_patient_full, patients_per_month_full = st.session_state["bundle"]
        
            # --- Select Period Dropdown ---
            st.markdown("#### 🕒 Select Period")
            period_options = ["All Data", "Prev 30 Days", "Prev 3 Months", "Prev 12 Months", "YTD"]
            selected_period = st.selectbox("Select Period:", period_options, index=0, label_visibility="collapsed")
        
            # --- Determine latest and earliest available dates using precomputed df_full ---
            latest_date   = pd.to_datetime(df_full["ChargeDate"], errors="coerce").max()
            earliest_date = pd.to_datetime(df_full["ChargeDate"], errors="coerce").min()
            if pd.isna(latest_date):
                latest_date = pd.Timestamp(user_today())
            if pd.isna(earliest_date):
                earliest_date = latest_date - pd.DateOffset(years=1)
        
            # --- Build period slice on df_full (cheap) ---
            df_period = df_full
            if selected_period == "Prev 30 Days":
                start_date = latest_date - pd.Timedelta(days=30)
                df_period = df_full[df_full["ChargeDate"] >= start_date]
                period_label = f"Prev 30 Days from {latest_date.strftime('%d %b %Y')}"
            elif selected_period == "Prev 3 Months":
                start_date = latest_date - pd.DateOffset(months=3)
                df_period = df_full[df_full["ChargeDate"] >= start_date]
                period_label = f"Prev 3 Months from {latest_date.strftime('%d %b %Y')}"
            elif selected_period == "Prev 12 Months":
                start_date = latest_date - pd.DateOffset(months=12)
                df_period = df_full[df_full["ChargeDate"] >= start_date]
                period_label = f"Prev 12 Months from {latest_date.strftime('%d %b %Y')}"
            elif selected_period == "YTD":
                start_date = pd.Timestamp(year=latest_date.year, month=1, day=1)
                df_period = df_full[df_full["ChargeDate"] >= start_date]
                period_label = f"YTD: {start_date.strftime('%d %b %Y')} → {latest_date.strftime('%d %b %Y')}"
            else:  # "All Data"
                start_date = earliest_date
                df_period = df_full
                period_label = f"All Data: {earliest_date.strftime('%d %b %Y')} → {latest_date.strftime('%d %b %Y')}"
        
            # --- Slice transactions strictly to the selected period ---
            tx_client = tx_client_full[
                (tx_client_full["StartDate"] >= start_date) &
                (tx_client_full["StartDate"] <= latest_date)
            ].copy()
            
            tx_patient = tx_patient_full[
                (tx_patient_full["StartDate"] >= start_date) &
                (tx_patient_full["StartDate"] <= latest_date)
            ].copy()

            # --- Helpers ---
            BAD_TERMS = ["counter", "walk", "cash", "test", "in-house", "in house"]
        
            def _norm_for_pairs(s: pd.Series) -> pd.Series:
                return normalize_key_series(s, index=getattr(s, "index", None))
        
            metrics = {}
        
            # -------------------------
            # Daily aggregates (Client transactions + Patient visits) — on period slice
            # -------------------------
            if not tx_client.empty:
                daily_tx = (
                    tx_client.groupby("StartDate")
                    .agg(
                        ClientTx=("Block", "count"),
                        Patients=("Patients", lambda p: len(set().union(*p)) if len(p) else 0),
                    )
                    .reset_index()
                    .sort_values("StartDate")
                )
                if not daily_tx.empty:
                    # limit to actual days in the selected window
                    num_days = max(1, (latest_date - start_date).days + 1)
                    max_tx_row = daily_tx.loc[daily_tx["ClientTx"].idxmax()]
                    metrics["Max Client Transactions"] = (
                        f"{int(max_tx_row['ClientTx']):,} ({max_tx_row['StartDate'].strftime('%d %b %Y')})"
                    )
                    metrics["Avg Client Transactions/Day"] = f"{tx_client.shape[0] / num_days:.1f}"

            # Patient visit daily metrics (distinct client+animal+day) using VisitFlag already in df_full
            vis = df_period.loc[df_period["VisitFlag"], ["ClientKey","AnimalKey","DateOnly"]].dropna()
            daily_visits = (
                vis.drop_duplicates(["ClientKey","AnimalKey","DateOnly"])
                   .groupby("DateOnly").size().reset_index(name="PatientVisits")
            )
            if not daily_visits.empty:
                num_days = max(1, (latest_date - start_date).days + 1)
                max_visit_row = daily_visits.loc[daily_visits["PatientVisits"].idxmax()]
                metrics["Max Patient Visits"] = (
                    f"{int(max_visit_row['PatientVisits']):,} ({max_visit_row['DateOnly'].strftime('%d %b %Y')})"
                )
                metrics["Avg Patient Visits/Day"] = f"{daily_visits['PatientVisits'].sum() / num_days:.1f}"

            # -------------------------
            # Total Unique Patients (distinct ClientKey+AnimalKey) — exclude BAD_TERMS
            # -------------------------
            df_pairs = (
                df_period[["Client Name","Animal Name","ClientKey","AnimalKey"]]
                .dropna(subset=["ClientKey","AnimalKey"])
                .copy()
            )
            if BAD_TERMS:
                bad_rx = "|".join(map(re.escape, BAD_TERMS))
                df_pairs = df_pairs[~df_pairs["ClientKey"].str.contains(bad_rx, case=False, na=False)]
            total_unique_patients = df_pairs.drop_duplicates(subset=["ClientKey","AnimalKey"]).shape[0]
            metrics["Total Unique Patients"] = f"{total_unique_patients:,}"
        
            # -------------------------
            # Patient Breakdown (Unique pairs per service) using precomputed masks
            # -------------------------
            # Map: label -> mask key
            pb_map = {
                "Anaesthetics": "ANAESTHETIC",
                "Boarding": "BOARDING",
                "Consults": "CONSULT",       
                "Dentals": "DENTAL",
                "Flea/Worm": "FLEA_WORM",
                "Food": "FOOD",
                "Grooms, Ears & Nails": "GROOMING",
                "Hospitalisations": "HOSPITAL",
                "Lab Work": "LABWORK",
                "Neuters": "NEUTER",
                "Ultrasounds": "ULTRASOUND",
                "Vaccinations": "VACCINE",
                "X-rays": "XRAY",
            }
        
            for label, key in pb_map.items():
                mask_series = masks[key].reindex(df_period.index, fill_value=False)
                subset = df_period.loc[mask_series, ["ClientKey","AnimalKey","Client Name","Animal Name"]]
                if not subset.empty:
                    # remove BAD_TERMS clients
                    if BAD_TERMS:
                        subset = subset[~subset["ClientKey"].str.contains(bad_rx, case=False, na=False)]
                    count = subset.drop_duplicates(subset=["ClientKey","AnimalKey"]).shape[0]
                    if total_unique_patients > 0:
                        metrics[f"Unique Patients Having {label}"] = f"{count:,} ({count/total_unique_patients:.1%})"
        
            # -------------------------
            # Client Transaction Histogram (by active days/blocks)
            # -------------------------
            # Approximate "transactions" per client = number of StartDate days per ClientKey in period
            if not tx_client.empty:
                tx_per_client = (tx_client.groupby("ClientKey")["StartDate"].nunique()).rename("TxDays")
                total_clients = int(tx_per_client.shape[0])
            else:
                tx_per_client = pd.Series(dtype=int)
                total_clients = 0
        
            if total_clients > 0:
                hist = {
                    "Clients with 1 Transaction":       int((tx_per_client == 1).sum()),
                    "Clients with 2 Transactions":      int((tx_per_client == 2).sum()),
                    "Clients with 3–5 Transactions":    int(((tx_per_client >= 3) & (tx_per_client <= 5)).sum()),
                    "Clients with 6+ Transactions":     int((tx_per_client >= 6).sum()),
                }
                for k, v in hist.items():
                    metrics[k] = f"{v:,} ({v/total_clients:.1%})"
        
            # -------------------------
            # 🎉 Fun Facts
            # -------------------------
            if not df_pairs.empty:
                # Build a stable client identifier for uniqueness
                # Prefer Xpress "Client ID" if available; else fall back to normalized ClientKey
                if "Client ID" in df_period.columns:
                    client_uid = (
                        df_period["Client ID"]
                        .astype(str).str.normalize("NFKC").str.strip().str.lower()
                    )
                else:
                    client_uid = df_period["ClientKey"].astype(str)
            
                # Build a compact frame for uniqueness by (client, animal name)
                animals = pd.DataFrame({
                    "ClientUID": client_uid.values,
                    "AnimalKey": (
                        df_period["AnimalKey"]
                        .astype(str).str.normalize("NFKC").str.strip()
                        .values
                    ),
                })
            
                # Remove blanks / obvious non-pet names
                BAD_PET_NAMES = {
                    "", "reception", "counter", "walk", "walk in", "walk-in", "walkin",
                    "cash", "test", "n/a", "na", "-", "--", "unknown", "nan","dog","cat"
                }
                animals = animals[animals["AnimalKey"].str.contains(r"[A-Za-z]", na=False)]
                animals = animals[~animals["AnimalKey"].str.lower().isin(BAD_PET_NAMES)]
            
                # ✅ De-duplicate to true unique animals (client + animal name)
                unique_animals = animals.drop_duplicates(subset=["ClientUID", "AnimalKey"])
            
                # Count most common pet names across unique animals
                pet_counts = (
                    unique_animals.groupby("AnimalKey").size()
                    .reset_index(name="Count")
                    .sort_values("Count", ascending=False)
                    .reset_index(drop=True)
                )
            
                if not pet_counts.empty:
                    top_name  = str(pet_counts.iloc[0]["AnimalKey"]).title()
                    top_count = int(pet_counts.iloc[0]["Count"])
                    metrics["Most Common Pet Name"] = f"{top_name} ({top_count:,})"


            # Patient with Most Visits (merge-close-days approach)
            if not vis.empty:
                # For each (ClientKey, AnimalKey), count visits after merging consecutive days within 1-day window
                def merge_close_visits(dates: pd.Series) -> int:
                    dates = dates.sort_values().dropna().reset_index(drop=True)
                    if dates.empty:
                        return 0
                    cnt, last = 1, dates.iloc[0]
                    for d in dates.iloc[1:]:
                        if (d - last).days > 1:
                            cnt += 1
                        last = d
                    return cnt
        
                visits_count = (
                    vis.groupby(["ClientKey","AnimalKey"])["DateOnly"]
                       .apply(merge_close_visits)
                       .reset_index(name="VisitCount")
                       .sort_values("VisitCount", ascending=False)
                )
                if not visits_count.empty:
                    top = visits_count.iloc[0]
                    # Find display names from df_period
                    one_client = df_period.loc[df_period["ClientKey"] == top["ClientKey"], "Client Name"]
                    one_animal = df_period.loc[df_period["AnimalKey"] == top["AnimalKey"], "Animal Name"]
                    client_disp = one_client.iloc[0].strip() if not one_client.empty else str(top["ClientKey"]).title()
                    animal_disp = one_animal.iloc[0].strip() if not one_animal.empty else str(top["AnimalKey"]).title()
                    metrics["Patient with Most Visits"] = f"{animal_disp} ({client_disp}) – {int(top['VisitCount']):,}"
        
            # -------------------------
            # Aggregate KPIs over period
            # -------------------------
            total_revenue   = float(df_period["Amount"].sum())
            unique_clients  = int(df_period["ClientKey"].nunique())
            unique_pairs    = int(df_pairs.drop_duplicates(subset=["ClientKey","AnimalKey"]).shape[0])
        
            # Client & patient transactions over period
            client_transactions  = int(tx_client.shape[0]) if not tx_client.empty else 0
            # Patient visits (distinct client+animal+day)
            patient_visits = int(vis.drop_duplicates(["ClientKey","AnimalKey","DateOnly"]).shape[0]) if not vis.empty else 0
            # Unique visiting patients in period
            unique_patient_visits = int(vis.drop_duplicates(["ClientKey","AnimalKey"]).shape[0]) if not vis.empty else 0
        
            # Ratios
            rev_per_client             = (total_revenue / unique_clients) if unique_clients else 0.0
            rev_per_visiting_patient   = (total_revenue / unique_patient_visits) if unique_patient_visits else 0.0
            rev_per_client_tx          = (total_revenue / client_transactions) if client_transactions else 0.0
            rev_per_patient_visit      = (total_revenue / patient_visits) if patient_visits else 0.0
            tx_per_client              = (client_transactions / unique_clients) if unique_clients else 0.0
            visits_per_patient         = (patient_visits / unique_patient_visits) if unique_patient_visits else 0.0
            visits_per_client          = (patient_visits / unique_clients) if unique_clients else 0.0
        
            # New Clients / New Patients within period (first-ever appearance in full dataset)
            first_seen_client = df_full.groupby("ClientKey")["ChargeDate"].min()
            first_seen_pair   = df_full.groupby(["ClientKey","AnimalKey"])["ChargeDate"].min()
            period_start      = pd.to_datetime(df_period["ChargeDate"]).min()
            period_end        = pd.to_datetime(df_period["ChargeDate"]).max()
            new_clients       = int(first_seen_client.between(period_start, period_end).sum()) if pd.notna(period_start) else 0
            new_patients      = int(first_seen_pair.between(period_start, period_end).sum()) if pd.notna(period_start) else 0
            if selected_period == "All Data":
                new_clients, new_patients = unique_clients, unique_pairs

            # Consults count during the selected period
            consult_rows_period = df_period.loc[masks["CONSULT"]].copy()
            num_consults_period = consult_rows_period.shape[0]
            
            # Add formatted KPIs
            metrics.update({
                "Total Revenue": f"{int(total_revenue):,}",
                "Revenue per Client": f"{rev_per_client:,.0f}",
                "Revenue per Visiting Patient": f"{rev_per_visiting_patient:,.0f}",
                "Revenue per Client Transaction": f"{rev_per_client_tx:,.0f}",
                "Revenue per Patient Visit": f"{rev_per_patient_visit:,.0f}",
                "Unique Clients Seen": f"{unique_clients:,}",
                "Unique Patient Visits": f"{unique_patient_visits:,}",
                "Number of Client Transactions": f"{client_transactions:,}",
                "Number of Patient Visits": f"{patient_visits:,}",
                "Transactions per Client": f"{tx_per_client:.1f}".rstrip("0").rstrip("."),
                "Visits per Patient": f"{visits_per_patient:.1f}".rstrip("0").rstrip("."),
                "Patient Visits per Client": f"{visits_per_client:.1f}".rstrip("0").rstrip("."),
                "New Clients": f"{new_clients:,}",
                "New Patients": f"{new_patients:,}",
                "Number of Consults": f"{num_consults_period:,}",
            })

        
            # -------------------------
            # Card Renderer
            # -------------------------
            CARD_STYLE = """<div style='background-color:{bg};
                border:1px solid var(--cr-border);padding:16px;border-radius:8px;text-align:center;
                margin-bottom:12px;min-height:120px;display:flex;flex-direction:column;justify-content:center;'>
                <div style='font-size:13px;color:var(--cr-muted);font-weight:600;'>{label}</div>
                <div style='font-size:{fs}px;font-weight:700;color:var(--cr-text);margin-top:6px;'>{val}</div></div>"""
        
            def _fs(v: str) -> int:
                return 16 if len(v) > 25 else (20 if len(v) > 18 else 22)
        
            def cardgroup(title: str, keys: list[str]):
                show = [k for k in keys if k in metrics]
                if not show:
                    return
                st.markdown(
                    f"<h4 style='font-size:17px;font-weight:700;color:var(--cr-muted);margin-top:1rem;margin-bottom:0.4rem;'>{title} – {period_label}</h4>",
                    unsafe_allow_html=True
                )
                cols = st.columns(5)
                for i, k in enumerate(show):
                    v  = metrics[k]
                    fs = _fs(v); bg = "var(--cr-surface)"
                    cols[i % 5].markdown(CARD_STYLE.format(bg=bg, label=k, val=v, fs=fs), unsafe_allow_html=True)
                    if (i+1) % 5 == 0 and (i+1) < len(show):
                        cols = st.columns(5)
        
            # -------------------------
            # 💰 Revenue Cards
            # -------------------------
            cardgroup("💰 Revenue", [
                "Total Revenue",
                "Revenue per Client",
                "Revenue per Visiting Patient",
                "Revenue per Client Transaction",
                "Revenue per Patient Visit",
            ])
        
            # -------------------------
            # 💵 Revenue Breakdown Cards (period slice, using masks)
            # -------------------------
            if not df_period.empty:
                def _sum_mask(key: str) -> float:
                    m = masks[key].reindex(df_period.index, fill_value=False)
                    return float(df_period.loc[m, "Amount"].sum())
        
                total_rev_period = float(df_period["Amount"].sum())
                rb = {
                    "Revenue from Boarding (Total & %)": _sum_mask("BOARDING"),
                    "Revenue from Consult Fees (Total & %)": _sum_mask("CONSULT"), 
                    "Revenue from Flea/Worm (Total & %)":  _sum_mask("FLEA_WORM"),
                    "Revenue from Food (Total & %)":       _sum_mask("FOOD"),
                    "Revenue from Grooms, Ears & Nails (Total & %)": _sum_mask("GROOMING"),
                    "Revenue from Lab Work (Total & %)":   _sum_mask("LABWORK"),
                    "Revenue from Neuters (Total & %)":    _sum_mask("NEUTER"),
                    "Revenue from Non-consult Fees (Total & %)": _sum_mask("FEE"),
                    "Revenue from Ultrasounds (Total & %)":_sum_mask("ULTRASOUND"),
                    "Revenue from X-rays (Total & %)":     _sum_mask("XRAY"),
                }
                for k, v in rb.items():
                    pct = (v / total_rev_period * 100) if total_rev_period > 0 else 0.0
                    metrics[k] = f"{int(v):,} ({pct:.1f}%)"
        
                cardgroup("💵 Revenue Breakdown", sorted(rb.keys(), key=str.lower))
        
            # -------------------------
            # 👥 Clients & Patients Cards
            # -------------------------
            cardgroup("👥 Clients & Patients", [
                "Unique Clients Seen",
                "Unique Patient Visits",
                "Patient Visits per Client",
                "Max Patient Visits",
                "Avg Patient Visits/Day",
                "New Clients",
                "New Patients",
            ])
        
            # -------------------------
            # 🔁 Transactions Cards
            # -------------------------
            cardgroup("🔁 Transactions", [
                "Number of Client Transactions",
                "Number of Patient Visits",
                "Transactions per Client",
                "Visits per Patient",
                "Max Client Transactions",
                "Avg Client Transactions/Day",
                "Number of Consults"
            ])
        
            # -------------------------
            # 🐾 Patient Breakdown Cards
            # -------------------------
            pb_titles = [f"Unique Patients Having {k}" for k in pb_map.keys()]
            cardgroup("🐾 Patient Breakdown", pb_titles)
        
            # -------------------------
            # 💼 Client Transaction Histogram
            # -------------------------
            if total_clients > 0:
                cardgroup("💼 Client Transaction Histogram", [
                    "Clients with 1 Transaction",
                    "Clients with 2 Transactions",
                    "Clients with 3–5 Transactions",
                    "Clients with 6+ Transactions",
                ])
        
            # -------------------------
            # 🎉 Fun Facts
            # -------------------------
            cardgroup("🎉 Fun Facts", [
                "Most Common Pet Name",
                "Patient with Most Visits",
            ])
        
            # ============================
            # 📋 Tables
            # ============================
            st.markdown("---")
            st.markdown("<div id='factoids-tables' class='anchor-offset'></div>", unsafe_allow_html=True)
            st.markdown("### 📋 Tables")
        
            # 💰 Top 20 Items by Revenue
            st.markdown(f"#### 💰 Top 20 Items by Revenue – {period_label}")
            top_items = (
                df_period.groupby("Item Name")
                .agg(TotalRevenue=("Amount","sum"), TotalCount=("Qty","sum"))
                .sort_values("TotalRevenue", ascending=False)
                .head(20)
            )
            if not top_items.empty:
                total_top = float(top_items["TotalRevenue"].sum())
                top_items["% of Total Revenue"] = (top_items["TotalRevenue"] / total_top * 100).round(1)
                top_items["Revenue"]   = top_items["TotalRevenue"].astype(int).apply(lambda x: f"{x:,}")
                top_items["How Many"]  = top_items["TotalCount"].astype(int).apply(lambda x: f"{x:,}")
                top_items["% of Total Revenue"] = top_items["% of Total Revenue"].astype(str) + "%"
        
                top_items = top_items.reset_index(drop=False)
                top_items.insert(0, "Rank", range(1, len(top_items) + 1))
                display_df = top_items[["Rank","Item Name","Revenue","% of Total Revenue","How Many"]]
        
                st.dataframe(
                    display_df.style.set_properties(
                        subset=["Rank"], **{"min-width":"12px","width":"12px","max-width":"12px","text-align":"center"}
                    ),
                    use_container_width=True, hide_index=True
                )
            else:
                st.info("No items found.")
        
            # 💎 Top 5 Spending Clients
            st.markdown(f"#### 💎 Top 5 Spending Clients – {period_label}")
            clients = (
                df_period.assign(Client_Clean=df_period["Client Name"].astype(str).str.strip())
                         .query("Client_Clean != ''", engine="python")
            )
            clients = clients[~clients["Client_Clean"].str.lower().str.contains("counter")]
            if not clients.empty:
                topc = (
                    clients.groupby("Client_Clean")["Amount"]
                           .sum()
                           .sort_values(ascending=False)
                           .head(5)
                           .rename("Total Spend")
                           .to_frame()
                )
                topc["Total Spend"] = topc["Total Spend"].astype(int).apply(lambda x: f"{x:,}")
                st.dataframe(topc, use_container_width=True)
            else:
                st.info("No client data.")
        
            # 📈 Top 5 Largest Client Transactions
            st.markdown(f"#### 📈 Top 5 Largest Client Transactions – {period_label}")
            txg = tx_client.copy()
            if not txg.empty:
                txg["Patients"] = txg["Patients"].apply(
                    lambda s: ", ".join(sorted([p for p in s if isinstance(p, str) and p.strip() != '' and 'counter' not in p.lower()]))
                )
                txg = txg[
                    txg["Client Name"].astype(str).str.strip().ne("") &
                    ~txg["Client Name"].str.lower().str.contains("counter")
                ]
                largest = txg.sort_values("Amount", ascending=False).head(5)
                if not largest.empty:
                    largest = largest[["Client Name","StartDate","EndDate","Patients","Amount"]].copy()
                    largest["Amount"] = largest["Amount"].astype(int).apply(lambda x: f"{x:,}")
                    largest["DateRange"] = largest.apply(
                        lambda r: f"{r['StartDate'].strftime('%d %b %Y')} → {r['EndDate'].strftime('%d %b %Y')}"
                        if r["StartDate"] != r["EndDate"] else r["StartDate"].strftime("%d %b %Y"),
                        axis=1
                    )
                    st.dataframe(largest[["Client Name","DateRange","Patients","Amount"]], use_container_width=True)
                else:
                    st.info("No transactions found.")
            else:
                st.info("No transactions found.")
        
            # ============================
            # 📊 Revenue Concentration Curves (Dropdown)
            # ============================
            st.markdown("---")
            st.subheader(f"📊 Revenue Concentration Curves – {period_label}")
        
            curve_choice = st.selectbox("Select curve to display:", ["Items","Clients"], index=0)
        
            chart_height = 400
            chart_width  = 700
        
            def make_conc_chart(df_in, color, title, x_title, y_title, tooltip_fields):
                return (
                    alt.Chart(df_in)
                    .mark_point(color=color, size=60, filled=True, opacity=1, strokeWidth=0)
                    .encode(
                        x=alt.X("TopPct:Q", title=x_title),
                        y=alt.Y("CumPct:Q", title=y_title),
                        tooltip=tooltip_fields,
                    )
                    .properties(height=chart_height, width=chart_width, title=title)
                )
        
            if curve_choice == "Items":
                rev_items = (
                    df_period.groupby("Item Name", dropna=False)
                             .agg(Frequency=("Qty","sum"), TotalRevenue=("Amount","sum"))
                             .sort_values("TotalRevenue", ascending=False)
                             .reset_index()
                )
                if not rev_items.empty and rev_items["TotalRevenue"].sum() > 0:
                    total_revenue_items = float(rev_items["TotalRevenue"].sum())
                    n_items = len(rev_items)
                    rev_items["Rank"]       = rev_items.index + 1
                    rev_items["TopPct"]     = rev_items["Rank"] / n_items * 100
                    rev_items["CumRevenue"] = rev_items["TotalRevenue"].cumsum()
                    rev_items["CumPct"]     = rev_items["CumRevenue"] / total_revenue_items * 100
        
                    chart_items = make_conc_chart(
                        rev_items,
                        "#60a5fa",
                        f"Revenue Concentration Curve: Items – {period_label}",
                        "Top X% of Items",
                        "% of Total Revenue",
                        [
                            alt.Tooltip("Rank:Q", title="Rank"),
                            alt.Tooltip("Item Name:N", title="Item"),
                            alt.Tooltip("TotalRevenue:Q", title="Item Revenue", format=",.0f"),
                            alt.Tooltip("TopPct:Q", title="Top X%", format=".1f"),
                            alt.Tooltip("CumPct:Q", title="Cumulative % of Revenue", format=".1f"),
                        ],
                    )
                    st.altair_chart(chart_items, use_container_width=True)
                else:
                    st.info("No item data found for this period.")
        
            elif curve_choice == "Clients":
                rev_clients = (
                    df_period.groupby("Client Name", dropna=False)["Amount"]
                             .sum()
                             .sort_values(ascending=False)
                             .reset_index()
                )
                if not rev_clients.empty and rev_clients["Amount"].sum() > 0:
                    total_revenue = float(rev_clients["Amount"].sum())
                    n_clients     = len(rev_clients)
                    rev_clients["Rank"]       = rev_clients.index + 1
                    rev_clients["TopPct"]     = rev_clients["Rank"] / n_clients * 100
                    rev_clients["CumRevenue"] = rev_clients["Amount"].cumsum()
                    rev_clients["CumPct"]     = rev_clients["CumRevenue"] / total_revenue * 100
        
                    chart_clients = make_conc_chart(
                        rev_clients,
                        "#f97316",
                        f"Revenue Concentration Curve: Clients – {period_label}",
                        "Top X% of Clients",
                        "% of Total Revenue",
                        [
                            alt.Tooltip("Rank:Q", title="Rank"),
                            alt.Tooltip("Client Name:N", title="Client"),
                            alt.Tooltip("Amount:Q", title="Client Spend", format=",.0f"),
                            alt.Tooltip("TopPct:Q", title="Top X%", format=".1f"),
                            alt.Tooltip("CumPct:Q", title="Cumulative % of Revenue", format=".1f"),
                        ],
                    )
                    st.altair_chart(chart_clients, use_container_width=True)
                else:
                    st.info("No client data found for this period.")

# ============================================================
# 💬 Feedback (Single source of truth)
# ============================================================
DEFAULT_FEEDBACK_SHEET_ID = "1LUK2lAmGww40aZzFpx1TSKPLvXsqmm_R5WkqXQVkf98"
FEEDBACK_SHEET_ID = config_value("FEEDBACK_SHEET_ID", DEFAULT_FEEDBACK_SHEET_ID)
FEEDBACK_SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

@st.cache_resource(show_spinner=False)
def get_feedback_sheet():
    """Connect to Feedback Google Sheet (lazy; cached)."""
    try:
        creds_dict = st.secrets["gcp_service_account"]
    except Exception:
        try:
            with open("google-credentials.json", "r") as f:
                creds_dict = json.load(f)
        except FileNotFoundError:
            return None

    try:
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, FEEDBACK_SCOPE)
        client = gspread.authorize(creds)
        return client.open_by_key(FEEDBACK_SHEET_ID).sheet1
    except Exception:
        return None


def insert_feedback(name: str, email: str, message: str):
    sheet = get_feedback_sheet()
    if sheet is None:
        st.error("⚠ Could not connect to Feedback Sheet. Check credentials or try again later.")
        return

    now = utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")

    # robust next id
    try:
        col_ids = sheet.col_values(1)[1:]  # skip header
        nums = [int(x) for x in col_ids if str(x).strip().isdigit()]
        next_id = (max(nums) if nums else 0) + 1
    except Exception:
        rows = sheet.get_all_values() or []
        next_id = max(0, len(rows) - 1) + 1

    sheet.append_row([next_id, now, name or "", email or "", message], value_input_option="USER_ENTERED")


@st.cache_data(ttl=600, show_spinner=False)
def fetch_feedback(limit=500):
    """Fetch last `limit` feedback rows (optional; for admin use)."""
    sheet = get_feedback_sheet()
    if sheet is None:
        return []
    rows = sheet.get_all_values() or []
    data = rows[1:] if rows else []
    return data[-limit:] if data else []


@st.cache_data(ttl=30, show_spinner=False)
def fetch_feedback_cached(limit=500):
    # keep your existing callsites working
    return fetch_feedback(limit)

# Feedback UI temporarily hidden; helper functions are kept above for easy restoration.

# --------------------------------
#  👩‍⚕️ ADMIN TOOLS
# --------------------------------

# Admin tools temporarily hidden.
if False and st.session_state.get("clinic_id") == "Admin":
    st.markdown("---")
    st.markdown("## 🧩 Clinic Account Management (Admin Only)")
    st.markdown("### 👩‍⚕️ Admin: Add or Reset Clinic Accounts")

    sheet = get_settings_sheet()
    st.info("Use this to add or update clinic login credentials. Passwords are stored as salted hashes.")

    with st.form("add_clinic_form"):
        new_clinic = st.text_input("Clinic ID (e.g., HappyVet)").strip()
        new_pw = st.text_input("Password (e.g., mypassword)").strip()
        submitted = st.form_submit_button("➕ Add / Update Clinic")

    if submitted:
        if not new_clinic or not new_pw:
            st.error("Please enter both Clinic ID and Password.")
        else:
            hashed = password_hash_for_storage(new_pw)
            all_vals = sheet.get_all_values()
            headers = all_vals[0]
            clinic_col = headers.index("ClinicID") + 1

            # Check if clinic already exists
            row = None
            for i, r in enumerate(all_vals[1:], start=2):
                if r[clinic_col - 1].strip().lower() == new_clinic.lower():
                    row = i
                    break

            if row:
                # Update existing clinic row
                _update_password_cells(sheet, headers, row, "", hashed, utc_now_iso())
                upsert_user_tracker(new_clinic, event="admin_password_update")
                st.success(f"✅ Updated password for clinic '{new_clinic}'.")
            else:
                # Add a new clinic row
                sheet.append_row(settings_row_values(headers, {
                    SHEET_COL_CLINIC_ID: new_clinic,
                    SHEET_COL_PASSWORD_HASH: hashed,
                    SHEET_COL_SETTINGS_JSON: "{}",
                    SHEET_COL_UPDATED_AT: utc_now_iso(),
                }))
                upsert_user_tracker(new_clinic, event="admin_created")
                st.success(f"✅ Added new clinic '{new_clinic}'.")

elif False:
    st.caption("Admin-only clinic management hidden. Log in as Admin to access it.")
    
# --------------------------------
# 🧷 Nova Vet Family Admin Access (temporarily hidden)
# --------------------------------
st.session_state["admin_unlocked"] = False

# --------------------------------
# If unlocked → show Keyword Debugging + Quarterly LLM Export
# --------------------------------
if False and st.session_state["admin_unlocked"]:
    # 🧪 Keyword Debugging Export
    st.markdown("---")
    st.markdown("### 🧪 Keyword Debugging Export")

    # Prefer the preprocessed bundle if available (faster + consistent)
    if "bundle" in st.session_state:
        df_source, pre_masks, _, _, _ = st.session_state["bundle"]
    else:
        df_source = st.session_state.get("working_df")

    if df_source is not None and not getattr(df_source, "empty", True):
        df_debug = df_source.copy()
        df_debug["Amount"] = pd.to_numeric(df_debug["Amount"], errors="coerce").fillna(0)

        have_pre_masks = "bundle" in st.session_state

        mask_key_map = {
            "CONSULT": "CONSULT",
            "DENTAL": "DENTAL",
            "GROOMING": "GROOMING",
            "BOARDING": "BOARDING",
            "FEE": "FEE",
            "FLEA_WORM": "FLEA_WORM",
            "FOOD": "FOOD",
            "XRAY": "XRAY",
            "ULTRASOUND": "ULTRASOUND",
            "LABWORK": "LABWORK",
            "ANAESTHETIC": "ANAESTHETIC",
            "HOSPITALISATION": "HOSPITAL",
            "VACCINE": "VACCINE",
            "DEATH": "DEATH",
            "NEUTER": "NEUTER",
            "PATIENT_VISIT": "PATIENT_VISIT",
        }

        keyword_groups = {
            "CONSULT": (CONSULT_KEYWORDS, CONSULT_EXCLUSIONS),
            "DENTAL": (DENTAL_KEYWORDS, DENTAL_EXCLUSIONS),
            "GROOMING": (GROOM_KEYWORDS, GROOM_EXCLUSIONS),
            "BOARDING": (BOARDING_KEYWORDS, BOARDING_EXCLUSIONS),
            "FEE": (FEE_KEYWORDS, FEE_EXCLUSIONS),
            "FLEA_WORM": (FLEA_WORM_KEYWORDS, FLEA_WORM_EXCLUSIONS),
            "FOOD": (FOOD_KEYWORDS, FOOD_EXCLUSIONS),
            "XRAY": (XRAY_KEYWORDS, XRAY_EXCLUSIONS),
            "ULTRASOUND": (ULTRASOUND_KEYWORDS, ULTRASOUND_EXCLUSIONS),
            "LABWORK": (LABWORK_KEYWORDS, LABWORK_EXCLUSIONS),
            "ANAESTHETIC": (ANAESTHETIC_KEYWORDS, ANAESTHETIC_EXCLUSIONS),
            "HOSPITALISATION": (HOSPITALISATION_KEYWORDS, HOSPITALISATION_EXCLUSIONS),
            "VACCINE": (VACCINE_KEYWORDS, VACCINE_EXCLUSIONS),
            "DEATH": (DEATH_KEYWORDS, DEATH_EXCLUSIONS),
            "NEUTER": (NEUTER_KEYWORDS, NEUTER_EXCLUSIONS),
            "PATIENT_VISIT": (PATIENT_VISIT_KEYWORDS, PATIENT_VISIT_EXCLUSIONS),
        }

        debug_frames = []

        def top_frames_for_subset(label: str, subset: pd.DataFrame):
            rev = (
                subset.groupby("Item Name", as_index=False)
                      .agg(TotalRevenue=("Amount", "sum"), Count=("Item Name", "size"))
            )
            rev_top = rev.nlargest(50, "TotalRevenue").copy()
            rev_top["Category"] = label
            rev_top["Metric"] = "Top 50 by Revenue"

            cnt_top = rev.nlargest(50, "Count").copy()
            cnt_top["Category"] = label
            cnt_top["Metric"] = "Top 50 by Count"
            return rev_top, cnt_top

        if have_pre_masks:
            for label, key in mask_key_map.items():
                m = pre_masks.get(key)
                if m is None:
                    continue
                m = m.reindex(df_debug.index, fill_value=False)
                subset = df_debug.loc[m].copy()
                if subset.empty:
                    continue
                r, c = top_frames_for_subset(label, subset)
                debug_frames.extend([r, c])

            all_mask = None
            for key in mask_key_map.values():
                m = pre_masks.get(key)
                if m is None:
                    continue
                m = m.reindex(df_debug.index, fill_value=False)
                all_mask = m if all_mask is None else (all_mask | m)
            if all_mask is not None:
                subset_all = df_debug.loc[all_mask].copy()
                if not subset_all.empty:
                    r_all, c_all = top_frames_for_subset("ALL_KEYWORDS", subset_all)
                    debug_frames.extend([r_all, c_all])
        else:
            for label, (includes, excludes) in keyword_groups.items():
                m = make_mask(df_debug, includes, excludes)
                subset = df_debug.loc[m].copy()
                if subset.empty:
                    continue
                r, c = top_frames_for_subset(label, subset)
                debug_frames.extend([r, c])

            all_mask = pd.Series(False, index=df_debug.index)
            for includes, excludes in keyword_groups.values():
                all_mask |= make_mask(df_debug, includes, excludes)
            subset_all = df_debug.loc[all_mask].copy()
            if not subset_all.empty:
                r_all, c_all = top_frames_for_subset("ALL_KEYWORDS", subset_all)
                debug_frames.extend([r_all, c_all])

        if debug_frames:
            debug_out = pd.concat(debug_frames, ignore_index=True)
            debug_out = debug_out[["Category", "Metric", "Item Name", "TotalRevenue", "Count"]]
            debug_out["TotalRevenue"] = debug_out["TotalRevenue"].astype(int)

            csv_bytes = debug_out.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="⬇️ Download Keyword Debug CSV (Top 50 by Revenue & Count, all categories)",
                data=csv_bytes,
                file_name="keyword_debug_top50_allcategories.csv",
                mime="text/csv",
            )
        else:
            st.info("No keyword matches found for any category.")
    else:
        st.warning("Upload data to enable debugging export.")

    # --------------------------------
    # 🧾 Quarterly LLM Bundle
    # --------------------------------
    # --- Guard: ensure export builders exist (prevents crashes if not included yet)
    quarterly_payload_builder = globals().get("build_quarterly_payload_full")
    quarterly_json_default = globals().get("_json_default")
    missing_export_bits = []
    if quarterly_payload_builder is None:
        missing_export_bits.append("build_quarterly_payload_full")
    if quarterly_json_default is None:
        missing_export_bits.append("_json_default")
    
    if missing_export_bits:
        st.warning(
            "Quarterly export is not available in this build. Missing: "
            + ", ".join(missing_export_bits)
        )
    else:
        st.markdown("---")
        st.markdown("### 🧾 Quarterly LLM Bundle")
    
        st.session_state.setdefault("llm_payload", None)
        st.session_state.setdefault("llm_zip_bytes", None)
        st.session_state.setdefault("llm_built_at", None)
    
        col_gen, col_dl = st.columns([1, 1])
    
        with col_gen:
            if st.button("Generate Data", help="Builds the quarterly JSON payload and CSVs (on click only)"):
                if "bundle" not in st.session_state:
                    st.error("Upload data first to enable this export.")
                else:
                    df_full, masks, tx_client, tx_patient, patients_per_month = st.session_state["bundle"]
                    with st.spinner("Generating quarterly export bundle..."):
                        payload, zip_bytes = quarterly_payload_builder(
                            df_full=df_full,
                            masks=masks,
                            tx_client=tx_client,
                            tx_patient=tx_patient,
                            patients_per_month=patients_per_month,
                            clinic_name=st.session_state.get("user_name") or None,
                            include_raw_rows_csv=True,
                            raw_rows_limit=None,
                        )
                    if zip_bytes:
                        clean_payload_json = json.dumps(payload, ensure_ascii=False, indent=2, default=quarterly_json_default, allow_nan=False)
                        clean_payload = json.loads(clean_payload_json)
    
                        st.session_state["llm_payload"] = clean_payload
                        st.session_state["llm_zip_bytes"] = zip_bytes
                        st.session_state["llm_built_at"] = pd.Timestamp.now(tz="Asia/Dubai")
                        st.success("Quarterly LLM data generated.")
                    else:
                        st.error("Could not build the bundle (no data or invalid dates).")
    
        with col_dl:
            has_zip = st.session_state.get("llm_zip_bytes") is not None
            if has_zip:
                st.download_button(
                    label="Download ZIP",
                    data=st.session_state["llm_zip_bytes"],
                    file_name="clinic_quarterly_llm_bundle.zip",
                    mime="application/zip",
                    help="Downloads quarterly_payload.json + supporting CSVs",
                )
            else:
                st.button("Download ZIP", disabled=True, help="Generate Data first")
    
        if st.session_state.get("llm_payload"):
            meta = f"Built at: {st.session_state.get('llm_built_at')}"
            with st.expander(f"Preview quarterly_payload.json  •  {meta}"):
                st.code(
                    json.dumps(st.session_state["llm_payload"], ensure_ascii=False, indent=2, default=quarterly_json_default, allow_nan=False)[:8000],
                    language="json",
                )
