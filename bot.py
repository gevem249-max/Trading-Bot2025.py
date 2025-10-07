# bot.py — Trading-Bot con Sniper + confirmaciones + auto-resultado SL/TP + logging
import os
import json
import re
import pytz
import datetime as dt
import smtplib
import traceback
from email.mime.text import MIMEText

import pandas as pd
import numpy as np
import yfinance as yf

import gspread
from google.oauth2.service_account import Credentials

# =========================
# 🔧 Configuración / env
# =========================
TZ = pytz.timezone("America/New_York")
MICRO_TICKERS = {"MES","MNQ","MYM","M2K","MGC","MCL","M6E","M6B","M6A"}
CRYPTO_TICKERS = {"BTCUSD","ETHUSD","SOLUSD","ADAUSD","XRPUSD"}
FOREX_RE = re.compile(r"^[A-Z]{6}$")

SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
gs_raw = os.getenv("GOOGLE_SHEETS_JSON", "")
GS_JSON = None
if gs_raw:
    try:
        GS_JSON = json.loads(gs_raw)
    except Exception:
        try:
            GS_JSON = json.loads(open(gs_raw).read())
        except Exception:
            GS_JSON = None

if not SPREADSHEET_ID or not GS_JSON:
    raise RuntimeError("⚠️ Falta SPREADSHEET_ID o GOOGLE_SHEETS_JSON en secrets/env")

CREDS = Credentials.from_service_account_info(
    GS_JSON, scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
GC = gspread.authorize(CREDS)
SHEET = GC.open_by_key(SPREADSHEET_ID).sheet1

# Gmail
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_PASS = os.getenv("GMAIL_APP_PASS")

# Routing de alertas (se definen en secrets, aquí ya preconfigurado)
ALERT_DEFAULT = os.getenv("ALERT_DEFAULT", "gevem249@gmail.com")
ALERT_DKNG = os.getenv("ALERT_DKNG", "gevem249@gmail.com,adri_touma@hotmail.com")
ALERT_MICROS = os.getenv("ALERT_MICROS", "gevem249@gmail.com")

# =========================
# 🧭 Utils
# =========================
def now_et() -> dt.datetime:
    return dt.datetime.now(TZ)

def classify_market(ticker: str) -> str:
    t = ticker.upper().replace("/", "")
    if t in MICRO_TICKERS: return "cme_micro"
    if t in CRYPTO_TICKERS: return "crypto"
    if FOREX_RE.match(t) and t not in CRYPTO_TICKERS: return "forex"
    return "equity"

# =========================
# 📬 Email
# =========================
def send_mail_many(subject: str, body: str, to_emails: str):
    if not to_emails or not GMAIL_USER or not GMAIL_PASS:
        return
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

# =========================
# 📈 Indicadores
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
    if ticker.upper()=="MES": y="^GSPC"
    if ticker.upper()=="MNQ": y="^NDX"
    if ticker.upper()=="MYM": y="^DJI"
    if ticker.upper()=="M2K": y="^RUT"
    try:
        df = yf.download(y, period=lookback, interval=interval, progress=False, threads=False)
    except Exception:
        df = pd.DataFrame()
    return df

def prob_multi_frame(ticker: str, side: str, weights=None) -> dict:
    frames = {"1m":("1m","2d"),"5m":("5m","5d"),"15m":("15m","1mo"),"1h":("60m","3mo")}
    probs = {}
    for k,(itv,lb) in frames.items():
        df = fetch_yf(ticker, itv, lb)
        probs[k] = frame_prob(df, side)
    if not weights:
        weights = {"1m":0.2,"5m":0.4,"15m":0.25,"1h":0.15}
    final = round(sum(probs[k]*weights.get(k,0) for k in probs),1)
    return {"per_frame":probs,"final":final}

# =========================
# Sniper básico
# =========================
def sniper_score(ticker, side):
    df5 = fetch_yf(ticker, "5m", "5d")
    base = frame_prob(df5, side) if not df5.empty else 50.0
    return {"score": base, "frame_probs": prob_multi_frame(ticker, side)}

# =========================
# Core signal
# =========================
def process_signal(ticker: str, side: str, entry: float):
    t = now_et()
    pm = prob_multi_frame(ticker, side)
    pf = pm["final"]
    sn = sniper_score(ticker, side)
    sniper_val = sn["score"]
    estado = "Pre" if sniper_val >= 80 else "Descartada"

    # Routing
    recipients = ALERT_DEFAULT
    if ticker.upper()=="DKNG" and ALERT_DKNG:
        recipients = ALERT_DKNG
    elif ticker.upper() in MICRO_TICKERS and ALERT_MICROS:
        recipients = ALERT_MICROS

    subject = f"📊 Señal {ticker} {side} {entry} – {round(sniper_val,1)}%"
    body = f"{ticker} {side} @ {entry}\nProbFinal {pf}% | Estado: {estado}"
    send_mail_many(subject, body, recipients)
    return {"ticker":ticker,"side":side,"entry":entry,"estado":estado}

# =========================
# ▶️ Main
# =========================
def main():
    print("🚀 Bot corriendo...")
    try:
        res = process_signal("DKNG", "buy", 30.0)
        print("Resultado:", res)
    except Exception as e:
        print("Error en main:", e)

if __name__ == "__main__":
    main()
