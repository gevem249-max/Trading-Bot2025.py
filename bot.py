import os, json, time, imaplib, email, re, math, ssl, smtplib, pytz, datetime as dt
from email.mime.text import MIMEText

import pandas as pd
import numpy as np
import yfinance as yf

import gspread
from google.oauth2.service_account import Credentials

# =========================
# 🔧 Config
# =========================
TZ = pytz.timezone("America/New_York")  # NJ/ET
MICRO_TICKERS = {"MES","MNQ","MYM","M2K","MGC","MCL","M6E","M6B","M6A"}
CRYPTO_TICKERS = {"BTCUSD","ETHUSD","SOLUSD","ADAUSD","XRPUSD"}
FOREX_RE = re.compile(r"^[A-Z]{6}$")  # EURUSD, GBPUSD, etc.

# Google Sheets
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
GS_JSON = json.loads(os.getenv("GOOGLE_SHEETS_JSON"))
CREDS = Credentials.from_service_account_info(GS_JSON, scopes=["https://www.googleapis.com/auth/spreadsheets"])
GC = gspread.authorize(CREDS)
SHEET = GC.open_by_key(SPREADSHEET_ID).sheet1

# Gmail (envío). Si quieres leer correos de Robinhood, ver bloque IMAP más abajo.
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_PASS = os.getenv("GMAIL_APP_PASS")

# =========================
# 🧭 Utilidades de tiempo/mercados
# =========================
def now_et():
    return dt.datetime.now(TZ)

def classify_market(ticker: str) -> str:
    t = ticker.upper().replace("/", "")
    if t in MICRO_TICKERS:
        return "cme_micro"
    if t in CRYPTO_TICKERS:
        return "crypto"
    if FOREX_RE.match(t) and t not in CRYPTO_TICKERS:
        return "forex"
    # por defecto tratamos como acción USA
    return "equity"

def is_market_open(market: str, t: dt.datetime) -> bool:
    # t es ET timezone-aware
    wd = t.weekday()  # 0=lunes ... 6=domingo
    h, m = t.hour, t.minute

    if market == "equity":
        # NYSE/NASDAQ: Lun-Vie 09:30–16:00 ET
        if wd >= 5: return False
        open_min = 9*60 + 30
        close_min = 16*60
        cur_min = h*60 + m
        return open_min <= cur_min < close_min

    if market == "cme_micro":
        # Futuros CME (Globex): Dom 18:00 – Vie 17:00, pausa diaria 17:00-18:00
        # Aprox: abierto todos los días excepto 17:00-18:00 ET; y cierra viernes 17:00 hasta domingo 18:00
        if wd == 5:  # sábado
            return False
        if wd == 6 and (h < 18):  # domingo antes de 18:00
            return False
        if wd == 4 and (h >= 17):  # viernes 17:00 en adelante cerrado
            return False
        # pausa diaria 17:00-18:00
        if h == 17:
            return False
        return True

    if market == "forex":
        # Forex: Abre domingo 17:00 ET, cierra viernes 17:00 ET
        if wd == 5:  # sábado
            return False
        if wd == 6 and h < 17:
            return False
        if wd == 4 and h >= 17:
            return False
        return True

    if market == "crypto":
        return True

    return False

def is_window_open_event(market: str, t: dt.datetime) -> bool:
    """True si estamos en los primeros 10 minutos tras apertura."""
    # Usado para mandar "mercado abrió"
    if market == "equity":
        return t.weekday() < 5 and (t.hour == 9 and 30 <= t.minute < 40)
    if market == "cme_micro":
        # apertura diaria post-pausa 18:00
        return (t.hour == 18 and t.minute < 10) or (t.weekday()==6 and t.hour==18 and t.minute<10)
    if market == "forex":
        # domingo 17:00
        return t.weekday()==6 and t.hour==17 and t.minute < 10
    if market == "crypto":
        return False
    return False

def is_window_close_event(market: str, t: dt.datetime) -> bool:
    """True si estamos en los últimos 10 minutos previo al cierre (o justo tras)."""
    if market == "equity":
        return t.weekday() < 5 and (t.hour == 16 and t.minute < 10)
    if market == "cme_micro":
        # pausa 17:00-18:00
        return t.hour == 17 and t.minute < 10
    if market == "forex":
        # viernes 17:00
        return t.weekday()==4 and t.hour==17 and t.minute < 10
    if market == "crypto":
        return False
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
    up = np.where(delta>0, delta, 0.0)
    down = np.where(delta<0, -delta, 0.0)
    roll_up = pd.Series(up, index=series.index).rolling(period).mean()
    roll_down = pd.Series(down, index=series.index).rolling(period).mean()
    rs = roll_up / (roll_down + 1e-9)
    return 100 - (100/(1+rs))

def frame_prob(df: pd.DataFrame, side: str) -> float:
    """
    Sencillo: prob sube si EMA8>EMA21 (BUY) o EMA8<EMA21 (SELL), RSI en zona saludable
    """
    if df.empty: return 50.0
    close = df["Close"]
    e8 = ema(close, 8)
    e21 = ema(close, 21)
    r = rsi(close, 14).fillna(50).iloc[-1]
    trend = (e8.iloc[-1] - e21.iloc[-1])

    score = 50.0
    if side.lower() == "buy":
        if trend > 0: score += 20
        if 45 <= r <= 70: score += 15
        if r < 35: score -= 15
    else:
        if trend < 0: score += 20
        if 30 <= r <= 55: score += 15
        if r > 65: score -= 15

    return max(0.0, min(100.0, score))

def fetch_yf(ticker: str, interval: str, lookback: str):
    # map Robinhood/Plus500 tickers a Yahoo si hace falta
    y = ticker
    if ticker.upper() in MICRO_TICKERS:
        # aproximación con índice subyacente
        if ticker.upper()=="MES": y = "^GSPC"  # S&P500
        if ticker.upper()=="MNQ": y = "^NDX"   # Nasdaq-100
        if ticker.upper()=="MYM": y = "^DJI"   # Dow
        if ticker.upper()=="M2K": y = "^RUT"   # Russell 2000
    data = yf.download(y, period=lookback, interval=interval, progress=False)
    return data

def prob_multi_frame(ticker: str, side: str) -> dict:
    frames = {
        "1m":  ("1m","2d"),
        "5m":  ("5m","5d"),
        "15m": ("15m","1mo"),
        "1h":  ("60m","3mo"),
    }
    probs = {}
    for k,(itv,lb) in frames.items():
        df = fetch_yf(ticker, itv, lb)
        probs[k] = frame_prob(df, side)
    # ponderación simple
    final = round((probs["1m"]*0.2 + probs["5m"]*0.4 + probs["15m"]*0.25 + probs["1h"]*0.15), 1)
    return {"per_frame": probs, "final": final}

# =========================
# 📑 Google Sheets IO
# =========================
def ensure_headers():
    vals = SHEET.get_all_values()
    if not vals:
        headers = ["FechaISO","HoraLocal","Ticker","Side","Entrada","Prob_1m","Prob_5m","Prob_15m","Prob_1h","ProbFinal","Estado","Resultado","Nota","Mercado"]
        SHEET.append_row(headers)

def append_signal(row_dict: dict):
    ensure_headers()
    order = ["FechaISO","HoraLocal","Ticker","Side","Entrada","Prob_1m","Prob_5m","Prob_15m","Prob_1h","ProbFinal","Estado","Resultado","Nota","Mercado"]
    SHEET.append_row([row_dict.get(k,"") for k in order])

def update_row_status(ticker, fecha_iso, estado=None, resultado=None, nota=None):
    vals = SHEET.get_all_values()
    if not vals: return
    headers = vals[0]
    rows = vals[1:]
    idx_map = {h:i for i,h in enumerate(headers)}
    for i, r in enumerate(rows, start=2):
        if r[idx_map["Ticker"]]==ticker and r[idx_map["FechaISO"]]==fecha_iso:
            if estado is not None: SHEET.update_cell(i, idx_map["Estado"]+1, estado)
            if resultado is not None: SHEET.update_cell(i, idx_map["Resultado"]+1, resultado)
            if nota is not None: SHEET.update_cell(i, idx_map["Nota"]+1, nota)
            break

def hourly_summary_email(market: str):
    vals = SHEET.get_all_records()
    if not vals: return
    today = now_et().date().isoformat()
    df = pd.DataFrame(vals)
    if "FechaISO" not in df.columns: return
    dft = df[df["FechaISO"].str.startswith(today) & (df["Mercado"]==market)]
    if dft.empty:
        send_mail(f"⏰ {market.upper()} – Resumen horario", "No hay señales registradas hoy.")
        return
    high = dft[dft["ProbFinal"]>=80]
    low  = dft[dft["ProbFinal"]<80]
    txt = []
    txt.append(f"🕒 Resumen {market.upper()} @ {now_et().strftime('%Y-%m-%d %H:%M ET')}")
    txt.append(f"Señales ≥80%: {len(high)} | Señales <80%: {len(low)}")
    if not high.empty:
        win_h = (high["Resultado"]=="Win").sum()
        loss_h = (high["Resultado"]=="Loss").sum()
        txt.append(f"≥80% → Win: {win_h} | Loss: {loss_h}")
    if not low.empty:
        win_l = (low["Resultado"]=="Win").sum()
        loss_l = (low["Resultado"]=="Loss").sum()
        txt.append(f"<80% (backtest) → Win: {win_l} | Loss: {loss_l}")
    send_mail(f"⏰ {market.upper()} – Resumen horario", "\n".join(txt))

# =========================
# 📩 Lectura de alertas (opcional – Robinhood por correo)
# =========================
def read_robinhood_new_alerts():
    """
    Opcional: si quieres ingestión automática desde Gmail.
    Busca correos UNSEEN de Robinhood y extrae: ticker, side, entry.
    Ajusta el FROM/subject según lo que recibes tú.
    """
    alerts = []
    try:
        imap = imaplib.IMAP4_SSL("imap.gmail.com")
        imap.login(GMAIL_USER, GMAIL_PASS)
        imap.select("INBOX")
        typ, data = imap.search(None, '(UNSEEN FROM "no-reply@robinhood.com")')
        for num in data[0].split():
            typ, msg_data = imap.fetch(num, '(RFC822)')
            msg = email.message_from_bytes(msg_data[0][1])
            subject = msg.get("Subject","")
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type()=="text/plain":
                        body += part.get_payload(decode=True).decode(errors="ignore")
            else:
                body = msg.get_payload(decode=True).decode(errors="ignore")
            text = subject + "\n" + body
            # Regex simple: "DKNG Buy 45.30"
            m = re.search(r"\b([A-Z]{1,5})\b\s+(Buy|Sell)\s+([\d\.]+)", text, re.I)
            if m:
                alerts.append({"ticker": m.group(1).upper(), "side": m.group(2).title(), "entry": float(m.group(3))})
        imap.close(); imap.logout()
    except Exception as e:
        # si no quieres leer correo, ignora
        pass
    return alerts

# =========================
# 🧪 Backtest simple para descartadas
# =========================
def backtest_result(ticker: str, side: str, entry: float, horizon_minutes=15, tp_ticks=0.004, sl_ticks=0.004):
    """
    Miramos el movimiento posterior en 15 min: si hubo avance a favor mayor que en contra.
    tp/sl relativos simples por defecto (0.4%).
    """
    df = fetch_yf(ticker, "1m", "2d")
    if df.empty: return "-"
    last_time = df.index.tz_localize(None)[-1] if df.index.tz is None else df.index[-1].tz_convert(TZ).tz_localize(None)
    # Tomamos últimos 20 minutos
    win = False; loss = False
    # Buscamos la barra más cercana a ahora para simular "después"
    close = df["Close"]
    recent = close.tail(horizon_minutes+1)
    if len(recent) < horizon_minutes+1: return "-"
    max_a_favor = (recent.max()-entry)/entry if side.lower()=="buy" else (entry - recent.min())/entry
    max_en_contra = (entry - recent.min())/entry if side.lower()=="buy" else (recent.max()-entry)/entry
    if max_a_favor >= tp_ticks: win = True
    if max_en_contra >= sl_ticks: loss = True
    if win and not loss: return "Win"
    if loss and not win: return "Loss"
    return "-"

# =========================
# 🚦 Motor principal
# =========================
def process_signal(ticker: str, side: str, entry: float, notify_email: str=None):
    t = now_et()
    market = classify_market(ticker)
    open_now = is_market_open(market, t)

    # 1) prob multi-frame
    pm = prob_multi_frame(ticker, side)
    p1, p5, p15, p1h = pm["per_frame"]["1m"], pm["per_frame"]["5m"], pm["per_frame"]["15m"], pm["per_frame"]["1h"]
    pf = pm["final"]

    # 2) registro PRE o DESCARTADA
    base = {
        "FechaISO": t.strftime("%Y-%m-%d"),
        "HoraLocal": t.strftime("%H:%M"),
        "Ticker": ticker.upper(),
        "Side": side.title(),
        "Entrada": entry,
        "Prob_1m": round(p1,1),
        "Prob_5m": round(p5,1),
        "Prob_15m": round(p15,1),
        "Prob_1h": round(p1h,1),
        "ProbFinal": round(pf,1),
        "Estado": "Pre" if pf>=80 else "Descartada",
        "Resultado": "-",
        "Nota": "",
        "Mercado": market
    }
    append_signal(base)

    if pf >= 80:
        # Pre-señal: enviar ahora
        send_mail(
            f"📊 Pre-señal {ticker} {side} {entry:.4f} – {pf}%",
            f"{ticker} {side} @ {entry:.4f}\nProb: {pf}% (1m {p1:.0f} / 5m {p5:.0f} / 15m {p15:.0f} / 1h {p1h:.0f})\nMercado: {market.upper()}\nEjecución en 5 min."
            , notify_email
        )
        # Esperar 5 min y confirmar si mercado abierto
        time.sleep(5*60)
        t2 = now_et()
        if is_market_open(market, t2) and open_now:  # sigue en sesión
            update_row_status(ticker, base["FechaISO"], estado="Confirmada")
            send_mail(
                f"✅ Confirmación {ticker} {side} {entry:.4f} – {pf}%",
                f"Confirmada {ticker} {side} @ {entry:.4f}\nMercado abierto ({market.upper()})."
                , notify_email
            )
        else:
            update_row_status(ticker, base["FechaISO"], estado="Rechazada", nota="Mercado cerrado")
            send_mail(
                f"⚠️ Rechazada {ticker} {side} – mercado cerrado",
                f"No se confirma la entrada porque el mercado {market.upper()} está cerrado."
                , notify_email
            )
    else:
        # Descartada: hacemos backtest a los 15 min
        time.sleep(15*60)
        res = backtest_result(ticker, side, entry)
        update_row_status(ticker, base["FechaISO"], resultado=res, nota="Backtest 15m")

# =========================
# 📨 Apertura / Cierre / Resumen HOURLY
# =========================
def send_open_close_if_needed():
    """Envía mensajes de apertura y cierre (por mercado) y resumen HOURLY."""
    t = now_et()
    markets = ["equity","cme_micro","forex","crypto"]
    # usamos una segunda pestaña para flags de envío
    try:
        meta = GC.open_by_key(SPREADSHEET_ID).worksheet("meta")
    except gspread.WorksheetNotFound:
        meta = GC.open_by_key(SPREADSHEET_ID).add_worksheet(title="meta", rows=100, cols=3)
        meta.update("A1:C1", [["market","date","last_sent"]])

    meta_vals = meta.get_all_records()
    dfm = pd.DataFrame(meta_vals) if meta_vals else pd.DataFrame(columns=["market","date","last_sent"])

    def get_flag(mkt, key):
        if dfm.empty: return None
        row = dfm[dfm["market"]==mkt]
        if row.empty: return None
        return row.iloc[0].get(key)

    def set_flag(mkt, date_str, label):
        nonlocal dfm
        # upsert
        if dfm.empty or dfm[dfm["market"]==mkt].empty:
            dfm = pd.concat([dfm, pd.DataFrame([{"market":mkt,"date":date_str,"last_sent":label}])], ignore_index=True)
        else:
            idx = dfm.index[dfm["market"]==mkt][0]
            dfm.loc[idx, "date"] = date_str
            dfm.loc[idx, "last_sent"] = label
        # push
        meta.clear()
        meta.update("A1:C1", [["market","date","last_sent"]])
        if not dfm.empty:
            meta.update(f"A2", dfm.values.tolist())

    today = t.strftime("%Y-%m-%d")

    for mkt in markets:
        opened = is_window_open_event(mkt, t)
        closed = is_window_close_event(mkt, t)
        # Abrir
        if opened and get_flag(mkt,"last_sent") != f"open@{today}":
            send_mail(f"🔔 {mkt.upper()} ABRIÓ", f"{mkt.upper()} abrió – {t.strftime('%H:%M ET')}")
            set_flag(mkt, today, f"open@{today}")
        # Cerrar
        if closed and get_flag(mkt,"last_sent") != f"close@{today}":
            send_mail(f"🔕 {mkt.upper()} CERRÓ", f"{mkt.upper()} cerró – {t.strftime('%H:%M ET')}")
            set_flag(mkt, today, f"close@{today}")
        # Resumen HOURLY si está abierto
        if is_market_open(mkt, t) and t.minute in {0,1,2}:  # primera ventana de cada hora
            hourly_summary_email(mkt)

# =========================
# ▶️ Entry points
# =========================
def main():
    ensure_headers()
    # 1) Mensajes apertura/cierre + resumen hourly
    send_open_close_if_needed()

    # 2) Leer alertas (opcional). Si no quieres IMAP, coméntalo y llama process_signal con tus datos.
    alerts = read_robinhood_new_alerts()
    for a in alerts:
        process_signal(a["ticker"], a["side"], a["entry"], notify_email=GMAIL_USER)

    # 3) Ejemplo manual (quitar si ya usas correo)
    # process_signal("DKNG","Buy",45.30, notify_email=GMAIL_USER)
    # process_signal("MES","Sell",4522, notify_email=GMAIL_USER)

if __name__ == "__main__":
    main()
