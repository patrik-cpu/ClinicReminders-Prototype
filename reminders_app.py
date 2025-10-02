import streamlit as st
import pandas as pd
from datetime import date, timedelta
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json
import streamlit.components.v1 as components

# Import shared utils
from utils import (
    PMS_DEFINITIONS, DEFAULT_RULES,
    save_settings, load_settings,
    detect_pms, parse_dates, process_file,
    ensure_reminder_columns,
    simplify_vaccine_text, get_visible_plan_item,
    format_items, format_due_date,
    normalize_display_case, map_intervals
)

def run_reminders():
    # -------------------------------
    # Title
    # -------------------------------
    st.title("ClinicReminders Prototype v3.5 (dev)")
    st.markdown("---")

    # Load session state
    if "rules" not in st.session_state:
        load_settings()
    st.session_state.setdefault("weekly_message", "")
    st.session_state.setdefault("search_message", "")
    st.session_state.setdefault("new_rule_counter", 0)
    st.session_state.setdefault("form_version", 0)

    # -------------------------------
    # Upload Data
    # -------------------------------
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

    # -------------------------------
    # Weekly Reminders
    # -------------------------------
    if working_df is not None:
        df = working_df.copy()

        st.markdown("---")
        st.markdown("## 📅 Weekly Reminders")
        st.info("Pick a Start Date to see reminders for the next 7-day window.")

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
                "Plan Item": g["MatchedItems"].apply(lambda lists: simplify_vaccine_text(format_items(sorted(set(i for sub in lists for i in (sub if isinstance(sub, list) else [sub]) if str(i).strip()))))),
                "Qty": g["Quantity"].sum(min_count=1),
                "Days": g["IntervalDays"].apply(lambda x: int(pd.to_numeric(x, errors="coerce").dropna().min()) if pd.to_numeric(x, errors="coerce").notna().any() else "")
            })
            .reset_index()
            .rename(columns={"DueDateFmt": "Due Date"})
        )[["Due Date","Charge Date","Client Name","Animal Name","Plan Item","Qty","Days"]]

        grouped["Qty"] = pd.to_numeric(grouped["Qty"], errors="coerce").fillna(0).astype(int)
        st.dataframe(grouped, use_container_width=True)

    # -------------------------------
    # Feedback Section
    # -------------------------------
    st.markdown("---")
    st.markdown("## 💬 Feedback")
    st.info("Found a problem? Let us know.")

    feedback_text = st.text_area("Describe the issue or suggestion", key="feedback_text", height=120)
    if st.button("Send Feedback"):
        if feedback_text.strip():
            st.success("Thanks! Your feedback has been recorded.")
        else:
            st.error("Please enter a message before sending.")
