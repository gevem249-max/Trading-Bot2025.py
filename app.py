import os
import json
import gspread
import smtplib
from email.mime.text import MIMEText
from oauth2client.service_account import ServiceAccountCredentials

# === 1. Cargar credenciales de Google desde secrets ===
service_account_info = json.loads(os.environ["GCP_SERVICE_ACCOUNT"])

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]
creds = ServiceAccountCredentials.from_json_keyfile_dict(service_account_info, scope)
client = gspread.authorize(creds)

# === 2. Abrir la hoja de cálculo ===
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
sheet = client.open_by_key(SPREADSHEET_ID).sheet1

# Leer los primeros registros
data = sheet.get_all_records()
print("✅ Conectado a Google Sheets")
print("📊 Primeras filas:", data[:5])

# === 3. Configurar Gmail para enviar correos ===
GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_APP_PASS = os.environ["GMAIL_APP_PASS"]

def enviar_correo(destinatario, asunto, mensaje):
    try:
        msg = MIMEText(mensaje)
        msg["Subject"] = asunto
        msg["From"] = GMAIL_USER
        msg["To"] = destinatario

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASS)
            server.sendmail(GMAIL_USER, destinatario, msg.as_string())

        print(f"📩 Correo enviado a {destinatario}")
    except Exception as e:
        print(f"❌ Error enviando correo: {e}")

# === 4. Ejemplo: enviar correo con primeras señales ===
if data:
    primera_fila = data[0]
    mensaje = f"Signal: {primera_fila}"
    enviar_correo("tucorreo@ejemplo.com", "📊 Señal de Trading", mensaje)
else:
    print("⚠️ No hay datos en la hoja.")
