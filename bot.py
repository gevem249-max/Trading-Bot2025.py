# bot.py — Trading-Bot DKNG + ES con Google Sheets, alertas y aprendizaje
import os
import json
import re
import pytz
import datetime as dt
import smtplib
from email.mime.text import MIMEText
import traceback

import pandas as pd
import numpy as np
import yfinance as yf

import gspread
from google.oauth2.service_account import Credentials

# =========================
# 🔧 Configuración
# =========================
TZ = pytz.timezone("America/New_York")
WATCHLIST = ["DKNG", "ES"]

SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
GS_JSON = json.loads(os.getenv("GOOGLE_SHEETS_JSON"))
CREDS = Credentials.from_service_account_info(
    GS_JSON, scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
GC = gspread.authorize(CREDS)
SHEET_SIGNALS = GC.open_by_key(SPREADSHEET_ID).worksheet("signals")
try:
    SHEET_LOGS = GC.open_by_key(SPREADSHEET_ID).worksheet("logs")
except gspread.WorksheetNotFound:
    SHEET_LOGS = GC.open_by_key(SPREADSHEET_ID).add_worksheet("logs", rows=2000, cols=5)
    SHEET_LOGS.update("A1:E1", [["Fecha","Hora","Nivel","Mensaje","Contexto"]])

# Gmail
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_PASS = os.getenv("GMAIL_APP_PASS")

# Destinatarios
ALERT_DKNG = "gevem249@gmail.com,adri_touma@hotmail.com"
ALERT_ES = "gevem249@gmail.com"

# =========================
# Utils
# =========================
def now_et() -> dt.datetime:
    return dt.datetime.now(TZ)

def log_msg(level, msg, ctx=""):
    """Guarda logs y elimina los de +7 días."""
    try:
        SHEET_LOGS.append_row([now_et().strftime("%Y-%m-%d"), now_et().strftime("%H:%M:%S"), level, msg, ctx])
        vals = SHEET_LOGS.get_all_records()
        df = pd.DataFrame(vals)
        if not df.empty:
            df["Fecha"] = pd.to_datetime(df["Fecha"])
            cutoff = now_et() - dt.timedelta(days=7)
            keep = df[df["Fecha"] >= cutoff]
            SHEET_LOGS.clear()
            SHEET_LOGS.update("A1:E1", [["Fecha","Hora","Nivel","Mensaje","Contexto"]])
            if not keep.empty:
                SHEET_LOGS.update("A2", keep.values.tolist())
    except Exception as e:
        print("⚠️ Error log:", e)

# =========================
# Email
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
        log_msg("ERROR", f"Error enviando correo: {e}", subject)

# =========================
# Indicadores
# =========================
def ema(series, span): return series.ewm(span=span, adjust=False).mean()

def rsi(series, period=14):
    delta = series.diff()
    up = np.where(delta > 0, delta, 0.0)
    down = np.where(delta < 0, -delta, 0.0)
    roll_up = pd.Series(up, index=series.index).rolling(period).mean()
    roll_down = pd.Series(down, index=series.index).rolling(period).mean()
    rs = roll_up / (roll_down + 1e-9)
    return 100 - (100/(1+rs))

def frame_prob(df: pd.DataFrame, side: str) -> float:
    if df is None or df.empty: return 50.0
    close = df["Close"].squeeze()
    e8, e21 = ema(close, 8), ema(close, 21)
    r = rsi(close, 14).fillna(50).iloc[-1]
    score = 50.0
    if side.lower()=="buy":
        if e8.iloc[-1] > e21.iloc[-1]: score += 20
        if 45 <= r <= 70: score += 15
    else:
        if e8.iloc[-1] < e21.iloc[-1]: score += 20
        if 30 <= r <= 55: score += 15
    return max(0.0, min(100.0, score))

def fetch_yf(ticker: str, interval: str, lookback: str):
    y = ticker
    if ticker.upper()=="ES": y="^GSPC"
    try:
        return yf.download(y, period=lookback, interval=interval, progress=False, threads=False)
    except Exception:
        return pd.DataFrame()

def prob_multi_frame(ticker: str, side: str) -> dict:
    frames = {"1m":("1m","2d"),"5m":("5m","5d"),"15m":("15m","1mo"),"1h":("60m","3mo")}
    probs = {}
    for k,(itv,lb) in frames.items():
        df = fetch_yf(ticker, itv, lb)
        probs[k] = frame_prob(df, side)
    final = round(sum(probs.values())/len(probs),1)
    return {"per_frame":probs,"final":final}

# =========================
# Señales
# =========================
def process_signal(ticker: str, side: str, entry: float):
    t = now_et()
    pm = prob_multi_frame(ticker, side)
    pf = pm["final"]
    estado = "Pre" if pf >= 80 else "Descartada"
    scheduled = (t + dt.timedelta(minutes=5)).isoformat() if estado=="Pre" else ""

    row = [
        t.strftime("%Y-%m-%d"), t.strftime("%H:%M"), t.strftime("%H:%M:%S"),
        ticker, side, entry,
        pm["per_frame"]["1m"], pm["per_frame"]["5m"], pm["per_frame"]["15m"], pm["per_frame"]["1h"],
        pf,
        "≥80" if pf >= 80 else "<80",
        estado, "Pre" if estado=="Pre" else "Backtest",
        "-", "", "equity", "-",0,0,0,0,0,0,
        ALERT_DKNG if ticker=="DKNG" else ALERT_ES,
        scheduled
    ]
    SHEET_SIGNALS.append_row(row)

    if estado=="Pre":
        recipients = ALERT_DKNG if ticker=="DKNG" else ALERT_ES
        subject = f"📊 Pre-señal {ticker} {side} {entry} – {pf}%"
        body = f"{ticker} {side} @ {entry}\nProbFinal {pf}% | Confirmación en 5 min"
        send_mail(subject, body, recipients)

    log_msg("INFO", f"Señal {ticker} {estado}", f"{pf}%")
    return {"ticker":ticker,"pf":pf,"estado":estado}

# =========================
# Confirmaciones
# =========================
def check_confirmations():
    vals = SHEET_SIGNALS.get_all_records()
    now = now_et()
    for i,row in enumerate(vals, start=2):
        if row.get("Estado")=="Pre" and row.get("ScheduledConfirm"):
            sc = dt.datetime.fromisoformat(row["ScheduledConfirm"])
            if sc <= now:
                pf2 = prob_multi_frame(row["Ticker"], row["Side"])["final"]
                estado2 = "Confirmada" if pf2>=80 else "Cancelada"
                SHEET_SIGNALS.update_cell(i, vals[0].keys().index("Estado")+1, estado2)
                log_msg("INFO", f"Confirmación {estado2}", row["Ticker"])

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
            log_msg("ERROR", str(e), ticker)

    check_confirmations()

if __name__ == "__main__":
    main()
