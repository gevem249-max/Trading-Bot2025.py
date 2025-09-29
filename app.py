import io
import os
import smtplib
import ssl
import time
from datetime import datetime, timedelta, time as dtime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import numpy as np
import pandas as pd
import pytz
import streamlit as st
import matplotlib.pyplot as plt

# =========================
# CONFIG INICIAL
# =========================
TZ_NJ = "America/New_York"
TZ_LON = "Europe/London"

DEFAULT_ASSETS = ["MES", "DKNG"]
SCORE_MIN = 40
PROB_HIGH = 80
PROB_MID_LOW = (40, 79)

# =========================
# UTILIDADES
# =========================
def now_nj():
    return datetime.now(pytz.timezone(TZ_NJ))

def fmt_nj(dt=None):
    if dt is None:
        dt = now_nj()
    return dt.strftime("%m/%d/%Y %I:%M:%S %p")

def ensure_columns(df: pd.DataFrame, cols: list):
    for c in cols:
        if c not in df.columns:
            df[c] = np.nan
    return df[cols]

def create_blank_book() -> dict:
    return {
        "signals": pd.DataFrame(columns=["symbol","alias","tf","direction","score","time","date","entry","tp","sl","expected_gain","contracts","stage","confirm_at","result"]),
        "pending": pd.DataFrame(columns=["symbol","alias","tf","direction","score","time","date","entry","tp","sl","confirm_at","notified_pre"]),
        "performance": pd.DataFrame(columns=["date","time","symbol","tf","trades","wins","losses","profit","accuracy"]),
        "log": pd.DataFrame(columns=["timestamp","event","details"]),
    }

def is_market_open_ny(dt_nj=None):
    if dt_nj is None:
        dt_nj = now_nj()
    wd = dt_nj.weekday()
    if wd == 5:  # Saturday
        return False
    if wd == 6:  # Sunday
        return dt_nj.time() >= dtime(18, 0)
    return True

def is_market_regular_nyse(dt_nj=None):
    if dt_nj is None:
        dt_nj = now_nj()
    t = dt_nj.time()
    return (t >= dtime(9,30)) and (t < dtime(16,0))

def is_market_open_london(dt_nj=None):
    if dt_nj is None:
        dt_nj = now_nj()
    london = dt_nj.astimezone(pytz.timezone(TZ_LON))
    t = london.time()
    wd = london.weekday()
    if wd >= 5:
        return False
    return (t >= dtime(8,0)) and (t < dtime(16,30))

def badge_open(is_open: bool) -> str:
    return "🟢 Abierto" if is_open else "🔴 Cerrado"

# =========================
# CARGA / GUARDA EXCEL
# =========================
@st.cache_data(show_spinner=False)
def load_book_from_bytes(content: bytes) -> dict:
    try:
        xls = pd.ExcelFile(io.BytesIO(content))
        out = {}
        for name in ["signals","pending","performance","log"]:
            if name in xls.sheet_names:
                out[name] = pd.read_excel(xls, sheet_name=name)
        base = create_blank_book()
        for k,v in base.items():
            if k not in out:
                out[k] = v.copy()
        return out
    except Exception:
        return create_blank_book()

def save_book_to_bytes(book: dict) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        for sheet, df in book.items():
            ensure_columns(df, list(df.columns)).to_excel(writer, sheet_name=sheet, index=False)
    buf.seek(0)
    return buf.read()

# =========================
# DASHBOARD STREAMLIT
# =========================
st.set_page_config(page_title="Trading Bot Dashboard", page_icon="📈", layout="wide")

st.title("📈 Trading Bot — Dashboard Visual")
st.caption("Refresco automático cada 30s • Archivo único Bot2025Real.xlsx")

# Sidebar
with st.sidebar:
    st.header("⚙️ Controles")
    activos = st.multiselect("Activos prioritarios", DEFAULT_ASSETS, default=DEFAULT_ASSETS)
    score_min = st.slider("Score mínimo (filtrado señales)", 0, 100, SCORE_MIN, 1)
    st.write(f"Mercado NY: {badge_open(is_market_open_ny())} (Regular: {'🟢' if is_market_regular_nyse() else '🔴'})")
    st.write(f"Mercado Londres: {badge_open(is_market_open_london())}")
    st.divider()
    st.write("📥 Sube tu Excel (deja vacío para usar plantilla):")
    file = st.file_uploader("Bot2025Real.xlsx", type=["xlsx"], accept_multiple_files=False)

# Cargar Excel
if "book" not in st.session_state:
    if file is not None:
        book = load_book_from_bytes(file.read())
    else:
        book = create_blank_book()
    st.session_state["book"] = book
else:
    if file is not None and file.size > 0:
        st.session_state["book"] = load_book_from_bytes(file.read())

book = st.session_state["book"]

# =========================
# GRÁFICO PRINCIPAL
# =========================
st.subheader("📊 Señales — Gráfico de distribución")
df = book["signals"].copy()
if not df.empty:
    try:
        df["score"] = pd.to_numeric(df["score"], errors="coerce").fillna(0)
    except:
        df["score"] = 0

    counts = {
        "Fuertes (≥80)": (df["score"] >= 80).sum(),
        "Medias (60–79)": ((df["score"] >= 60) & (df["score"] < 80)).sum(),
        "Básicas (40–59)": ((df["score"] >= 40) & (df["score"] < 60)).sum(),
        "Débiles (<40)": (df["score"] < 40).sum()
    }

    fig, ax = plt.subplots()
    ax.bar(counts.keys(), counts.values())
    ax.set_title("Distribución de Señales")
    ax.set_ylabel("Cantidad")
    st.pyplot(fig)

    st.markdown(f"**Última actualización:** {fmt_nj()}")
else:
    st.info("No hay señales en el Excel.")

# =========================
# PESTAÑAS
# =========================
tab1, tab2, tab3, tab4 = st.tabs(["⚡ Flash Report", "📝 Autoevaluación", "📉 Cierre", "⏱️ Heartbeat"])

with tab1:
    st.subheader("⚡ Flash Report (Manual)")
    st.write("En esta pestaña se mostrarán las últimas señales válidas (≥40).")

with tab2:
    st.subheader("📝 Autoevaluación (Manual)")
    st.write("Narrativa automática basada en señales y contexto.")

with tab3:
    st.subheader("📉 Reporte de Cierre")
    st.write("Resumen de trades, ganancias/pérdidas y accuracy al final del día.")

with tab4:
    st.subheader("⏱️ Heartbeat")
    st.write("Mini reporte cada 10 minutos (sólo si el mercado está abierto).")

# =========================
# DESCARGA EXCEL
# =========================
st.divider()
st.markdown("### 💾 Guardar cambios")
bytes_xlsx = save_book_to_bytes(book)
st.download_button(
    "⬇️ Descargar Bot2025Real.xlsx",
    data=bytes_xlsx,
    file_name="Bot2025Real.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

# =========================
# REFRESCO AUTOMÁTICO
# =========================
st_autorefresh = st.experimental_rerun
st_autorefresh = st.experimental_memo
st_autorefresh
