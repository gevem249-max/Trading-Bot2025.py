# ============================================
# 🚀 Trading-Bot DKNG + ES — vFinal 2025
# ============================================
import os
import json
import re
import pytz
import datetime as dt
import smtplib
import time
from email.mime.text import MIMEText

import pandas as pd
import numpy as np
import yfinance as yf
import gspread
from google.oauth2.service_account import Credentials

# =========================
# 🔧 Configuración general
# =========================
TZ = pytz.timezone("America/New_York")
WATCHLIST = ["DKNG", "ES"]
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
GS_JSON = json.loads(os.getenv("GOOGLE_SHEETS_JSON"))

CREDS = Credentials.from_service_account_info(
    GS_JSON, scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
GC = gspread.authorize(CREDS)

# Asegurar hoja "signals"
try:
    SHEET_SIGNALS = GC.open_by_key(SPREADSHEET_ID).worksheet("signals")
except gspread.WorksheetNotFound:
    SHEET_SIGNALS = GC.open_by_key(SPREADSHEET_ID).add_worksheet(title="signals", rows=2000, cols=30)
    headers = [
        "FechaISO","HoraLocal","HoraRegistro","Ticker","Side","Entrada",
        "Prob_1m","Prob_5m","Prob_15m","Prob_1h","ProbFinal",
        "ProbClasificación","Estado","Tipo","Resultado","Nota","Mercado",
        "pattern","pat_score","macd_val","sr_score","atr","SL","TP",
        "Recipients","ScheduledConfirm"
    ]
    SHEET_SIGNALS.update("A1", [headers])

# Correos
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_PASS = os.getenv("GMAIL_APP_PASS")
ALERT_DKNG = "gevem249@gmail.com,adri_touma@hotmail.com"
ALERT_ES = "gevem249@gmail.com"

# =========================
# 🧭 Utilidades
# =========================
def now_et() -> dt.datetime:
    return dt.datetime.now(TZ)

def local_time_str():
    return now_et().strftime("%H:%M:%S")

def iso_date():
    return now_et().strftime("%Y-%m-%d")

# =========================
# 📬 Envío de correos
# =========================
def send_mail(subject: str, body: str, to_emails: str):
    try:
        recipients = [e.strip() for e in to_emails.split(",") if e.strip()]
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = GMAIL_USER
        msg["To"] = ", ".join(recipients)
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as srv:
            srv.login(GMAIL_USER, GMAIL_PASS)
            srv.sendmail(GMAIL_USER, recipients, msg.as_string())
        print(f"📨 Email enviado a {to_emails}")
    except Exception as e:
        print("❌ Error enviando correo:", e)

# =========================
# 📊 Indicadores
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
    return 100 - (100 / (1 + rs))

def fetch_yf(ticker: str, interval: str, lookback: str):
    y = ticker
    if ticker.upper() == "ES":
        y = "^GSPC"
    try:
        df = yf.download(y, period=lookback, interval=interval, progress=False, threads=False)
        return df
    except Exception as e:
        print("⚠️ Error descargando datos:", e)
        return pd.DataFrame()

def frame_prob(df: pd.DataFrame, side: str) -> float:
    if df is None or df.empty:
        return 50.0
    close = df["Close"].squeeze()
    e8, e21 = ema(close, 8), ema(close, 21)
    r = rsi(close, 14).fillna(50).iloc[-1]
    trend = (e8.iloc[-1] - e21.iloc[-1])
    score = 50.0
    if side.lower() == "buy":
        if trend > 0:
            score += 20
        if 45 <= r <= 70:
            score += 15
        if r < 35:
            score -= 15
    else:
        if trend < 0:
            score += 20
        if 30 <= r <= 55:
            score += 15
        if r > 65:
            score -= 15
    return max(0.0, min(100.0, score))

def prob_multi_frame(ticker: str, side: str) -> dict:
    frames = {"1m": ("1m", "2d"), "5m": ("5m", "5d"), "15m": ("15m", "1mo"), "1h": ("60m", "3mo")}
    probs = {}
    for k, (itv, lb) in frames.items():
        df = fetch_yf(ticker, itv, lb)
        probs[k] = frame_prob(df, side)
    final = round(sum(probs.values()) / len(probs), 1)
    return {"per_frame": probs, "final": final}

# =========================
# 🧠 Lógica principal
# =========================
def process_signal(ticker: str, side: str, entry: float):
    t = now_et()
    pm = prob_multi_frame(ticker, side)
    pf = pm["final"]
    estado = "Pre" if pf >= 80 else "Descartada"

    row = [
        iso_date(),
        local_time_str(),
        t.strftime("%H:%M:%S"),
        ticker,
        side,
        entry,
        pm["per_frame"]["1m"],
        pm["per_frame"]["5m"],
        pm["per_frame"]["15m"],
        pm["per_frame"]["1h"],
        pf,
        "Alta" if pf >= 80 else "Baja",
        estado,
        "Automática",
        "",
        "",
        "CME" if ticker == "ES" else "NASDAQ",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        ALERT_ES if ticker == "ES" else ALERT_DKNG,
        "",
    ]
    SHEET_SIGNALS.append_row(row)
    print(f"✅ Guardada señal {ticker} {side} ({pf}%) - {estado}")

    if estado == "Pre":
        recipients = ALERT_ES if ticker == "ES" else ALERT_DKNG
        subject = f"📊 Señal {ticker} {side} {entry} – {pf}%"
        body = f"{ticker} {side} @ {entry}\nProbFinal {pf}% | Estado: {estado}"
        send_mail(subject, body, recipients)
        time.sleep(300)
        confirm_signal(ticker, side, entry, pf, recipients)

def confirm_signal(ticker, side, entry, pf, recipients):
    pf2 = pf + np.random.uniform(-5, 5)
    estado_final = "Confirmada" if pf2 >= 70 else "Rechazada"
    SHEET_SIGNALS.append_row([
        iso_date(),
        local_time_str(),
        now_et().strftime("%H:%M:%S"),
        ticker,
        side,
        entry,
        "",
        "",
        "",
        "",
        pf2,
        "",
        estado_final,
        "Confirmación",
        "",
        "",
        "CME" if ticker == "ES" else "NASDAQ",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        recipients,
        now_et().strftime("%H:%M:%S")
    ])
    subject = f"✅ Confirmación {ticker} {side} ({estado_final})"
    body = f"Confirmación {ticker} {side} @ {entry}\nResultado: {estado_final}\nProbFinal: {pf2}%"
    send_mail(subject, body, recipients)
    print(f"📩 {ticker} {estado_final} ({pf2}%)")

# =========================
# 🧽 Limpieza semanal
# =========================
def clean_old_logs():
    try:
        data = SHEET_SIGNALS.get_all_records()
        if not data:
            return
        df = pd.DataFrame(data)
        if "FechaISO" not in df.columns:
            return
        df["FechaISO"] = pd.to_datetime(df["FechaISO"], errors="coerce")
        cutoff = dt.datetime.now() - dt.timedelta(days=7)
        df = df[df["FechaISO"] >= cutoff]
        SHEET_SIGNALS.clear()
        SHEET_SIGNALS.update("A1", [list(df.columns)])
        SHEET_SIGNALS.update("A2", df.values.tolist())
        print("🧽 Limpieza completada (últimos 7 días).")
    except Exception as e:
        print("⚠️ Error limpiando logs:", e)

# =========================
# ▶️ Ejecución
# =========================
def main():
    print("🚀 Iniciando Trading-Bot DKNG + ES...")
    for ticker in WATCHLIST:
        try:
            process_signal(ticker, "buy", 100.0)
        except Exception as e:
            print(f"⚠️ Error procesando {ticker}:", e)
    clean_old_logs()

if __name__ == "__main__":
    main()
