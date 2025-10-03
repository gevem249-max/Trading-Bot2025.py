import gspread
from oauth2client.service_account import ServiceAccountCredentials
import streamlit as st

# Leer secrets desde Streamlit
service_account_info = dict(st.secrets["gp"])

# Autenticación con Google Sheets
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]
creds = ServiceAccountCredentials.from_json_keyfile_dict(service_account_info, scope)
client = gspread.authorize(creds)

# Abrir hoja
SPREADSHEET_ID = st.secrets["gp"].get("spreadsheet_id", "1yTd7l9NYvruWPJ4rgNSHQPsqE4o22F0_lvvBWhD1LbM")
sheet = client.open_by_key(SPREADSHEET_ID)

# UI
st.title("🚀 Trading Bot 2025")
st.success("✅ Conectado a Google Sheets correctamente")

# Probar lectura
try:
    ws = sheet.sheet1
    data = ws.get_all_records()
    st.write("📊 Primeras filas:", data[:5])
except Exception as e:
    st.error(f"❌ Error leyendo Google Sheets: {e}")
