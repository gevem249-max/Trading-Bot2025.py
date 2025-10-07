# bot.py — Trading-Bot para DKNG y Micros con Sheets + Gmail

import os, json, re, pytz, datetime as dt, smtplib, traceback
import pandas as pd, numpy as np, yfinance as yf, gspread
from email.mime.text import MIMEText
from google.oauth2.service_account import Credentials

# =========================
# 🔧 Configuración
# =========================
TZ = pytz.timezone("America/New_York")
MICRO_TICKERS = {"MES","MNQ","MYM","M2K"}   # micros principales
FOREX_RE = re.compile(r"^[A-Z]{6}$")

SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
GS_JSON = json.loads(os.getenv("GOOGLE_SHEETS_JSON", "{}"))

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
ALERT_DKNG = os.getenv("ALERT_DKNG")
ALERT_MICROS = os.getenv("ALERT_MICROS")
ALERT_DEFAULT = os.getenv("ALERT_DEFAULT", GMAIL_USER)

# =========================
# 🧭 Utils tiempo/mercado
# =========================
def now_et(): return dt.datetime.now(TZ)

# =========================
# 📬 Email
# =========================
def send_mail(subject, body, recipients):
    if not recipients or not GMAIL_USER or not GMAIL_PASS: return
    emails = [e.strip() for e in recipients.split(",") if e.strip()]
    if not emails: return
    msg = MIMEText(body)
    msg["Subject"], msg["From"], msg["To"] = subject, GMAIL_USER, ", ".join(emails)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as srv:
        srv.login(GMAIL_USER, GMAIL_PASS)
        srv.sendmail(GMAIL_USER, emails, msg.as_string())

# =========================
# 📈 Indicadores
# =========================
def ema(series, span): return series.ewm(span=span, adjust=False).mean()

def rsi(series, period=14):
    delta = series.diff()
    up, down = np.where(delta>0, delta, 0.0), np.where(delta<0, -delta, 0.0)
    roll_up = pd.Series(up, index=series.index).rolling(period).mean()
    roll_down = pd.Series(down, index=series.index).rolling(period).mean()
    rs = roll_up / (roll_down + 1e-9)
    return 100 - (100/(1+rs))

def frame_prob(df, side):
    if df is None or df.empty: return 50.0
    close = df["Close"].squeeze()
    e8, e21 = ema(close,8), ema(close,21)
    r = rsi(close,14).fillna(50).iloc[-1]
    score = 50
    if side.lower()=="buy":
        if e8.iloc[-1]>e21.iloc[-1]: score += 20
        if 45 <= r <= 70: score += 15
    else:
        if e8.iloc[-1]<e21.iloc[-1]: score += 20
        if 30 <= r <= 55: score += 15
    return max(0,min(100,score))

def fetch_yf(ticker, interval, lookback):
    m = {"MES":"^GSPC","MNQ":"^NDX","MYM":"^DJI","M2K":"^RUT","DKNG":"DKNG"}
    y = m.get(ticker.upper(), ticker)
    try: return yf.download(y, period=lookback, interval=interval, progress=False, threads=False)
    except: return pd.DataFrame()

def prob_multi_frame(ticker, side):
    frames = {"1m":("1m","2d"),"5m":("5m","5d")}
    probs = {k:frame_prob(fetch_yf(ticker,itv,lb),side) for k,(itv,lb) in frames.items()}
    final = round(sum(probs.values())/len(probs),1)
    return {"per_frame":probs,"final":final}

# =========================
# 📊 Google Sheets helpers
# =========================
HEADERS = ["Fecha","Hora","Ticker","Side","Entrada","Prob_1m","Prob_5m","ProbFinal","Estado"]

def ensure_headers():
    vals = SHEET.get_all_values()
    if not vals: SHEET.append_row(HEADERS)

def append_signal(row):
    ensure_headers()
    SHEET.append_row([row.get(h,"") for h in HEADERS])

# =========================
# 🚀 Señal
# =========================
def process_signal(ticker, side, entry):
    t = now_et()
    pm = prob_multi_frame(ticker, side)
    pf = pm["final"]
    estado = "Pre" if pf >= 80 else "Descartada"

    row = {
        "Fecha":t.strftime("%Y-%m-%d"),
        "Hora":t.strftime("%H:%M:%S"),
        "Ticker":ticker,
        "Side":side,
        "Entrada":entry,
        "Prob_1m":pm["per_frame"]["1m"],
        "Prob_5m":pm["per_frame"]["5m"],
        "ProbFinal":pf,
        "Estado":estado
    }
    append_signal(row)

    recips = ALERT_DEFAULT
    if ticker.upper()=="DKNG" and ALERT_DKNG: recips = ALERT_DKNG
    elif ticker.upper() in MICRO_TICKERS and ALERT_MICROS: recips = ALERT_MICROS

    subject = f"📊 Señal {ticker} {side} {entry} – {pf}%"
    body = f"{ticker} {side} @ {entry}\nProbFinal {pf}% | Estado: {estado}"
    send_mail(subject, body, recips)

    return row

# =========================
# ▶️ Main
# =========================
def main():
    print("🚀 Bot DKNG + Micros activo...")
    try:
        # ejemplo: DKNG long
        res = process_signal("DKNG","buy",30.0)
        print("Resultado:",res)
    except Exception as e:
        print("❌ Error:",e)
        traceback.print_exc()

if __name__=="__main__":
    main()
