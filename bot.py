# bot.py — Trading-Bot con señales por correo + registro en Google Sheets
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

# Conjuntos para clasificar mercados
MICRO_TICKERS = {"MES","MNQ","MYM","M2K","MGC","MCL","M6E","M6B","M6A"}
CRYPTO_TICKERS = {"BTCUSD","ETHUSD","SOLUSD","ADAUSD","XRPUSD"}
FOREX_RE = re.compile(r"^[A-Z]{6}$")

# Google Sheets
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
gs_raw = os.getenv("GOOGLE_SHEETS_JSON", "")
GS_JSON = None
if gs_raw:
    try:
        GS_JSON = json.loads(gs_raw)
    except Exception:
        try:
            # Si en dev pasaste una ruta al archivo JSON
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

# Routing de alertas (por defecto como pediste)
ALERT_DEFAULT = os.getenv("ALERT_DEFAULT", "gevem249@gmail.com")
ALERT_DKNG    = os.getenv("ALERT_DKNG", "gevem249@gmail.com,adri_touma@hotmail.com")
ALERT_MICROS  = os.getenv("ALERT_MICROS", "gevem249@gmail.com")   # micros -> tú

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
# 📈 Indicadores básicos
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
    """Heurística simple con EMAs y RSI."""
    if df is None or df.empty: 
        return 50.0
    close = df["Close"].squeeze()
    e13, e21 = ema(close, 13), ema(close, 21)
    r = rsi(close, 14).fillna(50).iloc[-1]
    trend = (e13.iloc[-1]-e21.iloc[-1])
    score = 50.0
    if side.lower()=="buy":
        if trend > 0: score += 20
        if 45 <= r <= 70: score += 15
        if r < 35: score -= 15
    else:
        if trend < 0: score += 20
        if 30 <= r <= 55: score += 15
        if r > 65: score -= 15
    return float(max(0.0, min(100.0, score)))

# =========================
# 📥 Datos de mercado (yfinance)
# =========================
def _map_micro_to_index(ticker: str) -> str:
    """Mapea algunos micros a índices de Yahoo para demo."""
    t = ticker.upper()
    return {
        "MES": "^GSPC",
        "MNQ": "^NDX",
        "MYM": "^DJI",
        "M2K": "^RUT",
    }.get(t, ticker)

def fetch_yf(ticker: str, interval: str, lookback: str):
    y = _map_micro_to_index(ticker)
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
# 🧮 Sniper (muy simple, usa 5m)
# =========================
def sniper_score(ticker, side):
    df5 = fetch_yf(ticker, "5m", "5d")
    base = frame_prob(df5, side) if df5 is not None and not df5.empty else 50.0
    return {"score": base, "frame_probs": prob_multi_frame(ticker, side)}

# =========================
# 📄 Google Sheets helpers
# =========================
HEADERS = [
    "FechaISO","HoraLocal","HoraRegistro","Ticker","Side","Entrada",
    "Prob_1m","Prob_5m","Prob_15m","Prob_1h","ProbFinal",
    "Estado","Resultado","Nota","Mercado","Recipients"
]

def ensure_headers():
    vals = SHEET.get_all_values()
    if not vals:
        SHEET.append_row(HEADERS)
        return
    current = vals[0]
    missing = [h for h in HEADERS if h not in current]
    if missing:
        new_headers = current + missing
        SHEET.update("A1", [new_headers])

def append_signal_row(row_dict: dict):
    ensure_headers()
    headers_live = SHEET.row_values(1)
    row = [row_dict.get(h, "") for h in headers_live]
    SHEET.append_row(row)

# =========================
# 🚦 Core: generar y notificar señal
# =========================
def process_signal(ticker: str, side: str, entry: float):
    t = now_et()
    market = classify_market(ticker)

    # Probabilidades por timeframe
    pm = prob_multi_frame(ticker, side)
    p1  = pm["per_frame"]["1m"]
    p5  = pm["per_frame"]["5m"]
    p15 = pm["per_frame"]["15m"]
    p1h = pm["per_frame"]["1h"]
    pf  = pm["final"]

    # Sniper simple (usa 5m)
    sn = sniper_score(ticker, side)
    sniper_val = sn["score"]

    estado = "Pre" if sniper_val >= 80 else "Descartada"

    # Routing de emails
    tkr = ticker.upper()
    if tkr == "DKNG":
        recipients = ALERT_DKNG                      # tú + Adri
    elif tkr in MICRO_TICKERS:
        recipients = ALERT_MICROS                    # micros -> tú
    else:
        recipients = ALERT_DEFAULT                   # todos los demás -> tú

    # Guarda en Google Sheets
    try:
        row = {
            "FechaISO": t.strftime("%Y-%m-%d"),
            "HoraLocal": t.strftime("%H:%M"),
            "HoraRegistro": t.strftime("%H:%M:%S"),
            "Ticker": tkr,
            "Side": side.title(),
            "Entrada": entry,
            "Prob_1m": round(p1,1),
            "Prob_5m": round(p5,1),
            "Prob_15m": round(p15,1),
            "Prob_1h": round(p1h,1),
            "ProbFinal": round(pf,1),
            "Estado": estado,
            "Resultado": "-",
            "Nota": f"sniper:{round(sniper_val,1)}",
            "Mercado": market,
            "Recipients": recipients,
        }
        append_signal_row(row)
    except Exception as e:
        # No romper el envío si falla el sheet
        try:
            dbg = GC.open_by_key(SPREADSHEET_ID).worksheet("debug")
        except gspread.WorksheetNotFound:
            dbg = GC.open_by_key(SPREADSHEET_ID).add_worksheet("debug", rows=2000, cols=10)
            dbg.update("A1", [["ts","error","ctx"]])
        dbg.append_row([t.isoformat(), str(e), f"append_signal_row {ticker}"])

    # Email
    subject = f"📊 Señal {ticker} {side} {entry} – {round(sniper_val,1)}%"
    body = (
        f"{ticker} {side} @ {entry}\n"
        f"ProbFinal: {pf}% (1m {p1} / 5m {p5} / 15m {p15} / 1h {p1h})\n"
        f"Estado: {estado} | Mercado: {market}\n"
        f"Destinatarios: {recipients}"
    )
    send_mail_many(subject, body, recipients)

    return {"ticker":ticker,"side":side,"entry":entry,"estado":estado,"recipients":recipients}

# =========================
# ▶️ Main (demo)
# =========================
def main():
    print("🚀 Bot corriendo...")
    try:
        # DEMO: dispara una señal de DKNG para ver correo + registro en Sheet
        res = process_signal("DKNG", "buy", 30.0)
        print("Resultado:", res)
    except Exception as e:
        print("Error en main:", e)
        tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
        # intenta log a debug
        try:
            dbg = GC.open_by_key(SPREADSHEET_ID).worksheet("debug")
        except gspread.WorksheetNotFound:
            dbg = GC.open_by_key(SPREADSHEET_ID).add_worksheet("debug", rows=2000, cols=10)
            dbg.update("A1", [["ts","error","trace"]])
        dbg.append_row([now_et().isoformat(), str(e), tb[:1800]])

if __name__ == "__main__":
    main()
