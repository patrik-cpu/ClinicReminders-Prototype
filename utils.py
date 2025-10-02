import pandas as pd
import re, unicodedata, os, json
import streamlit as st

# -----------------------
# Default Rules
# -----------------------
DEFAULT_RULES = {
    "rabies": {"days": 365, "use_qty": False, "visible_text": "Rabies Vaccine"},
    "dhppil": {"days": 365, "use_qty": False, "visible_text": "DHPPIL Vaccine"},
    "bravecto": {"days": 90, "use_qty": True, "visible_text": "Bravecto"},
    "dental": {"days": 365, "use_qty": False, "visible_text": "Dental exam"},
}

# -----------------------
# PMS definitions
# -----------------------
PMS_DEFINITIONS = {
    "VETport": {
        "columns": ["Planitem Performed","Client Name","Patient Name","Plan Item Name","Plan Item Quantity"],
        "mappings": {"date":"Planitem Performed","client":"Client Name","animal":"Patient Name","item":"Plan Item Name","qty":"Plan Item Quantity"}
    },
    "Xpress": {
        "columns": ["Date","Client Name","Animal Name","Item Name","Qty"],
        "mappings": {"date":"Date","client":"Client Name","animal":"Animal Name","item":"Item Name","qty":"Qty"}
    },
    "ezyVet": {
        "columns": ["Invoice Date","First Name","Last Name","Patient Name","Product Name","Qty","Total Invoiced (incl)"],
        "mappings": {"date":"Invoice Date","client_first":"First Name","client_last":"Last Name","animal":"Patient Name","item":"Product Name","qty":"Qty"}
    }
}

# -----------------------
# JSON Settings
# -----------------------
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
        rules.update(settings.get("rules", {}))
        st.session_state["rules"] = rules
        st.session_state["exclusions"] = settings.get("exclusions", [])
        st.session_state["user_name"] = settings.get("user_name", "")
    else:
        st.session_state["rules"] = DEFAULT_RULES.copy()
        st.session_state["exclusions"] = []
        st.session_state["user_name"] = ""
        save_settings()

# -----------------------
# Helpers
# -----------------------
def normalize_columns(cols):
    cleaned = []
    for c in cols:
        if not isinstance(c, str): c = str(c)
        c = c.replace("\u00a0", " ").replace("\ufeff", "")
        c = re.sub(r"\s+", " ", c).strip().lower()
        cleaned.append(c)
    return cleaned

def detect_pms(df: pd.DataFrame) -> str:
    df_cols = set(normalize_columns(df.columns))
    for pms_name, definition in PMS_DEFINITIONS.items():
        required = set(normalize_columns(definition["columns"]))
        if required.issubset(df_cols):
            return pms_name
    return None

def parse_dates(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce", dayfirst=True)

def simplify_vaccine_text(text: str) -> str:
    return text.strip() if isinstance(text, str) else text

def get_visible_plan_item(item_name: str, rules: dict) -> str:
    if not isinstance(item_name, str): return item_name
    n = item_name.lower()
    for rule_text, settings in rules.items():
        if rule_text in n:
            return settings.get("visible_text") or item_name
    return item_name

def format_items(item_list):
    items = [str(x).strip() for x in item_list if str(x).strip()]
    if not items: return ""
    if len(items) == 1: return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]

def format_due_date(date_str: str) -> str:
    try:
        dt = pd.to_datetime(date_str, errors="coerce")
        return dt.strftime("%d %b %Y") if pd.notna(dt) else date_str
    except Exception:
        return date_str

def normalize_display_case(text: str) -> str:
    if not isinstance(text, str): return text
    words = text.split()
    fixed = [w.capitalize() if w.isupper() and len(w) > 1 else w for w in words]
    return " ".join(fixed)

def map_intervals(df, rules):
    df = df.copy()
    df["MatchedItems"] = [[] for _ in range(len(df))]
    df["IntervalDays"] = pd.NA
    for idx, row in df.iterrows():
        normalized = str(row.get("Plan Item Name","")).lower()
        matches, interval_values = [], []
        for rule, settings in rules.items():
            if rule in normalized:
                matches.append(settings.get("visible_text", rule))
                days = settings["days"]
                if settings.get("use_qty"):
                    qty = pd.to_numeric(row.get("Quantity", 1), errors="coerce")
                    qty = int(qty) if pd.notna(qty) else 1
                    days *= max(qty,1)
                interval_values.append(days)
        if matches:
            df.at[idx,"MatchedItems"] = matches
            df.at[idx,"IntervalDays"] = min(interval_values)
    return df

def ensure_reminder_columns(df: pd.DataFrame, rules: dict) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=[
            "DueDateFmt","Client Name","ChargeDateFmt","Patient Name",
            "MatchedItems","Quantity","IntervalDays","NextDueDate","Planitem Performed"
        ])
    df = map_intervals(df, rules)
    days = pd.to_numeric(df["IntervalDays"], errors="coerce")
    df["NextDueDate"] = df["Planitem Performed"] + pd.to_timedelta(days, unit="D")
    df["ChargeDateFmt"] = pd.to_datetime(df["Planitem Performed"]).dt.strftime("%d %b %Y")
    df["DueDateFmt"] = pd.to_datetime(df["NextDueDate"]).dt.strftime("%d %b %Y")
    return df

def process_file(file, rules):
    if file.name.endswith(".csv"):
        df = pd.read_csv(file)
    else:
        df = pd.read_excel(file)
    df.columns = [c.strip() for c in df.columns]
    pms_name = detect_pms(df)
    if not pms_name:
        return None, None
    mappings = PMS_DEFINITIONS[pms_name]["mappings"]
    if pms_name == "ezyVet":
        df["Client Name"] = (
            df[mappings["client_first"]].fillna("").astype(str).str.strip() + " " +
            df[mappings["client_last"]].fillna("").astype(str).str.strip()
        ).str.strip()
        rename_map = {
            mappings["date"]: "Planitem Performed",
            mappings["animal"]: "Patient Name",
            mappings["item"]: "Plan Item Name",
        }
        df["Amount"] = pd.to_numeric(df["Total Invoiced (incl)"], errors="coerce")
    else:
        rename_map = {
            mappings["date"]: "Planitem Performed",
            mappings["client"]: "Client Name",
            mappings["animal"]: "Patient Name",
            mappings["item"]: "Plan Item Name",
        }
    df.rename(columns=rename_map, inplace=True)
    df["Planitem Performed"] = parse_dates(df["Planitem Performed"])
    df["Quantity"] = pd.to_numeric(df.get(mappings.get("qty","Qty"), 1), errors="coerce").fillna(1)
    return df, pms_name
