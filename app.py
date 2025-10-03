import os, ssl, smtplib, time, threading, schedule, json
from datetime import datetime, timedelta, time as dtime
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ==============================
# CONFIG
# ==============================
PRIMARY_EMAIL   = "gevem249@gmail.com"
SECONDARY_EMAIL = "adri_touma@hotmail.com"
USER_EMAIL      = PRIMARY_EMAIL
APP_PASS        = os.getenv("GMAIL_APP_PASS")  # Guardado en GitHub Secrets

SPREADSHEET_ID  = os.getenv("SPREADSHEET_ID")  # Guardado en GitHub Secrets
SERVICE_ACCOUNT_JSON = os.getenv("SERVICE_ACCOUNT_JSON")

# ==============================
# AUTH GOOGLE SHEETS
# ==============================
service_account_info = json.loads(SERVICE_ACCOUNT_JSON)
creds = Credentials.from_service_account_info(
    service_account_info,
    scopes=[
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
)
client = gspread.authorize(creds)
sheet = client.open_by_key(SPREADSHEET_ID)

# ==============================
# FUNCIONES DE TIEMPO
# ==============================
def now_local():
    return datetime.now()

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
    msg = MIMEMultipart("alternative")
    msg["From"], msg["To"], msg["Subject"] = USER_EMAIL, ", ".join(recipients), subject
    msg.attach(MIMEText(body,"html"))
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com",465,context=context) as server:
        server.login(USER_EMAIL, APP_PASS)
        server.sendmail(USER_EMAIL, recipients, msg.as_string())

def send_all(subject, html): 
    send_email_html(subject, html, [PRIMARY_EMAIL])

# ==============================
# TAREAS BOT
# ==============================
def evaluar_senales():
    try:
        ws = sheet.worksheet("signals")
        df = pd.DataFrame(ws.get_all_records())
        if df.empty:
            return
        # ejemplo: filtrar señales <80
        bajas = df[df["score"].astype(float) < 80]
        resumen = f"Total señales bajas: {len(bajas)}"
        send_all("📊 Reporte Señales", f"<p>{resumen}</p>")
    except Exception as e:
        send_all("❌ Error Bot", str(e))

def start_sched():
    schedule.every(1).hours.do(evaluar_senales)  # 👈 cada hora
    evaluar_senales()  # primera vez

def loop_sched():
    while True:
        schedule.run_pending()
        time.sleep(1)

# ==============================
# RUN
# ==============================
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
    start_sched()
    threading.Thread(target=loop_sched, daemon=True).start()

if __name__ == "__main__":
    run_bot()
    while True:
        time.sleep(60)
