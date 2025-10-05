import os, json, datetime as dt, pytz
import pandas as pd
import gspread
import yfinance as yf
import numpy as np
import smtplib
from email.mime.text import MIMEText
from google.oauth2.service_account import Credentials

# =====================
# Configuración
# =====================
TZ = pytz.timezone("America/New_York")

SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
GS_JSON = json.loads(os.getenv("GOOGLE_SHEETS_JSON"))
CREDS = Credentials.from_service_account_info(
    GS_JSON, scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
GC = gspread.authorize(CREDS)
SHEET = GC.open_by_key(SPREADSHEET_ID).sheet1

GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_PASS = os.getenv("GMAIL_APP_PASS")

ALERT_DKNG = os.getenv("ALERT_DKNG", GMAIL_USER)
ALERT_MICROS = os.getenv("ALERT_MICROS", GMAIL_USER)
ALERT_DEFAULT = os.getenv("ALERT_DEFAULT", GMAIL_USER)

# =====================
# Indicadores simples
# =====================
def ema(series, span):
    return series.ewm(span=span, adjust=False).mean()

def rsi(series, period=14):
    delta = series.diff()
    up = np.where(delta > 0, delta, 0)
    down = np.where(delta < 0, -delta, 0)
    roll_up = pd.Series(up).rolling(period).mean()
    roll_down = pd.Series(down).rolling(period).mean()
    rs = roll_up / (roll_down + 1e-9)
    return 100 - (100/(1+rs))

# =====================
# Enviar correo alerta
# =====================
def send_alert(to_email, subject, body):
    if not GMAIL_USER or not GMAIL_PASS:
        print("⚠️ Gmail no configurado")
        return
    try:
        msg = MIMEText(body, "plain")
        msg["Subject"] = subject
        msg["From"] = GMAIL_USER
        msg["To"] = to_email

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_PASS)
            server.sendmail(GMAIL_USER, [to_email], msg.as_string())
        print(f"📧 Alerta enviada a {to_email}: {subject}")
    except Exception as e:
        print("❌ Error enviando alerta:", e)

# =====================
# Estrategia simple
# =====================
def analyze_ticker(ticker):
    try:
        data = yf.download(ticker, period="2d", interval="5m", progress=False)
        if data.empty: 
            return None

        close = data["Close"]
        e8, e21 = ema(close, 8), ema(close, 21)
        r = rsi(close).iloc[-1]

        prob = 50
        if e8.iloc[-1] > e21.iloc[-1] and r > 55:
            prob = 80
        elif e8.iloc[-1] < e21.iloc[-1] and r < 45:
            prob = 80

        return {
            "Ticker": ticker,
            "Close": close.iloc[-1],
            "ProbFinal": prob,
            "Side": "LONG" if e8.iloc[-1] > e21.iloc[-1] else "SHORT",
            "FechaISO": dt.datetime.now(TZ).strftime("%Y-%m-%d"),
            "HoraLocal": dt.datetime.now(TZ).strftime("%H:%M:%S"),
        }
    except Exception as e:
        print(f"⚠️ Error en {ticker}: {e}")
        return None

# =====================
# Guardar en Sheets
# =====================
def save_signal(signal):
    try:
        SHEET.append_row([
            signal["FechaISO"], signal["HoraLocal"], signal["Ticker"],
            signal["Side"], signal["Close"], signal["ProbFinal"], "Pre", ""
        ])
        print(f"✅ Señal guardada: {signal}")
    except Exception as e:
        print("❌ Error guardando en Sheet:", e)

# =====================
# Main
# =====================
def main():
    tickers = ["DKNG", "MES=F", "M2K=F"]  # puedes agregar más micros aquí
    for tkr in tickers:
        sig = analyze_ticker(tkr)
        if not sig: 
            continue
        save_signal(sig)

        # Enviar alerta según ticker
        if tkr == "DKNG":
            send_alert(ALERT_DKNG, f"Alerta {tkr}", str(sig))
        elif "M" in tkr:
            send_alert(ALERT_MICROS, f"Alerta {tkr}", str(sig))
        else:
            send_alert(ALERT_DEFAULT, f"Alerta {tkr}", str(sig))

if __name__ == "__main__":
    main()
