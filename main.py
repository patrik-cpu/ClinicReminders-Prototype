import streamlit as st
from reminders_app import run_reminders
from factoids_app import run_factoids
from utils import process_file

st.set_page_config(page_title="ClinicReminders", layout="wide")

st.sidebar.title("Navigation")
main_tab = st.sidebar.radio("Choose section:", ["Data Upload", "Reminders", "Factoids"])

# -------------------
# Shared data uploader
# -------------------
if main_tab == "Data Upload":
    st.title("📂 Upload Data")

    file = st.file_uploader("Upload PMS data", type=["csv", "xls", "xlsx"])
    if file:
        df, pms_name = process_file(file, st.session_state.get("rules", {}))
        if df is not None:
            st.session_state["working_df"] = df
            st.session_state["pms_name"] = pms_name
            st.success(f"Uploaded successfully. PMS detected: {pms_name}")
        else:
            st.error("Could not detect PMS type. Please check your file.")

elif main_tab == "Reminders":
    if "working_df" not in st.session_state:
        st.warning("⚠ Please upload data first (see Data Upload tab).")
    else:
        run_reminders()

elif main_tab == "Factoids":
    if "working_df" not in st.session_state:
        st.warning("⚠ Please upload data first (see Data Upload tab).")
    else:
        run_factoids()
