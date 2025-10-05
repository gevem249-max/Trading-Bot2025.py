# update_results.py — valida operaciones abiertas y marca Win/Loss
import os, json
import gspread
import yfinance as yf
import pandas as pd
from google.oauth2.service_account import Credentials

# === Configuración Google Sheets ===
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
GS_JSON = json.loads(os.getenv("GOOGLE_SHEETS_JSON"))
creds = Credentials.from_service_account_info(
    GS_JSON, scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
gc = gspread.authorize(creds)
sheet = gc.open_by_key(SPREADSHEET_ID).sheet1

# === Leer datos ===
data = sheet.get_all_records()
df = pd.DataFrame(data)

# Reglas (puedes ajustar)
TP_PCT = 0.01   # +1% take profit
SL_PCT = 0.005  # -0.5% stop loss

for i, row in df.iterrows():
    if row["Resultado"] in ["Win", "Loss"]:
        continue  # ya evaluado
    if not row.get("Ticker") or not row.get("Entrada"):
        continue

    ticker = row["Ticker"]
    try:
        entrada = float(row["Entrada"])
        side = row.get("Side", "Long")

        data = yf.download(ticker, period="1d", interval="5m")
        if data.empty:
            continue
        ultimo = data["Close"].iloc[-1]

        res, nota = None, ""
        if side == "Long":
            if ultimo >= entrada * (1+TP_PCT):
                res, nota = "Win", "hit TP"
            elif ultimo <= entrada * (1-SL_PCT):
                res, nota = "Loss", "stop loss"
        elif side == "Short":
            if ultimo <= entrada * (1-TP_PCT):
                res, nota = "Win", "hit TP"
            elif ultimo >= entrada * (1+SL_PCT):
                res, nota = "Loss", "stop loss"

        if res:
            df.at[i,"Resultado"] = res
            df.at[i,"Nota"] = nota
            print(f"✅ {ticker} -> {res} ({nota})")

    except Exception as e:
        print(f"⚠️ Error en {ticker}: {e}")

# === Subir de nuevo ===
sheet.update([df.columns.values.tolist()] + df.values.tolist())
print("🔄 Resultados actualizados en Google Sheets")
