import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from utils import process_file

def run_factoids():
    st.title("📊 Factoids Dashboard")

    file = st.file_uploader("Upload PMS data", type=["csv", "xls", "xlsx"])
    if not file:
        st.info("Upload a file to see factoids.")
        return

    df, pms_name = process_file(file, {})
    if df is None or df.empty:
        st.error("Could not detect PMS or data is empty.")
        return

    st.success(f"PMS detected: {pms_name}")

    today = datetime.today()
    last_month = today - timedelta(days=30)

    # ---- Daily Transactions ----
    st.subheader("📌 Daily Activity")
    daily_counts = df.groupby(df["Planitem Performed"].dt.date).size()
    st.write("**Max transactions in a day:**", daily_counts.max())
    st.write("**Average transactions per day:**", round(daily_counts.mean(), 2))

    # ---- Top Items ----
    st.subheader("💉 Top Items")
    top_items = df.groupby("Plan Item Name")["Quantity"].sum().sort_values(ascending=False).head(5)
    st.dataframe(top_items)

    # ---- Top Spending Clients ----
    st.subheader("💰 Top Spending Clients (Last 30 Days)")
    if "Client Name" in df.columns and "Amount" in df.columns:
        last_month_df = df[df["Planitem Performed"] > last_month]
        top_clients = last_month_df.groupby("Client Name")["Amount"].sum().sort_values(ascending=False).head(5)
        st.dataframe(top_clients)

    # ---- Largest Transaction ----
    st.subheader("📈 Largest Transaction (Last 30 Days)")
    if "Amount" in df.columns:
        largest = df[df["Planitem Performed"] > last_month].sort_values("Amount", ascending=False).head(1)
        st.write(largest[["Client Name","Planitem Performed","Amount","Plan Item Name"]])

    # ---- Preventive Care Uptake ----
    st.subheader("🦟 Preventive Care Uptake")
    total_clients = df["Client Name"].nunique()
    flea_worm_clients = df[df["Plan Item Name"].str.contains("bravecto|revolution|deworm|frontline", case=False, na=False)]["Client Name"].nunique()
    dental_clients = df[df["Plan Item Name"].str.contains("dental", case=False, na=False)]["Client Name"].nunique()
    food_clients = df[df["Plan Item Name"].str.contains("food", case=False, na=False)]["Client Name"].nunique()

    st.write(f"% clients buying flea & worm control: {flea_worm_clients/total_clients:.1%}")
    st.write(f"% clients having dentals: {dental_clients/total_clients:.1%}")
    st.write(f"% clients buying food: {food_clients/total_clients:.1%}")
