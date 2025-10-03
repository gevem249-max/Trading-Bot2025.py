import gspread
from oauth2client.service_account import ServiceAccountCredentials
import streamlit as st
import pandas as pd

# ==============================
# 🔄 AUTO REFRESH
# ==============================
# Refresca cada 300 segundos (5 min). Puedes cambiar el valor a 600 (10 min) o 3600 (1 hora).
st_autorefresh = st.experimental_rerun if hasattr(st, "experimental_rerun") else None
st_autorefresh_interval = 300 * 1000  # en milisegundos
st_autorefresh_counter = st.experimental_memo(lambda: 0)()

st_autorefresh_counter += 1

# ==============================
# 📂 Conexión a Google Sheets
# ==============================
service_account_info = dict(st.secrets["gp"])
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_dict(service_account_info, scope)
client = gspread.authorize(creds)

SPREADSHEET_ID = st.secrets["gp"].get(
    "spreadsheet_id", "1yTd7l9NYvruWPJ4rgNSHQPsqE4o22F0_lvvBWhD1LbM"
)
sheet = client.open_by_key(SPREADSHEET_ID)

# ==============================
# 📊 UI Streamlit
# ==============================
st.title("🚀 Trading Bot 2025 — Dashboard en Vivo")
st.caption("Auto-refresh cada 5 minutos para mostrar nuevas señales 📈")

try:
    ws = sheet.worksheet("signals")
    data = ws.get_all_records()
    df = pd.DataFrame(data)

    if not df.empty:
        st.subheader("📊 Últimas señales registradas")
        st.dataframe(df.tail(20), use_container_width=True, height=400)

        # Contador de señales fuertes vs débiles
        fuertes = df[df["score"] >= 80].shape[0]
        medias = df[(df["score"] >= 60) & (df["score"] < 80)].shape[0]
        bajas = df[(df["score"] >= 40) & (df["score"] < 60)].shape[0]

        st.metric("🔴 Señales <60", bajas)
        st.metric("🟡 Señales 60–79", medias)
        st.metric("🟢 Señales ≥80", fuertes)
    else:
        st.info("⚠️ No hay señales aún en la hoja.")
except Exception as e:
    st.error(f"❌ Error leyendo Google Sheets: {e}")

st.write(f"♻️ Auto-refresh cada 5 minutos. Recarga Nº: {st_autorefresh_counter}")
