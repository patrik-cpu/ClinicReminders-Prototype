import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

def run_factoids():
    st.title("📊 Factoids Dashboard")

    if "working_df" not in st.session_state:
        st.warning("⚠ Please upload data first (see Data Upload tab).")
        return

    df = st.session_state["working_df"].copy()

    today = datetime.today()
    last_month = today - timedelta(days=30)

    # ---- Daily Transactions ----
    st.subheader("📌 Daily Activity")
    daily_counts = df.groupby(df["Planitem Performed"].dt.date).size()
    if not daily_counts.empty:
        st.write("**Max transactions in a day:**", daily_counts.max())
        st.write("**Average transactions per day:**", round(daily_counts.mean(), 2))
    else:
        st.info("No transactions found.")

    # ---- Top Items ----
    st.subheader("💉 Top 5 Items by Count")
    top_items_count = df.groupby("Plan Item Name")["Quantity"].sum().sort_values(ascending=False).head(5)
    st.dataframe(top_items_count)

    st.subheader("💰 Top 5 Items by Revenue")
    if "Amount" in df.columns:
        top_items_rev = df.groupby("Plan Item Name")["Amount"].sum().sort_values(ascending=False).head(5)
        st.dataframe(top_items_rev)

    # ---- Top Spending Clients ----
    st.subheader("💎 Top 5 Spending Clients (Last 30 Days)")
    if "Client Name" in df.columns and "Amount" in df.columns:
        last_month_df = df[df["Planitem Performed"] > last_month]
        top_clients = last_month_df.groupby("Client Name")["Amount"].sum().sort_values(ascending=False).head(5)
        st.dataframe(top_clients)

    # ---- Largest Transactions ----
    st.subheader("📈 Top 5 Largest Transactions (Last 30 Days)")
    if "Amount" in df.columns:
        last_month_df = df[df["Planitem Performed"] > last_month]
        largest_tx = last_month_df.sort_values("Amount", ascending=False).head(5)
        st.dataframe(largest_tx[["Client Name","Planitem Performed","Amount","Plan Item Name"]])
