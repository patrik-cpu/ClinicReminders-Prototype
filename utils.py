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
        "columns": [
            "Planitem Performed", "Client Name", "Patient Name",
            "Plan Item Name", "Plan Item Quantity", "Plan Item Amount"
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

# --------------------------------
# Helpers
# --------------------------------
def simplify_vaccine_text(text: str) -> str:
    if not isinstance(text, str): return text
    parts = [p.strip() for p in text.replace(" and ", ",").split(",") if p.strip()]
    cleaned = [p.strip() for p in parts if p]
    if not cleaned: return text
    cleaned_lower = [c.lower() for c in cleaned]
    if "vaccination" in cleaned_lower and len(cleaned) > 1:
        cleaned = [c for c in cleaned if c.lower() != "vaccination"]
    is_vax = lambda s: s.lower().endswith("vaccine") or s.lower().endswith("vaccines") or s.lower() in ["vaccination","vaccine(s)"]
    if all(is_vax(c) for c in cleaned):
        stripped = []
        for c in cleaned:
            tokens = c.split()
            if tokens and tokens[-1].lower().startswith("vaccine"): tokens = tokens[:-1]
            stripped.append(" ".join(tokens).strip())
        stripped = [s for s in stripped if s]
        if len(stripped) == 1: return stripped[0] + " Vaccine"
        if len(stripped) == 2: return f"{stripped[0]} and {stripped[1]} Vaccines"
        return f"{', '.join(stripped[:-1])} and {stripped[-1]} Vaccines"
    if len(cleaned) == 1: return cleaned[0]
    if len(cleaned) == 2: return f"{cleaned[0]} and {cleaned[1]}"
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

def normalize_display_case(text: str) -> str:
    if not isinstance(text, str): return text
    return " ".join([w.capitalize() if w.isupper() and len(w) > 1 else w for w in text.split()])

def normalize_item_name(name: str) -> str:
    if not isinstance(name, str): return ""
    name = unicodedata.normalize("NFKC", name).lower()
    name = re.sub(r"[\u00a0\ufeff]", " ", name)
    name = re.sub(r"[-+/().,]", " ", name)
    return re.sub(r"\s+", " ", name).strip()

def map_intervals(df, rules):
    df = df.copy()
    df["MatchedItems"] = [[] for _ in range(len(df))]
    df["IntervalDays"] = pd.NA
    for idx, row in df.iterrows():
        normalized = normalize_item_name(row.get("Plan Item Name", ""))
        matches, interval_values = [], []
        for rule, settings in rules.items():
            rule_norm = rule.lower().strip()
            if rule_norm in normalized:
                vis = settings.get("visible_text")
                matches.append(vis.strip() if vis and vis.strip() else row.get("Plan Item Name", rule))
                days = settings["days"]
                if settings.get("use_qty"):
                    qty = pd.to_numeric(row.get("Quantity", 1), errors="coerce")
                    qty = int(qty) if pd.notna(qty) else 1
                    days *= max(qty, 1)
                interval_values.append(days)
        if matches:
            df.at[idx, "MatchedItems"] = matches
            df.at[idx, "IntervalDays"] = min(interval_values)
        else:
            df.at[idx, "MatchedItems"] = [row.get("Plan Item Name", "")]
            df.at[idx, "IntervalDays"] = pd.NA
    return df

def parse_dates(series: pd.Series) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(series):
        return pd.to_datetime(series, errors="coerce")
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().sum() > 0:
        base_1900 = pd.Timestamp("1899-12-30")
        dt_1900 = base_1900 + pd.to_timedelta(numeric, unit="D")
        valid_1900 = dt_1900.dt.year.between(1990, 2100)
        base_1904 = pd.Timestamp("1904-01-01")
        dt_1904 = base_1904 + pd.to_timedelta(numeric, unit="D")
        valid_1904 = dt_1904.dt.year.between(1990, 2100)
        return dt_1904 if valid_1904.sum() > valid_1900.sum() else dt_1900
    s = series.astype(str).str.replace("\u00a0"," ",regex=False).str.replace("\ufeff","",regex=False).str.strip()
    formats = ["%d/%b/%Y","%d-%b-%Y","%d-%b-%y","%d/%m/%Y","%m/%d/%Y","%Y-%m-%d","%Y.%m.%d",
               "%d/%m/%Y %H:%M","%d/%m/%Y %H:%M:%S","%Y-%m-%d %H:%M:%S","%Y-%m-%d %H:%M"]
    for fmt in formats:
        parsed = pd.to_datetime(s, format=fmt, errors="coerce")
        if parsed.notna().sum() > 0: return parsed
    parsed = pd.to_datetime(s, errors="coerce", dayfirst=True)
    if parsed.notna().sum() > 0: return parsed
    return pd.to_datetime(s, errors="coerce")

def ensure_reminder_columns(df: pd.DataFrame, rules: dict) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["DueDateFmt","Client Name","ChargeDateFmt","Patient Name",
                                     "MatchedItems","Quantity","IntervalDays","NextDueDate","Planitem Performed"])
    df = df.copy()
    if "Quantity" not in df.columns: df["Quantity"] = 1
    df = map_intervals(df, rules)
    if "Planitem Performed" in df.columns and not pd.api.types.is_datetime64_any_dtype(df["Planitem Performed"]):
        df["Planitem Performed"] = parse_dates(df["Planitem Performed"])
    days = pd.to_numeric(df["IntervalDays"], errors="coerce")
    df["NextDueDate"] = df["Planitem Performed"] + pd.to_timedelta(days, unit="D")
    df["ChargeDateFmt"] = pd.to_datetime(df["Planitem Performed"]).dt.strftime("%d %b %Y")
    df["DueDateFmt"] = pd.to_datetime(df["NextDueDate"]).dt.strftime("%d %b %Y")
    for col in ["Patient Name", "Client Name"]:
        if col not in df.columns: df[col] = ""
    df["MatchedItems"] = df["MatchedItems"].apply(lambda v: [str(x).strip() for x in v] if isinstance(v, list) else ([str(v)] if pd.notna(v) else []))
    return df

@st.cache_data
def process_file(file, rules):
    name = file.name.lower()
    if name.endswith(".csv"):
        df = pd.read_csv(file)
    elif name.endswith((".xls", ".xlsx")):
        df = pd.read_excel(file)
    else:
        raise ValueError("Unsupported file type")

    # Clean column names
    df.columns = [c.strip().replace("\u00a0", " ").replace("\ufeff", "") for c in df.columns]

    # Detect PMS
    pms_name = detect_pms(df)
    if not pms_name:
        return df, None
    mappings = PMS_DEFINITIONS[pms_name]["mappings"]

    # --- Handle ezyVet special case (Client Name from first+last) ---
    if pms_name == "ezyVet":
        df["Client Name"] = (
            df[mappings["client_first"]].fillna("").astype(str).str.strip()
            + " "
            + df[mappings["client_last"]].fillna("").astype(str).str.strip()
        ).str.strip()
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

    # Rename columns
    df.rename(columns=rename_map, inplace=True)

    # --- Handle Amount column consistently ---
    if "amount" in mappings and mappings["amount"] in df.columns:
        df["Amount"] = (
            df[mappings["amount"]]
            .astype(str)
            .str.replace(r"[^\d.\-]", "", regex=True)  # remove non-numeric chars
        )
        df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce").fillna(0)
    else:
        df["Amount"] = 0

    # Parse dates
    if "Planitem Performed" in df.columns:
        df["Planitem Performed"] = parse_dates(df["Planitem Performed"])

    # Ensure Quantity column
    qty_col = mappings.get("qty")
    df["Quantity"] = pd.to_numeric(df.get(qty_col, 1), errors="coerce").fillna(1)

    # Map intervals (reminders)
    df = map_intervals(df, rules)
    df["NextDueDate"] = df["Planitem Performed"] + pd.to_timedelta(df["IntervalDays"], unit="D")
    df["ChargeDateFmt"] = df["Planitem Performed"].dt.strftime("%d %b %Y")
    df["DueDateFmt"] = df["NextDueDate"].dt.strftime("%d %b %Y")

    # Lowercase helper columns
    df["_client_lower"] = df["Client Name"].astype(str).str.lower()
    df["_animal_lower"] = df["Patient Name"].astype(str).str.lower()
    df["_item_lower"] = df["Plan Item Name"].astype(str).str.lower()

    return df, pms_name


# --------------------------------
# Preventive Care Keyword Lists
# --------------------------------
FLEA_WORM_KEYWORDS = [
    "bravecto", "revolution", "deworm", "frontline", "milbe", "milpro", "nexgard", "simparica", "advocate", "worm","praz","fenbend"
]

FOOD_KEYWORDS = [
    "hill's", "hills", "royal canin", "purina", "proplan", "iams", "eukanuba",
    "orijen", "acana", "farmina", "vetlife", "wellness", "taste of the wild", "nutro",
    "pouch", "tin", "can", "canned", "wet", "dry", "kibble",
    "tuna", "chicken", "beef", "salmon", "lamb", "duck",
    "senior", "diet", "food", "grain"
]
