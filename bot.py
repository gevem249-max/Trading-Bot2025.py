# bot.py — Trading-Bot con Google Sheets + Email Alerts + Limpieza semanal de logs

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
MICRO_TICKERS = {"MES","MNQ","MYM","M2K","MGC","MCL","M6E","M6B","M6A"}
CRYPTO_TICKERS = {"BTCUSD","ETHUSD","SOLUSD","ADAUSD","XRPUSD"}
FOREX_RE = re.compile(r"^[A-Z]{6}$")

SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
gs_raw = os.getenv("GOOGLE_SHEETS_JSON", "")
GS_JSON = json.loads(gs_raw)

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

# Routing de alertas
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
# Guardar en Google Sheets
# =========================
def append_to_sheet(row_dict):
    try:
        headers = SHEET.row_values(1)
        if not headers:
            SHEET.append_row(list(row_dict.keys()))
            headers = list(row_dict.keys())
        row = [row_dict.get(h,"") for h in headers]
        SHEET.append_row(row)
    except Exception as e:
        print("⚠️ Error guardando en Sheets:", e)

def clean_old_logs(days=7):
    try:
        vals = SHEET.get_all_records()
        if not vals:
            return
        df = pd.DataFrame(vals)
        if "Fecha" not in df.columns:
            return
        df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce")
        cutoff = now_et() - dt.timedelta(days=days)
        keep = df[df["Fecha"] >= cutoff]
        SHEET.clear()
        SHEET.append_row(list(keep.columns))
        for _, row in keep.iterrows():
            SHEET.append_row([row.get(c,"") for c in keep.columns])
        print(f"🧹 Limpieza hecha, {len(keep)} filas retenidas.")
    except Exception as e:
        print("⚠️ Error limpiando logs:", e)

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

    recipients = ALERT_DEFAULT
    if ticker.upper()=="DKNG":
        recipients = ALERT_DKNG
    elif ticker.upper() in MICRO_TICKERS:
        recipients = ALERT_MICROS

    subject = f"📊 Señal {ticker} {side} {entry} – {round(sniper_val,1)}%"
    body = f"{ticker} {side} @ {entry}\nProbFinal {pf}% | Estado: {estado}"

    send_mail_many(subject, body, recipients)

    row = {
        "Fecha": t.strftime("%Y-%m-%d"),
        "Hora": t.strftime("%H:%M:%S"),
        "Ticker": ticker,
        "Side": side,
        "Entry": entry,
        "ProbFinal": pf,
        "SniperScore": sniper_val,
        "Estado": estado
    }
    append_to_sheet(row)

    return row

# =========================
# ▶️ Main
# =========================
def main():
    print("🚀 Bot corriendo...")
    try:
        res = process_signal("DKNG", "buy", 30.0)
        print("Resultado:", res)
        clean_old_logs(7)  # limpieza semanal
    except Exception as e:
        print("Error en main:", e)

if __name__ == "__main__":
    main()
