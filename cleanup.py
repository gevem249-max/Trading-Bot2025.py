import os, json
import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
GS_JSON = json.loads(os.getenv("GOOGLE_SHEETS_JSON"))
CREDS = Credentials.from_service_account_info(
    GS_JSON, scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
GC = gspread.authorize(CREDS)

def cleanup_sheet(sheet_name, keep_rows=200):
    try:
        sh = GC.open_by_key(SPREADSHEET_ID)
        ws = sh.worksheet(sheet_name)
        values = ws.get_all_values()
        if len(values) > keep_rows:
            ws.batch_clear([f"A{keep_rows+1}:Z{len(values)}"])
            print(f"✅ Limpieza hecha en {sheet_name}, se conservaron {keep_rows} filas")
        else:
            print(f"ℹ️ {sheet_name} no necesita limpieza ({len(values)} filas)")
    except Exception as e:
        print(f"⚠️ Error limpiando {sheet_name}: {e}")

if __name__ == "__main__":
    for log_sheet in ["debug", "calibration"]:
        cleanup_sheet(log_sheet, keep_rows=200)
