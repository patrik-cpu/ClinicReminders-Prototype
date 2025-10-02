import streamlit as st
from reminders_app import run_reminders
from factoids_app import run_factoids

st.set_page_config(page_title="ClinicReminders", layout="wide")

# Sidebar Navigation
st.sidebar.title("Navigation")
main_tab = st.sidebar.radio("Choose section:", ["Reminders", "Factoids"])

if main_tab == "Reminders":
    run_reminders()
elif main_tab == "Factoids":
    run_factoids()
