# app.py
import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, time as dtime

st.set_page_config(page_title="Trading Bot Dashboard", layout="wide")

# ==========================
# Funciones auxiliares
# ==========================
def is_nyse_open(dt=None):
    """NYSE: 9:30–17:00 ET (Lun–Vie)"""
    if dt is None:
        dt = datetime.utcnow()  # simplificado, puedes ajustar a tz NY
    if dt.weekday() >= 5:  # 5=Sat, 6=Sun
        return False
    start, end = dtime(14, 30), dtime(21, 0)  # UTC ≈ 9:30–17:00 ET
    t = dt.time()
    return start <= t <= end

def plot_signals(df):
    """Generar gráfico de señales"""
    fig, ax = plt.subplots(figsize=(7,3))
    df["score"].plot(kind="bar", ax=ax, color="skyblue", edgecolor="black")
    ax.set_title("Distribución de Scores (≥40)")
    ax.set_xlabel("Señales")
    ax.set_ylabel("Score")
    st.pyplot(fig)

# ==========================
# Interfaz principal
# ==========================
st.title("📊 Trading Bot — Visual Dashboard")

estado = "🟢 ABIERTO" if is_nyse_open() else "🔴 CERRADO"
st.markdown(f"**Estado del mercado NYSE:** {estado}")

uploaded_file = st.file_uploader("📂 Sube tu archivo Bot2025Real.xlsx", type="xlsx")

if uploaded_file is not None:
    try:
        # Leer todo el archivo Excel
        data = pd.read_excel(uploaded_file, sheet_name=None)
        st.success("✅ Archivo cargado correctamente")

        # Crear pestañas
        tab1, tab2, tab3 = st.tabs(["⚡ Señales", "📜 Log", "📈 Performance"])

        # --- TAB 1: Señales ---
        with tab1:
            if "signals" in data:
                st.subheader("⚡ Señales válidas (score ≥ 40)")
                df = data["signals"].copy()

                if not df.empty:
                    df_valid = df[pd.to_numeric(df["score"], errors="coerce") >= 40]
                    st.dataframe(df_valid)

                    if not df_valid.empty:
                        plot_signals(df_valid)
                    else:
                        st.info("No hay señales con score ≥ 40.")
                else:
                    st.warning("La hoja 'signals' está vacía.")
            else:
                st.error("❌ No existe la hoja 'signals' en el archivo.")

        # --- TAB 2: Log ---
        with tab2:
            if "log" in data:
                st.subheader("📜 Log de eventos")
                st.dataframe(data["log"].tail(30))
            else:
                st.error("❌ No existe la hoja 'log' en el archivo.")

        # --- TAB 3: Performance ---
        with tab3:
            if "performance" in data:
                st.subheader("📈 Rendimiento")
                st.dataframe(data["performance"].tail(30))
            else:
                st.error("❌ No existe la hoja 'performance' en el archivo.")

    except Exception as e:
        st.error(f"⚠️ Error leyendo archivo: {e}")
else:
    st.warning("Por favor sube el archivo Bot2025Real.xlsx generado por Colab.")
