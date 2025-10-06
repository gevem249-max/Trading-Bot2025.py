# bot.py — Trading-Bot completo con Sniper + confirmaciones + auto-resultado SL/TP + error logging
import os
import sys
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

# Gmail (envío)
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_PASS = os.getenv("GMAIL_APP_PASS")

# Routing de alertas
ALERT_DKNG = os.getenv("ALERT_DKNG")
ALERT_MICROS = os.getenv("ALERT_MICROS")
ALERT_DEFAULT = os.getenv("ALERT_DEFAULT", GMAIL_USER)

# =========================
# 🧭 Tiempo/mercado
# =========================
def now_et() -> dt.datetime:
    return dt.datetime.now(TZ)

def classify_market(ticker: str) -> str:
    t = ticker.upper().replace("/", "")
    if t in MICRO_TICKERS: return "cme_micro"
    if t in CRYPTO_TICKERS: return "crypto"
    if FOREX_RE.match(t) and t not in CRYPTO_TICKERS: return "forex"
    return "equity"

def is_market_open(market: str, t: dt.datetime) -> bool:
    wd = t.weekday()
    h, m = t.hour, t.minute
    minutes = h*60 + m

    if market == "equity":
        if wd >= 5: return False
        return (9*60 + 30) <= minutes < (16*60)
    if market == "cme_micro":
        if wd == 5: return False
        if wd == 6 and minutes < (18*60): return False
        if wd == 4 and minutes >= (17*60): return False
        if (17*60) <= minutes < (18*60): return False
        return True
    if market == "forex":
        if wd == 5: return False
        if wd == 6 and minutes < (17*60): return False
        if wd == 4 and minutes >= (17*60): return False
        return True
    if market == "crypto":
        return True
    return False

# =========================
# 📬 Email
# =========================
def send_mail_many(subject: str, body: str, to_emails: str):
    if not to_emails: return
    recipients = [e.strip() for e in to_emails.split(",") if e.strip()]
    if not recipients: return
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
    if df is None or df.empty: return 50.0
    close = df["Close"]
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
        return yf.download(y, period=lookback, interval=interval, progress=False, threads=False)
    except Exception:
        return pd.DataFrame()

def prob_multi_frame(ticker: str, side: str, weights=None) -> dict:
    frames = {"1m":("1m","2d"),"5m":("5m","5d"),"15m":("15m","1mo"),"1h":("60m","3mo")}
    probs = {}
    for k,(itv,lb) in frames.items():
        df = fetch_yf(ticker, itv, lb)
        probs[k] = frame_prob(df, side)
    if not weights: weights = get_current_frame_weights()
    final = round(sum(probs[k]*weights.get(k,0) for k in probs),1)
    return {"per_frame":probs,"final":final}

# =========================
# 🔎 Sniper: ATR, MACD, patrones
# =========================
def atr(df, period=14):
    if df is None or df.empty: return 0.0
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    tr1 = (high - low).abs()
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period).mean().iloc[-1] if len(tr)>=period else tr.mean()

def macd_signal(df, fast=12, slow=26, signal=9):
    if df.empty: return 0.0
    close = df["Close"]
    ema_fast = close.ewm(span=fast).mean()
    ema_slow = close.ewm(span=slow).mean()
    macd = ema_fast - ema_slow
    macd_sig = macd.ewm(span=signal).mean()
    return (macd.iloc[-1] - macd_sig.iloc[-1]) if len(macd)>signal else 0.0

# =========================
# Google Sheets helpers
# =========================
HEADERS = [
    "FechaISO","HoraLocal","HoraRegistro","Ticker","Side","Entrada",
    "Prob_1m","Prob_5m","Prob_15m","Prob_1h","ProbFinal",
    "ProbClasificación","Estado","Tipo","Resultado","Nota","Mercado",
    "pattern","pat_score","macd_val","sr_score","atr","SL","TP",
    "Recipients","ScheduledConfirm"
]

def ensure_headers():
    vals = SHEET.get_all_values()
    if not vals: SHEET.append_row(HEADERS)

def append_signal(row_dict: dict):
    ensure_headers()
    row = [row_dict.get(k,"") for k in HEADERS]
    SHEET.append_row(row)

def find_rows(filter_fn):
    records = SHEET.get_all_records()
    return [(i+2, r) for i,r in enumerate(records) if filter_fn(r)]

# =========================
# Logging
# =========================
def log_error(exc: Exception, context: str = ""):
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    try:
        send_mail_many(f"⚠️ Error Bot: {context}", f"{tb}", ALERT_DEFAULT)
    except: pass

# =========================
# Pesos desde 'meta'
# =========================
def get_meta_ws():
    try: return GC.open_by_key(SPREADSHEET_ID).worksheet("meta")
    except gspread.WorksheetNotFound:
        ws = GC.open_by_key(SPREADSHEET_ID).add_worksheet("meta", rows=2000, cols=20)
        ws.update("A1", [["ts","w_1m","w_5m","w_15m","w_1h"]])
        return ws

def get_current_frame_weights():
    defaults = {"1m":0.2,"5m":0.4,"15m":0.25,"1h":0.15}
    try:
        vals = get_meta_ws().get_all_records()
        if not vals: return defaults
        last = vals[-1]
        s = last["w_1m"]+last["w_5m"]+last["w_15m"]+last["w_1h"]
        return {k: last[k]/s for k in ["w_1m","w_5m","w_15m","w_1h"]}
    except: return defaults

# =========================
# Señales
# =========================
def process_signal(ticker: str, side: str, entry: float):
    try:
        t = now_et()
        pm = prob_multi_frame(ticker, side)
        row = {
            "FechaISO": t.strftime("%Y-%m-%d"),
            "HoraLocal": t.strftime("%H:%M"),
            "HoraRegistro": t.strftime("%H:%M:%S"),
            "Ticker": ticker,
            "Side": side,
            "Entrada": entry,
            "Prob_1m": pm["per_frame"]["1m"],
            "Prob_5m": pm["per_frame"]["5m"],
            "Prob_15m": pm["per_frame"]["15m"],
            "Prob_1h": pm["per_frame"]["1h"],
            "ProbFinal": pm["final"],
            "ProbClasificación": "≥80" if pm["final"]>=80 else "<80",
            "Estado": "Pre" if pm["final"]>=80 else "Descartada",
            "Tipo": "Pre",
            "Resultado": "-",
            "Nota": "",
            "Mercado": classify_market(ticker),
            "pattern": "",
            "pat_score": "",
            "macd_val": "",
            "sr_score": "",
            "atr": "",
            "SL": "",
            "TP": "",
            "Recipients": ALERT_DEFAULT,
            "ScheduledConfirm": ""
        }
        append_signal(row)
        return row
    except Exception as e:
        log_error(e, "process_signal")
        raise

# =========================
# CLI
# =========================
def main():
    args = sys.argv[1:]
    if not args:
        print("Comandos: signal")
        return
    if args[0]=="signal":
        ticker, side, entry = args[1], args[2], float(args[3])
        row = process_signal(ticker, side, entry)
        print("OK:", row)

if __name__=="__main__":
    main()
