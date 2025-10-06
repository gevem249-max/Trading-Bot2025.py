# app.py — Panel de señales Trading Bot
import os, json, pytz, datetime as dt
import pandas as pd
import numpy as np
import gspread
import yfinance as yf
import matplotlib.pyplot as plt
import mplfinance as mpf
import streamlit as st
from google.oauth2.service_account import Credentials

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

# Cargar datos desde Yahoo Finance con indicadores
def cargar_datos_yf(ticker, interval, period="5d"):
    df = yf.download(ticker, interval=interval, period=period, auto_adjust=True)
    if df.empty:
        return df
    df.dropna(inplace=True)

    # EMA 13 y EMA 21
    df["EMA13"] = df["Close"].ewm(span=13, adjust=False).mean()
    df["EMA21"] = df["Close"].ewm(span=21, adjust=False).mean()

    # RSI
    delta = df["Close"].diff()
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    avg_gain = pd.Series(gain).rolling(14).mean()
    avg_loss = pd.Series(loss).rolling(14).mean()
    rs = avg_gain / avg_loss
    df["RSI"] = 100 - (100 / (1 + rs))

    # MACD
    exp1 = df["Close"].ewm(span=12, adjust=False).mean()
    exp2 = df["Close"].ewm(span=26, adjust=False).mean()
    df["MACD"] = exp1 - exp2
    df["Signal"] = df["MACD"].ewm(span=9, adjust=False).mean()

    return df

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

# Cargar datos de señales
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
    "🕒 Últimas Señales",
    "📊 Resumen Global",
    "📈 Gráfico Avanzado"
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

# 7. Resumen global
with tabs[6]:
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

# 8. Gráfico avanzado con velas + indicadores
with tabs[7]:
    st.header("📈 Gráfico Avanzado (Velas + Indicadores)")

    mercados = {
        "S&P 500 Mini (ES)": "ES=F",
        "Nasdaq Mini (NQ)": "NQ=F",
        "Dow Jones Micro (MYM)": "YM=F",
        "Russell 2000 (M2K)": "RTY=F",
        "Crudo WTI": "CL=F",
        "Oro": "GC=F",
        "Ethereum": "ETH-USD",
        "Bitcoin": "BTC-USD"
    }
    timeframes = {
        "1 minuto": "1m",
        "5 minutos": "5m",
        "15 minutos": "15m",
        "1 hora": "1h",
        "1 día": "1d"
    }

    mercado = st.selectbox("Selecciona mercado:", list(mercados.keys()))
    tf = st.selectbox("Selecciona timeframe:", list(timeframes.keys()))

    if mercado and tf:
        ticker = mercados[mercado]
        interval = timeframes[tf]
        try:
            df_yf = cargar_datos_yf(ticker, interval)
            if df_yf.empty:
                st.error("⚠️ No se pudo cargar el mercado.")
            else:
                # Gráfico principal con velas
                addplots = [
                    mpf.make_addplot(df_yf["EMA13"], color="blue"),
                    mpf.make_addplot(df_yf["EMA21"], color="red"),
                    mpf.make_addplot(df_yf["RSI"], panel=1, color="purple"),
                    mpf.make_addplot(df_yf["MACD"], panel=2, color="green"),
                    mpf.make_addplot(df_yf["Signal"], panel=2, color="orange")
                ]
                fig, _ = mpf.plot(
                    df_yf,
                    type="candle",
                    style="yahoo",
                    addplot=addplots,
                    title=f"{mercado} ({tf})",
                    volume=True,
                    figsize=(10,8),
                    returnfig=True
                )
                st.pyplot(fig)
        except Exception as e:
            st.error(f"Error cargando {ticker}: {e}")
