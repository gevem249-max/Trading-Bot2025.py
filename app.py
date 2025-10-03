import os
import json
import gspread
import streamlit as st
from oauth2client.service_account import ServiceAccountCredentials

# ==== Credenciales GCP ====
service_account_info = json.loads(os.environ["GCP_SERVICE_ACCOUNT"])
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]
creds = ServiceAccountCredentials.from_json_keyfile_dict(service_account_info, scope)
client = gspread.authorize(creds)

# ==== Google Sheets ====
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
sheet = client.open_by_key(SPREADSHEET_ID).sheet1

# ==== Gmail y API Key ====
GMAIL_PASS = os.environ.get("GMAIL_APP_PASS")
NEWS_API_KEY = os.environ.get("NEWS_API_KEY")

# ==== UI Streamlit ====
st.title("🚀 Trading Bot 2025")
st.success("✅ Conectado a Google Sheets correctamente")

try:
    data = sheet.get_all_records()
    st.write("📊 Primeras filas:", data[:5])
except Exception as e:
    st.error(f"❌ Error leyendo Google Sheets: {e}")
