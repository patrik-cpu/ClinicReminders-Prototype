import pandas as pd
import altair as alt
import unicodedata
import streamlit as st
import re
import json, os, time
import streamlit.components.v1 as components
import gspread
from settings_pointer_utils import settings_col_index, update_dataset_pointer_cells
from oauth2client.service_account import ServiceAccountCredentials
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import base64
import hmac
import numpy as np
from gspread.exceptions import APIError
import random
import html as html_lib
from zoneinfo import ZoneInfo

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
DRIVE_SCOPE = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]

_SPACE_RX = re.compile(r"\s+")
_CURRENCY_RX = re.compile(r"[^\d.\-]")
MAIN_SECTION_TABS = ["Reminders", "Get Started", "Upload Data", "Search Terms", "Exclusions"]
SETUP_LINK_TARGETS = {
    "upload-data": ("Upload Data", None),
    "search-terms": ("Search Terms", None),
    "reminders": ("Reminders", None),
    "whatsapp-composer": ("Reminders", "_scroll_to_whatsapp_composer"),
    "template-editor": ("Reminders", "_scroll_to_wa_template_editor"),
}


def set_main_section_tab(tab_name: str):
    if tab_name in MAIN_SECTION_TABS:
        st.session_state["main_section_tab"] = tab_name


def get_query_param_value(key: str) -> str:
    value = st.query_params.get(key, "")
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return str(value or "")


def consume_setup_navigation_target():
    target = get_query_param_value("setup_target")
    tab_and_scroll_flag = SETUP_LINK_TARGETS.get(target)
    if not tab_and_scroll_flag:
        return
    tab_name, scroll_flag = tab_and_scroll_flag
    set_main_section_tab(tab_name)
    if scroll_flag:
        st.session_state[scroll_flag] = True
    try:
        del st.query_params["setup_target"]
    except Exception:
        pass

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
            min-width: 7.5rem;
            width: auto !important;
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
            transform: translate(15px, 13px);
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
DATASETS_FOLDER_ID = "1omuJfEmo_nuntr5uQBJhil_Q8ZNa2Lpr"  # from Drive folder URL

# === Sheet columns you created ===
SHEET_COL_DATASET_FILE_ID = "DatasetFileId"
SHEET_COL_DATASET_FILE_NAME = "DatasetFileName"
SHEET_COL_DATASET_UPDATED_AT = "DatasetUpdatedAt"
GST_TZ = ZoneInfo("Asia/Dubai")
WA_TRACKER_WORKSHEET = "WA button tracker"
USER_TRACKER_WORKSHEET = "User tracker"
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
        st.session_state["file_uploader_reset_version"] = st.session_state.get("file_uploader_reset_version", 0) + 1
        st.session_state["last_uploaded_files"] = []
        st.session_state.pop("last_saved_upload_key", None)
        st.session_state.pop("pending_overlap_upload_key", None)
    if clear_cache:
        st.cache_data.clear()

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
    sheet, headers, row_idx = _get_settings_row_for_clinic(clinic_id)

    # Clear the dataset pointer cells
    sheet.update_cell(row_idx, _settings_col_index(headers, SHEET_COL_DATASET_FILE_ID), "")
    sheet.update_cell(row_idx, _settings_col_index(headers, SHEET_COL_DATASET_FILE_NAME), "")
    sheet.update_cell(row_idx, _settings_col_index(headers, SHEET_COL_DATASET_UPDATED_AT), "")

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


def gst_now(now: datetime | None = None) -> datetime:
    now = now or datetime.utcnow()
    if now.tzinfo is None:
        now = now.replace(tzinfo=ZoneInfo("UTC"))
    return now.astimezone(GST_TZ)


def gst_now_iso(now: datetime | None = None) -> str:
    return gst_now(now).strftime("%Y-%m-%d %H:%M:%S")


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
        ("PlainPassword", plain_password),
        ("PasswordHash", password_hash),
        ("UpdatedAt", updated_at),
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
    sheet = get_settings_sheet()
    all_vals = _gspread_retry(sheet.get_all_values)
    headers = all_vals[0]
    clinic_col = _settings_col_index(headers, "ClinicID")
    row_idx = None
    for i, r in enumerate(all_vals[1:], start=2):
        if r[clinic_col - 1].strip().lower() == clinic_id.strip().lower():
            row_idx = i
            break

    if row_idx is None:
        raise ValueError("ClinicID not found in settings sheet")
    return sheet, headers, row_idx
    
def drive_trash_file(file_id: str):
    if not file_id:
        return
    service = get_drive_service()
    service.files().update(
        fileId=file_id,
        body={"trashed": True},
        supportsAllDrives=True
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
        color: var(--cr-text);
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
    .block-container { max-width: 100% !important; padding-left: 2rem; padding-right: 2rem; }
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
        margin: 0.35rem 0 0.85rem;
        padding: 0.85rem 1rem;
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
    [class*="st-key-remove_dataset_upload_button_"] button {
        background: transparent !important;
        border: 0 !important;
        box-shadow: none !important;
        color: #e11d48 !important;
        font-size: 1.15rem !important;
        font-weight: 800 !important;
        min-height: 1.6rem !important;
        padding: 0 !important;
    }
    .dataset-check-grid {
        display: grid;
        gap: 0.6rem;
        grid-template-columns: repeat(3, minmax(180px, 1fr));
        margin-top: 0.8rem;
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
    .field-examples {
        color: var(--cr-muted);
        font-size: 0.95rem;
        font-style: italic;
        line-height: 1.45;
        margin-top: 0.45rem;
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
    .setup-step a {
        color: var(--cr-link);
        font-weight: 700;
        text-decoration: none;
    }
    .setup-link {
        display: inline-block;
        font-size: 0.9rem;
        margin-top: 0.2rem;
    }
    .setup-link:hover {
        text-decoration: underline;
    }
    [class*="st-key-reset_get_started_checklist"] button {
        min-width: 13rem;
    }
    [class*="st-key-del_client_excl_"] button,
    [class*="st-key-del_patient_excl_"] button,
    [class*="st-key-del_excl_"] button {
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
    [class*="st-key-del_excl_"] button:hover {
        background: rgba(217, 45, 32, 0.08) !important;
        border-radius: 999px !important;
    }
    [class*="st-key-del_client_excl_"] button p,
    [class*="st-key-del_patient_excl_"] button p,
    [class*="st-key-del_excl_"] button p {
        color: #d92d20 !important;
        font-size: 1.55rem !important;
        font-weight: 700 !important;
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


def render_field_label(container, label: str, help_text: str):
    safe_label = html_lib.escape(label)
    safe_help = html_lib.escape(help_text)
    container.markdown(
        f"<div style='font-size:0.9rem; font-weight:600; margin-bottom:0.35rem;'>{safe_label} <span class='column-help' data-tooltip='{safe_help}'>?</span></div>",
        unsafe_allow_html=True,
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
import hashlib

# === CONFIGURATION ===
SETTINGS_SHEET_ID = "1JQgF268JyHZZRHg0V-p3chBu5jhANIMnUvkb7M0Fxs8"  # ← your ClinicReminders_Settings_Master Sheet ID
SETTINGS_SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

# === DEV AUTO-LOGIN ===
DEV_AUTO_LOGIN = False
DEV_AUTO_LOGIN_CREDENTIALS = ("", "")
AUTO_LOGIN_ALLOWED_USERNAME = "PatTest"

def auto_login_allowed(username: str) -> bool:
    return str(username or "").strip().lower() == AUTO_LOGIN_ALLOWED_USERNAME.lower()

# === GOOGLE DRIVE CONFIG ===
@st.cache_resource
def get_drive_service():
    # Use Streamlit secrets first, fallback to local json file
    try:
        creds_dict = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=DRIVE_SCOPE)
    except Exception:
        creds = Credentials.from_service_account_file("google-credentials.json", scopes=DRIVE_SCOPE)

    return build("drive", "v3", credentials=creds)

def drive_download_bytes(file_id: str) -> bytes:
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
        # Show useful info in Streamlit
        st.error(f"Drive download failed. HTTP {getattr(e.resp, 'status', '?')}")
        try:
            st.code(e.content.decode("utf-8"))
        except Exception:
            pass
        raise
        
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
        df["ChargeDate"] = pd.to_datetime(df["ChargeDate"], errors="coerce")

    if "Qty" in df.columns:
        df["Qty"] = pd.to_numeric(df["Qty"], errors="coerce").fillna(1).astype(int)

    if "Amount" in df.columns:
        df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce").fillna(0)

    return df
    
def load_shared_dataset_for_clinic():
    """
    If the clinic has a DatasetFileId stored in the settings sheet,
    download it from Drive, process it, and set st.session_state['working_df'].
    """
    reset_uploaded_data_state(clear_cache=False)
    clinic_id = st.session_state.get("clinic_id")
    if not clinic_id:
        return

    sheet = get_settings_sheet()
    records = sheet.get_all_records()

    rec = next((r for r in records if str(r.get("ClinicID", "")).strip().lower() == clinic_id.strip().lower()), None)
    if not rec:
        return

    file_id = str(rec.get(SHEET_COL_DATASET_FILE_ID, "")).strip()
    if not file_id:
        return  # no shared dataset published yet

    try:
        file_bytes = drive_download_bytes(file_id)

        # Reuse your existing pipeline so schema normalization still happens
        # Filename is just for detect logic; use stored name if present, else default
        filename = rec.get(SHEET_COL_DATASET_FILE_NAME, "shared_dataset.csv") or "shared_dataset.csv"
        df, pms_name, amount_col = process_file(file_bytes, filename)
        
        st.session_state["working_df"] = sanitize_working_df(df)
        st.session_state["data_version"] = st.session_state.get("data_version", 0) + 1  # invalidate downstream caches
        st.session_state["shared_dataset_loaded"] = True
        st.session_state["shared_dataset_name"] = filename
        st.session_state["shared_dataset_updated_at"] = rec.get(SHEET_COL_DATASET_UPDATED_AT, "")

    except Exception as e:
        st.session_state["shared_dataset_loaded"] = False
        st.session_state["shared_dataset_error"] = str(e)

def drive_upsert_csv_bytes(
    file_bytes: bytes,
    filename: str,
    folder_id: str,
    existing_file_id: str | None,
) -> str:
    """
    If existing_file_id is provided -> update that file in-place.
    Else -> create a new file in folder_id.
    Uses resumable upload to reduce BrokenPipe issues.
    Returns the fileId.
    """
    service = get_drive_service()
    media = MediaIoBaseUpload(BytesIO(file_bytes), mimetype="text/csv", resumable=True)

    if existing_file_id:
        req = service.files().update(
            fileId=existing_file_id,
            media_body=media,
            supportsAllDrives=True,
        )
    else:
        body = {"name": filename, "parents": [folder_id]}
        req = service.files().create(
            body=body,
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
        st.error(f"Cannot access the Drive folder. HTTP {getattr(e.resp, 'status', '?')}")
        try:
            st.code(e.content.decode("utf-8"))
        except Exception:
            pass
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
    sheet, headers, row_idx = _get_settings_row_for_clinic(clinic_id)
    updated_at = datetime.utcnow().isoformat()
    sheet.update_cell(row_idx, _settings_col_index(headers, SHEET_COL_DATASET_FILE_ID), file_id)
    sheet.update_cell(row_idx, _settings_col_index(headers, SHEET_COL_DATASET_FILE_NAME), filename)
    sheet.update_cell(row_idx, _settings_col_index(headers, SHEET_COL_DATASET_UPDATED_AT), updated_at)
    return updated_at

# ============================================================
# ✅ Dataset Publishing (Refactor #1)
#   - Single orchestrator for publishing clinic datasets
#   - Helpers to fetch existing pointer + load existing dataset
# ============================================================
def _gspread_retry(fn, *args, **kwargs):
    """
    Retries common transient Google Sheets errors (429/500/503).
    Keeps other errors as-is so you still see real permission/config issues.
    """
    max_tries = 6
    for attempt in range(max_tries):
        try:
            return fn(*args, **kwargs)
        except APIError as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            # Some gspread versions store status differently; keep it robust:
            if status is None:
                status = getattr(getattr(e, "resp", None), "status", None)

            # Retry only transient/quota-ish errors
            if status in (429, 500, 503):
                sleep = min(30, (2 ** attempt) + random.random())
                time.sleep(sleep)
                continue

            # Not transient -> raise (likely 403 perms, 400 bad request, etc.)
            raise

    # If we exhausted retries, raise last error
    return fn(*args, **kwargs)

def get_existing_dataset_pointer(clinic_id: str) -> tuple[str, str]:
    """
    Returns (existing_file_id, existing_filename) using a light-weight read:
    - sheet.get_all_values() (still whole sheet) but avoids get_all_records() overhead
    - and does NOT parse into dicts
    If you want to go further, see section (3) below to read only 3 columns.
    """
    sheet = get_settings_sheet()
    all_vals = _gspread_retry(sheet.get_all_values)

    if not all_vals or len(all_vals) < 2:
        return "", ""

    headers = all_vals[0]
    # Defensive: handle missing headers gracefully
    try:
        clinic_ix = headers.index("ClinicID")
        fileid_ix = headers.index(SHEET_COL_DATASET_FILE_ID)
        fname_ix  = headers.index(SHEET_COL_DATASET_FILE_NAME)
    except ValueError:
        return "", ""

    cid = clinic_id.strip().lower()
    for r in all_vals[1:]:
        if len(r) <= max(clinic_ix, fileid_ix, fname_ix):
            continue
        if str(r[clinic_ix]).strip().lower() == cid:
            return str(r[fileid_ix]).strip(), str(r[fname_ix]).strip()

    return "", ""

def load_existing_shared_df(file_id: str, filename: str) -> pd.DataFrame | None:
    """
    Loads an existing shared dataset from Drive (if file_id exists),
    then normalizes it through process_file so schema matches.
    Returns None if no file_id.
    """
    if not file_id:
        return None

    existing_bytes = drive_download_bytes(file_id)

    # Normalize through your pipeline to guarantee canonical columns
    df_existing, _, _ = process_file(existing_bytes, filename or "shared_dataset.csv")

    # Optional: drop debug columns if present
    df_existing = df_existing.drop(columns=["_ChargeDate_raw"], errors="ignore")

    # If it loads but is empty, treat as None for merge logic
    if df_existing is None or getattr(df_existing, "empty", True):
        return None

    return df_existing

def dataset_date_bounds(df: pd.DataFrame) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    if df is None or getattr(df, "empty", True) or "ChargeDate" not in df.columns:
        return None, None

    dates = pd.to_datetime(df["ChargeDate"], errors="coerce").dt.normalize()
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
    try:
        return int(str(value or 0).replace(",", ""))
    except (TypeError, ValueError):
        return 0

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
            "rows": parse_history_int(entry.get("rows") or entry.get("Rows") or 0),
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
    return existing + incoming

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

def dataset_summary_checks(rows: list[dict]) -> list[dict]:
    normalized_rows = normalize_dataset_upload_history(rows)
    pms_values = [str(row.get("pms", "")).strip() for row in normalized_rows if str(row.get("pms", "")).strip()]
    unsupported_pms = {"", "-", "unknown", "undetected", "csv"}
    supported_pms = bool(pms_values) and all(pms.lower() not in unsupported_pms for pms in pms_values)
    same_pms = len({pms.lower() for pms in pms_values}) <= 1
    min_date, max_date = dataset_history_date_bounds(normalized_rows)
    today = pd.Timestamp(date.today())
    covers_last_year = bool(min_date is not None and max_date is not None and min_date <= today - pd.Timedelta(days=365) and max_date >= today - pd.Timedelta(days=1))
    max_gap = max_missing_days_between_uploads(normalized_rows)
    no_large_gaps = max_gap < 3
    return [
        {
            "good": supported_pms and same_pms,
            "text": "Same supported PMS" if supported_pms and same_pms else "CSV PMS types need attention",
        },
        {
            "good": covers_last_year,
            "text": "At least 365 days back from today" if covers_last_year else "Less than 365 days back from today",
        },
        {
            "good": no_large_gaps,
            "text": "No 3+ day gaps between CSVs" if no_large_gaps else f"{max_gap} day gap between CSVs",
        },
    ]

def date_ranges_overlap(
    first_min: pd.Timestamp | None,
    first_max: pd.Timestamp | None,
    second_min: pd.Timestamp | None,
    second_max: pd.Timestamp | None,
) -> bool:
    if any(d is None or pd.isna(d) for d in [first_min, first_max, second_min, second_max]):
        return False
    return first_min <= second_max and second_min <= first_max

def merge_dataset_update(
    existing_df: pd.DataFrame | None,
    new_df: pd.DataFrame,
    replace_overlapping_dates: bool = False,
) -> pd.DataFrame:
    if existing_df is None or getattr(existing_df, "empty", True):
        return new_df

    existing = existing_df.copy()
    new = new_df.copy()

    if replace_overlapping_dates:
        new_min, new_max = dataset_date_bounds(new)
        if new_min is not None and new_max is not None and "ChargeDate" in existing.columns:
            existing_dates = pd.to_datetime(existing["ChargeDate"], errors="coerce").dt.normalize()
            keep_existing = existing_dates.isna() | (existing_dates < new_min) | (existing_dates > new_max)
            existing = existing.loc[keep_existing].copy()

    merged = pd.concat([existing, new], ignore_index=True, sort=False)
    if "ChargeDate" in merged.columns:
        merged["_sort_charge_date"] = pd.to_datetime(merged["ChargeDate"], errors="coerce")
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
    # 1) Get current pointer (if any)
    if existing_file_id is None or existing_name is None:
        existing_file_id, existing_name = get_existing_dataset_pointer(clinic_id)

    # 2) Load existing dataset if present
    if existing_df is None:
        try:
            existing_df = load_existing_shared_df(existing_file_id, existing_name)
        except Exception as e:
            # show signal but still allow publish
            st.warning(f"Could not load existing shared dataset; saving upload as new. ({e})")
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
    
    # ✅ Update existing file if it exists; otherwise create first time
    new_file_id = drive_upsert_csv_bytes(
        file_bytes=out_bytes,
        filename=out_name,
        folder_id=datasets_folder_id,
        existing_file_id=(existing_file_id or None),
    )
    
    # ✅ Only update pointer after upload success
    dataset_updated_at = update_clinic_dataset_pointer(clinic_id, new_file_id, out_name)
    st.session_state["shared_dataset_updated_at"] = dataset_updated_at


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

    sheet = get_settings_sheet()
    records = sheet.get_all_records()
    rec = next((r for r in records if r["ClinicID"].strip().lower() == clinic_id.lower()), None)

    if rec and rec["SettingsJSON"]:
        try:
            settings = json.loads(rec["SettingsJSON"])
        except Exception:
            settings = {}
        st.session_state["rules"] = settings.get("rules", DEFAULT_RULES.copy())
        st.session_state["exclusions"] = settings.get("exclusions", [])
        st.session_state["client_exclusions"] = settings.get("client_exclusions", [])
        st.session_state["patient_exclusions"] = settings.get("patient_exclusions", [])
        st.session_state["user_name"] = settings.get("user_name", "")
        st.session_state["user_template"] = settings.get("user_template", DEFAULT_WA_TEMPLATE)
        st.session_state["client_group_days"] = max(0, int(settings.get("client_group_days", 1) or 0))
        raw_window_days = settings.get("reminder_window_days", 1)
        try:
            st.session_state["reminder_window_days"] = max(0, int(raw_window_days if raw_window_days not in (None, "") else 1))
        except (TypeError, ValueError):
            st.session_state["reminder_window_days"] = 1
        st.session_state["reminder_warning_days"] = int(settings.get("reminder_warning_days", 0) or 0)
        st.session_state["wa_reminder_log"] = settings.get("wa_reminder_log", [])
        st.session_state["deleted_reminders"] = settings.get("deleted_reminders", [])
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
    else:
        # Defaults for new clinics
        st.session_state["rules"] = DEFAULT_RULES.copy()
        st.session_state["exclusions"] = []
        st.session_state["client_exclusions"] = []
        st.session_state["patient_exclusions"] = []
        st.session_state["user_name"] = ""
        st.session_state["user_template"] = DEFAULT_WA_TEMPLATE
        st.session_state["client_group_days"] = 1
        st.session_state["reminder_window_days"] = 1
        st.session_state["reminder_warning_days"] = 0
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


def save_settings():
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

    remote_settings = get_remote_settings(sheet=sheet, headers=headers, row=row)
    if st.session_state.pop("_replace_wa_reminder_log_once", False):
        wa_reminder_log = st.session_state.get("wa_reminder_log", [])
    else:
        wa_reminder_log = merge_wa_reminder_logs(
            remote_settings.get("wa_reminder_log", []),
            st.session_state.get("wa_reminder_log", []),
        )
    st.session_state["wa_reminder_log"] = wa_reminder_log
    if st.session_state.pop("_replace_deleted_reminders_once", False):
        deleted_reminders = st.session_state.get("deleted_reminders", [])
    else:
        deleted_reminders = merge_deleted_reminders(
            remote_settings.get("deleted_reminders", []),
            st.session_state.get("deleted_reminders", []),
        )
        st.session_state["deleted_reminders"] = deleted_reminders

    def int_setting_for_save(key: str, default: int) -> int:
        value = st.session_state[key] if key in st.session_state else remote_settings.get(key, default)
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def setting_for_save(key: str, default):
        return st.session_state[key] if key in st.session_state else remote_settings.get(key, default)

    # Build the JSON blob for settings
    settings_data = {
        "rules": setting_for_save("rules", DEFAULT_RULES.copy()),
        "exclusions": setting_for_save("exclusions", []),
        "client_exclusions": setting_for_save("client_exclusions", []),
        "patient_exclusions": setting_for_save("patient_exclusions", []),
        "user_name": setting_for_save("user_name", ""),
        "user_template": setting_for_save("user_template", DEFAULT_WA_TEMPLATE),
        "client_group_days": max(0, int_setting_for_save("client_group_days", 1)),
        "reminder_window_days": max(0, int_setting_for_save("reminder_window_days", 1)),
        "reminder_warning_days": max(0, int_setting_for_save("reminder_warning_days", 0)),
        "wa_reminder_log": wa_reminder_log,
        "deleted_reminders": deleted_reminders,
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
    }
    settings_json = json.dumps(settings_data)
    updated_at = datetime.utcnow().isoformat()

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
    else:
        sheet.append_row([clinic_id, "", settings_json, updated_at])
    upsert_user_tracker(clinic_id, country=st.session_state.get("user_country", ""), event="settings_saved")
# --------------------------------

def _reminder_client_key(client_name: str) -> str:
    return _SPACE_RX.sub(" ", str(client_name or "").strip()).lower()

def _parse_reminder_log_time(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None

def _days_ago_text(then: datetime, now: datetime) -> str:
    days = max(0, (now.date() - then.date()).days)
    if days == 0:
        return "today"
    if days == 1:
        return "1 day ago"
    return f"{days} days ago"

def get_remote_settings(sheet=None, headers=None, row=None) -> dict:
    clinic_id = st.session_state.get("clinic_id")
    if not clinic_id:
        return {}

    try:
        if not (sheet and headers and row):
            sheet, headers, row = _get_settings_row_for_clinic(clinic_id)
        current_row = sheet.row_values(row)
        settings_idx = _settings_col_index(headers, "SettingsJSON") - 1
        if len(current_row) <= settings_idx or not current_row[settings_idx]:
            return {}
        return json.loads(current_row[settings_idx])
    except Exception:
        return {}

def get_remote_wa_reminder_log(sheet=None, headers=None, row=None) -> list:
    return get_remote_settings(sheet=sheet, headers=headers, row=row).get("wa_reminder_log", [])

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
    )[-1000:]

HIDDEN_REMINDER_KEY_FIELDS = ("Client Name", "Animal Name", "Plan Item", "Due Date", "Reminder Date")
REMINDER_ACTION_SENT = "sent"
REMINDER_ACTION_DECLINED = "declined"
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


def hidden_reminder_key(row) -> tuple[str, ...]:
    return tuple(
        _SPACE_RX.sub(" ", str(row.get(field, "") or "").strip()).lower()
        for field in HIDDEN_REMINDER_KEY_FIELDS
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
            merged[key] = dict(entry)
    return list(merged.values())[-1000:]


def get_hidden_reminder_record(row) -> dict | None:
    target_key = hidden_reminder_key(row)
    if not any(target_key):
        return None
    for entry in st.session_state.get("deleted_reminders", []):
        if isinstance(entry, dict) and hidden_reminder_key(entry) == target_key:
            return entry
    return None


def upsert_hidden_reminder(row, action: str, message: str = "", now: datetime | None = None) -> dict:
    now = now or datetime.utcnow()
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

    target_key = hidden_reminder_key(rec)
    reminders = [
        existing for existing in st.session_state.get("deleted_reminders", [])
        if not (isinstance(existing, dict) and hidden_reminder_key(existing) == target_key)
    ]
    reminders.append(rec)
    st.session_state["deleted_reminders"] = reminders[-1000:]
    return rec


def filter_hidden_reminders(reminders_df: pd.DataFrame) -> pd.DataFrame:
    deleted = st.session_state.get("deleted_reminders", [])
    if reminders_df.empty or not deleted:
        return reminders_df

    deleted_keys = {hidden_reminder_key(d) for d in deleted if isinstance(d, dict)}
    if not deleted_keys:
        return reminders_df

    keep_mask = reminders_df.apply(lambda row: hidden_reminder_key(row) not in deleted_keys, axis=1)
    return reminders_df.loc[keep_mask].copy()


def remove_actioned_reminder(row) -> None:
    target_key = hidden_reminder_key(row)
    if not any(target_key):
        return
    st.session_state["deleted_reminders"] = [
        entry for entry in st.session_state.get("deleted_reminders", [])
        if not (isinstance(entry, dict) and hidden_reminder_key(entry) == target_key)
    ]
    st.session_state["_replace_deleted_reminders_once"] = True


def get_recent_reminder_warning(client_name: str, now: datetime | None = None, sync_remote: bool = False) -> str | None:
    warning_days = int(st.session_state.get("reminder_warning_days", 0) or 0)
    if warning_days <= 0:
        return None

    now = now or datetime.utcnow()
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
    now = now or datetime.utcnow()
    entry = {
        "Client Name": str(client_name or "").strip(),
        "RemindedAt": now.isoformat(),
    }
    if row is not None:
        entry["ReminderKey"] = list(hidden_reminder_key(row))
    log = list(st.session_state.get("wa_reminder_log", []))
    log.append(entry)
    st.session_state["wa_reminder_log"] = log[-1000:]
    if save:
        save_settings()


def remove_wa_reminder_click_for_row(row):
    target_key = list(hidden_reminder_key(row))
    if not any(target_key):
        return
    st.session_state["wa_reminder_log"] = [
        entry for entry in st.session_state.get("wa_reminder_log", [])
        if not (isinstance(entry, dict) and entry.get("ReminderKey") == target_key)
    ]
    st.session_state["_replace_wa_reminder_log_once"] = True


def record_wa_button_tracker(row, message: str, source: str, now: datetime | None = None):
    append_tracker_row(
        WA_TRACKER_WORKSHEET,
        WA_TRACKER_HEADERS,
        [
            gst_now_iso(now),
            str(st.session_state.get("clinic_id", "")).strip(),
            str(st.session_state.get("user_name", "")).strip(),
            normalize_display_case(row.get("Client Name", "")),
            normalize_display_case(row.get("Animal Name", "")),
            normalize_display_case(row.get("Plan Item", "")),
            str(row.get("Due Date", "")).strip(),
            str(row.get("Charge Date", "")).strip(),
            str(message or "").strip(),
            source,
        ],
    )


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
    if pd.api.types.is_datetime64_any_dtype(series):
        return pd.to_datetime(series.dt.date, errors="coerce")
    s = series.astype(str).str.strip()
    s = s.str.extract(
        r"(\d{1,2}[/-][A-Za-z]{3}[/-]\d{4}|\d{1,2}[/-]\d{1,2}[/-]\d{4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})"
    )[0]
    numeric = pd.to_numeric(s, errors="coerce")
    if numeric.notna().sum() > 0:
        base_1900 = pd.Timestamp("1899-12-30")
        dt_1900 = base_1900 + pd.to_timedelta(numeric, unit="D")
        base_1904 = pd.Timestamp("1904-01-01")
        dt_1904 = base_1904 + pd.to_timedelta(numeric, unit="D")
        valid_1900 = dt_1900.dt.year.between(1990, 2100)
        valid_1904 = dt_1904.dt.year.between(1990, 2100)
        return (dt_1904 if valid_1904.sum() > valid_1900.sum() else dt_1900).dt.normalize()
    formats = [
        "%d/%b/%Y", "%d-%b-%Y",
        "%d/%m/%Y", "%m/%d/%Y",
        "%Y-%m-%d", "%Y.%m.%d"
    ]
    for fmt in formats:
        parsed = pd.to_datetime(s, format=fmt, errors="coerce")
        if parsed.notna().sum() > 0:
            return parsed.dt.normalize()
    parsed = pd.to_datetime(s, errors="coerce", dayfirst=True)
    return parsed.dt.normalize()


class UploadValidationError(ValueError):
    pass


REQUIRED_UPLOAD_COLUMNS = ["ChargeDate", "Client Name", "Animal Name", "Item Name"]
DATE_COLUMN_CANDIDATES = [
    "ChargeDate", "DateTime", "Date Time", "Date", "Invoice Date",
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


def find_column_ci(columns, candidates):
    normalized = {str(c).strip().lower(): c for c in columns}
    for candidate in candidates:
        match = normalized.get(str(candidate).strip().lower())
        if match is not None:
            return match
    return None


def apply_vetport_alias_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for source, target in VETPORT_ALIAS_COLUMNS.items():
        source_col = find_column_ci(df.columns, [source])
        target_col = find_column_ci(df.columns, [target])
        if source_col is not None and target_col is None:
            df[target] = df[source_col]
    return df


def validate_upload_dataframe(df: pd.DataFrame, filename: str):
    missing = [col for col in REQUIRED_UPLOAD_COLUMNS if col not in df.columns]
    if missing:
        raise UploadValidationError(
            f"{filename} is missing required column(s): {', '.join(missing)}."
        )
    if "ChargeDate" not in df.columns or pd.to_datetime(df["ChargeDate"], errors="coerce").notna().sum() == 0:
        raise UploadValidationError(
            f"{filename} needs a readable date column such as DateTime, Date, Invoice Date, or Planitem Performed."
        )
    if df.empty:
        raise UploadValidationError(f"{filename} does not contain any usable rows.")

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
    validate_upload_dataframe(df, filename)
    df["_client_lower"] = df["Client Name"].astype(str).str.lower()
    df["_animal_lower"] = df["Animal Name"].astype(str).str.lower()
    df["_item_lower"] = df["Item Name"].astype(str).str.lower()

    # --- ✅ Return normalized data ---
    return df, pms_name, amount_col
    
# === GOOGLE SHEETS CONNECTION ===
@st.cache_resource
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


@st.cache_resource
def get_settings_sheet():
    """Connect to the shared ClinicReminders_Settings_Master sheet."""
    return get_settings_spreadsheet().sheet1


def get_or_create_tracker_sheet(title: str, headers: list[str]):
    spreadsheet = get_settings_spreadsheet()
    try:
        worksheet = spreadsheet.worksheet(title)
    except Exception:
        worksheet = spreadsheet.add_worksheet(title=title, rows=1000, cols=max(len(headers), 8))

    first_row = worksheet.row_values(1)
    if first_row[:len(headers)] != headers:
        end_col = _column_number_to_letter(len(headers))
        _gspread_retry(worksheet.update, values=[headers], range_name=f"A1:{end_col}1")
    return worksheet


def append_tracker_row(title: str, headers: list[str], row_values: list[str]):
    try:
        worksheet = get_or_create_tracker_sheet(title, headers)
        _gspread_retry(worksheet.append_row, row_values, value_input_option="USER_ENTERED")
        return True
    except Exception:
        return False


# === LOGIN HELPER FUNCTIONS ===
def hash_pw(pw: str):
    """Return MD5 hash of a password."""
    return hashlib.md5(pw.encode()).hexdigest()

def authenticate_user(username, password):
    """Check username/password pair against the sheet."""
    sheet = get_settings_sheet()
    records = sheet.get_all_records()
    for r in records:
        if r["ClinicID"].strip().lower() == username.strip().lower():
            if r["PasswordHash"] == hash_pw(password):
                return r
    return None

def get_clinic_row(username):
    """Return a clinic row by ClinicID without checking password."""
    sheet = get_settings_sheet()
    records = sheet.get_all_records()
    for r in records:
        if r["ClinicID"].strip().lower() == username.strip().lower():
            return r
    return None


def _remember_login_signature(clinic_id: str, expires_at: int, password_hash: str) -> str:
    payload = f"{clinic_id.strip().lower()}|{expires_at}|{password_hash}"
    return hmac.new(
        str(SETTINGS_SHEET_ID).encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def create_remember_login_token(clinic_id: str, user_row: dict | None = None, days: int = 14) -> str:
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
    return clinic_id if hmac.compare_digest(signature, expected) else None


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
    if token:
        set_query_param("remember", token)


def clear_remember_login_token():
    clear_query_param("remember")


def default_settings_for_country(country: str = "") -> dict:
    return {
        "rules": DEFAULT_RULES.copy(),
        "exclusions": [],
        "client_exclusions": [],
        "patient_exclusions": [],
        "user_name": "",
        "user_template": DEFAULT_WA_TEMPLATE,
        "client_group_days": 1,
        "reminder_window_days": 1,
        "reminder_warning_days": 0,
        "wa_reminder_log": [],
        "deleted_reminders": [],
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
        last_login = timestamp if event == "login" else existing.get("LastLoginAtGST", "")
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


def create_clinic_account(clinic_id: str, country: str, password: str):
    clinic_id = str(clinic_id or "").strip()
    country = str(country or "").strip()
    if get_clinic_row(clinic_id):
        raise ValueError("That clinic name is already registered.")

    sheet = get_settings_sheet()
    all_vals = _gspread_retry(sheet.get_all_values)
    headers = all_vals[0] if all_vals else ["ClinicID", "PlainPassword", "PasswordHash", "SettingsJSON", "UpdatedAt"]
    settings_json = json.dumps(default_settings_for_country(country))
    row_values = [""] * len(headers)
    values_by_header = {
        "ClinicID": clinic_id,
        "PlainPassword": "",
        "PasswordHash": hash_pw(password),
        "SettingsJSON": settings_json,
        "UpdatedAt": datetime.utcnow().isoformat(),
    }
    for header, value in values_by_header.items():
        if header in headers:
            row_values[headers.index(header)] = value

    _gspread_retry(sheet.append_row, row_values, value_input_option="USER_ENTERED")
    upsert_user_tracker(clinic_id, country=country, event="created")


def update_clinic_password(clinic_id: str, new_password: str):
    """Update the password hash for the current clinic login."""
    sheet, headers, row_idx = _get_settings_row_for_clinic(clinic_id)
    password_col = _settings_col_index(headers, "PasswordHash")
    _gspread_retry(sheet.update_cell, row_idx, password_col, hash_pw(new_password))

def _to_blob(uploaded):
    # Deterministic blob for caching; avoids .read() side effects
    b = uploaded.getvalue()
    return {"name": uploaded.name, "bytes": b}

def upload_fingerprint(file_blobs) -> str:
    h = hashlib.sha256()
    for fb in file_blobs:
        h.update(str(fb["name"]).encode("utf-8"))
        h.update(b"\0")
        h.update(fb["bytes"])
        h.update(b"\0")
    return h.hexdigest()

@st.cache_data(show_spinner=False)
def summarize_uploads(file_blobs):
    datasets, summary_rows = [], []
    for fb in file_blobs:
        df, pms_name, amount_col = process_file(fb["bytes"], fb["name"])
        validate_upload_dataframe(df, fb["name"])
        pms_name = pms_name or "Canonical CSV"
        charge_dates = pd.to_datetime(df["ChargeDate"], errors="coerce")
        from_date = charge_dates.min()
        to_date = charge_dates.max()
        summary_rows.append({
            "File name": fb["name"],
            "Rows": len(df),
            "PMS": pms_name,
            "From": from_date.strftime("%d %b %Y") if pd.notna(from_date) else "-",
            "To":   to_date.strftime("%d %b %Y")   if pd.notna(to_date)   else "-"
        })
        datasets.append((pms_name, df))
    return datasets, summary_rows

@st.cache_data(show_spinner=False)
def prepare_session_bundle(df: pd.DataFrame, rules_fp: str):
    """
    Build a single, reusable bundle for the whole app:
      - Normalized keys & core date fields
      - Precomputed boolean masks for ALL categories (incl. PATIENT_VISIT)
      - VisitFlag column
      - Transactions (client- & patient-level) using 'Block' segmentation
      - patients_per_month series
    NOTE: Cache key should include (data_version, rules_fp) at call site.
    """
    import numpy as np

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
    df["ChargeDate"] = pd.to_datetime(df["ChargeDate"], errors="coerce")
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

remember_token = get_query_param("remember")
if remember_token and not st.session_state["logged_in"]:
    remembered_clinic_id = validate_remember_login_token(remember_token)
    if remembered_clinic_id:
        st.session_state["clinic_id"] = remembered_clinic_id
        st.session_state["logged_in"] = True
        st.session_state["show_top_change_password"] = False
        reset_uploaded_data_state(clear_cache=True, reset_uploader=True)
        load_settings()
        load_shared_dataset_for_clinic()
        upsert_user_tracker(
            remembered_clinic_id,
            country=st.session_state.get("user_country", ""),
            event="remembered_login",
        )
        rerun_app()
    else:
        clear_remember_login_token()

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
        st.session_state["clinic_id"] = default_username
        st.session_state["logged_in"] = True
        st.session_state["show_top_change_password"] = False
        reset_uploaded_data_state(clear_cache=True, reset_uploader=True)
        load_settings()
        load_shared_dataset_for_clinic()
        rerun_app()

if not st.session_state["logged_in"]:
    login_col, _ = st.columns([0.36, 0.64])
    with login_col:
        st.markdown("### Clinic Login")
        with st.form("clinic_login_form"):
            username = st.text_input("Clinic ID / Username", value=DEV_AUTO_LOGIN_CREDENTIALS[0])
            password = st.text_input("Password", type="password", value="")
            login_submitted = st.form_submit_button("Login", type="primary", use_container_width=True)

        if login_submitted:
            user_row = authenticate_user(username, password)
            if user_row:
                st.session_state["clinic_id"] = username
                st.session_state["logged_in"] = True
                st.session_state["show_top_change_password"] = False
                set_remember_login_token(create_remember_login_token(username, user_row))

                reset_uploaded_data_state(clear_cache=True, reset_uploader=True)
                load_settings()
                # ✅ Auto-load shared dataset from Drive into working_df
                load_shared_dataset_for_clinic()
                upsert_user_tracker(
                    username,
                    country=st.session_state.get("user_country", ""),
                    event="login",
                )

                st.success(f"✅ Welcome, {username}!")
                st.rerun()
            else:
                st.error("❌ Invalid username or password.")

        if "show_create_account" not in st.session_state:
            st.session_state["show_create_account"] = False
        if st.button("Create Account", key="toggle_create_account"):
            st.session_state["show_create_account"] = not st.session_state["show_create_account"]

        if st.session_state["show_create_account"]:
            st.markdown("### Create Account")
            with st.form("create_account_form"):
                new_clinic = st.text_input("Clinic Name (username)").strip()
                country = st.selectbox("Country", COUNTRY_OPTIONS)
                new_password = st.text_input("Set password", type="password")
                confirm_password = st.text_input("Confirm password", type="password")
                create_submitted = st.form_submit_button("Create Account", type="primary", use_container_width=True)

            if create_submitted:
                if not new_clinic or not new_password or not confirm_password:
                    st.error("Enter a clinic name and password twice.")
                elif len(new_password) < 6:
                    st.error("Password must be at least 6 characters.")
                elif new_password != confirm_password:
                    st.error("Passwords do not match.")
                else:
                    try:
                        create_clinic_account(new_clinic, country, new_password)
                        st.session_state["clinic_id"] = new_clinic
                        st.session_state["logged_in"] = True
                        st.session_state["show_top_change_password"] = False
                        set_remember_login_token(create_remember_login_token(new_clinic))
                        reset_uploaded_data_state(clear_cache=True, reset_uploader=True)
                        load_settings()
                        st.session_state["user_country"] = country
                        st.success(f"✅ Account created. Welcome, {new_clinic}!")
                        st.rerun()
                    except ValueError as e:
                        st.error(str(e))
                    except Exception:
                        st.error("Could not create account. Please try again or contact support.")
else:
    clinic_id = st.session_state.get("clinic_id", "")
    with top_account_slot.container():
        with st.popover("Account", use_container_width=False):
            if st.button("Change password", key="top_account_show_change_password", use_container_width=True):
                st.session_state["show_top_change_password"] = not st.session_state.get("show_top_change_password", False)

            if st.button("Logout", key="top_account_logout", use_container_width=True):
                clear_remember_login_token()
                for key in ["logged_in", "clinic_id"]:
                    st.session_state.pop(key, None)
                st.session_state["show_create_account"] = False
                st.session_state["show_top_change_password"] = False
                st.success("You have been logged out.")
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
                    elif len(new_password) < 6:
                        st.error("New password must be at least 6 characters.")
                    elif not authenticate_user(clinic_id, current_password):
                        st.error("Current password is incorrect.")
                    else:
                        update_clinic_password(clinic_id, new_password)
                        set_remember_login_token(create_remember_login_token(clinic_id))
                        upsert_user_tracker(
                            clinic_id,
                            country=st.session_state.get("user_country", ""),
                            event="password_changed",
                        )
                        st.session_state["show_top_change_password"] = False
                        st.success("Password updated.")

# Block access to rest of app until logged in
if not st.session_state["logged_in"]:
    st.stop()

if "rules" not in st.session_state:
    load_settings()

st.markdown(
    """
    <style>
      div[data-testid="stTabs"] div[role="tablist"] button,
      div[data-testid="stTabs"] div[role="tablist"] button p,
      div[data-testid="stTabs"] div[role="tablist"] [role="tab"],
      div[data-testid="stTabs"] div[role="tablist"] [role="tab"] p,
      button[data-baseweb="tab"],
      button[data-baseweb="tab"] p {
        font-size: 1.75rem !important;
        font-weight: 700 !important;
        line-height: 1.2 !important;
      }
      div[data-testid="stTabs"] div[role="tablist"] {
        align-items: flex-end !important;
        border-bottom: 1px solid var(--cr-border) !important;
        gap: 0.2rem !important;
        margin-bottom: 1rem !important;
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
        min-height: 2.75rem !important;
        padding: 0.45rem 0.9rem !important;
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
    </style>
    """,
    unsafe_allow_html=True,
)
consume_setup_navigation_target()
reminders_page_tab, get_started_tab, data_tab, search_terms_tab, exclusions_tab = st.tabs(
    MAIN_SECTION_TABS,
    default=st.session_state.get("main_section_tab", "Reminders"),
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
    st.session_state.pop("bundle_key", None)
    st.session_state["_search_criteria_refreshed"] = True


# === Bundle Creation (inline hash; safe if rules not set yet) ===
rules_dict = get_applied_reminder_rules()
rules_fp = _rules_fp(rules_dict)
bundle_key = (st.session_state.get("data_version", 0), rules_fp)

if st.session_state.get("working_df") is not None:
    # Build/refresh the session bundle only when data exists
    if st.session_state.get("bundle_key") != bundle_key:
        df_full, masks, tx_client, tx_patient, patients_per_month = prepare_session_bundle(
            st.session_state["working_df"], rules_fp
        )
        st.session_state["bundle"] = (df_full, masks, tx_client, tx_patient, patients_per_month)
        st.session_state["bundle_key"] = bundle_key
else:
    # No data → clear any stale bundle so downstream checks can bail gracefully
    st.session_state.pop("bundle", None)
    st.session_state.pop("bundle_key", None)

# === What data is uploaded
def render_dataset_status():
    if st.session_state.get("shared_dataset_error"):
        st.warning(f"⚠️ Could not load clinic data: {st.session_state['shared_dataset_error']}")
    elif not st.session_state.get("shared_dataset_loaded"):
        st.caption("No clinic data saved yet — upload a file to start.")

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
            if row_cols[4].button("×", key=f"remove_dataset_upload_button_{idx}_{row_key}", help="Remove this data file"):
                remove_dataset_upload_at_index(idx)
                st.rerun()

        check_cols = st.columns(3, gap="small")
        for col, check in zip(check_cols, dataset_summary_checks(normalized_rows)):
            class_name = "good" if check["good"] else "bad"
            icon = "✓" if check["good"] else "×"
            col.markdown(
                f"<div class='dataset-check {class_name}'>{icon} {html_lib.escape(check['text'])}</div>",
                unsafe_allow_html=True,
            )

def get_saved_dataset_summary_rows() -> list[dict]:
    history = normalize_dataset_upload_history(st.session_state.get("dataset_upload_history", []))
    if history:
        return history

    df_w = st.session_state.get("working_df")
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
        if "<div" in file_name.lower() or file_name == "Saved clinic data" or pms in {"", "-", "unknown", "csv"}:
            return True
    return False

def repair_dataset_upload_history_from_rows(summary_rows: list[dict]) -> bool:
    upload_history = upload_summary_rows_to_history(summary_rows, status="Saved")
    if not upload_history:
        return False
    st.session_state["dataset_upload_history"] = upload_history
    save_settings()
    return True

def render_dataset_date_range(extra_rows: list[dict] | None = None):
    rows = get_saved_dataset_summary_rows() + normalize_dataset_upload_history(extra_rows or [])
    render_dataset_summary_box("Saved clinic data", rows)

def remove_dataset_upload_at_index(remove_idx: int):
    clinic_id = st.session_state.get("clinic_id")
    if not clinic_id:
        st.error("Not logged in.")
        st.stop()

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
        current_df = load_existing_shared_df(existing_file_id, existing_name)

    target_start = parse_history_date(target.get("from"))
    target_end = parse_history_date(target.get("to"))
    remaining_df = pd.DataFrame()
    if current_df is not None and not getattr(current_df, "empty", True) and target_start is not None and target_end is not None and "ChargeDate" in current_df.columns:
        source_df = current_df.copy()
        charge_dates = pd.to_datetime(source_df["ChargeDate"], errors="coerce").dt.normalize()
        keep_mask = charge_dates.isna() | (charge_dates < target_start) | (charge_dates > target_end)
        remaining_df = source_df.loc[keep_mask].copy()

    if remaining_df.empty:
        clear_clinic_dataset_pointer(clinic_id)
        st.session_state.pop("working_df", None)
        st.session_state["shared_dataset_loaded"] = False
        st.session_state["shared_dataset_name"] = None
        st.session_state["shared_dataset_updated_at"] = ""
    else:
        out_name = existing_name or f"{clinic_id}_shared_dataset.csv"
        out_bytes = remaining_df.drop(columns=["_ChargeDate_raw"], errors="ignore").to_csv(index=False).encode("utf-8")
        new_file_id = drive_upsert_csv_bytes(
            file_bytes=out_bytes,
            filename=out_name,
            folder_id=DATASETS_FOLDER_ID,
            existing_file_id=(existing_file_id or None),
        )
        updated_at = update_clinic_dataset_pointer(clinic_id, new_file_id, out_name)
        st.session_state["working_df"] = sanitize_working_df(remaining_df)
        st.session_state["data_version"] = st.session_state.get("data_version", 0) + 1
        st.session_state["shared_dataset_loaded"] = True
        st.session_state["shared_dataset_name"] = out_name
        st.session_state["shared_dataset_updated_at"] = updated_at

    st.session_state["dataset_upload_history"] = remaining_history
    st.session_state["dataset_save_notice"] = f"Removed {target.get('file_name', 'CSV')} from saved clinic data."
    save_settings()

def consume_dataset_upload_removal():
    remove_idx_raw = get_query_param_value("remove_dataset_upload")
    if remove_idx_raw == "":
        return
    try:
        remove_idx = int(remove_idx_raw)
    except ValueError:
        remove_idx = -1
    try:
        del st.query_params["remove_dataset_upload"]
    except Exception:
        pass
    if remove_idx >= 0:
        remove_dataset_upload_at_index(remove_idx)
    st.rerun()

def render_setup_checklist():
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

    upload_done = has_data and happened_after_reset(st.session_state.get("shared_dataset_updated_at", ""))
    search_done = search_term_added and happened_after_reset(st.session_state.get("search_term_added_at", ""))
    name_done = has_sender_name and happened_after_reset(st.session_state.get("user_name_updated_at", ""))
    template_done = template_updated and happened_after_reset(st.session_state.get("wa_template_updated_at", ""))
    reminder_done = sent_after_reset()
    decline_done = action_after_reset(REMINDER_ACTION_DECLINED)

    def status(done: bool):
        if done:
            return "complete", "Done"
        return "todo", "To do"

    upload_class, upload_status = status(upload_done)
    search_class, search_status = status(search_done)
    name_class, name_status = status(name_done)
    template_class, template_status = status(template_done)
    reminders_class, reminders_status = status(reminder_done)
    decline_class, decline_status = status(decline_done)

    try:
        setup_panel = st.container(border=True)
    except TypeError:
        setup_panel = st.container()

    with setup_panel:
        st.markdown(
            '<p class="setup-intro">Six quick checks before you start using reminders.</p>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f"""
          <div class="setup-grid">
            <div class="setup-step {upload_class}">
              <div class="setup-status">{upload_status}</div>
              <div class="setup-title">1. Upload data</div>
              <div class="setup-copy">Upload a CSV, XLS, or XLSX sales plan export. One year of data is ideal so yearly reminders can be found reliably.</div>
              <a class="setup-link" href="?setup_target=upload-data" target="_self">Go to Upload Data</a>
            </div>
            <div class="setup-step {search_class}">
              <div class="setup-status">{search_status}</div>
              <div class="setup-title">2. Add new search term</div>
              <div class="setup-copy">Add at least one clinic-specific product or service so reminders match your clinic language.</div>
              <a class="setup-link" href="?setup_target=search-terms" target="_self">Go to Search Terms</a>
            </div>
            <div class="setup-step {name_class}">
              <div class="setup-status">{name_status}</div>
              <div class="setup-title">3. Set sender name</div>
              <div class="setup-copy">This fills [Your Name] in WhatsApp messages. Example: Mary from Bob's Test Vet Clinic.</div>
              <a class="setup-link" href="?setup_target=whatsapp-composer" target="_self">Go to WhatsApp Composer</a>
            </div>
            <div class="setup-step {template_class}">
              <div class="setup-status">{template_status}</div>
              <div class="setup-title">4. Update template</div>
              <div class="setup-copy">Save the WhatsApp template once so it matches your clinic tone and wording.</div>
              <a class="setup-link" href="?setup_target=template-editor" target="_self">Go to Template Editor</a>
            </div>
            <div class="setup-step {reminders_class}">
              <div class="setup-status">{reminders_status}</div>
              <div class="setup-title">5. Send your first reminder</div>
              <div class="setup-copy">Open Reminders, prepare a WhatsApp message, then mark it Sent once the client has been contacted.</div>
              <a class="setup-link" href="?setup_target=reminders" target="_self">Go to Reminders</a>
            </div>
            <div class="setup-step {decline_class}">
              <div class="setup-status">{decline_status}</div>
              <div class="setup-title">6. Decline your first reminder</div>
              <div class="setup-copy">Tick the red X to decline sending this reminder while still marking it actioned.</div>
              <a class="setup-link" href="?setup_target=reminders" target="_self">Go to Reminders</a>
            </div>
          </div>
        """,
            unsafe_allow_html=True,
        )

    reset_col, _ = st.columns([0.85, 5], gap="small")
    with reset_col:
        if st.button("↻ Reset", key="reset_get_started_checklist", help="Reset only this guide. Clinic data and settings are not deleted."):
            st.session_state["get_started_reset_at"] = datetime.utcnow().isoformat()
            save_settings()
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
    due_dates = sorted({str(x).strip() for x in cluster_df.get("DueDateFmt", []) if str(x).strip()})
    reminder_dates = sorted({str(x).strip() for x in cluster_df.get("ReminderDateFmt", []) if str(x).strip()})
    animals = sorted({str(x).strip() for x in cluster_df.get("Animal Name", []) if str(x).strip()})

    all_items = []
    for val in cluster_df.get("MatchedItems", []):
        if isinstance(val, list):
            all_items.extend([str(x).strip() for x in val if str(x).strip()])
        else:
            s = str(val).strip()
            if s:
                all_items.append(s)

    items_text = simplify_vaccine_text(format_items(sorted(set(all_items))))

    reminder_details = []
    for _, row in cluster_df.iterrows():
        animal = str(row.get("Animal Name", "")).strip() or "your pet"
        item_name = str(row.get("Item Name", "")).strip()
        if not item_name and isinstance(row.get("MatchedItems"), list):
            item_name = format_items([str(x).strip() for x in row.get("MatchedItems", []) if str(x).strip()])
        item_name = simplify_vaccine_text(item_name or "treatment")
        due_value = str(row.get("DueDateFmt") or row.get("NextDueDate") or row.get("Due Date") or "").strip()
        reminder_details.append({
            "Animal Name": animal,
            "Plan Item": item_name,
            "Due Date": due_value,
        })

    n_animals = len(set(animals))
    n_items = len(set(all_items))
    is_grouped = len(cluster_df) > 1 or (n_animals > 1) or (n_items > 1) or (len(due_dates) > 1)

    qty_sum = pd.to_numeric(cluster_df.get("Qty", pd.Series(dtype=float)), errors="coerce").sum(min_count=1)
    interval_min = pd.to_numeric(cluster_df.get("IntervalDays", pd.Series(dtype=float)), errors="coerce")
    base_min = pd.to_numeric(cluster_df.get("BaseIntervalDays", pd.Series(dtype=float)), errors="coerce")

    days_qty = int(interval_min.dropna().min()) if interval_min.notna().any() else ""
    days_base = int(base_min.dropna().min()) if base_min.notna().any() else ""

    return {
        "Reminder Date": " | ".join(reminder_dates),
        "Due Date": " | ".join(due_dates),
        "Charge Date": cluster_df.get("ChargeDateFmt", pd.Series(dtype=str)).max(),
        "Client Name": client_name,
        "Animal Name": format_items(animals),
        "Plan Item": items_text,
        "Qty": "NA" if is_grouped else qty_sum,
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

    if window_days <= 0:
        for client_name, cdf in work.sort_values(["_ReminderDateTs", "ChargeDate"], ascending=[True, True]).groupby("Client Name", dropna=False):
            for _, row in cdf.iterrows():
                out_rows.append(_summarize_client_cluster(pd.DataFrame([row]), client_name, rules))
        grouped = pd.DataFrame(out_rows)
        if grouped.empty:
            return pd.DataFrame(columns=["Reminder Date", "Due Date", "Charge Date", "Client Name", "Animal Name", "Plan Item", "Qty", "Days"])
        grouped["Qty"] = grouped["Qty"].where(
            grouped["Qty"].astype(str) == "NA",
            pd.to_numeric(grouped["Qty"], errors="coerce").fillna(0).astype(int)
        )
        return grouped[["Reminder Date", "Due Date", "Charge Date", "Client Name", "Animal Name", "Plan Item", "Qty", "Days", "ReminderDetails"]]

    max_gap_days = max(int(window_days) - 1, 0)
    for client_name, cdf in work.groupby("Client Name", dropna=False):
        cdf = cdf.sort_values(["_ReminderDateTs", "ChargeDate"], ascending=[True, True]).reset_index(drop=True)
        cluster = []
        anchor = None

        for _, row in cdf.iterrows():
            reminder_ts = row.get("_ReminderDateTs")
            if anchor is None:
                anchor = reminder_ts
                cluster = [row]
                continue

            same_cluster = pd.notna(reminder_ts) and pd.notna(anchor) and abs((reminder_ts - anchor).days) <= max_gap_days
            if same_cluster:
                cluster.append(row)
            else:
                out_rows.append(_summarize_client_cluster(pd.DataFrame(cluster), client_name, rules))
                cluster = [row]
                anchor = reminder_ts

        if cluster:
            out_rows.append(_summarize_client_cluster(pd.DataFrame(cluster), client_name, rules))

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

    matched = np.empty(n, dtype=object)
    matched[:] = [[] for _ in range(n)]

    for rule_text, settings in rules.items():
        pat = re.escape(rule_text.lower().strip())
        mask = df["ItemNorm"].str.contains(pat, na=False)
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
            for i in idxs: matched[i].append(vis)
        else:
            for i in idxs: matched[i].append(df.at[i, "Item Name"])

    df["MatchedItems"] = [list({x.strip() for x in lst if str(x).strip()}) for lst in matched]
    df["IntervalDays"] = interval_qty
    df["BaseIntervalDays"] = interval_base
    df["Reminder1Days"] = reminder_1
    df["Reminder2Days"] = reminder_2
    df["OverdueReminderDays"] = overdue_reminder
    return df


def expand_reminder_dates(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df

    out = []
    for _, row in df.iterrows():
        interval_days = pd.to_numeric(pd.Series([row.get("IntervalDays")]), errors="coerce").iloc[0]
        reminder_days = []
        for field in ("Reminder1Days", "Reminder2Days", "OverdueReminderDays"):
            value = pd.to_numeric(pd.Series([row.get(field)]), errors="coerce").iloc[0]
            if pd.notna(value) and int(value) > 0:
                reminder_days.append(int(value))

        if pd.notna(interval_days):
            reminder_days.append(int(interval_days))

        for reminder_day in sorted(set(reminder_days)):
            rec = row.copy()
            rec["ReminderDays"] = reminder_day
            rec["ReminderDate"] = rec.get("ChargeDate") + pd.to_timedelta(reminder_day, unit="D")
            rec["ReminderDateTs"] = pd.to_datetime(rec.get("ReminderDate"), errors="coerce")
            rec["ReminderDateFmt"] = (
                rec["ReminderDateTs"].strftime("%d %b %Y")
                if pd.notna(rec["ReminderDateTs"])
                else ""
            )
            out.append(rec)

    if not out:
        return df.iloc[0:0].copy()
    return pd.DataFrame(out).reset_index(drop=True)

@st.cache_data(show_spinner=False)
def ensure_reminder_columns(df: pd.DataFrame, rules: dict) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=[
            "ReminderDateFmt", "DueDateFmt", "Client Name", "ChargeDateFmt", "Animal Name",
            "MatchedItems", "Qty", "IntervalDays", "BaseIntervalDays", "Reminder1Days", "Reminder2Days", "OverdueReminderDays",
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

# --- Data section ---
with get_started_tab:
    st.markdown("<div id='getting-started' class='anchor-offset'></div>", unsafe_allow_html=True)
    st.markdown("## ✅ Get Started")
    render_setup_checklist()
    
with data_tab:
    st.markdown("<div id='data-upload' class='anchor-offset'></div>", unsafe_allow_html=True)
    st.markdown("## 📂 Upload Data")
    render_dataset_status()
    dataset_summary_slot = st.empty()
    with dataset_summary_slot.container():
        render_dataset_date_range()
    st.caption("Supported PMSs: VETport, ezyVet, Xpress, plus already-canonical CSV/XLS/XLSX files.")
    if st.session_state.get("dataset_save_notice"):
        st.success(st.session_state.pop("dataset_save_notice"))

    datasets = []
    summary_rows = []
    working_df = None
    
    # --------------------------------
    # Cached dataset loader (persistent across reruns)
    # --------------------------------
    @st.cache_resource(show_spinner=False)
    def load_persistent_dataset(file_blobs):
        return summarize_uploads(file_blobs)
    
    # --------------------------------
    # File uploader
    # --------------------------------
    render_field_label(
        st,
        "Upload sales data files",
        "Upload one or more CSV, XLS, or XLSX sales exports. Valid uploads are saved for everyone using this clinic login."
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
        st.toast("🔄 File change detected — clearing cache and refreshing data...")
    
        st.session_state["last_uploaded_files"] = current_files
        st.session_state["data_version"] = st.session_state.get("data_version", 0) + 1
        reset_uploaded_data_state(clear_cache=True)
    
        # optional but recommended
        load_shared_dataset_for_clinic()
    
        st.rerun()
    
    
    # --------------------------------
    # File upload handling
    # --------------------------------
    if files:
        file_blobs = tuple(_to_blob(f) for f in files)
        current_upload_key = upload_fingerprint(file_blobs)
    
        if st.session_state.get("last_saved_upload_key") == current_upload_key:
            try:
                _, summary_rows = load_persistent_dataset(file_blobs)
            except Exception:
                summary_rows = []
            if summary_rows and dataset_history_needs_metadata_repair(st.session_state.get("dataset_upload_history", [])):
                repair_dataset_upload_history_from_rows(summary_rows)
                st.session_state["dataset_save_notice"] = "Saved data details updated."
                st.rerun()
            st.info("This upload has already been saved for this clinic.")
        else:
            # ✅ Use cached dataset loader (faster after first run)
            try:
                datasets, summary_rows = load_persistent_dataset(file_blobs)
            except UploadValidationError as e:
                st.toast("Upload needs different columns.")
                st.warning(
                    "This upload does not look like a supported sales export. "
                    + str(e)
                    + " Please upload a file with client, patient, item, amount/quantity, and date columns."
                )
                st.stop()
            except Exception:
                st.toast("Upload could not be read.")
                st.warning(
                    "This file could not be read as a supported clinic sales export. "
                    "Please check that it is a CSV, XLS, or XLSX export with client, patient, item, amount/quantity, and date columns."
                )
                st.stop()
    
            all_pms = {p for p, _ in datasets}
            rules_fp = _rules_fp(get_applied_reminder_rules())
    
            # --- Case 1: All files from same PMS ---
            if len(all_pms) == 1 and "Undetected" not in all_pms:
                working_df = pd.concat([df for _, df in datasets], ignore_index=True)
                st.session_state["working_df"] = sanitize_working_df(working_df)
                st.caption(f"All files detected as {list(all_pms)[0]} — saving automatically.")
    
            # --- Case 2: Mixed PMS or undetected but schema-compatible ---
            else:
                try:
                    cand = pd.concat([df for _, df in datasets], ignore_index=True, sort=False)
                    required_cols = ["ChargeDate", "Client Name", "Animal Name", "Item Name", "Qty", "Amount"]
    
                    if all(c in cand.columns for c in required_cols):
                        working_df = cand
                        st.session_state["working_df"] = sanitize_working_df(working_df)
                        st.caption("Files merged into canonical schema — saving automatically.")
                    else:
                        st.warning("⚠️ PMS mismatch or missing columns. Reminders cannot be generated reliably.")
    
                except Exception as e:
                    st.warning(f"⚠️ PMS mismatch or undetected files. Reminders cannot be generated. ({e})")
                    st.session_state.pop("working_df", None)
    
            if st.session_state.get("working_df") is not None and not st.session_state["working_df"].empty:
                df_full, masks, tx_client, tx_patient, patients_per_month = prepare_session_bundle(
                    st.session_state["working_df"], rules_fp
                )
                st.session_state["bundle"] = (df_full, masks, tx_client, tx_patient, patients_per_month)
                st.session_state["bundle_key"] = (st.session_state.get("data_version", 0), rules_fp)
    
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
                        existing_df = load_existing_shared_df(existing_file_id, existing_name)
                    except Exception as e:
                        st.error(
                            "Could not load the existing clinic dataset, so this upload was not saved. "
                            f"Please try again before replacing clinic data. ({e})"
                        )
                        st.stop()
    
                existing_min, existing_max = dataset_date_bounds(existing_df)
                overlaps_existing = date_ranges_overlap(upload_min, upload_max, existing_min, existing_max)
    
                def save_uploaded_dataset(replace_overlapping_dates: bool):
                    merged_df, new_file_id, out_name = publish_dataset_for_clinic(
                        clinic_id=clinic_id,
                        new_df=new_df,
                        datasets_folder_id=DATASETS_FOLDER_ID,
                        replace_overlapping_dates=replace_overlapping_dates,
                        existing_file_id=existing_file_id,
                        existing_name=existing_name,
                        existing_df=existing_df,
                    )
    
                    st.session_state["working_df"] = sanitize_working_df(merged_df)
                    st.session_state["data_version"] = st.session_state.get("data_version", 0) + 1
                    st.session_state["shared_dataset_loaded"] = True
                    st.session_state["shared_dataset_name"] = out_name
                    existing_upload_history = st.session_state.get("dataset_upload_history", [])
                    if dataset_history_needs_metadata_repair(existing_upload_history):
                        existing_upload_history = []
                    st.session_state["dataset_upload_history"] = merge_dataset_upload_history(
                        existing_upload_history,
                        upload_summary_rows_to_history(summary_rows, status="Saved"),
                        replace_overlapping_dates=replace_overlapping_dates,
                        upload_min=upload_min,
                        upload_max=upload_max,
                    )
                    st.session_state["last_saved_upload_key"] = current_upload_key
                    st.session_state["file_uploader_reset_version"] = st.session_state.get("file_uploader_reset_version", 0) + 1
                    st.session_state["last_uploaded_files"] = []
                    st.session_state["dataset_save_notice"] = (
                        "✅ Dataset saved for this clinic. Other users with this login will load it automatically."
                    )
                    st.session_state.pop("pending_overlap_upload_key", None)
                    save_settings()
    
                    df_full, masks, tx_client, tx_patient, patients_per_month = prepare_session_bundle(
                        st.session_state["working_df"], rules_fp
                    )
                    st.session_state["bundle"] = (df_full, masks, tx_client, tx_patient, patients_per_month)
                    st.session_state["bundle_key"] = (st.session_state.get("data_version", 0), rules_fp)
    
                    st.rerun()
    
                save_uploaded_dataset(replace_overlapping_dates=overlaps_existing)
    
    # -------------------------------------
    # Clear Clinic Data
    # -------------------------------------
    st.markdown("#### Clear Clinic Data")
    confirm_reset = st.checkbox(
        "I understand this will remove clinic data for my clinic",
        key="confirm_reset_dataset",
    )
    
    if st.button(
        "Clear clinic data",
        disabled=not confirm_reset,
        help="Clear clinic data so the clinic behaves like no data is saved."
    ):
        clinic_id = st.session_state.get("clinic_id")
        if not clinic_id:
            st.error("Not logged in.")
            st.stop()
    
        # Grab current pointer so we can optionally trash it
        try:
            existing_file_id, existing_name = get_existing_dataset_pointer(clinic_id)
        except Exception as e:
            existing_file_id, existing_name = "", ""
            st.warning(f"Could not read existing dataset pointer (will still reset). ({type(e).__name__})")
    
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
        save_settings()

        # Optional: clear uploader + caches
        st.cache_data.clear()
    
        st.success("✅ Clinic data cleared. No clinic data is saved for this clinic now.")
        st.rerun()
    
# --------------------------------
# Render Tables
# --------------------------------
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
    patient_exclusions = st.session_state.get("patient_exclusions", [])
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


def render_table(df, title, key_prefix, msg_key, rules):
    if df.empty:
        st.info(f"No reminders in {title}.")
        return
    df = apply_reminder_exclusion_filters(df, rules)
    if df.empty:
        st.info("All reminders in this view are hidden by exclusions.")
        return

    show_pending_recent_reminder_warning()
    show_pending_reminder_action_status()

    active_tab, actioned_tab = st.tabs(["Active Reminders", "Actioned Reminders"])
    with active_tab:
        active_df = filter_hidden_reminders(df)
        if active_df.empty:
            st.info("All reminders have been actioned.")
        else:
            render_table_with_buttons(active_df, key_prefix, msg_key)

    with actioned_tab:
        render_actioned_reminders_tab(key_prefix)


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
    client_name = row_data.get("Client Name", "")
    now = datetime.utcnow()
    warning_message = get_recent_reminder_warning(client_name, now=now)
    queue_recent_reminder_warning(warning_message, key=f"{key_prefix}_recent_reminder_ok_{idx}")

    message = build_whatsapp_message_for_row(row_data)
    st.session_state[msg_key] = message
    st.session_state["_scroll_to_whatsapp_composer"] = True


def mark_reminder_sent_action(row_data: dict, key_prefix: str, msg_key: str, idx):
    client_name = row_data.get("Client Name", "")
    now = datetime.utcnow()
    hidden_record = get_hidden_reminder_record(row_data)
    hidden_action = str((hidden_record or {}).get("Action", "")).strip().lower()

    warning_message = get_recent_reminder_warning(client_name, now=now)
    queue_recent_reminder_warning(warning_message, key=f"{key_prefix}_recent_sent_ok_{idx}")

    message = build_whatsapp_message_for_row(row_data)
    st.session_state[msg_key] = message
    if hidden_action != REMINDER_ACTION_SENT:
        record_wa_reminder_click(client_name, now=now, row=row_data, save=False)
        record_wa_button_tracker(row_data, message, source=f"{key_prefix}_sent", now=now)
    rec = upsert_hidden_reminder(row_data, REMINDER_ACTION_SENT, message=message, now=now)
    hide_revealed_reminders_after_action(key_prefix)
    save_settings()
    st.session_state["_pending_reminder_action_status"] = {
        "message": f"Reminder for {normalize_display_case(rec['Animal Name'])} marked sent.",
    }


def decline_reminder_action(row_data: dict, key_prefix: str):
    hidden_record = get_hidden_reminder_record(row_data)
    hidden_action = str((hidden_record or {}).get("Action", "")).strip().lower()
    if hidden_action == REMINDER_ACTION_SENT:
        remove_wa_reminder_click_for_row(row_data)
    rec = upsert_hidden_reminder(row_data, REMINDER_ACTION_DECLINED, now=datetime.utcnow())
    hide_revealed_reminders_after_action(key_prefix)
    save_settings()
    st.session_state["_pending_reminder_action_status"] = {
        "message": f"Reminder for {normalize_display_case(rec['Animal Name'])} declined.",
    }


def remove_actioned_reminder_action(row_data: dict, key_prefix: str):
    hidden_record = get_hidden_reminder_record(row_data) or row_data
    hidden_action = str(hidden_record.get("Action", "")).strip().lower()
    if hidden_action == REMINDER_ACTION_SENT:
        remove_wa_reminder_click_for_row(row_data)
    remove_actioned_reminder(row_data)
    save_settings()
    st.session_state["_pending_reminder_action_status"] = {
        "message": f"Reminder for {normalize_display_case(row_data.get('Animal Name', ''))} returned to Active Reminders.",
    }


def show_pending_reminder_action_status():
    pending = st.session_state.pop("_pending_reminder_action_status", None)
    if not isinstance(pending, dict):
        return
    st.success(str(pending.get("message", "")))
    preview = str(pending.get("preview", "")).strip()
    if preview:
        st.markdown(f"**Preview:** {preview}")


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
    "Actioned By": "The name saved in the WhatsApp Composer when the reminder was actioned.",
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
    now = now or datetime.utcnow()
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
        st.caption("Set this once so prepared messages sound like they are coming from your clinic.")

        prev_name = st.session_state.get("user_name", "")
        render_field_label(
            st,
            "Your name / clinic",
            "This fills [Your Name] in prepared WhatsApp messages."
        )
        new_name = st.text_input(
            "Your name / clinic (appears in WhatsApp messages):",
            value=prev_name,
            key=f"user_name_input_{key_prefix}",
            placeholder="e.g. Mary from Neighbourhood Veterinary Clinic",
            label_visibility="collapsed",
        )
        
        # Auto-save to Google Sheets when the name changes
        if new_name != prev_name:
            st.session_state["user_name"] = new_name
            st.session_state["user_name_updated_at"] = datetime.utcnow().isoformat()
            save_settings()
            st.toast("✅ Name saved to settings.")


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
                    st.session_state["wa_template"] = new_template
                    st.session_state["user_template"] = new_template
                    st.session_state["wa_template_reviewed"] = True
                    st.session_state["wa_template_updated"] = True
                    st.session_state["wa_template_updated_at"] = datetime.utcnow().isoformat()
                    save_settings()
                    st.success("Template updated successfully!")
                    st.rerun()
        with col_reset:
            if st.button("🗑️ Reset Template", key=f"reset_template_{key_prefix}", use_container_width=True):
                st.session_state["wa_template"] = DEFAULT_WA_TEMPLATE
                st.session_state["user_template"] = DEFAULT_WA_TEMPLATE
                st.session_state["wa_template_reviewed"] = False
                st.session_state["wa_template_updated"] = False
                st.session_state["wa_template_updated_at"] = ""
                save_settings()
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
        st.caption(
            "Example: Hi [Client Name], this is [Your Name] reminding you that [Pet Name] is due for their [Item] on the [Due Date]."
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

# --------------------------------
# Prepared dataframe memo (recompute only when data/applied rules change)
# --------------------------------
def get_prepared_df(working_df: pd.DataFrame, rules: dict) -> pd.DataFrame:
    key = (st.session_state.get("data_version", 0), _rules_fp(rules), PREPARED_SCHEMA_VERSION)
    if st.session_state.get("prepared_key") != key:
        prepared = ensure_reminder_columns(working_df, rules)
        prepared = drop_early_duplicates_fast(prepared)
        prepared = expand_reminder_dates(prepared)

        st.session_state["prepared_df"] = prepared
        st.session_state["prepared_key"] = key

    return st.session_state["prepared_df"]

# --------------------------------
# Main
# --------------------------------
if st.session_state.get("working_df") is not None:
    df = st.session_state["working_df"].copy()
    applied_rules = get_applied_reminder_rules()

    with reminders_page_tab:
        st.markdown("<div id='reminders' class='anchor-offset'></div>", unsafe_allow_html=True)
        st.markdown("## 📅 Reminders")
    
        prepared = get_prepared_df(df, applied_rules)
    
        # ✅ safety: if schema changed but cache is stale, rebuild
        if "BaseIntervalDays" not in prepared.columns:
            st.error("Internal error: BaseIntervalDays missing. Rebuilding reminder cache...")
            st.session_state.pop("prepared_df", None)
            st.session_state.pop("prepared_key", None)
            # optional big hammer:
            # st.cache_data.clear()
            st.rerun()

        default_start = date.today()
        current_window_days = st.session_state.get("reminder_window_days", 1)
        try:
            current_window_days = min(30, max(0, int(current_window_days)))
        except (TypeError, ValueError):
            current_window_days = 1
        if st.session_state.get("reminder_window_days") != current_window_days:
            st.session_state["reminder_window_days"] = current_window_days

        start_col, window_col, group_col, warning_col = st.columns(4)
        with start_col:
            render_field_label(
                st,
                "Today",
                "Choose the first date to show reminders for. It defaults to today, but you can pick another date."
            )
            start_date = st.date_input(
                "Today",
                value=default_start,
                label_visibility="collapsed",
            )
        with window_col:
            render_field_label(
                st,
                "Days to look ahead",
                "0 shows the selected day only. 1 includes the selected day plus the next day."
            )
            reminder_window_days = st.number_input(
                "Days to look ahead",
                min_value=0,
                max_value=30,
                value=current_window_days,
                step=1,
                key="reminder_window_days",
                on_change=save_settings,
                label_visibility="collapsed",
            )
        with group_col:
            render_field_label(
                st,
                "Number of days to group reminders for the same client",
                "Controls how reminders for the same client are combined. 0 means no grouping; 1 groups same-day reminders."
            )
            group_days = st.number_input(
                "Number of days to group reminders for the same client",
                min_value=0,
                value=st.session_state.get("client_group_days", 1),
                step=1,
                key="client_group_days",
                on_change=save_settings,
                label_visibility="collapsed",
            )
        with warning_col:
            render_field_label(
                st,
                "Number of days for repeat-reminder warning",
                "Warns you before preparing WhatsApp if the same client had a recent reminder. Use 0 to turn warnings off."
            )
            st.number_input(
                "Number of days for repeat-reminder warning",
                min_value=0,
                value=st.session_state.get("reminder_warning_days", 0),
                step=1,
                key="reminder_warning_days",
                on_change=save_settings,
                label_visibility="collapsed",
            )
    
        render_search_criteria_refresh_notice()
    
        end_date = start_date + timedelta(days=reminder_window_days)
    
        reminder_ts = prepared.get("ReminderDateTs")
        if reminder_ts is None:
            reminder_ts = prepared.get("NextDueDateTs")
        if reminder_ts is None:
            reminder_ts = pd.to_datetime(prepared["NextDueDate"], errors="coerce")
        start_ts = pd.Timestamp(start_date)
        end_ts = pd.Timestamp(end_date)
        due2 = prepared[(reminder_ts >= start_ts) & (reminder_ts <= end_ts)].copy()
        reminders_before_exclusions = len(due2)
        due2 = apply_reminder_exclusion_filters(due2, applied_rules)
    
        if not due2.empty:
            grouped = bundle_client_reminders_by_window(due2, window_days=group_days, rules=applied_rules)
    
            render_table(grouped, f"{start_date} to {end_date}", "weekly", "weekly_message", applied_rules)
        else:
            if reminders_before_exclusions:
                st.info("All reminders in the selected date range are hidden by exclusions.")
            else:
                st.info("No reminders in the selected date range.")
    
    with search_terms_tab:
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
            st.session_state["rules"][rule]["days"] = int(days_raw)
            save_settings()
            invalidate_reminder_rule_cache()
    
        def save_rule_reminder_day(rule, field, key):
            days_raw = str(st.session_state.get(key, "")).strip()
            if days_raw == "":
                st.session_state["rules"][rule].pop(field, None)
            elif days_raw.isdigit() and int(days_raw) > 0:
                st.session_state["rules"][rule][field] = int(days_raw)
            else:
                label = {
                    "reminder_1": "Reminder 1",
                    "reminder_2": "Reminder 2",
                    "overdue_reminder": "Overdue Reminder",
                }.get(field, "Reminder")
                st.session_state["_search_terms_autosave_error"] = f"{label} must be blank or a positive integer for: {rule}"
                return
            save_settings()
            invalidate_reminder_rule_cache()
    
        def save_rule_visible_text(rule, key):
            visible_text = str(st.session_state.get(key, "")).strip()
            if visible_text:
                st.session_state["rules"][rule]["visible_text"] = visible_text
            else:
                st.session_state["rules"][rule].pop("visible_text", None)
            save_settings()
            invalidate_reminder_rule_cache()
    
        def toggle_use_qty(rule, key):
            st.session_state["rules"][rule]["use_qty"] = st.session_state[key]
            save_settings()
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

        def field_examples(first_example: str, second_example: str):
            st.markdown(
                f"""
                <div class="field-examples">
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
                            st.session_state["search_term_added_at"] = datetime.utcnow().isoformat()
                            save_settings()
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
                    st.markdown(f"<div style='padding-top:8px;'>{rule}</div>", unsafe_allow_html=True)
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
                st.session_state["rules"].pop(rule, None)
            save_settings()
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
            save_settings()
            invalidate_reminder_rule_cache()
            st.rerun()
    
        # --------------------------------
    with exclusions_tab:
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
                        st.markdown(f"<div style='padding-top:8px;'>{client_name}</div>", unsafe_allow_html=True)
                    with cols[1]:
                        if st.button("×", key=f"del_client_excl_{safe_client}", help="Remove client exclusion"):
                            st.session_state["client_exclusions"].remove(client_name)
                            save_settings()
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
                        save_settings()
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
                        st.markdown(f"<div style='padding-top:8px;'>{client_name} - {patient_name}</div>", unsafe_allow_html=True)
                    with cols[1]:
                        if st.button("×", key=f"del_patient_excl_{safe_pair}", help="Remove patient exclusion"):
                            st.session_state["patient_exclusions"].remove(exclusion)
                            save_settings()
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
                        st.session_state["patient_exclusions"].append({"client": safe_client, "patient": safe_patient})
                        save_settings()
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
                        st.markdown(f"<div style='padding-top:8px;'>{term}</div>", unsafe_allow_html=True)
                    with cols[1]:
                        if st.button("×", key=f"del_excl_{safe_term}", help="Remove item exclusion"):
                            st.session_state["exclusions"].remove(term)
                            save_settings()
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
                        save_settings()
                        st.session_state["new_rule_counter"] += 1
                        st.rerun()
                    else:
                        st.info("This exclusion already exists.")
                else:
                    st.error("Enter a valid exclusion term")
    
else:
    with reminders_page_tab:
        st.info("Upload data in the Upload Data tab to generate reminders.")
    with search_terms_tab:
        st.info("Upload data in the Upload Data tab to manage search terms.")
    with exclusions_tab:
        st.info("Upload data in the Upload Data tab to manage exclusions.")

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
                latest_date = pd.Timestamp.today()
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
FEEDBACK_SHEET_ID = "1LUK2lAmGww40aZzFpx1TSKPLvXsqmm_R5WkqXQVkf98"
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

    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

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


@st.cache_data(ttl=30)
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
    st.info("Use this to add or update clinic login credentials. Plain passwords will be visible in the Sheet for convenience.")

    with st.form("add_clinic_form"):
        new_clinic = st.text_input("Clinic ID (e.g., HappyVet)").strip()
        new_pw = st.text_input("Password (e.g., mypassword)").strip()
        submitted = st.form_submit_button("➕ Add / Update Clinic")

    if submitted:
        if not new_clinic or not new_pw:
            st.error("Please enter both Clinic ID and Password.")
        else:
            plain = new_pw
            hashed = hash_pw(new_pw)
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
                _update_password_cells(sheet, headers, row, plain, hashed, datetime.utcnow().isoformat())
                upsert_user_tracker(new_clinic, event="admin_password_update")
                st.success(f"✅ Updated password for clinic '{new_clinic}'.")
            else:
                # Add a new clinic row
                sheet.append_row([new_clinic, plain, hashed, "{}", datetime.utcnow().isoformat()])
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
    missing_export_bits = []
    if "build_quarterly_payload_full" not in globals():
        missing_export_bits.append("build_quarterly_payload_full")
    if "_json_default" not in globals():
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
                        payload, zip_bytes = build_quarterly_payload_full(
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
                        clean_payload_json = json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default, allow_nan=False)
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
                    json.dumps(st.session_state["llm_payload"], ensure_ascii=False, indent=2, default=_json_default, allow_nan=False)[:8000],
                    language="json",
                )
