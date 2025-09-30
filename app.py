import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import io, time
from datetime import datetime, time as dtime

st.set_page_config(page_title="Trading Bot — Visual Dashboard", layout="wide")

# =========================
# Funciones auxiliares
# =========================
def is_nyse_open(dt=None):
    if dt is None:
        dt = datetime.now()
    if dt.weekday() >= 5:
        return False
    start = dtime(9, 30)
    end = dtime(17, 0)
    return start <= dt.time() <= end

def market_status():
    return "🟢 ABIERTO" if is_nyse_open() else "🔴 CERRADO"

def load_excel(uploaded_file):
    try:
        return pd.read_excel(uploaded_file, sheet_name=None)
    except Exception as e:
        st.error(f"Error al leer Excel: {e}")
        return None

# =========================
# Cabecera
# =========================
st.title("📊 Trading Bot — Visual Dashboard")
st.caption("Panel visual de señales y reportes • Archivo único: Bot2025Real.xlsx")

st.markdown(f"**Estado del mercado NYSE:** {market_status()}")

# =========================
# Subir archivo
# =========================
uploaded_file = st.file_uploader("📂 Sube tu archivo Bot2025Real.xlsx", type=["xlsx"])

if uploaded_file:
    data = load_excel(uploaded_file)

    if data:
        # Mostrar hojas disponibles
        st.sidebar.subheader("📑 Hojas disponibles")
        for sheet in data.keys():
            st.sidebar.write(f"- {sheet}")

        # =========================
        # Señales (hoja signals)
        # =========================
        if "signals" in data:
            df
