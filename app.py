# ========================================
# 📊 Trading Bot — Visual Dashboard (Streamlit)
# ========================================

import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import os

st.set_page_config(page_title="Trading Bot Dashboard", layout="wide")

# --- Título ---
st.title("📊 Trading Bot — Visual Dashboard")
st.write("Panel visual de señales y reportes • Archivo único: **Bot2025Real.xlsx**")

# --- Subida del archivo ---
uploaded_file = st.file_uploader("📂 Sube el archivo Bot2025Real.xlsx generado por Colab", type=["xlsx"])

if uploaded_file is None:
    st.warning("Por favor sube el archivo **Bot2025Real.xlsx** generado por Colab.")
    st.stop()

# --- Leer hojas ---
try:
    signals = pd.read_excel(uploaded_file, sheet_name="signals")
    performance = pd.read_excel(uploaded_file, sheet_name="performance")
    log = pd.read_excel(uploaded_file, sheet_name="log")
except Exception as e:
    st.error(f"Error al leer el archivo: {e}")
    st.stop()

# ========================================
# 📊 Panel de Señales
# ========================================
st.header("📊 Señales recientes")

if signals.empty:
    st.info("No hay señales registradas aún.")
else:
    # Mostrar últimas 20
    st.subheader("📋 Últimas 20 señales")
    st.dataframe(signals.tail(20))

    # Histograma de scores
    st.subheader("📊 Distribución de scores")
    fig, ax = plt.subplots(figsize=(6,4))
    signals["score"].dropna().astype(float).hist(bins=20, ax=ax, color="skyblue", edgecolor="black")
    ax.set_title("Distribución de Scores")
    ax.set_xlabel("Score")
    ax.set_ylabel("Frecuencia")
    st.pyplot(fig)

# ========================================
# 📈 Panel de Performance
# ========================================
st.header("📈 Performance acumulada")

if performance.empty:
    st.info("No hay datos de performance aún.")
else:
    perf = performance.copy()
    perf["profit"] = pd.to_numeric(perf["profit"], errors="coerce").fillna(0)
    perf["cumulative_profit"] = perf["profit"].cumsum()

    fig, ax = plt.subplots(figsize=(8,4))
    ax.plot(perf["cumulative_profit"], marker="o", linestyle="-", color="green")
    ax.set_title("Curva de Profit Acumulado")
    ax.set_xlabel("Operaciones")
    ax.set_ylabel("Profit acumulado")
    st.pyplot(fig)

# ========================================
# 📜 Log de Eventos
# ========================================
st.header("📜 Log de eventos")

if log.empty:
    st.info("No hay eventos registrados aún.")
else:
    st.dataframe(log.tail(30))  # Últimos 30 eventos

st.success("✅ Dashboard cargado correctamente")
