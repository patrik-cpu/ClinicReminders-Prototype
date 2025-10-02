import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

def run_factoids():
    st.markdown("<h2 id='factoids'>📊 Factoids</h2>", unsafe_allow_html=True)
    st.info("📈 Quick insights into your clinic's activity and sales.")

    if "working_df" not in st.session_state or st.session_state["working_df"] is None or st.session_state["working_df"].empty:
        st.warning("⚠ Please upload data first in the '📂 Upload Data' section (Reminders).")
        return

    df = st.session_state["working_df"].copy()

    # Make sure core columns exist
    if "Planitem Performed" not in df.columns:
        st.error("Missing 'Planitem Performed' in dataset.")
        return
    if "Quantity" not in df.columns:
        df["Quantity"] = 1
    if "Amount" not in df.columns:
        # Some PMS (e.g., VETport) may not have revenue; keep as zeros so revenue-based factoids still render.
        df["Amount"] = 0

    # Date window
    today = datetime.today()
    last_30 = today - timedelta(days=30)
    df_last30 = df[df["Planitem Performed"] > last_30]

    # --------------------------------
    # Daily Activity
    # --------------------------------
    st.subheader("📌 Daily Activity")
    try:
        daily_counts = df.groupby(df["Planitem Performed"].dt.date).size()
        if not daily_counts.empty:
            st.write("**Max transactions in a day:**", int(daily_counts.max()))
            st.write("**Average transactions per day:**", round(daily_counts.mean(), 2))
        else:
            st.info("No transactions available.")
    except Exception:
        st.info("Could not compute daily activity (date parsing issue).")

    # --------------------------------
    # Top Items by Count
    # --------------------------------
    st.subheader("💉 Top 5 Items by Count")
    if "Plan Item Name" in df.columns:
        top_items_count = (
            df.groupby("Plan Item Name")["Quantity"]
              .sum()
              .sort_values(ascending=False)
              .head(5)
              .rename("Total Quantity")
              .to_frame()
        )
        st.dataframe(top_items_count, use_container_width=True)
    else:
        st.info("No 'Plan Item Name' column found to compute item counts.")

    # --------------------------------
    # Top Items by Revenue
    # --------------------------------
    st.subheader("💰 Top 5 Items by Revenue")
    if "Plan Item Name" in df.columns and "Amount" in df.columns:
        top_items_rev = (
            df.groupby("Plan Item Name")["Amount"]
              .sum()
              .sort_values(ascending=False)
              .head(5)
              .rename("Total Revenue")
              .to_frame()
        )
        st.dataframe(top_items_rev, use_container_width=True)
    else:
        st.info("Revenue not available for items.")

    # --------------------------------
    # Top Spending Clients (Last 30 Days)
    # --------------------------------
    st.subheader("💎 Top 5 Spending Clients (Last 30 Days)")
    if "Client Name" in df.columns and "Amount" in df.columns:
        if not df_last30.empty:
            top_clients = (
                df_last30.groupby("Client Name")["Amount"]
                         .sum()
                         .sort_values(ascending=False)
                         .head(5)
                         .rename("Amount (Last 30d)")
                         .to_frame()
            )
            st.dataframe(top_clients, use_container_width=True)
        else:
            st.info("No transactions in the last 30 days.")
    else:
        st.info("Client or revenue data not available.")

    # --------------------------------
    # Largest Transactions (Last 30 Days)
    # --------------------------------
    st.subheader("📈 Top 5 Largest Transactions (Last 30 Days)")
    if "Amount" in df.columns:
        if not df_last30.empty:
            largest_tx = (
                df_last30.sort_values("Amount", ascending=False)
                         .loc[:, ["Client Name", "Planitem Performed", "Amount", "Plan Item Name"]]
                         .head(5)
            )
            st.dataframe(largest_tx, use_container_width=True)
        else:
            st.info("No transactions in the last 30 days.")
    else:
        st.info("Transaction amounts not available.")

    # --------------------------------
    # Preventive Care Uptake
    # --------------------------------
    st.subheader("🦟 Preventive Care Uptake")
    if "Client Name" in df.columns and "Plan Item Name" in df.columns:
        total_clients = df["Client Name"].nunique()
        if total_clients > 0:
            flea_pattern = "bravecto|revolution|deworm|frontline|milpro|milbem"
            flea_worm_clients = df[df["Plan Item Name"].str.contains(flea_pattern, case=False, na=False)]["Client Name"].nunique()
            dental_clients = df[df["Plan Item Name"].str.contains("dental", case=False, na=False)]["Client Name"].nunique()
            food_clients = df[df["Plan Item Name"].str.contains("food", case=False, na=False)]["Client Name"].nunique()

            st.write(f"% clients buying flea & worm control: {flea_worm_clients/total_clients:.1%}")
            st.write(f"% clients having dentals: {dental_clients/total_clients:.1%}")
            st.write(f"% clients buying food: {food_clients/total_clients:.1%}")
        else:
            st.info("No clients found in dataset.")
    else:
        st.info("Not enough columns to compute preventive care metrics.")
