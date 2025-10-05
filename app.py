import os, json, pytz, datetime as dt
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import streamlit as st
import matplotlib.pyplot as plt

# =========================
# 🔧 Config
# =========================
TZ = pytz.timezone("America/New_York")

SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
GS_JSON = json.loads(os.getenv("GOOGLE_SHEETS_JSON"))
CREDS = Credentials.from_service_account_info(GS_JSON, scopes=["https://www.googleapis.com/auth/spreadsheets"])
GC = gspread.authorize(CREDS)
SHEET = GC.open_by_key(SPREADSHEET_ID).sheet1

# =========================
# 🧭 Funciones auxiliares
# =========================
def now_et():
    return dt.datetime.now(TZ)

def load_data():
    values = SHEET.get_all_records()
    if not values:
        return pd.DataFrame(columns=[
            "FechaISO","HoraLocal","Ticker","Side","Entrada",
            "Prob_1m","Prob_5m","Prob_15m","Prob_1h","ProbFinal",
            "Estado","Resultado","Nota","Mercado"
        ])
    return pd.DataFrame(values)

# =========================
# 🎨 Dashboard
# =========================
st.set_page_config(page_title="Panel de Señales", layout="wide")

st.title("📊 Panel de Señales - Trading Bot 2025")

# Estado del bot
st.success("😊 Bot Activo – corriendo en tiempo real")

# Hora local
hora_actual = now_et()
st.write(f"🕒 **Hora local (NJ/ET):** {hora_actual.strftime('%Y-%m-%d %H:%M:%S')}")

# Cargar datos
df = load_data()

# =========================
# 📑 Tabs
# =========================
tabs = st.tabs([
    "✅ Señales Enviadas",
    "❌ Descartadas",
    "📈 Resultados Hoy",
    "📊 Histórico",
    "📉 Distribución Probabilidades",
    "🕒 Últimas Señales"
])

# 1. Señales enviadas (≥80%)
with tabs[0]:
    sent = df[df["Estado"].isin(["Pre","Confirmada"])]
    st.subheader("✅ Señales enviadas (≥80%)")
    if sent.empty:
        st.warning("⚠️ No hay señales enviadas registradas.")
    else:
        st.dataframe(sent)

# 2. Descartadas (<80%)
with tabs[1]:
    disc = df[df["Estado"]=="Descartada"]
    st.subheader("❌ Señales descartadas (<80%)")
    if disc.empty:
        st.warning("⚠️ No hay señales descartadas.")
    else:
        st.dataframe(disc)

# 3. Resultados de hoy + gráfico Win/Loss
with tabs[2]:
    st.subheader("📈 Resultados de Hoy")
    today = hora_actual.strftime("%Y-%m-%d")
    today_df = df[df["FechaISO"]==today]
    if today_df.empty:
        st.warning("⚠️ No hay resultados hoy.")
    else:
        st.dataframe(today_df)

        # Gráfico de Win/Loss
        winloss_data = today_df.groupby(["Resultado"]).size()
        fig, ax = plt.subplots()
        winloss_data.plot(kind="bar", color=["green","red","gray"], ax=ax)
        ax.set_title("Resultados Win/Loss (Hoy)")
        ax.set_ylabel("Cantidad")
        st.pyplot(fig)

# 4. Histórico
with tabs[3]:
    st.subheader("📊 Histórico Completo")
    if df.empty:
        st.warning("⚠️ No hay histórico todavía.")
    else:
        st.dataframe(df)

# 5. Distribución de probabilidades
with tabs[4]:
    st.subheader("📉 Distribución de Probabilidades")
    if df.empty:
        st.warning("⚠️ No hay datos de probabilidades.")
    else:
        fig, ax = plt.subplots()
        df["ProbFinal"].hist(bins=20, ax=ax, color="skyblue", edgecolor="black")
        ax.set_title("Distribución de Probabilidades")
        ax.set_xlabel("Probabilidad final")
        ax.set_ylabel("Frecuencia")
        st.pyplot(fig)

# 6. Últimas señales
with tabs[5]:
    st.subheader("🕒 Últimas Señales Registradas")
    if df.empty:
        st.warning("⚠️ No hay señales recientes.")
    else:
        st.dataframe(df.tail(10))
