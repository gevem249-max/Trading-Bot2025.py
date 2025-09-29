import io
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

# =========================
# UTILIDADES
# =========================
def now_nj():
    return datetime.now(pytz.timezone(TZ_NJ))

def fmt_nj(dt=None):
    if dt is None:
        dt = now_nj()
    return dt.strftime("%m/%d/%Y %I:%M:%S %p")

@st.cache_data(show_spinner=False)
def load_book_from_bytes(content: bytes) -> dict:
    try:
        xls = pd.ExcelFile(io.BytesIO(content))
        out = {}
        for name in ["signals","pending","performance","log","intuition"]:
            if name in xls.sheet_names:
                out[name] = pd.read_excel(xls, sheet_name=name)
        return out
    except Exception:
        return {}

# =========================
# UI STREAMLIT
# =========================
st.set_page_config(page_title="Trading Bot Dashboard", page_icon="📊", layout="wide")

st.title("📊 Trading Bot — Visual Dashboard")
st.caption("Panel visual de señales y reportes • Archivo único: Bot2025Real.xlsx")

# Sidebar
with st.sidebar:
    st.header("⚙️ Configuración")
    file = st.file_uploader("📥 Subir Bot2025Real.xlsx", type=["xlsx"])
    st.info("Sube el archivo Excel actualizado desde Colab")

if file is None:
    st.warning("Por favor sube el archivo Bot2025Real.xlsx generado por Colab.")
    st.stop()

# Cargar datos
book = load_book_from_bytes(file.read())
signals = book.get("signals", pd.DataFrame())
performance = book.get("performance", pd.DataFrame())
log = book.get("log", pd.DataFrame())

# =========================
# PANTALLA PRINCIPAL — SEÑALES
# =========================
st.subheader(f"📈 Señales recientes — Hora NJ: {fmt_nj()}")

if signals.empty:
    st.info("No hay señales registradas todavía.")
else:
    signals["score"] = pd.to_numeric(signals.get("score", pd.Series()), errors="coerce").fillna(0)
    signals["date"] = pd.to_datetime(signals.get("date", pd.Series()), errors="coerce")

    last = signals.tail(50)

    # Gráfico barras
    fig, ax = plt.subplots(figsize=(10,5))
    ax.bar(last.index.astype(str), last["score"], color="skyblue")
    ax.axhline(80, color="green", linestyle="--", label="Alta probabilidad (≥80)")
    ax.axhline(40, color="orange", linestyle="--", label="Mínimo aceptado (≥40)")
    ax.set_title("📊 Scores de las últimas señales")
    ax.set_ylabel("Score")
    ax.set_xlabel("Últimas señales")
    ax.legend()
    plt.xticks(rotation=45)

    st.pyplot(fig)

    # Tabla
    st.markdown("### 📋 Tabla de señales recientes")
    st.dataframe(
        last[["symbol","alias","tf","direction","score","entry","tp","sl","contracts","date","time","result"]],
        use_container_width=True,
        height=300
    )

# =========================
# RENDIMIENTO DIARIO — PERFORMANCE
# =========================
st.subheader("📊 Rendimiento diario")

if performance.empty:
    st.info("No hay datos de performance registrados.")
else:
    performance["date"] = pd.to_datetime(performance.get("date", pd.Series()), errors="coerce")

    today = now_nj().date()
    df_today = performance[performance["date"].dt.date == today]

    if df_today.empty:
        st.info("No hay operaciones registradas para hoy.")
    else:
        wins = pd.to_numeric(df_today["wins"], errors="coerce").fillna(0).sum()
        losses = pd.to_numeric(df_today["losses"], errors="coerce").fillna(0).sum()
        profit = pd.to_numeric(df_today["profit"], errors="coerce").fillna(0).sum()

        # Gráfico pastel
        fig2, ax2 = plt.subplots()
        ax2.pie(
            [wins, losses],
            labels=["Ganados","Perdidos"],
            autopct="%1.1f%%",
            startangle=90,
            colors=["#4CAF50","#F44336"]
        )
        ax2.set_title("📊 Distribución de resultados hoy")
        st.pyplot(fig2)

        # Tabla performance
        st.markdown("### 📋 Detalle de performance hoy")
        st.dataframe(
            df_today[["time","symbol","tf","trades","wins","losses","profit","accuracy"]],
            use_container_width=True,
            height=300
        )

# =========================
# LOG
# =========================
st.divider()
st.markdown("### 📜 Log de eventos")
if log.empty:
    st.info("Sin eventos registrados aún.")
else:
    st.dataframe(log.tail(100), use_container_width=True, height=200)
