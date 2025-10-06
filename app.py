# app.py — Panel de Señales Trading Bot 2025 (completo y robusto)

import os, json, pytz, datetime as dt
import pandas as pd
import numpy as np
import yfinance as yf
import gspread
from google.oauth2.service_account import Credentials
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import matplotlib.pyplot as plt
import mplfinance as mpf

# =========================
# 🔧 Configuración
# =========================
TZ = pytz.timezone("America/New_York")
REFRESH_MS = int(os.getenv("STREAMLIT_REFRESH_MS", "20000"))  # 20s por defecto

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
# 📄 Google Sheets (carga segura)
# =========================
SAFE_COLS = [
    "FechaISO","HoraLocal","HoraRegistro","Ticker","Side","Entrada",
    "Prob_1m","Prob_5m","Prob_15m","Prob_1h","ProbFinal",
    "ProbClasificación","Estado","Tipo","Resultado","Nota","Mercado",
    "pattern","pat_score","macd_val","sr_score","atr","SL","TP",
    "Recipients","ScheduledConfirm"
]

def load_data() -> pd.DataFrame:
    try:
        values = SHEET.get_all_records()
        if not values:
            return pd.DataFrame(columns=SAFE_COLS)
        df = pd.DataFrame(values)
        # Asegurar todas las columnas, rellenando faltantes
        for c in SAFE_COLS:
            if c not in df.columns:
                df[c] = ""
        # Orden de columnas y convertir a string para evitar ArrowTypeError
        df = df[SAFE_COLS].astype(str)
        # Ordenar por fecha/hora desc (recientes arriba)
        if "FechaISO" in df.columns and "HoraRegistro" in df.columns:
            df["_ts"] = df["FechaISO"] + " " + df["HoraRegistro"]
            try:
                df["_ts"] = pd.to_datetime(df["_ts"], errors="coerce")
                df = df.sort_values("_ts", ascending=False)
            except Exception:
                pass
            df = df.drop(columns=["_ts"], errors="ignore")
        return df
    except Exception as e:
        st.error(f"Error leyendo Google Sheets: {e}")
        return pd.DataFrame(columns=SAFE_COLS)

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

    # EMA 13/21
    out["EMA13"] = out["Close"].ewm(span=13, adjust=False).mean()
    out["EMA21"] = out["Close"].ewm(span=21, adjust=False).mean()

    # RSI 14
    delta = out["Close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean().replace(0, np.nan)
    rs = avg_gain / avg_loss
    out["RSI"] = 100 - (100 / (1 + rs))
    out["RSI"] = out["RSI"].fillna(method="bfill")

    # MACD (12,26,9)
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
st_autorefresh(interval=REFRESH_MS, key="auto_refresh")

# Primera línea: hora + estado mercados (horizontal)
hora_actual = now_et()
labels = {"equity":"Equities", "cme_micro":"CME Micros", "forex":"Forex", "crypto":"Crypto"}
top_cols = st.columns([2,2,2,2,4])
with top_cols[0]:
    st.markdown("### ⏰ ET")
    st.markdown(f"**{hora_actual.strftime('%Y-%m-%d %H:%M:%S')}**")
for i, mkt in enumerate(["equity","cme_micro","forex","crypto"], start=1):
    opened = is_market_open(mkt, hora_actual)
    icon = "🟢" if opened else "🔴"
    with top_cols[i]:
        st.markdown(f"### {labels[mkt]}")
        st.markdown(f"{icon} **{'Abierto' if opened else 'Cerrado'}**")

# Título y estado del bot
st.title("📊 Panel de Señales - Trading Bot 2025")
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
    "📉 Distribución Probabilidades",
    "🕒 Últimas Señales",
    "📊 Resumen Global",
    "📈 Gráfico Avanzado",
    "🤔 Consulta Manual"
])

# 1) Señales enviadas (recientes arriba)
with tabs[0]:
    st.subheader("✅ Señales enviadas (≥80%)")
    sent = df[df["Estado"].isin(["Pre","Confirmada","Confirmado"])] if not df.empty else pd.DataFrame(columns=SAFE_COLS)
    st.dataframe(sent, use_container_width=True) if not sent.empty else st.warning("⚠️ No hay señales enviadas registradas.")

# 2) Descartadas
with tabs[1]:
    st.subheader("❌ Señales descartadas (<80%)")
    disc = df[df["Estado"].eq("Descartada")] if not df.empty else pd.DataFrame(columns=SAFE_COLS)
    st.dataframe(disc, use_container_width=True) if not disc.empty else st.warning("⚠️ No hay señales descartadas.")

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
            # Conteo Win/Loss
            wl = today_df["Resultado"].value_counts()
            fig, ax = plt.subplots()
            wl.reindex(["Win","Loss","-"]).fillna(0).plot(kind="bar", color=["green","red","gray"], ax=ax)
            ax.set_title("Resultados Win/Loss (Hoy)")
            ax.set_ylabel("Cantidad")
            st.pyplot(fig)

# 4) Histórico completo
with tabs[3]:
    st.subheader("📊 Histórico Completo")
    st.dataframe(df, use_container_width=True) if not df.empty else st.warning("⚠️ No hay histórico todavía.")

# 5) Distribución Probabilidades
with tabs[4]:
    st.subheader("📉 Distribución de Probabilidades")
    if df.empty or "ProbFinal" not in df.columns:
        st.warning("⚠️ No hay datos de probabilidades.")
    else:
        nums = pd.to_numeric(df["ProbFinal"], errors="coerce").dropna()
        if nums.empty:
            st.warning("⚠️ No hay valores numéricos válidos en ProbFinal.")
        else:
            fig, ax = plt.subplots()
            nums.hist(bins=20, ax=ax, color="skyblue", edgecolor="black")
            ax.set_title("Distribución de Probabilidades")
            ax.set_xlabel("Probabilidad final")
            ax.set_ylabel("Frecuencia")
            st.pyplot(fig)

# 6) Últimas señales (recientes primero)
with tabs[5]:
    st.subheader("🕒 Últimas Señales Registradas")
    st.dataframe(df.head(10), use_container_width=True) if not df.empty else st.warning("⚠️ No hay señales recientes.")

# 7) Resumen Global
with tabs[6]:
    st.subheader("📊 Resumen Global de Señales")
    if df.empty:
        st.warning("⚠️ No hay datos aún.")
    else:
        ticker_counts = df["Ticker"].value_counts()
        result_counts = df["Resultado"].value_counts()
        total_ops = int(result_counts.sum())
        winrate = round((result_counts.get("Win", 0) / total_ops) * 100, 2) if total_ops else 0.0

        c1, c2, c3 = st.columns(3)
        c1.metric("Total de señales", len(df))
        c2.metric("Ganadas", int(result_counts.get("Win", 0)))
        c3.metric("Winrate (%)", f"{winrate}%")

        st.subheader("📌 Señales por Ticker")
        fig1, ax1 = plt.subplots()
        ticker_counts.plot(kind="bar", color="skyblue", ax=ax1)
        ax1.set_ylabel("Señales")
        st.pyplot(fig1)

        st.subheader("🏆 Distribución de Resultados")
        fig2, ax2 = plt.subplots()
        ordered = ["Win","Loss","-"]
        result_counts.reindex(ordered).fillna(0).plot(kind="bar", color=["green","red","gray"], ax=ax2)
        ax2.set_ylabel("Cantidad")
        st.pyplot(fig2)

# 8) Gráfico Avanzado (Velas + Indicadores)
with tabs[7]:
    st.subheader("📈 Gráfico Avanzado (Velas + EMA13/21, RSI, MACD)")
    mercados = {
        "S&P 500 Mini (ES)": "ES=F",
        "Nasdaq 100 Mini (NQ)": "NQ=F",
        "Dow Jones (YM/MYM)": "YM=F",
        "Russell 2000 (RTY/M2K)": "RTY=F",
        "Oro (GC)": "GC=F",
        "Crudo (CL)": "CL=F",
        "EUR/USD": "EURUSD=X",
        "Bitcoin/USD": "BTC-USD",
        "DKNG": "DKNG"
    }
    timeframes = {
        "1 minuto": ("1m", "7d"),
        "5 minutos": ("5m", "30d"),
        "15 minutos": ("15m", "60d"),
        "1 hora": ("1h", "730d"),
        "1 día": ("1d", "5y"),
    }
    cA, cB = st.columns(2)
    with cA:
        mercado_sel = st.selectbox("Selecciona mercado:", list(mercados.keys()), index=0)
    with cB:
        timeframe_sel = st.selectbox("Selecciona timeframe:", list(timeframes.keys()), index=1)

    yf_ticker = mercados[mercado_sel]
    interval, period = timeframes[timeframe_sel]

    try:
        base = fetch_yf_clean(yf_ticker, interval, period)
        if base.empty:
            st.error(f"No hay datos disponibles para {yf_ticker}")
        else:
            df_plot = add_indicators(base)
            fig = plot_candles(df_plot, f"{mercado_sel} — {timeframe_sel}")
            st.pyplot(fig, use_container_width=True)
    except Exception as e:
        st.error(f"Error cargando {yf_ticker}: {e}")

# 9) Consulta Manual (ticker + entrada + side => evaluación rápida)
with tabs[8]:
    st.subheader("🤔 Consulta Manual de Entrada")
    c1, c2, c3 = st.columns(3)
    with c1:
        tick = st.text_input("Ticker (ej: DKNG, ES=F, EURUSD=X)", value="DKNG")
    with c2:
        side = st.selectbox("Dirección", ["Buy","Sell"])
    with c3:
        entry = st.number_input("Precio de entrada", min_value=0.0, value=45.0, step=0.01)

    if st.button("Evaluar entrada"):
        try:
            # 5m / 15m para señales
            df5 = fetch_yf_clean(tick, "5m", "5d")
            df15 = fetch_yf_clean(tick, "15m", "60d")
            if df5.empty or df15.empty:
                st.warning("No hay suficientes datos para evaluar.")
            else:
                # Prob. base simple
                def ema(s, span): return s.ewm(span=span, adjust=False).mean()
                def rsi(s, p=14):
                    d = s.diff()
                    up = d.clip(lower=0)
                    dn = -d.clip(upper=0)
                    rs = up.rolling(p).mean() / (dn.rolling(p).mean().replace(0, np.nan))
                    return 100 - (100/(1+rs))

                close5 = df5["Close"]
                e8, e21 = ema(close5, 8), ema(close5, 21)
                r = rsi(close5, 14).iloc[-1]
                trend = (e8.iloc[-1]-e21.iloc[-1])
                base = 50.0
                if side.lower()=="buy":
                    if trend > 0: base += 20
                    if 45 <= r <= 70: base += 15
                    if r < 35: base -= 15
                else:
                    if trend < 0: base += 20
                    if 30 <= r <= 55: base += 15
                    if r > 65: base -= 15
                base = max(0.0, min(100.0, base))

                # MACD 15m
                c15 = df15["Close"]
                ema12 = c15.ewm(span=12, adjust=False).mean()
                ema26 = c15.ewm(span=26, adjust=False).mean()
                macd = (ema12 - ema26).iloc[-1]
                signal = (ema12 - ema26).ewm(span=9, adjust=False).mean().iloc[-1]
                macd_score = 8 if (macd > signal and side=="Buy") or (macd < signal and side=="Sell") else 0

                # ATR 5m
                high5, low5, close5s = df5["High"], df5["Low"], df5["Close"]
                tr = pd.concat([
                    (high5 - low5).abs(),
                    (high5 - close5s.shift(1)).abs(),
                    (low5 - close5s.shift(1)).abs()
                ], axis=1).max(axis=1)
                atr_val = tr.rolling(14).mean().iloc[-1] if len(tr)>=14 else tr.mean()

                # SL/TP sugeridos (RR 2:1)
                if side=="Buy":
                    sl = entry - atr_val
                    tp = entry + 2*atr_val
                else:
                    sl = entry + atr_val
                    tp = entry - 2*atr_val

                final_score = round(base*0.7 + (100*(macd_score/8.0))*0.3, 1)
                st.info(f"Probabilidad estimada: **{final_score}%**")
                st.write(f"ATR(5m): {atr_val:.4f} | SL: **{sl:.4f}** | TP: **{tp:.4f}**")

                st.success("Recomendación: " + ("Alta probabilidad ✅" if final_score>=80 else "Baja/Media probabilidad ⚠️"))
        except Exception as e:
            st.error(f"Error evaluando: {e}")
