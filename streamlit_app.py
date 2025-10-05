# streamlit_app.py
import os
import json
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Trading Bot Dashboard", layout="wide")
st.title("📊 Trading Bot Dashboard")

st.success("✅ Streamlit cargó correctamente.")

# --- Lectura opcional del Google Sheet (solo si hay secretos) ---
def get_secret(name, default=None):
    # Streamlit Cloud -> st.secrets / local -> env
    try:
        return st.secrets.get(name, default)
    except Exception:
        return os.getenv(name, default)

SPREADSHEET_ID = get_secret("SPREADSHEET_ID")
GS_JSON_RAW = get_secret("GOOGLE_SHEETS_JSON")

if SPREADSHEET_ID and GS_JSON_RAW:
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        GS_JSON = json.loads(GS_JSON_RAW)
        creds = Credentials.from_service_account_info(
            GS_JSON, scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        gc = gspread.authorize(creds)
        ws = gc.open_by_key(SPREADSHEET_ID).sheet1
        rows = ws.get_all_records()
        df = pd.DataFrame(rows).tail(50)
        st.subheader("📄 Últimos 50 registros")
        if df.empty:
            st.info("No hay datos aún en la hoja.")
        else:
            st.dataframe(df, use_container_width=True, height=420)
    except Exception as e:
        st.warning(f"No se pudo leer Google Sheets (opcional): {e}")
else:
    st.info("Configura SPREADSHEET_ID y GOOGLE_SHEETS_JSON en **Secrets** si quieres ver la tabla aquí.")
