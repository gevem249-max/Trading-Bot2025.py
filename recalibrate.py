# recalibrate.py — script independiente para recalibración de pesos
import os, json, datetime as dt
import pandas as pd
import numpy as np
import gspread
from google.oauth2.service_account import Credentials
import yfinance as yf

# ======================
# Configuración
# ======================
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
GS_JSON = json.loads(os.getenv("GOOGLE_SHEETS_JSON"))
CREDS = Credentials.from_service_account_info(
    GS_JSON, scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
GC = gspread.authorize(CREDS)
SHEET = GC.open_by_key(SPREADSHEET_ID).sheet1

# ======================
# Mapear tickers a Yahoo Finance
# ======================
def map_ticker_yf(ticker):
    t = ticker.upper()
    if t == "MES": return "^GSPC"
    if t == "MNQ": return "^NDX"
    if t == "MYM": return "^DJI"
    if t == "M2K": return "^RUT"
    if t == "BTCUSD": return "BTC-USD"
    if t == "ETHUSD": return "ETH-USD"
    if t == "SOLUSD": return "SOL-USD"
    if t == "ADAUSD": return "ADA-USD"
    if t == "XRPUSD": return "XRP-USD"
    return t

# ======================
# Indicadores técnicos
# ======================
def ema(series, span): 
    return series.ewm(span=span, adjust=False).mean()

def rsi(series, period=14):
    delta = series.diff().squeeze()
    up = np.where(delta > 0, delta, 0.0)
    down = np.where(delta < 0, -delta, 0.0)
    roll_up = pd.Series(up, index=series.index).rolling(period).mean()
    roll_down = pd.Series(down, index=series.index).rolling(period).mean()
    rs = roll_up / (roll_down + 1e-9)
    return 100 - (100/(1+rs))

def macd(series, fast=12, slow=26, signal=9):
    exp1 = series.ewm(span=fast, adjust=False).mean()
    exp2 = series.ewm(span=slow, adjust=False).mean()
    macd_line = exp1 - exp2
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line

# ======================
# Recalibración avanzada
# ======================
def recalibrate():
    try:
        vals = SHEET.get_all_records()
        if not vals:
            log_debug("⚠️ No hay datos en la hoja para recalibrar.")
            return

        df = pd.DataFrame(vals)
        df = df[df["Resultado"].isin(["Win","Loss"])]

        if df.empty:
            log_debug("⚠️ No hay suficientes resultados para recalibrar.")
            return

        # Métricas
        total = len(df)
        wins = (df["Resultado"] == "Win").sum()
        losses = (df["Resultado"] == "Loss").sum()
        winrate = round((wins / total) * 100, 2)

        avg_win_prob = df[df["Resultado"]=="Win"]["ProbFinal"].mean()
        avg_loss_prob = df[df["Resultado"]=="Loss"]["ProbFinal"].mean()

        sniper_hits, sniper_miss = 0, 0
        for tkr in df["Ticker"].unique():
            try:
                data = yf.download(map_ticker_yf(tkr), period="5d", interval="5m", progress=False)
                if data.empty: continue
                close = data["Close"]
                e8, e21 = ema(close, 8), ema(close, 21)
                r = rsi(close).iloc[-1]
                macd_line, signal_line = macd(close)
                sniper_ok = ((e8.iloc[-1] > e21.iloc[-1]) and (r > 50) and (macd_line.iloc[-1] > signal_line.iloc[-1]))
                if sniper_ok: sniper_hits += 1
                else: sniper_miss += 1
            except Exception as e:
                log_debug(f"⚠️ Error analizando {tkr}: {e}")

        sniper_rate = round((sniper_hits / (sniper_hits + sniper_miss + 1e-6)) * 100, 2)
        new_threshold = max(70, min(90, int(avg_win_prob)))

        # Guardar resultados en hoja calibration
        try:
            try:
                sheet2 = GC.open_by_key(SPREADSHEET_ID).worksheet("calibration")
            except gspread.WorksheetNotFound:
                sheet2 = GC.open_by_key(SPREADSHEET_ID).add_worksheet("calibration", rows=100, cols=5)

            sheet2.update("A1:E1", [["Fecha","Winrate","AvgWinProb","SniperRate","NuevoThreshold"]])
            sheet2.append_row([
                dt.datetime.now().isoformat(),
                winrate, round(avg_win_prob,1), sniper_rate, new_threshold
            ])
            log_debug("✅ Recalibración completada y guardada.")
        except Exception as e:
            log_debug(f"⚠️ No se pudo guardar calibración: {e}")

    except Exception as e:
        log_debug(f"❌ Error global recalibrate: {e}")

# ======================
# Log de ejecución
# ======================
def log_debug(message):
    try:
        try:
            dbg = GC.open_by_key(SPREADSHEET_ID).worksheet("debug")
        except gspread.WorksheetNotFound:
            dbg = GC.open_by_key(SPREADSHEET_ID).add_worksheet("debug", rows=1000, cols=2)
            dbg.update("A1:B1", [["Fecha","Mensaje"]])
        dbg.append_row([dt.datetime.now().isoformat(), message])
    except Exception as e:
        print("⚠️ Error guardando log:", e)

if __name__ == "__main__":
    recalibrate()
