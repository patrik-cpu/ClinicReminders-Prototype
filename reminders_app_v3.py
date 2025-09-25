import pandas as pd
import streamlit as st
import urllib.parse
import re
import json, os
from datetime import timedelta, date

# --------------------------------
# Title
# --------------------------------
title_col, tut_col = st.columns([4,1])
with title_col:
    st.title("ClinicReminders Prototype v3.2 (stable)")
st.markdown("---")

# --------------------------------
# CSS Styling
# --------------------------------
st.markdown(
    """
    <style>
    /* Target only buttons with "WA" label (Chrome/Edge support) */
    div[data-testid="stButton"] button:has(span:contains("WA")) {
        font-size: 10px !important;
        padding: 0px 4px !important;
        height: 18px !important;
        min-height: 18px !important;
        line-height: 1 !important;
    }
    div[data-testid="stButton"] {
        min-height: 0px !important;
        height: auto !important;
    }
    .block-container {
        max-width: 60% !important;
        padding-left: 2rem;
        padding-right: 2rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# --------------------------------
# Defaults
# --------------------------------
DEFAULT_RULES = {
    "vaccine": {"days": 365, "use_qty": False, "visible_text": ""},
    "rabies": {"days": 365, "use_qty": False, "visible_text": ""},
    "dhpp": {"days": 365, "use_qty": False, "visible_text": ""},
    "tricat": {"days": 365, "use_qty": False, "visible_text": ""},
    "dental cat": {"days": 365, "use_qty": False, "visible_text": "Dental exam"},
    "dental dog": {"days": 365, "use_qty": False, "visible_text": "Dental exam"},
    "caniverm": {"days": 90, "use_qty": False, "visible_text": "Caniverm"},
    "bravecto plus": {"days": 60, "use_qty": True, "visible_text": "Bravecto Plus"},
    "bravecto": {"days": 90, "use_qty": True, "visible_text": "Bravecto"},
    "frontline": {"days": 30, "use_qty": True, "visible_text": "Frontline"},
    "revolution": {"days": 30, "use_qty": True, "visible_text": "Revolution"},
    "librela": {"days": 30, "use_qty": False, "visible_text": "Librela"},
    "solensia": {"days": 30, "use_qty": False, "visible_text": "Solensia"},
    "samylin": {"days": 30, "use_qty": True, "visible_text": "Samylin"},
    "cystaid": {"days": 30, "use_qty": False, "visible_text": "Cystaid"},
    "kennel cough": {"days": 30, "use_qty": False, "visible_text": "Kennel Cough"},
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
        ]
    }
}

def detect_pms(df: pd.DataFrame) -> str:
    for pms_name, definition in PMS_DEFINITIONS.items():
        if list(df.columns[:len(definition["columns"])]) == definition["columns"]:
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
    df["IntervalDays"] = pd.NA
    for rule, settings in rules.items():
        mask = df["Plan Item Name"].str.contains(rule, case=False, na=False)
        if settings["use_qty"]:
            df.loc[mask, "IntervalDays"] = df.loc[mask, "Quantity"] * settings["days"]
        else:
            df.loc[mask, "IntervalDays"] = settings["days"]
    return df

# --------------------------------
# Cached CSV processor
# --------------------------------
@st.cache_data
def process_csv(file, rules):
    df = pd.read_csv(file)
    df.columns = [c.strip() for c in df.columns]
    date_col = "Planitem Performed"
    if date_col in df.columns:
        extracted = df[date_col].astype(str).str.extract(r"(\d{2}/[A-Za-z]{3}/\d{4})")[0]
        parsed = pd.to_datetime(extracted, format="%d/%b/%Y", errors="coerce")
        if parsed.notna().sum() == 0:
            parsed = pd.to_datetime(df[date_col], errors="coerce")
        df[date_col] = parsed
    if "Plan Item Quantity" in df.columns:
        df["Quantity"] = pd.to_numeric(df["Plan Item Quantity"], errors="coerce").fillna(1)
    else:
        df["Quantity"] = 1
    df = map_intervals(df, rules)
    df["NextDueDate"] = df[date_col] + pd.to_timedelta(df["IntervalDays"], unit="D")
    df["ChargeDateFmt"] = df[date_col].dt.strftime("%d %b %Y")
    df["DueDateFmt"] = df["NextDueDate"].dt.strftime("%d %b %Y")
    df["_client_lower"] = df["Client Name"].astype(str).str.lower()
    df["_animal_lower"] = df["Patient Name"].astype(str).str.lower()
    df["_item_lower"]   = df["Plan Item Name"].astype(str).str.lower()
    return df

# --------------------------------
# File uploader + summary
# --------------------------------
csv_col, tut_col = st.columns([4,1])
with csv_col:
    files = st.file_uploader("Upload Sales Plan CSV(s)", type="csv", accept_multiple_files=True)
with tut_col:
    st.markdown("### 💡 Tip")
    st.info("Upload and review sales data CSVs here. Check date range and PMS detection.")

datasets, summary_rows, working_df = [], [], None
if files:
    for file in files:
        df = process_csv(file, st.session_state["rules"])
        pms_name = detect_pms(df) or "Undetected"
        from_date, to_date = df["Planitem Performed"].min(), df["Planitem Performed"].max()
        summary_rows.append({
            "CSV name": file.name,
            "PMS": pms_name,
            "From": from_date.strftime("%d %b %Y") if pd.notna(from_date) else "-",
            "To": to_date.strftime("%d %b %Y") if pd.notna(to_date) else "-"
        })
        datasets.append((pms_name, df))
    st.write("### Uploaded Files Summary")
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
    col_widths = [2, 2, 5, 2, 5, 1, 1, 2]
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

        # WA button -> prepare message + inline feedback
        if cols[7].button("WA", key=f"{key_prefix}_wa_{idx}"):
            first_name  = vals['Client Name'].split()[0].strip() if vals['Client Name'] else "there"
            animal_name = vals['Animal Name'].strip() if vals['Animal Name'] else "your pet"
            plan_for_msg = vals["Plan Item"].strip()
            user = st.session_state.get("user_name", "").strip()
            due_date_fmt = format_due_date(vals['Due Date'])
            closing = " Get in touch with us any time for scheduling, and we look forward to hearing from you soon! 🐱🐶"

            if user:
                st.session_state[msg_key] = (
                    f"Hi {first_name}, this is {user} reminding you that "
                    f"{animal_name} is due their {plan_for_msg} {due_date_fmt}.{closing}"
                )
            else:
                st.session_state[msg_key] = (
                    f"Hi {first_name}, this is a reminder letting you know that "
                    f"{animal_name} is due their {plan_for_msg} {due_date_fmt}.{closing}"
                )

            st.success(f"WhatsApp message prepared for {animal_name}. Scroll to the Composer below to send.")
            st.markdown(f"**Preview:** {st.session_state[msg_key]}")

    # Composer (bound to session_state) + tips
    comp_main, comp_tip = st.columns([4,1])
    with comp_main:
        st.write("### WhatsApp Composer")

        # Ensure key exists and bind textarea to session_state
        if msg_key not in st.session_state:
            st.session_state[msg_key] = ""
        st.text_area("Message:", key=msg_key, height=100)

        # Phone input bound to session_state (no Enter required)
        phone_key = f"{key_prefix}_phone"
        st.text_input("Phone (+countrycode)", key=phone_key)

        # Always re-encode latest message & phone on each rerun
        current_message = st.session_state.get(msg_key, "").strip()
        encoded = urllib.parse.quote(current_message) if current_message else ""
        phone_val = st.session_state.get(phone_key, "").strip()
        phone_clean = phone_val.replace(" ", "").replace("-", "").lstrip("+")
        wa_web = f"https://wa.me/{phone_clean}?text={encoded}" if phone_clean else "#"
        wa_app = f"whatsapp://send?phone={phone_clean}&text={encoded}" if phone_clean else "#"

        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f"[WhatsApp Web]({wa_web})", unsafe_allow_html=True)
        with c2:
            st.markdown(f"[WhatsApp Desktop]({wa_app})", unsafe_allow_html=True)

    with comp_tip:
        st.markdown("### 💡 Tip")
        st.info("Review and edit the message, enter the phone **with country code**, then click WhatsApp Web or Desktop to send.")

# --------------------------------
# Main
# --------------------------------
if working_df is not None:
    df = working_df.copy()

    # Your name / clinic
    st.markdown("---")
    name_col, tut_col = st.columns([4,1])
    with name_col:
        st.session_state["user_name"] = st.text_input("Your name / clinic", value=st.session_state["user_name"])
    with tut_col:
        st.markdown("### 💡 Tip")
        st.info("This name will appear in your WhatsApp reminders")

    # Weekly Reminders
    st.markdown("---")
    st.write("### Weekly Reminders")
    st.info("💡 Pick a Start Date to see reminders for the next 7-day window. Click WA to prepare a message.")

    latest_date = df["Planitem Performed"].max()
    default_start = (latest_date + timedelta(days=1)).date() if pd.notna(latest_date) else date.today()
    start_date = st.date_input("Start Date (7-day window)", value=default_start)
    end_date = start_date + timedelta(days=6)

    due = df[(df["NextDueDate"] >= pd.to_datetime(start_date)) & (df["NextDueDate"] <= pd.to_datetime(end_date))]

    grouped = (
        due.groupby(["DueDateFmt","Client Name","Patient Name"], dropna=False)
        .agg({
            "ChargeDateFmt": "max",
            "Plan Item Name": lambda x: format_items(x.unique()),
            "Quantity": "sum",
            "IntervalDays": lambda x: ", ".join(str(int(v)) for v in sorted(set(x.dropna())))
        })
        .reset_index()
        .rename(columns={
            "DueDateFmt": "Due Date",
            "ChargeDateFmt": "Charge Date",
            "Client Name": "Client Name",
            "Patient Name": "Animal Name",
            "Plan Item Name": "Plan Item",
            "IntervalDays": "Days",
            "Quantity": "Qty",
        })
    )
    grouped["Qty"] = pd.to_numeric(grouped["Qty"], errors="coerce").fillna(0).astype(int)
    grouped = grouped[["Due Date","Charge Date","Client Name","Animal Name","Plan Item","Qty","Days"]]

    render_table(grouped, f"{start_date} to {end_date}", "weekly", "weekly_message", st.session_state["rules"])

    # Search
    st.markdown("---")
    st.write("### Search Table")
    st.info("💡 Search by client, animal, or plan item to find upcoming reminders.")
    search_term = st.text_input("Enter text to search (client, animal, or plan item)")
    if search_term:
        q = search_term.lower()
        mask = (
            df["_client_lower"].str.contains(q, regex=False) |
            df["_animal_lower"].str.contains(q, regex=False) |
            df["_item_lower"].str.contains(q, regex=False)
        )
        filtered = df[mask].sort_values("NextDueDate")
        if not filtered.empty:
            filtered = filtered.rename(columns={
                "DueDateFmt":"Due Date","ChargeDateFmt":"Charge Date",
                "Client Name":"Client Name","Patient Name":"Animal Name",
                "Plan Item Name":"Plan Item","Quantity":"Qty"
            })
            filtered["Days"] = pd.to_numeric(filtered["IntervalDays"], errors="coerce").fillna(0).astype(int)
            filtered = filtered[["Due Date","Charge Date","Client Name","Animal Name","Plan Item","Qty","Days"]]
            render_table(filtered, "Search Results", "search", "search_message", st.session_state["rules"])
        else:
            st.info("No matches found.")

    # Rules editor
    st.markdown("---")
    st.write("### Search Terms and Recurrence Interval (editable)")
    st.info(
        "💡 1) See all current Search Terms, set their recurrence interval, and delete if necessary.\n\n"
        "2) Decide if the Quantity column should be considered (e.g. 1× Bravecto = 90 days, 2× Bravecto = 180 days).\n"
        "3) View and edit the Visible Text which will appear in the WhatsApp template message."
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

    for i, (rule, settings) in enumerate(sorted(st.session_state["rules"].items(), key=lambda x: x[0])):
        ver = st.session_state["form_version"]
        cols = st.columns([3,1,1,2,0.6])
        with cols[0]: st.write(rule)
        with cols[1]:
            new_values.setdefault(rule, {})["days"] = st.text_input(
                "days", value=str(settings["days"]), key=f"days_{i}_{ver}", label_visibility="collapsed"
            )
        with cols[2]:
            st.checkbox(
                "Use Qty", value=settings["use_qty"],
                key=f"useqty_{i}_{ver}", on_change=toggle_use_qty, args=(rule, f"useqty_{i}_{ver}",)
            )
        with cols[3]:
            new_values[rule]["visible_text"] = st.text_input(
                "Visible Text", value=settings.get("visible_text",""),
                key=f"vis_{i}_{ver}", label_visibility="collapsed"
            )
        with cols[4]:
            if st.button("❌", key=f"del_{i}_{ver}"):
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
            save_settings()
            st.rerun()

    with colR:
        if st.button("Reset defaults"):
            reset_rules = {
                k: {"days": v["days"], "use_qty": v["use_qty"], "visible_text": v.get("visible_text","")}
                for k, v in DEFAULT_RULES.items()
            }
            st.session_state["rules"] = reset_rules
            st.session_state["exclusions"] = []  # clear exclusions too
            st.session_state["form_version"] += 1  # 🔥 force widgets to refresh with defaults
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

    c1, c2, c3, c4, c5 = st.columns([4,1,1,2,1])
    with c1: new_rule_name = st.text_input("Rule name", key=f"new_rule_name_{st.session_state['new_rule_counter']}")
    with c2: new_rule_days = st.text_input("Days", key=f"new_rule_days_{st.session_state['new_rule_counter']}")
    with c3: new_rule_use_qty = st.checkbox("Use Qty", key=f"new_rule_useqty_{st.session_state['new_rule_counter']}")
    with c4: new_rule_visible = st.text_input("Visible Text (optional)", key=f"new_rule_vis_{st.session_state['new_rule_counter']}")
    with c5:
        if st.button("➕ Add", key=f"add_{st.session_state['new_rule_counter']}"):
            if new_rule_name and str(new_rule_days).isdigit():
                st.session_state["rules"][new_rule_name.strip().lower()] = {
                    "days": int(new_rule_days),
                    "use_qty": bool(new_rule_use_qty),
                    "visible_text": new_rule_visible.strip(),
                }
                save_settings()
                st.session_state["new_rule_counter"] += 1
                st.rerun()
            else:
                st.error("Enter a name and valid integer for days")

    # Exclusions
    st.markdown("---")
    st.write("### Exclusion List (remove reminders containing these terms)")
    st.info("💡 Add terms here to automatically hide reminders that contain them.")
    if st.session_state["exclusions"]:
        for i, term in enumerate(st.session_state["exclusions"]):
            cols = st.columns([6,1])
            cols[0].write(term)
            if cols[1].button("❌", key=f"del_excl_{i}"):
                st.session_state["exclusions"].pop(i)
                save_settings()
                st.rerun()
    else:
        st.info("No exclusions yet.")

    c1, c2 = st.columns([4,1])
    with c1:
        new_excl = st.text_input("Add New Exclusion Term", key=f"new_excl_{st.session_state['new_rule_counter']}")
    with c2:
        if st.button("➕ Add Exclusion", key=f"add_excl_{st.session_state['new_rule_counter']}"):
            if new_excl and new_excl.strip():
                term = new_excl.strip().lower()
                if term not in st.session_state["exclusions"]:
                    st.session_state["exclusions"].append(term)
                    save_settings()
                    st.session_state["new_rule_counter"] += 1
                    st.rerun()
                else:
                    st.info("This exclusion already exists.")
            else:
                st.error("Enter a valid exclusion term")

