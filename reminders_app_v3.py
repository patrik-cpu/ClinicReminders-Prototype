import pandas as pd
import altair as alt
import unicodedata
import streamlit as st
import re
import json, os, time
import streamlit.components.v1 as components
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import date, datetime, timedelta
import hashlib
import numpy as np

@st.cache_data(ttl=30)
def fetch_feedback_cached(limit=500):
    return fetch_feedback(limit)

_SPACE_RX = re.compile(r"\s+")
_CURRENCY_RX = re.compile(r"[^\d.\-]")

# --------------------------------
# Title
# --------------------------------
title_col, tut_col = st.columns([4,1])
with title_col:
    st.title("ClinicReminders & Factoids Prototype v5.4")
st.markdown("---")

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
    <ul style="list-style-type:none; padding-left:0; line-height:1.8; font-size:16px;">
      <li><a href="#tutorial" style="text-decoration:none;">📖 !Tutorial - Read</a></li>
      <li><a href="#data-upload" style="text-decoration:none;">📂 Data Upload</a></li>
      <li><a href="#reminders" style="text-decoration:none;">📅 Reminders</a></li>
        <ul style="list-style-type:none; padding-left:1.2em; line-height:1.6;">
          <li><a href="#weekly-reminders" style="text-decoration:none;">🔹 Weekly Reminders</a></li>
          <li><a href="#search" style="text-decoration:none;">🔹 Search</a></li>
          <li><a href="#search-terms" style="text-decoration:none;">🔹 Search Terms</a></li>
          <li><a href="#exclusions" style="text-decoration:none;">🔹 Exclusions</a></li>
        </ul>
      <li><a href="#factoids" style="text-decoration:none;">📊 Factoids</a></li>
        <ul style="list-style-type:none; padding-left:1.2em; line-height:1.6;">
          <li><a href="#factoids-monthlycharts" style="text-decoration:none;">🔹 Monthly Charts</a></li>
          <li><a href="#factoids-ataglance" style="text-decoration:none;">🔹 At a Glance</a></li>
          <li><a href="#factoids-tables" style="text-decoration:none;">🔹 Tables</a></li>
        </ul>
      <li><a href="#feedback-section" style="text-decoration:none;">💬 Feedback</a></li>
    </ul>
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
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

# === GOOGLE SHEETS CONNECTION ===
@st.cache_resource
def get_settings_sheet():
    """Connect to the shared ClinicReminders_Settings_Master sheet."""
    try:
        creds_dict = st.secrets["gcp_service_account"]
    except Exception:
        with open("google-credentials.json", "r") as f:
            creds_dict = json.load(f)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPE)
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


# === LOGIN FORM (Sidebar) ===
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

if not st.session_state["logged_in"]:
    st.sidebar.markdown("### 🔑 Clinic Login")
    username = st.sidebar.text_input("Clinic ID / Username")
    password = st.sidebar.text_input("Password", type="password")
    if st.sidebar.button("Login"):
        user_row = authenticate_user(username, password)
        if user_row:
            st.session_state["clinic_id"] = username
            st.session_state["logged_in"] = True
            st.success(f"✅ Welcome, {username}!")
            st.rerun()
        else:
            st.error("❌ Invalid username or password.")
else:
    st.sidebar.success(f"Logged in as {st.session_state['clinic_id']}")

# Block access to rest of app until logged in
if not st.session_state["logged_in"]:
    st.warning("Please log in to access ClinicReminders & Factoids.")
    st.stop()


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
    else:
        # Defaults for new clinics
        st.session_state["rules"] = DEFAULT_RULES.copy()
        st.session_state["exclusions"] = []
        st.session_state["user_name"] = ""
        st.session_state["user_template"] = DEFAULT_WA_TEMPLATE


def save_settings():
    """Save current clinic’s settings back to the Google Sheet."""
    clinic_id = st.session_state.get("clinic_id")
    if not clinic_id:
        return

    sheet = get_settings_sheet()
    all_vals = sheet.get_all_values()
    headers = all_vals[0]
    clinic_col = headers.index("ClinicID") + 1

    # Find the existing row for this clinic (2-based index since row 1 is headers)
    row = None
    for i, r in enumerate(all_vals[1:], start=2):
        if r[clinic_col - 1].strip().lower() == clinic_id.lower():
            row = i
            break

    # Build the JSON blob for settings
    settings_data = {
        "rules": st.session_state["rules"],
        "exclusions": st.session_state["exclusions"],
        "user_name": st.session_state["user_name"],
        "user_template": st.session_state.get("user_template", DEFAULT_WA_TEMPLATE),
    }
    settings_json = json.dumps(settings_data)
    updated_at = datetime.utcnow().isoformat()

    # Update existing row or append a new one
    if row:
        sheet.update_cell(row, headers.index("SettingsJSON") + 1, settings_json)
        sheet.update_cell(row, headers.index("UpdatedAt") + 1, updated_at)
    else:
        sheet.append_row([clinic_id, "", settings_json, updated_at])

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
# 👩‍⚕️ Admin – Add or Reset Clinic Accounts
# --------------------------------
st.markdown("---")
st.markdown("### 👩‍⚕️ Admin: Add or Reset Clinic Accounts")

# Only show to a special admin account (for example, “Admin”)
if st.session_state.get("clinic_id") == "Admin":
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
                sheet.update_cell(row, headers.index("PlainPassword") + 1, plain)
                sheet.update_cell(row, headers.index("PasswordHash") + 1, hashed)
                sheet.update_cell(row, headers.index("UpdatedAt") + 1, datetime.utcnow().isoformat())
                st.success(f"✅ Updated password for clinic '{new_clinic}'.")
            else:
                # Add a new clinic row
                sheet.append_row([new_clinic, plain, hashed, "{}", datetime.utcnow().isoformat()])
                st.success(f"✅ Added new clinic '{new_clinic}'.")

else:
    st.caption("Admin-only clinic management hidden. Log in as Admin to access it.")


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
    v_keys = {"planitem performed", "plan item amount"}
    x_keys = {"date", "animal name", "amount", "item name"}
    e_keys = {"invoice date", "total invoiced (excl)", "product name", "first name", "last name"}
    if v_keys.issubset(normalized_cols): return "VETport"
    if e_keys.issubset(normalized_cols): return "ezyVet"
    if x_keys.issubset(normalized_cols): return "Xpress"
    for pms_name, definition in PMS_DEFINITIONS.items():
        required = set(normalize_columns(definition["columns"]))
        if required.issubset(normalized_cols):
            return pms_name
    return None

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
# --------------------------------
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
        dt = pd.to_datetime(date_str, format="%d %b %Y", errors="coerce")
        if pd.isna(dt):
            return date_str
        day = dt.day
        suffix = "th" if 10 <= day % 100 <= 20 else {1:"st",2:"nd",3:"rd"}.get(day%10,"th")
        return f"{day}{suffix} of {dt.strftime('%B')}, {dt.year}"
    except Exception:
        return date_str

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

# -------------------------
# Vectorized interval mapping
# -------------------------
@st.cache_data(show_spinner=False)
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
    interval = pd.Series(pd.NA, index=df.index, dtype="Float64")
    matched = np.empty(n, dtype=object)
    matched[:] = [[] for _ in range(n)]

    for rule_text, settings in rules.items():
        pat = re.escape(rule_text.lower().strip())
        mask = df["ItemNorm"].str.contains(pat, na=False)
        if not mask.any():
            continue

        days = int(settings["days"])
        if settings.get("use_qty"):
            qty = pd.to_numeric(df.loc[mask, "Qty"], errors="coerce").fillna(1).astype(int).clip(lower=1)
            cand = qty * days
        else:
            cand = pd.Series(days, index=df.index)[mask]

        interval = interval.where(~mask, pd.concat([interval[mask], cand], axis=1).min(axis=1))

        vis = settings.get("visible_text", "").strip()
        idxs = df.index[mask]
        if vis:
            for i in idxs: matched[i].append(vis)
        else:
            for i in idxs: matched[i].append(df.at[i, "Item Name"])

    df["MatchedItems"] = [list({x.strip() for x in lst if str(x).strip()}) for lst in matched]
    df["IntervalDays"] = interval
    return df

@st.cache_data(show_spinner=False)
def ensure_reminder_columns(df: pd.DataFrame, rules: dict) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=[
            "DueDateFmt", "Client Name", "ChargeDateFmt", "Animal Name",
            "MatchedItems", "Qty", "IntervalDays", "NextDueDate", "ChargeDate"
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
    df = map_intervals_vec(df, rules)
    days = pd.to_numeric(df["IntervalDays"], errors="coerce")
    df["NextDueDate"] = df["ChargeDate"] + pd.to_timedelta(days, unit="D")
    df["ChargeDateFmt"] = pd.to_datetime(df["ChargeDate"]).dt.strftime("%d %b %Y")
    df["DueDateFmt"]    = pd.to_datetime(df["NextDueDate"]).dt.strftime("%d %b %Y")
    df["MatchedItems"] = df["MatchedItems"].apply(
        lambda v: [str(x).strip() for x in v] if isinstance(v, list) else ([str(v)] if pd.notna(v) else [])
    )
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
        df = pd.read_csv(file)
    elif lowerfn.endswith((".xls", ".xlsx")):
        df = pd.read_excel(file)
    else:
        raise ValueError("Unsupported file type")

    # --- Clean up column headers early (strip ALL whitespace and normalize unicode) ---
    def clean_header(h):
        if not isinstance(h, str):
            h = str(h)
        return unicodedata.normalize("NFKC", h).replace("\u00a0", " ").replace("\ufeff", "").strip()
    
    df.columns = [clean_header(c) for c in df.columns]


    # --- 3️⃣ Case-insensitive map for reliable lookups ---
    lower_map = {c.lower(): c for c in df.columns}

    # --- 4️⃣ Detect PMS ---
    pms_name = detect_pms(df)
    if not pms_name:
        return df, None, None

    # --- 5️⃣ Vetport: force canonical column order immediately ---
    if pms_name == "VETport":
        expected_cols = [
            "planitem performed", "client name", "client id", "patient name",
            "patient id", "plan item id", "plan item name", "plan item quantity",
            "performed staff", "plan item amount", "returned quantity",
            "returned date", "invoice no"
        ]
        # Reorder in a case-insensitive way
        cols_present = [lower_map.get(c, c) for c in expected_cols if c in lower_map]
        df = df[cols_present + [c for c in df.columns if c not in cols_present]]

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
        # Last resort: fallback to known Vetport variants
        for cand in ["Planitem Performed", "PlanItem Performed", "planitem performed"]:
            if cand in df.columns:
                df["ChargeDate"] = df[cand]
                break
    if "ChargeDate" in df.columns:
        df["ChargeDate"] = parse_dates(df["ChargeDate"]).dt.normalize()
    else:
        df["ChargeDate"] = pd.NaT  # guarantee existence

    # --- 11️⃣ Add lowercase helper columns for search and reminders ---
    df["_client_lower"] = df["Client Name"].astype(str).str.lower()
    df["_animal_lower"] = df["Animal Name"].astype(str).str.lower()
    df["_item_lower"] = df["Item Name"].astype(str).str.lower()

    # --- ✅ Return normalized data ---
    return df, pms_name, amount_col


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

    df = df.copy()

    # ---- Core columns/prep (once) ----
    df["ChargeDate"] = pd.to_datetime(df["ChargeDate"], errors="coerce")
    df["DateOnly"]   = df["ChargeDate"].dt.normalize()
    df["Month"]      = df["ChargeDate"].dt.to_period("M")
    df["Year"]       = df["ChargeDate"].dt.year
    df["MonthNum"]   = df["ChargeDate"].dt.month

    def _norm(s: pd.Series) -> pd.Series:
        return (
            s.astype(str)
             .str.normalize("NFKC").str.lower()
             .str.replace(r"[\u00A0\u200B]", "", regex=True)
             .str.strip().str.replace(r"\s+", " ", regex=True)
        )

    df["ClientKey"] = _norm(df.get("Client Name", pd.Series(index=df.index)))
    df["AnimalKey"] = _norm(df.get("Animal Name", pd.Series(index=df.index)))
    df["ItemNorm"]  = _norm(df.get("Item Name", pd.Series(index=df.index)))

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



# --------------------------------
# Tutorial section
# --------------------------------
st.markdown("<div id='tutorial' class='anchor-offset'></div>", unsafe_allow_html=True)
st.markdown("<h2 id='tutorial'>📖 Tutorial - Read me first!</h2>", unsafe_allow_html=True)
st.info(
    "### 🧭 READ THIS FIRST!\n"
    "This prototype does two main things:\n\n"
    "1️⃣ **Sets Reminders** for all sorts of things — Vaccines, Dentals, Flea/Worm, Librela/Solensia, and anything else.  \n"
    "2️⃣ **Shows you interesting Factoids** about your clinic. Use the sidebar on the left to navigate.\n\n"
    "### 📋 How to use:\n"
    "**STEP 1:** Upload your data. Patrik has probably provided you with this.  \n"
    "**STEP 2:** Look at the *Weekly Reminders* section. It shows reminders due starting the week after the latest date in your data.  \n"
    "**STEP 3:** Click the *WA* button to generate a template WhatsApp message for copying or direct sending.  \n"
    "**STEP 4:** *Search Terms* (which control what reminders are generated) can be added, modified, or deleted.  \n"
    "**STEP 5:** View the *Factoids* section for lots of insights! Contact Patrik for a full walk-through.  \n\n"
    "There's more you can do, but this should be enough to get you started."
)

# --- Upload Data section ---
st.markdown("<div id='data-upload' class='anchor-offset'></div>", unsafe_allow_html=True)
st.markdown("## 📂 Data Upload")

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
    key="file_uploader_main"
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

    # Clear all Streamlit caches
    st.cache_data.clear()
    st.cache_resource.clear()

    # Reset version and working state
    st.session_state["last_uploaded_files"] = current_files
    st.session_state["data_version"] = st.session_state.get("data_version", 0) + 1

    for key in ["working_df", "prepared_df", "bundle", "bundle_key", "prepared_key"]:
        st.session_state.pop(key, None)

    st.caption("🧹 Cache cleared — data will be reprocessed on next upload.")

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
        st.session_state["working_df"] = working_df

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
                st.session_state["working_df"] = working_df

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
            first_name = normalize_display_case(row.get("Client Name", "")).split()[0].strip() if row.get("Client Name") else "there"
            animal_name = normalize_display_case(row.get("Animal Name", "")).strip() if row.get("Animal Name") else "your pet"
            plan_for_msg = normalize_display_case(row.get("Plan Item", "")).strip()
            user = st.session_state.get("user_name", "").strip()
            due_date_fmt = format_due_date(str(row.get("Due Date", "")))

            template = (st.session_state.get("user_template", "") or DEFAULT_WA_TEMPLATE).strip()

            def replace_case_insensitive(text, placeholder, value):
                pattern = re.compile(re.escape(placeholder), re.IGNORECASE)
                return pattern.sub(value, text)

            message = template
            message = replace_case_insensitive(message, "[Client Name]", first_name)
            message = replace_case_insensitive(message, "[Your Name]", user or "our clinic")
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

        st.session_state["user_name"] = st.text_input(
            "Your name / clinic (appears in WhatsApp messages):",
            value=st.session_state.get("user_name", ""),
            key=f"user_name_input_{key_prefix}",
            placeholder="e.g. Best Health Vet Clinic or Patrik from Best Health Vet Clinic"
        )

        if msg_key not in st.session_state:
            st.session_state[msg_key] = ""

        st.text_area("Message:", key=msg_key, height=200)
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
    st.info("1. **Update** the WhatsApp template here... 2. Click **Update Template** or **Reset Template**.")
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
    key = (st.session_state.get("data_version", 0), _rules_fp(rules))
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
    st.info("💡 Pick a Start Date to see reminders for the next 7-day window. Click WA to prepare a message.")

    prepared = get_prepared_df(df, st.session_state["rules"])
    latest_date = prepared["ChargeDate"].max()
    default_start = (latest_date + timedelta(days=1)).date() if pd.notna(latest_date) else date.today()
    start_date = st.date_input("Start Date (7-day window)", value=default_start)
    end_date = start_date + timedelta(days=6)

    due2 = prepared[
        (pd.to_datetime(prepared["NextDueDate"]) >= pd.to_datetime(start_date)) &
        (pd.to_datetime(prepared["NextDueDate"]) <= pd.to_datetime(end_date))
    ].copy()

    if not due2.empty:
        g = due2.groupby(["DueDateFmt", "Client Name"], dropna=False)
        grouped = (
            pd.DataFrame({
                "Charge Date": g["ChargeDateFmt"].max(),
                "Animal Name": g["Animal Name"].apply(lambda s: format_items(sorted(set(s.dropna())))),
                "Plan Item": g["MatchedItems"].apply(
                    lambda lists: simplify_vaccine_text(
                        format_items(sorted(set(
                            i.strip()
                            for sublist in lists
                            for i in (sublist if isinstance(sublist, list) else [sublist])
                            if str(i).strip()
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

        # --- Filter out deleted reminders before rendering ---
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

        grouped["Qty"] = pd.to_numeric(grouped["Qty"], errors="coerce").fillna(0).astype(int)
        render_table(grouped, f"{start_date} to {end_date}", "weekly", "weekly_message", st.session_state["rules"])

    else:
        st.info("No reminders in the selected week.")

    # --------------------------------
    # Search
    # --------------------------------
    st.markdown("---")
    st.markdown("<div id='search' class='anchor-offset'></div>", unsafe_allow_html=True)
    st.markdown("#### 🔍 Search")
    st.info("💡 Search by client, animal, or item to find upcoming reminders.")
    search_term = st.text_input("Enter text to search (client, animal, or item)")

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
        "1. See all current Search Terms, set their recurrence interval, and delete if necessary.\n"
        "2. Decide if the Quantity column should be considered (e.g. 1× Bravecto = 90 days, 2× Bravecto = 180 days).\n"
        "3. View and edit the Visible Text which will appear in the WhatsApp template message."
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
                    key=f"days_{safe_rule}_{ver}", label_visibility="collapsed"
                )
            with cols[2]:
                st.checkbox(
                    "Use Qty", value=settings["use_qty"],
                    key=f"useqty_{safe_rule}_{ver}",
                    on_change=toggle_use_qty,
                    args=(rule, f"useqty_{safe_rule}_{ver}",)
                )
            with cols[3]:
                new_values[rule]["visible_text"] = st.text_input(
                    "Visible Text", value=settings.get("visible_text",""),
                    key=f"vis_{safe_rule}_{ver}", label_visibility="collapsed"
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
        if st.button("Update"):
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
        if st.button("Reset defaults"):
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
        new_rule_name = st.text_input("Rule name", key=f"new_rule_name_{row_id}")
    with c2:
        new_rule_days = st.text_input("Days", key=f"new_rule_days_{row_id}")
    with c3:
        new_rule_use_qty = st.checkbox("Use Qty", key=f"new_rule_useqty_{row_id}")
    with c4:
        new_rule_visible = st.text_input("Visible Text (optional)", key=f"new_rule_vis_{row_id}")
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
        new_excl = st.text_input("Add New Exclusion Term", key=f"new_excl_{row_id}")
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

@st.cache_resource(show_spinner=False)
def get_sheet():
    # Do not connect unless Feedback needs it
    try:
        creds_dict = st.secrets["gcp_service_account"]
    except Exception:
        try:
            with open("google-credentials.json", "r") as f:
                creds_dict = json.load(f)
        except FileNotFoundError:
            return None
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPE)
        client = gspread.authorize(creds)
        return client.open_by_key(SHEET_ID).sheet1
    except Exception:
        return None

def _next_id_from_column(sheet):
    try:
        col_ids = sheet.col_values(1)[1:]  # skip header
        nums = [int(x) for x in col_ids if x.strip().isdigit()]
        return (max(nums) if nums else 0) + 1
    except Exception:
        rows = sheet.get_all_values()
        return len(rows)

def insert_feedback(name, email, message):
    sheet = get_sheet()
    if sheet is None:
        st.error("Google credentials not found or Sheet unavailable.")
        return
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    next_id = _next_id_from_column(sheet)
    sheet.append_row([next_id, now, name or "", email or "", message],
                     value_input_option="USER_ENTERED")

@st.cache_data(ttl=600, show_spinner=False)
def fetch_feedback(limit=500):
    sheet = get_sheet()
    if sheet is None:
        return []
    rows = sheet.get_all_values()
    data = rows[1:] if rows else []
    return data[-limit:] if data else []

# --------------------------------
# 📊 Factoids Section (Password Protected)
# --------------------------------
st.markdown("<div id='factoids' class='anchor-offset'></div>", unsafe_allow_html=True)
st.markdown("## 📊 Factoids")

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
            def _norm(s: pd.Series) -> pd.Series:
                return (
                    s.astype(str)
                     .str.normalize("NFKC").str.lower()
                     .str.replace(r"[\u00A0\u200B]", "", regex=True)
                     .str.strip().str.replace(r"\s+", " ", regex=True)
                )
            if "ClientKey" not in df.columns:
                df["ClientKey"] = _norm(df.get("Client Name", pd.Series(index=df.index)))
            if "AnimalKey" not in df.columns:
                df["AnimalKey"] = _norm(df.get("Animal Name", pd.Series(index=df.index)))
        
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
                return (
                    s.astype(str)
                     .str.normalize("NFKC").str.lower()
                     .str.replace(r"[\u00A0\u200B]", "", regex=True)
                     .str.strip().str.replace(r"\s+", " ", regex=True)
                )
        
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
    
# --------------------------------
# 💬 Feedback (Lazy Sheets; isolated from reruns)
# --------------------------------
st.markdown("<div id='feedback-section' class='anchor-offset'></div>", unsafe_allow_html=True)
st.markdown("## 💬 Feedback")
st.markdown("### Found a problem? Let me (Patrik) know here:")

@st.cache_resource(show_spinner=False)
def get_sheet():
    """Lazy Google Sheets connector (single source of truth)."""
    SHEET_ID = "1LUK2lAmGww40aZzFpx1TSKPLvXsqmm_R5WkqXQVkf98"
    SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    # Credentials: try st.secrets, then local fallback
    try:
        creds_dict = st.secrets["gcp_service_account"]
    except Exception:
        try:
            with open("google-credentials.json", "r") as f:
                creds_dict = json.load(f)
        except FileNotFoundError:
            return None
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPE)
        client = gspread.authorize(creds)
        return client.open_by_key(SHEET_ID).sheet1
    except Exception:
        return None

def insert_feedback(name, email, message):
    sheet = get_sheet()
    if sheet is None:
        st.error("⚠ Could not connect to Google Sheet. Please check credentials or try again later.")
        return
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        col_ids = sheet.col_values(1)[1:]  # skip header
        nums = [int(x) for x in col_ids if x.strip().isdigit()]
        next_id = (max(nums) if nums else 0) + 1
    except Exception:
        rows = sheet.get_all_values() or []
        next_id = max(0, len(rows) - 1) + 1
    sheet.append_row([next_id, now, name or "", email or "", message], value_input_option="USER_ENTERED")

@st.cache_data(ttl=600, show_spinner=False)
def fetch_feedback(limit=500):
    """Optional: fetch last `limit` rows for an admin list (not used in UI yet)."""
    sheet = get_sheet()
    if sheet is None:
        return []
    rows = sheet.get_all_values() or []
    data = rows[1:] if rows else []
    return data[-limit:] if data else []

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
# 🧷 Nova Vet Family Admin Access (Password Protected)
# --------------------------------
st.markdown("---")
st.markdown("## 🧷 Nova Vet Family Admin Access")

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



