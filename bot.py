# bot.py — Trading-Bot completo con Sniper + Recalibración + Confirmaciones + Debug
import os, json, re, pytz, datetime as dt, smtplib, sys
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
if gs_raw:
    try:
        GS_JSON = json.loads(gs_raw)
    except Exception:
        try:
            GS_JSON = json.loads(open(gs_raw).read())
        except Exception:
            GS_JSON = None
else:
    GS_JSON = None

if not SPREADSHEET_ID or not GS_JSON:
    raise RuntimeError("Falta SPREADSHEET_ID o GOOGLE_SHEETS_JSON en secrets/env")

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

# Debug flag
DEBUG_MODE = "--debug" in sys.argv

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
    log_debug({"event":"email_sent","to":to_emails,"subject":subject})

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
# Sniper extra
# =========================
def atr(df, period=14):
    if df is None or df.empty: return 0.0
    high = df["High"].squeeze()
    low = df["Low"].squeeze()
    close = df["Close"].squeeze()
    prev_close = close.shift(1)
    tr1 = (high - low).abs()
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period).mean().iloc[-1] if len(tr)>=period else tr.mean()

def macd_signal(df, fast=12, slow=26, signal=9):
    if df is None or df.empty: return 0.0
    close = df["Close"].squeeze()
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    macd_sig = macd.ewm(span=signal, adjust=False).mean()
    return (macd.iloc[-1] - macd_sig.iloc[-1]) if len(macd)>signal else 0.0

def detect_candle_pattern(df):
    if df is None or df.empty: return ("none", 0)
    o = df["Open"].squeeze().iloc[-1]
    h = df["High"].squeeze().iloc[-1]
    l = df["Low"].squeeze().iloc[-1]
    c = df["Close"].squeeze().iloc[-1]
    body = abs(c - o)
    range_ = h - l + 1e-9
    lower_wick = min(o,c) - l
    upper_wick = h - max(o,c)
    if body / range_ < 0.1: return ("doji", -5)
    if lower_wick > 2 * body and upper_wick < 0.5*body: return ("hammer", 8 if c>o else -8)
    if len(df) >= 2:
        o2 = df["Open"].squeeze().iloc[-2]
        c2 = df["Close"].squeeze().iloc[-2]
        if c > o and c2 < o2 and (c - o) > (o2 - c2): return ("bull_engulf", 12)
        if c < o and c2 > o2 and (o - c) > (c2 - o2): return ("bear_engulf", -12)
    return ("none", 0)

def support_resistance_basic(df, lookback=50):
    if df is None or df.empty or len(df) < 3: return (None, None)
    close = df["Close"].squeeze().iloc[-1]
    highs = df["High"].squeeze().tail(lookback)
    lows = df["Low"].squeeze().tail(lookback)
    resist = highs.max()
    support = lows.min()
    ds = (close - support)/support*100 if support>0 else None
    dr = (resist - close)/resist*100 if resist>0 else None
    return (ds, dr)

def compute_sl_tp(entry, atr_val, side, rr=2.0, atr_multiplier_sl=1.0):
    if not atr_val or atr_val==0:
        if side.lower()=="buy":
            return (round(entry*0.995,6), round(entry*1.01,6))
        else:
            return (round(entry*1.005,6), round(entry*0.99,6))
    risk = atr_val * atr_multiplier_sl
    if side.lower()=="buy":
        sl = entry - risk
        tp = entry + rr * risk
    else:
        sl = entry + risk
        tp = entry - rr * risk
    return (round(sl,6), round(tp,6))

# =========================
# Google Sheets Headers
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
    elif vals[0] != HEADERS: SHEET.update("A1", [HEADERS])

def append_signal(row_dict: dict):
    ensure_headers()
    row = [row_dict.get(k,"") for k in HEADERS]
    SHEET.append_row(row)

def find_rows(filter_fn):
    records = SHEET.get_all_records()
    out = []
    for i, r in enumerate(records, start=2):
        try:
            if filter_fn(r): out.append((i, r))
        except: continue
    return out

# =========================
# Debug logging
# =========================
def log_debug(row_dict: dict):
    try:
        if DEBUG_MODE:
            print("DEBUG:", row_dict)
        try:
            dbg = GC.open_by_key(SPREADSHEET_ID).worksheet("debug")
        except gspread.WorksheetNotFound:
            dbg = GC.open_by_key(SPREADSHEET_ID).add_worksheet(title="debug", rows=2000, cols=40)
            dbg.update("A1", [list(row_dict.keys())])
        dbg.append_row([str(row_dict.get(k,"")) for k in row_dict.keys()])
    except Exception as e:
        if DEBUG_MODE:
            print("⚠️ Debug logging failed:", e)

# =========================
# Core process_signal
# =========================
def process_signal(ticker: str, side: str, entry: float):
    t = now_et()
    market = classify_market(ticker)
    pm = prob_multi_frame(ticker, side)
    p1, p5, p15, p1h, pf = pm["per_frame"]["1m"], pm["per_frame"]["5m"], pm["per_frame"]["15m"], pm["per_frame"]["1h"], pm["final"]

    pat, pat_score = detect_candle_pattern(fetch_yf(ticker,"5m","5d"))
    macd_val = macd_signal(fetch_yf(ticker,"15m","1mo"))
    ds, dr = support_resistance_basic(fetch_yf(ticker,"15m","1mo"))
    sr_score = 0
    if ds is not None:
        if side.lower()=="buy" and ds < 1.0: sr_score += 6
        if side.lower()=="sell" and dr < 1.0: sr_score += 6
    atr_val = atr(fetch_yf(ticker,"5m","5d"))

    sl,tp = compute_sl_tp(entry, atr_val, side)

    sniper_val = round((pf+pat_score+sr_score)/3,1)
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
        "pattern": pat,"pat_score": pat_score,"macd_val": macd_val,"sr_score": sr_score,"atr": atr_val,
        "SL": sl,"TP": tp,"Recipients": recipients,"ScheduledConfirm": scheduled_confirm
    }
    append_signal(row)
    log_debug({"event":"signal","row":row})

    if estado=="Pre" and recipients:
        send_mail_many(f"📊 Pre-señal {ticker} {side} {entry} – {sniper_val}%",
            f"{ticker} {side} @ {entry}\nProb final:{pf}% Sniper:{sniper_val}%\nSL:{sl} TP:{tp}\nConfirm:{scheduled_confirm}",recipients)
    return row

# =========================
# Confirmaciones
# =========================
def check_pending_confirmations():
    now = now_et()
    pending = find_rows(lambda r: r.get("Estado")=="Pre" and r.get("ScheduledConfirm"))
    for idx,r in pending:
        sc = r.get("ScheduledConfirm")
        if not sc: continue
        sc_dt = dt.datetime.fromisoformat(sc).astimezone(TZ)
        if sc_dt <= now:
            ticker = r.get("Ticker"); side=r.get("Side"); entry=float(r.get("Entrada") or 0)
            sn = prob_multi_frame(ticker, side)
            pf2 = sn["final"]
            estado2 = "Confirmado" if pf2>=80 else "Cancelado"
            SHEET.update_cell(idx, HEADERS.index("Estado")+1, estado2)
            log_debug({"event":"confirmation","ticker":ticker,"estado":estado2})

# =========================
# Recalibración
# =========================
def recalibrate_weights_from_sheet(n_recent=500, alpha=0.25):
    """
    Recalibra pesos de señales (base/pat/macd/sr) usando histórico.
    Guarda último set en hoja 'meta'. Devuelve dict con pesos o None.
    """
    try:
        rows = SHEET.get_all_records()
        if not rows: 
            log_debug({"event":"recalibrate","status":"no_rows"})
            return None
        df = pd.DataFrame(rows).tail(n_recent)
        needed = ["ProbFinal","pat_score","macd_val","sr_score","Resultado"]
        if not all(c in df.columns for c in needed):
            log_debug({"event":"recalibrate","status":"missing_columns"})
            return None
        df = df.dropna(subset=["Resultado"])
        df["y"] = df["Resultado"].apply(lambda x: 1 if str(x).strip().lower()=="win"=="win" else (1 if str(x).strip().lower()=="win" else 0))
        if df["y"].sum()==0:
            log_debug({"event":"recalibrate","status":"no_wins"})
            return None

        cors = {
            "base": abs(df["ProbFinal"].corr(df["y"]) or 0),
            "pat":  abs(df["pat_score"].corr(df["y"]) or 0),
            "macd": abs(df["macd_val"].corr(df["y"]) or 0),
            "sr":   abs(df["sr_score"].corr(df["y"]) or 0)
        }
        s = sum(cors.values())+1e-9
        norm = {k: cors[k]/s for k in cors}
        sm = {
            "w_base": round(alpha*norm["base"]+(1-alpha)*0.5,3),
            "w_pat":  round(alpha*norm["pat"] +(1-alpha)*0.2,3),
            "w_macd": round(alpha*norm["macd"]+(1-alpha)*0.15,3),
            "w_sr":   round(alpha*norm["sr"]  +(1-alpha)*0.15,3),
            "ts": now_et().isoformat()
        }
        try:
            ws = GC.open_by_key(SPREADSHEET_ID).worksheet("meta")
        except gspread.WorksheetNotFound:
            ws = GC.open_by_key(SPREADSHEET_ID).add_worksheet("meta", 100, 20)
            ws.update("A1", [["w_base","w_pat","w_macd","w_sr","ts"]])
        ws.append_row([sm["w_base"], sm["w_pat"], sm["w_macd"], sm["w_sr"], sm["ts"]])
        log_debug({"event":"recalibrate","weights":sm})
        return sm
    except Exception as e:
        log_debug({"event":"recalibrate_error","error":str(e)})
        return None

# =========================
# Util: último precio como entrada
# =========================
def latest_price(ticker: str) -> float:
    df = fetch_yf(ticker, "1m", "1d")
    try:
        return float(df["Close"].iloc[-1])
    except Exception:
        return 0.0

# =========================
# ▶️ Main
# =========================
def main():
    ensure_headers()

    # Señales de prueba para equity y micros (usa último precio como entrada)
    try:
        dkng_px = latest_price("DKNG")
        if dkng_px > 0:
            process_signal("DKNG", "Buy", round(dkng_px, 4))
    except Exception as e:
        log_debug({"event":"seed_signal_error","ticker":"DKNG","error":str(e)})

    try:
        mes_px = latest_price("MES")
        if mes_px > 0:
            process_signal("MES", "Sell", round(mes_px, 2))
    except Exception as e:
        log_debug({"event":"seed_signal_error","ticker":"MES","error":str(e)})

    try:
        mnq_px = latest_price("MNQ")
        if mnq_px > 0:
            process_signal("MNQ", "Buy", round(mnq_px, 2))
    except Exception as e:
        log_debug({"event":"seed_signal_error","ticker":"MNQ","error":str(e)})

    # Confirmaciones pendientes
    check_pending_confirmations()

if __name__=="__main__":
    main()
