import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime

# ==========================
# 🔑 Cargar credenciales desde secrets
# ==========================
SERVICE_ACCOUNT_JSON = st.secrets["google_service_account"]["json"]
service_account_info = json.loads(SERVICE_ACCOUNT_JSON)

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

creds = ServiceAccountCredentials.from_json_keyfile_dict(service_account_info, scope)
client = gspread.authorize(creds)

# ==========================
# 📊 Conectar al Google Sheet
# ==========================
SPREADSHEET_ID = "1yTd7l9NYvruWPJ4rgNSHQPsqE4o22F0_lvvBWhD1LbM"
sheet = client.open_by_key(SPREADSHEET_ID)

st.title("📈 Trading Bot Dashboard")
st.success("✅ Conectado a Google Sheets correctamente")

# ==========================
# 📄 Leer datos
# ==========================
def get_df(sheet_name):
    try:
        ws = sheet.worksheet(sheet_name)
        data = ws.get_all_records()
        return pd.DataFrame(data)
    except Exception as e:
        st.warning(f"No se pudo leer la hoja {sheet_name}: {e}")
        return pd.DataFrame()

signals_df = get_df("signals")
pending_df = get_df("pending")
perf_df = get_df("performance")
log_df = get_df("log")

# ==========================
# 📊 Mostrar gráficos
# ==========================
st.header("📊 Señales")
if not signals_df.empty:
    st.dataframe(signals_df.tail(20))
    fig, ax = plt.subplots()
    signals_df["score"].plot(kind="hist", bins=10, ax=ax)
    ax.set_title("Distribución de Scores")
    st.pyplot(fig)
else:
    st.info("No hay datos en 'signals'.")

st.header("⏳ Pendientes")
st.dataframe(pending_df.tail(20) if not pending_df.empty else pd.DataFrame())

st.header("📉 Performance")
if not perf_df.empty:
    st.dataframe(perf_df.tail(20))
    fig, ax = plt.subplots()
    perf_df.groupby("date")["profit"].sum().plot(kind="bar", ax=ax)
    ax.set_title("Profit diario")
    st.pyplot(fig)
else:
    st.info("No hay datos en 'performance'.")

st.header("📜 Log de eventos")
st.dataframe(log_df.tail(30) if not log_df.empty else pd.DataFrame())
