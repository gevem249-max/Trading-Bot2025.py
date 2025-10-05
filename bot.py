# bot.py — Trading-Bot con Sniper + Confirmaciones + Recalibración + Debug logs
import os, json, re, pytz, datetime as dt, smtplib, traceback
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
GS_JSON = json.loads(os.getenv("GOOGLE_SHEETS_JSON"))
CREDS = Credentials.from_service_account_info(GS_JSON, scopes=["https://www.googleapis.com/auth/spreadsheets"])
GC = gspread.authorize(CREDS)
SHEET = GC.open_by_key(SPREADSHEET_ID).sheet1

# Gmail
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_PASS = os.getenv("GMAIL_APP_PASS")

# Routing de alertas
ALERT_DKNG = os.getenv("ALERT_DKNG")
ALERT_MICROS = os.getenv("ALERT_MICROS")
ALERT_DEFAULT = os.getenv("ALERT_DEFAULT", GMAIL_USER)

# =========================
# 🧭 Tiempo y mercado
# =========================
def now_et():
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
    try:
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
    except Exception as e:
        log_debug({"action":"send_mail","error":str(e),"trace":traceback.format_exc()})

# =========================
# 📈 Indicadores
# =========================
def ema(series, span): return series.ewm(span=span, adjust=False).mean()

def rsi(series, period=14):
    series = series.squeeze()
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
    except Exception as e:
        log_debug({"action":"fetch_yf","ticker":ticker,"error":str(e)})
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
# Debug logging
# =========================
def log_debug(info: dict):
    try:
        dbg = None
        try:
            dbg = GC.open_by_key(SPREADSHEET_ID).worksheet("debug")
        except gspread.WorksheetNotFound:
            dbg = GC.open_by_key(SPREADSHEET_ID).add_worksheet("debug", rows=1000, cols=20)
            dbg.update("A1", [list(info.keys())])
        dbg.append_row([str(info.get(k,"")) for k in info.keys()])
    except Exception as e:
        print("⚠️ log_debug error:", e)

# =========================
# Señales
# =========================
HEADERS = [
    "FechaISO","HoraLocal","HoraRegistro","Ticker","Side","Entrada",
    "Prob_1m","Prob_5m","Prob_15m","Prob_1h","ProbFinal",
    "ProbClasificación","Estado","Tipo","Resultado","Nota","Mercado",
    "SL","TP","Recipients","ScheduledConfirm"
]

def ensure_headers():
    vals = SHEET.get_all_values()
    if not vals: SHEET.append_row(HEADERS)
    elif vals[0] != HEADERS: SHEET.update("A1", [HEADERS])

def append_signal(row_dict: dict):
    ensure_headers()
    SHEET.append_row([row_dict.get(k,"") for k in HEADERS])

# =========================
# Core process_signal
# =========================
def process_signal(ticker: str, side: str, entry: float):
    try:
        t = now_et()
        market = classify_market(ticker)
        pm = prob_multi_frame(ticker, side)
        p1, p5, p15, p1h, pf = pm["per_frame"]["1m"], pm["per_frame"]["5m"], pm["per_frame"]["15m"], pm["per_frame"]["1h"], pm["final"]

        sniper_val = round((pf),1)
        clasif = "≥80" if pf >= 80 else "<80"
        estado = "Pre" if sniper_val >= 80 else "Descartada"
        scheduled_confirm = (t+dt.timedelta(minutes=5)).isoformat() if estado=="Pre" else ""

        recipients = ALERT_DEFAULT
        if ticker.upper()=="DKNG" and ALERT_DKNG: recipients = ALERT_DKNG
        elif ticker.upper() in MICRO_TICKERS and ALERT_MICROS: recipients = ALERT_MICROS

        row = {
            "FechaISO": t.strftime("%Y-%m-%d"),
            "HoraLocal": t.strftime("%H:%M"),
            "HoraRegistro": t.strftime("%H:%M:%S"),
            "Ticker": ticker.upper(),
            "Side": side.title(),
            "Entrada": entry,
            "Prob_1m": p1,"Prob_5m": p5,"Prob_15m": p15,"Prob_1h": p1h,
            "ProbFinal": pf,"ProbClasificación": clasif,
            "Estado": estado,"Tipo": "Pre" if estado=="Pre" else "Backtest",
            "Resultado": "-","Nota": f"sniper:{sniper_val}","Mercado": market,
            "SL": round(entry*0.99,6),"TP": round(entry*1.02,6),
            "Recipients": recipients,"ScheduledConfirm": scheduled_confirm
        }
        append_signal(row)
        log_debug({**row,"action":"process_signal"})

        if estado=="Pre" and recipients:
            send_mail_many(f"📊 Pre-señal {ticker} {side} {entry} – {sniper_val}%",
                f"{ticker} {side} @ {entry}\nProb final:{pf}% Sniper:{sniper_val}%\nConfirm:{scheduled_confirm}",recipients)
        return row
    except Exception as e:
        log_debug({"action":"process_signal","ticker":ticker,"error":str(e),"trace":traceback.format_exc()})

# =========================
# ▶️ Main
# =========================
def main():
    ensure_headers()
    process_signal("DKNG","Buy",45.3)
    process_signal("MES","Buy",5300.0)   # ejemplo micros
    process_signal("EURUSD","Sell",1.085) # ejemplo forex

if __name__=="__main__":
    main()
