import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import os, json
from bot import ejecutar_bot

# ------------------------------------------------------
# 1. Conexión a Google Sheets
# ------------------------------------------------------
def conectar_sheets():
    google_json = os.getenv("GOOGLE_SHEETS_JSON")
    if not google_json:
        st.error("No se encontró GOOGLE_SHEETS_JSON en Secrets")
        return None
    creds_info = json.loads(google_json)
    scope = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(creds_info, scopes=scope)
    cliente = gspread.authorize(creds)
    sheet = cliente.open("SeñalesBot").sheet1
    return sheet

# ------------------------------------------------------
# 2. Cargar historial desde Sheets
# ------------------------------------------------------
def cargar_historial():
    sheet = conectar_sheets()
    if not sheet:
        return pd.DataFrame(columns=["Fecha","Asunto","Tipo","Resultado"])
    datos = sheet.get_all_records()
    return pd.DataFrame(datos)

# ------------------------------------------------------
# 3. Dashboard Streamlit
# ------------------------------------------------------
st.set_page_config(page_title="Trading Bot Panel", layout="wide")
st.title("📊 Panel de Señales - Trading Bot 2025")

# Botón para ejecutar el bot y traer nuevas alertas
if st.button("🔄 Actualizar Alertas (leer correos)"):
    resultado = ejecutar_bot()
    st.success(resultado)

# Cargar historial desde Sheets
df = cargar_historial()

if not df.empty:
    # Métricas
    total = len(df)
    wins = (df["Resultado"] == "Win").sum()
    loss = (df["Resultado"] == "Loss").sum()
    pendientes = (df["Resultado"] == "Pendiente").sum()
    efectividad = (wins / total * 100) if total > 0 else 0

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Señales", total)
    col2.metric("Ganadas (Win)", wins)
    col3.metric("Perdidas (Loss)", loss)
    col4.metric("Efectividad", f"{efectividad:.1f}%")

    st.subheader("📜 Historial de Señales")
    st.dataframe(df)

    # Gráfico circular Win/Loss
    import matplotlib.pyplot as plt
    resultados = df["Resultado"].value_counts()
    fig, ax = plt.subplots()
    resultados.plot.pie(autopct="%1.1f%%", ax=ax)
    ax.set_ylabel("")
    st.pyplot(fig)

else:
    st.warning("No hay datos en el historial todavía.")
