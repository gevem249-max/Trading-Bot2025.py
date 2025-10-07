# bot.py — Trading-Bot DKNG + ES con Google Sheets y alertas por correo

import os
import json
import re
import pytz
import datetime as dt
import smtplib
from email.mime.text import MIMEText

import pandas as pd
import numpy as np
import yfinance as yf

import gspread
from google.oauth2.service_account import Credentials

# =========================
# 🔧 Configuración
# =========================
TZ = pytz.timezone("America/New_York")
WATCHLIST = ["DKNG", "ES"]   # activos a monitorear

SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
GS_JSON = json.loads(os.getenv("GOOGLE_SHEETS_JSON"))

CREDS = Credentials.from_service_account_info(
    GS_JSON, scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
GC = gspread.authorize(CREDS)
SHEET = GC.open_by_key(SPREADSHEET_ID).sheet1

# Gmail
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_PASS = os.getenv("GMAIL_APP_PASS")

# Destinatarios
ALERT_DKNG = "gevem249@gmail.com,adri_touma@hotmail.com"
ALERT_ES = "gevem249@gmail.com"

# =========================
# 🧭 Utils
# =========================
def now_et() -> dt.datetime:
    return dt.datetime.now(TZ)

# =========================
# 📬 Email
# =========================
def send_mail(subject: str, body: str, to_emails: str):
    try:
        recipients = [e.strip() for e in to_emails.split(",") if e.strip()]
        if not recipients:
            return
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = GMAIL_USER
        msg["To"] = ", ".join(recipients)
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as srv:
            srv.login(GMAIL_USER, GMAIL_PASS)
            srv.sendmail(GMAIL_USER, recipients, msg.as_string())
    except Exception as e:
        print("❌ Error enviando correo:", e)

# =========================
# 📈 Indicadores
# =========================
def ema(series, span): 
    return series.ewm(span=span, adjust=False).mean()

def rsi(series, period=14):
    delta = series.diff()
    up = np.where(delta > 0, delta, 0.0)
    down = np.where(delta < 0, -delta, 0.0)
    roll_up = pd.Series(up, index=series.index).rolling(period).mean()
    roll_down = pd.Series(down, index=series.index).rolling(period).mean()
    rs = roll_up / (roll_down + 1e-9)
    return 100 - (100/(1+rs))

def frame_prob(df: pd.DataFrame, side: str) -> float:
    if df is None or df.empty: 
        return 50.0
    close = df["Close"].squeeze()
    e8, e21 = ema(close, 8), ema(close, 21)
    r = rsi(close, 14).fillna(50).iloc[-1]
    trend = (e8.iloc[-1]-e21.iloc[-1])
    score = 50.0
    if side.lower()=="buy":
        if trend > 0: score += 20
        if 45 <= r <= 70: score += 15
        if r < 35: score -= 15
    else:
        if trend < 0: score += 20
        if 30 <= r <= 55: score += 15
        if r > 65: score -= 15
    return max(0.0, min(100.0, score))

def fetch_yf(ticker: str, interval: str, lookback: str):
    y = ticker
    if ticker.upper()=="ES": y="^GSPC"  # mapeo ES → S&P500
    try:
        df = yf.download(y, period=lookback, interval=interval, progress=False, threads=False)
    except Exception:
        df = pd.DataFrame()
    return df

def prob_multi_frame(ticker: str, side: str) -> dict:
    frames = {"1m":("1m","2d"),"5m":("5m","5d"),"15m":("15m","1mo"),"1h":("60m","3mo")}
    probs = {}
    for k,(itv,lb) in frames.items():
        df = fetch_yf(ticker, itv, lb)
        probs[k] = frame_prob(df, side)
    final = round(sum(probs.values())/len(probs),1)
    return {"per_frame":probs,"final":final}

# =========================
# Core
# =========================
def process_signal(ticker: str, side: str, entry: float):
    t = now_et()
    pm = prob_multi_frame(ticker, side)
    pf = pm["final"]
    estado = "Pre" if pf >= 80 else "Descartada"

    # Guardar en Google Sheets
    row = [t.strftime("%Y-%m-%d %H:%M:%S"), ticker, side, entry, pf, estado]
    SHEET.append_row(row)

    # Notificar solo si es Pre
    if estado == "Pre":
        recipients = ALERT_ES if ticker.upper()=="ES" else ALERT_DKNG
        subject = f"📊 Señal {ticker} {side} {entry} – {pf}%"
        body = f"{ticker} {side} @ {entry}\nProbFinal {pf}% | Estado: {estado}"
        send_mail(subject, body, recipients)

    return {"ticker":ticker,"side":side,"entry":entry,"pf":pf,"estado":estado}

# =========================
# ▶️ Main
# =========================
def main():
    print("🚀 Bot corriendo...")
    for ticker in WATCHLIST:
        try:
            res = process_signal(ticker, "buy", 100.0)  # entrada dummy
            print("Resultado:", res)
        except Exception as e:
            print("Error con", ticker, ":", e)

if __name__ == "__main__":
    main()
