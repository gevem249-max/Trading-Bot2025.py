# update_results.py — Estado de mercado + email en apertura/cierre + log en Sheets
import os, json, pytz, datetime as dt
import gspread
from google.oauth2.service_account import Credentials
import smtplib
from email.mime.text import MIMEText

# ======== Config ========
TZ = pytz.timezone("America/New_York")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
GS_JSON = json.loads(os.getenv("GOOGLE_SHEETS_JSON") or "{}")
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_PASS = os.getenv("GMAIL_APP_PASS")
ALERT_DEFAULT = os.getenv("ALERT_DEFAULT", GMAIL_USER or "")

if not SPREADSHEET_ID or not GS_JSON:
    raise RuntimeError("Faltan SPREADSHEET_ID o GOOGLE_SHEETS_JSON")

CREDS = Credentials.from_service_account_info(
    GS_JSON, scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
GC = gspread.authorize(CREDS)
SS = GC.open_by_key(SPREADSHEET_ID)

# ======== Helpers ========
def now_et() -> dt.datetime:
    return dt.datetime.now(TZ)

def is_weekday(t: dt.datetime) -> bool:
    return t.weekday() < 5  # 0 = lunes ... 4 = viernes

def market_status(t: dt.datetime) -> str:
    """Regular hours US equities: 09:30–16:00 ET, lun–vie."""
    if not is_weekday(t):
        return "Cerrado"
    open_time = t.replace(hour=9, minute=30, second=0, microsecond=0)
    close_time = t.replace(hour=16, minute=0, second=0, microsecond=0)
    return "Abierto" if (open_time <= t < close_time) else "Cerrado"

def ensure_ws(title: str, headers: list[str]):
    try:
        ws = SS.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = SS.add_worksheet(title=title, rows=2000, cols=max(10, len(headers)))
        ws.update("A1", [headers])
    # si faltan columnas, las agrega al final de la fila 1
    current = ws.row_values(1)
    missing = [h for h in headers if h not in current]
    if missing:
        ws.update("A1", [current + missing])
    return ws

def send_mail(subject: str, body: str, recipients: str):
    if not recipients or not GMAIL_USER or not GMAIL_PASS:
        return
    to_list = [e.strip() for e in recipients.split(",") if e.strip()]
    if not to_list:
        return
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = GMAIL_USER
    msg["To"] = ", ".join(to_list)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as srv:
        srv.login(GMAIL_USER, GMAIL_PASS)
        srv.sendmail(GMAIL_USER, to_list, msg.as_string())

def get_last_status(ws):
    vals = ws.get_all_values()
    if len(vals) < 2:
        return None
    # última fila no vacía
    last = vals[-1]
    # columnas: FechaISO | HoraLocal | Estado | Comentario
    if len(last) >= 3 and last[2]:
        return last[2]
    return None

# ======== Main ========
def main():
    t = now_et()
    estado = market_status(t)

    ws = ensure_ws("market_status", ["FechaISO","HoraLocal","Estado","Comentario"])

    # Ver si cambió respecto al último estado
    prev = get_last_status(ws)
    changed = (prev is None) or (prev != estado)

    # Mensaje para el log
    comentario = "Mercado dentro del horario regular" if estado == "Abierto" else "Fuera de horario regular"
    ws.append_row([
        t.strftime("%Y-%m-%d"),
        t.strftime("%H:%M:%S"),
        estado,
        comentario
    ])

    # Si hubo cambio, enviar correo
    if changed and ALERT_DEFAULT:
        if estado == "Abierto":
            subject = "📈 Mercado ABIERTO (US Equities)"
            body = f"El mercado abrió a las 09:30 ET.\nHora actual ET: {t.strftime('%H:%M:%S')}\nEstado: {estado}"
        else:
            subject = "📉 Mercado CERRADO (US Equities)"
            body = f"El mercado cerró a las 16:00 ET.\nHora actual ET: {t.strftime('%H:%M:%S')}\nEstado: {estado}"
        send_mail(subject, body, ALERT_DEFAULT)

if __name__ == "__main__":
    main()
