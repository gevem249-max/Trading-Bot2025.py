# =====================================
# 📊 Trading Bot — Visual Dashboard
# Versión corregida (sin streamlit_autorefresh)
# =====================================

import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import time
from datetime import datetime, time as dtime

# -----------------------------
# 🔹 Funciones auxiliares
# -----------------------------
def is_nyse_open():
    """Determina si el mercado NYSE está abierto (9:30–17:00 ET, Lun–Vie)."""
    now = datetime.now()
    if now.weekday() >= 5:  # sábado(5) o domingo(6)
        return False
    start = dtime(9, 30)
    end = dtime(17, 0)
    return start <= now.time() <= end

def load_data(uploaded_file):
    try:
        df = pd.read_excel(uploaded_file, sheet_name="signals")
        df["score"] = pd.to_numeric(df["score"], errors="coerce").fillna(0)
        return df
    except Exception:
        return pd.DataFrame()

# -----------------------------
# 🔹 Configuración de la página
# -----------------------------
st.set_page_config(page_title="Trading Bot Dashboard", layout="wide")

# -----------------------------
# 🔹 Estado del mercado
# -----------------------------
estado = "🟢 ABIERTO" if is_nyse_open() else "🔴 CERRADO"
st.title("📈 Trading Bot — Visual Dashboard")
st.subheader(f"Estado del mercado NYSE: {estado}")

# -----------------------------
# 🔹 Subida de archivo
# -----------------------------
uploaded_file = st.file_uploader("📂 Sube tu archivo Bot2025Real.xlsx", type=["xlsx"])

if uploaded_file:
    df = load_data(uploaded_file)

    if not df.empty:
        # Filtrar señales válidas
        valid = df[df["score"] >= 40].copy()

        st.markdown("### 📊 Señales válidas (score ≥ 40)")
        st.dataframe(valid.tail(20))  # últimas 20 señales

        # -----------------------------
        # 🔹 Gráfico de distribución
        # -----------------------------
        st.markdown("### 📈 Distribución de señales por score")

        fig, ax = plt.subplots()
        valid["score"].plot(kind="hist", bins=20, ax=ax, color="skyblue", edgecolor="black")
        ax.set_title("Distribución de Score de Señales")
        ax.set_xlabel("Score")
        ax.set_ylabel("Frecuencia")
        st.pyplot(fig)

        # Guardar cambios (botón manual)
        if st.button("💾 Guardar cambios"):
            valid.to_excel("Bot2025Real.xlsx", index=False)
            st.success("✅ Archivo actualizado correctamente.")

    else:
        st.warning("⚠️ No se pudieron leer señales en el archivo.")
else:
    st.info("Por favor sube el archivo Bot2025Real.xlsx generado por Colab.")

# -----------------------------
# 🔹 Refresco automático nativo
# -----------------------------
placeholder = st.empty()
if "last_refresh" not in st.session_state:
    st.session_state.last_refresh = time.time()

# Cada 60 segundos refresca
if time.time() - st.session_state.last_refresh > 60:
    st.session_state.last_refresh = time.time()
    st.experimental_rerun()
