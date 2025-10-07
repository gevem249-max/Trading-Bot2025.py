# clean_logs.py — limpia registros viejos en Google Sheets

import os, json, datetime as dt
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import pytz

TZ = pytz.timezone("America/New_York")

# Config
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
gs_raw = os.getenv("GOOGLE_SHEETS_JSON", "")
GS_JSON = json.loads(gs_raw)

CREDS = Credentials.from_service_account_info(
    GS_JSON, scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
GC = gspread.authorize(CREDS)
SHEET = GC.open_by_key(SPREADSHEET_ID).sheet1

def now_et():
    return dt.datetime.now(TZ)

def clean_old_logs(days=7):
    try:
        vals = SHEET.get_all_records()
        if not vals:
            print("⚠️ No hay registros para limpiar")
            return
        df = pd.DataFrame(vals)
        if "Fecha" not in df.columns:
            print("⚠️ No existe columna 'Fecha' en hoja")
            return
        df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce")
        cutoff = now_et() - dt.timedelta(days=days)
        keep = df[df["Fecha"] >= cutoff]
        SHEET.clear()
        SHEET.append_row(list(keep.columns))
        for _, row in keep.iterrows():
            SHEET.append_row([row.get(c,"") for c in keep.columns])
        print(f"🧹 Limpieza hecha, {len(keep)} filas retenidas.")
    except Exception as e:
        print("❌ Error limpiando logs:", e)

if __name__ == "__main__":
    clean_old_logs(7)
