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
    st.subheader("💉 Top Items")
    if "Plan Item Name" in df.columns:
        top_items = df.groupby("Plan Item Name")["Quantity"].sum().sort_values(ascending=False).head(5)
        st.dataframe(top_items)
    else:
        st.info("No items data available.")

    # ---- Top Spending Clients ----
    st.subheader("💰 Top Spending Clients (Last 30 Days)")
    if "Client Name" in df.columns and "Amount" in df.columns:
        last_month_df = df[df["Planitem Performed"] > last_month]
        top_clients = last_month_df.groupby("Client Name")["Amount"].sum().sort_values(ascending=False).head(5)
        st.dataframe(top_clients)
    else:
        st.info("No revenue data available.")

    # ---- Largest Transaction ----
    st.subheader("📈 Largest Transaction (Last 30 Days)")
    if "Amount" in df.columns:
        largest = df[df["Planitem Performed"] > last_month].sort_values("Amount", ascending=False).head(1)
        st.write(largest[["Client Name","Planitem Performed","Amount","Plan Item Name"]])
    else:
        st.info("No transaction amounts available.")

    # ---- Preventive Care Uptake ----
    st.subheader("🦟 Preventive Care Uptake")
    if "Client Name" in df.columns and "Plan Item Name" in df.columns:
        total_clients = df["Client Name"].nunique()
        if total_clients > 0:
            flea_worm_clients = df[df["Plan Item Name"].str.contains("bravecto|revolution|deworm|frontline", case=False, na=False)]["Client Name"].nunique()
            dental_clients = df[df["Plan Item Name"].str.contains("dental", case=False, na=False)]["Client Name"].nunique()
            food_clients = df[df["Plan Item Name"].str.contains("food", case=False, na=False)]["Client Name"].nunique()

            st.write(f"% clients buying flea & worm control: {flea_worm_clients/total_clients:.1%}")
            st.write(f"% clients having dentals: {dental_clients/total_clients:.1%}")
            st.write(f"% clients buying food: {food_clients/total_clients:.1%}")
        else:
            st.info("No clients found.")
    else:
        st.info("Not enough data for preventive care metrics.")
