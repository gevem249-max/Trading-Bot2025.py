# ========================================
# 🚀 Streamlit Dashboard Trading Bot
# Visualiza Google Sheets + Estados del mercado
# ========================================

import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta, time as dtime

# ==============================
# CONFIG
# ==============================
SPREADSHEET_ID = "1yTd7l9NYvruWPJ4rgNSHQPsqE4o22F0_lvvBWhD1LbM"
SERVICE_ACCOUNT_FILE = "service_account.json"  # súbelo al repo

# conexión google sheets
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name(SERVICE_ACCOUNT_FILE, scope)
client = gspread.authorize(creds)
sheet = client.open_by_key(SPREADSHEET_ID)

# ==============================
# FUNCIONES HORARIOS
# ==============================
def now_local():
    return datetime.now()

def hora_local_fmt():
    return now_local().strftime("%m/%d/%Y %I:%M:%S %p")

def is_nyse_open(dt=None):
    if dt is None: dt = now_local()
    if dt.weekday() >= 5: return False
    return time(9,30) <= dt.time() <= time(16,0)

def is_mes_open(dt=None):
    if dt is None: dt = now_local()
    wd = dt.weekday()
    if wd == 5: return False
    if wd == 6: return dt.time() >= time(18,0)
    return True

def is_lse_open(dt=None):
    if dt is None: dt = now_local()
    london = dt + timedelta(hours=5)
    return london.weekday() < 5 and time(8,0) <= london.time() <= time(16,30)

# ==============================
# INTERFAZ STREAMLIT
# ==============================
st.set_page_config(page_title="Trading Bot — Visual Dashboard", layout="wide")

st.title("📊 Trading Bot — Visual Dashboard")
st.write("Panel visual de señales y reportes conectado a Google Sheets")

# Estado de los mercados
st.subheader("🌍 Estado del Mercado (hora NJ)")
st.markdown(f"**Hora local NJ:** {hora_local_fmt()}")

col1, col2, col3 = st.columns(3)
col1.metric("NYSE", "ABIERTO" if is_nyse_open() else "CERRADO")
col2.metric("MES (futuros)", "ABIERTO" if is_mes_open() else "CERRADO")
col3.metric("Londres", "ABIERTO" if is_lse_open() else "CERRADO")

st.divider()

# ==============================
# LECTURA DE HOJAS
# ==============================
def read_ws(name):
    try:
        ws = sheet.worksheet(name)
        data = ws.get_all_records()
        return pd.DataFrame(data)
    except:
        return pd.DataFrame()

# pestañas
tab1, tab2, tab3, tab4 = st.tabs(["📈 Signals", "⏳ Pending", "📊 Performance", "📝 Log"])

with tab1:
    df = read_ws("signals")
    st.subheader("Señales registradas")
    st.dataframe(df, use_container_width=True)

with tab2:
    df = read_ws("pending")
    st.subheader("Señales pendientes")
    st.dataframe(df, use_container_width=True)

with tab3:
    df = read_ws("performance")
    st.subheader("Performance del día")
    st.dataframe(df, use_container_width=True)
    if not df.empty:
        st.bar_chart(df[["wins","losses"]])

with tab4:
    df = read_ws("log")
    st.subheader("Log de actividad")
    st.dataframe(df, use_container_width=True)

st.success("✅ Dashboard actualizado en tiempo real con Google Sheets")
