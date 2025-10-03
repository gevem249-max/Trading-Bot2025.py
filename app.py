import json
import gspread
import pandas as pd
import streamlit as st
from oauth2client.service_account import ServiceAccountCredentials
import plotly.express as px

# ============================
# CONFIGURACIÓN
# ============================
st.set_page_config(page_title="Trading Bot 2025", layout="wide")

# Leer credenciales desde Streamlit Secrets
service_account_info = dict(st.secrets["google_service_account"])
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]
creds = ServiceAccountCredentials.from_json_keyfile_dict(service_account_info, scope)
client = gspread.authorize(creds)

# Google Sheet
SPREADSHEET_ID = st.secrets["google_service_account"].get(
    "spreadsheet_id", "1yTd7l9NYvruWPJ4rgNSHQPsqE4o22F0_lvvBWhD1LbM"
)
sheet = client.open_by_key(SPREADSHEET_ID)

# ============================
# FUNCIONES DE CARGA
# ============================
def load_df(ws_name):
    try:
        ws = sheet.worksheet(ws_name)
        data = ws.get_all_records()
        df = pd.DataFrame(data)
        return df
    except Exception as e:
        st.warning(f"No se pudo leer {ws_name}: {e}")
        return pd.DataFrame()

df_signals = load_df("signals")
df_pending = load_df("pending")

# ============================
# DASHBOARD
# ============================
st.title("🚀 Trading Bot 2025 – Dashboard en Vivo")
st.markdown("Visualización de señales, preavisos y confirmaciones desde Google Sheets.")

# ----- Gráfico de distribución -----
if not df_signals.empty:
    df_signals["score"] = pd.to_numeric(df_signals["score"], errors="coerce").fillna(0)
    bins = pd.cut(df_signals["score"], bins=[0,40,60,80,100], labels=["<40","40–59","60–79","≥80"])
    counts = bins.value_counts().sort_index()
    fig = px.bar(
        counts,
        x=counts.index,
        y=counts.values,
        labels={"x":"Rango Score","y":"Cantidad"},
        title="Distribución de Señales por Score"
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No hay señales registradas aún en la hoja.")

# ----- Tabla de últimas señales -----
st.subheader("📊 Últimas señales registradas")
if not df_signals.empty:
    st.dataframe(df_signals.tail(10))
else:
    st.write("Sin datos en 'signals'.")

# ----- Tabla de pendientes (PRE/CONF) -----
st.subheader("⏳ Pendientes (Preaviso/Confirmación)")
if not df_pending.empty:
    st.dataframe(df_pending.tail(10))
else:
    st.write("Sin datos en 'pending'.")
