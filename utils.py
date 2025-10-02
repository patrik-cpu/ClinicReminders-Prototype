import pandas as pd
import re, unicodedata, os, json
import streamlit as st

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
    "milbem": {"days": 90, "use_qty": False, "visible_text": "Deworming"},
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

# --------------------------------
# Settings persistence
# --------------------------------
SETTINGS_FILE = "clinicreminders_settings.json"

def save_settings():
    settings = {
        "rules": st.session_state.get("rules", DEFAULT_RULES),
        "exclusions": st.session_state.get("exclusions", []),
        "user_name": st.session_state.get("user_name", ""),
    }
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f)

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r") as f:
            settings = json.load(f)
        rules = DEFAULT_RULES.copy()
        saved_rules = settings.get("rules", {})
        for k, v in saved_rules.items():
            if "visible_text" in v and isinstance(v["visible_text"], str) and not v["visible_text"].strip():
                v.pop("visible_text")
        rules.update(saved_rules)
        st.session_state["rules"] = rules
        st.session_state["exclusions"] = settings.get("exclusions", [])
        st.session_state["user_name"] = settings.get("user_name", "")
    else:
        st.session_state["rules"] = DEFAULT_RULES.copy()
        st.session_state["exclusions"] = []
        st.session_state["user_name"] = ""
        save_settings()

# --------------------------------
# PMS definitions
# --------------------------------
PMS_DEFINITIONS = {
    "VETport": {
        "columns": ["Planitem Performed","Client Name","Patient Name","Plan Item Name","Plan Item Quantity"],
        "mappings": {"date":"Planitem Performed","client":"Client Name","animal":"Patient Name","item":"Plan Item Name","qty":"Plan Item Quantity"}
    },
    "Xpress": {
        "columns": ["Date","Client Name","Animal Name","Item Name","Qty","Amount"],
        "mappings": {"date":"Date","client":"Client Name","animal":"Animal Name","item":"Item Name","qty":"Qty","amount":"Amount"}
    },
    "ezyVet": {
        "columns": ["Invoice Date","First Name","Last Name","Patient Name","Product Name","Qty","Total Invoiced (incl)"],
        "mappings": {"date":"Invoice Date","client_first":"First Name","client_last":"Last Name","animal":"Patient Name","item":"Product Name","qty":"Qty","amount":"Total Invoiced (incl)"}
    }
}

def normalize_columns(cols):
    return [str(c).strip().lower() for c in cols]

def detect_pms(df: pd.DataFrame) -> str:
    df_cols = set(normalize_columns(df.columns))
    for pms_name, definition in PMS_DEFINITIONS.items():
        required = set(normalize_columns(definition["columns"]))
        if required.issubset(df_cols):
            return pms_name
    return None

def parse_dates(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce", dayfirst=True)

def ensure_reminder_columns(df: pd.DataFrame, rules: dict) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=[
            "DueDateFmt","Client Name","ChargeDateFmt","Patient Name",
            "MatchedItems","Quantity","IntervalDays","NextDueDate","Planitem Performed"
        ])
    df = df.copy()
    if "Quantity" not in df.columns:
        df["Quantity"] = 1
    if "Planitem Performed" in df.columns and not pd.api.types.is_datetime64_any_dtype(df["Planitem Performed"]):
        df["Planitem Performed"] = parse_dates(df["Planitem Performed"])
    return df

@st.cache_data
def process_file(file, rules):
    if file.name.endswith(".csv"):
        df = pd.read_csv(file)
    else:
        df = pd.read_excel(file)
    df.columns = [c.strip() for c in df.columns]
    pms_name = detect_pms(df)
    if not pms_name:
        return df, None
    mappings = PMS_DEFINITIONS[pms_name]["mappings"]
    if pms_name == "ezyVet":
        df["Client Name"] = (
            df[mappings["client_first"]].fillna("").astype(str).str.strip() + " " +
            df[mappings["client_last"]].fillna("").astype(str).str.strip()
        ).str.strip()
        df["Amount"] = pd.to_numeric(df[mappings["amount"]], errors="coerce")
        rename_map = {
            mappings["date"]: "Planitem Performed",
            mappings["animal"]: "Patient Name",
            mappings["item"]: "Plan Item Name",
        }
    else:
        rename_map = {
            mappings["date"]: "Planitem Performed",
            mappings["client"]: "Client Name",
            mappings["animal"]: "Patient Name",
            mappings["item"]: "Plan Item Name",
        }
        if "amount" in mappings:
            df["Amount"] = pd.to_numeric(df[mappings["amount"]], errors="coerce")
        else:
            df["Amount"] = 0
    df.rename(columns=rename_map, inplace=True)
    df["Planitem Performed"] = parse_dates(df["Planitem Performed"])
    qty_col = mappings.get("qty")
    df["Quantity"] = pd.to_numeric(df.get(qty_col, 1), errors="coerce").fillna(1)
    return df, pms_name

# --------------------------------
# Preventive Care Keyword Lists
# --------------------------------
FLEA_WORM_KEYWORDS = [
    "bravecto", "revolution", "deworm", "frontline"
]

FOOD_KEYWORDS = [
    "hill's", "hills", "royal canin", "purina", "proplan",
    "pouch", "tuna", "chicken", "beef", "salmon",
    "kitten", "puppy", "adult", "diet", "food"
]
