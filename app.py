import os
import json
import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import matplotlib.pyplot as plt

# ==============================
# Conexión con Google Sheets
# ==============================
def conectar_sheets():
    google_json = os.getenv("GOOGLE_SHEETS_JSON")  # Aquí va tu secret en GitHub
    creds_info = json.loads(google_json)
    creds = Credentials.from_service_account_info(
        creds_info,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    client = gspread.authorize(creds)
    spreadsheet_id = os.getenv("SPREADSHEET_ID")  # Aquí va tu ID de hoja
    sheet = client.open_by_key(spreadsheet_id).sheet1
    return sheet

def cargar_historial():
    sheet = conectar_sheets()
    data = sheet.get_all_records()
    df = pd.DataFrame(data)
    return df

# ==============================
# Interfaz Streamlit
# ==============================
st.set_page_config(page_title="📊 Panel de Señales - Trading Bot 2025")

st.title("📊 Panel de Señales - Trading Bot 2025")

try:
    df = cargar_historial()

    if df.empty:
        st.warning("⚠️ No hay señales registradas aún en la hoja.")
    else:
        # Mostrar tabla
        st.subheader("📋 Historial de Señales")
        st.dataframe(df)

        # Conteo Win/Loss
        if "win_loss" in df.columns:
            conteo = df["win_loss"].value_counts()

            # Gráfico
            fig, ax = plt.subplots()
            conteo.plot(kind="bar", ax=ax)
            ax.set_title("Win vs Loss")
            ax.set_ylabel("Cantidad")
            st.pyplot(fig)

except Exception as e:
    st.error(f"❌ Error al conectar con Google Sheets: {e}")
