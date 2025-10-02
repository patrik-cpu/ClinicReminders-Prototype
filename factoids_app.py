import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

def run_factoids():
    st.markdown("<h2 id='factoids'>📊 Factoids</h2>", unsafe_allow_html=True)
    st.info("📈 Quick insights into your clinic's activity and sales.")

    if "working_df" not in st.session_state:
        st.warning("⚠ Please upload data first in '📂 Upload Data'.")
        return

    df = st.session_state["working_df"].copy()
    today = datetime.today()
    last_month = today - timedelta(days=30)

    # Daily Activity
    st.subheader("📌 Daily Activity")
    daily_counts = df.groupby(df["Planitem Performed"].dt.date).size()
    if not daily_counts.empty:
        st.write("**Max transactions in a day:**", int(daily_counts.max()))
        st.write("**Average transactions per day:**", round(daily_counts.mean(), 2))
    else:
        st.info("No transactions available.")

    # Top Items by Count
    st.subheader("💉 Top 5 Items by Count")
    if "Plan Item Name" in df.columns:
        top_items_count = df.groupby("Plan Item Name")["Quantity"].sum().sort_values(ascending=False).head(5)
        st.dataframe(top_items_count)

    # Top Items by Revenue
    st.subheader("💰 Top 5 Items by Revenue")
    if "Plan Item Name" in df.columns and "Amount" in df.columns:
        top_items_revenue = df.groupby("Plan Item Name")["Amount"].sum().sort_values(ascending=False).head(5)
        st.dataframe(top_items_revenue)

    # Top Spending Clients
    st.subheader("💎 Top 5 Spending Clients (Last 30 Days)")
    if "Client Name" in df.columns and "Amount" in df.columns:
        last_month_df = df[df["Planitem Performed"] > last_month]
        top_clients = last_month_df.groupby("Client Name")["Amount"].sum().sort_values(ascending=False).head(5)
        st.dataframe(top_clients)

    # Largest Transactions
    st.subheader("📈 Top 5 Largest Transactions (Last 30 Days)")
    if "Amount" in df.columns:
        last_month_df = df[df["Planitem Performed"] > last_month]
        largest_tx = last_month_df.sort_values("Amount", ascending=False).head(5)
        st.dataframe(largest_tx[["Client Name","Planitem Performed","Amount","Plan Item Name"]])

    # Preventive Care Uptake
    st.subheader("🦟 Preventive Care Uptake")
    if "Client Name" in df.columns and "Plan Item Name" in df.columns:
        total_clients = df["Client Name"].nunique()
        if total_clients > 0:
            flea_worm = df[df["Plan Item Name"].str.contains("bravecto|revolution|deworm|frontline", case=False, na=False)]["Client Name"].nunique()
            dental = df[df["Plan Item Name"].str.contains("dental", case=False, na=False)]["Client Name"].nunique()
            food = df[df["Plan Item Name"].str.contains("food", case=False, na=False)]["Client Name"].nunique()
            st.write(f"% clients buying flea & worm control: {flea_worm/total_clients:.1%}")
            st.write(f"% clients having dentals: {dental/total_clients:.1%}")
            st.write(f"% clients buying food: {food/total_clients:.1%}")
