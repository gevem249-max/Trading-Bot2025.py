# update_results.py — Actualiza señales, resultados, registra estado del mercado y envía correos (versión completa)

import os
import json
import datetime as dt
import pytz
import pandas as pd
import yfinance as yf
import gspread
import smtplib
from email.mime.text import MIMEText
from google.oauth2.service_account import Credentials

# =========================
# ⚙️ Configuración
# =========================
TZ = pytz.timezone("America/New_York")

SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
GS_JSON = json.loads(os.getenv("GOOGLE_SHEETS_JSON"))

CREDS = Credentials.from_service_account_info(
    GS_JSON, scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
GC = gspread.authorize(CREDS)

# Hojas
SHEET_SIGNALS = GC.open_by_key(SPREADSHEET_ID).worksheet("signals")

try:
    SHEET_LOG = GC.open_by_key(SPREADSHEET_ID).worksheet("logs")
except gspread.WorksheetNotFound:
    SHEET_LOG = GC.open_by_key(SPREADSHEET_ID).add_worksheet("logs", rows=1000, cols=10)
    SHEET_LOG.update("A1", [["Timestamp", "Action", "Ticker", "Side", "Old", "New", "Note"]])

try:
    SHEET_MARKET = GC.open_by_key(SPREADSHEET_ID).worksheet("market_status")
except gspread.WorksheetNotFound:
    SHEET_MARKET = GC.open_by_key(SPREADSHEET_ID).add_worksheet("market_status", rows=200, cols=5)
    SHEET_MARKET.update("A1:E1", [["FechaISO", "HoraApertura", "HoraCierre", "TiempoActivo", "Estado"]])

# Gmail config
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_PASS = os.getenv("GMAIL_APP_PASS")
ALERT_EMAIL = "gevem249@gmail.com"

# =========================
# 🕒 Utils
# =========================
def now_et() -> dt.datetime:
    return dt.datetime.now(TZ)

def map_ticker_yf(ticker):
    t = ticker.upper()
    if t == "ES": return "^GSPC"
    if t == "MNQ": return "^NDX"
    if t == "MYM": return "^DJI"
    if t == "M2K": return "^RUT"
    if t == "BTCUSD": return "BTC-USD"
    if t == "ETHUSD": return "ETH-USD"
    return t

def send_mail(subject: str, body: str):
    if not GMAIL_USER or not GMAIL_PASS:
        return
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = GMAIL_USER
    msg["To"] = ALERT_EMAIL
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as srv:
            srv.login(GMAIL_USER, GMAIL_PASS)
            srv.sendmail(GMAIL_USER, [ALERT_EMAIL], msg.as_string())
    except Exception as e:
        print("❌ Error enviando correo:", e)

def log_action(action, ticker, side, old, new, note=""):
    SHEET_LOG.append_row([
        now_et().isoformat(), action, ticker, side, old, new, note
    ])

# =========================
# 🏛️ Registro de mercado + correo
# =========================
def update_market_status():
    print("⏰ Revisando estado del mercado...")
    current_time = now_et()
    weekday = current_time.weekday()

    open_hour = 9
    close_hour = 16
    estado = "Cerrado"
    if weekday < 5 and open_hour <= current_time.hour < close_hour:
        estado = "Abierto"

    vals = SHEET_MARKET.get_all_records()
    today_iso = current_time.date().isoformat()

    if vals and vals[-1]["FechaISO"] == today_iso:
        last_row = len(vals) + 1
        last_estado = vals[-1]["Estado"]
        if estado != last_estado:
            # cambio de estado -> enviar correo
            if estado == "Abierto":
                hora_apertura = current_time.strftime("%H:%M:%S")
                SHEET_MARKET.append_row([today_iso, hora_apertura, "", "", estado])
                send_mail(
                    f"📈 Apertura del mercado ({today_iso})",
                    f"El mercado abrió a las {hora_apertura} ET.\n\nEstado: {estado}"
                )
            elif estado == "Cerrado":
                hora_cierre = current_time.strftime("%H:%M:%S")
                hora_apertura = vals[-1].get("HoraApertura", "")
                tiempo_activo = ""
                if hora_apertura:
                    try:
                        h1 = dt.datetime.strptime(hora_apertura, "%H:%M:%S")
                        h2 = dt.datetime.strptime(hora_cierre, "%H:%M:%S")
                        diff = h2 - h1
                        tiempo_activo = str(diff)
                    except:
                        tiempo_activo = ""
                SHEET_MARKET.append_row([today_iso, hora_apertura, hora_cierre, tiempo_activo, estado])
                send_mail(
                    f"📉 Cierre del mercado ({today_iso})",
                    f"El mercado cerró a las {hora_cierre} ET.\nTiempo activo: {tiempo_activo}\n\nEstado: {estado}"
                )
    else:
        # primera entrada del día
        if estado == "Abierto":
            hora_apertura = current_time.strftime("%H:%M:%S")
            SHEET_MARKET.append_row([today_iso, hora_apertura, "", "", estado])
            send_mail(
                f"📈 Apertura del mercado ({today_iso})",
                f"El mercado abrió a las {hora_apertura} ET.\n\nEstado: {estado}"
            )

    print(f"📅 Estado del mercado ({today_iso}): {estado}")

# =========================
# 📈 Confirmaciones / Resultados
# =========================
def update_confirmations_and_results():
    print("🔁 Actualizando señales...")
    rows = SHEET_SIGNALS.get_all_records()
    if not rows:
        print("⚠️ No hay señales.")
        return

    df = pd.DataFrame(rows)
    if "Estado" not in df.columns:
        print("⚠️ Falta columna Estado.")
        return

    for i, row in enumerate(rows, start=2):
        try:
            estado = row.get("Estado", "")
            ticker = row.get("Ticker", "")
            side = row.get("Side", "buy").lower()
            scheduled = row.get("ScheduledConfirm", "")
            sl = float(row.get("SL") or 0)
            tp = float(row.get("TP") or 0)

            # Confirmaciones (Pre → Confirmado / Cancelado)
            if estado == "Pre" and scheduled:
                sc_dt = dt.datetime.fromisoformat(scheduled).astimezone(TZ)
                if sc_dt <= now_et():
                    y_ticker = map_ticker_yf(ticker)
                    df_now = yf.download(y_ticker, period="1d", interval="1m", progress=False)
                    if df_now.empty:
                        continue
                    price_now = df_now["Close"].iloc[-1]
                    estado2 = "Confirmado" if price_now else "Cancelado"
                    SHEET_SIGNALS.update_cell(i, df.columns.get_loc("Estado")+1, estado2)
                    log_action("Confirmación", ticker, side, estado, estado2)

            # Resultados (Win / Loss)
            if estado in ["Pre", "Confirmado"] and row.get("Resultado", "-") in ["-", ""]:
                y_ticker = map_ticker_yf(ticker)
                df_now = yf.download(y_ticker, period="1d", interval="1m", progress=False)
                if df_now.empty:
                    continue
                last_price = float(df_now["Close"].iloc[-1])
                resultado = None

                if side == "buy":
                    if last_price <= sl:
                        resultado = "Loss"
                    elif last_price >= tp:
                        resultado = "Win"
                else:
                    if last_price >= sl:
                        resultado = "Loss"
                    elif last_price <= tp:
                        resultado = "Win"

                if resultado:
                    SHEET_SIGNALS.update_cell(i, df.columns.get_loc("Resultado")+1, resultado)
                    log_action("Resultado", ticker, side, estado, resultado)
        except Exception as e:
            log_action("Error", row.get("Ticker", ""), row.get("Side", ""), "", "", str(e))
    print("✅ Señales actualizadas correctamente.")

# =========================
# 🧹 Limpieza semanal
# =========================
def cleanup_old_logs(days=7):
    print("🧹 Limpiando logs antiguos...")
    vals = SHEET_LOG.get_all_records()
    if not vals:
        return
    cutoff = now_et() - dt.timedelta(days=days)
    new_vals = [v for v in vals if dt.datetime.fromisoformat(v["Timestamp"]) >= cutoff]
    SHEET_LOG.clear()
    SHEET_LOG.update("A1", [["Timestamp", "Action", "Ticker", "Side", "Old", "New", "Note"]])
    for v in new_vals:
        SHEET_LOG.append_row([v["Timestamp"], v["Action"], v["Ticker"], v["Side"], v["Old"], v["New"], v["Note"]])
    print(f"🧾 {len(vals)-len(new_vals)} registros antiguos eliminados.")

# =========================
# ▶️ MAIN
# =========================
if __name__ == "__main__":
    update_market_status()
    update_confirmations_and_results()
    cleanup_old_logs(7)
