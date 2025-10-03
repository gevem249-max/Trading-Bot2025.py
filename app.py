import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import streamlit as st
import pandas as pd
import pytz
from datetime import datetime, time as dtime
import matplotlib.pyplot as plt

# ==============================
# 🔑 Autenticación Google Sheets
# ==============================
SERVICE_ACCOUNT_JSON = st.secrets["service_account_json"]
service_account_info = json.loads(SERVICE_ACCOUNT_JSON)

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_dict(service_account_info, scope)
client = gspread.authorize(creds)

# ID de tu Google Sheet
SPREADSHEET_ID = "1yTd7l9NYvruWPJ4rgNSHQPsqE4o22F0_lvvBWhD1LbM"
sheet = client.open_by_key(SPREADSHEET_ID)

st.success("✅ Conectado a Google Sheets correctamente")

# ==============================
# 🌍 Funciones de tiempo y mercado
# ==============================
TZ_NJ = pytz.timezone("America/New_York")
TZ_LON = pytz.timezone("Europe/London")

def now_nj():
    return datetime.now(TZ_NJ)

def fmt_time(dt=None):
    if dt is None:
        dt = now_nj()
    return dt.strftime("%m/%d/%Y %I:%M:%S %p")

def is_market_open_nyse():
    now = now_nj()
    if now.weekday() >= 5:  # sábado o domingo
        return False
    return dtime(9,30) <= now.time() <= dtime(16,0)

def is_market_open_mes():
    now = now_nj()
    wd = now.weekday()
    if wd == 5:  # sábado
        return False
    if wd == 6 and now.time() < dtime(18,0):  # domingo antes de 6pm
        return False
    return True

def is_market_open_lse():
    now = datetime.now(TZ_LON)
    if now.weekday() >= 5:
        return False
    return dtime(8,0) <= now.time() <= dtime(16,30)

def badge_open(is_open):
    return "🟢 Abierto" if is_open else "🔴 Cerrado"

# ==============================
# 📊 Cargar datos desde Sheets
# ==============================
def load_sheet(name):
    try:
        ws = sheet.worksheet(name)
        data = ws.get_all_records()
        return pd.DataFrame(data)
    except Exception as e:
        st.error(f"Error cargando {name}: {e}")
        return pd.DataFrame()

# ==============================
# 📈 Dashboard principal
# ==============================
st.title("📊 Trading Bot Dashboard")

# Estado de mercados
col1, col2, col3 = st.columns(3)
with col1:
    st.metric("NYSE", badge_open(is_market_open_nyse()), fmt_time())
with col2:
    st.metric("MES Futuros", badge_open(is_market_open_mes()), fmt_time())
with col3:
    st.metric("LSE Londres", badge_open(is_market_open_lse()), fmt_time())

st.divider()

# Sección de señales
st.header("⚡ Señales registradas")
signals_df = load_sheet("signals")
if not signals_df.empty:
    st.dataframe(signals_df.tail(20), use_container_width=True)

    # gráfico
    fig, ax = plt.subplots()
    signals_df["score"].plot(kind="hist", bins=10, ax=ax, title="Distribución de Scores")
    st.pyplot(fig)
else:
    st.info("No hay señales en este momento.")

# Sección de pendientes
st.header("📬 Señales pendientes (≥80)")
pending_df = load_sheet("pending")
if not pending_df.empty:
    st.dataframe(pending_df.tail(20), use_container_width=True)
else:
    st.info("No hay pendientes.")

# Performance
st.header("📉 Performance")
perf_df = load_sheet("performance")
if not perf_df.empty:
    st.dataframe(perf_df.tail(20), use_container_width=True)
else:
    st.info("No hay performance aún.")

# Logs
st.header("📜 Logs recientes")
log_df = load_sheet("log")
if not log_df.empty:
    st.dataframe(log_df.tail(20), use_container_width=True)
else:
    st.info("No hay logs aún.")
