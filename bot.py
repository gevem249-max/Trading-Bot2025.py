# bot.py — Trading-Bot completo (Sniper + confirmaciones + recalibración)
import os, json, re, pytz, datetime as dt, smtplib, argparse
from email.mime.text import MIMEText

import pandas as pd
import numpy as np
import yfinance as yf

import gspread
from google.oauth2.service_account import Credentials

# =========================
# 🔧 Config / env
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
    raise RuntimeError("Falta SPREADSHEET_ID o GOOGLE_SHEETS_JSON en secrets/env")

CREDS = Credentials.from_service_account_info(
    GS_JSON, scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
GC = gspread.authorize(CREDS)
SHEET = GC.open_by_key(SPREADSHEET_ID).sheet1

# Gmail
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_PASS = os.getenv("GMAIL_APP_PASS")

# Routing
ALERT_DKNG   = os.getenv("ALERT_DKNG")                 # "mail1@x.com,mail2@y.com"
ALERT_MICROS = os.getenv("ALERT_MICROS")               # idem
ALERT_DEFAULT= os.getenv("ALERT_DEFAULT", GMAIL_USER)  # fallback

# =========================
# ⏱️ Tiempo/Mercado
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
    if market == "equity":
        return wd < 5 and (9*60+30) <= (h*60+m) < (16*60)
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
    if market == "crypto":
        return True
    return False

# =========================
# ✉️ Email
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
# 📈 Indicadores base
# =========================
def ema(series, span): return series.ewm(span=span, adjust=False).mean()

def rsi(series, period=14):
    s = series.squeeze()
    delta = s.diff()
    up = np.where(delta > 0, delta, 0.0)
    down = np.where(delta < 0, -delta, 0.0)
    roll_up = pd.Series(up, index=s.index).rolling(period).mean()
    roll_down = pd.Series(down, index=s.index).rolling(period).mean()
    rs = roll_up / (roll_down + 1e-9)
    return 100 - (100/(1+rs))

def frame_prob(df: pd.DataFrame, side: str) -> float:
    if df is None or df.empty: return 50.0
    close = df["Close"].squeeze()
    e8, e21 = ema(close, 8), ema(close, 21)
    r = rsi(close, 14).fillna(50).iloc[-1]
    trend = (e8.iloc[-1] - e21.iloc[-1])
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
    frames = {"1m":("1m","2d"), "5m":("5m","5d"), "15m":("15m","1mo"), "1h":("60m","3mo")}
    probs = {}
    for k,(itv,lb) in frames.items():
        probs[k] = frame_prob(fetch_yf(ticker, itv, lb), side)
    if not weights:
        weights = {"1m":0.2,"5m":0.4,"15m":0.25,"1h":0.15}
    final = round(sum(probs[k]*weights.get(k,0) for k in probs), 1)
    return {"per_frame": probs, "final": final}

# =========================
# 🔎 Sniper: ATR, MACD, patrones, S/R
# =========================
def atr(df, period=14):
    if df is None or df.empty: return 0.0
    h = df["High"].squeeze(); l = df["Low"].squeeze(); c = df["Close"].squeeze()
    pc = c.shift(1)
    tr = pd.concat([(h-l).abs(), (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean().iloc[-1] if len(tr)>=period else tr.mean()

def macd_signal(df, fast=12, slow=26, signal=9):
    if df is None or df.empty: return 0.0
    c = df["Close"].squeeze()
    macd = c.ewm(span=fast, adjust=False).mean() - c.ewm(span=slow, adjust=False).mean()
    macd_sig = macd.ewm(span=signal, adjust=False).mean()
    return (macd.iloc[-1] - macd_sig.iloc[-1]) if len(macd)>signal else 0.0

def detect_candle_pattern(df):
    if df is None or df.empty: return ("none", 0)
    o = df["Open"].squeeze().iloc[-1]; h=df["High"].squeeze().iloc[-1]
    l = df["Low"].squeeze().iloc[-1];  c=df["Close"].squeeze().iloc[-1]
    body = abs(c-o); rng = h-l+1e-9
    lw = min(o,c)-l; uw = h-max(o,c)
    if body/rng < 0.1: return ("doji", -5)
    if lw > 2*body and uw < 0.5*body: return ("hammer", 8 if c>o else -8)
    if len(df)>=2:
        o2 = df["Open"].squeeze().iloc[-2]; c2=df["Close"].squeeze().iloc[-2]
        if c>o and c2<o2 and (c-o)>(o2-c2): return ("bull_engulf", 12)
        if c<o and c2>o2 and (o-c)>(c2-o2): return ("bear_engulf", -12)
    return ("none", 0)

def support_resistance_basic(df, lookback=50):
    if df is None or df.empty or len(df)<3: return (None, None)
    c = df["Close"].squeeze().iloc[-1]
    highs = df["High"].squeeze().tail(lookback)
    lows  = df["Low"].squeeze().tail(lookback)
    resist = highs.max(); support = lows.min()
    ds = (c - support)/support*100 if support>0 else None
    dr = (resist - c)/resist*100 if resist>0 else None
    return (ds, dr)

def compute_sl_tp(entry, atr_val, side, rr=2.0, atr_multiplier_sl=1.0):
    if not atr_val:
        if side.lower()=="buy":  return (round(entry*0.995,6), round(entry*1.01,6))
        else:                    return (round(entry*1.005,6), round(entry*0.99,6))
    risk = atr_val * atr_multiplier_sl
    if side.lower()=="buy":
        sl = entry - risk; tp = entry + rr*risk
    else:
        sl = entry + risk; tp = entry - rr*risk
    return (round(sl,6), round(tp,6))

# =========================
# 📄 Sheets helpers
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
    if not vals:
        SHEET.append_row(HEADERS)
    elif vals[0] != HEADERS:
        SHEET.update("A1", [HEADERS])

def append_signal(row_dict: dict):
    ensure_headers()
    SHEET.append_row([row_dict.get(k,"") for k in HEADERS])

def update_row_status_by_index(row_index:int, updates:dict):
    vals = SHEET.get_all_values()
    if row_index < 2 or row_index > len(vals): return
    headers = vals[0]
    for k,v in updates.items():
        if k in headers:
            col = headers.index(k)+1
            SHEET.update_cell(row_index, col, v)

def find_rows(filter_fn):
    records = SHEET.get_all_records()
    out = []
    for i, r in enumerate(records, start=2):
        try:
            if filter_fn(r): out.append((i, r))
        except Exception:
            continue
    return out

# =========================
# 🧪 Meta (pesos) + Threshold
# =========================
def read_meta_weights():
    try:
        ws = GC.open_by_key(SPREADSHEET_ID).worksheet("meta")
        rows = ws.get_all_records()
        if not rows: return None
        last = pd.DataFrame(rows).tail(1).iloc[0].to_dict()
        return {
            "1m": float(last.get("w_1m",0.2)),
            "5m": float(last.get("w_5m",0.4)),
            "15m": float(last.get("w_15m",0.25)),
            "1h": float(last.get("w_1h",0.15)),
            "base": float(last.get("w_base",0.5)),
            "pat": float(last.get("w_pat",0.2)),
            "macd": float(last.get("w_macd",0.15)),
            "sr": float(last.get("w_sr",0.15))
        }
    except Exception:
        return None

def read_current_threshold(default_val=80):
    try:
        ws = GC.open_by_key(SPREADSHEET_ID).worksheet("calibration")
        rows = ws.get_all_records()
        if not rows: return default_val
        last = rows[-1]
        val = int(last.get("NuevoThreshold", default_val))
        return max(50, min(95, val))
    except Exception:
        return default_val

# =========================
# 🎯 Sniper score
# =========================
def sniper_score(ticker, side):
    meta = read_meta_weights()
    frame_weights = {k:meta[k] for k in ["1m","5m","15m","1h"]} if meta else None
    w_base = meta.get("base") if meta else 0.5
    w_pat  = meta.get("pat")  if meta else 0.2
    w_macd = meta.get("macd") if meta else 0.15
    w_sr   = meta.get("sr")   if meta else 0.15

    df5  = fetch_yf(ticker, "5m",  "5d")
    df1  = fetch_yf(ticker, "1m",  "2d")
    df15 = fetch_yf(ticker, "15m", "1mo")

    base = frame_prob(df5, side) if df5 is not None else 50.0
    pat, pat_score = detect_candle_pattern(df5)
    macd_val = macd_signal(df15)
    macd_score = 8 if (macd_val>0 and side.lower()=="buy") else (8 if (macd_val<0 and side.lower()=="sell") else 0)
    ds, dr = support_resistance_basic(df15)
    sr_score = 0
    if ds is not None:
        if side.lower()=="buy" and ds < 1.0: sr_score += 6
        if side.lower()=="sell" and dr < 1.0: sr_score += 6
        if side.lower()=="buy" and dr < 1.0: sr_score -= 8

    atr_val = atr(df5)

    final_score = (base * w_base
                   + ((pat_score/20.0)*100 if pat_score else 0) * w_pat
                   + ((macd_score/8.0)*100  if macd_score else 0) * w_macd
                   + ((sr_score/8.0)*100    if sr_score else 0) * w_sr)
    final_score = max(0.0, min(100.0, final_score))

    return {
        "score": round(final_score,1),
        "base": round(base,1),
        "pattern": pat,
        "pat_score": pat_score,
        "macd_val": round(macd_val,6),
        "macd_score": macd_score,
        "sr_score": sr_score,
        "atr": round(atr_val,6),
        "frame_probs": prob_multi_frame(ticker, side, frame_weights)
    }

# =========================
# 🛠️ Recalibración (opcional)
# =========================
def recalibrate_weights_from_sheet(n_recent=500, alpha=0.25):
    try:
        rows = SHEET.get_all_records()
        if not rows: return None
        df = pd.DataFrame(rows).tail(n_recent)
        need_cols = ["ProbFinal","pat_score","macd_val","sr_score","Resultado"]
        if not all(c in df.columns for c in need_cols): return None
        df = df.dropna(subset=["Resultado"])
        df["y"] = df["Resultado"].apply(lambda x: 1 if str(x).strip().lower()=="win" else 0)
        if df["y"].sum() == 0: return None

        Xb = (df["ProbFinal"]-df["ProbFinal"].mean())/(df["ProbFinal"].std()+1e-9)
        Xp = (df["pat_score"]-df["pat_score"].mean())/(df["pat_score"].std()+1e-9)
        Xm = (df["macd_val"]-df["macd_val"].mean())/(df["macd_val"].std()+1e-9)
        Xs = (df["sr_score"]-df["sr_score"].mean())/(df["sr_score"].std()+1e-9)

        cors = {
            "base": abs(Xb.corr(df["y"]) or 0),
            "pat":  abs(Xp.corr(df["y"]) or 0),
            "macd": abs(Xm.corr(df["y"]) or 0),
            "sr":   abs(Xs.corr(df["y"]) or 0),
        }
        s = sum(cors.values()) + 1e-9
        norm = {k: cors[k]/s for k in cors}

        w_base = 0.6*norm["base"] + 0.4*0.5
        w_pat  = 0.6*norm["pat"]  + 0.4*0.2
        w_macd = 0.6*norm["macd"] + 0.4*0.15
        w_sr   = 0.6*norm["sr"]   + 0.4*0.15

        w_5m = 0.4 + 0.4*(norm["base"]); w_1m = 0.15
        w_15m = 0.25 - 0.1*(norm["base"]); w_1h = 0.2 - 0.3*(norm["base"])
        total = w_1m + w_5m + w_15m + w_1h
        w_1m/=total; w_5m/=total; w_15m/=total; w_1h/=total

        current = read_meta_weights() or {"1m":0.2,"5m":0.4,"15m":0.25,"1h":0.15,"base":0.5,"pat":0.2,"macd":0.15,"sr":0.15}
        sm = {
            "w_1m": alpha*w_1m + (1-alpha)*current.get("1m",0.2),
            "w_5m": alpha*w_5m + (1-alpha)*current.get("5m",0.4),
            "w_15m":alpha*w_15m+ (1-alpha)*current.get("15m",0.25),
            "w_1h": alpha*w_1h + (1-alpha)*current.get("1h",0.15),
            "w_base":alpha*w_base+(1-alpha)*current.get("base",0.5),
            "w_pat": alpha*w_pat + (1-alpha)*current.get("pat",0.2),
            "w_macd":alpha*w_macd+(1-alpha)*current.get("macd",0.15),
            "w_sr":  alpha*w_sr  + (1-alpha)*current.get("sr",0.15),
            "ts": now_et().isoformat()
        }
        try:
            ws = GC.open_by_key(SPREADSHEET_ID).worksheet("meta")
        except gspread.WorksheetNotFound:
            ws = GC.open_by_key(SPREADSHEET_ID).add_worksheet(title="meta", rows=100, cols=20)
            ws.update("A1", [["w_1m","w_5m","w_15m","w_1h","w_base","w_pat","w_macd","w_sr","ts"]])
        ws.append_row([sm["w_1m"],sm["w_5m"],sm["w_15m"],sm["w_1h"],sm["w_base"],sm["w_pat"],sm["w_macd"],sm["w_sr"],sm["ts"]])
        return sm
    except Exception:
        return None

# =========================
# 📝 Debug
# =========================
def log_debug(row_dict: dict):
    try:
        try:
            dbg = GC.open_by_key(SPREADSHEET_ID).worksheet("debug")
        except gspread.WorksheetNotFound:
            dbg = GC.open_by_key(SPREADSHEET_ID).add_worksheet(title="debug", rows=2000, cols=40)
            dbg.update("A1", [list(row_dict.keys())])
        dbg.append_row([str(row_dict.get(k,"")) for k in row_dict.keys()])
    except Exception:
        pass

# =========================
# 🚦 Señal principal
# =========================
def process_signal(ticker: str, side: str, entry: float):
    t = now_et()
    market = classify_market(ticker)
    weights = read_meta_weights()
    pm = prob_multi_frame(ticker, side, weights)
    p1,p5,p15,p1h = pm["per_frame"]["1m"], pm["per_frame"]["5m"], pm["per_frame"]["15m"], pm["per_frame"]["1h"]
    pf = pm["final"]

    sn = sniper_score(ticker, side)
    sniper_val = sn["score"]
    pat = sn["pattern"]; pat_score = sn["pat_score"]
    macd_val = sn["macd_val"]; sr_score = sn["sr_score"]; atr_val = sn["atr"]

    sl, tp = compute_sl_tp(entry, atr_val, side)

    th = read_current_threshold(80)
    clasif = f"≥{th}" if pf >= th else f"<{th}"
    # Reglas: exigimos BOTH pf>=th y sniper>=th para “Pre”
    is_pre = (pf >= th) and (sniper_val >= th)
    estado = "Pre" if is_pre else "Descartada"
    tipo   = "Pre" if is_pre else "Backtest"
    scheduled_confirm = (t + dt.timedelta(minutes=5)).isoformat() if is_pre else ""

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
        "Prob_1m": round(p1,1),
        "Prob_5m": round(p5,1),
        "Prob_15m": round(p15,1),
        "Prob_1h": round(p1h,1),
        "ProbFinal": round(pf,1),
        "ProbClasificación": clasif,
        "Estado": estado,
        "Tipo": tipo,
        "Resultado": "-",
        "Nota": f"sniper:{sniper_val}",
        "Mercado": market,
        "pattern": pat,
        "pat_score": pat_score,
        "macd_val": macd_val,
        "sr_score": sr_score,
        "atr": atr_val,
        "SL": sl,
        "TP": tp,
        "Recipients": recipients,
        "ScheduledConfirm": scheduled_confirm
    }
    append_signal(row)
    log_debug({**row, "action":"saved"})

    if is_pre and recipients:
        subject = f"📊 Pre-señal {ticker} {side} {entry} – Sniper {sniper_val}%"
        body = (
            f"{ticker} {side} @ {entry}\n"
            f"Prob: {pf}% (1m {p1} / 5m {p5} / 15m {p15} / 1h {p1h})\n"
            f"Sniper: {sniper_val}% | Pattern: {pat} ({pat_score}) | MACD: {macd_val}\n"
            f"SL: {sl} | TP: {tp}\n"
            f"Confirmación programada: {scheduled_confirm} ET\n"
            f"Mercado: {market.upper()}"
        )
        send_mail_many(subject, body, recipients)
    return row

# =========================
# ✅ Confirmaciones (se ejecuta con el Action)
# =========================
def check_pending_confirmations():
    now = now_et()
    th = read_current_threshold(80)
    pending = find_rows(lambda r: r.get("Estado","")=="Pre" and r.get("ScheduledConfirm",""))
    for idx, r in pending:
        try:
            sc = r.get("ScheduledConfirm","")
            if not sc: continue
            sc_dt = dt.datetime.fromisoformat(sc).astimezone(TZ)
            if sc_dt <= now:
                ticker = r.get("Ticker")
                side   = r.get("Side")
                entry  = float(r.get("Entrada") or 0)
                market = r.get("Mercado")
                recipients = r.get("Recipients", ALERT_DEFAULT)

                sn = sniper_score(ticker, side)
                sniper_val = sn["score"]
                open_now = is_market_open(market, now)

                if sniper_val >= th and open_now:
                    update_row_status_by_index(idx, {"Estado":"Confirmada"})
                    subject = f"✅ Confirmación {ticker} {side} {entry} – Sniper {sniper_val}%"
                    body = f"Confirmada {ticker} {side} @ {entry}\nMercado: {market.upper()}\nSniper: {sniper_val}%"
                    send_mail_many(subject, body, recipients)
                else:
                    update_row_status_by_index(idx, {"Estado":"Rechazada", "Nota":"falló confirmación"})
                    subject = f"⚠️ Rechazada {ticker} {side}"
                    body = "Se rechazó por sniper<threshold o mercado cerrado."
                    send_mail_many(subject, body, recipients)
        except Exception as e:
            log_debug({"error":"confirm_check","msg":str(e)})
            continue

# =========================
# ▶️ main con flags
# =========================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true", help="Dispara una señal demo DKNG Buy 45.30")
    parser.add_argument("--check-confirmations", action="store_true", help="Procesa confirmaciones pendientes")
    parser.add_argument("--recalibrate", action="store_true", help="Recalibra pesos y guarda en 'meta'")
    parser.add_argument("--signal", nargs=3, metavar=("TICKER","SIDE","ENTRY"), help="Dispara señal manual")
    args = parser.parse_args()

    ensure_headers()

    if args.recalibrate:
        recalibrate_weights_from_sheet()

    if args.signal:
        tkr, side, entry = args.signal[0], args.signal[1], float(args.signal[2])
        process_signal(tkr, side, entry)

    if args.demo:
        process_signal("DKNG","Buy",45.30)

    if args.check_confirmations:
        check_pending_confirmations()

    # Si no se pasó ninguna flag, no hace nada para evitar spam en Actions.
    # Usa --demo o --signal o programar otro proceso que ingeste alertas.

if __name__ == "__main__":
    main()
