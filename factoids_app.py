import streamlit as st
import pandas as pd
from datetime import datetime
from utils import FLEA_WORM_KEYWORDS, FOOD_KEYWORDS

def run_factoids():
    st.markdown("<h2 id='factoids'>📊 Factoids</h2>", unsafe_allow_html=True)
    st.info("📈 Quick insights into your clinic's activity and sales.")

    if "working_df" not in st.session_state or st.session_state["working_df"] is None or st.session_state["working_df"].empty:
        st.warning("⚠ Please upload data first in the '📂 Upload Data' section (Reminders).")
        return

    df = st.session_state["working_df"].copy()
    if "Planitem Performed" not in df.columns:
        st.error("Missing 'Planitem Performed' in dataset.")
        return
    if "Quantity" not in df.columns: df["Quantity"] = 1
    if "Amount" not in df.columns: df["Amount"] = 0
    if "Client Name" not in df.columns: df["Client Name"] = ""
    if "Patient Name" not in df.columns: df["Patient Name"] = ""

    # Add Month column for dropdown
    df["Month"] = df["Planitem Performed"].dt.to_period("M").dt.to_timestamp()
    months_sorted = sorted(df["Month"].dropna().unique(), reverse=True)
    month_labels = ["All Data"] + [m.strftime("%b %Y") for m in months_sorted]
    selected = st.selectbox("Select period:", month_labels)

    if selected != "All Data":
        selected_month = datetime.strptime(selected, "%b %Y")
        df = df[df["Month"] == selected_month]

    # Restrict width
    st.markdown("<div style='max-width:50%;'>", unsafe_allow_html=True)

    # Daily Activity
    st.subheader("📌 Daily Activity")
    if not df.empty:
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

    # Top Items by Revenue
    st.subheader("💰 Top 20 Items by Revenue")
    top_items = (
        df.groupby("Plan Item Name")
          .agg(TotalRevenue=("Amount", "sum"), TotalCount=("Quantity", "sum"))
          .sort_values("TotalRevenue", ascending=False)
          .head(20)
    )
    top_items["TotalRevenue"] = top_items["TotalRevenue"].apply(lambda x: f"{int(x):,}")
    top_items["TotalCount"] = top_items["TotalCount"].apply(lambda x: f"{int(x):,}")
    st.dataframe(top_items, use_container_width=True)

    # Top Spending Clients
    st.subheader("💎 Top 5 Spending Clients")
    clients_nonblank = df[df["Client Name"].astype(str).str.strip() != ""]
    if not clients_nonblank.empty:
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

    # Largest Transactions
    st.subheader("📈 Top 5 Largest Transactions")
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

    # Preventive Care Uptake (All Data)
    st.subheader("🦟 Preventive Care Uptake (All Data)")
    df_all = st.session_state["working_df"].copy()

    total_patients = df_all["Patient Name"].nunique()

    # Flea & Worm
    flea_pattern = "|".join(FLEA_WORM_KEYWORDS)
    flea_patients = df_all[df_all["Plan Item Name"].str.contains(flea_pattern, case=False, na=False)]["Patient Name"].nunique()

    # Food
    food_pattern = "|".join(FOOD_KEYWORDS)
    food_patients = df_all[df_all["Plan Item Name"].str.contains(food_pattern, case=False, na=False)]["Patient Name"].nunique()

    # Dental transactions > 500
    dental_rows = df_all[df_all["Plan Item Name"].str.contains("dental", case=False, na=False)].copy()
    dental_patients = 0
    if not dental_rows.empty:
        d_sorted = df_all.sort_values(["Client Name", "Planitem Performed"])
        d_sorted["DateOnly"] = pd.to_datetime(d_sorted["Planitem Performed"]).dt.normalize()
        d_sorted["DayDiff"] = d_sorted.groupby("Client Name")["DateOnly"].diff().dt.days.fillna(1)
        d_sorted["Block"] = (d_sorted["DayDiff"] > 1).cumsum()
        tx = (
            d_sorted.groupby(["Client Name", "Block"])
            .agg(
                Amount=("Amount", "sum"),
                StartDate=("DateOnly", "min"),
                EndDate=("DateOnly", "max"),
                Patients=("Patient Name", lambda x: set(x.astype(str)))
            )
            .reset_index()
        )
        # Only include blocks with "dental" AND total amount > 500
        dental_blocks = d_sorted[d_sorted["Plan Item Name"].str.contains("dental", case=False, na=False)][["Client Name","Block"]].drop_duplicates()
        qualifying_blocks = pd.merge(dental_blocks, tx, on=["Client Name","Block"])
        qualifying_blocks = qualifying_blocks[qualifying_blocks["Amount"] > 500]
        patients = set()
        for patlist in qualifying_blocks["Patients"]:
            patients.update(patlist)
        dental_patients = len(patients)

    if total_patients > 0:
        st.write("**Total unique patients:**", f"{int(total_patients):,}")
        st.write("**Unique patients with ≥1 flea/worm purchase:**", f"{int(flea_patients):,}")
        st.write("**% patients buying flea & worm control:**", f"{flea_patients/total_patients:.1%}")
        st.write("**Unique patients with ≥1 food purchase:**", f"{int(food_patients):,}")
        st.write("**% patients buying food:**", f"{food_patients/total_patients:.1%}")
        st.write("**Unique patients with ≥1 dental (transaction >500):**", f"{int(dental_patients):,}")
        st.write("**% patients having dentals (transaction >500):**", f"{dental_patients/total_patients:.1%}")
    else:
        st.info("No patients found in dataset.")

    st.markdown("</div>", unsafe_allow_html=True)
