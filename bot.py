# bot.py — Full-Scan DKNG + ES: señales, confirmaciones, apertura/cierre, logs y limpieza semanal

import os, json, re, time, pytz, traceback
import datetime as dt
import smtplib
from email.mime.text import MIMEText

import numpy as np
import pandas as pd
import yfinance as yf

import gspread
from google.oauth2.service_account import Credentials

# =========================
# 🔧 Configuración básica
# =========================
TZ = pytz.timezone("America/New_York")

WATCHLIST = ["DKNG", "ES"]                   # Activos a monitorear
PRE_THRESHOLD = float(os.getenv("PRE_THRESHOLD", "80"))
CONFIRM_THRESHOLD = float(os.getenv("CONFIRM_THRESHOLD", "80"))
CONFIRM_WAIT_MIN = int(os.getenv("CONFIRM_WAIT_MIN", "5"))

CYCLES = int(os.getenv("CYCLES", "3"))       # sub-iteraciones por run
SLEEP_SECONDS = int(os.getenv("SLEEP_SECONDS", "60"))

SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
GS_JSON = json.loads(os.getenv("GOOGLE_SHEETS_JSON", "{}"))

CREDS = Credentials.from_service_account_info(
    GS_JSON, scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
GC = gspread.authorize(CREDS)
SS = GC.open_by_key(SPREADSHEET_ID)

# Gmail
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_PASS = os.getenv("GMAIL_APP_PASS")

# Routing default (puedes sobreescribir con secrets)
ALERT_DEFAULT = os.getenv("ALERT_DEFAULT", "gevem249@gmail.com")
ALERT_DKNG    = os.getenv("ALERT_DKNG",    "gevem249@gmail.com,adri_touma@hotmail.com")
ALERT_ES      = os.getenv("ALERT_ES",      "gevem249@gmail.com")

# =========================
# 📄 Hojas y encabezados
# =========================
HEADERS_SIGNALS = [
    "FechaISO","HoraLocal","HoraRegistro","Ticker","Side","Entrada",
    "Prob_1m","Prob_5m","Prob_15m","Prob_1h","ProbFinal",
    "ProbClasificación","Estado","Tipo","Resultado","Nota","Mercado",
    "pattern","pat_score","macd_val","sr_score","atr","SL","TP",
    "Recipients","ScheduledConfirm"
]

HEADERS_STATE = ["date","dkng_open_sent","dkng_close_sent","es_open_sent","es_close_sent","last_purge_ts"]
HEADERS_DEBUG = ["ts","ctx","msg"]

def ensure_ws(title: str, headers: list[str]):
    try:
        ws = SS.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = SS.add_worksheet(title=title, rows=2000, cols=max(30, len(headers)))
        ws.update("A1", [headers])
        return ws
    # asegura encabezados
    vals = ws.get_all_values()
    if not vals:
        ws.update("A1", [headers])
    else:
        cur = vals[0]
        missing = [h for h in headers if h not in cur]
        if missing:
            ws.update("A1", [cur + missing])
    return ws

WS_SIGNALS = ensure_ws("signals", HEADERS_SIGNALS)
WS_STATE   = ensure_ws("state",   HEADERS_STATE)
WS_DEBUG   = ensure_ws("debug",   HEADERS_DEBUG)

def get_headers(ws): return ws.row_values(1)

# =========================
# 🧭 Tiempo / mercado
# =========================
def now_et() -> dt.datetime: return dt.datetime.now(TZ)

def market_status(ticker: str) -> tuple[str,str]:
    """
    Devuelve ("open"|"closed", "equity"|"futures")
    DKNG (equity): 09:30–16:00 ET, lunes–viernes
    ES (futuros): abierto casi 24h; consideramos cerrado 16:00–18:05 ET
    """
    t = now_et()
    wd = t.weekday()  # 0=Lunes
    if ticker.upper() == "DKNG":
        if wd >= 5: return ("closed", "equity")
        # equity window
        open_t  = t.replace(hour=9,  minute=30, second=0, microsecond=0)
        close_t = t.replace(hour=16, minute=0,  second=0, microsecond=0)
        return ("open", "equity") if open_t <= t <= close_t else ("closed","equity")
    else:  # ES (futuros)
        # Cerrado ~16:00–18:05 ET, todos los días
        close1 = t.replace(hour=16, minute=0,  second=0, microsecond=0)
        open1  = t.replace(hour=18, minute=5,  second=0, microsecond=0)
        if close1 <= t < open1:
            return ("closed","futures")
        # los sábados suele cerrar; simplificamos:
        if wd == 6:  # domingo (antes de 18:05 abierto? cerremos hasta 18:05)
            if t.hour < 18 or (t.hour==18 and t.minute<5):
                return ("closed","futures")
        return ("open","futures")

# =========================
# 📬 Email helpers
# =========================
def send_mail_many(subject: str, body: str, to_emails: str):
    try:
        recips = [e.strip() for e in to_emails.split(",") if e.strip()]
        if not recips or not GMAIL_USER or not GMAIL_PASS: return
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"]    = GMAIL_USER
        msg["To"]      = ", ".join(recips)
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(GMAIL_USER, GMAIL_PASS)
            s.sendmail(GMAIL_USER, recips, msg.as_string())
    except Exception as e:
        log_debug("send_mail_many", f"email error: {e}")

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
    trend = (e8.iloc[-1] - e21.iloc[-1])
    score = 50.0
    if side.lower()=="buy":
        if trend>0: score += 20
        if 45 <= r <= 70: score += 15
        if r < 35: score -= 15
    else:
        if trend<0: score += 20
        if 30 <= r <= 55: score += 15
        if r > 65: score -= 15
    return max(0.0, min(100.0, score))

def map_ticker_yf(ticker: str) -> str:
    if ticker.upper() == "ES": return "^GSPC"
    return ticker

def fetch_yf(ticker: str, interval: str, lookback: str):
    try:
        y = map_ticker_yf(ticker)
        return yf.download(y, period=lookback, interval=interval, progress=False, threads=False)
    except Exception:
        return pd.DataFrame()

def prob_multi_frame(ticker: str, side: str) -> dict:
    frames = {"1m":("1m","2d"),"5m":("5m","5d"),"15m":("15m","1mo"),"1h":("60m","3mo")}
    probs = {}
    for k,(itv,lb) in frames.items():
        df = fetch_yf(ticker, itv, lb)
        probs[k] = round(frame_prob(df, side),1)
    final = round(0.2*probs["1m"] + 0.4*probs["5m"] + 0.25*probs["15m"] + 0.15*probs["1h"], 1)
    return {"per_frame":probs,"final":final}

# =========================
# 🔎 Logs / utilidades
# =========================
def log_debug(ctx: str, msg: str):
    try:
        WS_DEBUG.append_row([now_et().isoformat(), ctx, msg])
    except Exception:
        pass

def purge_old_debug(days=7):
    try:
        rows = WS_DEBUG.get_all_records()
        if not rows: return
        df = pd.DataFrame(rows)
        df["ts"] = pd.to_datetime(df["ts"], errors="coerce")
        cutoff = now_et() - dt.timedelta(days=days)
        df_new = df[df["ts"] >= cutoff]
        WS_DEBUG.clear()
        WS_DEBUG.update("A1", [HEADERS_DEBUG])
        if not df_new.empty:
            WS_DEBUG.update("A2", df_new.astype(str).values.tolist())
        # marca en state
        upsert_state({"last_purge_ts": now_et().isoformat()})
    except Exception as e:
        log_debug("purge_old_debug", str(e))

def read_state_today() -> dict:
    vals = WS_STATE.get_all_records()
    today = now_et().date().isoformat()
    for r in vals:
        if str(r.get("date","")) == today:
            return r
    return {"date": today, "dkng_open_sent":"", "dkng_close_sent":"", "es_open_sent":"", "es_close_sent":"", "last_purge_ts":""}

def upsert_state(upd: dict):
    vals = WS_STATE.get_all_records()
    headers = get_headers(WS_STATE)
    today = now_et().date().isoformat()
    # buscar fila del día
    idx = None
    for i,r in enumerate(vals, start=2):
        if str(r.get("date","")) == today:
            idx = i; break
    if idx is None:  # nueva fila
        base = read_state_today()
        base.update(upd)
        row = [base.get(h,"") for h in headers]
        WS_STATE.append_row(row)
    else:
        # update columnas específicas
        for k,v in upd.items():
            if k in headers:
                col = headers.index(k)+1
                WS_STATE.update_cell(idx, col, v)

# =========================
# 📣 Apertura / Cierre
# =========================
def notify_open_close():
    st = read_state_today()
    t = now_et().strftime("%Y-%m-%d %H:%M:%S")
    # DKNG
    m_dk, _ = market_status("DKNG")
    if m_dk == "open" and not st.get("dkng_open_sent"):
        send_mail_many("🟢 Apertura DKNG", f"DKNG abierto {t} ET", ALERT_DKNG)
        upsert_state({"dkng_open_sent":"1"})
    if m_dk == "closed" and not st.get("dkng_close_sent"):
        send_mail_many("🔴 Cierre DKNG", f"DKNG cerrado {t} ET", ALERT_DKNG)
        upsert_state({"dkng_close_sent":"1"})
    # ES
    m_es, _ = market_status("ES")
    if m_es == "open" and not st.get("es_open_sent"):
        send_mail_many("🟢 Apertura ES", f"ES abierto {t} ET", ALERT_ES)
        upsert_state({"es_open_sent":"1"})
    if m_es == "closed" and not st.get("es_close_sent"):
        send_mail_many("🔴 Cierre ES", f"ES cerrado {t} ET", ALERT_ES)
        upsert_state({"es_close_sent":"1"})

# =========================
# 💾 Guardar señales
# =========================
def ensure_headers_signals():
    # ya lo hace ensure_ws, pero por si se crea vacía
    cur = WS_SIGNALS.get_all_values()
    if not cur:
        WS_SIGNALS.update("A1", [HEADERS_SIGNALS])

def append_signal_row(row_dict: dict):
    ensure_headers_signals()
    headers_live = get_headers(WS_SIGNALS)
    WS_SIGNALS.append_row([row_dict.get(h,"") for h in headers_live])

def update_row_by_index(idx: int, updates: dict):
    headers = get_headers(WS_SIGNALS)
    for k,v in updates.items():
        if k in headers:
            WS_SIGNALS.update_cell(idx, headers.index(k)+1, v)

def find_rows(filter_fn):
    recs = WS_SIGNALS.get_all_records()
    out = []
    for i,r in enumerate(recs, start=2):
        try:
            if filter_fn(r): out.append((i,r))
        except Exception:
            continue
    return out

# =========================
# 📐 SL/TP básico con ATR fallback
# =========================
def compute_sl_tp(entry: float, side: str, atr: float|None) -> tuple[float,float]:
    if not atr or atr == 0:  # fallback 0.5%
        if side.lower()=="buy":  return (round(entry*0.995,6), round(entry*1.01,6))
        else:                    return (round(entry*1.005,6), round(entry*0.99,6))
    risk = atr
    if side.lower()=="buy":  return (round(entry-risk,6), round(entry+2*risk,6))
    else:                    return (round(entry+risk,6), round(entry-2*risk,6))

# =========================
# 🔎 Procesar 1 ticker
# =========================
def process_ticker(ticker: str, side: str = "buy", entry: float|None = None):
    try:
        status, market_kind = market_status(ticker)
        t = now_et()
        pm = prob_multi_frame(ticker, side)
        p1,p5,p15,p1h = (pm["per_frame"]["1m"], pm["per_frame"]["5m"], pm["per_frame"]["15m"], pm["per_frame"]["1h"])
        pf = pm["final"]

        # “indicadores extra” (abreviados a placeholders seguros)
        pattern, pat_score = "none", 0
        macd_val, sr_score, atr_val = 0.0, 0, 0.0

        # precio “entrada” si no se dio
        if entry is None:
            df = fetch_yf(ticker, "1m", "1d")
            entry = float(df["Close"].iloc[-1]) if not df.empty else 0.0

        sl, tp = compute_sl_tp(entry, side, atr_val)

        clasif = "≥80" if pf >= PRE_THRESHOLD else "<80"
        estado = "Dormido" if status=="closed" else ("Pre" if pf >= PRE_THRESHOLD else "Observado")
        tipo = "Pre" if estado=="Pre" else "Scan"

        sched = (t + dt.timedelta(minutes=CONFIRM_WAIT_MIN)).isoformat() if estado=="Pre" else ""

        recipients = ALERT_DEFAULT
        if ticker.upper()=="DKNG": recipients = ALERT_DKNG
        elif ticker.upper()=="ES": recipients = ALERT_ES

        row = {
            "FechaISO": t.strftime("%Y-%m-%d"),
            "HoraLocal": t.strftime("%H:%M"),
            "HoraRegistro": t.strftime("%H:%M:%S"),
            "Ticker": ticker.upper(),
            "Side": side.title(),
            "Entrada": entry,
            "Prob_1m": p1, "Prob_5m": p5, "Prob_15m": p15, "Prob_1h": p1h,
            "ProbFinal": pf, "ProbClasificación": clasif,
            "Estado": estado, "Tipo": tipo, "Resultado": "-",
            "Nota": f"{status}", "Mercado": market_kind,
            "pattern": pattern, "pat_score": pat_score,
            "macd_val": macd_val, "sr_score": sr_score, "atr": atr_val,
            "SL": sl, "TP": tp, "Recipients": recipients,
            "ScheduledConfirm": sched
        }
        append_signal_row(row)

        # notificación si Pre
        if estado=="Pre":
            subject = f"📊 Pre-señal {ticker} {side} {entry} – {pf}%"
            body = (f"{ticker} {side} @ {entry}\n"
                    f"ProbFinal {pf}% (1m {p1} / 5m {p5} / 15m {p15} / 1h {p1h})\n"
                    f"SL {sl} | TP {tp} | Confirma en {CONFIRM_WAIT_MIN} min.")
            send_mail_many(subject, body, recipients)

    except Exception as e:
        log_debug("process_ticker", f"{ticker}: {e}")

# =========================
# ✅ Confirmaciones
# =========================
def check_pending_confirmations():
    try:
        now = now_et()
        pend = find_rows(lambda r: r.get("Estado")=="Pre" and r.get("ScheduledConfirm"))
        for idx, r in pend:
            try:
                sc = r.get("ScheduledConfirm","")
                sc_dt = dt.datetime.fromisoformat(sc).astimezone(TZ)
                if sc_dt <= now:
                    ticker = r.get("Ticker")
                    side = r.get("Side","Buy")
                    pm = prob_multi_frame(ticker, side)
                    pf2 = pm["final"]
                    new_state = "Confirmada" if pf2 >= CONFIRM_THRESHOLD else "Cancelada"
                    update_row_by_index(idx, {"Estado": new_state})
                    if new_state == "Confirmada":
                        rcpts = r.get("Recipients", ALERT_DEFAULT)
                        send_mail_many(f"✅ Confirmada {ticker} {side} {r.get('Entrada')}",
                                       f"Confirmada con ProbFinal {pf2}%.",
                                       rcpts)
            except Exception as ie:
                log_debug("check_pending_confirmations_row", str(ie))
    except Exception as e:
        log_debug("check_pending_confirmations", str(e))

# =========================
# ▶️ Main loop (full-scan)
# =========================
def main():
    log_debug("main", "run start")
    # apertura/cierre (una vez por día)
    notify_open_close()
    # limpieza semanal de debug
    purge_old_debug(days=7)

    # sub-iteraciones internas para mantener actividad
    for i in range(CYCLES):
        for tk in WATCHLIST:
            process_ticker(tk, "buy", None)
        check_pending_confirmations()
        if i < CYCLES-1:
            time.sleep(SLEEP_SECONDS)

    log_debug("main", "run end")

if __name__ == "__main__":
    main()
