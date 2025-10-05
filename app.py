# app.py — Panel de señales Trading Bot con gráficos avanzados
import os, json, pytz, datetime as dt
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import streamlit as st
import matplotlib.pyplot as plt
import yfinance as yf
import mplfinance as mpf

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
        if wd >= 5: return False
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
    if market == "crypto": return True
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

# Hora local y estado de mercados
hora_actual = now_et()
labels = {"equity": "Equities","cme_micro": "CME Micros","forex": "Forex","crypto": "Crypto"}
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
st.success("😊 Bot Activo – corriendo en tiempo real")

# =========================
# 📈 Gráfico dinámico por mercado/timeframe con velas
# =========================
st.header("📈 Gráfico Avanzado (Velas + Indicadores)")

futures_list = {
    "S&P 500 (MES)": "MES=F",
    "Nasdaq (MNQ)": "NQ=F",
    "Dow Jones (MYM)": "YM=F",
    "Russell 2000 (M2K)": "RTY=F",
    "Crude Oil (CL)": "CL=F",
    "Gold (GC)": "GC=F",
    "EUR/USD": "EURUSD=X",
    "Bitcoin": "BTC-USD",
    "DraftKings": "DKNG"
}
timeframes = {
    "1 minuto": ("1m","1d"),
    "5 minutos": ("5m","5d"),
    "15 minutos": ("15m","1mo"),
    "1 hora": ("60m","3mo"),
    "1 día": ("1d","1y")
}
col1, col2 = st.columns(2)
with col1:
    choice = st.selectbox("Selecciona mercado:", list(futures_list.keys()))
    ticker = futures_list[choice]
with col2:
    tf_choice = st.selectbox("Selecciona timeframe:", list(timeframes.keys()))
    interval, period = timeframes[tf_choice]

try:
    data = yf.download(ticker, period=period, interval=interval, progress=False)
    if not data.empty:
        # Indicadores
        data["EMA13"] = data["Close"].ewm(span=13, adjust=False).mean()
        data["EMA21"] = data["Close"].ewm(span=21, adjust=False).mean()

        # Subplots
        apds = [
            mpf.make_addplot(data["EMA13"], color="blue"),
            mpf.make_addplot(data["EMA21"], color="orange"),
        ]

        # Crear figura
        fig, axes = mpf.plot(
            data,
            type="candle",
            style="yahoo",
            addplot=apds,
            volume=True,
            returnfig=True,
            figratio=(16,9),
            figscale=1.2
        )

        # RSI
        delta = data["Close"].diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = -delta.where(delta < 0, 0).rolling(14).mean()
        rs = gain / (loss + 1e-9)
        rsi = 100 - (100/(1+rs))
        axes[2].plot(rsi, label="RSI", color="purple")
        axes[2].axhline(70, color="red", linestyle="--")
        axes[2].axhline(30, color="green", linestyle="--")
        axes[2].legend()

        # MACD
        exp1 = data["Close"].ewm(span=12, adjust=False).mean()
        exp2 = data["Close"].ewm(span=26, adjust=False).mean()
        macd = exp1 - exp2
        signal = macd.ewm(span=9, adjust=False).mean()
        axes[2].plot(macd, label="MACD", color="cyan")
        axes[2].plot(signal, label="Signal", color="orange")
        axes[2].legend()

        st.pyplot(fig)
    else:
        st.warning(f"⚠️ No se pudo cargar datos de {ticker}")
except Exception as e:
    st.error(f"Error cargando {ticker}: {e}")
