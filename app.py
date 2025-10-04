import streamlit as st
import os, json
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd

st.set_page_config(page_title="📊 Panel de Señales - Trading Bot 2025", layout="wide")
st.title("📊 Panel de Señales - Trading Bot 2025")

# --------------------------------------
# Conectar a Google Sheets
# --------------------------------------
def conectar_sheets():
    google_json = os.getenv("GOOGLE_SHEETS_JSON")
    creds_info = json.loads(google_json)   # ahora sí debe decodificar bien
    scope = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(creds_info, scopes=scope)
    cliente = gspread.authorize(creds)
    sheet = cliente.open("SeñalesBot").sheet1
    return sheet

# --------------------------------------
# Cargar historial desde Sheets
# --------------------------------------
def cargar_historial():
    sheet = conectar_sheets()
    data = sheet.get_all_records()
    return pd.DataFrame(data)

# --------------------------------------
# Mostrar historial
# --------------------------------------
try:
    df = cargar_historial()
    if df.empty:
        st.info("✅ Conexión correcta, pero tu hoja de Google Sheets está vacía.")
    else:
        st.success("✅ Conexión correcta a Google Sheets.")
        st.subheader("📜 Historial de Señales")
        st.dataframe(df)
except Exception as e:
    st.error(f"❌ Error al conectar con Google Sheets: {e}")
