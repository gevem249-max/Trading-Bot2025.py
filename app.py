# ===============================
# Trading Bot Visual Dashboard
# Streamlit completo (con estado de mercado)
# ===============================

import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import time
import io
from datetime import datetime, time as dtime

# ===============================
# Función de Autorefresco
# ===============================
def auto_refresh_every(seconds: int, key: str = "auto_refresh_tick"):
    """
    Vuelve a ejecutar la app cada 'seconds' segundos sin usar experimental_rerun.
    """
    now = int(time.time())
    last = st.session_state.get(key, now)
    if key not in st.session_state:
        st.session_state[key] = now
    elif (now - last) >= seconds:
        st.session_state[key] = now
        st.rerun()

# ===============================
# Estado del mercado (NYSE)
# ===============================
def is_nyse_open(dt=None):
    if dt is None:
        dt = datetime.now()
    if dt.weekday() >= 5:  # sábado y domingo
        return False
    start = dtime(9,30)
    end   = dtime(17,0)
    return start <= dt.time() <= end

def estado_mercado():
    return "🟢 ABIERTO" if is_nyse_open() else "🔴 CERRADO"

# ===============================
# Configuración
# ===============================
st.set_page_config(
    page_title="Trading Bot Visual Dashboard",
    layout="wide",
    page_icon="📊"
)

st.title(f"📊 Trading Bot — Visual Dashboard ({estado_mercado()})")
st.caption("Panel visual de señales y reportes • Archivo único: Bot2025Real.xlsx")

# ===============================
# Cargar archivo
# ===============================
uploaded_file = st.file_uploader("📂 Sube el archivo Bot2025Real.xlsx generado por Colab", type="xlsx")

if uploaded_file is None:
    st.warning("Por favor sube el archivo **Bot2025Real.xlsx** generado por Colab.")
    st.stop()

# Leer todas las hojas del Excel
xls = pd.ExcelFile(uploaded_file)
signals = pd.read_excel(xls, sheet_name="signals")
pending = pd.read_excel(xls, sheet_name="pending")
performance = pd.read_excel(xls, sheet_name="performance")
log = pd.read_excel(xls, sheet_name="log")

# ===============================
# Autorefresco cada 60s
# ===============================
auto_refresh_every(60, key="refresh_dashboard")

# ===============================
# Pestañas
# ===============================
tab1, tab2, tab3, tab4 = st.tabs(["📈 Señales", "⏳ Pending", "📊 Performance", "📜 Log"])

# --- Tab1: Señales
with tab1:
    st.subheader("Últimas Señales (≥40)")
    if signals.empty:
        st.info("No hay señales registradas todavía.")
    else:
        signals["score"] = pd.to_numeric(signals["score"], errors="coerce").fillna(0)
        valid = signals[signals["score"] >= 40]
        if valid.empty:
            st.warning("No hay señales con score ≥ 40.")
        else:
            st.dataframe(valid.tail(20))
            # Gráfico de distribución
            fig, ax = plt.subplots()
            valid["score"].plot(kind="hist", bins=10, ax=ax, color="skyblue", edgecolor="black")
            ax.set_title("Distribución de Scores (≥40)")
            ax.set_xlabel("Score")
            st.pyplot(fig)

# --- Tab2: Pending
with tab2:
    st.subheader("⏳ Señales Pending (Pre/Confirmación)")
    if pending.empty:
        st.info("No hay señales pendientes.")
    else:
        st.dataframe(pending.tail(20))

# --- Tab3: Performance
with tab3:
    st.subheader("📊 Rendimiento")
    if performance.empty:
        st.info("No hay datos de rendimiento aún.")
    else:
        st.dataframe(performance.tail(20))
        # Accuracy simple
        perf_today = performance.copy()
        perf_today["accuracy"] = pd.to_numeric(perf_today["accuracy"], errors="coerce").fillna(0)
        avg_acc = round(perf_today["accuracy"].mean(), 2)
        st.metric("Promedio Accuracy", f"{avg_acc}%")

# --- Tab4: Log
with tab4:
    st.subheader("📜 Log de eventos")
    if log.empty:
        st.info("No hay eventos en el log.")
    else:
        st.dataframe(log.tail(50))

# ===============================
# Descargar Excel actualizado
# ===============================
st.subheader("💾 Guardar cambios")
output = io.BytesIO()
with pd.ExcelWriter(output, engine="openpyxl") as writer:
    signals.to_excel(writer, sheet_name="signals", index=False)
    pending.to_excel(writer, sheet_name="pending", index=False)
    performance.to_excel(writer, sheet_name="performance", index=False)
    log.to_excel(writer, sheet_name="log", index=False)

st.download_button(
    label="⬇️ Descargar Bot2025Real.xlsx actualizado",
    data=output.getvalue(),
    file_name="Bot2025Real.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
