import pandas as pd
import unicodedata
import streamlit as st
import re, json, os
import streamlit.components.v1 as components
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import date, datetime, timedelta
from utils import (
    DEFAULT_RULES, SETTINGS_FILE, save_settings, load_settings,
    PMS_DEFINITIONS, detect_pms, process_file,
    ensure_reminder_columns, simplify_vaccine_text,
    format_items, format_due_date, normalize_display_case
)

@st.cache_data(ttl=30)
def fetch_feedback_cached(limit=500):
    return fetch_feedback(limit)

def run_reminders():
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
        .block-container h1, .block-container h2, .block-container h3 {
            margin-top: 0.2rem;
        }
        div[data-testid="stButton"] {
            min-height: 0px !important;
            height: auto !important;
        }
        .block-container {
            max-width: 100% !important;
            padding-left: 2rem;
            padding-right: 2rem;
        }
        h2[id] {
            scroll-margin-top: 80px;
        }
        .anchor-offset {
            position: relative;
            top: -100px;
            height: 0;
        }
        </style>
        ''',
        unsafe_allow_html=True,
    )

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
    st.markdown("<div id='upload-data' class='anchor-offset'></div>", unsafe_allow_html=True)
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

        # Save uploaded files to session
        st.session_state["datasets"] = datasets
        st.session_state["file_summaries"] = summary_rows

    # --- Reuse session state if no new uploads ---
    datasets = st.session_state.get("datasets", [])
    summary_rows = st.session_state.get("file_summaries", [])

    if summary_rows:
        st.dataframe(pd.DataFrame(summary_rows), use_container_width=True)

        # Clear all uploads button
        if st.button("❌ Clear uploaded files"):
            for key in ["datasets", "file_summaries", "working_df"]:
                if key in st.session_state:
                    del st.session_state[key]
            st.rerun()

    if datasets:
        all_pms = {p for p, _ in datasets}
        if len(all_pms) == 1 and "Undetected" not in all_pms:
            working_df = pd.concat([df for _, df in datasets], ignore_index=True)
            st.success(f"All files detected as {list(all_pms)[0]} — merging datasets.")
            st.session_state["working_df"] = working_df
        else:
            st.warning("PMS mismatch or undetected files. Reminders cannot be generated.")

    if "working_df" not in st.session_state:
        return
    df = st.session_state["working_df"].copy()

    # --------------------------------
    # The rest of your old v3.4 code continues here
    # Weekly Reminders (with WA buttons, composer, etc.)
    # Search
    # Rules editor
    # Exclusions
    # Feedback
    # (unchanged — paste from your old working version)
    # --------------------------------
