# app.py — Panel de Señales Trading Bot 2025
import os, json, pytz, datetime as dt
import pandas as pd
import numpy as np
import yfinance as yf
import gspread
from google.oauth2.service_account import Credentials
import streamlit as st
import matplotlib.pyplot as plt
import mplfinance as mpf

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
# 📊 Gráficos Avanzados
# =========================
def cargar_datos_yf(ticker, interval, period="5d"):
    df = yf.download(ticker, interval=interval, period=period, auto_adjust=True)
    if df.empty:
        return df
    df.dropna(inplace=True)

    # EMA 13 y EMA 21
    df["EMA13"] = df["Close"].ewm(span=13, adjust=False).mean()
    df["EMA21"] = df["Close"].ewm(span=21, adjust=False).mean()

    # ======================
    # RSI
    # ======================
    delta = df["Close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss
    df["RSI"] = (100 - (100 / (1 + rs))).astype(float)

    # ======================
    # MACD
    # ======================
    exp1 = df["Close"].ewm(span=12, adjust=False).mean()
    exp2 = df["Close"].ewm(span=26, adjust=False).mean()
    df["MACD"] = (exp1 - exp2).astype(float)
    df["Signal"] = df["MACD"].ewm(span=9, adjust=False).mean().astype(float)

    return df

def plot_candles(df, ticker):
    apds = [
        mpf.make_addplot(df["EMA13"], color="blue"),
        mpf.make_addplot(df["EMA21"], color="orange"),
        mpf.make_addplot(df["RSI"], panel=1, color="purple", ylabel="RSI"),
        mpf.make_addplot(df["MACD"], panel=2, color="green", ylabel="MACD"),
        mpf.make_addplot(df["Signal"], panel=2, color="red"),
    ]
    fig, _ = mpf.plot(
        df,
        type="candle",
        style="yahoo",
        volume=True,
        addplot=apds,
        title=f"{ticker} — Velas + Indicadores",
        figratio=(16,9),
        figscale=1.2,
        returnfig=True
    )
    return fig

# =========================
# 🎨 Dashboard Streamlit
# =========================
st.set_page_config(page_title="Panel de Señales", layout="wide")

# Hora local y estado de mercados
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
st.title("🤖 Bot 2025")
st.success("😊 Bot Activo – corriendo en tiempo real")

# Cargar datos
df = load_data()

# =========================
# 📑 Tabs
# =========================
tabs = st.tabs([
    "🕒 Últimas Señales",
    "📊 Resumen Global",
    "📈 Gráfico Avanzado"
])

# 1. Últimas señales
with tabs[0]:
    st.subheader("🕒 Últimas Señales Registradas")
    if df.empty:
        st.warning("⚠️ No hay señales registradas todavía.")
    else:
        st.dataframe(df.tail(15))

# 2. Resumen Global
with tabs[1]:
    st.subheader("📊 Resumen Global de Señales")
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
        st.pyplot(fig1)

        st.subheader("🏆 Distribución de Resultados")
        fig2, ax2 = plt.subplots()
        ordered = [c for c in ["Win","Loss","-"] if c in result_counts.index] + \
                  [c for c in result_counts.index if c not in ["Win","Loss","-"]]
        result_counts.loc[ordered].plot(kind="bar", color=["green","red","gray"], ax=ax2)
        ax2.set_title("Resultados Win/Loss")
        st.pyplot(fig2)

# 3. Gráfico Avanzado
with tabs[2]:
    st.subheader("📈 Gráfico Avanzado (Velas + Indicadores)")

    mercados = {
        "S&P 500 Mini (ES)": "ES=F",
        "Nasdaq 100 Mini (NQ)": "NQ=F",
        "Dow Jones Micro (MYM)": "YM=F",
        "Russell 2000 (M2K)": "RTY=F",
        "Oro (GC)": "GC=F",
        "Crudo (CL)": "CL=F",
        "Euro/Dólar (EURUSD)": "EURUSD=X",
        "Bitcoin/USD": "BTC-USD",
    }
    timeframes = {
        "1 minuto": "1m",
        "5 minutos": "5m",
        "15 minutos": "15m",
        "1 hora": "1h",
        "1 día": "1d",
    }

    mercado_sel = st.selectbox("Selecciona mercado:", list(mercados.keys()))
    timeframe_sel = st.selectbox("Selecciona timeframe:", list(timeframes.keys()))

    ticker = mercados[mercado_sel]
    interval = timeframes[timeframe_sel]

    try:
        df_yf = cargar_datos_yf(ticker, interval)
        if df_yf.empty:
            st.error(f"No hay datos disponibles para {ticker}")
        else:
            fig = plot_candles(df_yf, mercado_sel)
            st.pyplot(fig)
    except Exception as e:
        st.error(f"Error cargando {ticker}: {e}")
