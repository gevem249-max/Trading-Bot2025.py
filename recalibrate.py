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
    vals = SHEET.get_all_records()
    if not vals:
        print("⚠️ No hay datos para recalibrar.")
        return

    df = pd.DataFrame(vals)
    df = df[df["Resultado"].isin(["Win","Loss"])]

    if df.empty:
        print("⚠️ No hay suficientes resultados.")
        return

    # Métricas generales
    total = len(df)
    wins = (df["Resultado"] == "Win").sum()
    losses = (df["Resultado"] == "Loss").sum()
    winrate = round((wins / total) * 100, 2)

    avg_win_prob = df[df["Resultado"]=="Win"]["ProbFinal"].mean()
    avg_loss_prob = df[df["Resultado"]=="Loss"]["ProbFinal"].mean()

    # Sniper rate básico
    sniper_hits, sniper_miss = 0, 0
    for tkr in df["Ticker"].unique():
        try:
            data = yf.download(tkr, period="5d", interval="5m", progress=False)
            if data.empty: 
                continue

            close = data["Close"]
            e8, e21 = ema(close, 8), ema(close, 21)
            r = rsi(close).iloc[-1]
            macd_line, signal_line = macd(close)

            sniper_ok = (
                (e8.iloc[-1] > e21.iloc[-1]) and
                (r > 50) and
                (macd_line.iloc[-1] > signal_line.iloc[-1])
            )
            if sniper_ok:
                sniper_hits += 1
            else:
                sniper_miss += 1
        except Exception as e:
            print(f"⚠️ Error analizando {tkr}: {e}")

    sniper_rate = round((sniper_hits / (sniper_hits + sniper_miss + 1e-6)) * 100, 2)

    # Ajuste dinámico de threshold
    new_threshold = max(70, min(90, int(avg_win_prob)))
    print(f"✅ Recalibración {dt.datetime.now()}")
    print(f"Total: {total} | Wins: {wins} | Losses: {losses} | Winrate: {winrate}%")
    print(f"Prob medio WIN: {avg_win_prob:.1f} | Prob medio LOSS: {avg_loss_prob:.1f}")
    print(f"Sniper precisión: {sniper_rate}%")
    print(f"Nuevo threshold recomendado: {new_threshold}%")

    # Guardar en Google Sheets (pestaña calibration)
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
    except Exception as e:
        print("⚠️ No se pudo guardar calibración:", e)

if __name__ == "__main__":
    recalibrate()
