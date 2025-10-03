# ========================================
# 📊 Trading Bot Dashboard (Streamlit)
# ========================================

import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
from datetime import datetime, time as dtime, timedelta

# ==============================
# ⚙️ CONFIGURACIÓN GOOGLE SHEETS
# ==============================
SERVICE_ACCOUNT_FILE = "service_account.json"   # ya lo tienes en tu repo
SPREADSHEET_ID = "1yTd7l9NYvruWPJ4rgNSHQPsqE4o22F0_lvvBWhD1LbM"

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

creds = ServiceAccountCredentials.from_json_keyfile_name(SERVICE_ACCOUNT_FILE, scope)
client = gspread.authorize(creds)
sheet = client.open_by_key(SPREADSHEET_ID)

# ==============================
# 🕒 UTILIDADES HORARIOS
# ==============================
def now_et():
    return datetime.now()

def is_nyse_open(dt=None):
    if dt is None: dt = now_et()
    if dt.weekday() >= 5: return False
    return dtime(9,30) <= dt.time() <= dtime(16,0)

def is_mes_open(dt=None):
    if dt is None: dt = now_et()
    wd = dt.weekday()
    if wd == 5: return False
    if wd == 6: return dt.time() >= dtime(18,0)
    return True

def is_lse_open(dt=None):
    if dt is None: dt = now_et()
    london = dt + timedelta(hours=5)  # NJ vs Londres
    return london.weekday() < 5 and dtime(8,0) <= london.time() <= dtime(16,30)

# ==============================
# 📊 DASHBOARD STREAMLIT
# ==============================
st.set_page_config(page_title="Trading Bot Dashboard", layout="centered")

st.title("🤖 Trading Bot — Visual Dashboard")
st.write("Panel visual de señales y reportes conectado a Google Sheets")

# Estado de los mercados
st.subheader("🌍 Estado de los Mercados")
st.markdown(f"""
- **Hora local NJ:** {now_et().strftime("%m/%d/%Y %I:%M:%S %p")}
- **NYSE:** {"🟢 ABIERTO" if is_nyse_open() else "🔴 CERRADO"}
- **MES (futuros):** {"🟢 ABIERTO" if is_mes_open() else "🔴 CERRADO"}
- **Londres:** {"🟢 ABIERTO" if is_lse_open() else "🔴 CERRADO"}
""")

# Leer señales
st.subheader("📈 Últimas señales")
try:
    ws = sheet.worksheet("signals")
    data = ws.get_all_records()
    df = pd.DataFrame(data)
    if not df.empty:
        st.dataframe(df.tail(10))  # mostrar las últimas 10 señales
    else:
        st.info("No hay señales registradas todavía.")
except Exception as e:
    st.error(f"No se pudieron leer las señales: {e}")

# Log de eventos
st.subheader("📝 Log de eventos")
try:
    ws_log = sheet.worksheet("log")
    data_log = ws_log.get_all_records()
    df_log = pd.DataFrame(data_log)
    if not df_log.empty:
        st.dataframe(df_log.tail(15))
    else:
        st.info("No hay eventos registrados todavía.")
except Exception as e:
    st.error(f"No se pudo leer el log: {e}")
