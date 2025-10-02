import streamlit as st
from reminders_app import run_reminders
from factoids_app import run_factoids

st.set_page_config(page_title="ClinicReminders", layout="wide")

# Sidebar TOC identical to v3.4 with Factoids added
st.sidebar.markdown(
    """
    <div style="font-size:18px; font-weight:bold;">📂 Navigation</div>
    <ul style="list-style-type:none; padding-left:0; line-height:1.8;">
      <li><a href="#tutorial" style="text-decoration:none;">📖 Tutorial</a></li>
      <li><a href="#upload-data" style="text-decoration:none;">📂 Upload Data</a></li>
      <li><a href="#weekly-reminders" style="text-decoration:none;">📅 Weekly Reminders</a></li>
      <li><a href="#search" style="text-decoration:none;">🔍 Search</a></li>
      <li><a href="#search-terms" style="text-decoration:none;">📝 Search Terms</a></li>
      <li><a href="#exclusions" style="text-decoration:none;">🚫 Exclusions</a></li>
      <li><a href="#factoids" style="text-decoration:none;">📊 Factoids</a></li>
      <li><a href="#feedback" style="text-decoration:none;">💬 Feedback</a></li>
    </ul>
    """,
    unsafe_allow_html=True,
)

# Radio to switch between main sections
main_tab = st.sidebar.radio("Main Section", ["Reminders", "Factoids"])

if main_tab == "Reminders":
    run_reminders()
elif main_tab == "Factoids":
    run_factoids()
