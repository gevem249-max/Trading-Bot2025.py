import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import smtplib
from email.mime.text import MIMEText
import pandas as pd

# ==========================
# 1. Configuración inicial
# ==========================

# Gmail credentials desde secrets
GMAIL_USER = st.secrets["GMAIL_USER"]
GMAIL_PASS = st.secrets["GMAIL_PASS"]

# Spreadsheet ID desde secrets
SPREADSHEET_ID = st.secrets["SPREADSHEET_ID"]

# Service account desde secrets
service_account_info = dict(st.secrets["service_account"])
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]
creds = ServiceAccountCredentials.from_json_keyfile_dict(service_account_info, scope)
client = gspread.authorize(creds)

# ==========================
# 2. Google Sheets
# ==========================

try:
    sheet = client.open_by_key(SPREADSHEET_ID).sheet1
    data = sheet.get_all_records()
    df = pd.DataFrame(data)
    st.success("✅ Conectado a Google Sheets correctamente")
except Exception as e:
    st.error(f"❌ Error conectando a Google Sheets: {e}")
    df = pd.DataFrame()

# ==========================
# 3. UI Streamlit
# ==========================

st.title("🚀 Trading Bot 2025")
st.write("Este bot está conectado a Google Sheets y Gmail vía secrets.")

if not df.empty:
    st.subheader("📊 Primeras filas de la hoja:")
    st.write(df.head())
else:
    st.warning("⚠️ No hay datos cargados en la hoja.")

# ==========================
# 4. Envío de correo (prueba)
# ==========================

def enviar_correo(destinatario, asunto, mensaje):
    try:
        msg = MIMEText(mensaje)
        msg["Subject"] = asunto
        msg["From"] = GMAIL_USER
        msg["To"] = destinatario

        server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
        server.login(GMAIL_USER, GMAIL_PASS)
        server.sendmail(GMAIL_USER, [destinatario], msg.as_string())
        server.quit()
        return True
    except Exception as e:
        st.error(f"❌ Error enviando correo: {e}")
        return False

st.subheader("📧 Enviar un correo de prueba")
email = st.text_input("Correo destino:", "")
if st.button("Enviar prueba"):
    if email:
        ok = enviar_correo(email, "Prueba Trading Bot 2025", "✅ El bot está funcionando y conectado correctamente.")
        if ok:
            st.success("Correo enviado con éxito.")
    else:
        st.warning("⚠️ Ingresa un correo válido.")
