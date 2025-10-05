import os, json, time, imaplib, email, re, smtplib, pytz, datetime as dt
from email.mime.text import MIMEText

import pandas as pd
import numpy as np
import yfinance as yf

import gspread
from google.oauth2.service_account import Credentials

# =========================
# 🔧 Configuración
# =========================
TZ = pytz.timezone("America/New_York")  # Zona horaria NJ/ET
MICRO_TICKERS = {"MES","MNQ","MYM","M2K","MGC","MCL","M6E","M6B","M6A"}
CRYPTO_TICKERS = {"BTCUSD","ETHUSD","SOLUSD","ADAUSD","XRPUSD"}
FOREX_RE = re.compile(r"^[A-Z]{6}$")  # EURUSD, GBPUSD, etc.

# Google Sheets
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
GS_JSON = json.loads(os.getenv("GOOGLE_SHEETS_JSON"))
CREDS = Credentials.from_service_account_info(GS_JSON, scopes=["https://www.googleapis.com/auth/spreadsheets"])
GC = gspread.authorize(CREDS)
SHEET = GC.open_by_key(SPREADSHEET_ID).sheet1

# Gmail
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_PASS = os.getenv("GMAIL_APP_PASS")

# =========================
# 🧭 Utilidades de tiempo/mercados
# =========================
def now_et():
    return dt.datetime.now(TZ)

def classify_market(ticker: str) -> str:
    t = ticker.upper().replace("/", "")
    if t in MICRO_TICKERS: return "cme_micro"
    if t in CRYPTO_TICKERS: return "crypto"
    if FOREX_RE.match(t) and t not in CRYPTO_TICKERS: return "forex"
    return "equity"

def is_market_open(market: str, t: dt.datetime) -> bool:
    wd, h, m = t.weekday(), t.hour, t.minute
    if market == "equity": return wd < 5 and (9*60+30) <= (h*60+m) < (16*60)
    if market == "cme_micro":
        if wd == 5: return False
        if wd == 6 and h < 18: return False
        if wd == 4 and h >= 17: return False
        if h == 17: return False
        return True
    if market == "forex":
        if wd == 5: return False
        if wd == 6 and h < 17: return False
        if wd == 4 and h >= 17: return False
        return True
    if market == "crypto": return True
    return False

# =========================
# 📬 Email
# =========================
def send_mail(subject: str, body: str, to_email: str=None):
    to_email = to_email or GMAIL_USER
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = GMAIL_USER
    msg["To"] = to_email
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as srv:
        srv.login(GMAIL_USER, GMAIL_PASS)
        srv.sendmail(GMAIL_USER, [to_email], msg.as_string())

# =========================
# 📈 Probabilidad multi-timeframe
# =========================
def ema(series, span): 
    return series.ewm(span=span, adjust=False).mean()

def rsi(series, period=14):
    delta = series.diff()
    up, down = np.where(delta>0, delta, 0.0), np.where(delta<0, -delta, 0.0)
    roll_up = pd.Series(up, index=series.index).rolling(period).mean()
    roll_down = pd.Series(down, index=series.index).rolling(period).mean()
    rs = roll_up / (roll_down + 1e-9)
    return 100 - (100/(1+rs))

def frame_prob(df: pd.DataFrame, side: str) -> float:
    if df.empty: return 50.0
    close, e8, e21 = df["Close"], ema(df["Close"], 8), ema(df["Close"], 21)
    r, trend, score = rsi(close, 14).fillna(50).iloc[-1], (e8.iloc[-1]-e21.iloc[-1]), 50.0
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
    return yf.download(y, period=lookback, interval=interval, progress=False)

def prob_multi_frame(ticker: str, side: str) -> dict:
    frames = {"1m":("1m","2d"),"5m":("5m","5d"),"15m":("15m","1mo"),"1h":("60m","3mo")}
    probs = {k: frame_prob(fetch_yf(ticker,itv,lb), side) for k,(itv,lb) in frames.items()}
    final = round((probs["1m"]*0.2 + probs["5m"]*0.4 + probs["15m"]*0.25 + probs["1h"]*0.15),1)
    return {"per_frame":probs,"final":final}

# =========================
# 📑 Google Sheets IO
# =========================
HEADERS = [
    "FechaISO","HoraLocal","HoraRegistro","Ticker","Side","Entrada",
    "Prob_1m","Prob_5m","Prob_15m","Prob_1h","ProbFinal",
    "ProbClasificación","Estado","Tipo","Resultado","Nota","Mercado"
]

def ensure_headers():
    vals = SHEET.get_all_values()
    if not vals: 
        SHEET.append_row(HEADERS)
    elif vals[0] != HEADERS: 
        SHEET.update("A1", [HEADERS])

def append_signal(row_dict: dict):
    ensure_headers()
    SHEET.append_row([row_dict.get(k,"") for k in HEADERS])

def update_row_status(ticker, fecha_iso, estado=None, resultado=None, nota=None):
    vals = SHEET.get_all_values()
    if not vals: return
    headers, rows = vals[0], vals[1:]
    idx_map = {h:i for i,h in enumerate(headers)}
    for i, r in enumerate(rows, start=2):
        if r[idx_map["Ticker"]]==ticker and r[idx_map["FechaISO"]]==fecha_iso:
            if estado: SHEET.update_cell(i, idx_map["Estado"]+1, estado)
            if resultado: SHEET.update_cell(i, idx_map["Resultado"]+1, resultado)
            if nota: SHEET.update_cell(i, idx_map["Nota"]+1, nota)
            break

# =========================
# 🚦 Motor principal
# =========================
def process_signal(ticker: str, side: str, entry: float, notify_email: str=None):
    t, market = now_et(), classify_market(ticker)
    pm = prob_multi_frame(ticker, side)
    p1, p5, p15, p1h, pf = pm["per_frame"]["1m"], pm["per_frame"]["5m"], pm["per_frame"]["15m"], pm["per_frame"]["1h"], pm["final"]

    clasif = "≥80" if pf >= 80 else "<80"
    base = {
        "FechaISO": t.strftime("%Y-%m-%d"),
        "HoraLocal": t.strftime("%H:%M"),
        "HoraRegistro": t.strftime("%H:%M:%S"),
        "Ticker": ticker.upper(),
        "Side": side.title(),
        "Entrada": entry,
        "Prob_1m": round(p1,1),"Prob_5m": round(p5,1),"Prob_15m": round(p15,1),"Prob_1h": round(p1h,1),
        "ProbFinal": round(pf,1),"ProbClasificación": clasif,
        "Estado": "Pre" if pf>=80 else "Descartada",
        "Tipo": "Pre" if pf>=80 else "Backtest",
        "Resultado": "-","Nota":"","Mercado": market
    }
    append_signal(base)

    # Notificación opcional
    if notify_email:
        send_mail(
            f"Señal {ticker} {side} {entry} – {pf}%",
            f"Ticker: {ticker}\nLado: {side}\nEntrada: {entry}\nProbFinal: {pf}%\nClasificación: {clasif}",
            notify_email
        )

# =========================
# ▶️ Entry
# =========================
def main():
    ensure_headers()
    # Ejemplo manual (descomenta o cambia por alertas reales)
    process_signal("DKNG","Buy",45.30, notify_email=GMAIL_USER)

if __name__=="__main__":
    main()
