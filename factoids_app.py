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
    if "Client Name" not in df.columns:
        df["Client Name"] = ""
    if "Patient Name" not in df.columns:
        df["Patient Name"] = ""

    # Add Month column for dropdown
    df["Month"] = df["Planitem Performed"].dt.to_period("M").dt.to_timestamp()

    # Dropdown filter
    months_sorted = sorted(df["Month"].dropna().unique(), reverse=True)
    month_labels = ["All Data"] + [m.strftime("%b %Y") for m in months_sorted]
    selected = st.selectbox("Select period:", month_labels)

    if selected != "All Data":
        selected_month = datetime.strptime(selected, "%b %Y")
        df = df[df["Month"] == selected_month]

    # Restrict width to 50%
    st.markdown("<div style='max-width:50%;'>", unsafe_allow_html=True)

    # --------------------------------
    # Daily Activity
    # --------------------------------
    st.subheader("📌 Daily Activity")

    if not df.empty:
        df_sorted = df.sort_values(["Client Name", "Planitem Performed"])
        df_sorted["DateOnly"] = pd.to_datetime(df_sorted["Planitem Performed"]).dt.normalize()
        df_sorted["DayDiff"] = df_sorted.groupby("Client Name")["DateOnly"].diff().dt.days.fillna(1)
        df_sorted["Block"] = (df_sorted["DayDiff"] > 1).cumsum()

        # Transactions = per client, contiguous days grouped
        tx_groups = (
            df_sorted.groupby(["Client Name", "Block"])
            .agg(
                Amount=("Amount", "sum"),
                StartDate=("DateOnly", "min"),
                EndDate=("DateOnly", "max"),
                Patients=("Patient Name", lambda x: set(x)),
            )
            .reset_index()
        )

        # Daily stats
        daily = df.groupby(df["Planitem Performed"].dt.date).agg(
            Transactions=("Client Name", "count"),
            Clients=("Client Name", pd.Series.nunique),
            Patients=("Patient Name", pd.Series.nunique),
        )

        if not daily.empty:
            st.write("**Max transactions in a day:**", f"{int(daily['Transactions'].max()):,}")
            st.write("**Average transactions per day:**", f"{int(round(daily['Transactions'].mean())):,}")
            st.write("**Max unique clients in a day:**", f"{int(daily['Clients'].max()):,}")
            st.write("**Average clients per day:**", f"{int(round(daily['Clients'].mean())):,}")
            st.write("**Max unique patients in a day:**", f"{int(daily['Patients'].max()):,}")
            st.write("**Average patients per day:**", f"{int(round(daily['Patients'].mean())):,}")
        else:
            st.info("No daily activity data available.")
    else:
        st.info("No transactions available.")

    # --------------------------------
    # Top Items by Revenue (Top 20, with counts)
    # --------------------------------
    st.subheader("💰 Top 20 Items by Revenue")
    if "Plan Item Name" in df.columns and "Amount" in df.columns:
        top_items = (
            df.groupby("Plan Item Name")
              .agg(
                  TotalRevenue=("Amount", "sum"),
                  TotalCount=("Quantity", "sum")
              )
              .sort_values("TotalRevenue", ascending=False)
              .head(20)
        )
        top_items["TotalRevenue"] = top_items["TotalRevenue"].apply(lambda x: f"{int(x):,}")
        top_items["TotalCount"] = top_items["TotalCount"].apply(lambda x: f"{int(x):,}")
        st.dataframe(top_items, use_container_width=True)

    # --------------------------------
    # Top Spending Clients (exclude blanks)
    # --------------------------------
    st.subheader("💎 Top 5 Spending Clients")
    clients_nonblank = df[df["Client Name"].astype(str).str.strip() != ""]
    if not clients_nonblank.empty and "Amount" in clients_nonblank.columns:
        top_clients = (
            clients_nonblank.groupby("Client Name")["Amount"]
                            .sum()
                            .sort_values(ascending=False)
                            .head(5)
                            .rename("Total Spend")
                            .to_frame()
        )
        top_clients["Total Spend"] = top_clients["Total Spend"].apply(lambda x: f"{int(x):,}")
        st.dataframe(top_clients, use_container_width=True)
    else:
        st.info("No valid client spend data available.")

    # --------------------------------
    # Largest Transactions (include patients, formatted dates)
    # --------------------------------
    st.subheader("📈 Top 5 Largest Transactions")
    if {"Client Name", "Amount", "Patient Name"}.issubset(df.columns):
        df_sorted = df.sort_values(["Client Name", "Planitem Performed"])
        df_sorted["DateOnly"] = pd.to_datetime(df_sorted["Planitem Performed"]).dt.normalize()
        df_sorted["DayDiff"] = df_sorted.groupby("Client Name")["DateOnly"].diff().dt.days.fillna(1)
        df_sorted["Block"] = (df_sorted["DayDiff"] > 1).cumsum()

        tx_groups = (
            df_sorted.groupby(["Client Name", "Block"])
            .agg(
                Amount=("Amount", "sum"),
                StartDate=("DateOnly", "min"),
                EndDate=("DateOnly", "max"),
                Patients=("Patient Name", lambda x: ", ".join(sorted(set(x.astype(str))))),
            )
            .reset_index()
        )

        tx_groups["DateRange"] = tx_groups.apply(
            lambda r: r["StartDate"].strftime("%d %b %Y") if r["StartDate"] == r["EndDate"]
            else f"{r['StartDate'].strftime('%d %b %Y')} → {r['EndDate'].strftime('%d %b %Y')}",
            axis=1,
        )

        largest_tx = tx_groups.sort_values("Amount", ascending=False).head(5)
        largest_tx = largest_tx[["Client Name", "DateRange", "Patients", "Amount"]]
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
