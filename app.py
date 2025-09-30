import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
from streamlit_autorefresh import st_autorefresh

# =========================
# CONFIGURACIÓN INICIAL
# =========================
st.set_page_config(page_title="Trading Bot Dashboard", page_icon="📈", layout="wide")
st.title("📈 Trading Bot — Visual Dashboard")

# 🔄 Auto-refresco cada 60s
st_autorefresh(interval=60 * 1000, key="refresh")

# =========================
# SUBIDA DE ARCHIVO
# =========================
uploaded_file = st.file_uploader("📂 Sube tu archivo Bot2025Real.xlsx", type=["xlsx"])

if uploaded_file is not None:
    try:
        # Leer todas las hojas
        book = pd.read_excel(uploaded_file, sheet_name=None)

        st.success("✅ Archivo cargado correctamente.")
        st.write("Hojas disponibles:", list(book.keys()))

        # =========================
        # VISUALIZACIÓN DE SEÑALES
        # =========================
        if "signals" in book:
            df_signals = book["signals"]

            if not df_signals.empty:
                st.subheader("📊 Señales registradas")

                # Mostrar últimas 20
                st.dataframe(df_signals.tail(20), use_container_width=True)

                # ====== Gráfico de señales por Score ======
                fig, ax = plt.subplots()
                df_signals["score"].dropna().astype(float).plot(
                    kind="hist", bins=20, ax=ax, alpha=0.7
                )
                ax.set_title("Distribución de Scores de Señales")
                ax.set_xlabel("Score")
                ax.set_ylabel("Cantidad")
                st.pyplot(fig)
            else:
                st.info("No hay señales registradas en la hoja `signals`.")
        else:
            st.warning("⚠️ La hoja `signals` no está en el archivo.")

        # =========================
        # VISUALIZACIÓN DE PERFORMANCE
        # =========================
        if "performance" in book:
            df_perf = book["performance"]

            if not df_perf.empty:
                st.subheader("📈 Rendimiento acumulado")
                st.dataframe(df_perf.tail(20), use_container_width=True)

                # Gráfico de profit acumulado
                if "profit" in df_perf.columns:
                    fig2, ax2 = plt.subplots()
                    df_perf["profit"].dropna().astype(float).cumsum().plot(ax=ax2)
                    ax2.set_title("Evolución de Profit acumulado")
                    ax2.set_xlabel("Operaciones")
                    ax2.set_ylabel("Profit acumulado")
                    st.pyplot(fig2)
            else:
                st.info("No hay datos de rendimiento en la hoja `performance`.")
        else:
            st.warning("⚠️ La hoja `performance` no está en el archivo.")

        # =========================
        # LOGS
        # =========================
        if "log" in book:
            df_log = book["log"]

            if not df_log.empty:
                st.subheader("📜 Últimos eventos")
                st.dataframe(df_log.tail(20), use_container_width=True, height=300)
            else:
                st.info("El log está vacío.")
        else:
            st.warning("⚠️ La hoja `log` no está en el archivo.")

    except Exception as e:
        st.error(f"❌ Error al leer el Excel: {e}")

else:
    st.warning("Por favor sube el archivo **Bot2025Real.xlsx** generado por Colab.")
