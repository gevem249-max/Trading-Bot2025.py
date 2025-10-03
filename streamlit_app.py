import streamlit as st
import pandas as pd
import numpy as np
import pytz
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

# ==================================
# 📌 CONFIGURACIÓN
# ==================================
SPREADSHEET_ID = "1yTd7l9NYvruWPJ4rgNSHQPsqE4o22F0_lvvBWhD1LbM"

# Cargar credenciales desde Secrets
creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"])
client = gspread.authorize(creds)
sheet = client.open_by_key(SPREADSHEET_ID)

# ==================================
# 📌 FUNCIONES DE UTILIDAD
# ==================================
def hora_local_nj():
    tz = pytz.timezone("America/New_York")
    return datetime.now(tz).strftime("%m/%d/%Y %I:%M:%S %p")

def estado_mercados():
    nyse = "ABIERTO" if 9 <= datetime.now().hour < 16 else "CERRADO"
    mes = "ABIERTO"  # ejemplo: futuros 24h
    londres = "ABIERTO" if 3 <= datetime.now().hour < 11 else "CERRADO"
    return nyse, mes, londres

# ==================================
# 📌 INTERFAZ STREAMLIT
# ==================================
st.set_page_config(page_title="Trading Bot Dashboard", page_icon="🤖")

st.title("🤖 Trading Bot — Dashboard")
st.write("Panel visual de señales y reportes conectados a Google Sheets.")

# Estado actual
nyse, mes, londres = estado_mercados()
st.markdown(f"""
### ⏰ Hora local NJ: {hora_local_nj()}

- **NYSE:** {nyse}  
- **MES (futuros):** {mes}  
- **Londres:** {londres}  
""")

# ==================================
# 📌 LECTURA DE HOJA DE GOOGLE SHEETS
# ==================================
try:
    ws = sheet.worksheet("log")
    data = ws.get_all_records()
    df = pd.DataFrame(data)
    if not df.empty:
        st.subheader("📊 Últimos eventos registrados")
        st.dataframe(df.tail(10))
    else:
        st.info("No hay datos aún en la hoja 'log'.")
except Exception as e:
    st.error(f"Error al leer Google Sheets: {e}")

st.success("✅ Bot en Streamlit listo y conectado")
