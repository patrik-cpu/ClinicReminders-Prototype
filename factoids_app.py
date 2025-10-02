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

    # Ensure essential columns
    if "Planitem Performed" not in df.columns:
        st.error("Missing 'Planitem Performed' in dataset.")
        return
    if "Quantity" not in df.columns:
        df["Quantity"] = 1
    if "Amount" not in df.columns:
        df["Amount"] = 0

    df["Month"] = df["Planitem Performed"].dt.to_period("M").dt.to_timestamp()

    # Dropdown filter
    months_sorted = sorted(df["Month"].dropna().unique(), reverse=True)
    month_labels = ["All Data"] + [m.strftime("%b %Y") for m in months_sorted]
    selected = st.selectbox("Select period:", month_labels)

    if selected != "All Data":
        selected_month = datetime.strptime(selected, "%b %Y")
        df = df[df["Month"] == selected_month]

    # Restrict width
    st.markdown("<div style='max-width:50%;'>", unsafe_allow_html=True)

    # --------------------------------
    # Daily Activity
    # --------------------------------
    st.subheader("📌 Daily Activity")
    daily_counts = df.groupby(df["Planitem Performed"].dt.date).size()
    if not daily_counts.empty:
        st.write("**Max transactions in a day:**", f"{int(daily_counts.max()):,}")
        st.write("**Average transactions per day:**", f"{int(round(daily_counts.mean())):,}")
    else:
        st.info("No transactions available.")

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
        st.dataframe(top_items_count.applymap(lambda x: f"{int(x):,}"), use_container_width=True)

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
        st.dataframe(top_items_rev.applymap(lambda x: f"{int(x):,}"), use_container_width=True)

    # --------------------------------
    # Top Spending Clients
    # --------------------------------
    st.subheader("💎 Top 5 Spending Clients")
    if "Client Name" in df.columns and "Amount" in df.columns:
        top_clients = (
            df.groupby("Client Name")["Amount"]
              .sum()
              .sort_values(ascending=False)
              .head(5)
              .rename("Total Spend")
              .to_frame()
        )
        st.dataframe(top_clients.applymap(lambda x: f"{int(x):,}"), use_container_width=True)

    # --------------------------------
    # Largest Transactions
    # --------------------------------
    st.subheader("📈 Top 5 Largest Transactions")
    if "Client Name" in df.columns and "Amount" in df.columns:
        # Sort by client + date
        df_sorted = df.sort_values(["Client Name", "Planitem Performed"])

        # Detect contiguous days
        df_sorted["DateOnly"] = df_sorted["Planitem Performed"].dt.date
        df_sorted["DayDiff"] = df_sorted.groupby("Client Name")["DateOnly"].diff().dt.days.fillna(1)
        df_sorted["Block"] = (df_sorted["DayDiff"] > 1).cumsum()

        # Group by client + block
        tx_groups = (
            df_sorted.groupby(["Client Name", "Block"])
            .agg(
                Amount=("Amount", "sum"),
                StartDate=("DateOnly", "min"),
                EndDate=("DateOnly", "max"),
            )
            .reset_index()
        )

        tx_groups["DateRange"] = tx_groups.apply(
            lambda r: str(r["StartDate"]) if r["StartDate"] == r["EndDate"] else f"{r['StartDate']} → {r['EndDate']}",
            axis=1,
        )

        largest_tx = tx_groups.sort_values("Amount", ascending=False).head(5)
        largest_tx = largest_tx[["Client Name", "DateRange", "Amount"]]
        largest_tx["Amount"] = largest_tx["Amount"].apply(lambda x: f"{int(x):,}")

        st.dataframe(largest_tx, use_container_width=True)

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

    st.markdown("</div>", unsafe_allow_html=True)
