# recalibrate.py — recalibración avanzada con logging en hoja "calibration"
import os, json, datetime as dt
import pandas as pd, numpy as np, gspread, yfinance as yf
from google.oauth2.service_account import Credentials

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
MAP = {"MES":"^GSPC","MNQ":"^NDX","MYM":"^DJI","M2K":"^RUT",
       "BTCUSD":"BTC-USD","ETHUSD":"ETH-USD","SOLUSD":"SOL-USD",
       "ADAUSD":"ADA-USD","XRPUSD":"XRP-USD"}

def map_ticker_yf(t): return MAP.get(t.upper(), t)

# ======================
# Recalibración
# ======================
def recalibrate():
    vals=SHEET.get_all_records()
    if not vals: return
    df=pd.DataFrame(vals)
    df=df[df["Resultado"].isin(["Win","Loss"])]
    if df.empty: return

    total=len(df); wins=(df["Resultado"]=="Win").sum()
    winrate=round((wins/total)*100,2)
    avg_win=df[df["Resultado"]=="Win"]["ProbFinal"].mean()
    avg_loss=df[df["Resultado"]=="Loss"]["ProbFinal"].mean()

    # Nuevo threshold recomendado
    new_threshold=max(70,min(90,int(avg_win))) if not pd.isna(avg_win) else 80

    # Guardar en hoja calibration
    try:
        try: ws=GC.open_by_key(SPREADSHEET_ID).worksheet("calibration")
        except gspread.WorksheetNotFound:
            ws=GC.open_by_key(SPREADSHEET_ID).add_worksheet("calibration",rows=200,cols=10)
            ws.update("A1:E1",[["Fecha","Winrate","AvgWinProb","AvgLossProb","NuevoThreshold"]])
        ws.append_row([dt.datetime.now().isoformat(), winrate, round(avg_win,1), round(avg_loss,1), new_threshold])
        print(f"✅ Recalibrado: winrate {winrate}% | Nuevo th={new_threshold}")
    except Exception as e:
        print("⚠️ Error guardando calibración:",e)

if __name__=="__main__": recalibrate()
