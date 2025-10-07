# bot.py — Trading-Bot DKNG + ES con señales Pre/Confirmación, market open/close emails,
# indicadores (EMA13/21, RSI, MACD, ATR), patrones de velas, SL/TP y logging en Google Sheets.

import os, json, re, pytz, datetime as dt, smtplib, traceback
from email.mime.text import MIMEText

import pandas as pd
import numpy as np
import yfinance as yf

import gspread
from google.oauth2.service_account import Credentials

# =========================
# 🔧 Configuración / constantes
# =========================
TZ = pytz.timezone("America/New_York")

WATCHLIST = ["DKNG", "ES"]                   # activos a monitorear
MICRO_TICKERS = {"ES"}                       # ES (mini S&P) para routing CME micros
CRYPTO_TICKERS = set()
FOREX_RE = re.compile(r"^[A-Z]{6}$")

SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
GS_JSON_RAW = os.getenv("GOOGLE_SHEETS_JSON", "")

if not SPREADSHEET_ID or not GS_JSON_RAW:
    raise RuntimeError("⚠️ Falta SPREADSHEET_ID o GOOGLE_SHEETS_JSON en secrets/env")

try:
    GS_JSON = json.loads(GS_JSON_RAW)
except Exception:
    GS_JSON = json.loads(open(GS_JSON_RAW).read())

CREDS = Credentials.from_service_account_info(
    GS_JSON, scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
GC = gspread.authorize(CREDS)
SS = GC.open_by_key(SPREADSHEET_ID)

# Gmail (envío)
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_PASS = os.getenv("GMAIL_APP_PASS")

# Routing de alertas
ALERT_DEFAULT = "gevem249@gmail.com"
ALERT_DKNG = "gevem249@gmail.com,adri_touma@hotmail.com"
ALERT_ES = "gevem249@gmail.com"

# Hojas
def ensure_worksheet(name: str, rows=2000, cols=40):
    try:
        return SS.worksheet(name)
    except gspread.WorksheetNotFound:
        return SS.add_worksheet(title=name, rows=rows, cols=cols)

SHEET_SIGNALS = ensure_worksheet("signals", rows=5000, cols=50)
SHEET_MKTLOG  = ensure_worksheet("market_log", rows=1000, cols=10)
SHEET_DEBUG   = ensure_worksheet("debug", rows=2000, cols=10)
SHEET_META    = ensure_worksheet("meta", rows=200, cols=10)

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
    wd = t.weekday()  # 0=Lunes ... 6=Domingo
    h, m = t.hour, t.minute
    minutes = h*60 + m

    if market == "equity":
        if wd >= 5:  # fin de semana
            return False
        return (9*60 + 30) <= minutes < (16*60)

    if market == "cme_micro":
        # Globex minis: Cierra viernes 17:00, reabre domingo 18:00. Daily pause 17:00–18:00.
        if wd == 5: return False
        if wd == 6 and minutes < (18*60): return False
        if wd == 4 and minutes >= (17*60): return False
        if (17*60) <= minutes < (18*60): return False
        return True

    if market == "crypto":
        return True
    if market == "forex":
        if wd == 5: return False
        if wd == 6 and minutes < (17*60): return False
        if wd == 4 and minutes >= (17*60): return False
        return True
    return False

# =========================
# 📬 Email helpers
# =========================
def send_mail_many(subject: str, body: str, to_emails: str):
    try:
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
    except Exception as e:
        log_error(e, "send_mail_many")

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

def macd_vals(series, fast=12, slow=26, signal=9):
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    sig = macd.ewm(span=signal, adjust=False).mean()
    return macd, sig

def atr(df, period=14):
    if df is None or df.empty: return 0.0
    h = df["High"].squeeze()
    l = df["Low"].squeeze()
    c = df["Close"].squeeze()
    pc = c.shift(1)
    tr = pd.concat([(h-l).abs(), (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean().iloc[-1] if len(tr)>=period else float(tr.mean())

def detect_candle_pattern(df):
    """Muy simple: doji/hammer/engulfing."""
    if df is None or df.empty: return ("none", 0)
    o = df["Open"].iloc[-1]; h = df["High"].iloc[-1]
    l = df["Low"].iloc[-1];  c = df["Close"].iloc[-1]
    body = abs(c - o); rng = (h - l + 1e-9)
    lower_wick = min(o,c) - l
    upper_wick = h - max(o,c)
    if body / rng < 0.1: return ("doji", -5)
    if lower_wick > 2*body and upper_wick < 0.5*body: return ("hammer", 8 if c>o else -8)
    if len(df) >= 2:
        o2 = df["Open"].iloc[-2]; c2 = df["Close"].iloc[-2]
        if c > o and c2 < o2 and (c-o) > (o2-c2): return ("bull_engulf", 12)
        if c < o and c2 > o2 and (o-c) > (c2-o2): return ("bear_engulf", -12)
    return ("none", 0)

def support_resistance_basic(df, lookback=50):
    if df is None or df.empty or len(df) < 3: return (None, None)
    close = df["Close"].iloc[-1]
    highs = df["High"].tail(lookback)
    lows = df["Low"].tail(lookback)
    resist = highs.max(); support = lows.min()
    ds = (close - support)/support*100 if support>0 else None
    dr = (resist - close)/resist*100 if resist>0 else None
    return (ds, dr)

def compute_sl_tp(entry, atr_val, side, rr=2.0, atr_multiplier_sl=1.0):
    if not atr_val or atr_val == 0:
        return (round(entry*0.995,6), round(entry*1.01,6)) if side=="buy" else (round(entry*1.005,6), round(entry*0.99,6))
    risk = atr_val * atr_multiplier_sl
    if side=="buy":  sl, tp = entry - risk, entry + rr*risk
    else:            sl, tp = entry + risk, entry - rr*risk
    return (round(sl,6), round(tp,6))

def frame_prob(df: pd.DataFrame, side: str) -> float:
    if df is None or df.empty: return 50.0
    close = df["Close"].squeeze()
    e13, e21 = ema(close, 13), ema(close, 21)
    r = rsi(close, 14).fillna(50).iloc[-1]
    trend = (e13.iloc[-1]-e21.iloc[-1])
    score = 50.0
    if side=="buy":
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
    if ticker.upper()=="ES": y="^GSPC"  # mapeo ES → S&P500 cash proxy
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
# Google Sheets helpers
# =========================
HEADERS = [
    "FechaISO","HoraLocal","HoraRegistro","Ticker","Side","Entrada",
    "Prob_1m","Prob_5m","Prob_15m","Prob_1h","ProbFinal",
    "ProbClasificación","Estado","Tipo","Resultado","Nota","Mercado",
    "pattern","pat_score","macd_val","sr_score","atr","SL","TP",
    "Recipients","ScheduledConfirm"
]

def ensure_signal_headers():
    vals = SHEET_SIGNALS.get_all_values()
    if not vals:
        SHEET_SIGNALS.update("A1", [HEADERS])
        return
    current = vals[0]
    missing = [h for h in HEADERS if h not in current]
    if missing:
        SHEET_SIGNALS.update("A1", [current + missing])

def append_signal(row_dict: dict):
    ensure_signal_headers()
    headers_live = SHEET_SIGNALS.row_values(1)
    row = [row_dict.get(h,"") for h in headers_live]
    SHEET_SIGNALS.append_row(row)

def log_debug(payload: dict):
    try:
        cols = list(payload.keys())
        if SHEET_DEBUG.row_count == 0:
            SHEET_DEBUG.update("A1", [cols])
        SHEET_DEBUG.append_row([str(payload.get(k,"")) for k in cols])
    except Exception:
        pass

def log_error(exc: Exception, context: str = ""):
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    payload = {
        "ts": now_et().isoformat(),
        "context": context,
        "error": str(exc),
        "trace": tb[:1800]
    }
    try:
        SHEET_DEBUG.append_row([payload["ts"], payload["context"], payload["error"], payload["trace"]])
    except Exception:
        pass
    try:
        send_mail_many(f"⚠️ Error Bot: {context}", f"{payload['ts']}\n{payload['error']}\n\n{tb}", ALERT_DEFAULT)
    except Exception:
        pass

# =========================
# Señales
# =========================
def process_signal(ticker: str, side: str, entry: float):
    t = now_et()
    market = classify_market(ticker)

    pm = prob_multi_frame(ticker, side)
    p1, p5, p15, p1h = pm["per_frame"]["1m"], pm["per_frame"]["5m"], pm["per_frame"]["15m"], pm["per_frame"]["1h"]
    pf = pm["final"]

    # indicadores extras sobre 5m
    df5 = fetch_yf(ticker, "5m", "5d")
    atr_val = atr(df5) if not df5.empty else 0.0
    macd_line, macd_sig = macd_vals(df5["Close"]) if not df5.empty else (pd.Series([0]), pd.Series([0]))
    macd_val = float((macd_line.tail(1)-macd_sig.tail(1)).iloc[0]) if len(macd_line)>=1 and len(macd_sig)>=1 else 0.0
    pat, pat_score = detect_candle_pattern(df5) if not df5.empty else ("none", 0)
    ds, dr = support_resistance_basic(df5 if not df5.empty else None)
    sr_score = 0
    if ds is not None:
        if side=="buy" and ds < 1.0: sr_score += 6
        if side=="sell" and dr < 1.0: sr_score += 6

    sl, tp = compute_sl_tp(entry, atr_val, side)

    clasif = "≥80" if pf >= 80 else "<80"
    estado = "Pre" if pf >= 80 else "Descartada"
    tipo = "Pre" if estado=="Pre" else "Backtest"
    scheduled_confirm = (t + dt.timedelta(minutes=5)).isoformat() if estado=="Pre" else ""

    recipients = ALERT_DEFAULT
    if ticker.upper()=="DKNG":
        recipients = ALERT_DKNG
    elif ticker.upper()=="ES":
        recipients = ALERT_ES

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
        "Nota": f"ind:EMA13/21,RSI,MACD,ATR; ds={ds},dr={dr}",
        "Mercado": market,
        "pattern": pat,
        "pat_score": pat_score,
        "macd_val": round(macd_val,6),
        "sr_score": sr_score,
        "atr": round(atr_val,6),
        "SL": sl,
        "TP": tp,
        "Recipients": recipients,
        "ScheduledConfirm": scheduled_confirm
    }

    append_signal(row)

    if estado == "Pre":
        subject = f"📊 Pre-señal {ticker} {side} @ {entry} – {pf}%"
        body = (
            f"{ticker} {side} @ {entry}\n"
            f"ProbFinal: {pf}% (1m {p1} / 5m {p5} / 15m {p15} / 1h {p1h})\n"
            f"MACDΔ: {round(macd_val,4)} | ATR: {round(atr_val,4)} | Patrón: {pat}({pat_score})\n"
            f"SL: {sl} | TP: {tp}\n"
            f"Confirmación programada: {scheduled_confirm}\n"
            f"Mercado: {market}"
        )
        send_mail_many(subject, body, recipients)

    log_debug({"action":"signal_saved","ticker":ticker,"pf":pf,"estado":estado})
    return row

def check_pending_confirmations():
    """Revisa señales en estado 'Pre' y decide Confirmado / Cancelado 5 min después."""
    try:
        records = SHEET_SIGNALS.get_all_records()
        now = now_et()
        headers = SHEET_SIGNALS.row_values(1)
        if "Estado" not in headers or "ScheduledConfirm" not in headers:
            return
        idx_estado = headers.index("Estado")+1
        idx_sched  = headers.index("ScheduledConfirm")+1
        idx_ticker = headers.index("Ticker")+1
        idx_side   = headers.index("Side")+1
        idx_entry  = headers.index("Entrada")+1
        idx_recip  = headers.index("Recipients")+1

        for i, r in enumerate(records, start=2):
            try:
                if str(r.get("Estado","")).strip() != "Pre":
                    continue
                sc = r.get("ScheduledConfirm","")
                if not sc: 
                    continue
                sc_dt = dt.datetime.fromisoformat(sc).astimezone(TZ)
                if sc_dt > now:
                    continue
                # reevaluar
                ticker = str(r.get("Ticker")).upper()
                side = str(r.get("Side","Buy")).lower()
                entry = float(r.get("Entrada") or 0.0)
                pm = prob_multi_frame(ticker, side)
                pf2 = pm["final"]
                new_state = "Confirmado" if pf2 >= 80 else "Cancelado"
                SHEET_SIGNALS.update_cell(i, idx_estado, new_state)

                # correo de confirmación/cancelación
                recipients = r.get("Recipients") or ALERT_DEFAULT
                subject = f"🔁 {new_state} {ticker} {side} @ {entry} – {pf2}%"
                body = f"{ticker} {side} @ {entry}\nProbFinal reevaluada: {pf2}%\nEstado: {new_state}"
                send_mail_many(subject, body, recipients)

                log_debug({"action":"confirm_check","row":i,"ticker":ticker,"new_state":new_state,"pf2":pf2})
            except Exception as e_in:
                log_error(e_in, f"check_pending_confirmations row {i}")
    except Exception as e:
        log_error(e, "check_pending_confirmations")

# =========================
# Monitor de apertura/cierre + heartbeat
# =========================
def get_last_market_state(market: str):
    try:
        rows = SHEET_MKTLOG.get_all_records()
        rows = [r for r in rows if r.get("Market")==market]
        if not rows: return None
        return rows[-1].get("State")
    except Exception:
        return None

def append_market_log(market: str, state: str, note: str=""):
    t = now_et()
    headers = SHEET_MKTLOG.row_values(1)
    if not headers:
        SHEET_MKTLOG.update("A1", [["FechaISO","HoraLocal","Timestamp","Market","State","Note"]])
    SHEET_MKTLOG.append_row([
        t.strftime("%Y-%m-%d"),
        t.strftime("%H:%M"),
        t.isoformat(),
        market,
        state,
        note
    ])

def monitor_markets_and_notify():
    for market in ["equity","cme_micro"]:
        try:
            cur = "OPEN" if is_market_open(market, now_et()) else "CLOSED"
            last = get_last_market_state(market)
            if last != cur:
                append_market_log(market, cur, "state-change")
                subject = f"🕰️ {market.upper()} ahora {cur}"
                body = f"{market.upper()} cambió a {cur} ({now_et().strftime('%Y-%m-%d %H:%M:%S ET')})."
                send_mail_many(subject, body, ALERT_DEFAULT)
            else:
                # heartbeat cada 60 min aprox: lo dejamos siempre como pequeña entrada
                append_market_log(market, cur, "heartbeat")
        except Exception as e:
            log_error(e, f"monitor_markets_and_notify({market})")

# =========================
# Limpieza semanal
# =========================
def weekly_cleanup():
    """Mantener market_log y debug con retención de 7 días."""
    try:
        cutoff = (now_et() - dt.timedelta(days=7)).date().isoformat()
        def prune(ws, date_col_name="FechaISO"):
            records = ws.get_all_records()
            headers = ws.row_values(1)
            if not headers: return
            if date_col_name not in headers: return
            idx_date = headers.index(date_col_name)+1
            keep_rows = [1]  # header
            for i, r in enumerate(records, start=2):
                d = str(r.get(date_col_name,""))
                if d >= cutoff:
                    keep_rows.append(i)
            # si hay demasiadas filas viejas, recreamos hoja con las que quedan
            if len(keep_rows) < len(records):
                name = ws.title
                data_to_keep = [headers]
                for i in keep_rows[1:]:
                    data_to_keep.append(ws.row_values(i))
                SS.del_worksheet(ws)
                new_ws = SS.add_worksheet(title=name, rows=max(1000,len(data_to_keep)+10), cols=len(headers)+2)
                new_ws.update("A1", data_to_keep)
                return new_ws
            return ws
        new_mkt = prune(SHEET_MKTLOG)
        if new_mkt: 
            globals()["SHEET_MKTLOG"] = new_mkt
    except Exception as e:
        log_error(e, "weekly_cleanup")

# =========================
# ▶️ Main
# =========================
def main():
    print("🚀 Bot corriendo...")
    try:
        # 1) Apertura/cierre + heartbeat
        monitor_markets_and_notify()

        # 2) Señales (DKNG / ES). Entrada = último precio actual.
        for ticker in WATCHLIST:
            try:
                # Último precio 1m
                df = fetch_yf(ticker, "1m", "1d")
                if df is None or df.empty:
                    continue
                entry = float(df["Close"].iloc[-1])
                # Decidir lado por cruce EMA13/21 en 5m
                df5 = fetch_yf(ticker, "5m", "5d")
                side = "buy"
                if df5 is not None and not df5.empty:
                    e13, e21 = ema(df5["Close"],13), ema(df5["Close"],21)
                    if e13.iloc[-1] < e21.iloc[-1]:
                        side = "sell"
                process_signal(ticker, side, entry)
            except Exception as e_tkr:
                log_error(e_tkr, f"signal_loop({ticker})")

        # 3) Confirmaciones pendientes
        check_pending_confirmations()

        # 4) Limpieza semanal (ligera, inofensiva si corre varias veces)
        if now_et().weekday() == 6 and now_et().hour in (18,19):  # domingo tarde-noche
            weekly_cleanup()

        print("✅ Ciclo ok.")
    except Exception as e:
        log_error(e, "main")

if __name__ == "__main__":
    main()
