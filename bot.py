# bot.py — Trading-Bot completo con Sniper + confirmaciones + auto-resultado SL/TP + error logging
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
            # en dev podrías pasar un path al json en la variable
            GS_JSON = json.loads(open(gs_raw).read())
        except Exception:
            GS_JSON = None

if not SPREADSHEET_ID or not GS_JSON:
    raise RuntimeError("⚠️ Falta SPREADSHEET_ID o GOOGLE_SHEETS_JSON en secrets/env")

CREDS = Credentials.from_service_account_info(GS_JSON, scopes=["https://www.googleapis.com/auth/spreadsheets"])
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
# 🧭 Utils tiempo/mercado
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
# 📬 Email helpers
# =========================
def send_mail_many(subject: str, body: str, to_emails: str):
    """Envía correo SSL vía Gmail a lista coma-separada"""
    if not to_emails:
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
# 📈 Indicadores / helpers
# =========================
def ema(series, span):
    return series.ewm(span=span, adjust=False).mean()

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
# 🔎 Sniper helpers: ATR, MACD, candle patterns, SR
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
    # Doji
    if body / range_ < 0.1:
        return ("doji", -5)
    # Hammer
    if lower_wick > 2 * body and upper_wick < 0.5*body:
        return ("hammer", 8 if c>o else -8)
    # Engulfing
    if len(df) >= 2:
        o2 = df["Open"].squeeze().iloc[-2]
        c2 = df["Close"].squeeze().iloc[-2]
        if c > o and c2 < o2 and (c - o) > (o2 - c2):
            return ("bull_engulf", 12)
        if c < o and c2 > o2 and (o - c) > (c2 - o2):
            return ("bear_engulf", -12)
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
# HEADERS de Google Sheets (agrega campos nuevos)
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
    else:
        current = vals[0]
        missing = [h for h in HEADERS if h not in current]
        if missing:
            new_headers = current + missing
            SHEET.update("A1", [new_headers])

def append_signal(row_dict: dict):
    ensure_headers()
    # append row in HEADERS order; if sheet had extra headers new_headers used above, we keep original HEADERS order
    row = [row_dict.get(k,"") for k in HEADERS]
    SHEET.append_row(row)

def update_row_status_by_index(row_index:int, updates:dict):
    vals = SHEET.get_all_values()
    if row_index < 2 or row_index > len(vals): return
    headers = vals[0]
    for k,v in updates.items():
        if k in headers:
            col = headers.index(k) + 1
            SHEET.update_cell(row_index, col, v)

def find_rows(filter_fn):
    """Devuelve lista de (row_index,row_dict) para rows que cumplan filter_fn(dict)->bool"""
    records = SHEET.get_all_records()
    out = []
    for i, r in enumerate(records, start=2):
        try:
            if filter_fn(r):
                out.append((i, r))
        except Exception:
            continue
    return out

# =========================
# Logging / debug sheet & error email
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

def log_error(exc: Exception, context: str = ""):
    """Guarda traza en sheet debug y manda correo de error a ALERT_DEFAULT"""
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    payload = {
        "ts": now_et().isoformat(),
        "context": context,
        "error": str(exc),
        "trace": tb[:2000]  # limitar tamaño para el sheet
    }
    # write to debug sheet
    try:
        try:
            dbg = GC.open_by_key(SPREADSHEET_ID).worksheet("debug")
        except gspread.WorksheetNotFound:
            dbg = GC.open_by_key(SPREADSHEET_ID).add_worksheet(title="debug", rows=2000, cols=10)
            dbg.update("A1", [["ts","context","error","trace"]])
        dbg.append_row([payload["ts"], payload["context"], payload["error"], payload["trace"]])
    except Exception:
        pass
    # send email
    try:
        send_mail_many(f"⚠️ Error Bot: {context}", f"{payload['ts']}\nContext: {context}\n\n{payload['error']}\n\nTrace:\n{tb}", ALERT_DEFAULT)
    except Exception:
        pass

# =========================
# Sniper scoring (simple)
# =========================
def sniper_score(ticker, side):
    # fetch frames
    df5 = fetch_yf(ticker, "5m", "5d")
    df1 = fetch_yf(ticker, "1m", "2d")
    df15 = fetch_yf(ticker, "15m", "1mo")

    base = frame_prob(df5, side) if df5 is not None else 50.0
    pat, pat_score = detect_candle_pattern(df5)
    macd_val = macd_signal(df15)
    macd_score = 8 if (macd_val > 0 and side.lower()=="buy") else (8 if (macd_val < 0 and side.lower()=="sell") else 0)
    ds, dr = support_resistance_basic(df15)
    sr_score = 0
    if ds is not None:
        if side.lower()=="buy" and ds < 1.0: sr_score += 6
        if side.lower()=="sell" and dr < 1.0: sr_score += 6

    atr_val = atr(df5)

    final_score = (base*0.5 + ( (pat_score/20.0)*100 if pat_score else 0 )*0.2 + ( (macd_score/8.0)*100 if macd_score else 0 )*0.15 + ( (sr_score/8.0)*100 if sr_score else 0 )*0.15)
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
        "frame_probs": prob_multi_frame(ticker, side)
    }

# =========================
# Core: process_signal (no espera confirmación)
# =========================
def process_signal(ticker: str, side: str, entry: float, notify_email: str=None):
    try:
        t = now_et()
        market = classify_market(ticker)
        pm = prob_multi_frame(ticker, side)
        p1, p5, p15, p1h = pm["per_frame"]["1m"], pm["per_frame"]["5m"], pm["per_frame"]["15m"], pm["per_frame"]["1h"]
        pf = pm["final"]

        sn = sniper_score(ticker, side)
        sniper_val = sn["score"]
        pat = sn["pattern"]; pat_score = sn["pat_score"]
        macd_val = sn["macd_val"]; sr_score = sn["sr_score"]; atr_val = sn["atr"]

        sl, tp = compute_sl_tp(entry, atr_val, side)

        clasif = "≥80" if pf >= 80 else "<80"
        estado = "Pre" if sniper_val >= 80 else "Descartada"
        tipo = "Pre" if estado=="Pre" else "Backtest"

        scheduled_confirm = (t + dt.timedelta(minutes=5)).isoformat() if estado=="Pre" else ""

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

        if estado == "Pre" and recipients:
            subject = f"📊 Pre-señal {ticker} {side} {entry} – {round(sniper_val,1)}%"
            body = (
                f"{ticker} {side} @ {entry}\nProb final: {pf}% (1m {p1} / 5m {p5} / 15m {p15} / 1h {p1h})\n"
                f"Sniper: {sniper_val}% | Pattern: {pat} ({pat_score}) | MACD: {macd_val}\nSL: {sl} | TP: {tp}\nConfirmación: {scheduled_confirm}\nMercado: {market}"
            )
            send_mail_many(subject, body, recipients)

        return row
    except Exception as e:
        log_error(e, context=f"process_signal({ticker},{side},{entry})")
        raise

# =========================
# check_pending_confirmations: debe ejecutarse periódicamente (GitHub Actions cada 1-5min)
# =========================
def check_pending_confirmations():
    try:
        now = now_et()
        pending = find_rows(lambda r: r.get("Estado","")=="Pre" and r.get("ScheduledConfirm",""))
        for idx, r in pending:
            try:
                sc = r.get("ScheduledConfirm","")
                if not sc: continue
                sc_dt = dt.datetime.fromisoformat(sc)
                sc_dt = sc_dt.astimezone(TZ)
                if sc_dt <= now:
                    ticker = r.get("Ticker")
                    side = r.get("Side")
                    entry = float(r.get("Entrada") or 0)
                    # re-eval probabilities
                    pm = prob_multi_frame(ticker, side)
                    pf2 = pm["final"]
                    estado2 = "Confirmado" if pf2>=80 else "Cancelado"
                    SHEET.update_cell(idx, HEADERS.index("Estado")+1, estado2)
                    log_debug({"row_idx": idx, "old": "Pre", "new": estado2, "ticker": ticker, "pf2": pf2})
            except Exception as e_inner:
                log_error(e_inner, context=f"check_pending_confirmations row {idx}")
    except Exception as e:
        log_error(e, context="check_pending_confirmations")
        raise

# =========================
# Auto-update de resultados SL/TP
# =========================
def check_trade_outcomes():
    try:
        rows = find_rows(lambda r: r.get("Estado") in ["Pre","Confirmado"] and (r.get("Resultado","") in ["-",""]))
        for idx,r in rows:
            try:
                ticker = r.get("Ticker")
                side = r.get("Side","Buy").lower()
                entry = float(r.get("Entrada") or 0)
                sl = float(r.get("SL") or 0)
                tp = float(r.get("TP") or 0)

                df = fetch_yf(ticker,"1m","1d")
                if df.empty: continue
                last_price = df["Close"].iloc[-1]

                if side=="buy":
                    if last_price <= sl:
                        SHEET.update_cell(idx, HEADERS.index("Resultado")+1, "Loss")
                    elif last_price >= tp:
                        SHEET.update_cell(idx, HEADERS.index("Resultado")+1, "Win")
                else:
                    if last_price >= sl:
                        SHEET.update_cell(idx, HEADERS.index("Resultado")+1, "Loss")
                    elif last_price <= tp:
                        SHEET.update_cell(idx, HEADERS.index("Resultado")+1, "Win")
            except Exception as e_inner:
                log_error(e_inner, context=f"check_trade_outcomes row {idx}")
    except Exception as e:
        log_error(e, context="check_trade_outcomes")
        raise

# =========================
# Recalibración (simple wrapper)
# =========================
def recalibrate_weights_from_sheet(n_recent=500, alpha=0.25):
    try:
        rows = SHEET.get_all_records()
        if not rows: return None
        df = pd.DataFrame(rows).tail(n_recent)
        if not all(c in df.columns for c in ["ProbFinal","pat_score","macd_val","sr_score","Resultado"]):
            return None
        df = df.dropna(subset=["Resultado"])
        df["y"] = df["Resultado"].apply(lambda x: 1 if str(x).strip().lower()=="win" else 0)
        if df["y"].sum() == 0: return None

        # predictors
        Xb = (df["ProbFinal"] - df["ProbFinal"].mean()) / (df["ProbFinal"].std()+1e-9)
        Xp = (df["pat_score"] - df["pat_score"].mean()) / (df["pat_score"].std()+1e-9)
        Xm = (df["macd_val"] - df["macd_val"].mean()) / (df["macd_val"].std()+1e-9)
        Xs = (df["sr_score"] - df["sr_score"].mean()) / (df["sr_score"].std()+1e-9)

        corr_base = abs(Xb.corr(df["y"]) or 0)
        corr_pat  = abs(Xp.corr(df["y"]) or 0)
        corr_macd = abs(Xm.corr(df["y"]) or 0)
        corr_sr   = abs(Xs.corr(df["y"]) or 0)

        cors = {"base":max(0,corr_base),"pat":max(0,corr_pat),"macd":max(0,corr_macd),"sr":max(0,corr_sr)}
        s = sum(cors.values()) + 1e-9
        norm = {k: cors[k]/s for k in cors}

        w_base = 0.6*norm["base"] + 0.4*0.5
        w_pat = 0.6*norm["pat"] + 0.4*0.2
        w_macd = 0.6*norm["macd"] + 0.4*0.15
        w_sr = 0.6*norm["sr"] + 0.4*0.15

        w_5m = 0.4 + 0.4*(norm["base"])
        w_1m = 0.15
        w_15m = 0.25 - 0.1*(norm["base"])
        w_1h = 0.2 - 0.3*(norm["base"])
        total_frames = w_1m + w_5m + w_15m + w_1h
        w_1m /= total_frames; w_5m /= total_frames; w_15m /= total_frames; w_1h /= total_frames

        current = {"1m":0.2,"5m":0.4,"15m":0.25,"1h":0.15,"base":0.5,"pat":0.2,"macd":0.15,"sr":0.15}
        sm = {
            "w_1m": alpha*w_1m + (1-alpha)*current.get("1m",0.2),
            "w_5m": alpha*w_5m + (1-alpha)*current.get("5m",0.4),
            "w_15m": alpha*w_15m + (1-alpha)*current.get("15m",0.25),
            "w_1h": alpha*w_1h + (1-alpha)*current.get("1h",0.15),
            "w_base": alpha*w_base + (1-alpha)*current.get("base",0.5),
            "w_pat": alpha*w_pat + (1-alpha)*current.get("pat",0.2),
            "w_macd": alpha*w_macd + (1-alpha)*current.get("macd",0.15),
            "w_sr": alpha*w_sr + (1-alpha)*current.get("sr",0.15),
            "ts": now_et().isoformat()
        }
        
