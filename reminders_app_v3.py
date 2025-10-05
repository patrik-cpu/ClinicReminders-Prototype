# === ClinicReminders Prototype v4.1 — Optimized Replacement ===
# Drop-in replacement file (preserves UI & outputs, improves performance)

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

# ------------------------------------------------------------
# Small wrapper to keep compatibility with earlier code that
# referenced fetch_feedback_cached near the top of the file.
# The real implementation of fetch_feedback is defined later.
# ------------------------------------------------------------
@st.cache_data(ttl=30)
def fetch_feedback_cached(limit=500):
    return fetch_feedback(limit)

_SPACE_RX = re.compile(r"\s+")
_CURRENCY_RX = re.compile(r"[^\d.\-]")

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
          <li><a href="#factoids-charts" style="text-decoration:none;">🔹 Charts</a></li>
          <li><a href="#factoids-ataglance" style="text-decoration:none;">🔹 At a Glance</a></li>
          <li><a href="#factoids-tables" style="text-decoration:none;">🔹 Tables</a></li>
        </ul>
      <li><a href="#feedback" style="text-decoration:none;">💬 Feedback</a></li>
    </ul>
    """,
    unsafe_allow_html=True,
)

# --------------------------------
# Title
# --------------------------------
title_col, tut_col = st.columns([4,1])
with title_col:
    st.title("ClinicReminders Prototype v4.1 (with Factoids!)")
st.markdown("---")

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

# --------------------------------
# Settings persistence (local JSON) — ephemeral on Streamlit Cloud
# --------------------------------
SETTINGS_FILE = "clinicreminders_settings.json"
_last_settings = None  # global cache

def save_settings():
    global _last_settings
    settings = {
        "rules": st.session_state["rules"],
        "exclusions": st.session_state["exclusions"],
        "user_name": st.session_state["user_name"],
    }
    if settings != _last_settings:  # only write if changed
        with open(SETTINGS_FILE, "w") as f:
            json.dump(settings, f)
        _last_settings = settings

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r") as f:
            settings = json.load(f)
        rules = DEFAULT_RULES.copy()
        saved_rules = settings.get("rules", {})
        for k, v in saved_rules.items():
            if "visible_text" in v and not v["visible_text"].strip():
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
        if pd.isna(dt): return f"on {date_str}"
        day = dt.day
        suffix = "th" if 10 <= day % 100 <= 20 else {1:"st",2:"nd",3:"rd"}.get(day%10,"th")
        return f"on the {day}{suffix} of {dt.strftime('%B')}, {dt.year}"
    except Exception:
        return f"on {date_str}"

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

def drop_early_duplicates_fast(df):
    if df.empty:
        return df
    df = df.copy()
    df["MatchedItems_str"] = df["MatchedItems"].apply(
        lambda x: ", ".join(sorted(x)) if isinstance(x, list) else str(x)
    )
    df.sort_values(["Client Name", "Animal Name", "MatchedItems_str", "ChargeDate"],
                   inplace=True, ignore_index=True)
    g = df.groupby(["Client Name","Animal Name","MatchedItems_str"], dropna=False)
    next_charge = g["ChargeDate"].shift(-1)
    keep = next_charge.isna() | (next_charge > df["NextDueDate"])
    out = df.loc[keep].drop(columns=["MatchedItems_str"]).reset_index(drop=True)
    return out

# --------------------------------
# File processing (decoupled from rules)
# --------------------------------
@st.cache_data(show_spinner=False)
def process_file(file_bytes, filename):
    from io import BytesIO
    file = BytesIO(file_bytes)
    lowerfn = filename.lower()
    if lowerfn.endswith(".csv"):
        df = pd.read_csv(file)
    elif lowerfn.endswith((".xls", ".xlsx")):
        df = pd.read_excel(file)
    else:
        raise ValueError("Unsupported file type")
    def _normalize(c): return str(c).replace("\u00a0", " ").replace("\ufeff", "").strip()
    df.columns = [_normalize(c) for c in df.columns]

    pms_name = detect_pms(df)
    if not pms_name:
        return df, None, None

    mappings = PMS_DEFINITIONS[pms_name]["mappings"]
    amount_col = mappings.get("amount")
    if amount_col and amount_col in df.columns:
        df["Amount"] = clean_revenue_column(df[amount_col])
    else:
        df["Amount"] = 0

    if pms_name == "ezyVet":
        cf = mappings.get("client_first"); cl = mappings.get("client_last")
        if cf in df.columns and cl in df.columns:
            df["Client Name"] = (
                df[cf].fillna("").astype(str).str.strip()
                + " "
                + df[cl].fillna("").astype(str).str.strip()
            ).str.strip()
        else:
            df["Client Name"] = (
                df.get(cf, "").astype(str).fillna("")
                + " "
                + df.get(cl, "").astype(str).fillna("")
            ).str.strip()

    rename_map = {}
    if "date" in mappings and mappings["date"] in df.columns:
        rename_map[mappings["date"]] = "ChargeDate"
    if "client" in mappings and mappings["client"] in df.columns:
        rename_map[mappings["client"]] = "Client Name"
    if "animal" in mappings and mappings["animal"] in df.columns:
        rename_map[mappings["animal"]] = "Animal Name"
    if "item" in mappings and mappings["item"] in df.columns:
        rename_map[mappings["item"]] = "Item Name"
    df = df.rename(columns=rename_map)

    for col, default in [
        ("ChargeDate", pd.NaT),
        ("Client Name", ""),
        ("Animal Name", ""),
        ("Item Name", ""),
    ]:
        if col not in df.columns:
            df[col] = default

    qty_col = mappings.get("qty")
    if qty_col and qty_col in df.columns:
        df["Qty"] = pd.to_numeric(df[qty_col], errors="coerce").fillna(1).astype(int)
    else:
        fallback_qty_cols = ["Qty", "Quantity", "Plan Item Quantity"]
        found = False
        for c in fallback_qty_cols:
            if c in df.columns:
                df["Qty"] = pd.to_numeric(df[c], errors="coerce").fillna(1).astype(int)
                found = True; break
        if not found:
            df["Qty"] = 1

    df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce").fillna(0)

    if not pd.api.types.is_datetime64_any_dtype(df["ChargeDate"]):
        if "ChargeDate" in df.columns:
            df["ChargeDate"] = parse_dates(df["ChargeDate"]).dt.normalize()

    df["_client_lower"] = df["Client Name"].astype(str).str.lower()
    df["_animal_lower"] = df["Animal Name"].astype(str).str.lower()
    df["_item_lower"] = df["Item Name"].astype(str).str.lower()
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

# --------------------------------
# Tutorial section
# --------------------------------
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

files = st.file_uploader(
    "Upload Sales Plan file(s)",
    type=["csv", "xls", "xlsx"],
    accept_multiple_files=True
)

datasets = []
summary_rows = []
working_df = None

# Auto clear/rekey when file list changes
if "last_uploaded_files" not in st.session_state:
    st.session_state["last_uploaded_files"] = []
current_files = [f.name for f in files] if files else []
if current_files != st.session_state["last_uploaded_files"]:
    if current_files != st.session_state.get("last_uploaded_files", []):
        st.session_state["last_uploaded_files"] = current_files
        st.session_state["data_version"] = st.session_state.get("data_version", 0) + 1
    st.session_state["last_uploaded_files"] = current_files
    if "working_df" in st.session_state:
        del st.session_state["working_df"]
    if "prepared_df" in st.session_state:
        del st.session_state["prepared_df"]
        st.session_state.pop("prepared_key", None)

if files:
    file_blobs = tuple(_to_blob(f) for f in files)
    datasets, summary_rows = summarize_uploads(file_blobs)
    st.dataframe(pd.DataFrame(summary_rows), use_container_width=True)

    all_pms = {p for p, _ in datasets}
    if len(all_pms) == 1 and "Undetected" not in all_pms:
        working_df = pd.concat([df for _, df in datasets], ignore_index=True)
        st.session_state["working_df"] = working_df
        st.success(f"All files detected as {list(all_pms)[0]} — merging datasets.")
    else:
        try:
            cand = pd.concat([df for _, df in datasets], ignore_index=True, sort=False)
            required_cols = ["ChargeDate","Client Name","Animal Name","Item Name","Qty","Amount"]
            if all(c in cand.columns for c in required_cols):
                working_df = cand
                st.session_state["working_df"] = working_df
                st.success("Files merged into canonical schema.")
            else:
                st.warning("PMS mismatch or some files missing expected canonical columns. Reminders cannot be generated reliably.")
        except Exception:
            st.warning("PMS mismatch or undetected files. Reminders cannot be generated.")

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
        df = df[~df["Plan Item"].str.lower().str.contains(excl_pattern)]
    if df.empty:
        st.info("All rows excluded by exclusion list.")
        return
    render_table_with_buttons(df, key_prefix, msg_key)

def render_table_with_buttons(df, key_prefix, msg_key):
    col_widths = [2, 2, 5, 3, 4, 1, 1, 2]
    headers = ["Due Date", "Charge Date", "Client Name", "Animal Name", "Plan Item", "Qty", "Days", "WA"]
    cols = st.columns(col_widths)
    for c, head in zip(cols, headers):
        c.markdown(f"**{head}**")
    for idx, row in df.iterrows():
        vals = {h: str(row.get(h, "")) for h in headers[:-1]}
        cols = st.columns(col_widths, gap="small")
        for j, h in enumerate(headers[:-1]):
            val = vals[h]
            if h in ["Client Name", "Animal Name", "Plan Item"]:
                val = normalize_display_case(val)
            cols[j].markdown(val)
        if cols[7].button("WA", key=f"{key_prefix}_wa_{idx}"):
            first_name  = vals['Client Name'].split()[0].strip() if vals['Client Name'] else "there"
            animal_name = vals['Animal Name'].strip() if vals['Animal Name'] else "your pet"
            plan_for_msg = vals["Plan Item"].strip()
            user = st.session_state.get("user_name", "").strip()
            due_date_fmt = format_due_date(vals['Due Date'])
            closing = " Get in touch with us any time, and we look forward to hearing from you soon!"
            verb = "are" if (" and " in animal_name or "," in animal_name) else "is"
            if user:
                st.session_state[msg_key] = (
                    f"Hi {first_name}, this is {user} reminding you that "
                    f"{animal_name} {verb} due for their {plan_for_msg} {due_date_fmt}.{closing}"
                )
            else:
                st.session_state[msg_key] = (
                    f"Hi {first_name}, this is a reminder letting you know that "
                    f"{animal_name} {verb} due for their {plan_for_msg} {due_date_fmt}.{closing}"
                )
            st.success(f"WhatsApp message prepared for {animal_name}. Scroll to the Composer below to send.")
            st.markdown(f"**Preview:** {st.session_state[msg_key]}")
    comp_main, comp_tip = st.columns([4,1])
    with comp_main:
        st.write("### WhatsApp Composer")
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
                    try {{
                      await navigator.clipboard.writeText(text);
                    }} catch (err) {{
                      const ta = document.createElement('textarea');
                      ta.value = text;
                      document.body.appendChild(ta);
                      ta.select();
                      try {{ document.execCommand('copy'); }} finally {{
                        document.body.removeChild(ta);
                      }}
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
    with comp_tip:
        st.markdown("### 💡 Tip")
        st.info("If you leave the phone blank, the message is auto-copied. WhatsApp opens in forward/search mode — just paste into the chat.")

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

    # Your name / clinic
    st.markdown("---")
    name_col, tut_col = st.columns([4,1])
    with name_col:
        st.markdown("### Your name / clinic")
        st.session_state["user_name"] = st.text_input(
            "",
            value=st.session_state["user_name"],
            key="user_name_input",
            label_visibility="collapsed"
        )
    with tut_col:
        st.markdown("### 💡 Tip")
        st.info("This name will appear in your WhatsApp reminders")

    # Weekly Reminders
    st.markdown("---")
    st.markdown("<h2 id='reminders'>📅 Reminders</h2>", unsafe_allow_html=True)
    st.markdown("<div id='weekly-reminders' class='anchor-offset'></div>", unsafe_allow_html=True)
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
        # Filter the already-prepared DF — no heavy recompute
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

# --- Google Sheets Setup (LAZY & PERSISTENT) ---
SHEET_ID = "1LUK2lAmGww40aZzFpx1TSKPLvXsqmm_R5WkqXQVkf98"
SCOPE = ["https://spreadsheets.google.com/feeds",
         "https://www.googleapis.com/auth/drive"]

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
# 📊 Factoids Section (Optimized with Ghost Bars + Full Metrics)
# --------------------------------

st.markdown("<div id='factoids' class='anchor-offset'></div>", unsafe_allow_html=True)
st.markdown("## 📊 Factoids")

# -----------------------
# Keyword Definitions
# -----------------------
FLEA_WORM_KEYWORDS = [
    "bravecto","revolution","deworm","frontline","milbe","milpro",
    "nexgard","simparica","advocate","worm","praz","fenbend"
]
FOOD_KEYWORDS = [
    "hill's","hills","royal canin","purina","proplan","iams","eukanuba",
    "orijen","acana","farmina","vetlife","wellness","taste of the wild",
    "nutro","pouch","tin","can","canned","wet","dry","kibble",
    "tuna","chicken","beef","salmon","lamb","duck","senior","diet","food","grain","rc"
]
XRAY_KEYWORDS = ["xray","x-ray","radiograph","radiology"]
ULTRASOUND_KEYWORDS = ["ultrasound","echo","afast","tfast","a-fast","t-fast"]
LABWORK_KEYWORDS = [
    "cbc","blood test","lab","biochemistry","haematology","urinalysis","labwork","idexx","ghp",
    "chem","felv","fiv","urine","cytology","smear","faecal","fecal","microscopic","slide","bun",
    "crea","phos","cpl","cpli","lipase","amylase","pancreatic","cortisol"
]
ANAESTHETIC_KEYWORDS = [
    "anaesthesia","anesthesia","spay","neuter","castrate","surgery",
    "isoflurane","propofol","alfaxan","alfaxalone"
]
HOSPITALISATION_KEYWORDS = ["hospitalisation","hospitalization"]
VACCINE_KEYWORDS = ["vaccine","vaccination","booster","rabies","dhpp","dhppil","tricat","pch","pcl","leukemia","kennel cough"]

def _rx(words):
    return re.compile("|".join(map(re.escape, words)), flags=re.IGNORECASE)

# -----------------------
# Cached base computation
# -----------------------
@st.cache_data(show_spinner=False)
def prepare_factoids_data(df: pd.DataFrame):
    df = df.copy()
    df["ChargeDate"] = pd.to_datetime(df["ChargeDate"], errors="coerce")
    df_sorted = df.sort_values(["Client Name", "ChargeDate"]).copy()
    df_sorted["DateOnly"] = pd.to_datetime(df_sorted["ChargeDate"]).dt.normalize()
    df_sorted["DayDiff"] = df_sorted.groupby("Client Name")["DateOnly"].diff().dt.days.fillna(1)
    df_sorted["Block"] = df_sorted.groupby("Client Name")["DayDiff"].transform(lambda x: (x > 1).cumsum())
    df_sorted["Month"] = df_sorted["ChargeDate"].dt.to_period("M")
    tx = (
        df_sorted.groupby(["Client Name","Block"])
        .agg(StartDate=("DateOnly","min"),
             EndDate=("DateOnly","max"),
             Patients=("Animal Name", lambda x: set(x.astype(str))),
             Amount=("Amount","sum"))
        .reset_index()
    )
    patients_per_month = df_sorted.groupby("Month")["Animal Name"].nunique()
    return df_sorted, tx, patients_per_month

@st.cache_data(show_spinner=False)
def compute_monthly_data(df_blocked: pd.DataFrame,
                         tx: pd.DataFrame,
                         patients_per_month: pd.Series,
                         rx_pattern: re.Pattern,
                         apply_amount_filter: bool = False) -> pd.DataFrame:
    """Return last-12-month rows with columns: Month (Period[M]), MonthLabel, UniquePatients, TotalPatientsMonth, Percent."""
    if df_blocked.empty:
        return pd.DataFrame()

    mask = df_blocked["Item Name"].astype(str).apply(lambda s: bool(rx_pattern.search(s)))
    service_rows = df_blocked.loc[mask, ["Client Name","Block","ChargeDate"]].drop_duplicates()
    if service_rows.empty:
        return pd.DataFrame()

    qualifying = pd.merge(service_rows, tx, on=["Client Name","Block"], how="left")
    if apply_amount_filter:
        qualifying = qualifying[qualifying["Amount"] > 700]
    if qualifying.empty:
        return pd.DataFrame()

    qualifying["Month"] = qualifying["ChargeDate"].dt.to_period("M")
    last_month = qualifying["Month"].max()
    month_range = pd.period_range(last_month - 11, last_month, freq="M")

    monthly = (
        qualifying.groupby("Month")["Patients"]
        .apply(lambda p: len(set().union(*p)))
        .reindex(month_range, fill_value=0)
        .reset_index()
        .rename(columns={"index":"Month","Patients":"UniquePatients"})
    )

    monthly["TotalPatientsMonth"] = monthly["Month"].map(patients_per_month).fillna(0).astype(int)
    monthly["Percent"] = monthly.apply(
        lambda r: (r["UniquePatients"]/r["TotalPatientsMonth"]) if r["TotalPatientsMonth"] > 0 else 0,
        axis=1
    )
    monthly["MonthLabel"] = monthly["Month"].dt.strftime("%b %Y")
    return monthly.sort_values("Month")

def run_factoids():
    df = st.session_state.get("working_df")
    if df is None or df.empty:
        st.warning("Upload data first.")
        return

    # Precompute blocked DF and monthly denominators once
    df_blocked, tx, patients_per_month = prepare_factoids_data(df)

    # ============================
    # 📈 Charts (with Previous-Year Ghost Bars)
    # ============================
    st.markdown("<div id='factoids-charts' class='anchor-offset'></div>", unsafe_allow_html=True)
    st.markdown("### 📈 Charts (with Previous-Year Ghost Bars)")

    metric_configs = {
        "Anaesthetics": {"rx": _rx(ANAESTHETIC_KEYWORDS), "color": "#fb7185"},
        "Dentals": {"rx": re.compile("dental", re.I), "color": "#60a5fa", "filter": True},
        "Flea/Worm Treatments": {"rx": _rx(FLEA_WORM_KEYWORDS), "color": "#4ade80"},
        "Food Purchases": {"rx": _rx(FOOD_KEYWORDS), "color": "#facc15"},
        "Hospitalisations": {"rx": _rx(HOSPITALISATION_KEYWORDS), "color": "#f97316"},
        "Lab Work": {"rx": _rx(LABWORK_KEYWORDS), "color": "#fbbf24"},
        "Ultrasounds": {"rx": _rx(ULTRASOUND_KEYWORDS), "color": "#a5b4fc"},
        "Vaccinations": {"rx": _rx(VACCINE_KEYWORDS), "color": "#22d3ee"},
        "X-rays": {"rx": _rx(XRAY_KEYWORDS), "color": "#93c5fd"},
    }

    sorted_metrics = sorted(metric_configs.keys())
    choice = st.selectbox("Select a metric:", sorted_metrics, index=0, key="factoid_metric")
    conf = metric_configs[choice]

    # --- compute current 12-month data
    monthly = compute_monthly_data(df_blocked, tx, patients_per_month, conf["rx"], conf.get("filter", False))
    if monthly.empty:
        st.info(f"No qualifying {choice.lower()} data found.")
    else:
        monthly["Year"] = monthly["Month"].dt.year
        monthly["MonthNum"] = monthly["Month"].dt.month
        df_blocked["Year"] = df_blocked["ChargeDate"].dt.year
        df_blocked["MonthNum"] = df_blocked["ChargeDate"].dt.month

        # --- find ghost values (same month previous year)
        ghost_data = []
        for _, row in monthly.iterrows():
            year_prev = row["Year"] - 1
            month_num = row["MonthNum"]
            subset_prev = df_blocked[
                (df_blocked["Year"] == year_prev) &
                (df_blocked["MonthNum"] == month_num)
            ]
            if not subset_prev.empty:
                prev_monthly = compute_monthly_data(
                    subset_prev, tx, patients_per_month,
                    conf["rx"], conf.get("filter", False)
                )
                if not prev_monthly.empty:
                    ghost_val = prev_monthly["Percent"].iloc[-1]
                    ghost_patients = prev_monthly["UniquePatients"].iloc[-1]
                    ghost_total = prev_monthly["TotalPatientsMonth"].iloc[-1]
                    ghost_data.append((row["MonthLabel"], year_prev, ghost_val, ghost_patients, ghost_total))

        # --- merge ghost results into monthly dataset
        merged = monthly.copy()
        merged["PrevPercent"] = pd.NA
        merged["PrevUniquePatients"] = pd.NA
        merged["PrevYear"] = pd.NA
        merged["PrevTotalPatients"] = pd.NA

        for label, yprev, val, pats, tot in ghost_data:
            merged.loc[merged["MonthLabel"] == label, "PrevPercent"] = val
            merged.loc[merged["MonthLabel"] == label, "PrevUniquePatients"] = pats
            merged.loc[merged["MonthLabel"] == label, "PrevYear"] = yprev
            merged.loc[merged["MonthLabel"] == label, "PrevTotalPatients"] = tot

        merged["has_ghost"] = merged["PrevPercent"].notna()

        # ✅ Month-only string for tooltips (no year)
        merged["MonthOnly"] = merged["MonthLabel"].str.split().str[0]

        color = conf["color"]

        # --- ghost bars (30% opacity, offset left)
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
                    alt.Tooltip("PrevYear:O", title="Year"),
                    alt.Tooltip("MonthOnly:N", title="Month"),  # ← month name only
                    alt.Tooltip("PrevTotalPatients:Q", title="Monthly Patients", format=",.0f"),
                    alt.Tooltip("PrevUniquePatients:Q", title=f"{choice} Patients", format=",.0f"),
                    alt.Tooltip("PrevPercent:Q", title="%", format=".1%"),
                ],
            )
        )

        # --- current bars (centered unless ghost exists)
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
                    alt.Tooltip("Year:O", title="Year"),
                    alt.Tooltip("MonthOnly:N", title="Month"),  # ← month name only
                    alt.Tooltip("TotalPatientsMonth:Q", title="Monthly Patients", format=",.0f"),
                    alt.Tooltip("UniquePatients:Q", title=f"{choice} Patients", format=",.0f"),
                    alt.Tooltip("Percent:Q", title="%", format=".1%"),
                ],
            )
            .transform_calculate(xOffset="datum.has_ghost ? 25 : 0")
        )

        chart = (
            alt.layer(ghost, current)
            .resolve_scale(y="shared")
            .properties(
                height=400,
                width=700,
                title=f"% of Monthly Patients Having {choice} (with previous-year ghost bars)"
            )
        )
        
        st.altair_chart(chart, use_container_width=True)

    # ============================
    # 📊 Revenue Concentration Curve
    # ============================
    st.markdown("---")
    st.subheader("📊 Revenue Concentration Curve")

    rev = df.groupby("Client Name", dropna=False)["Amount"].sum().sort_values(ascending=False).reset_index()
    if not rev.empty and rev["Amount"].sum() > 0:
        tot = float(rev["Amount"].sum())
        n = len(rev)
        rev["Rank"] = rev.index + 1
        rev["TopPct"] = rev["Rank"] / n * 100
        rev["CumPct"] = rev["Amount"].cumsum() / tot * 100
        st.altair_chart(
            alt.Chart(rev)
            .mark_line(point=True)
            .encode(
                x=alt.X("TopPct:Q", title="Top X% of Clients"),
                y=alt.Y("CumPct:Q", title="% of Total Revenue"),
                tooltip=[
                    alt.Tooltip("Client Name:N"),
                    alt.Tooltip("Amount:Q", format=",.0f"),
                    alt.Tooltip("TopPct:Q", format=".1f"),
                    alt.Tooltip("CumPct:Q", format=".1f"),
                ]
            )
            .properties(height=400, width=700),
            use_container_width=True
        )
    else:
        st.info("No client revenue data available.")

    # ============================
    # 📌 At a Glance (complete, fixed)
    # ============================
    st.markdown("---")
    st.markdown("<div id='factoids-ataglance' class='anchor-offset'></div>", unsafe_allow_html=True)
    st.markdown("### 📌 At a Glance")

    transactions = tx

    # --- Daily aggregates (per StartDate)
    daily = transactions.groupby("StartDate").agg(
        ClientTx=("Block", "count"),
        Patients=("Patients", lambda p: len(set().union(*p)) if len(p) else 0),
    )

    metrics = {}

    if not daily.empty:
        max_tx_day = daily["ClientTx"].idxmax()
        max_pat_day = daily["Patients"].idxmax()
        metrics["Max Transactions/Day"] = f"{int(daily.loc[max_tx_day, 'ClientTx']):,} ({max_tx_day.strftime('%d %b %Y')})"
        metrics["Avg Transactions/Day"] = f"{int(round(daily['ClientTx'].mean())):,}"
        metrics["Max Patients/Day"] = f"{int(daily.loc[max_pat_day, 'Patients']):,} ({max_pat_day.strftime('%d %b %Y')})"
        metrics["Avg Patients/Day"] = f"{int(round(daily['Patients'].mean())):,}"

    # --- Total Unique Patients (unique client-animal pairs)
    unique_pairs_all = df[["Client Name", "Animal Name"]].dropna().drop_duplicates()
    total_unique_patients = unique_pairs_all.shape[0]
    metrics["Total Unique Patients"] = f"{total_unique_patients:,}"

    # --- Patient Breakdown (unique patients per service)
    masks = {
        "Dentals": re.compile("dental", re.I),
        "X-rays": _rx(XRAY_KEYWORDS),
        "Ultrasounds": _rx(ULTRASOUND_KEYWORDS),
        "Flea/Worm": _rx(FLEA_WORM_KEYWORDS),
        "Food": _rx(FOOD_KEYWORDS),
        "Lab Work": _rx(LABWORK_KEYWORDS),
        "Anaesthetics": _rx(ANAESTHETIC_KEYWORDS),
        "Hospitalisations": _rx(HOSPITALISATION_KEYWORDS),
        "Vaccinations": _rx(VACCINE_KEYWORDS),
    }

    for k, rx in masks.items():
        matched = df[df["Item Name"].astype(str).str.contains(rx, na=False)]
        count = matched[["Client Name", "Animal Name"]].dropna().drop_duplicates().shape[0]
        if total_unique_patients > 0:
            metrics[f"Unique Patients Having {k}"] = f"{count:,} ({count/total_unique_patients:.1%})"

    # --- Client Transaction Histogram
    tx_per_client = df.groupby("Client Name")["ChargeDate"].nunique()
    total_clients = tx_per_client.shape[0]
    if total_clients > 0:
        hist = {
            "Clients with 1 Transaction": (tx_per_client == 1).sum(),
            "Clients with 2 Transactions": (tx_per_client == 2).sum(),
            "Clients with 3–5 Transactions": ((tx_per_client >= 3) & (tx_per_client <= 5)).sum(),
            "Clients with 6+ Transactions": (tx_per_client >= 6).sum(),
        }
        for k, v in hist.items():
            metrics[k] = f"{v:,} ({v/total_clients:.1%})"

    # --- Fun Facts (unique pairs)
    common_pet_counts = unique_pairs_all["Animal Name"].value_counts()
    if not common_pet_counts.empty:
        top_pet_name = common_pet_counts.index[0]
        top_pet_count = int(common_pet_counts.iloc[0])
        metrics["Most Common Pet Name"] = f"{top_pet_name} ({top_pet_count:,})"

    # Patient with most transactions (unique client-animal pair)
    tx_expanded = transactions.explode("Patients").dropna(subset=["Patients"]).copy()
    tx_expanded["Patients"] = tx_expanded["Patients"].astype(str).str.strip()
    tx_expanded = tx_expanded[tx_expanded["Patients"] != ""]
    tx_pair_visits = (
        tx_expanded
        .assign(Client=tx_expanded["Client Name"].astype(str).str.strip())
        .dropna(subset=["Client"])
        .groupby(["Client", "Patients"])["StartDate"]
        .nunique()
        .reset_index(name="VisitCount")
        .sort_values(["VisitCount", "Patients"], ascending=[False, True])
    )
    if not tx_pair_visits.empty:
        top_row = tx_pair_visits.iloc[0]
        metrics["Patient with Most Transactions"] = (
            f"{top_row['Patients']} ({top_row['Client']}) – {int(top_row['VisitCount']):,}"
        )

    # --- Card rendering (unchanged)
    CARD_STYLE = """<div style='background-color:{bg};
       border:1px solid #94a3b8;padding:16px;border-radius:10px;text-align:center;
       margin-bottom:12px;min-height:120px;display:flex;flex-direction:column;justify-content:center;'>
       <div style='font-size:13px;color:#334155;font-weight:600;'>{label}</div>
       <div style='font-size:{fs}px;font-weight:700;color:#0f172a;margin-top:6px;'>{val}</div></div>"""

    def _fs(v): return 16 if len(v) > 25 else (20 if len(v) > 18 else 22)

    def cardgroup(title, keys):
        if not any(k in metrics for k in keys): return
        st.markdown(
            f"<h4 style='font-size:17px;font-weight:700;color:#475569;margin-top:1rem;margin-bottom:0.4rem;'>{title}</h4>",
            unsafe_allow_html=True
        )
        cols = st.columns(5)
        i = 0
        for k in keys:
            if k in metrics:
                v = metrics[k]; fs = _fs(v); bg = "#f1f5f9" if "Total" not in k else "#dbeafe"
                cols[i % 5].markdown(CARD_STYLE.format(bg=bg, label=k, val=v, fs=fs), unsafe_allow_html=True)
                i += 1
                if i % 5 == 0 and i < len(keys): cols = st.columns(5)

    cardgroup("⭐ Core", [
        "Total Unique Patients",
        "Max Patients/Day",
        "Avg Patients/Day",
        "Max Transactions/Day",
        "Avg Transactions/Day",
    ])
    cardgroup("🐾 Patient Breakdown", [f"Unique Patients Having {k}" for k in masks.keys()])
    if total_clients > 0:
        cardgroup("💼 Client Transaction Histogram", list(hist.keys()))
    cardgroup("🎉 Fun Facts", [
        "Most Common Pet Name",
        "Patient with Most Transactions",
    ])



    # ============================
    # 📋 Tables
    # ============================
    st.markdown("---")
    st.markdown("<div id='factoids-tables' class='anchor-offset'></div>", unsafe_allow_html=True)
    st.markdown("### 📋 Tables")

    # Top 20 Items by Revenue
    st.markdown("#### 💰 Top 20 Items by Revenue")
    top = (
        df.groupby("Item Name")
        .agg(TotalRevenue=("Amount","sum"), TotalCount=("Qty","sum"))
        .sort_values("TotalRevenue", ascending=False)
        .head(20)
    )
    if not top.empty:
        total = top["TotalRevenue"].sum()
        top["% of Total Revenue"] = (top["TotalRevenue"]/total*100).round(1)
        top["Revenue"] = top["TotalRevenue"].astype(int).apply(lambda x: f"{x:,}")
        top["How Many"] = top["TotalCount"].astype(int).apply(lambda x: f"{x:,}")
        top["% of Total Revenue"] = top["% of Total Revenue"].astype(str) + "%"
        st.dataframe(top[["Revenue","% of Total Revenue","How Many"]], use_container_width=True)
    else:
        st.info("No items found.")

    # Top 5 Spending Clients
    st.markdown("#### 💎 Top 5 Spending Clients")
    clients = (
        df.assign(Client_Clean=df["Client Name"].astype(str).str.strip())
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

    # Top 5 Largest Client Transactions
    st.markdown("#### 📈 Top 5 Largest Client Transactions")
    txg = tx.copy()
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

run_factoids()

# --------------------------------
# 💬 Feedback (Lazy Sheets; isolated from reruns)
# --------------------------------
st.markdown("<div id='feedback' class='anchor-offset'></div>", unsafe_allow_html=True)
st.markdown("## 💬 Feedback")
st.markdown("### Found a problem? Let me (Patrik) know here:")

@st.cache_resource(show_spinner=False)
def get_sheet():
    """Lazy Google Sheets connector."""
    SHEET_ID = "1LUK2lAmGww40aZzFpx1TSKPLvXsqmm_R5WkqXQVkf98"
    SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    try:
        creds_dict = st.secrets["gcp_service_account"]
    except Exception:
        try:
            with open("google-credentials.json", "r") as f:
                creds_dict = json.load(f)
        except FileNotFoundError:
            return None
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPE)
    try:
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
    sheet = get_sheet()
    if sheet is None:
        return []
    rows = sheet.get_all_values() or []
    data = rows[1:] if rows else []
    return data[-limit:] if data else []

fb_col1, fb_col2 = st.columns([3,1])
with fb_col1:
    feedback_text = st.text_area(
        "Describe the issue or suggestion",
        key="feedback_text",
        height=120,
        placeholder="What did you try? What happened? Any screenshots or CSV names?",
    )
with fb_col2:
    user_name_for_feedback = st.text_input("Your name (optional)", key="feedback_name", placeholder="Clinic / Your name")
    user_email_for_feedback = st.text_input("Your email (optional)", key="feedback_email", placeholder="you@example.com")

if st.button("Send", key="fb_send"):
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




































