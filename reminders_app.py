import streamlit as st
import pandas as pd
from datetime import date, timedelta
from utils import (
    save_settings, load_settings,
    ensure_reminder_columns, simplify_vaccine_text,
    format_items, format_due_date
)

def run_reminders():
    st.title("📅 Reminders")

    if "rules" not in st.session_state:
        load_settings()

    if "working_df" not in st.session_state:
        st.warning("⚠ Please upload data first (see Data Upload tab).")
        return

    df = st.session_state["working_df"].copy()
    df = ensure_reminder_columns(df, st.session_state["rules"])

    # Pick date range
    st.markdown("### Weekly Reminders")
    latest_date = df["Planitem Performed"].max()
    default_start = (latest_date + timedelta(days=1)).date() if pd.notna(latest_date) else date.today()
    start_date = st.date_input("Start Date (7-day window)", value=default_start)
    end_date = start_date + timedelta(days=6)

    due = df[(df["NextDueDate"] >= pd.to_datetime(start_date)) & 
             (df["NextDueDate"] <= pd.to_datetime(end_date))]

    if due.empty:
        st.info("No reminders found in this window.")
        return

    # Group
    g = due.groupby(["DueDateFmt", "Client Name"], dropna=False)
    grouped = (
        pd.DataFrame({
            "Charge Date": g["ChargeDateFmt"].max(),
            "Animal Name": g["Patient Name"].apply(lambda s: format_items(sorted(set(s.dropna())))),
            "Plan Item": g["MatchedItems"].apply(lambda lists: simplify_vaccine_text(format_items(sorted(set(
                i for sub in lists for i in (sub if isinstance(sub, list) else [sub]) if str(i).strip()
            ))))),
            "Qty": g["Quantity"].sum(min_count=1),
            "Days": g["IntervalDays"].apply(lambda x: int(pd.to_numeric(x, errors="coerce").dropna().min()) if pd.to_numeric(x, errors="coerce").notna().any() else "")
        })
        .reset_index()
        .rename(columns={"DueDateFmt": "Due Date"})
    )[["Due Date","Charge Date","Client Name","Animal Name","Plan Item","Qty","Days"]]

    grouped["Qty"] = pd.to_numeric(grouped["Qty"], errors="coerce").fillna(0).astype(int)
    st.dataframe(grouped, use_container_width=True)
