# app.py — Panel de Señales Trading Bot 2025 (sin gráficos para estabilidad)

import os, json, pytz, datetime as dt
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import streamlit as st

# =========================
# 🔧 Configuración
# =========================
TZ = pytz.timezone("America/New_York")

SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
GS_JSON = json.loads(os.getenv("GOOGLE_SHEETS_JSON"))
CREDS = Credentials.from_service_account_info(
    GS_JSON, scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
GC = gspread.authorize(CREDS)
SHEET = GC.open_by_key(SPREADSHEET_ID).sheet1

# =========================
# 🧭 Utilidades tiempo/mercado
# =========================
def now_et() -> dt.datetime:
    return dt.datetime.now(TZ)

# =========================
# 📄 Datos de Google Sheets
# =========================
def load_data() -> pd.DataFrame:
    values = SHEET.get_all_records()
    if not values:
        return pd.DataFrame(columns=[
            "FechaISO","HoraLocal","Ticker","Side","Entrada",
            "Prob_1m","Prob_5m","Prob_15m","Prob_1h","ProbFinal",
            "Estado","Resultado","Nota","Mercado"
        ])
    return pd.DataFrame(values)

# =========================
# 🎨 UI — Streamlit
# =========================
st.set_page_config(page_title="Panel de Señales", layout="wide")

hora_actual = now_et()
st.markdown("### ⏰ Hora local (ET): " + hora_actual.strftime("%Y-%m-%d %H:%M:%S"))

st.title("🤖 Bot 2025")
st.success("😊 Bot Activo – corriendo en tiempo real")

# Cargar hoja
df = load_data()

# =========================
# 📑 Pestañas
# =========================
tabs = st.tabs([
    "✅ Señales Enviadas",
    "❌ Descartadas",
    "📈 Resultados Hoy",
    "📊 Histórico",
    "📉 Distribución Probabilidades"
])

# 1) Señales enviadas
with tabs[0]:
    st.subheader("✅ Señales enviadas (≥80%)")
    sent = df[df["Estado"].isin(["Pre","Confirmada","Confirmado"])] if not df.empty else pd.DataFrame()
    if sent.empty:
        st.warning("⚠️ No hay señales enviadas registradas.")
    else:
        st.dataframe(sent, use_container_width=True)

# 2) Descartadas
with tabs[1]:
    st.subheader("❌ Señales descartadas (<80%)")
    disc = df[df["Estado"].eq("Descartada")] if not df.empty else pd.DataFrame()
    if disc.empty:
        st.warning("⚠️ No hay señales descartadas.")
    else:
        st.dataframe(disc, use_container_width=True)

# 3) Resultados hoy
with tabs[2]:
    st.subheader("📈 Resultados de Hoy")
    if df.empty:
        st.warning("⚠️ No hay resultados hoy.")
    else:
        today = hora_actual.strftime("%Y-%m-%d")
        today_df = df[df["FechaISO"].eq(today)]
        if today_df.empty:
            st.warning("⚠️ No hay resultados hoy.")
        else:
            st.dataframe(today_df, use_container_width=True)

# 4) Histórico
with tabs[3]:
    st.subheader("📊 Histórico Completo")
    if df.empty:
        st.warning("⚠️ No hay histórico todavía.")
    else:
        st.dataframe(df, use_container_width=True)

# 5) Distribución Probabilidades
with tabs[4]:
    st.subheader("📉 Distribución de Probabilidades")
    if df.empty or "ProbFinal" not in df.columns:
        st.warning("⚠️ No hay datos de probabilidades.")
    else:
        st.bar_chart(pd.to_numeric(df["ProbFinal"], errors="coerce").dropna())
