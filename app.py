# app.py — Panel de señales Trading Bot
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
CREDS = Credentials.from_service_account_info(
    GS_JSON, scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
GC = gspread.authorize(CREDS)
SHEET = GC.open_by_key(SPREADSHEET_ID).sheet1

# =========================
# 🧭 Funciones auxiliares
# =========================
def now_et() -> dt.datetime:
    return dt.datetime.now(TZ)

def is_market_open(market: str, t: dt.datetime) -> bool:
    wd = t.weekday()
    h, m = t.hour, t.minute
    minutes = h * 60 + m

    if market == "equity":
        if wd >= 5:
            return False
        return (9*60 + 30) <= minutes < (16*60)

    if market == "cme_micro":
        if wd == 5:
            return False
        if wd == 6 and minutes < (18*60):
            return False
        if wd == 4 and minutes >= (17*60):
            return False
        if (17*60) <= minutes < (18*60):
            return False
        return True

    if market == "forex":
        if wd == 5:
            return False
        if wd == 6 and minutes < (17*60):
            return False
        if wd == 4 and minutes >= (17*60):
            return False
        return True

    if market == "crypto":
        return True

    return False

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
# 🎨 Dashboard
# =========================
st.set_page_config(page_title="Panel de Señales", layout="wide")

# Hora local y estado de mercados en la PRIMERA línea
hora_actual = now_et()
labels = {
    "equity": "Equities",
    "cme_micro": "CME Micros",
    "forex": "Forex",
    "crypto": "Crypto",
}

st.markdown("### ⏰ Hora local (ET): " + hora_actual.strftime("%Y-%m-%d %H:%M:%S"))

cols = st.columns(4)
for i, mkt in enumerate(["equity","cme_micro","forex","crypto"]):
    opened = is_market_open(mkt, hora_actual)
    icon = "🟢" if opened else "🔴"
    status = "Abierto" if opened else "Cerrado"
    with cols[i]:
        st.markdown(f"**{labels[mkt]}**")
        st.markdown(f"{icon} **{status}**")

# Título principal
st.title("📊 Panel de Señales - Trading Bot 2025")

# Estado del bot
st.success("😊 Bot Activo – corriendo en tiempo real")

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

# 1. Señales enviadas
with tabs[0]:
    sent = df[df["Estado"].isin(["Pre","Confirmada"])]
    st.subheader("✅ Señales enviadas (≥80%)")
    if sent.empty:
        st.warning("⚠️ No hay señales enviadas registradas.")
    else:
        st.dataframe(sent)

# 2. Descartadas
with tabs[1]:
    disc = df[df["Estado"]=="Descartada"]
    st.subheader("❌ Señales descartadas (<80%)")
    if disc.empty:
        st.warning("⚠️ No hay señales descartadas.")
    else:
        st.dataframe(disc)

# 3. Resultados de hoy
with tabs[2]:
    st.subheader("📈 Resultados de Hoy")
    today = hora_actual.strftime("%Y-%m-%d")
    today_df = df[df["FechaISO"] == today]
    if today_df.empty:
        st.warning("⚠️ No hay resultados hoy.")
    else:
        st.dataframe(today_df)
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

# =========================
# 📊 Resumen global
# =========================
st.header("📊 Resumen Global de Señales")

if df.empty:
    st.warning("⚠️ No hay datos aún.")
else:
    ticker_counts = df["Ticker"].value_counts()
    result_counts = df["Resultado"].value_counts()
    total_ops = result_counts.sum()
    winrate = round((result_counts.get("Win", 0) / total_ops) * 100, 2) if total_ops else 0.0

    col1, col2, col3 = st.columns(3)
    col1.metric("Total de señales", len(df))
    col2.metric("Ganadas", int(result_counts.get("Win", 0)))
    col3.metric("Winrate (%)", f"{winrate}%")

    st.subheader("📌 Señales por Ticker")
    fig1, ax1 = plt.subplots()
    ticker_counts.plot(kind="bar", color="skyblue", ax=ax1)
    ax1.set_title("Cantidad de señales por Ticker")
    ax1.set_ylabel("Señales")
    st.pyplot(fig1)

    st.subheader("🏆 Distribución de Resultados")
    fig2, ax2 = plt.subplots()
    ordered = [c for c in ["Win","Loss","-"] if c in result_counts.index] + \
              [c for c in result_counts.index if c not in ["Win","Loss","-"]]
    result_counts.loc[ordered].plot(kind="bar", color=["green","red","gray"], ax=ax2)
    ax2.set_title("Resultados Win/Loss")
    ax2.set_ylabel("Cantidad")
    st.pyplot(fig2)
