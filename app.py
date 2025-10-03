import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, time as dtime, timedelta
import matplotlib.pyplot as plt

# ==============================
# 🔑 Autenticación Google Sheets
# ==============================
SERVICE_ACCOUNT_JSON = st.secrets["service_account_json"]["json"]
service_account_info = json.loads(SERVICE_ACCOUNT_JSON)

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_dict(service_account_info, scope)
client = gspread.authorize(creds)

# Tu hoja de Google Sheets
SPREADSHEET_ID = "1yTd7l9NYvruWPJ4rgNSHQPsqE4o22F0_lvvBWhD1LbM"
sheet = client.open_by_key(SPREADSHEET_ID)

# ==============================
# ⏰ Utilidades de hora
# ==============================
def now_nj():
    return datetime.now()  # NJ ya es tu hora local en el servidor

def fmt_hora():
    return now_nj().strftime("%m/%d/%Y %I:%M:%S %p")

def is_nyse_open(dt=None):
    if dt is None:
        dt = now_nj()
    if dt.weekday() >= 5:
        return False
    return dtime(9,30) <= dt.time() <= dtime(16,0)

def is_mes_open(dt=None):
    if dt is None:
        dt = now_nj()
    wd = dt.weekday()
    if wd == 5:
        return False
    if wd == 6:
        return dt.time() >= dtime(18,0)
    return True

def is_lse_open(dt=None):
    if dt is None:
        dt = now_nj()
    london = dt + timedelta(hours=5)  # NJ +5 aprox Londres
    return london.weekday() < 5 and dtime(8,0) <= london.time() <= dtime(16,30)

# ==============================
# 📊 Dashboard Streamlit
# ==============================
st.set_page_config(page_title="Trading Bot Dashboard", page_icon="📈", layout="wide")
st.title("📈 Trading Bot — Dashboard")
st.caption(f"Última actualización: {fmt_hora()}")

# Tabs
tab1, tab2, tab3 = st.tabs(["📊 Señales", "📉 Performance", "⚙️ Control"])

# ---------------- TAB 1 ----------------
with tab1:
    st.subheader("📊 Señales recientes")

    try:
        ws_signals = sheet.worksheet("signals")
        data = ws_signals.get_all_records()
        df_signals = pd.DataFrame(data)
        if df_signals.empty:
            st.info("No hay señales registradas aún.")
        else:
            st.dataframe(df_signals.tail(20), use_container_width=True)

            # Gráfico simple: cantidad por dirección
            fig, ax = plt.subplots()
            df_signals["direction"].value_counts().plot(kind="bar", ax=ax)
            ax.set_title("Direcciones de Señales")
            st.pyplot(fig)

    except Exception as e:
        st.error(f"Error cargando señales: {e}")

# ---------------- TAB 2 ----------------
with tab2:
    st.subheader("📉 Rendimiento acumulado")
    try:
        ws_perf = sheet.worksheet("performance")
        data_perf = ws_perf.get_all_records()
        df_perf = pd.DataFrame(data_perf)

        if df_perf.empty:
            st.info("No hay datos de performance aún.")
        else:
            st.dataframe(df_perf.tail(20), use_container_width=True)

            # Accuracy acumulado
            df_perf["accuracy"] = pd.to_numeric(df_perf.get("accuracy", pd.Series()), errors="coerce")
            acc = df_perf["accuracy"].mean()
            st.metric("📈 Accuracy Promedio", f"{acc:.2f} %")
    except Exception as e:
        st.error(f"Error cargando performance: {e}")

# ---------------- TAB 3 ----------------
with tab3:
    st.subheader("⚙️ Control manual")

    colA, colB = st.columns(2)
    with colA:
        if st.button("📨 Enviar notificación de prueba"):
            st.success("✅ Notificación enviada (simulada).")

    with colB:
        st.markdown(f"""
        **Estado de mercados ahora:**
        - NYSE: {"🟢 Abierto" if is_nyse_open() else "🔴 Cerrado"}
        - Futuros (MES): {"🟢 Abierto" if is_mes_open() else "🔴 Cerrado"}
        - Londres: {"🟢 Abierto" if is_lse_open() else "🔴 Cerrado"}
        """)

# ---------------- FOOTER ----------------
st.divider()
st.caption("✅ Conectado a Google Sheets — Bot listo para operar")
