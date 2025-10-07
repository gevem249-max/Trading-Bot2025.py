# bot.py — Trading-Bot DKNG + ES con autogeneración de hojas + limpieza semanal + estadísticas

import os
import json
import pytz
import datetime as dt
import smtplib
from email.mime.text import MIMEText

import pandas as pd
import numpy as np
import yfinance as yf

import gspread
from google.oauth2.service_account import Credentials

# =========================
# 🔧 CONFIGURACIÓN
# =========================
TZ = pytz.timezone("America/New_York")
WATCHLIST = ["DKNG", "ES"]  # activos a monitorear

SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
GS_JSON = json.loads(os.getenv("GOOGLE_SHEETS_JSON"))

CREDS = Credentials.from_service_account_info(
    GS_JSON, scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
GC = gspread.authorize(CREDS)
SPREAD = GC.open_by_key(SPREADSHEET_ID)

# =========================
# 🗂️ CREAR HOJAS SI NO EXISTEN
# =========================
def ensure_sheet(name, headers=None, cols=25):
    try:
        sheet = SPREAD.worksheet(name)
        return sheet
    except gspread.WorksheetNotFound:
        print(f"⚠️ Hoja '{name}' no encontrada. Creando una nueva...")
        sheet = SPREAD.add_worksheet(title=name, rows=500, cols=cols)
        if headers:
            sheet.insert_row(headers, 1)
        print(f"✅ Hoja '{name}' creada correctamente.")
        return sheet

HEADERS_SIGNALS = [
    "FechaISO","HoraLocal","HoraRegistro","Ticker","Side","Entrada",
    "Prob_1m","Prob_5m","Prob_15m","Prob_1h","ProbFinal","ProbClasificación",
    "Estado","Tipo","Resultado","Nota","Mercado","pattern","pat_score",
    "macd_val","sr_score","atr","SL","TP","Recipients","ScheduledConfirm"
]

SHEET_SIGNALS = ensure_sheet("signals", HEADERS_SIGNALS)
SHEET_META = ensure_sheet("meta", ["Métrica", "Valor"], cols=2)

# =========================
# 📧 GMAIL CONFIG
# =========================
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_PASS = os.getenv("GMAIL_APP_PASS")

ALERT_DKNG = "gevem249@gmail.com,adri_touma@hotmail.com"
ALERT_ES = "gevem249@gmail.com"

# =========================
# ⏰ FUNCIONES AUXILIARES
# =========================
def now_et() -> dt.datetime:
    return dt.datetime.now(TZ)

def send_mail(subject: str, body: str, to_emails: str):
    try:
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
        print("❌ Error enviando correo:", e)

# =========================
# 📈 INDICADORES
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
    return 100 - (100/(1+rs))

def frame_prob(df: pd.DataFrame, side: str) -> float:
    if df is None or df.empty: 
        return 50.0
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
    if ticker.upper()=="ES": y="^GSPC"
    try:
        df = yf.download(y, period=lookback, interval=interval, progress=False, threads=False)
    except Exception:
        df = pd.DataFrame()
    return df

def prob_multi_frame(ticker: str, side: str) -> dict:
    frames = {"1m":("1m","2d"),"5m":("5m","5d"),"15m":("15m","1mo"),"1h":("60m","3mo")}
    probs = {}
    for k,(itv,lb) in frames.items():
        df = fetch_yf(ticker, itv, lb)
        probs[k] = frame_prob(df, side)
    final = round(sum(probs.values())/len(probs),1)
    return {"per_frame":probs,"final":final}

# =========================
# 🧹 LIMPIEZA SEMANAL
# =========================
def clean_old_records():
    try:
        data = SHEET_SIGNALS.get_all_records()
        if not data:
            return
        df = pd.DataFrame(data)
        df["FechaISO"] = pd.to_datetime(df["FechaISO"], errors="coerce")
        cutoff = now_et().date() - dt.timedelta(days=7)
        df = df[df["FechaISO"].dt.date >= cutoff]
        SHEET_SIGNALS.clear()
        SHEET_SIGNALS.insert_row(list(df.columns), 1)
        for _, row in df.iterrows():
            SHEET_SIGNALS.append_row(row.astype(str).tolist())
        print("🧹 Registros antiguos (más de 7 días) eliminados correctamente.")
    except Exception as e:
        print("⚠️ Error limpiando registros viejos:", e)

# =========================
# 📊 ESTADÍSTICAS (META)
# =========================
def update_meta():
    try:
        data = SHEET_SIGNALS.get_all_records()
        if not data:
            SHEET_META.update("A1:B5", [
                ["Métrica","Valor"],
                ["Total Señales", 0],
                ["Pre (≥80%)", 0],
                ["Descartadas (<80%)", 0],
                ["Promedio ProbFinal", 0],
            ])
            return
        df = pd.DataFrame(data)
        total = len(df)
        pre = len(df[df["Estado"]=="Pre"])
        desc = len(df[df["Estado"]=="Descartada"])
        avg_prob = round(df["ProbFinal"].astype(float).mean(),1) if "ProbFinal" in df else 0
        stats = [
            ["Métrica","Valor"],
            ["Total Señales", total],
            ["Pre (≥80%)", pre],
            ["Descartadas (<80%)", desc],
            ["Promedio ProbFinal", avg_prob],
            ["Última Actualización", now_et().strftime("%Y-%m-%d %H:%M:%S")]
        ]
        SHEET_META.update("A1:B6", stats)
        print("📊 Hoja 'meta' actualizada correctamente.")
    except Exception as e:
        print("⚠️ Error actualizando hoja meta:", e)

# =========================
# 📡 PROCESAR SEÑALES
# =========================
def process_signal(ticker: str, side: str, entry: float):
    t = now_et()
    pm = prob_multi_frame(ticker, side)
    pf = pm["final"]
    estado = "Pre" if pf >= 80 else "Descartada"

    # Registrar en Google Sheets
    row = [
        t.strftime("%Y-%m-%d"), t.strftime("%H:%M:%S"), dt.datetime.utcnow().strftime("%H:%M:%S"),
        ticker, side, entry,
        pm["per_frame"]["1m"], pm["per_frame"]["5m"], pm["per_frame"]["15m"], pm["per_frame"]["1h"],
        pf, "Alta" if pf >= 80 else "Media" if pf >= 60 else "Baja",
        estado, "Auto", "", "", "NYSE" if ticker=="ES" else "NASDAQ",
        "", "", "", "", "", "", "", "", "", ""
    ]
    SHEET_SIGNALS.append_row(row)
    print(f"📝 Registrado {ticker} {side} {pf}% → {estado}")

    # Notificación por correo
    if estado == "Pre":
        recipients = ALERT_ES if ticker.upper()=="ES" else ALERT_DKNG
        subject = f"📊 Señal {ticker} {side} {entry} – {pf}%"
        body = f"{ticker} {side} @ {entry}\nProbFinal {pf}% | Estado: {estado}"
        send_mail(subject, body, recipients)

# =========================
# ▶️ MAIN
# =========================
def main():
    print("🚀 Bot corriendo...")
    clean_old_records()
    for ticker in WATCHLIST:
        try:
            process_signal(ticker, "buy", 100.0)
        except Exception as e:
            print("Error con", ticker, ":", e)
    update_meta()

if __name__ == "__main__":
    main()
