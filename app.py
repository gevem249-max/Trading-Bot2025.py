import io
import os
import pandas as pd
import numpy as np
import pytz
import streamlit as st
import matplotlib.pyplot as plt
from datetime import datetime

# =========================
# CONFIG
# =========================
TZ_NJ = "America/New_York"
XLSX_NAME = "Bot2025Real.xlsx"

SCHEMAS = {
    "signals": ["symbol","alias","tf","direction","score","time","date","entry","tp","sl","expected_gain","contracts","stage","confirm_at","result"],
    "pending": ["symbol","alias","tf","direction","score","time","date","entry","tp","sl","confirm_at","notified_pre"],
    "performance": ["date","time","symbol","tf","trades","wins","losses","profit","accuracy"],
    "log": ["timestamp","event","details"],
    "intuition": ["timestamp","context","intuition_score","note","outcome"]
}

def now_nj():
    return datetime.now(pytz.timezone(TZ_NJ))

def fmt_nj(dt=None):
    if dt is None: dt = now_nj()
    return dt.strftime("%m/%d/%Y %I:%M:%S %p")

def create_blank_book() -> dict:
    return {sh: pd.DataFrame(columns=cols) for sh, cols in SCHEMAS.items()}

@st.cache_data(show_spinner=False)
def load_book_from_bytes(content: bytes) -> dict:
    try:
        xls = pd.ExcelFile(io.BytesIO(content))
        out = {}
        for sh in SCHEMAS.keys():
            if sh in xls.sheet_names:
                out[sh] = pd.read_excel(xls, sheet_name=sh)
            else:
                out[sh] = pd.DataFrame(columns=SCHEMAS[sh])
        return out
    except Exception:
        return create_blank_book()

def save_book_to_bytes(book: dict) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as wr:
        for sh, df in book.items():
            df.to_excel(wr, sheet_name=sh, index=False)
    buf.seek(0)
    return buf.read()

def append_log(book: dict, event: str, details: str=""):
    log = book["log"]
    log.loc[len(log)] = [fmt_nj(), event, details]

# =========================
# STREAMLIT APP
# =========================
st.set_page_config(page_title="📊 Trading Bot Dashboard", layout="wide")

st.title("📊 Trading Bot Dashboard")
st.caption("Flash, Autoevaluación, Heartbeat, Reporte Cierre • Archivo único: Bot2025Real.xlsx")

# Sidebar
with st.sidebar:
    st.header("⚙️ Controles")
    file = st.file_uploader("Sube tu Excel (Bot2025Real.xlsx)", type=["xlsx"], accept_multiple_files=False)
    st.info("Si no subes archivo, se usará uno en blanco.")

# Cargar libro
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
# Tabs principales
# =========================
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "⚡ Flash Report", "📝 Autoevaluación", "📉 Cierre", "⏱️ Heartbeat", "📬 Pre/Confirmación", "📊 Gráficos"
])

# ============== FLASH (MANUAL) ==============
with tab1:
    st.subheader("⚡ Flash Report (Manual)")
    df = book["signals"]
    if df.empty:
        st.info("No hay señales registradas.")
    else:
        today = now_nj().strftime("%Y-%m-%d")
        df_today = df[df["date"]==today].tail(10)
        st.dataframe(df_today, use_container_width=True)
        if st.button("✉️ Enviar Flash Report Manual"):
            append_log(book, "flash_manual", "Flash Report enviado manual")
            st.success("⚡ Flash Report manual generado.")

# ============== AUTOEVALUACIÓN (MANUAL) ==============
with tab2:
    st.subheader("📝 Autoevaluación (Manual)")
    today = now_nj().strftime("%Y-%m-%d")
    df = book["signals"]
    resumen = df[df["date"]==today] if not df.empty else pd.DataFrame()
    if resumen.empty:
        st.info("Sin señales hoy.")
    else:
        st.write(f"Señales de hoy: {len(resumen)}")
        st.dataframe(resumen[["symbol","tf","direction","score","result"]])
    if st.button("✉️ Enviar Autoevaluación Manual"):
        append_log(book, "autoeval_manual", "Autoevaluación enviada manual")
        st.success("📝 Autoevaluación manual generada.")

# ============== CIERRE (MANUAL) ==============
with tab3:
    st.subheader("📉 Reporte de Cierre (Manual)")
    df = book["performance"]
    if df.empty:
        st.info("Sin datos de performance.")
    else:
        st.dataframe(df.tail(10))
    if st.button("✉️ Enviar Reporte Cierre Manual"):
        append_log(book, "cierre_manual", "Cierre enviado manual")
        st.success("📉 Reporte Cierre manual generado.")

# ============== HEARTBEAT (MANUAL) ==============
with tab4:
    st.subheader("⏱️ Heartbeat (Manual)")
    df = book["signals"]
    if df.empty:
        st.info("Sin señales aún.")
    else:
        last = df.tail(20)
        count = len(last)
        wins = (last["result"].str.lower()=="win").sum()
        losses = (last["result"].str.lower()=="loss").sum()
        st.write(f"Últimas 20 señales: {count} | Ganadas: {wins} | Perdidas: {losses}")
        st.dataframe(last)
    if st.button("✉️ Enviar Heartbeat Manual"):
        append_log(book, "heartbeat_manual", "Heartbeat enviado manual")
        st.success("⏱️ Heartbeat manual generado.")

# ============== PRE/CONFIRMACIÓN ==============
with tab5:
    st.subheader("📬 Preaviso / Confirmación")
    df = book["pending"]
    if df.empty:
        st.info("No hay pendientes.")
    else:
        st.dataframe(df.tail(10))
    if st.button("Procesar Pre/Confirmaciones"):
        append_log(book, "preconfirm", "Procesadas señales pendientes")
        st.success("📬 Pre/Confirmaciones procesadas.")

# ============== GRÁFICOS ==============
with tab6:
    st.subheader("📊 Evolución de Señales")
    if not book["signals"].empty:
        df_plot = book["signals"].copy()
        df_plot["date"] = pd.to_datetime(df_plot["date"], errors="coerce")
        df_plot["result"] = df_plot["result"].fillna("pendiente").str.lower()
        df_count = df_plot.groupby(["date","result"]).size().unstack(fill_value=0)

        fig, ax = plt.subplots(figsize=(8,4))
        df_count.plot(kind="bar", stacked=True, ax=ax)
        ax.set_title("Evolución de señales por resultado")
        ax.set_xlabel("Fecha")
        ax.set_ylabel("Cantidad")
        st.pyplot(fig)
    else:
        st.info("No hay datos de señales para graficar.")

# =========================
# Guardar Excel
# =========================
st.divider()
bytes_xlsx = save_book_to_bytes(book)
st.download_button(
    "⬇️ Descargar Bot2025Real.xlsx actualizado",
    data=bytes_xlsx,
    file_name="Bot2025Real.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

# =========================
# Log
# =========================
with st.expander("📜 Log de eventos"):
    st.dataframe(book["log"].tail(50), use_container_width=True, height=250)
