import pandas as pd
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

# Sidebar "table of contents"
st.sidebar.markdown(
    """
    <div style="font-size:18px; font-weight:bold;">📂 Navigation</div>
    <ul style="list-style-type:none; padding-left:0; line-height:1.8;">
      <li><a href="#tutorial" style="text-decoration:none;">📖 Tutorial</a></li>
      <li><a href="#upload-data" style="text-decoration:none;">📂 Upload Data</a></li>
      <li><a href="#weekly-reminders" style="text-decoration:none;">📅 Weekly Reminders</a></li>
      <li><a href="#search" style="text-decoration:none;">🔍 Search</a></li>
      <li><a href="#search-terms" style="text-decoration:none;">📝 Search Terms</a></li>
      <li><a href="#exclusions" style="text-decoration:none;">🚫 Exclusions</a></li>
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
    st.title("ClinicReminders Prototype v3.4 (stable)")
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
    "rabies": {"days": 365, "use_qty": False, "visible_text": "Rabies vaccine"},
    "dhppil": {"days": 365, "use_qty": False, "visible_text": "DHPPIL vaccine"},
    "leukemia": {"days": 365, "use_qty": False, "visible_text": "Leukemia vaccine"},
    "tricat": {"days": 365, "use_qty": False, "visible_text": "Tricat vaccine"},
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
    "milbem": {"days": 90, "use_qty": False, "visible_text": "Deworming"},
    "milpro": {"days": 90, "use_qty": False, "visible_text": "Deworming"},
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
    "kennel cough": {"days": 365, "use_qty": False, "visible_text": "Kennel Cough vaccine"},
}

# --------------------------------
# Settings persistence (local JSON)
# (Note: on Streamlit Cloud this is ephemeral)
# --------------------------------
SETTINGS_FILE = "clinicreminders_settings.json"

def save_settings():
    settings = {
        "rules": st.session_state["rules"],
        "exclusions": st.session_state["exclusions"],
        "user_name": st.session_state["user_name"],
    }
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f)

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r") as f:
            settings = json.load(f)
        st.session_state["rules"] = settings.get("rules", DEFAULT_RULES.copy())
        st.session_state["exclusions"] = settings.get("exclusions", [])
        st.session_state["user_name"] = settings.get("user_name", "")
    else:
        st.session_state["rules"] = DEFAULT_RULES.copy()
        st.session_state["exclusions"] = []
        st.session_state["user_name"] = ""

# --------------------------------
# PMS definitions
# --------------------------------
PMS_DEFINITIONS = {
    "VETport": {
        "columns": [
            "Planitem Performed", "Client Name", "Client ID", "Patient Name",
            "Patient ID", "Plan Item ID", "Plan Item Name", "Plan Item Quantity",
            "Performed Staff", "Plan Item Amount", "Returned Quantity",
            "Returned Date", "Invoice No",
        ],
        "mappings": {
            "date": "Planitem Performed",
            "client": "Client Name",
            "animal": "Patient Name",
            "item": "Plan Item Name",
            "qty": "Plan Item Quantity",
        }
    },
    "Xpress": {
        "columns": [
            "Date", "Client ID", "Client Name", "SLNo", "Doctor",
            "Animal Name", "Item Name", "Item ID", "Qty", "Rate",
            "Amount"
        ],
        "mappings": {
            "date": "Date",
            "client": "Client Name",
            "animal": "Animal Name",
            "item": "Item Name",
            "qty": "Qty",
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
            "date": "Invoice Date",                         # → Planitem Performed
            "client_first": "First Name",                   # combine First + Last
            "client_last": "Last Name",
            "animal": "Patient Name",                       # → Patient Name
            "item": "Product Name",                         # → Plan Item Name
            "qty": "Qty",                                   # → Quantity
        }
    }
}


def normalize_columns(cols):
    """Lowercase, collapse spaces, strip BOM/nbsp for robust comparison."""
    cleaned = []
    for c in cols:
        if not isinstance(c, str):
            c = str(c)
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
    if not isinstance(text, str): return text
    if text.lower().count("vaccine") <= 1: return text
    parts = [p.strip() for p in text.replace(" and ", ",").split(",") if p.strip()]
    cleaned = []
    for p in parts:
        tokens = p.split()
        if tokens and tokens[-1].lower().startswith("vaccine"):
            tokens = tokens[:-1]
        cleaned.append(" ".join(tokens).strip())
    if len(cleaned) == 1:
        return cleaned[0] + " Vaccines"
    return ", ".join(cleaned[:-1]) + " and " + cleaned[-1] + " Vaccines"

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
            return settings.get("visible_text") or item_name
    return item_name

def map_intervals(df, rules):
    df["MatchedItems"] = [[] for _ in range(len(df))]
    df["IntervalDays"] = pd.NA

    for idx, row in df.iterrows():
        # normalize invoice text
        name = str(row["Plan Item Name"]).lower()
        name = name.replace("\u00a0", " ").replace("\ufeff", " ")
        name = re.sub(r"[^a-z0-9 ]", " ", name)   # drop punctuation
        name = re.sub(r"\s+", " ", name).strip()

        matches, interval_values = [], []

        for rule, settings in rules.items():
            rule_norm = rule.lower().strip()
            if rule_norm in name:  # simple substring match, more forgiving
                matches.append(settings.get("visible_text", rule.title()))
                interval_values.append(
                    row["Quantity"] * settings["days"] if settings["use_qty"] else settings["days"]
                )

        if matches:
            df.at[idx, "MatchedItems"] = matches
            df.at[idx, "IntervalDays"] = min(interval_values) if interval_values else pd.NA
        else:
            df.at[idx, "MatchedItems"] = [row["Plan Item Name"]]
            df.at[idx, "IntervalDays"] = pd.NA

    return df



def parse_dates(series: pd.Series) -> pd.Series:
    """
    Robust parser:
      - If already datetime, return as-is.
      - If numeric (Excel serial), convert (tries 1900 and 1904 systems).
      - Else try multiple explicit formats, then pandas with dayfirst=True, then fallback.
    """
    # Already datetime?
    if pd.api.types.is_datetime64_any_dtype(series):
        return pd.to_datetime(series, errors="coerce")

    # Try numeric Excel serials first (before string-casting)
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().sum() > 0:
        # Consider rows that look purely numeric (e.g., "45234" or 45234.0)
        # If majority are numeric, treat as Excel serials
        numeric_like = series.astype(str).str.fullmatch(r"\d+(\.0+)?", na=False)
        if numeric_like.sum() >= max(1, int(0.6 * len(series.dropna()))):
            base_1900 = pd.Timestamp("1899-12-30")
            dt_1900 = base_1900 + pd.to_timedelta(numeric, unit="D")
            valid_1900 = dt_1900.dt.year.between(1990, 2100)

            base_1904 = pd.Timestamp("1904-01-01")
            dt_1904 = base_1904 + pd.to_timedelta(numeric, unit="D")
            valid_1904 = dt_1904.dt.year.between(1990, 2100)

            # Choose the system with more plausible dates
            if valid_1904.sum() > valid_1900.sum():
                return dt_1904
            else:
                return dt_1900

    # Clean strings and try explicit formats
    s = (
        series.astype(str)
        .str.replace("\u00a0", " ", regex=False)
        .str.replace("\ufeff", "", regex=False)
        .str.strip()
    )
    formats = [
        "%d/%b/%Y",      # 12/Jan/2024
        "%d-%b-%Y",      # 12-Jan-2024
        "%d-%b-%y",      # 12-Jan-24
        "%d/%m/%Y",      # 12/01/2024
        "%m/%d/%Y",      # 01/12/2024
        "%Y-%m-%d",      # 2024-01-12
        "%Y.%m.%d",      # 2024.01.12
        "%d/%m/%Y %H:%M",    # 12/01/2024 00:00
        "%d/%m/%Y %H:%M:%S", # 12/01/2024 00:00:00
        "%Y-%m-%d %H:%M:%S", # 2024-06-28 18:18:16 (ezyVet exports)
        "%Y-%m-%d %H:%M",    # 2024-06-28 18:18
    ]
    for fmt in formats:
        parsed = pd.to_datetime(s, format=fmt, errors="coerce")
        if parsed.notna().sum() > 0:
            return parsed

    # Try pandas inference with dayfirst preference, then without
    parsed = pd.to_datetime(s, errors="coerce", dayfirst=True)
    if parsed.notna().sum() > 0:
        return parsed
    return pd.to_datetime(s, errors="coerce")

def ensure_reminder_columns(df: pd.DataFrame, rules: dict) -> pd.DataFrame:
    """Guarantee all columns needed for grouping exist with sane values."""
    if df is None or df.empty:
        return pd.DataFrame(columns=[
            "DueDateFmt","Client Name","ChargeDateFmt","Patient Name",
            "MatchedItems","Quantity","IntervalDays","NextDueDate","Planitem Performed"
        ])

    df = df.copy()

    # Quantity default
    if "Quantity" not in df.columns:
        df["Quantity"] = 1

    # Ensure MatchedItems & IntervalDays exist (use map_intervals if needed)
    if "MatchedItems" not in df.columns or "IntervalDays" not in df.columns:
        df = map_intervals(df, rules)

    if "IntervalDays" not in df.columns:
        df["IntervalDays"] = pd.NA

    # Dates: make sure Planitem Performed is datetime
    if "Planitem Performed" in df.columns and not pd.api.types.is_datetime64_any_dtype(df["Planitem Performed"]):
        df["Planitem Performed"] = parse_dates(df["Planitem Performed"])

    # Compute NextDueDate if missing
    if "NextDueDate" not in df.columns:
        days = pd.to_numeric(df["IntervalDays"], errors="coerce")
        df["NextDueDate"] = pd.to_datetime(df.get("Planitem Performed")) + pd.to_timedelta(days, unit="D")

    # Pretty date strings
    if "ChargeDateFmt" not in df.columns:
        if "Planitem Performed" in df.columns:
            df["ChargeDateFmt"] = pd.to_datetime(df["Planitem Performed"]).dt.strftime("%d %b %Y")
        else:
            df["ChargeDateFmt"] = ""

    if "DueDateFmt" not in df.columns:
        if "NextDueDate" in df.columns:
            df["DueDateFmt"] = pd.to_datetime(df["NextDueDate"]).dt.strftime("%d %b %Y")
        else:
            df["DueDateFmt"] = ""

    # Ensure these text columns exist
    if "Patient Name" not in df.columns:
        df["Patient Name"] = ""
    if "Client Name" not in df.columns:
        df["Client Name"] = ""

    # Ensure MatchedItems is always a list[str]
    def _to_list(v):
        if isinstance(v, list):
            return [str(x) for x in v if isinstance(x, (str, int, float)) and str(x).strip()]
        if pd.isna(v):
            return []
        return [str(v)]
    df["MatchedItems"] = df["MatchedItems"].apply(_to_list)

    return df



# --------------------------------
# Cached CSV processor
# --------------------------------

@st.cache_data
def process_file(file, rules):
    # Choose parser based on extension
    name = file.name.lower()
    if name.endswith(".csv"):
        df = pd.read_csv(file)
    elif name.endswith((".xls", ".xlsx")):
        df = pd.read_excel(file)
    else:
        raise ValueError("Unsupported file type")

    # Clean column names (surface level)
    df.columns = [c.strip() for c in df.columns]

    # Detect PMS on *normalized* headers
    pms_name = detect_pms(df)
    if not pms_name:
        return df, None  # undetected PMS
    # --- Date parsing ---
    if "Planitem Performed" in df.columns:
        if pms_name == "VETport":
            # Hardcode the known format for VETport
            df["Planitem Performed"] = pd.to_datetime(
                df["Planitem Performed"].astype(str).str.strip(),
                format="%d/%b/%Y %H:%M %S",
                errors="coerce"
            )
        else:
            # All other PMS can use the generic parser
            df["Planitem Performed"] = parse_dates(df["Planitem Performed"])

    mappings = PMS_DEFINITIONS[pms_name]["mappings"]

    # --- Normalize columns FIRST ---
    if pms_name == "ezyVet":
        # Build client name
        df["Client Name"] = (
            df[mappings["client_first"]].fillna("").astype(str).str.strip() + " " +
            df[mappings["client_last"]].fillna("").astype(str).str.strip()
        ).str.strip()

        df.rename(
            columns={
                mappings["date"]: "Planitem Performed",
                mappings["animal"]: "Patient Name",
                mappings["item"]: "Plan Item Name",
            },
            inplace=True,
        )
    else:
        df.rename(
            columns={
                mappings["date"]: "Planitem Performed",
                mappings["client"]: "Client Name",
                mappings["animal"]: "Patient Name",
                mappings["item"]: "Plan Item Name",
            },
            inplace=True,
        )

    # --- Date parsing on unified column ---
    if "Planitem Performed" in df.columns:
        df["Planitem Performed"] = parse_dates(df["Planitem Performed"])

    # --- Quantity (kept on original source column name) ---
    qty_col = mappings.get("qty")
    if qty_col and qty_col in df.columns:
        df["Quantity"] = pd.to_numeric(df[qty_col], errors="coerce").fillna(1)
    else:
        df["Quantity"] = 1

    # --- Standardize downstream fields ---
    df = map_intervals(df, rules)
    df["NextDueDate"] = df["Planitem Performed"] + pd.to_timedelta(df["IntervalDays"], unit="D")
    df["ChargeDateFmt"] = df["Planitem Performed"].dt.strftime("%d %b %Y")
    df["DueDateFmt"] = df["NextDueDate"].dt.strftime("%d %b %Y")
    df["_client_lower"] = df["Client Name"].astype(str).str.lower()
    df["_animal_lower"] = df["Patient Name"].astype(str).str.lower()
    df["_item_lower"] = df["Plan Item Name"].astype(str).str.lower()

    return df, pms_name

# --------------------------------
# Tutorial section
# --------------------------------
st.markdown("<h2 id='tutorial'>📖 Tutorial</h2>", unsafe_allow_html=True)

st.info(
    "1. How it works: ClinicReminders checks when an item/service was purchased (e.g. Bravecto or Dental cleaning), "
    "and sets a custom future reminder (e.g. 90 days or 1 year).\n"
    "2. To start, upload your Invoiced Transactions data, and check that the PMS and date range is correct.\n"
    "3. Once uploaded, click on 'Start Date 7-day Window'. You will see reminders coming up for the next 7 days.\n"
    "4. Review the list of upcoming reminders. To generate a template WhatsApp message, click the WA button and review the output.\n"
    "5. Review the Search Terms list below the main table to customise the reminders, their recurring interval, and other specifics.\n"
    "6. You can also Add new terms or Delete terms.\n"
    "7. There's a bit more you can do, but this should be enough to get you started!"
)

# --------------------------------
# Upload Data section
# --------------------------------
st.markdown("<div id='upload-data' class='anchor-offset'></div>", unsafe_allow_html=True)  # stable scroll target
st.markdown("## 📂 Upload Data - Do this first!")

files = st.file_uploader(
    "Upload Sales Plan file(s)",
    type=["csv", "xls", "xlsx"],
    accept_multiple_files=True
)

datasets, summary_rows, working_df = [], [], None

if files:
    for file in files:
        df, pms_name = process_file(file, st.session_state["rules"])
        pms_name = pms_name or "Undetected"

        from_date, to_date = None, None
        if "Planitem Performed" in df.columns:
            from_date, to_date = df["Planitem Performed"].min(), df["Planitem Performed"].max()

        summary_rows.append({
            "File name": file.name,
            "PMS": pms_name,
            "From": from_date.strftime("%d %b %Y") if pd.notna(from_date) else "-",
            "To": to_date.strftime("%d %b %Y") if pd.notna(to_date) else "-"
        })
        datasets.append((pms_name, df))

    st.dataframe(pd.DataFrame(summary_rows), use_container_width=True)

    all_pms = {p for p, _ in datasets}
    if len(all_pms) == 1 and "Undetected" not in all_pms:
        working_df = pd.concat([df for _, df in datasets], ignore_index=True)
        st.success(f"All files detected as {list(all_pms)[0]} — merging datasets.")
    else:
        st.warning("PMS mismatch or undetected files. Reminders cannot be generated.")


# --------------------------------
# Render Tables
# --------------------------------
def render_table(df, title, key_prefix, msg_key, rules):
    if df.empty:
        st.info(f"No reminders in {title}."); return
    df = df.copy()
    source_col = "Plan Item Name" if "Plan Item Name" in df.columns else "Plan Item"
    df["Plan Item"] = df[source_col].apply(lambda x: simplify_vaccine_text(get_visible_plan_item(x, rules)))
    if st.session_state["exclusions"]:
        excl_pattern = "|".join(map(re.escape, st.session_state["exclusions"]))
        df = df[~df["Plan Item"].str.lower().str.contains(excl_pattern)]
    if df.empty:
        st.info("All rows excluded by exclusion list."); return
    render_table_with_buttons(df, key_prefix, msg_key)
def render_table_with_buttons(df, key_prefix, msg_key):
    # Column layout
    col_widths = [2, 2, 5, 3, 4, 1, 1, 2]
    headers = ["Due Date","Charge Date","Client Name","Animal Name","Plan Item","Qty","Days","WA"]
    cols = st.columns(col_widths)
    for c, head in zip(cols, headers):
        c.markdown(f"**{head}**")

    # Rows
    for idx, row in df.iterrows():
        vals = {h: str(row.get(h, "")) for h in headers[:-1]}
        cols = st.columns(col_widths, gap="small")
        for j, h in enumerate(headers[:-1]):
            cols[j].markdown(vals[h])

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

    # Composer (message text via Streamlit; phone input + buttons inside HTML for live behavior)
    comp_main, comp_tip = st.columns([4,1])
    with comp_main:
        st.write("### WhatsApp Composer")

        if msg_key not in st.session_state:
            st.session_state[msg_key] = ""
        st.text_area("Message:", key=msg_key, height=200)

        current_message = st.session_state.get(msg_key, "")

        # HTML block: phone input + buttons
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
                      // No phone → copy automatically before opening
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
    # ⚠️ Warning note under buttons
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
    st.markdown("<h2 id='weekly-reminders'>📅 Weekly Reminders</h2>", unsafe_allow_html=True)
    st.info("💡 Pick a Start Date to see reminders for the next 7-day window. Click WA to prepare a message.")

    latest_date = df["Planitem Performed"].max()
    default_start = (latest_date + timedelta(days=1)).date() if pd.notna(latest_date) else date.today()
    start_date = st.date_input("Start Date (7-day window)", value=default_start)
    end_date = start_date + timedelta(days=6)

    due = df[(df["NextDueDate"] >= pd.to_datetime(start_date)) & (df["NextDueDate"] <= pd.to_datetime(end_date))]
    due2 = ensure_reminder_columns(due, st.session_state["rules"])

    g = due2.groupby(["DueDateFmt", "Client Name"], dropna=False)
    grouped = (
        pd.DataFrame({
            "Charge Date": g["ChargeDateFmt"].max(),
            "Animal Name": g["Patient Name"].apply(lambda s: format_items(sorted(set(s.dropna())))),
            "Plan Item": g["MatchedItems"].apply(
                lambda lists: simplify_vaccine_text(
                    format_items(sorted(set(
                        i.strip() for sub in lists for i in (sub if isinstance(sub, list) else [sub]) if str(i).strip()
                    )))
                )
            ),
            "Qty": g["Quantity"].sum(min_count=1),
            "Days": g["IntervalDays"].apply(
                lambda x: int(pd.to_numeric(x, errors="coerce").dropna().min())
                    if pd.to_numeric(x, errors="coerce").notna().any()
                    else ""
            ),
        })
        .reset_index()
        .rename(columns={"DueDateFmt": "Due Date"})
    )[["Due Date","Charge Date","Client Name","Animal Name","Plan Item","Qty","Days"]]
    
    grouped["Qty"] = pd.to_numeric(grouped["Qty"], errors="coerce").fillna(0).astype(int)
    grouped = grouped[["Due Date","Charge Date","Client Name","Animal Name","Plan Item","Qty","Days"]]
    render_table(grouped, f"{start_date} to {end_date}", "weekly", "weekly_message", st.session_state["rules"])

    # --------------------------------
    # Search
    # --------------------------------
    st.markdown("---")
    st.markdown("<h2 id='search'>🔍 Search</h2>", unsafe_allow_html=True)
    st.info("💡 Search by client, animal, or plan item to find upcoming reminders.")
    search_term = st.text_input("Enter text to search (client, animal, or plan item)")
    if search_term:
        q = search_term.lower()
        mask = (
            df["_client_lower"].str.contains(q, regex=False) |
            df["_animal_lower"].str.contains(q, regex=False) |
            df["_item_lower"].str.contains(q, regex=False)
        )
        filtered = df[mask].copy().sort_values("NextDueDate")
    
        filtered2 = ensure_reminder_columns(filtered, st.session_state["rules"])
    
        if not filtered2.empty:
            g = filtered2.groupby(["DueDateFmt", "Client Name"], dropna=False)
            grouped_search = (
                pd.DataFrame({
                    "Charge Date": g["ChargeDateFmt"].max(),
                    "Animal Name": g["Patient Name"].apply(lambda s: format_items(sorted(set(s.dropna())))),
                    "Plan Item": g["MatchedItems"].apply(
                        lambda lists: simplify_vaccine_text(
                            format_items(sorted(set(
                                i.strip() for sub in lists for i in (sub if isinstance(sub, list) else [sub]) if str(i).strip()
                            )))
                        )
                    ),
                    "Qty": g["Quantity"].sum(min_count=1),
                    "Days": g["IntervalDays"].apply(
                        lambda x: int(pd.to_numeric(x, errors="coerce").dropna().min())
                            if pd.to_numeric(x, errors="coerce").notna().any()
                            else ""
                    ),
                })
                .reset_index()
                .rename(columns={"DueDateFmt": "Due Date"})
            )[["Due Date","Charge Date","Client Name","Animal Name","Plan Item","Qty","Days"]]
    
            render_table(grouped_search, "Search Results", "search", "search_message", st.session_state["rules"])
        else:
            st.info("No matches found.")



    # Rules editor
    st.markdown("---")
    st.markdown("<h2 id='search-terms'>📝 Search Terms</h2>", unsafe_allow_html=True)
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
                updated[rule] = {"days": d, "use_qty": settings["use_qty"], "visible_text": vis}
            st.session_state["rules"] = updated
        
            save_settings()  # ✅ ensure JSON is written before rerun
            st.rerun()


    with colR:
        if st.button("Reset defaults"):
            reset_rules = {
                k: {"days": v["days"], "use_qty": v["use_qty"], "visible_text": v.get("visible_text","")}
                for k, v in DEFAULT_RULES.items()
            }
            st.session_state["rules"] = reset_rules
            st.session_state["exclusions"] = []
            st.session_state["form_version"] += 1
        
            save_settings()  # ✅ ensure persistence
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
    
                st.session_state["rules"][safe_rule] = {
                    "days": int(new_rule_days),
                    "use_qty": bool(new_rule_use_qty),
                    "visible_text": new_rule_visible.strip(),
                }
                save_settings()
                st.session_state["new_rule_counter"] += 1  # bump so next add row is fresh
                st.rerun()
            else:
                st.error("Enter a name and valid integer for days")


    # --------------------------------
    # Exclusions
    # --------------------------------
    st.markdown("---")
    st.markdown("<h2 id='exclusions'>🚫 Exclusions</h2>", unsafe_allow_html=True)
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

try:
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SHEET_ID).sheet1
except Exception as e:
    st.error("Couldn't connect to Google Sheets. Check sharing, API enablement, and Sheet ID.")
    st.stop()

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


def fetch_feedback(limit=500):
    rows = sheet.get_all_values()
    data = rows[1:] if rows else []
    return data[-limit:] if data else []



# Feedback section
st.markdown("<h2 id='feedback'>💬 Feedback</h2>", unsafe_allow_html=True)
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


