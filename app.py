import os, ssl, smtplib, threading, time, json, warnings
warnings.filterwarnings("ignore")
import pandas as pd
import numpy as np
import schedule
from datetime import datetime, timedelta, time as dtime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import gspread
from google.oauth2.service_account import Credentials

# ==============================
# CONFIG
# ==============================
PRIMARY_EMAIL   = "gevem249@gmail.com"
SECONDARY_EMAIL = "adri_touma@hotmail.com"
USER_EMAIL      = PRIMARY_EMAIL
APP_PASS        = os.getenv("GMAIL_APP_PASS")   # 👈 pon este también como secret en GitHub

# Google Sheets desde Secrets
service_account_info = json.loads(os.getenv("SERVICE_ACCOUNT_JSON"))
creds = Credentials.from_service_account_info(
    service_account_info,
    scopes=[
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
)
client = gspread.authorize(creds)

SPREADSHEET_ID = "1yTd7l9NYvruWPJ4rgNSHQPsqE4o22F0_lvvBWhD1LbM"
sheet = client.open_by_key(SPREADSHEET_ID)

# ==============================
# HORARIOS
# ==============================
def now_local():
    return datetime.now()  # hora servidor (ajustada con tz si quieres)

def hora_local_mdY_hms():
    return now_local().strftime("%m/%d/%Y %I:%M:%S %p")

def is_nyse_open(dt=None):
    if dt is None: dt = now_local()
    if dt.weekday() >= 5: return False
    return dtime(9,30) <= dt.time() <= dtime(16,0)

def is_mes_open(dt=None):
    if dt is None: dt = now_local()
    wd = dt.weekday()
    if wd == 5: return False
    if wd == 6: return dt.time() >= dtime(18,0)
    return True

def is_lse_open(dt=None):
    if dt is None: dt = now_local()
    london = dt + timedelta(hours=5)
    return london.weekday() < 5 and dtime(8,0) <= london.time() <= dtime(16,30)

# ==============================
# EMAIL
# ==============================
def send_email_html(subject, body, recipients):
    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = USER_EMAIL
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = subject
        msg.attach(MIMEText(body,"html"))
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com",465,context=context) as server:
            server.login(USER_EMAIL, APP_PASS)
            server.sendmail(USER_EMAIL, recipients, msg.as_string())
    except Exception as e:
        print("❌ Error enviando correo:", e)

def send_all(subject, html): 
    send_email_html(subject, html, [PRIMARY_EMAIL])

# ==============================
# PROCESOS
# ==============================
def tick_report():
    """Ejecuta cada hora, revisa señales <80 en Sheet y manda mini reporte"""
    try:
        ws = sheet.worksheet("signals")
        data = pd.DataFrame(ws.get_all_records())
        if not data.empty:
            bajas = data[pd.to_numeric(data["score"], errors="coerce") < 80]
            resumen = f"<p>Señales <80 revisadas: {len(bajas)}</p>"
        else:
            resumen = "<p>No hay datos en 'signals'</p>"
    except:
        resumen = "<p>No pude leer hoja 'signals'</p>"

    body = f"""
    <h3>📊 Reporte Automático</h3>
    <p>Hora local NJ: {hora_local_mdY_hms()}</p>
    <ul>
      <li>NYSE: {"ABIERTO" if is_nyse_open() else "CERRADO"}</li>
      <li>MES (futuros): {"ABIERTO" if is_mes_open() else "CERRADO"}</li>
      <li>Londres: {"ABIERTO" if is_lse_open() else "CERRADO"}</li>
    </ul>
    {resumen}
    """
    send_all("📊 Reporte Bot", body)

def run_bot():
    body = f"""
    <h3>🤖 Bot Activado</h3>
    <p>Hora local NJ: {hora_local_mdY_hms()}</p>
    <ul>
      <li>NYSE: {"ABIERTO" if is_nyse_open() else "CERRADO"}</li>
      <li>MES (futuros): {"ABIERTO" if is_mes_open() else "CERRADO"}</li>
      <li>Londres: {"ABIERTO" if is_lse_open() else "CERRADO"}</li>
    </ul>
    """
    send_all("🤖 Bot Activado", body)
    schedule.every(1).hours.do(tick_report)   # 👈 cada 1 hora
    threading.Thread(target=loop_sched, daemon=True).start()

def loop_sched():
    while True:
        schedule.run_pending()
        time.sleep(1)

# ==============================
# START
# ==============================
if __name__ == "__main__":
    run_bot()
    print("✅ BOT MAESTRO LISTO (GitHub)")
