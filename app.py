# app.py — Panel de señales Trading Bot 2025
import os, json, pytz, datetime as dt
import pandas as pd
import numpy as np
import gspread
from google.oauth2.service_account import Credentials
import streamlit as st
import matplotlib.pyplot as plt
import mplfinance as mpf
import yfinance as yf
from streamlit_autorefresh import st_autorefresh

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

# refresco automático cada 20s
st_autorefresh(interval=20 * 1000, key="refresh_graph")

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
# 📊 Indicadores técnicos
# =========================
def add_indicators(df):
    df["EMA13"] = df["Close"].ewm(span=13, adjust=False).mean()
    df["EMA21"] = df["Close"].ewm(span=21, adjust=False).mean()

    delta = df["Close"].diff().fillna(0)
    gain = np.where(delta > 0, delta, 0).ravel()
    loss = np.where(delta < 0, -delta, 0).ravel()
    roll_up = pd.Series(gain).rolling(14).mean()
    roll_down = pd.Series(loss).rolling(14).mean()
    RS = roll_up / roll_down
    df["RSI"] = 100 - (100 / (1 + RS))

    ema12 = df["Close"].ewm(span=12, adjust=False).mean()
    ema26 = df["Close"].ewm(span=26, adjust=False).mean()
    df["MACD"] = ema12 - ema26
    df["Signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
    return df

def plot_chart(symbol, tf_label, tf_yf):
    try:
        df = yf.download(symbol, period="5d", interval=tf_yf)
        df.dropna(inplace=True)
        df = add_indicators(df)

        apds = [
            mpf.make_addplot(df["EMA13"], color="blue"),
            mpf.make_addplot(df["EMA21"], color="orange"),
            mpf.make_addplot(df["RSI"], panel=2, color="purple", ylabel="RSI"),
            mpf.make_addplot(df["MACD"], panel=3, color="red", ylabel="MACD"),
            mpf.make_addplot(df["Signal"], panel=3, color="green"),
        ]

        fig, _ = mpf.plot(
            df,
            type="candle",
            volume=True,
            addplot=apds,
            returnfig=True,
            style="yahoo",
            title=f"{symbol} — {tf_label}",
            figsize=(10,8)
        )
        st.pyplot(fig)

        return df
    except Exception as e:
        st.error(f"Error cargando {symbol}: {e}")
        return pd.DataFrame()

# =========================
# 🎨 Dashboard
# =========================
st.set_page_config(page_title="Panel de Señales", layout="wide")

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

st.title("🤖 Bot 2025")
st.success("😊 Bot Activo – corriendo en tiempo real")

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
    st.dataframe(sent if not sent.empty else pd.DataFrame())

# 2. Descartadas
with tabs[1]:
    disc = df[df["Estado"]=="Descartada"]
    st.subheader("❌ Señales descartadas (<80%)")
    st.dataframe(disc if not disc.empty else pd.DataFrame())

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
        st.pyplot(fig)

# 4. Histórico
with tabs[3]:
    st.subheader("📊 Histórico Completo")
    st.dataframe(df if not df.empty else pd.DataFrame())

# 5. Distribución de probabilidades
with tabs[4]:
    st.subheader("📉 Distribución de Probabilidades")
    if not df.empty:
        fig, ax = plt.subplots()
        df["ProbFinal"].hist(bins=20, ax=ax, color="skyblue", edgecolor="black")
        ax.set_title("Distribución de Probabilidades")
        st.pyplot(fig)

# 6. Últimas señales
with tabs[5]:
    st.subheader("🕒 Últimas Señales Registradas")
    st.dataframe(df.tail(10) if not df.empty else pd.DataFrame())

# 7. Resumen Global
with tabs[6]:
    st.subheader("📊 Resumen Global de Señales")
    if not df.empty:
        ticker_counts = df["Ticker"].value_counts()
        result_counts = df["Resultado"].value_counts()
        total_ops = result_counts.sum()
        winrate = round((result_counts.get("Win", 0) / total_ops) * 100, 2) if total_ops else 0.0

        col1, col2, col3 = st.columns(3)
        col1.metric("Total de señales", len(df))
        col2.metric("Ganadas", int(result_counts.get("Win", 0)))
        col3.metric("Winrate (%)", f"{winrate}%")

# 8. Gráfico Avanzado
with tabs[7]:
    st.subheader("📈 Gráfico Avanzado (Velas + Indicadores)")

    mercados = {
        "S&P 500 Mini (ES)": "ES=F",
        "Dow Jones Micro (MYM)": "YM=F",
        "Nasdaq 100 Mini (NQ)": "NQ=F",
        "Russell 2000 (M2K)": "RTY=F",
        "EUR/USD": "EURUSD=X",
        "GBP/USD": "GBPUSD=X",
        "USD/JPY": "JPY=X",
        "Bitcoin": "BTC-USD",
        "Ethereum": "ETH-USD"
    }
    timeframes = {
        "1 minuto": "1m",
        "5 minutos": "5m",
        "15 minutos": "15m",
        "1 hora": "1h",
        "1 día": "1d"
    }

    mercado = st.selectbox("Selecciona mercado:", list(mercados.keys()))
    tf_label = st.selectbox("Selecciona timeframe:", list(timeframes.keys()))

    df_chart = plot_chart(mercados[mercado], tf_label, timeframes[tf_label])

    st.subheader("🎯 Evaluación de entrada manual")
    entrada = st.number_input("Precio de entrada:", value=0.0, format="%.2f")

    if entrada > 0 and not df_chart.empty:
        ultimo = df_chart.iloc[-1]
        tendencia = "ALCISTA" if ultimo["EMA13"] > ultimo["EMA21"] else "BAJISTA"
        rsi = ultimo["RSI"]
        macd = ultimo["MACD"] - ultimo["Signal"]

        if tendencia == "ALCISTA" and rsi > 50 and macd > 0:
            st.success(f"✅ Alta probabilidad de subida desde {entrada}")
        elif tendencia == "BAJISTA" and rsi < 50 and macd < 0:
            st.error(f"❌ Alta probabilidad de bajada desde {entrada}")
        else:
            st.warning(f"⚠️ Señal mixta en {entrada}, probabilidad media.")
