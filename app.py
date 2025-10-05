import os, json, pytz, datetime as dt
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import streamlit as st
import matplotlib.pyplot as plt

# =========================
# 🔧 Configuración
# =========================
TZ = pytz.timezone("America/New_York")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
GS_JSON = json.loads(os.getenv("GOOGLE_SHEETS_JSON"))
CREDS = Credentials.from_service_account_info(GS_JSON, scopes=["https://www.googleapis.com/auth/spreadsheets"])
GC = gspread.authorize(CREDS)
SHEET = GC.open_by_key(SPREADSHEET_ID).sheet1

# =========================
# 🧭 Funciones
# =========================
def now_et():
    return dt.datetime.now(TZ)

def load_data():
    try:
        values = SHEET.get_all_records()
        if not values:
            return pd.DataFrame()
        return pd.DataFrame(values)
    except Exception as e:
        st.error(f"⚠️ Error cargando datos: {e}")
        return pd.DataFrame()

# =========================
# 🎨 Interfaz Streamlit
# =========================
st.set_page_config(page_title="Panel Trading Bot", layout="wide")
st.title("📊 Panel de Señales - Trading Bot 2025")

# Estado del bot
st.success("😊 Bot Activo – corriendo en tiempo real")

# Hora local
hora_actual = now_et()
st.write(f"🕒 **Hora local (ET):** {hora_actual.strftime('%Y-%m-%d %H:%M:%S')}")

# Cargar datos
df = load_data()

# =========================
# 📑 Tabs
# =========================
tabs = st.tabs(["✅ Señales", "📈 Resultados Hoy", "📊 Histórico"])

# 1. Señales
with tabs[0]:
    st.subheader("✅ Señales registradas")
    if df.empty:
        st.warning("⚠️ No hay datos.")
    else:
        st.dataframe(df)

# 2. Resultados de hoy
with tabs[1]:
    st.subheader("📈 Resultados de Hoy")
    today = hora_actual.strftime("%Y-%m-%d")
    today_df = df[df["FechaISO"] == today] if not df.empty else pd.DataFrame()
    if today_df.empty:
        st.warning("⚠️ No hay resultados hoy.")
    else:
        st.dataframe(today_df)
        winloss = today_df["Resultado"].value_counts()
        fig, ax = plt.subplots()
        winloss.plot(kind="bar", color=["green","red"], ax=ax)
        ax.set_title("Resultados Win/Loss (Hoy)")
        st.pyplot(fig)

# 3. Histórico
with tabs[2]:
    st.subheader("📊 Histórico Completo")
    if df.empty:
        st.warning("⚠️ No hay histórico todavía.")
    else:
        st.dataframe(df)
