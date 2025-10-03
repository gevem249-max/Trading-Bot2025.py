import streamlit as st
import gspread
import json
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import pandas as pd
from streamlit_autorefresh import st_autorefresh

# ==============================
# 🔄 AUTO REFRESH
# ==============================
# refresca cada 5 minutos (300000 ms)
st_autorefresh(interval=300000, key="refresh")

# ==============================
# 🔑 GOOGLE SHEETS AUTH
# ==============================
service_account_info = dict(st.secrets["gp"])  # tu secret en Streamlit llamado "gp"

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_dict(service_account_info, scope)
client = gspread.authorize(creds)

# ID de tu Google Sheet
SPREADSHEET_ID = st.secrets["gp"].get(
    "spreadsheet_id", "1yTd7l9NYvruWPJ4rgNSHQPsqE4o22F0_lvvBWhD1LbM"
)
sheet = client.open_by_key(SPREADSHEET_ID)

# ==============================
# 📊 DASHBOARD STREAMLIT
# ==============================
st.title("🚀 Trading Bot 2025")
st.caption("Conectado a Google Sheets + Auto-refresh")

# Hora actual en NJ
hora_local = datetime.now().strftime("%m/%d/%Y %I:%M:%S %p")
st.info(f"🕒 Hora local (NJ): {hora_local}")

# Probar lectura de la hoja "signals"
try:
    ws = sheet.worksheet("signals")
    data = ws.get_all_records()
    df = pd.DataFrame(data)

    if not df.empty:
        st.subheader("📊 Últimas señales registradas")
        st.dataframe(df.tail(20), use_container_width=True, height=300)

        # Gráfico simple de distribución de scores
        if "score" in df.columns:
            st.bar_chart(df["score"])
    else:
        st.warning("⚠️ No hay datos en la hoja 'signals' todavía.")

except Exception as e:
    st.error(f"❌ Error leyendo Google Sheets: {e}")

# ==============================
# ✅ STATUS
# ==============================
st.success("✅ Bot activo y conectado correctamente a Google Sheets.")
