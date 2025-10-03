import gspread
from oauth2client.service_account import ServiceAccountCredentials
import streamlit as st
import pandas as pd

# Leer service account desde secrets
service_account_info = dict(st.secrets["gp"])

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]
creds = ServiceAccountCredentials.from_json_keyfile_dict(service_account_info, scope)
client = gspread.authorize(creds)

# Usar spreadsheet_id del secret
SPREADSHEET_ID = st.secrets["gp"]["spreadsheet_id"]
sheet = client.open_by_key(SPREADSHEET_ID)

st.title("🚀 Trading Bot 2025 conectado")
st.success("✅ Conexión con Google Sheets lista")

# Mostrar contenido
try:
    ws = sheet.sheet1
    data = ws.get_all_records()
    st.dataframe(pd.DataFrame(data).head())
except Exception as e:
    st.error(f"❌ Error leyendo hoja: {e}")
