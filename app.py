import streamlit as st
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import smtplib, ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# ==============================
# 📂 CONFIG
# ==============================
GMAIL_USER = st.secrets["GMAIL_USER"]        # tu correo Gmail
GMAIL_PASS = st.secrets["GMAIL_APP_PASS"]    # App Password de Gmail
SPREADSHEET_ID = st.secrets["SPREADSHEET_ID"]  # ID de Google Sheets
SERVICE_ACCOUNT_JSON = st.secrets["GCP_SERVICE_ACCOUNT"]  # JSON en secrets

# ==============================
# ⏰ UTILIDADES
# ==============================
def hora_local():
    return datetime.now().strftime("%m/%d/%Y %I:%M:%S %p")

# ==============================
# 📊 GOOGLE SHEETS
# ==============================
service_account_info = json.loads(SERVICE_ACCOUNT_JSON)

scope = ["https://spreadsheets.google.com/feeds", 
         "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_dict(service_account_info, scope)
client = gspread.authorize(creds)

sheet = client.open_by_key(SPREADSHEET_ID)
ws_log = sheet.worksheet("log")

def log(event, details=""):
    ws_log.append_row([hora_local(), event, details])

# ==============================
# 📧 CORREO
# ==============================
def send_email(subject, body, to_email):
    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = GMAIL_USER
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "html"))

        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
            server.login(GMAIL_USER, GMAIL_PASS)
            server.sendmail(GMAIL_USER, [to_email], msg.as_string())

        log("email_sent", f"{subject} -> {to_email}")
        return True
    except Exception as e:
        log("email_error", str(e))
        return False

# ==============================
# 🚀 STREAMLIT UI
# ==============================
st.title("🚀 Trading Bot 2025")
st.success("✅ Conectado a Google Sheets correctamente")

if st.button("Enviar correo de prueba"):
    ok = send_email("📈 Bot Activo", f"<p>El bot fue activado a las {hora_local()}</p>", GMAIL_USER)
    if ok:
        st.success("✅ Correo enviado con éxito")
    else:
        st.error("❌ Error al enviar correo")

if st.button("Ver últimos logs"):
    logs = ws_log.get_all_records()
    st.dataframe(logs[-10:] if logs else [])
