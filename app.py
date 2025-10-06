# app.py — Panel de Señales Trading Bot 2025 (completo)

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
# 🧭 Utilidades tiempo/mercado
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
        if wd == 5: return False
        if wd == 6 and minutes < (18*60): return False
        if wd == 4 and minutes >= (17*60): return False
        if (17*60) <= minutes < (18*60): return False
        return True

    if market == "forex":
        if wd == 5: return False
        if wd == 6 and minutes < (17*60): return False
        if wd == 4 and minutes >= (17*60): return False
        return True

    if market == "crypto":
        return True

    return False

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
# 📈 Yahoo Finance (limpieza robusta)
# =========================
def fetch_yf_clean(ticker: str, interval: str, period: str):
    df = yf.download(
        ticker, interval=interval, period=period,
        auto_adjust=True, progress=False, threads=False
    )
    if df is None or df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    for col in ["Open","High","Low","Close","Adj Close","Volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    keep = [c for c in ["Open","High","Low","Close","Volume"] if c in df.columns]
    df = df[keep].dropna(subset=["Open","High","Low","Close"])
    if "Volume" in df.columns:
        df["Volume"] = df["Volume"].fillna(0)
    df = df.astype({c: float for c in ["Open","High","Low","Close"] if c in df.columns})
    if "Volume" in df.columns:
        df["Volume"] = df["Volume"].astype(float)
    return df

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df.copy()
    out = df.copy()
    out["EMA13"] = out["Close"].ewm(span=13, adjust=False).mean()
    out["EMA21"] = out["Close"].ewm(span=21, adjust=False).mean()
    delta = out["Close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / (avg_loss.replace(0, np.nan))
    out["RSI"] = 100 - (100 / (1 + rs))
    out["RSI"] = out["RSI"].fillna(method="bfill")
    ema12 = out["Close"].ewm(span=12, adjust=False).mean()
    ema26 = out["Close"].ewm(span=26, adjust=False).mean()
    out["MACD"] = ema12 - ema26
    out["Signal"] = out["MACD"].ewm(span=9, adjust=False).mean()
    return out

def plot_candles(df: pd.DataFrame, title: str):
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
        title=title,
        figratio=(16,9),
        figscale=1.2,
        returnfig=True
    )
    return fig

# =========================
# 🎨 UI — Streamlit
# =========================
st.set_page_config(page_title="Panel de Señales", layout="wide")
hora_actual = now_et()
labels = {"equity":"Equities", "cme_micro":"CME Micros", "forex":"Forex", "crypto":"Crypto"}
st.markdown("### ⏰ Hora local (ET): " + hora_actual.strftime("%Y-%m-%d %H:%M:%S"))
cols = st.columns(4)
for i, mkt in enumerate(["equity","cme_micro","forex","crypto"]):
    opened = is_market_open(mkt, hora_actual)
    icon = "🟢" if opened else "🔴"
    with cols[i]:
        st.markdown(f"**{labels[mkt]}**")
        st.markdown(f"{icon} **{'Abierto' if opened else 'Cerrado'}**")

st.title("🤖 Bot 2025")
st.success("😊 Bot Activo – corriendo en tiempo real")

df = load_data()

# =========================
# 📑 Pestañas
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

# Pestañas de datos (igual que antes)...
with tabs[0]:
    st.subheader("✅ Señales enviadas (≥80%)")
    sent = df[df["Estado"].isin(["Pre","Confirmada","Confirmado"])] if not df.empty else pd.DataFrame()
    st.dataframe(sent, use_container_width=True) if not sent.empty else st.warning("⚠️ No hay señales enviadas registradas.")

with tabs[1]:
    st.subheader("❌ Señales descartadas (<80%)")
    disc = df[df["Estado"].eq("Descartada")] if not df.empty else pd.DataFrame()
    st.dataframe(disc, use_container_width=True) if not disc.empty else st.warning("⚠️ No hay señales descartadas.")

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
            winloss_data = today_df["Resultado"].value_counts()
            fig, ax = plt.subplots()
            winloss_data.reindex(["Win","Loss","-"]).fillna(0).plot(kind="bar", color=["green","red","gray"], ax=ax)
            st.pyplot(fig)

with tabs[3]:
    st.subheader("📊 Histórico Completo")
    st.dataframe(df, use_container_width=True) if not df.empty else st.warning("⚠️ No hay histórico todavía.")

with tabs[4]:
    st.subheader("📉 Distribución de Probabilidades")
    if df.empty or "ProbFinal" not in df.columns:
        st.warning("⚠️ No hay datos de probabilidades.")
    else:
        fig, ax = plt.subplots()
        pd.to_numeric(df["ProbFinal"], errors="coerce").dropna().hist(bins=20, ax=ax, color="skyblue", edgecolor="black")
        st.pyplot(fig)

with tabs[5]:
    st.subheader("🕒 Últimas Señales Registradas")
    st.dataframe(df.tail(10), use_container_width=True) if not df.empty else st.warning("⚠️ No hay señales recientes.")

with tabs[6]:
    st.subheader("📊 Resumen Global de Señales")
    if df.empty:
        st.warning("⚠️ No hay datos aún.")
    else:
        result_counts = df["Resultado"].value_counts()
        total_ops = int(result_counts.sum())
        winrate = round((result_counts.get("Win", 0) / total_ops) * 100, 2) if total_ops else 0.0
        c1, c2, c3 = st.columns(3)
        c1.metric("Total de señales", len(df))
        c2.metric("Ganadas", int(result_counts.get("Win", 0)))
        c3.metric("Winrate (%)", f"{winrate}%")

# 8) Gráfico Avanzado
with tabs[7]:
    st.subheader("📈 Gráfico Avanzado (Velas + Indicadores)")

    mercados = {
        "S&P 500 Mini (ES)": "ES=F",
        "Nasdaq 100 Mini (NQ)": "NQ=F",
        "Dow Jones (YM/MYM)": "YM=F",
        "Russell 2000 (RTY/M2K)": "RTY=F",
        "Oro (GC)": "GC=F",
        "Plata (SI)": "SI=F",
        "Crudo WTI (CL)": "CL=F",
        "Gas Natural (NG)": "NG=F",
        "Euro FX (6E)": "EURUSD=X",
        "Libra FX (6B)": "GBPUSD=X",
        "Yen FX (6J)": "JPY=X",
        "Bitcoin/USD": "BTC-USD",
        "Ethereum/USD": "ETH-USD"
    }

    timeframes = {
        "1 minuto": ("1m", "7d"),
        "5 minutos": ("5m", "30d"),
        "15 minutos": ("15m", "60d"),
        "1 hora": ("1h", "730d"),
        "1 día": ("1d", "5y"),
    }

    mercado_sel = st.selectbox("Selecciona mercado:", list(mercados.keys()))
    timeframe_sel = st.selectbox("Selecciona timeframe:", list(timeframes.keys()))

    yf_ticker = mercados[mercado_sel]
    interval, period = timeframes[timeframe_sel]

    try:
        base = fetch_yf_clean(yf_ticker, interval, period)
        if base.empty:
            st.error(f"No hay datos disponibles para {yf_ticker}")
        else:
            df_plot = add_indicators(base)
            fig = plot_candles(df_plot, f"{mercado_sel} — {timeframe_sel}")
            st.pyplot(fig)
    except Exception as e:
        st.error(f"Error cargando {yf_ticker}: {e}")
