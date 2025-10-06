# app.py — Panel de Señales Trading Bot 2025
import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import matplotlib.pyplot as plt
import mplfinance as mpf
from streamlit_autorefresh import st_autorefresh
import gspread
from google.oauth2.service_account import Credentials
import os

# =========================
# 🔧 Configuración Google Sheets
# =========================
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
gs_raw = os.getenv("GOOGLE_SHEETS_JSON", "")
GS_JSON = None
if gs_raw:
    try:
        import json
        GS_JSON = json.loads(gs_raw)
    except Exception:
        GS_JSON = None

if not SPREADSHEET_ID or not GS_JSON:
    st.error("⚠️ Falta configuración de Google Sheets (SPREADSHEET_ID o GOOGLE_SHEETS_JSON)")
    st.stop()

CREDS = Credentials.from_service_account_info(GS_JSON, scopes=["https://www.googleapis.com/auth/spreadsheets"])
GC = gspread.authorize(CREDS)
SHEET = GC.open_by_key(SPREADSHEET_ID).sheet1

# =========================
# 📊 Configuración general
# =========================
st.set_page_config(page_title="Panel de Señales · Trading Bot 2025", layout="wide")
st.title("🤖 Bot 2025")
st.success("😊 Bot Activo – corriendo en tiempo real")

tabs = st.tabs(["📩 Últimas Señales", "📈 Resumen Global", "📊 Distribución", "🐞 Debug", "📉 Gráfico Avanzado"])

# =========================
# 📩 Últimas Señales
# =========================
with tabs[0]:
    st.subheader("📩 Últimas Señales registradas")
    try:
        data = SHEET.get_all_records()
        df = pd.DataFrame(data)
        if not df.empty:
            df = df.sort_values("HoraRegistro", ascending=False)  # últimas primero
            st.dataframe(df.head(20), use_container_width=True)
        else:
            st.info("No hay señales registradas aún.")
    except Exception as e:
        st.error(f"Error cargando señales: {e}")

# =========================
# 📈 Resumen Global
# =========================
with tabs[1]:
    st.subheader("📈 Resumen Global de Resultados")
    try:
        data = SHEET.get_all_records()
        df = pd.DataFrame(data)
        if not df.empty and "Resultado" in df.columns:
            total = len(df)
            wins = (df["Resultado"].str.lower()=="win").sum()
            losses = (df["Resultado"].str.lower()=="loss").sum()
            st.metric("✅ Ganadas", wins)
            st.metric("❌ Perdidas", losses)
            st.metric("📊 Total", total)
        else:
            st.info("No hay resultados aún.")
    except Exception as e:
        st.error(f"Error cargando resumen: {e}")

# =========================
# 📊 Distribución de probabilidades
# =========================
with tabs[2]:
    st.subheader("📊 Distribución de Probabilidades")
    try:
        data = SHEET.get_all_records()
        df = pd.DataFrame(data)
        if not df.empty and "ProbFinal" in df.columns:
            plt.hist(df["ProbFinal"], bins=20, color="skyblue", edgecolor="black")
            plt.title("Distribución de Probabilidades Finales")
            plt.xlabel("ProbFinal")
            plt.ylabel("Frecuencia")
            st.pyplot(plt.gcf())
            plt.clf()
        else:
            st.info("No hay probabilidades para graficar.")
    except Exception as e:
        st.error(f"Error en distribución: {e}")

# =========================
# 🐞 Debug (últimos errores/logs)
# =========================
with tabs[3]:
    st.subheader("🐞 Debug / Logs")
    try:
        dbg = GC.open_by_key(SPREADSHEET_ID).worksheet("debug")
        logs = dbg.get_all_records()
        df_logs = pd.DataFrame(logs)
        if not df_logs.empty:
            df_logs = df_logs.sort_values("ts", ascending=False)
            st.dataframe(df_logs.head(20), use_container_width=True)
        else:
            st.info("Sin logs todavía.")
    except Exception as e:
        st.error(f"Error cargando logs: {e}")

# =========================
# 📉 Gráfico Avanzado
# =========================
with tabs[4]:
    st.subheader("📉 Gráfico Avanzado (Velas + Indicadores)")

    mercados = {
        "S&P 500 Mini (ES)": "ES=F",
        "Nasdaq Mini (NQ)": "NQ=F",
        "Dow Jones Micro (MYM)": "YM=F",
        "Russell 2000 (M2K)": "RTY=F",
        "Oro (GC)": "GC=F",
        "Crudo (CL)": "CL=F",
        "EUR/USD": "EURUSD=X",
        "GBP/USD": "GBPUSD=X",
        "USD/JPY": "JPY=X",
        "Bitcoin (BTC)": "BTC-USD",
        "Ethereum (ETH)": "ETH-USD"
    }

    tf_map = {
        "1 minuto": ("1m","2d"),
        "5 minutos": ("5m","5d"),
        "15 minutos": ("15m","1mo"),
        "1 hora": ("60m","3mo"),
        "1 día": ("1d","1y")
    }

    market = st.selectbox("Selecciona mercado:", list(mercados.keys()))
    tf = st.selectbox("Selecciona timeframe:", list(tf_map.keys()))

    ticker = mercados[market]
    interval, lookback = tf_map[tf]

    # 🔄 Auto refresco cada 20s
    st_autorefresh(interval=20 * 1000, key="grafico_refresh")

    try:
        df_yf = yf.download(ticker, period=lookback, interval=interval, progress=False, threads=False)

        if df_yf.empty:
            st.error(f"⚠️ No se pudieron obtener datos para {ticker}")
        else:
            # Fix columnas
            for col in ["Open","High","Low","Close","Volume"]:
                if col in df_yf.columns:
                    df_yf[col] = pd.to_numeric(df_yf[col], errors="coerce")

            # Indicadores
            df_yf["EMA13"] = df_yf["Close"].ewm(span=13, adjust=False).mean()
            df_yf["EMA21"] = df_yf["Close"].ewm(span=21, adjust=False).mean()

            delta = df_yf["Close"].diff()
            gain = delta.where(delta > 0, 0.0)
            loss = -delta.where(delta < 0, 0.0)
            rs = gain.rolling(14).mean() / (loss.rolling(14).mean() + 1e-9)
            df_yf["RSI"] = 100 - (100 / (1 + rs))

            ema_fast = df_yf["Close"].ewm(span=12, adjust=False).mean()
            ema_slow = df_yf["Close"].ewm(span=26, adjust=False).mean()
            df_yf["MACD"] = ema_fast - ema_slow
            df_yf["MACD_signal"] = df_yf["MACD"].ewm(span=9, adjust=False).mean()

            apds = [
                mpf.make_addplot(df_yf["EMA13"], color="blue"),
                mpf.make_addplot(df_yf["EMA21"], color="red"),
                mpf.make_addplot(df_yf["RSI"], panel=1, color="purple", ylabel="RSI"),
                mpf.make_addplot(df_yf["MACD"], panel=2, color="green", ylabel="MACD"),
                mpf.make_addplot(df_yf["MACD_signal"], panel=2, color="orange")
            ]

            fig, axes = mpf.plot(
                df_yf,
                type="candle",
                volume=True,
                style="yahoo",
                addplot=apds,
                title=f"{market} — {tf}",
                returnfig=True,
                figscale=1.2
            )
            st.pyplot(fig)

    except Exception as e:
        st.error(f"Error cargando {ticker}: {e}")

    # 🎯 Evaluación manual de entrada
    st.subheader("🎯 Evaluación de entrada manual")
    entry_price = st.number_input("Precio de entrada:", min_value=0.0, value=0.0, step=0.25)

    if entry_price > 0 and not df_yf.empty:
        ultima_candle = df_yf.iloc[-1]
        ema13 = ultima_candle["EMA13"]
        ema21 = ultima_candle["EMA21"]
        rsi_val = ultima_candle["RSI"]
        macd_val = ultima_candle["MACD"] - ultima_candle["MACD_signal"]

        score = 50
        if ema13 > ema21: score += 10
        if rsi_val < 30: score += 15
        elif rsi_val > 70: score -= 15
        if macd_val > 0: score += 10
        else: score -= 10

        st.write(f"📊 Probabilidad estimada para entrada en {entry_price}: **{score}%**")
