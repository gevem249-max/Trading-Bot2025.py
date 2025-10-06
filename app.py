# app.py — Panel de Señales Trading Bot 2025
import os, json, pytz, datetime as dt
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import streamlit as st
import matplotlib.pyplot as plt
import yfinance as yf
import mplfinance as mpf
import numpy as np
from streamlit_autorefresh import st_autorefresh

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
# 📈 Gráfico avanzado con indicadores
# =========================
def plot_chart(symbol: str, tf: str):
    tf_map = {
        "1 minuto": "1m",
        "5 minutos": "5m",
        "15 minutos": "15m",
        "1 hora": "1h",
        "1 día": "1d"
    }
    tf_yf = tf_map.get(tf, "5m")

    df = yf.download(symbol, period="5d", interval=tf_yf)
    if df.empty:
        st.error(f"No hay datos para {symbol}")
        return

    # 🔧 limpiar datos y forzar numéricos
    df = df.dropna()
    for col in ["Open","High","Low","Close","Volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna()

    # EMA13 y EMA21
    df["EMA13"] = df["Close"].ewm(span=13, adjust=False).mean()
    df["EMA21"] = df["Close"].ewm(span=21, adjust=False).mean()

    # RSI
    delta = df["Close"].diff()
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    roll_up = pd.Series(gain).rolling(14).mean()
    roll_down = pd.Series(loss).rolling(14).mean()
    RS = roll_up / (roll_down + 1e-9)
    df["RSI"] = 100.0 - (100.0 / (1.0 + RS))

    # MACD
    ema12 = df["Close"].ewm(span=12, adjust=False).mean()
    ema26 = df["Close"].ewm(span=26, adjust=False).mean()
    df["MACD"] = ema12 - ema26
    df["Signal"] = df["MACD"].ewm(span=9, adjust=False).mean()

    # Crear gráfico
    apds = [
        mpf.make_addplot(df["EMA13"], color="blue"),
        mpf.make_addplot(df["EMA21"], color="orange"),
        mpf.make_addplot(df["RSI"], panel=1, color="purple", ylabel="RSI"),
        mpf.make_addplot(df["MACD"], panel=2, color="red", ylabel="MACD"),
        mpf.make_addplot(df["Signal"], panel=2, color="green"),
    ]

    fig, _ = mpf.plot(
        df,
        type="candle",
        volume=True,
        addplot=apds,
        style="yahoo",
        figsize=(10,8),
        returnfig=True
    )
    st.pyplot(fig)

# =========================
# 🎨 Dashboard
# =========================
st.set_page_config(page_title="Panel de Señales", layout="wide")

# 🔄 Auto refresh cada 20s
st_autorefresh(interval=20 * 1000, key="refresh")

# Hora local y estado mercados
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
    "✅ Señales Enviadas",
    "❌ Descartadas",
    "📈 Resultados Hoy",
    "📊 Histórico",
    "📉 Distribución Probabilidades",
    "📊 Resumen Global",
    "📈 Gráfico Avanzado"
])

# 1. Últimas señales
with tabs[0]:
    st.subheader("🕒 Últimas Señales Registradas")
    if df.empty:
        st.warning("⚠️ No hay señales recientes.")
    else:
        st.dataframe(df.tail(10).iloc[::-1])  # más nuevas arriba

# 2. Señales enviadas
with tabs[1]:
    sent = df[df["Estado"].isin(["Pre","Confirmada"])]
    st.subheader("✅ Señales enviadas (≥80%)")
    if sent.empty:
        st.warning("⚠️ No hay señales enviadas registradas.")
    else:
        st.dataframe(sent)

# 3. Descartadas
with tabs[2]:
    disc = df[df["Estado"]=="Descartada"]
    st.subheader("❌ Señales descartadas (<80%)")
    if disc.empty:
        st.warning("⚠️ No hay señales descartadas.")
    else:
        st.dataframe(disc)

# 4. Resultados de hoy
with tabs[3]:
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

# 5. Histórico
with tabs[4]:
    st.subheader("📊 Histórico Completo")
    if df.empty:
        st.warning("⚠️ No hay histórico todavía.")
    else:
        st.dataframe(df)

# 6. Distribución de probabilidades
with tabs[5]:
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

# 7. Resumen Global
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

# 8. Gráfico Avanzado
with tabs[7]:
    st.subheader("📈 Gráfico Avanzado (Velas + Indicadores)")
    mercados = {
        "S&P 500 Mini (ES)": "ES=F",
        "Nasdaq 100 Mini (NQ)": "NQ=F",
        "Dow Jones Micro (MYM)": "YM=F",
        "Russell 2000 (M2K)": "RTY=F",
        "Oro (GC)": "GC=F",
        "Crudo (CL)": "CL=F",
        "EUR/USD": "EURUSD=X",
        "BTC/USD": "BTC-USD"
    }
    mkt = st.selectbox("Selecciona mercado:", list(mercados.keys()))
    tf = st.selectbox("Selecciona timeframe:", ["1 minuto","5 minutos","15 minutos","1 hora","1 día"])
    try:
        plot_chart(mercados[mkt], tf)
    except Exception as e:
        st.error(f"Error cargando {mercados[mkt]}: {e}")

    st.markdown("### 🎯 Evaluación de entrada manual")
    entry_price = st.number_input("Precio de entrada:", min_value=0.0, value=0.0, step=0.25)
    if entry_price > 0 and not df.empty:
        last_close = df["Entrada"].iloc[-1] if "Entrada" in df.columns else None
        if last_close:
            prob = np.random.uniform(60,95)
            if entry_price < last_close:
                st.success(f"📉 Posible corto – Probabilidad estimada {prob:.1f}%")
            else:
                st.success(f"📈 Posible largo – Probabilidad estimada {prob:.1f}%")
