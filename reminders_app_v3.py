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
import numpy as np
from gspread.exceptions import APIError
import random

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
PREPARED_SCHEMA_VERSION = 2
DRIVE_SCOPE = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]

_SPACE_RX = re.compile(r"\s+")
_CURRENCY_RX = re.compile(r"[^\d.\-]")

# --------------------------------
# Title (retention change))
# --------------------------------
title_col, tut_col = st.columns([4,1])
with title_col:
    st.title("ClinicReminders")
    st.caption("Daily reminders first. Uploads, setup, Factoids, and feedback are still available when you need them.")
st.markdown("---")

# === Drive folder where canonical datasets live ===
DATASETS_FOLDER_ID = "1omuJfEmo_nuntr5uQBJhil_Q8ZNa2Lpr"  # from Drive folder URL

# === Sheet columns you created ===
SHEET_COL_DATASET_FILE_ID = "DatasetFileId"
SHEET_COL_DATASET_FILE_NAME = "DatasetFileName"
SHEET_COL_DATASET_UPDATED_AT = "DatasetUpdatedAt"

def reset_uploaded_data_state(clear_cache: bool = True):
    """Single reset helper used by upload/reset flows."""
    for key in ["working_df", "prepared_df", "bundle", "bundle_key", "prepared_key"]:
        st.session_state.pop(key, None)
    st.session_state.pop("file_uploader_main", None)
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


def _update_dataset_pointer_cells(sheet, headers, row_idx, file_id, filename, updated_at):
    first_idx = _settings_col_index(headers, SHEET_COL_DATASET_FILE_ID)
    last_idx = _settings_col_index(headers, SHEET_COL_DATASET_UPDATED_AT)
    payload = [{
        "range": _row_range_a1(row_idx, first_idx, last_idx),
        "values": [[file_id, filename, updated_at]],
    }]
    _gspread_retry(sheet.batch_update, payload)


def _update_settings_cells(sheet, headers, row_idx, settings_json, updated_at):
    first_idx = _settings_col_index(headers, "SettingsJSON")
    last_idx = _settings_col_index(headers, "UpdatedAt")
    payload = [{
        "range": _row_range_a1(row_idx, first_idx, last_idx),
        "values": [[settings_json, updated_at]],
    }]
    _gspread_retry(sheet.batch_update, payload)


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

# Sidebar "table of contents" — simplified navigation
st.sidebar.markdown(
    """
    <div style="font-size:15px; line-height:1.85;">
      <div style="font-weight:700; margin-bottom:0.25rem;">Daily workflow</div>
      <a href="#reminders" style="text-decoration:none; display:block;">📅 Reminders</a>
      <a href="#data-upload" style="text-decoration:none; display:block;">📂 Data</a>
      <div style="font-weight:700; margin:1rem 0 0.25rem;">Reminder setup</div>
      <a href="#search" style="text-decoration:none; display:block;">🔍 Search reminders</a>
      <a href="#search-terms" style="text-decoration:none; display:block;">📝 Search terms</a>
      <a href="#exclusions" style="text-decoration:none; display:block;">🚫 Exclusions</a>
      <div style="font-weight:700; margin:1rem 0 0.25rem;">Occasional tools</div>
      <a href="#tutorial" style="text-decoration:none; display:block;">📖 User Guide</a>
      <a href="#factoids" style="text-decoration:none; display:block;">📊 Factoids</a>
      <a href="#feedback-section" style="text-decoration:none; display:block;">💬 Feedback</a>
    </div>
    """,
    unsafe_allow_html=True,
)

# --------------------------------
# CSS Styling
# --------------------------------
st.markdown(
    '''
    <style>
    .block-container h1, .block-container h2, .block-container h3 { margin-top: 0.2rem; }
    div[data-testid="stButton"] { min-height: 0px !important; height: auto !important; }
    .block-container { max-width: 100% !important; padding-left: 2rem; padding-right: 2rem; }
    h2[id] { scroll-margin-top: 80px; }
    .anchor-offset { position: relative; top: -100px; height: 0; }
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
DEV_AUTO_LOGIN = True
DEV_AUTO_LOGIN_CREDENTIALS = ("PatTest", "pat123")

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
    sheet.update_cell(row_idx, _settings_col_index(headers, SHEET_COL_DATASET_FILE_ID), file_id)
    sheet.update_cell(row_idx, _settings_col_index(headers, SHEET_COL_DATASET_FILE_NAME), filename)
    sheet.update_cell(row_idx, _settings_col_index(headers, SHEET_COL_DATASET_UPDATED_AT), datetime.utcnow().isoformat())

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


def publish_dataset_for_clinic(
    clinic_id: str,
    new_df: pd.DataFrame,
    datasets_folder_id: str,
) -> tuple[pd.DataFrame, str, str]:
    """
    Publish upload for the whole clinic:
      1) fetch existing dataset pointer from settings sheet
      2) load existing shared dataset from Drive (if any)
      3) merge + dedupe (uses your existing merge_dedupe)
      4) upload merged CSV to Drive (new file each publish)
      5) update dataset pointer columns in settings sheet

    Returns:
      (merged_df, new_file_id, out_name)
    """
    # 1) Get current pointer (if any)
    existing_file_id, existing_name = get_existing_dataset_pointer(clinic_id)

    # 2) Load existing dataset if present
    existing_df = None
    try:
        existing_df = load_existing_shared_df(existing_file_id, existing_name)
    except Exception as e:
        # show signal but still allow publish
        st.warning(f"Could not load existing shared dataset; publishing upload as new. ({e})")
        existing_df = None

    # 3) Merge + de-dupe
    if existing_df is not None and not existing_df.empty:
        merged_df = merge_dedupe(existing_df, new_df)
    else:
        merged_df = new_df

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
    update_clinic_dataset_pointer(clinic_id, new_file_id, out_name)


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
        st.session_state["user_name"] = settings.get("user_name", "")
        st.session_state["user_template"] = settings.get("user_template", DEFAULT_WA_TEMPLATE)
        st.session_state["client_group_days"] = int(settings.get("client_group_days", 1) or 1)
        st.session_state["reminder_warning_days"] = int(settings.get("reminder_warning_days", 0) or 0)
        st.session_state["wa_reminder_log"] = settings.get("wa_reminder_log", [])
    else:
        # Defaults for new clinics
        st.session_state["rules"] = DEFAULT_RULES.copy()
        st.session_state["exclusions"] = []
        st.session_state["user_name"] = ""
        st.session_state["user_template"] = DEFAULT_WA_TEMPLATE
        st.session_state["client_group_days"] = 1
        st.session_state["reminder_warning_days"] = 0
        st.session_state["wa_reminder_log"] = []


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

    wa_reminder_log = merge_wa_reminder_logs(
        get_remote_wa_reminder_log(sheet=sheet, headers=headers, row=row),
        st.session_state.get("wa_reminder_log", []),
    )
    st.session_state["wa_reminder_log"] = wa_reminder_log

    # Build the JSON blob for settings
    settings_data = {
        "rules": st.session_state["rules"],
        "exclusions": st.session_state["exclusions"],
        "user_name": st.session_state["user_name"],
        "user_template": st.session_state.get("user_template", DEFAULT_WA_TEMPLATE),
        "client_group_days": int(st.session_state.get("client_group_days", 1) or 1),
        "reminder_warning_days": int(st.session_state.get("reminder_warning_days", 0) or 0),
        "wa_reminder_log": wa_reminder_log,
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

def get_remote_wa_reminder_log(sheet=None, headers=None, row=None) -> list:
    clinic_id = st.session_state.get("clinic_id")
    if not clinic_id:
        return []

    try:
        if not (sheet and headers and row):
            sheet, headers, row = _get_settings_row_for_clinic(clinic_id)
        current_row = sheet.row_values(row)
        settings_idx = _settings_col_index(headers, "SettingsJSON") - 1
        if len(current_row) <= settings_idx or not current_row[settings_idx]:
            return []
        current_settings = json.loads(current_row[settings_idx])
        return current_settings.get("wa_reminder_log", [])
    except Exception:
        return []

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
            merged[(client_name, reminded_at)] = {
                "Client Name": client_name,
                "RemindedAt": reminded_at,
            }

    return sorted(
        merged.values(),
        key=lambda entry: _parse_reminder_log_time(entry.get("RemindedAt", "")) or datetime.min,
    )[-1000:]

def get_recent_reminder_warning(client_name: str, now: datetime | None = None) -> str | None:
    warning_days = int(st.session_state.get("reminder_warning_days", 0) or 0)
    if warning_days <= 0:
        return None

    now = now or datetime.utcnow()
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

def record_wa_reminder_click(client_name: str, now: datetime | None = None):
    now = now or datetime.utcnow()
    log = list(st.session_state.get("wa_reminder_log", []))
    log.append({
        "Client Name": str(client_name or "").strip(),
        "RemindedAt": now.isoformat(),
    })
    st.session_state["wa_reminder_log"] = log[-1000:]
    save_settings()

def show_recent_reminder_warning(message: str, key: str):
    if hasattr(st, "dialog"):
        @st.dialog("Reminder warning")
        def _warning_dialog():
            st.write(message)
            if st.button("OK", key=key):
                st.rerun()
        _warning_dialog()
    elif hasattr(st, "experimental_dialog"):
        @st.experimental_dialog("Reminder warning")
        def _warning_dialog():
            st.write(message)
            if st.button("OK", key=key):
                st.rerun()
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
    v_date_keys = {"planitem performed", "plan item performed"}
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
        for cand in ["Planitem Performed", "PlanItem Performed", "planitem performed"]:
            if cand in df.columns:
                df["ChargeDate"] = df[cand]
                break
    
    # Keep raw date strings for debugging
    if "ChargeDate" in df.columns:
        df["ChargeDate"] = parse_dates(df["ChargeDate"]).dt.normalize()
    else:
        df["ChargeDate"] = pd.NaT

    # --- 11️⃣ Add lowercase helper columns for search and reminders ---
    df["_client_lower"] = df["Client Name"].astype(str).str.lower()
    df["_animal_lower"] = df["Animal Name"].astype(str).str.lower()
    df["_item_lower"] = df["Item Name"].astype(str).str.lower()

    # --- ✅ Return normalized data ---
    return df, pms_name, amount_col
    
# === GOOGLE SHEETS CONNECTION ===
@st.cache_resource
def get_settings_sheet():
    """Connect to the shared ClinicReminders_Settings_Master sheet."""
    try:
        creds_dict = st.secrets["gcp_service_account"]
    except Exception:
        with open("google-credentials.json", "r") as f:
            creds_dict = json.load(f)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SETTINGS_SCOPE)
    client = gspread.authorize(creds)
    return client.open_by_key(SETTINGS_SHEET_ID).sheet1


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

def _to_blob(uploaded):
    # Deterministic blob for caching; avoids .read() side effects
    b = uploaded.getvalue()
    return {"name": uploaded.name, "bytes": b}

@st.cache_data(show_spinner=False)
def summarize_uploads(file_blobs):
    datasets, summary_rows = [], []
    for fb in file_blobs:
        df, pms_name, amount_col = process_file(fb["bytes"], fb["name"])
        pms_name = pms_name or "Undetected"
        from_date = pd.to_datetime(df.get("ChargeDate")).min()
        to_date   = pd.to_datetime(df.get("ChargeDate")).max()
        summary_rows.append({
            "File name": fb["name"],
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

# === LOGIN FORM (Sidebar) ===
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

if "auto_login_attempted" not in st.session_state:
    st.session_state["auto_login_attempted"] = False

if get_script_run_ctx is not None and get_script_run_ctx() is not None and not st.session_state["logged_in"] and DEV_AUTO_LOGIN and not st.session_state["auto_login_attempted"]:
    st.session_state["auto_login_attempted"] = True
    default_username, default_password = DEV_AUTO_LOGIN_CREDENTIALS
    user_row = authenticate_user(default_username, default_password)
    if user_row:
        st.session_state["clinic_id"] = default_username
        st.session_state["logged_in"] = True
        load_settings()
        load_shared_dataset_for_clinic()
        rerun_app()

if not st.session_state["logged_in"]:
    st.sidebar.markdown("### 🔑 Clinic Login")
    username = st.sidebar.text_input("Clinic ID / Username", value=DEV_AUTO_LOGIN_CREDENTIALS[0])
    password = st.sidebar.text_input("Password", type="password", value=DEV_AUTO_LOGIN_CREDENTIALS[1])
    if st.sidebar.button("Login"):
        user_row = authenticate_user(username, password)
        if user_row:
            st.session_state["clinic_id"] = username
            st.session_state["logged_in"] = True

            load_settings()
            # ✅ Auto-load shared dataset from Drive into working_df
            load_shared_dataset_for_clinic()
                    
            st.success(f"✅ Welcome, {username}!")
            st.rerun()
        else:
            st.error("❌ Invalid username or password.")
else:
    st.sidebar.success(f"Logged in as {st.session_state['clinic_id']}")

# --- 🚪 Logout button ---
if st.session_state.get("logged_in", False):
    if st.sidebar.button("🚪 Logout"):
        # Clear login state
        for key in ["logged_in", "clinic_id"]:
            st.session_state.pop(key, None)
        st.success("You have been logged out.")
        st.rerun()

# Block access to rest of app until logged in
if not st.session_state["logged_in"]:
    st.warning("Please log in to access ClinicReminders & Factoids.")
    st.stop()
    
# === Bundle Creation (inline hash; safe if rules not set yet) ===
rules_dict = st.session_state.get("rules", {})  # avoid KeyError if rules not initialized
rules_fp = hashlib.md5(json.dumps(rules_dict, sort_keys=True).encode()).hexdigest()
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
    if st.session_state.get("shared_dataset_loaded"):
        st.info(f"📌 Using shared clinic dataset: {st.session_state.get('shared_dataset_name','(unknown)')}")
    elif st.session_state.get("shared_dataset_error"):
        st.warning(f"⚠️ Could not load shared dataset: {st.session_state['shared_dataset_error']}")
    else:
        st.caption("No shared dataset published yet — upload a file to start. Remember to 'Publish' data!")

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

# Show dataset date range (shared or locally uploaded)
df_w = st.session_state.get("working_df")
df_w = drop_duplicate_columns(df_w) if df_w is not None else None

dmin, dmax = get_dataset_date_range(df_w)

if dmin is not None and dmax is not None:
    st.caption(f"Dataset range: {dmin:%d %b %Y} → {dmax:%d %b %Y} - remember to 'Publish' data!")
else:
    st.caption("Dataset range: (dates not detected) - remember to 'Publish' data!")

# --------------------------------
# 🗑️ Local hidden-reminders tracking
# --------------------------------
DELETED_REMINDERS_FILE = "deleted_reminders.json"

def load_deleted_reminders():
    if os.path.exists(DELETED_REMINDERS_FILE):
        with open(DELETED_REMINDERS_FILE, "r") as f:
            return json.load(f)
    return []

def save_deleted_reminders(deleted_list):
    with open(DELETED_REMINDERS_FILE, "w") as f:
        json.dump(deleted_list, f)

# --------------------------------
# Session state init
# --------------------------------
if "rules" not in st.session_state:
    load_settings()
st.session_state.setdefault("weekly_message", "")
st.session_state.setdefault("search_message", "")
st.session_state.setdefault("new_rule_counter", 0)
st.session_state.setdefault("form_version", 0)
st.session_state.setdefault("deleted_reminders", load_deleted_reminders())

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
        return pd.DataFrame(columns=["Due Date", "Charge Date", "Client Name", "Animal Name", "Plan Item", "Qty", "Days", "ReminderDetails"])

    out_rows = []
    work = due_df.copy()
    due_col = "DueDate" if "DueDate" in work.columns else "NextDueDate"
    work["_DueDateTs"] = pd.to_datetime(work[due_col], errors="coerce")

    for client_name, cdf in work.groupby("Client Name", dropna=False):
        cdf = cdf.sort_values(["_DueDateTs", "ChargeDate"], ascending=[True, True]).reset_index(drop=True)
        cluster = []
        anchor = None

        for _, row in cdf.iterrows():
            due_ts = row.get("_DueDateTs")
            if anchor is None:
                anchor = due_ts
                cluster = [row]
                continue

            same_cluster = pd.notna(due_ts) and pd.notna(anchor) and abs((due_ts - anchor).days) <= window_days
            if same_cluster:
                cluster.append(row)
            else:
                out_rows.append(_summarize_client_cluster(pd.DataFrame(cluster), client_name, rules))
                cluster = [row]
                anchor = due_ts

        if cluster:
            out_rows.append(_summarize_client_cluster(pd.DataFrame(cluster), client_name, rules))

    grouped = pd.DataFrame(out_rows)
    if grouped.empty:
        return pd.DataFrame(columns=["Due Date", "Charge Date", "Client Name", "Animal Name", "Plan Item", "Qty", "Days"])

    grouped["Qty"] = grouped["Qty"].where(
        grouped["Qty"].astype(str) == "NA",
        pd.to_numeric(grouped["Qty"], errors="coerce").fillna(0).astype(int)
    )
    return grouped[["Due Date", "Charge Date", "Client Name", "Animal Name", "Plan Item", "Qty", "Days", "ReminderDetails"]]
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
    return df

@st.cache_data(show_spinner=False)
def ensure_reminder_columns(df: pd.DataFrame, rules: dict) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=[
            "DueDateFmt", "Client Name", "ChargeDateFmt", "Animal Name",
            "MatchedItems", "Qty", "IntervalDays", "BaseIntervalDays",
            "NextDueDate", "NextDueDateBase", "ChargeDate"
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

    df["ChargeDateFmt"] = pd.to_datetime(df["ChargeDate"]).dt.strftime("%d %b %Y")
    df["DueDateFmt"]    = pd.to_datetime(df["NextDueDate"]).dt.strftime("%d %b %Y")

    df["MatchedItems"] = df["MatchedItems"].apply(
        lambda v: [str(x).strip() for x in v] if isinstance(v, list) else ([str(v)] if pd.notna(v) else [])
    )

    # ✅ hard guarantee column exists even if something upstream changes
    if "BaseIntervalDays" not in df.columns:
        df["BaseIntervalDays"] = pd.NA

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
st.markdown("<div id='data-upload' class='anchor-offset'></div>", unsafe_allow_html=True)
st.markdown("## 📂 Data")
render_dataset_status()

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
files = st.file_uploader(
    "Upload Sales Plan file(s)",
    type=["csv", "xls", "xlsx"],
    accept_multiple_files=True,
    key="file_uploader_main",
    help="Upload one or more PMS export files. Other clinic users will not see this upload until you publish it."
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


# --------------------------------
# File upload handling
# --------------------------------
if files:
    file_blobs = tuple(_to_blob(f) for f in files)
    # ✅ Use cached dataset loader (faster after first run)
    datasets, summary_rows = load_persistent_dataset(file_blobs)

    st.dataframe(pd.DataFrame(summary_rows), use_container_width=True)

    all_pms = {p for p, _ in datasets}
    rules_dict = st.session_state.get("rules", {})
    rules_fp = hashlib.md5(json.dumps(rules_dict, sort_keys=True).encode()).hexdigest()

    # --- Case 1: All files from same PMS ---
    if len(all_pms) == 1 and "Undetected" not in all_pms:
        working_df = pd.concat([df for _, df in datasets], ignore_index=True)
        st.session_state["working_df"] = sanitize_working_df(working_df)

        # ✅ Immediately rebuild Factoids bundle after new upload
        df_full, masks, tx_client, tx_patient, patients_per_month = prepare_session_bundle(
            st.session_state["working_df"], rules_fp
        )
        st.session_state["bundle"] = (df_full, masks, tx_client, tx_patient, patients_per_month)
        st.session_state["bundle_key"] = (st.session_state.get("data_version", 0), rules_fp)

        st.success(f"All files detected as {list(all_pms)[0]} — merging datasets.")

    # --- Case 2: Mixed PMS or undetected but schema-compatible ---
    else:
        try:
            cand = pd.concat([df for _, df in datasets], ignore_index=True, sort=False)
            required_cols = ["ChargeDate", "Client Name", "Animal Name", "Item Name", "Qty", "Amount"]

            if all(c in cand.columns for c in required_cols):
                working_df = cand
                st.session_state["working_df"] = sanitize_working_df(working_df)

                # ✅ Rebuild Factoids bundle even if PMS undetected
                df_full, masks, tx_client, tx_patient, patients_per_month = prepare_session_bundle(
                    st.session_state["working_df"], rules_fp
                )
                st.session_state["bundle"] = (df_full, masks, tx_client, tx_patient, patients_per_month)
                st.session_state["bundle_key"] = (st.session_state.get("data_version", 0), rules_fp)

                st.success("Files merged into canonical schema.")
            else:
                st.warning("⚠️ PMS mismatch or missing columns. Reminders cannot be generated reliably.")

        except Exception as e:
            st.warning(f"⚠️ PMS mismatch or undetected files. Reminders cannot be generated. ({e})")
            st.session_state.pop("working_df", None)

    # ============================
    # ✅ Publish dataset for clinic
    # ============================

    # Optional debug button (instead of calling on every rerun)
    # if st.button("Test Drive folder access (debug)"):
    #    drive_check_folder_access(DATASETS_FOLDER_ID)

    if st.session_state.get("working_df") is not None and not st.session_state["working_df"].empty:
        df_preview = st.session_state["working_df"]
        min_d = pd.to_datetime(df_preview.get("ChargeDate"), errors="coerce").min()
        max_d = pd.to_datetime(df_preview.get("ChargeDate"), errors="coerce").max()
        st.caption(
            f"Current upload date range: "
            f"{min_d.strftime('%d %b %Y') if pd.notna(min_d) else '-'} → "
            f"{max_d.strftime('%d %b %Y') if pd.notna(max_d) else '-'}"
        )

        st.markdown("### ✅ Publish dataset for the whole clinic")
        st.info(
            "This will update your shared clinic dataset.\n\n"
            "If a shared dataset already exists, the app will merge and de-duplicate overlapping rows."
        )

        if st.button(
            "📌 Publish this upload to clinic",
            help="Make this processed upload the shared dataset for everyone using this clinic login."
        ):
            clinic_id = st.session_state.get("clinic_id")
            if not clinic_id:
                st.error("Not logged in.")
                st.stop()

            new_df = st.session_state["working_df"].copy()
            new_df = new_df.drop(columns=["_ChargeDate_raw"], errors="ignore")
            new_df = ensure_min_canonical_schema(new_df)
            
            merged_df, new_file_id, out_name = publish_dataset_for_clinic(
                clinic_id=clinic_id,
                new_df=new_df,
                datasets_folder_id=DATASETS_FOLDER_ID,
            )

            st.session_state["working_df"] = sanitize_working_df(merged_df)
            st.session_state["data_version"] = st.session_state.get("data_version", 0) + 1
            st.session_state["shared_dataset_loaded"] = True
            st.session_state["shared_dataset_name"] = out_name

            # rebuild bundle immediately for this session
            df_full, masks, tx_client, tx_patient, patients_per_month = prepare_session_bundle(
                st.session_state["working_df"], rules_fp
            )
            st.session_state["bundle"] = (df_full, masks, tx_client, tx_patient, patients_per_month)
            st.session_state["bundle_key"] = (st.session_state.get("data_version", 0), rules_fp)

            st.success("✅ Published! All clinic users will now load this dataset automatically.")
            st.rerun()

# -------------------------------------
# Reset Clinic Dataset
# -------------------------------------
st.markdown("### 🧨 Reset Clinic Dataset (Testing / Wrong Upload)")
st.caption("This clears the shared dataset pointer for this clinic so the app behaves like no dataset is published.")
confirm_reset = st.checkbox(
    "I understand this will remove the shared dataset for my clinic",
    key="confirm_reset_dataset",
    help="Use this only when the wrong shared dataset was published for the clinic."
)

if st.button(
    "🗑️ Reset shared dataset for clinic",
    disabled=not confirm_reset,
    help="Clear the shared dataset pointer so the clinic behaves like no dataset is published."
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
    reset_uploaded_data_state(clear_cache=False)

    st.session_state["shared_dataset_loaded"] = False
    st.session_state["shared_dataset_name"] = None
    st.session_state["shared_dataset_error"] = None

    # Optional: clear uploader + caches
    st.cache_data.clear()

    st.success("✅ Clinic dataset reset. No shared dataset is published for this clinic now.")
    st.rerun()

# --------------------------------
# Render Tables
# --------------------------------
def render_table(df, title, key_prefix, msg_key, rules):
    if df.empty:
        st.info(f"No reminders in {title}.")
        return
    df = df.copy()
    if "Item Name" in df.columns:
        df["Plan Item"] = df["Item Name"].apply(
            lambda x: simplify_vaccine_text(get_visible_plan_item(x, rules))
        )
    elif "Plan Item" not in df.columns:
        df["Plan Item"] = ""
    if st.session_state["exclusions"]:
        excl_pattern = "|".join(map(re.escape, st.session_state["exclusions"]))
        target_col = "Item Name" if "Item Name" in df.columns else "Plan Item"
        df = df[~df[target_col].astype(str).str.lower().str.contains(excl_pattern, regex=True, na=False)]
    if df.empty:
        st.info("All rows excluded by exclusion list.")
        return
    render_table_with_buttons(df, key_prefix, msg_key)

def render_table_with_buttons(df, key_prefix, msg_key):
    # Make the WA and Hide columns the same width for clean alignment
    col_widths = [2, 2, 5, 3, 4, 1, 1, 2, 2]
    headers = ["Due Date", "Charge Date", "Client Name", "Animal Name", "Plan Item", "Qty", "Days", "WA", "Hide"]

    # --- Header row ---
    header_cols = st.columns(col_widths)
    for c, head in zip(header_cols, headers):
        align = "center" if head in ["WA", "Hide"] else "left"
        c.markdown(f"<div style='text-align:{align}; font-weight:600;'>{head}</div>", unsafe_allow_html=True)

    # --- Table rows ---
    for idx, row in df.iterrows():
        # Values for the non-action columns (everything except WA & Hide)
        vals = {h: str(row.get(h, "")) for h in headers[:-2]}

        row_cols = st.columns(col_widths, gap="small")

        # Print ONLY data columns (not the action columns)
        for j, h in enumerate(headers[:-2]):  # up to "Days"
            val = vals[h]
            if h in ["Client Name", "Animal Name", "Plan Item"]:
                val = normalize_display_case(val)
            row_cols[j].markdown(val)

        # --- WA button (aligned to its column, full-width) ---
        if row_cols[7].button("WA", key=f"{key_prefix}_wa_{idx}", use_container_width=True):
            client_name = row.get("Client Name", "")
            now = datetime.utcnow()
            warning_message = get_recent_reminder_warning(client_name, now=now)
            if warning_message:
                show_recent_reminder_warning(warning_message, key=f"{key_prefix}_recent_reminder_ok_{idx}")
            record_wa_reminder_click(client_name, now=now)

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

            st.session_state[msg_key] = message
            st.success(f"WhatsApp message prepared for {animal_name}. Scroll to the Composer below to send.")
            st.markdown(f"**Preview:** {st.session_state[msg_key]}")

        # --- Hide button (❌), aligned to its column, full-width) ---
        if row_cols[8].button("❌", key=f"{key_prefix}_hide_{idx}", use_container_width=True):
            rec = {
                "Due Date": row.get("Due Date", ""),
                "Charge Date": row.get("Charge Date", ""),
                "Client Name": row.get("Client Name", ""),
                "Animal Name": row.get("Animal Name", ""),
                "Plan Item": row.get("Plan Item", ""),
                "Qty": row.get("Qty", ""),
                "Days": row.get("Days", ""),
                "DeletedAt": datetime.now().isoformat()
            }
            st.session_state.setdefault("deleted_reminders", []).append(rec)
            save_deleted_reminders(st.session_state["deleted_reminders"])
            st.success(f"Reminder for {normalize_display_case(rec['Animal Name'])} hidden.")
            st.rerun()

    # --- Hidden count + Restore button (directly under the table) ---
    num_deleted = len(st.session_state.get("deleted_reminders", []))
    if num_deleted:
        st.caption(f"🗑️ {num_deleted} reminders hidden (use Restore to bring them back)")
        if st.button("♻️ Restore Hidden Reminders"):
            st.session_state["deleted_reminders"] = []
            save_deleted_reminders([])
            st.success("All hidden reminders restored.")
            st.rerun()

    # --- WhatsApp Composer section (after the table + restore) ---
    comp_main, comp_tip = st.columns([4, 1])
    with comp_main:
        st.write("### WhatsApp Composer")

        prev_name = st.session_state.get("user_name", "")
        new_name = st.text_input(
            "Your name / clinic (appears in WhatsApp messages):",
            value=prev_name,
            key=f"user_name_input_{key_prefix}",
            placeholder="e.g. Best Health Vet Clinic or Patrik from Best Health Vet Clinic",
            help="Saved for the clinic and used in the [Your Name] placeholder."
        )
        
        # Auto-save to Google Sheets when the name changes
        if new_name != prev_name:
            st.session_state["user_name"] = new_name
            save_settings()
            st.toast("✅ Name saved to settings.")


        if msg_key not in st.session_state:
            st.session_state[msg_key] = ""

        st.text_area(
            "Message:",
            key=msg_key,
            height=200,
            help="Prepared when you click WA in the reminders table. You can edit it before opening WhatsApp."
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
                  .phone-row input {{
                    width: 100%; height: 44px; padding: 0 12px;
                    border: 1px solid #ccc; border-radius: 6px; font-size: 16px;
                    font-family: inherit;
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
                  <div class="phone-row">
                    <input id="phoneInput" type="text" inputmode="tel"
                           placeholder="+9715XXXXXXXX" aria-label="Phone number (with country code)">
                  </div>
                  <div class="button-row">
                    <button class="wa-btn" id="waBtn">📲 Open in WhatsApp</button>
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
                    const rawPhone = document.getElementById('phoneInput').value || '';
                    const phoneClean = rawPhone.replace(/[^0-9]/g, '');
                    const encMsg = encodeURIComponent(MESSAGE_RAW || '');
                    let url = '';
                    if (phoneClean) {{
                      url = `https://wa.me/${{phoneClean}}${{encMsg ? "?text=" + encMsg : ""}}`;
                    }} else {{
                      await copyToClipboard(MESSAGE_RAW || '');
                      url = "https://wa.me/";
                    }}
                    window.open(url, '_blank', 'noopener');
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
            height=130,
        )

    st.markdown(
        "<span style='color:red; font-weight:bold;'>❗ Note:</span> "
        "WhatsApp button might not work the first time after refreshing. Use twice for normal function.",
        unsafe_allow_html=True
    )
    st.info("If you leave the phone blank, the message is auto-copied. WhatsApp opens in forward/search mode — just paste into the chat.")


    # --- WhatsApp Template Editor (unchanged) ---
    st.markdown("### 🧩 WhatsApp Template Editor")
    st.caption("Setup tool: edit only when the standard WhatsApp wording needs to change.")
    if "wa_template" not in st.session_state or not st.session_state.get("wa_template"):
        st.session_state["wa_template"] = st.session_state.get("user_template", DEFAULT_WA_TEMPLATE) or DEFAULT_WA_TEMPLATE

    ver_key = f"{key_prefix}_tmpl_ver"
    if ver_key not in st.session_state:
        st.session_state[ver_key] = 0

    editor_key = f"wa_template_editor_{key_prefix}_{st.session_state[ver_key]}"
    st.text_area(
        "Customize your WhatsApp message template:",
        value=st.session_state["wa_template"],
        height=200,
        key=editor_key,
        help="Use placeholders: [Client Name], [Your Name], [Pet Name], [Item], [Due Date]",
    )
    st.info(
        "### 🧩 How to Customize Your WhatsApp Message Template\n\n"
        "**1️⃣ Edit your message below** – you can freely rewrite it to match your clinic’s tone or language.\n\n"
        "**2️⃣ Use dynamic placeholders (square brackets)** to make messages automatically fill with client and pet details:\n"
        "- `[Client Name]` → Inserts the client’s first name  \n"
        "- `[Your Name]` → Inserts your name or clinic name (set above)  \n"
        "- `[Pet Name]` → Inserts the patient’s name(s)  \n"
        "- `[Item]` → Inserts what’s due (e.g., *Rabies Vaccine*, *Dental Exam*)  \n"
        "- `[Due Date]` → Inserts the formatted due date (e.g., *5th of September, 2025*)\n\n"
        "**3️⃣ Example:**  \n"
        "_Hi [Client Name], this is [Your Name] reminding you that [Pet Name] is due for their [Item] on the [Due Date]._  \n\n"
        "**4️⃣ Click ‘✅ Update Template’ to save**, or **‘🗑️ Reset Template’** to return to the default message."
    )

    col_update, col_reset = st.columns([1, 1])
    with col_update:
        if st.button("✅ Update Template", key=f"update_template_{key_prefix}"):
            new_template = st.session_state.get(editor_key, "").strip()
            if new_template:
                st.session_state["wa_template"] = new_template
                st.session_state["user_template"] = new_template
                save_settings()
                st.success("Template updated successfully!")
                st.rerun()
    with col_reset:
        if st.button("🗑️ Reset Template", key=f"reset_template_{key_prefix}"):
            st.session_state["wa_template"] = DEFAULT_WA_TEMPLATE
            st.session_state["user_template"] = DEFAULT_WA_TEMPLATE
            save_settings()
            st.session_state[ver_key] += 1
            st.success("Template reset to default!")
            st.rerun()

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
# Prepared dataframe memo (recompute only when data/rules change)
# --------------------------------
def _rules_fp(rules: dict) -> str:
    return hashlib.md5(json.dumps(rules, sort_keys=True).encode()).hexdigest()

def get_prepared_df(working_df: pd.DataFrame, rules: dict) -> pd.DataFrame:
    key = (st.session_state.get("data_version", 0), _rules_fp(rules), PREPARED_SCHEMA_VERSION)
    if st.session_state.get("prepared_key") != key:
        prepared = ensure_reminder_columns(working_df, rules)
        prepared = drop_early_duplicates_fast(prepared)

        st.session_state["prepared_df"] = prepared
        st.session_state["prepared_key"] = key

    return st.session_state["prepared_df"]

# --------------------------------
# Main
# --------------------------------
if st.session_state.get("working_df") is not None:
    df = st.session_state["working_df"].copy()

    # Weekly Reminders
    st.markdown("---")
    st.markdown("<h2 id='reminders'>📅 Reminders</h2>", unsafe_allow_html=True)
    st.markdown("<div id='reminders' class='anchor-offset'></div>", unsafe_allow_html=True)
    st.markdown("#### 📅 Weekly Reminders")
    st.info("💡 Daily workspace: pick a start date, review due reminders, then click WA to prepare a message.")

    prepared = get_prepared_df(df, st.session_state["rules"])

    # ✅ safety: if schema changed but cache is stale, rebuild
    if "BaseIntervalDays" not in prepared.columns:
        st.error("Internal error: BaseIntervalDays missing. Rebuilding reminder cache...")
        st.session_state.pop("prepared_df", None)
        st.session_state.pop("prepared_key", None)
        # optional big hammer:
        # st.cache_data.clear()
        st.rerun()

    latest_date = prepared["ChargeDate"].max()
    default_start = (latest_date + timedelta(days=1)).date() if pd.notna(latest_date) else date.today()

    start_date = st.date_input(
        "Start Date (7-day window)",
        value=default_start,
        help="Shows reminders due from this date through the next 6 days."
    )
    end_date = start_date + timedelta(days=6)

    due2 = prepared[
        (pd.to_datetime(prepared["NextDueDate"]) >= pd.to_datetime(start_date)) &
        (pd.to_datetime(prepared["NextDueDate"]) <= pd.to_datetime(end_date))
    ].copy()

    group_col, warning_col = st.columns(2)
    with group_col:
        group_days = st.number_input(
            "Number of days to group reminders for the same Client",
            min_value=1,
            value=st.session_state.get("client_group_days", 1),
            step=1,
            key="client_group_days",
            on_change=save_settings,
            help="Group all reminders for the same client within this many days into one reminder row."
        )
    with warning_col:
        st.number_input(
            "Number of days for repeat-reminder warning",
            min_value=0,
            value=st.session_state.get("reminder_warning_days", 0),
            step=1,
            key="reminder_warning_days",
            on_change=save_settings,
            help="Show a warning when WA is clicked for a client who already had a reminder within this many days. Use 0 to turn warnings off."
        )

    if not due2.empty:
        grouped = bundle_client_reminders_by_window(due2, window_days=group_days, rules=st.session_state.get("rules", {}))

        # Filter out deleted reminders
        deleted = st.session_state.get("deleted_reminders", [])
        if deleted:
            deleted_keys = {
                (d["Client Name"], d["Animal Name"], d["Plan Item"], d["Due Date"])
                for d in deleted
            }
            grouped = grouped[
                ~grouped.apply(
                    lambda r: (r["Client Name"], r["Animal Name"], r["Plan Item"], r["Due Date"]) in deleted_keys,
                    axis=1
                )
            ]

        render_table(grouped, f"{start_date} to {end_date}", "weekly", "weekly_message", st.session_state["rules"])
    else:
        st.info("No reminders in the selected week.")

    st.markdown("<div id='tutorial' class='anchor-offset'></div>", unsafe_allow_html=True)
    with st.expander("📖 User Guide", expanded=False):
        st.info(
            "### User Guide\n\n"
            "ClinicReminders helps you find due reminders, prepare WhatsApp messages, and keep clients engaged.\n\n"
            "### Daily workflow\n"
            "**STEP 1:** Confirm the clinic dataset is loaded, or upload and publish a new file in **Data**.  \n"
            "**STEP 2:** Use **Weekly Reminders** to see reminders due in the next 7-day window.  \n"
            "**STEP 3:** Click **WA** to prepare the WhatsApp message.  \n"
            "**STEP 4:** Use **Search Terms**, **Exclusions**, and the **WhatsApp Template Editor** only when setup needs changing.  \n\n"
            "Factoids and feedback are available further down for occasional review and support."
        )


    # --------------------------------
    # Search
    # --------------------------------
    st.markdown("---")
    st.markdown("<div id='search' class='anchor-offset'></div>", unsafe_allow_html=True)
    st.markdown("#### 🔍 Search Reminders")
    st.info("💡 Search by client, animal, or item to find upcoming reminders.")
    search_term = st.text_input(
        "Enter text to search (client, animal, or item)",
        help="Searches upcoming reminders by client name, animal name, or item text."
    )

    if search_term:
        q = search_term.lower()
        # Ensure lowercase columns exist for searching
        for col in ["Client Name", "Animal Name", "Item Name"]:
            col_lower = f"_{col.split()[0].lower()}_lower"
            if col_lower not in prepared.columns and col in prepared.columns:
                prepared[col_lower] = prepared[col].astype(str).str.lower()
    
        # Now run the query safely
        filtered2 = prepared.query(
            "_client_lower.str.contains(@q, regex=False) or _animal_lower.str.contains(@q, regex=False) or _item_lower.str.contains(@q, regex=False)",
            engine="python"
        ).copy()


        if not filtered2.empty:
            g = filtered2.groupby(["DueDateFmt", "Client Name"], dropna=False)
            grouped_search = (
                pd.DataFrame({
                    "Charge Date": g["ChargeDateFmt"].max(),
                    "Animal Name": g["Animal Name"].apply(lambda s: format_items(sorted(set(s.dropna())))),
                    "Plan Item": g["MatchedItems"].apply(
                        lambda lists: simplify_vaccine_text(
                            format_items(sorted(set(
                                i.strip() for sub in lists for i in (sub if isinstance(sub, list) else [sub]) if str(i).strip()
                            )))
                        )
                    ),
                    "Qty": g["Qty"].sum(min_count=1),
                    "Days": g["IntervalDays"].apply(
                        lambda x: int(pd.to_numeric(x, errors="coerce").dropna().min())
                        if pd.to_numeric(x, errors="coerce").notna().any()
                        else ""
                    ),
                })
                .reset_index()
                .rename(columns={"DueDateFmt": "Due Date"})
            )[["Due Date", "Charge Date", "Client Name", "Animal Name", "Plan Item", "Qty", "Days"]]

            render_table(grouped_search, "Search Results", "search", "search_message", st.session_state["rules"])
        else:
            st.info("No matches found.")

    # Rules editor (unchanged UI; behavior preserved)
    st.markdown("---")
    st.markdown("<div id='search-terms' class='anchor-offset'></div>", unsafe_allow_html=True)
    st.markdown("#### 📝 Search Terms")
    st.info(
        "### 🧩 How to Manage Search Terms\n\n"
        "**1️⃣ View and edit all existing Search Terms** — each term represents a product or service that generates a reminder (e.g., *Rabies*, *Bravecto*, *Dental*).\n\n"
        "**2️⃣ Set the recurrence interval (‘Days’)** — how long until the next reminder appears.  \n"
        "Example: 90 days for Bravecto, 365 days for Vaccinations.\n\n"
        "**3️⃣ Choose whether to use the ‘Qty’ column** — if checked, the reminder multiplies the interval by quantity.  \n"
        "Example: *2× Bravecto* = 180 days.\n\n"
        "**4️⃣ Edit the ‘Visible Text’** — this is what appears inside the WhatsApp message instead of the raw product name.  \n"
        "Example: *bravecto* → **Bravecto Tablet**, *rabies* → **Rabies Vaccine**.\n\n"
        "**5️⃣ You can also delete outdated terms or add new ones at the bottom of the section.**"
    )

    cols = st.columns([3,1,1,2,0.7])
    with cols[0]: st.markdown("**Rule**")
    with cols[1]: st.markdown("**Days**")
    with cols[2]: st.markdown("**Use Qty**")
    with cols[3]: st.markdown("**Visible Text**")
    with cols[4]: st.markdown("**Delete**")

    new_values, to_delete = {}, []
    def toggle_use_qty(rule, key):
        st.session_state["rules"][rule]["use_qty"] = st.session_state[key]
        save_settings()
        st.rerun()

    for rule, settings in sorted(st.session_state["rules"].items(), key=lambda x: x[0]):
        ver = st.session_state["form_version"]
        safe_rule = re.sub(r'[^a-zA-Z0-9_-]', '_', rule)
        with st.container():
            cols = st.columns([3,1,1,2,0.7], gap="small")
            with cols[0]:
                st.markdown(f"<div style='padding-top:8px;'>{rule}</div>", unsafe_allow_html=True)
            with cols[1]:
                new_values.setdefault(rule, {})["days"] = st.text_input(
                    "Days", value=str(settings["days"]),
                    key=f"days_{safe_rule}_{ver}", label_visibility="collapsed",
                    help="How many days after the charge date this item should become due again."
                )
            with cols[2]:
                st.checkbox(
                    "Use Qty", value=settings["use_qty"],
                    key=f"useqty_{safe_rule}_{ver}",
                    on_change=toggle_use_qty,
                    args=(rule, f"useqty_{safe_rule}_{ver}",),
                    help="When enabled, quantity multiplies the recurrence interval."
                )
            with cols[3]:
                new_values[rule]["visible_text"] = st.text_input(
                    "Visible Text", value=settings.get("visible_text",""),
                    key=f"vis_{safe_rule}_{ver}", label_visibility="collapsed",
                    help="Optional friendly wording shown in tables and WhatsApp messages."
                )
            with cols[4]:
                if st.button("❌", key=f"del_{safe_rule}_{ver}"):
                    to_delete.append(rule)

    if to_delete:
        for rule in to_delete:
            st.session_state["rules"].pop(rule, None)
        save_settings()
        st.rerun()

    colU, colR, colTip = st.columns([2,1,2])
    with colU:
        if st.button("Update", help="Save changes to recurrence intervals and visible text."):
            updated = {}
            for rule, settings in st.session_state["rules"].items():
                d = int(new_values.get(rule, {}).get("days", settings["days"]))
                vis = new_values.get(rule, {}).get("visible_text", settings.get("visible_text", ""))
                if vis.strip() == "":
                    updated[rule] = {"days": d, "use_qty": settings["use_qty"]}
                else:
                    updated[rule] = {"days": d, "use_qty": settings["use_qty"], "visible_text": vis.strip()}
            st.session_state["rules"] = updated
            save_settings()
            # invalidate prepared cache because rules changed
            st.session_state.pop("prepared_df", None)
            st.session_state.pop("prepared_key", None)
            st.rerun()

    with colR:
        if st.button("Reset defaults", help="Restore the default search terms and clear exclusions."):
            st.session_state["rules"] = DEFAULT_RULES.copy()
            st.session_state["exclusions"] = []
            st.session_state["form_version"] += 1
            save_settings()
            st.session_state.pop("prepared_df", None)
            st.session_state.pop("prepared_key", None)
            st.rerun()

    with colTip:
        st.markdown("### 💡 Tip")
        st.info(
            "Click **Update** to save changes to Recurrence Intervals or Visible Text.\n\n"
            "Click **Reset defaults** to restore rules and exclusions to your defaults."
        )

    st.markdown("---")
    st.write("### Add New Search Term")
    st.info("💡 Add a new **Search Term** (e.g., Cardisure), set its days, whether to use quantity, and optional visible text.")
    row_id = st.session_state['new_rule_counter']
    c1, c2, c3, c4, c5 = st.columns([3,1,1,2,0.7], gap="small")
    with c1:
        new_rule_name = st.text_input(
            "Rule name",
            key=f"new_rule_name_{row_id}",
            help="Text to look for in the PMS item name, such as bravecto, rabies, or librela."
        )
    with c2:
        new_rule_days = st.text_input(
            "Days",
            key=f"new_rule_days_{row_id}",
            help="Positive integer number of days until this item should be due again."
        )
    with c3:
        new_rule_use_qty = st.checkbox(
            "Use Qty",
            key=f"new_rule_useqty_{row_id}",
            help="Use when quantity should extend the reminder interval."
        )
    with c4:
        new_rule_visible = st.text_input(
            "Visible Text (optional)",
            key=f"new_rule_vis_{row_id}",
            help="Friendly wording to show users and clients, such as Bravecto Tablet."
        )
    with c5:
        if st.button("➕ Add", key=f"add_{row_id}"):
            if new_rule_name and str(new_rule_days).isdigit():
                safe_rule = new_rule_name.strip().lower()
                rule_data = {"days": int(new_rule_days), "use_qty": bool(new_rule_use_qty)}
                if new_rule_visible.strip():
                    rule_data["visible_text"] = new_rule_visible.strip()
                st.session_state["rules"][safe_rule] = rule_data
                save_settings()
                st.session_state["new_rule_counter"] += 1
                st.session_state.pop("prepared_df", None)
                st.session_state.pop("prepared_key", None)
                st.rerun()
            else:
                st.error("Enter a name and valid integer for days")

    # --------------------------------
    # Exclusions
    # --------------------------------
    st.markdown("---")
    st.markdown("<div id='exclusions' class='anchor-offset'></div>", unsafe_allow_html=True)
    st.markdown("#### 🚫 Exclusions")
    st.info("💡 Add terms here to automatically hide reminders that contain them.")
    if st.session_state["exclusions"]:
        for term in sorted(st.session_state["exclusions"]):
            safe_term = re.sub(r'[^a-zA-Z0-9_-]', '_', term)
            with st.container():
                cols = st.columns([6,1], gap="small")
                with cols[0]:
                    st.markdown(f"<div style='padding-top:8px;'>{term}</div>", unsafe_allow_html=True)
                with cols[1]:
                    if st.button("❌", key=f"del_excl_{safe_term}"):
                        st.session_state["exclusions"].remove(term)
                        save_settings()
                        st.rerun()
    else:
        st.error("No exclusions yet.")

    row_id = st.session_state['new_rule_counter']
    c1, c2 = st.columns([4,1], gap="small")
    with c1:
        new_excl = st.text_input(
            "Add New Exclusion Term",
            key=f"new_excl_{row_id}",
            help="Any reminder containing this text will be hidden from reminder tables."
        )
    with c2:
        if st.button("➕ Add Exclusion", key=f"add_excl_{row_id}"):
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

# --------------------------------
# 📊 Factoids Section (Password Protected)
# --------------------------------
st.markdown("<div id='factoids' class='anchor-offset'></div>", unsafe_allow_html=True)
st.markdown("## 📊 Factoids")
st.caption("Occasional reporting area. Most reminder users can leave this locked and continue working above.")

# --- Simple password gate — hides all content until unlocked
if "factoids_unlocked" not in st.session_state:
    st.session_state["factoids_unlocked"] = False

if not st.session_state["factoids_unlocked"]:
    st.info("🔒 Enter password to view Factoids (admin/manager access only).")

    with st.form("unlock_factoids_form"):
        password_input = st.text_input(
            "Enter password to view Factoids",
            type="password",
            key="factoids_password"
        )
        submitted = st.form_submit_button("Unlock Factoids")

    if submitted:
        if password_input == "clinic123":
            st.session_state["factoids_unlocked"] = True
            st.success("✅ Access granted. Loading Factoids...")
            st.rerun()
        else:
            st.error("❌ Incorrect password. Please try again.")

# --- Only show Factoids after unlock ---
if st.session_state["factoids_unlocked"]:

    # Guard: ensure the session bundle (df_full, masks, tx_client, tx_patient, patients_per_month) exists
    if "bundle" not in st.session_state:
        st.warning("Upload data first to enable Factoids.")
    else:
        df_full, masks, tx_client, tx_patient, patients_per_month = st.session_state["bundle"]
        rules_fp = _rules_fp(st.session_state["rules"])
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
                "<h4 style='font-size:17px;font-weight:700;color:#475569;margin-top:1rem;margin-bottom:0.4rem;'>💰 Revenue & Transactions</h4>",
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
                "<h4 style='font-size:17px;font-weight:700;color:#475569;margin-top:1rem;margin-bottom:0.4rem;'>👥 Clients & Patients</h4>",
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
            "<h4 style='font-size:17px;font-weight:700;color:#475569;margin-top:1rem;margin-bottom:0.4rem;'>💵 Revenue Breakdown by Month</h4>",
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
            "<h4 style='font-size:17px;font-weight:700;color:#475569;margin-top:1rem;margin-bottom:0.4rem;'>⭐ Patient Breakdown %'s</h4>",
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
                border:1px solid #94a3b8;padding:16px;border-radius:10px;text-align:center;
                margin-bottom:12px;min-height:120px;display:flex;flex-direction:column;justify-content:center;'>
                <div style='font-size:13px;color:#334155;font-weight:600;'>{label}</div>
                <div style='font-size:{fs}px;font-weight:700;color:#0f172a;margin-top:6px;'>{val}</div></div>"""
        
            def _fs(v: str) -> int:
                return 16 if len(v) > 25 else (20 if len(v) > 18 else 22)
        
            def cardgroup(title: str, keys: list[str]):
                show = [k for k in keys if k in metrics]
                if not show:
                    return
                st.markdown(
                    f"<h4 style='font-size:17px;font-weight:700;color:#475569;margin-top:1rem;margin-bottom:0.4rem;'>{title} – {period_label}</h4>",
                    unsafe_allow_html=True
                )
                cols = st.columns(5)
                for i, k in enumerate(show):
                    v  = metrics[k]
                    fs = _fs(v); bg = "#f1f5f9"
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

st.markdown("<div id='feedback-section' class='anchor-offset'></div>", unsafe_allow_html=True)
st.markdown("## 💬 Feedback")
st.markdown("### Found a problem? Let me (Patrik) know here:")

# Wrap inputs in a form to avoid reruns per keystroke
with st.form("feedback_form"):
    feedback_text = st.text_area(
        "Describe the issue or suggestion",
        key="feedback_text",
        height=120,
        placeholder="What did you try? What happened? Any screenshots or CSV names?",
    )
    user_name_for_feedback = st.text_input("Your name (optional)", key="feedback_name", placeholder="Clinic / Your name")
    user_email_for_feedback = st.text_input("Your email (optional)", key="feedback_email", placeholder="you@example.com")
    submitted_fb = st.form_submit_button("Send")

if submitted_fb:
    if not feedback_text.strip():
        st.error("Please enter a message before sending.")
    else:
        try:
            insert_feedback(user_name_for_feedback, user_email_for_feedback, feedback_text.strip())
            st.success("Thanks! Your message has been recorded.")
            for k in ["feedback_text","feedback_name","feedback_email"]:
                if k in st.session_state:
                    del st.session_state[k]
        except Exception as e:
            st.error(f"Could not save your message: {e}")

# --------------------------------
#  👩‍⚕️ ADMIN TOOLS
# --------------------------------

# Only show to a special admin account (for example, “Admin”)
if st.session_state.get("clinic_id") == "Admin":
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
                st.success(f"✅ Updated password for clinic '{new_clinic}'.")
            else:
                # Add a new clinic row
                sheet.append_row([new_clinic, plain, hashed, "{}", datetime.utcnow().isoformat()])
                st.success(f"✅ Added new clinic '{new_clinic}'.")

else:
    st.caption("Admin-only clinic management hidden. Log in as Admin to access it.")
    
# --------------------------------
# 🧷 Nova Vet Family Admin Access (Password Protected)
# --------------------------------
st.markdown("---")
st.markdown("### 🧷 Nova Vet Family Admin Access")

# Password gate (separate from Factoids)
if "admin_unlocked" not in st.session_state:
    st.session_state["admin_unlocked"] = False

if not st.session_state["admin_unlocked"]:
    st.info("🔒 Enter password.")

    with st.form("unlock_admin_form"):
        admin_pw = st.text_input(
            "Enter password for Nova Vet Family Admin Access",
            type="password",
            key="admin_pw_input"
        )
        submitted_admin = st.form_submit_button("Unlock")

    if submitted_admin:
        if admin_pw == "Nova@2025":
            st.session_state["admin_unlocked"] = True
            st.success("✅ Access granted. Admin tools unlocked!")
            st.rerun()
        else:
            st.error("❌ Incorrect password. Please try again.")

# --------------------------------
# If unlocked → show Keyword Debugging + Quarterly LLM Export
# --------------------------------
if st.session_state["admin_unlocked"]:
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
else:
    st.info("🔒 NVF admin-only sections are locked.")
