import pandas as pd
import altair as alt
import unicodedata
import streamlit as st
import re
import json, os
import streamlit.components.v1 as components
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import date, datetime, timedelta

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
    /* Adjust headings spacing */
    .block-container h1, .block-container h2, .block-container h3 {
        margin-top: 0.2rem;
    }

    /* Reset Streamlit button height */
    div[data-testid="stButton"] {
        min-height: 0px !important;
        height: auto !important;
    }

    /* Make page use full width */
    .block-container {
        max-width: 100% !important;
        padding-left: 2rem;
        padding-right: 2rem;
    }

    /* Ensure anchor headers are not hidden under Streamlit's padding */
    h2[id] {
        scroll-margin-top: 80px;
    }

    /* Extra anchor offset trick for Upload Data */
    .anchor-offset {
        position: relative;
        top: -100px;   /* pull the anchor up so title aligns like other sections */
        height: 0;
    }
    </style>
    ''',
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

# --------------------------------
# Settings persistence (local JSON)
# (Note: on Streamlit Cloud this is ephemeral)
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

        # Start from defaults
        rules = DEFAULT_RULES.copy()

        # Merge saved rules on top
        saved_rules = settings.get("rules", {})

        # 🚑 Cleanup: remove empty visible_text values
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
    """
    Robust PMS detection using small unique key-sets per PMS.
    Returns one of: 'VETport', 'Xpress', 'ezyVet', or None.
    Optimized: avoids redundant normalize_columns() calls.
    """
    # Normalize once
    normalized_cols = set(normalize_columns(df.columns))

    # Unique key sets (lowercased)
    v_keys = {"planitem performed", "plan item amount"}
    x_keys = {"date", "animal name", "amount", "item name"}
    e_keys = {"invoice date", "total invoiced (excl)", "product name", "first name", "last name"}

    # Prefer stronger (more specific) matches
    if v_keys.issubset(normalized_cols):
        return "VETport"
    if e_keys.issubset(normalized_cols):
        return "ezyVet"
    if x_keys.issubset(normalized_cols):
        return "Xpress"

    # Fallback: try the long lists in PMS_DEFINITIONS as a last resort, first match wins
    for pms_name, definition in PMS_DEFINITIONS.items():
        required = set(definition["columns"])
        required = set(normalize_columns(required))  # normalize once per PMS, not per df
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
# 🔑 form version to re-key widgets after reset
st.session_state.setdefault("form_version", 0)

# --------------------------------
# Helpers
# --------------------------------

def simplify_vaccine_text(text: str) -> str:
    """Format vaccine names cleanly; only add Vaccine(s) when items are vaccines."""
    if not isinstance(text, str):
        return text

    # Split into parts (comma and "and")
    parts = [p.strip() for p in text.replace(" and ", ",").split(",") if p.strip()]
    cleaned = [p.strip() for p in parts if p]

    if not cleaned:
        return text

    # Special: ignore 'Vaccination' if other items exist
    cleaned_lower = [c.lower() for c in cleaned]
    if "vaccination" in cleaned_lower and len(cleaned) > 1:
        cleaned = [c for c in cleaned if c.lower() != "vaccination"]

    # Determine if ALL items are vaccines
    is_vaccine_item = lambda s: s.lower().endswith("vaccine") or s.lower().endswith("vaccines") or s.lower() in ["vaccination", "vaccine(s)"]
    all_vaccines = all(is_vaccine_item(c) for c in cleaned)

    # If all items are vaccines, strip trailing "vaccine(s)" for clean grammar
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

    # Otherwise → non-vaccine items, just return nicely joined
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
    """Normalize item names for matching."""
    if not isinstance(name, str):
        return ""
    name = unicodedata.normalize("NFKC", name).lower()
    name = re.sub(r"[\u00a0\ufeff]", " ", name)  # clean nbsp/BOM
    name = re.sub(r"[-+/().,]", " ", name)       # separators
    return re.sub(r"\s+", " ", name).strip()

@st.cache_data(show_spinner=False)
def map_intervals(df, rules):
    """
    Map item names to rules (by substring match) and compute IntervalDays.
    Uses canonical columns: Item Name, Qty, ChargeDate.
    Produces: MatchedItems (list of visible texts), IntervalDays (min of matches).
    """
    df = df.copy()
    df["MatchedItems"] = [[] for _ in range(len(df))]
    df["IntervalDays"] = pd.NA

    for idx, row in df.iterrows():
        normalized = normalize_item_name(row.get("Item Name", ""))
        matches, interval_values = [], []

        for rule, settings in rules.items():
            rule_norm = rule.lower().strip()
            if rule_norm in normalized:
                vis = settings.get("visible_text")
                # Show visible_text when present; fallback to source item
                if vis and vis.strip():
                    matches.append(vis.strip())
                else:
                    matches.append(row.get("Item Name", rule))

                days = settings["days"]
                if settings.get("use_qty"):
                    qty = pd.to_numeric(row.get("Qty", 1), errors="coerce")
                    qty = int(qty) if pd.notna(qty) else 1
                    days *= max(qty, 1)
                interval_values.append(days)

        if matches:
            df.at[idx, "MatchedItems"] = matches
            df.at[idx, "IntervalDays"] = min(interval_values)
        else:
            # No match → show the original Item Name and keep IntervalDays as NA
            df.at[idx, "MatchedItems"] = [row.get("Item Name", "")]
            df.at[idx, "IntervalDays"] = pd.NA

    return df

def parse_dates(series: pd.Series) -> pd.Series:
    """
    Robust parser for PMS date columns.
    Always strips any time or trailing junk (e.g. Vetport "01/Jan/2024 16:20 57"),
    so only the date part remains.
    Works across Vetport, Xpress, and ezyVet.
    """
    # Already datetime dtype → normalize to date
    if pd.api.types.is_datetime64_any_dtype(series):
        return pd.to_datetime(series.dt.date, errors="coerce")

    s = series.astype(str).str.strip()

    # --- Extract only the date portion ---
    s = s.str.extract(
        r"(\d{1,2}[/-][A-Za-z]{3}[/-]\d{4}|\d{1,2}[/-]\d{1,2}[/-]\d{4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})"
    )[0]

    # Excel serials
    numeric = pd.to_numeric(s, errors="coerce")
    if numeric.notna().sum() > 0:
        base_1900 = pd.Timestamp("1899-12-30")
        dt_1900 = base_1900 + pd.to_timedelta(numeric, unit="D")
        base_1904 = pd.Timestamp("1904-01-01")
        dt_1904 = base_1904 + pd.to_timedelta(numeric, unit="D")
        valid_1900 = dt_1900.dt.year.between(1990, 2100)
        valid_1904 = dt_1904.dt.year.between(1990, 2100)
        return (dt_1904 if valid_1904.sum() > valid_1900.sum() else dt_1900).dt.normalize()

    # Explicit formats
    formats = [
        "%d/%b/%Y", "%d-%b-%Y",
        "%d/%m/%Y", "%m/%d/%Y",
        "%Y-%m-%d", "%Y.%m.%d"
    ]
    for fmt in formats:
        parsed = pd.to_datetime(s, format=fmt, errors="coerce")
        if parsed.notna().sum() > 0:
            return parsed.dt.normalize()

    # Fallback: pandas inference
    parsed = pd.to_datetime(s, errors="coerce", dayfirst=True)
    return parsed.dt.normalize()
    
@st.cache_data(show_spinner=False)
def ensure_reminder_columns(df: pd.DataFrame, rules: dict) -> pd.DataFrame:
    """
    Ensure canonical reminder fields exist using the standardized schema:
    ChargeDate, Client Name, Animal Name, Item Name, Qty, Amount.
    Adds:
      - MatchedItems, IntervalDays
      - NextDueDate (ChargeDate + IntervalDays)
      - ChargeDateFmt, DueDateFmt
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=[
            "DueDateFmt", "Client Name", "ChargeDateFmt", "Animal Name",
            "MatchedItems", "Qty", "IntervalDays", "NextDueDate", "ChargeDate"
        ])

    df = df.copy()

    # Ensure canonical columns exist
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

    # Parse dates robustly
    if not pd.api.types.is_datetime64_any_dtype(df["ChargeDate"]):
        df["ChargeDate"] = parse_dates(df["ChargeDate"])

    # Map rules to intervals
    df = map_intervals(df, rules)

    # Compute next due dates
    days = pd.to_numeric(df["IntervalDays"], errors="coerce")
    df["NextDueDate"] = df["ChargeDate"] + pd.to_timedelta(days, unit="D")
    # The above keeps NaT where IntervalDays is NA

    # Format dates
    df["ChargeDateFmt"] = pd.to_datetime(df["ChargeDate"]).dt.strftime("%d %b %Y")
    df["DueDateFmt"]    = pd.to_datetime(df["NextDueDate"]).dt.strftime("%d %b %Y")

    # Ensure MatchedItems is a clean list of strings
    df["MatchedItems"] = df["MatchedItems"].apply(
        lambda v: [str(x).strip() for x in v] if isinstance(v, list) else ([str(v)] if pd.notna(v) else [])
    )
    return df
    
def drop_early_duplicates(df):
    """
    Remove reminders where the same client-animal-item combination 
    was purchased again before its next due date (e.g., early vaccination).
    """
    if df.empty:
        return df

    # Convert lists in MatchedItems to comparable strings for sorting/grouping
    df = df.copy()
    df["MatchedItems_str"] = df["MatchedItems"].apply(
        lambda x: ", ".join(sorted(x)) if isinstance(x, list) else str(x)
    )

    # Sort safely
    df = df.sort_values(["Client Name", "Animal Name", "MatchedItems_str", "ChargeDate"]).reset_index(drop=True)

    keep_mask = [True] * len(df)

    for idx, row in df.iterrows():
        client = row.get("Client Name")
        animal = row.get("Animal Name")
        item_str = row.get("MatchedItems_str", "")
        charge_date = row.get("ChargeDate")
        due_date = row.get("NextDueDate")

        # Skip if missing key info
        if not item_str or pd.isna(charge_date) or pd.isna(due_date):
            continue

        # Find later entries of the same item between charge and due date
        subset = df[
            (df["Client Name"] == client)
            & (df["Animal Name"] == animal)
            & (df["MatchedItems_str"] == item_str)
            & (df["ChargeDate"] > charge_date)
            & (df["ChargeDate"] <= due_date)
        ]

        if not subset.empty:
            # There is a later occurrence of the same item before due date → skip this row
            keep_mask[idx] = False

    return df.loc[keep_mask].drop(columns=["MatchedItems_str"]).reset_index(drop=True)

def normalize_display_case(text: str) -> str:
    """If a word is ALL CAPS, convert to Title Case. Else leave as-is."""
    if not isinstance(text, str):
        return text
    words = text.split()
    fixed = []
    for w in words:
        if w.isupper() and len(w) > 1:   # all caps, not single letters
            fixed.append(w.capitalize())
        else:
            fixed.append(w)
    return " ".join(fixed)

def clean_revenue_column(series: pd.Series) -> pd.Series:
    return (
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace(_CURRENCY_RX, "", regex=True)
        .pipe(pd.to_numeric, errors="coerce")
        .fillna(0)
    )

@st.cache_data(show_spinner=False)
def process_file(file_bytes, filename, rules):
    """
    Read the file bytes + filename, detect PMS, clean revenue, standardize to:
    ChargeDate, Client Name, Animal Name, Item Name, Qty, Amount
    Returns: df_standardized, pms_name, amount_col (raw column name)
    """
    from io import BytesIO
    file = BytesIO(file_bytes)

    # Load file
    lowerfn = filename.lower()
    if lowerfn.endswith(".csv"):
        df = pd.read_csv(file)
    elif lowerfn.endswith((".xls", ".xlsx")):
        df = pd.read_excel(file)
    else:
        raise ValueError("Unsupported file type")

    # Normalize headers
    def _normalize(c):
        return str(c).replace("\u00a0", " ").replace("\ufeff", "").strip()
    df.columns = [_normalize(c) for c in df.columns]

    # Detect PMS
    pms_name = detect_pms(df)
    if not pms_name:
        return df, None, None

    mappings = PMS_DEFINITIONS[pms_name]["mappings"]
    amount_col = mappings.get("amount")

    # Clean Amount
    if amount_col and amount_col in df.columns:
        df["Amount"] = clean_revenue_column(df[amount_col])
    else:
        df["Amount"] = 0

    # Special case: ezyVet client name from first+last
    if pms_name == "ezyVet":
        cf = mappings.get("client_first")
        cl = mappings.get("client_last")
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

    # Rename to canonical schema
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

    # Ensure canonical columns exist
    for col, default in [
        ("ChargeDate", pd.NaT),
        ("Client Name", ""),
        ("Animal Name", ""),
        ("Item Name", ""),
    ]:
        if col not in df.columns:
            df[col] = default

    # Qty column
    qty_col = mappings.get("qty")
    if qty_col and qty_col in df.columns:
        df["Qty"] = pd.to_numeric(df[qty_col], errors="coerce").fillna(1)
    else:
        fallback_qty_cols = ["Qty", "Quantity", "Plan Item Quantity"]
        found = False
        for c in fallback_qty_cols:
            if c in df.columns:
                df["Qty"] = pd.to_numeric(df[c], errors="coerce").fillna(1)
                found = True
                break
        if not found:
            df["Qty"] = 1

    # Final Amount numeric safety
    df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce").fillna(0)

    # Parse dates
    if not pd.api.types.is_datetime64_any_dtype(df["ChargeDate"]):
        if "ChargeDate" in df.columns:
            df["ChargeDate"] = parse_dates(df["ChargeDate"])
            df["ChargeDate"] = df["ChargeDate"].dt.normalize()

    # Helper lowercase cols
    df["_client_lower"] = df["Client Name"].astype(str).str.lower()
    df["_animal_lower"] = df["Animal Name"].astype(str).str.lower()
    df["_item_lower"] = df["Item Name"].astype(str).str.lower()

    return df, pms_name, amount_col
    
@st.cache_data(show_spinner=False)
def summarize_uploads(files, rules):
    """Read and summarize all uploaded files. Cached for speed."""
    datasets, summary_rows = [], []

    for file in files:
        file_bytes = file.read()
        df, pms_name, amount_col = process_file(file_bytes, file.name, rules)
        pms_name = pms_name or "Undetected"

        from_date, to_date = None, None
        if "ChargeDate" in df.columns:
            try:
                from_date = df["ChargeDate"].min()
                to_date = df["ChargeDate"].max()
            except Exception:
                pass

        summary_rows.append({
            "File name": file.name,
            "PMS": pms_name,
            "From": from_date.strftime("%d %b %Y") if pd.notna(from_date) else "-",
            "To": to_date.strftime("%d %b %Y") if pd.notna(to_date) else "-"
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

# --- Upload Data section (replace existing) ---
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

# Auto clear cache when file list changes (so cached results won't be stale)
if "last_uploaded_files" not in st.session_state:
    st.session_state["last_uploaded_files"] = []
current_files = [f.name for f in files] if files else []
if current_files != st.session_state["last_uploaded_files"]:
    if current_files != st.session_state.get("last_uploaded_files", []):
        st.session_state["last_uploaded_files"] = current_files
        st.session_state["data_version"] = st.session_state.get("data_version", 0) + 1

    st.session_state["last_uploaded_files"] = current_files
    # Also clear previously stored working_df in session state to avoid stale data
    if "working_df" in st.session_state:
        del st.session_state["working_df"]

if files:
    datasets, summary_rows = summarize_uploads(files, st.session_state["rules"])
    st.dataframe(pd.DataFrame(summary_rows), use_container_width=True)

    all_pms = {p for p, _ in datasets}
    if len(all_pms) == 1 and "Undetected" not in all_pms:
        # concatenate standardized dataframes
        working_df = pd.concat([df for _, df in datasets], ignore_index=True)
        st.session_state["working_df"] = working_df
        st.success(f"All files detected as {list(all_pms)[0]} — merging datasets.")
    else:
        # If mixing PMS types, allow concatenation as long as standard columns exist across files
        # We'll attempt to concatenate and check for required canonical columns
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

    # Always build a display "Plan Item" from canonical Item Name + rules
    if "Item Name" in df.columns:
        df["Plan Item"] = df["Item Name"].apply(
            lambda x: simplify_vaccine_text(get_visible_plan_item(x, rules))
        )
    elif "Plan Item" not in df.columns:
        df["Plan Item"] = ""

    # Exclusions apply to the final display text
    if st.session_state["exclusions"]:
        excl_pattern = "|".join(map(re.escape, st.session_state["exclusions"]))
        df = df[~df["Plan Item"].str.lower().str.contains(excl_pattern)]
    if df.empty:
        st.info("All rows excluded by exclusion list.")
        return

    render_table_with_buttons(df, key_prefix, msg_key)

def render_table_with_buttons(df, key_prefix, msg_key):
    # Column layout
    col_widths = [2, 2, 5, 3, 4, 1, 1, 2]
    headers = ["Due Date", "Charge Date", "Client Name", "Animal Name", "Plan Item", "Qty", "Days", "WA"]
    cols = st.columns(col_widths)
    for c, head in zip(cols, headers):
        c.markdown(f"**{head}**")

    # Rows
    for idx, row in df.iterrows():
        vals = {h: str(row.get(h, "")) for h in headers[:-1]}
        cols = st.columns(col_widths, gap="small")
        for j, h in enumerate(headers[:-1]):
            val = vals[h]
            if h in ["Client Name", "Animal Name", "Plan Item"]:  # clean display fields only
                val = normalize_display_case(val)
            cols[j].markdown(val)

        # WA button -> prepare message
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

    # Composer (same as before) ...
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
                    display: flex;
                    flex-direction: column;
                    gap: 10px;
                    font-family: "Source Sans Pro", sans-serif;
                  }}
                  .phone-row input {{
                    width: 100%;
                    height: 44px;
                    padding: 0 12px;
                    border: 1px solid #ccc;
                    border-radius: 6px;
                    font-size: 16px;
                    font-family: inherit;
                  }}
                  .button-row {{
                    display: flex;
                    gap: 12px;
                    align-items: center;
                    margin-top: 2px;
                  }}
                  .button-row button {{
                    height: 52px;
                    padding: 0 20px;
                    border: none;
                    border-radius: 6px;
                    cursor: pointer;
                    font-size: 18px;
                    font-weight: 600;
                    font-family: "Source Sans Pro", sans-serif;
                    flex: 1;
                  }}
                  .wa-btn {{
                    background-color: #25D366;
                    color: white;
                  }}
                  .copy-btn {{
                    background-color: #555;
                    color: white;
                  }}
                  .copy-btn:active {{
                    transform: translateY(2px);
                    filter: brightness(85%);
                  }}
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
                      url = "https://wa.me/";  // forward/search
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

# --------------------------------
# Main
# --------------------------------
if working_df is not None:
    df = working_df.copy()

    # Your name / clinic
    st.markdown("---")
    name_col, tut_col = st.columns([4,1])
    
    with name_col:
        # Make the label big using Markdown
        st.markdown("### Your name / clinic")
        # Render the text input without its label
        st.session_state["user_name"] = st.text_input(
            "", 
            value=st.session_state["user_name"], 
            key="user_name_input",
            label_visibility="collapsed"   # hides the empty label
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
    
    # Prepare reminder fields on the fully standardized df
    prepared = ensure_reminder_columns(df, st.session_state["rules"])
    prepared = drop_early_duplicates(prepared)

    
    latest_date = prepared["ChargeDate"].max()
    default_start = (latest_date + timedelta(days=1)).date() if pd.notna(latest_date) else date.today()
    start_date = st.date_input("Start Date (7-day window)", value=default_start)
    end_date = start_date + timedelta(days=6)
    
    # Filter by NextDueDate within the 7-day window
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
        filtered = df.query(
            "_client_lower.str.contains(@q, regex=False) or _animal_lower.str.contains(@q, regex=False) or _item_lower.str.contains(@q, regex=False)",
            engine="python"
        ).copy()

        filtered2 = ensure_reminder_columns(filtered, st.session_state["rules"])
        filtered2 = drop_early_duplicates(filtered2)

    
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

    # Rules editor
    st.markdown("---")
    st.markdown("<div id='search-terms' class='anchor-offset'></div>", unsafe_allow_html=True)
    st.markdown("#### 📝 Search Terms")

    st.info(
        "1. See all current Search Terms, set their recurrence interval, and delete if necessary.\n"
        "2. Decide if the Quantity column should be considered (e.g. 1× Bravecto = 90 days, 2× Bravecto = 180 days).\n"
        "3. View and edit the Visible Text which will appear in the WhatsApp template message."
    )

    # Header row
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
        
        # Use rule name itself (sanitized) instead of index for stable widget keys
        safe_rule = re.sub(r'[^a-zA-Z0-9_-]', '_', rule)
    
        with st.container():  # keeps each row discrete
            cols = st.columns([3,1,1,2,0.7], gap="small")
    
            with cols[0]:
                st.markdown(f"<div style='padding-top:8px;'>{rule}</div>", unsafe_allow_html=True)
    
            with cols[1]:
                new_values.setdefault(rule, {})["days"] = st.text_input(
                    "Days", value=str(settings["days"]),
                    key=f"days_{safe_rule}_{ver}",
                    label_visibility="collapsed"
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
                    key=f"vis_{safe_rule}_{ver}",
                    label_visibility="collapsed"
                )
    
            with cols[4]:
                if st.button("❌", key=f"del_{safe_rule}_{ver}"):
                    to_delete.append(rule)


    if to_delete:
        for rule in to_delete:
            st.session_state["rules"].pop(rule, None)
        save_settings()
        st.rerun()

    # Update / Reset + Tip
    colU, colR, colTip = st.columns([2,1,2])
    with colU:
        if st.button("Update"):
            updated = {}
            for rule, settings in st.session_state["rules"].items():
                d = int(new_values.get(rule, {}).get("days", settings["days"]))
                vis = new_values.get(rule, {}).get("visible_text", settings.get("visible_text", ""))
                # Treat blank as unset → remove from dict
                if vis.strip() == "":
                    updated[rule] = {"days": d, "use_qty": settings["use_qty"]}
                else:
                    updated[rule] = {"days": d, "use_qty": settings["use_qty"], "visible_text": vis.strip()}

            st.session_state["rules"] = updated
        
            save_settings()  # ✅ ensure JSON is written before rerun
            st.rerun()


    with colR:
        if st.button("Reset defaults"):
            st.session_state["rules"] = DEFAULT_RULES.copy()
            st.session_state["exclusions"] = []
            st.session_state["form_version"] += 1
            save_settings()
            st.rerun()

    with colTip:
        st.markdown("### 💡 Tip")
        st.info(
            "Click **Update** to save changes to Recurrence Intervals or Visible Text.\n\n"
            "Click **Reset defaults** to restore rules and exclusions to your defaults."
        )

    # Add new rule
    st.markdown("---")
    st.write("### Add New Search Term")
    st.info("💡 Add a new **Search Term** (e.g., Cardisure), set its days, whether to use quantity, and optional visible text.")
    
    # Use the counter only to make this row unique *until* it's added
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
    
                rule_data = {
                    "days": int(new_rule_days),
                    "use_qty": bool(new_rule_use_qty),
                }
                if new_rule_visible.strip():
                    rule_data["visible_text"] = new_rule_visible.strip()
                
                st.session_state["rules"][safe_rule] = rule_data

                save_settings()
                st.session_state["new_rule_counter"] += 1  # bump so next add row is fresh
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
    
    # Add new exclusion row
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


# --- Google Sheets Setup ---
SHEET_ID = "1LUK2lAmGww40aZzFpx1TSKPLvXsqmm_R5WkqXQVkf98"
SCOPE = ["https://spreadsheets.google.com/feeds",
         "https://www.googleapis.com/auth/drive"]

# Load creds (Cloud via secrets; local fallback to file if present)
try:
    creds_dict = st.secrets["gcp_service_account"]
except Exception:
    try:
        with open("google-credentials.json", "r") as f:
            creds_dict = json.load(f)
    except FileNotFoundError:
        st.error("Google credentials not found. Add them in Streamlit Secrets or google-credentials.json.")
        st.stop()

creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPE)

import time

sheet = None
try:
    client = gspread.authorize(creds)
    start = time.time()
    while sheet is None and (time.time() - start) < 5:
        try:
            sheet = client.open_by_key(SHEET_ID).sheet1
        except Exception:
            time.sleep(0.5)  # retry every half second
except Exception:
    sheet = None

if sheet is None:
    st.warning("⚠ Couldn't connect to Google Sheets. Check sharing, API enablement, and Sheet ID. Continuing without Sheets integration.")


def _next_id_from_column():
    """Find the max numeric ID in column A and add 1 (robust to mid-sheet deletions)."""
    try:
        col_ids = sheet.col_values(1)[1:]  # skip header
        nums = [int(x) for x in col_ids if x.strip().isdigit()]
        return (max(nums) if nums else 0) + 1
    except Exception:
        # Fallback if parsing fails
        return len(sheet.get_all_values())

def insert_feedback(name, email, message):
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    next_id = _next_id_from_column()
    sheet.append_row([next_id, now, name or "", email or "", message],
                     value_input_option="USER_ENTERED")

@st.cache_data(ttl=60)
def fetch_feedback(limit=500):
    rows = sheet.get_all_values()
    data = rows[1:] if rows else []
    return data[-limit:] if data else []

# --------------------------------
# Factoids Section
# --------------------------------

# Preventive Care Keyword Lists
# Preventive Care & Service Keyword Lists
FLEA_WORM_KEYWORDS = [
    "bravecto", "revolution", "deworm", "frontline", "milbe", "milpro",
    "nexgard", "simparica", "advocate", "worm", "praz", "fenbend"
]

FOOD_KEYWORDS = [
    "hill's", "hills", "royal canin", "purina", "proplan", "iams", "eukanuba",
    "orijen", "acana", "farmina", "vetlife", "wellness", "taste of the wild",
    "nutro", "pouch", "tin", "can", "canned", "wet", "dry", "kibble",
    "tuna", "chicken", "beef", "salmon", "lamb", "duck",
    "senior", "diet", "food", "grain","rc"
]

XRAY_KEYWORDS = [
    "xray", "x-ray", "radiograph", "radiology"
]

ULTRASOUND_KEYWORDS = [
    "ultrasound", "echo", "afast", "tfast", "a-fast", "t-fast"
]

LABWORK_KEYWORDS = [
    "cbc", "blood test", "lab", "biochemistry", "haematology", "urinalysis", "labwork", "idexx", "ghp", "chem", "FELV", "FIV", "urine",
    "urinalysis","elisa","CHLAMYDIA","PCR", "MICROSCOPIQUE","biochem","cytology","smear","faecal","fecal","MICROSCOPIC","SWAB","Lyte",
    "Catalyst","i-stat","istat","hematology","electrolyte","slide","bun","crea","phos","upc","sdma","lab","pcv","hct","uppc","Parasitology",
    "parvo","distemper","giardia","pap","pre-anaesthetic","pre-anasthetic","cpl","cpli","lipase","amylase","pancreatic","cortisol","lddst","acth"
]

ANAESTHETIC_KEYWORDS = [
    "anaesthesia", "anesthesia", "general anaesthetic", "ga", "propofol", "isoflurane","spay","castrate","neuter","anae","surgery","alfaxane",
    "alfaxalone"
]

HOSPITALISATION_KEYWORDS = [
    "hospitalisation", "hospitalization"
]

VACCINE_KEYWORDS = [
    "vaccine", "vaccination", "booster",
    "rabies", "dhpp", "dhppil", "tricat", "pch", "pcl", "leukemia",
    "fvr", "feline viral rhinotracheitis", "calici", "panleukopenia",
    "lepto", "kennel cough", "bordetella", "parvo", "distemper",
    "lyme", "influenza", "flu", "vacc"
]

def _rx(words):
    # literal OR; matches current behavior that looks for substrings
    return re.compile("|".join(map(re.escape, words)), flags=re.IGNORECASE)

XRAY_RX             = _rx(XRAY_KEYWORDS)
ULTRASOUND_RX       = _rx(ULTRASOUND_KEYWORDS)
FLEA_WORM_RX        = _rx(FLEA_WORM_KEYWORDS)
FOOD_RX             = _rx(FOOD_KEYWORDS)
LABWORK_RX          = _rx(LABWORK_KEYWORDS)
ANAESTHETIC_RX      = _rx(ANAESTHETIC_KEYWORDS)
HOSPITALISATION_RX  = _rx(HOSPITALISATION_KEYWORDS)
VACCINE_RX          = _rx(VACCINE_KEYWORDS)

def run_factoids():
    df = st.session_state.get("working_df")
    if df is None or df.empty:
        st.warning("Upload data first.")
        return

    df["ChargeDate"] = pd.to_datetime(df["ChargeDate"], errors="coerce")
    dentals = df[df["Item Name"].str.contains("dental", case=False, na=False)]

    data = (
        dentals.groupby(dentals["ChargeDate"].dt.to_period("M"))["Animal Name"]
        .nunique()
        .sort_index()
        .tail(12)
    )

    st.altair_chart(
        alt.Chart(data.reset_index())
        .mark_bar()
        .encode(x="ChargeDate:T", y="Animal Name:Q"),
        use_container_width=True,
    )


    # -------------------------
    # 📊 Revenue Concentration Curve
    # -------------------------
    st.markdown("---")
    st.subheader("📊 Revenue Concentration Curve")
    rev_by_client = (
        df.groupby("Client Name", dropna=False)["Amount"]
        .sum()
        .sort_values(ascending=False)
        .reset_index()
    )
    if not rev_by_client.empty and rev_by_client["Amount"].sum() > 0:
        total_rev_all = float(rev_by_client["Amount"].sum())
        n_clients = len(rev_by_client)
        rev_by_client["Rank"] = rev_by_client.index + 1
        rev_by_client["TopClientPercent"] = rev_by_client["Rank"] / n_clients * 100.0
        rev_by_client["CumRevenue"] = rev_by_client["Amount"].cumsum()
        rev_by_client["CumRevenuePercent"] = rev_by_client["CumRevenue"] / total_rev_all * 100.0

        st.altair_chart(
            alt.Chart(rev_by_client)
            .mark_line(point=True)
            .encode(
                x=alt.X("TopClientPercent:Q", title="Top X% of Clients"),
                y=alt.Y("CumRevenuePercent:Q", title="% of Total Revenue"),
                tooltip=[
                    alt.Tooltip("Client Name:N", title="Client"),
                    alt.Tooltip("Amount:Q", title="Client Spend", format=",.0f"),
                    alt.Tooltip("TopClientPercent:Q", title="Top X%", format=".1f"),
                    alt.Tooltip("CumRevenuePercent:Q", title="Cum. % Revenue", format=".1f"),
                ],
            )
            .properties(
                title="Revenue Concentration - What % of Revenue is Made Up by the Top X% Spending Clients (Mouse-over for details)",
                height=400,
                width=700,
            ),
            use_container_width=True,
        )
    else:
        st.info("No client revenue available to plot revenue concentration.")
        
    # -------------------------
    # 📅 Select Period dropdown
    # -------------------------
    st.markdown("<div style='font-size:18px; font-weight:bold; color:red;'>Select Period:</div>", unsafe_allow_html=True)
    period_options = [
        "All Data",
        "Prev 30 Days (of most recent data)",
        "Prev Quarter (of most recent data)",
        "Prev Year (of most recent data)"
    ]
    selected = st.selectbox("", period_options, index=0, label_visibility="collapsed", key="factoids_period_select")

    if not pd.isna(latest_date):
        if selected == "Prev 30 Days (of most recent data)":
            start_date = latest_date - pd.DateOffset(days=30)
            df = df[df["ChargeDate"] >= start_date]
        elif selected == "Prev Quarter (of most recent data)":
            start_date = latest_date - pd.DateOffset(months=3)
            df = df[df["ChargeDate"] >= start_date]
        elif selected == "Prev Year (of most recent data)":
            start_date = latest_date - pd.DateOffset(years=1)
            df = df[df["ChargeDate"] >= start_date]

    # --------------------------------
    # 📌 At a Glance Metrics
    # --------------------------------
    st.markdown("<div id='factoids-ataglance' class='anchor-offset'></div>", unsafe_allow_html=True)
    st.markdown("### 📌 At a Glance")

    # --- Block computation (reused) ---
    df_sorted = df.sort_values(["Client Name", "ChargeDate"]).copy()
    df_sorted["DateOnly"] = pd.to_datetime(df_sorted["ChargeDate"]).dt.normalize()
    df_sorted["DayDiff"] = df_sorted.groupby("Client Name")["DateOnly"].diff().dt.days.fillna(1)
    df_sorted["Block"] = df_sorted.groupby("Client Name")["DayDiff"].transform(lambda x: (x > 1).cumsum())

    transactions = (
        df_sorted.groupby(["Client Name", "Block"])
        .agg(
            StartDate=("DateOnly", "min"),
            EndDate=("DateOnly", "max"),
            Patients=("Animal Name", lambda x: set(x.astype(str))),
            Amount=("Amount", "sum"),
        )
        .reset_index()
    )

    daily = transactions.groupby("StartDate").agg(
        ClientTransactions=("Block", "count"),
        Patients=("Patients", lambda pats: len(set().union(*pats)) if len(pats) else 0),
    )

    # --- Daily metrics ---
    metrics = {}
    if not daily.empty:
        max_tx_day = daily["ClientTransactions"].idxmax()
        max_pat_day = daily["Patients"].idxmax()
        metrics[f"Max Transactions/Day ({max_tx_day.strftime('%d %b %Y')})"] = f"{int(daily.loc[max_tx_day, 'ClientTransactions']):,}"
        metrics["Avg Transactions/Day"] = f"{int(round(daily['ClientTransactions'].mean())):,}"
        metrics[f"Max Patients/Day ({max_pat_day.strftime('%d %b %Y')})"] = f"{int(daily.loc[max_pat_day, 'Patients']):,}"
        metrics["Avg Patients/Day"] = f"{int(round(daily['Patients'].mean())):,}"
    else:
        metrics["Max Transactions/Day"] = "-"
        metrics["Avg Transactions/Day"] = "-"
        metrics["Max Patients/Day"] = "-"
        metrics["Avg Patients/Day"] = "-"

    # --- Unique patient metrics ---
    total_patients = df["Animal Name"].nunique()
    flea_patients = df[df["Item Name"].str.contains(FLEA_WORM_RX, na=False)]["Animal Name"].nunique()
    food_patients = df[df["Item Name"].str.contains(FOOD_RX, na=False)]["Animal Name"].nunique()
    xray_patients = df[df["Item Name"].str.contains(XRAY_RX, na=False)]["Animal Name"].nunique()
    us_patients = df[df["Item Name"].str.contains(ULTRASOUND_RX, na=False)]["Animal Name"].nunique()
    lab_patients = df[df["Item Name"].str.contains(LABWORK_RX, na=False)]["Animal Name"].nunique()
    anaesth_patients = df[df["Item Name"].str.contains(ANAESTHETIC_RX, na=False)]["Animal Name"].nunique()
    hosp_patients = df[df["Item Name"].str.contains(HOSPITALISATION_RX, na=False)]["Animal Name"].nunique()
    vacc_patients = df[df["Item Name"].str.contains(VACCINE_RX, na=False)]["Animal Name"].nunique()

    # Dental logic (unique block threshold)
    dental_patients = 0
    dental_rows = df[df["Item Name"].str.contains("dental", case=False, na=False)]
    if not dental_rows.empty:
        tx = (
            df_sorted.groupby(["Client Name", "Block"])
            .agg(Amount=("Amount", "sum"), Patients=("Animal Name", lambda x: set(x.astype(str))))
            .reset_index()
        )
        dental_blocks = df_sorted[df_sorted["Item Name"].str.contains("dental", case=False, na=False)][["Client Name", "Block"]].drop_duplicates()
        qualifying_blocks = pd.merge(dental_blocks, tx, on=["Client Name", "Block"])
        qualifying_blocks = qualifying_blocks[qualifying_blocks["Amount"] > 700]
        patients = set()
        for patlist in qualifying_blocks["Patients"]:
            patients.update(patlist)
        dental_patients = len(patients)

    if total_patients > 0:
        metrics.update({
            "Total Unique Patients": f"{total_patients:,}",
            "Unique Patients Having Dentals": f"{dental_patients:,} ({dental_patients/total_patients:.1%})",
            "Unique Patients Having X-rays": f"{xray_patients:,} ({xray_patients/total_patients:.1%})",
            "Unique Patients Having Ultrasounds": f"{us_patients:,} ({us_patients/total_patients:.1%})",
            "Unique Patients Buying Flea/Worm": f"{flea_patients:,} ({flea_patients/total_patients:.1%})",
            "Unique Patients Buying Food": f"{food_patients:,} ({food_patients/total_patients:.1%})",
            "Unique Patients Having Lab Work": f"{lab_patients:,} ({lab_patients/total_patients:.1%})",
            "Unique Patients Having Anaesthetics": f"{anaesth_patients:,} ({anaesth_patients/total_patients:.1%})",
            "Unique Patients Hospitalised": f"{hosp_patients:,} ({hosp_patients/total_patients:.1%})",
            "Unique Patients Vaccinated": f"{vacc_patients:,} ({vacc_patients/total_patients:.1%})",
        })
    else:
        st.info("No patients found in dataset.")

    # --- Fun + transactional metrics ---
    unique_patients = df[["Client Name", "Animal Name"]].dropna().drop_duplicates()
    common_pet = unique_patients["Animal Name"].value_counts().head(1)
    if not common_pet.empty:
        metrics["Most Common Pet Name"] = f"{common_pet.index[0]} ({common_pet.iloc[0]:,})"

    patient_tx_counts = (
        transactions.explode("Patients")
        .dropna(subset=["Patients", "Client Name"])
        .query("Patients.str.strip() != '' and Client_Name.str.strip() != ''", engine="python")
        .copy()
    )
    
    # Normalize text for filtering out junk like 'SALE COUNTER'
    patient_tx_counts["Patients"] = patient_tx_counts["Patients"].astype(str).str.strip()
    patient_tx_counts["Client Name"] = patient_tx_counts["Client Name"].astype(str).str.strip()
    patient_tx_counts = patient_tx_counts[
        ~patient_tx_counts["Patients"].str.lower().str.contains("counter")
        & ~patient_tx_counts["Client Name"].str.lower().str.contains("counter")
    ]
    
    patient_tx_counts = (
        patient_tx_counts
        .groupby(["Patients", "Client Name"])
        .size()
        .reset_index(name="VisitCount")
        .sort_values("VisitCount", ascending=False)
    )
    
    if not patient_tx_counts.empty:
        top_patient = patient_tx_counts.iloc[0]
        metrics["Patient with Most Transactions"] = (
            f"{top_patient['Patients']} ({top_patient['Client Name']}) – {int(top_patient['VisitCount']):,}"
        )

    visits_per_client = df.groupby("Client Name")["ChargeDate"].nunique()
    total_clients = visits_per_client.shape[0]
    if total_clients > 0:
        buckets = {
            "Clients with 1 Transaction": (visits_per_client == 1).sum(),
            "Clients with 2 Transactions": (visits_per_client == 2).sum(),
            "Clients with 3-5 Transactions": ((visits_per_client >= 3) & (visits_per_client <= 5)).sum(),
            "Clients with 6+ Transactions": (visits_per_client >= 6).sum(),
        }
        for k, v in buckets.items():
            metrics[k] = f"{v:,} ({v/total_clients:.1%})"

    # ----------------------------
    # 🧱 Card rendering
    # ----------------------------
    CARD_STYLE = """
    <div style='background-color:{bg_color};
                border:1px solid #94a3b8;
                padding:16px;
                border-radius:10px;
                text-align:center;
                margin-bottom:12px;
                min-height:120px;
                display:flex;
                flex-direction:column;
                justify-content:center;'>
        <div style='font-size:13px; color:#334155; font-weight:600; line-height:1.2;'>{label}</div>
        <div style='font-size:{font_size}px; font-weight:700; color:#0f172a; margin-top:6px;'>{value}</div>
    </div>
    """

    def adjust_font_size(text, base_size=22, min_size=16):
        if len(text) > 25:
            return min_size
        elif len(text) > 18:
            return base_size - 2
        return base_size

    core_keys = [
        "Total Unique Patients",
        "Max Patients/Day",
        "Avg Patients/Day",
        "Max Transactions/Day",
        "Avg Transactions/Day",
    ]

    patient_breakdown_keys = [
        "Unique Patients Having Dentals",
        "Unique Patients Having X-rays",
        "Unique Patients Having Ultrasounds",
        "Unique Patients Buying Flea/Worm",
        "Unique Patients Buying Food",
        "Unique Patients Having Lab Work",
        "Unique Patients Having Anaesthetics",
        "Unique Patients Hospitalised",
        "Unique Patients Vaccinated",
    ]

    transaction_keys = [
        "Clients with 1 Transaction",
        "Clients with 2 Transactions",
        "Clients with 3-5 Transactions",
        "Clients with 6+ Transactions",
    ]

    fun_fact_keys = [
        "Most Common Pet Name",
        "Patient with Most Transactions",
    ]

    def render_card_group(title, keys, fuzzy=False):
        if not any(k in metrics for k in keys):
            return
        st.markdown(
            f"<h4 style='font-size:17px; font-weight:700; color:#475569; margin-top:1rem; margin-bottom:0.4rem;'>{title}</h4>",
            unsafe_allow_html=True,
        )
        cols = st.columns(5)
        i = 0
        for key in keys:
            matched_key = key
            if fuzzy:
                for existing in metrics.keys():
                    if existing.startswith(key):
                        matched_key = existing
                        break
            if matched_key in metrics:
                value = metrics.get(matched_key, "–")
                font_size = adjust_font_size(value)
                bg_color = "#f1f5f9" if not matched_key.startswith("Total Unique Patients") else "#dbeafe"
                cols[i % 5].markdown(
                    CARD_STYLE.format(bg_color=bg_color, label=matched_key, value=value, font_size=font_size),
                    unsafe_allow_html=True,
                )
                i += 1
                if i % 5 == 0 and matched_key != keys[-1]:
                    cols = st.columns(5)

    render_card_group("⭐ Core", core_keys, fuzzy=True)
    render_card_group("🐾 Patient Breakdown", patient_breakdown_keys)
    render_card_group("💼 Transaction Numbers", transaction_keys)
    render_card_group("🎉 Fun Facts", fun_fact_keys)

    # -------------------------
    # 💰 Top 20 Items by Revenue (Table 1)
    # -------------------------

    # 🔗 Sidebar anchor for “Tables” section
    st.markdown("<div id='factoids-tables' class='anchor-offset'></div>", unsafe_allow_html=True)
    st.markdown("### 📋 Tables")

    # Table title
    st.markdown("#### 💰 Top 20 Items by Revenue")
    
    top_items = (
        df.groupby("Item Name")
        .agg(TotalRevenue=("Amount", "sum"), TotalCount=("Qty", "sum"))
        .sort_values("TotalRevenue", ascending=False)
        .head(20)
    )
    
    if not top_items.empty:
        total_rev = top_items["TotalRevenue"].sum()
        top_items["% of Total Revenue"] = (top_items["TotalRevenue"] / total_rev * 100).round(1)
        top_items["Revenue"] = top_items["TotalRevenue"].apply(lambda x: f"{int(x):,}")
        top_items["How Many"] = top_items["TotalCount"].apply(lambda x: f"{int(x):,}")
        top_items["% of Total Revenue"] = top_items["% of Total Revenue"].astype(str) + "%"
    
        st.dataframe(
            top_items[["Revenue", "% of Total Revenue", "How Many"]],
            use_container_width=True
        )
    else:
        st.info("No items found for the selected period.")

    # -------------------------
    # 💎 Top 5 Spending Clients
    # -------------------------
    st.markdown("#### 💎 Top 5 Spending Clients")
    
    clients_nonblank = (
        df.dropna(subset=["Client Name"])
        .assign(Client_Clean=df["Client Name"].astype(str).str.strip())
    )
    clients_nonblank = clients_nonblank[
        (clients_nonblank["Client_Clean"] != "")
        & (~clients_nonblank["Client_Clean"].str.lower().str.contains("counter"))
    ]
    
    if not clients_nonblank.empty:
        top_clients = (
            clients_nonblank.groupby("Client_Clean")["Amount"]
            .sum()
            .sort_values(ascending=False)
            .head(5)
            .rename("Total Spend")
            .to_frame()
        )
    
        top_clients["Total Spend"] = top_clients["Total Spend"].apply(lambda x: f"{int(x):,}")
        st.dataframe(top_clients, use_container_width=True)
    else:
        st.info("No client spend data for the selected period.")

    # -------------------------
    # 📈 Top 5 Largest Client Transactions
    # -------------------------
    st.markdown("#### 📈 Top 5 Largest Client Transactions")
    tx_groups = transactions.copy()
    tx_groups["Patients"] = tx_groups["Patients"].apply(
        lambda s: ", ".join(sorted([
            p for p in s
            if isinstance(p, str)
            and p.strip() != ""
            and "counter" not in p.lower()
        ]))
    )
    tx_groups = tx_groups[
        tx_groups["Client Name"].notna()
        & tx_groups["Client Name"].astype(str).str.strip().ne("")
        & ~tx_groups["Client Name"].astype(str).str.lower().str.contains("counter")
    ]
    largest_tx = tx_groups.sort_values("Amount", ascending=False).head(5)

    if not largest_tx.empty:
        largest_tx = largest_tx[["Client Name", "StartDate", "EndDate", "Patients", "Amount"]]
        largest_tx["Amount"] = largest_tx["Amount"].apply(lambda x: f"{int(x):,}")
        largest_tx["DateRange"] = largest_tx.apply(
            lambda r: f"{r['StartDate'].strftime('%d %b %Y')} → {r['EndDate'].strftime('%d %b %Y')}"
            if r["StartDate"] != r["EndDate"]
            else r["StartDate"].strftime("%d %b %Y"),
            axis=1,
        )
        st.dataframe(largest_tx[["Client Name", "DateRange", "Patients", "Amount"]], use_container_width=True)
    else:
        st.info("No transactions found.")

run_factoids()

# --------------------------------
# 💬 Feedback
# --------------------------------
st.markdown("<div id='feedback' class='anchor-offset'></div>", unsafe_allow_html=True)
st.markdown("## 💬 Feedback")
st.markdown("### Found a problem? Let me (Patrik) know here:")

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

            # clear inputs
            for k in ["feedback_text", "feedback_name", "feedback_email"]:
                if k in st.session_state:
                    del st.session_state[k]
        except Exception as e:
            st.error(f"Could not save your message. {e}")
















