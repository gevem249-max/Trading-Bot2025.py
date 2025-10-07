# update_results.py — Actualiza señales, resultados y registra estado del mercado (completo y automático)

import os
import json
import datetime as dt
import pytz
import pandas as pd
import yfinance as yf
import gspread
from google.oauth2.service_account import Credentials

# =========================
# ⚙️ Configuración general
# =========================
TZ = pytz.timezone("America/New_York")

SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
GS_JSON = json.loads(os.getenv("GOOGLE_SHEETS_JSON"))

CREDS = Credentials.from_service_account_info(
    GS_JSON, scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
GC = gspread.authorize(CREDS)

# === Hojas ===
SHEET_SIGNALS = GC.open_by_key(SPREADSHEET_ID).worksheet("signals")

# Logs
try:
    SHEET_LOG = GC.open_by_key(SPREADSHEET_ID).worksheet("logs")
except gspread.WorksheetNotFound:
    SHEET_LOG = GC.open_by_key(SPREADSHEET_ID).add_worksheet("logs", rows=1000, cols=10)
    SHEET_LOG.update("A1", [["Timestamp", "Action", "Ticker", "Side", "Old", "New", "Note"]])

# Estado del mercado
try:
    SHEET_MARKET = GC.open_by_key(SPREADSHEET_ID).worksheet("market_status")
except gspread.WorksheetNotFound:
    SHEET_MARKET = GC.open_by_key(SPREADSHEET_ID).add_worksheet("market_status", rows=200, cols=5)
    SHEET_MARKET.update("A1:E1", [["FechaISO", "HoraApertura", "HoraCierre", "TiempoActivo", "Estado"]])

# =========================
# 🕒 Funciones auxiliares
# =========================
def now_et() -> dt.datetime:
    return dt.datetime.now(TZ)

def map_ticker_yf(ticker):
    t = ticker.upper()
    if t == "ES": return "^GSPC"
    if t == "MNQ": return "^NDX"
    if t == "MYM": return "^DJI"
    if t == "M2K": return "^RUT"
    if t == "BTCUSD": return "BTC-USD"
    if t == "ETHUSD": return "ETH-USD"
    return t

def log_action(action, ticker, side, old, new, note=""):
    SHEET_LOG.append_row([
        now_et().isoformat(), action, ticker, side, old, new, note
    ])

# =========================
# 🏛️ Registro del mercado
# =========================
def update_market_status():
    print("⏰ Revisando estado del mercado...")
    current_time = now_et()
    weekday = current_time.weekday()  # 0 = lunes, 6 = domingo

    # Horario del mercado (NY)
    open_hour = 9
    close_hour = 16
    estado = "Cerrado"

    if weekday < 5 and open_hour <= current_time.hour < close_hour:
        estado = "Abierto"

    vals = SHEET_MARKET.get_all_records()
    today_iso = current_time.date().isoformat()

    if vals and vals[-1]["FechaISO"] == today_iso:
        last_row = len(vals) + 1
        if estado == "Abierto":
            SHEET_MARKET.update_cell(last_row, 5, estado)
        else:
            hora_cierre = current_time.strftime("%H:%M:%S")
            hora_apertura = vals[-1].get("HoraApertura", "")
            tiempo_activo = ""
            if hora_apertura:
                try:
                    h1 = dt.datetime.strptime(hora_apertura, "%H:%M:%S")
                    h2 = dt.datetime.strptime(hora_cierre, "%H:%M:%S")
                    diff = h2 - h1
                    tiempo_activo = str(diff)
                except:
                    tiempo_activo = ""
            SHEET_MARKET.update(f"B{last_row}:E{last_row}", [[hora_apertura, hora_cierre, tiempo_activo, estado]])
    else:
        hora_apertura = current_time.strftime("%H:%M:%S") if estado == "Abierto" else ""
        SHEET_MARKET.append_row([
            today_iso,
            hora_apertura,
            "" if estado == "Abierto" else current_time.strftime("%H:%M:%S"),
            "",
            estado
        ])
    print(f"📅 Estado del mercado ({today_iso}): {estado}")

# =========================
# 📈 Lógica de actualización
# =========================
def update_confirmations_and_results():
    print("🔁 Iniciando actualización de confirmaciones y resultados...")
    rows = SHEET_SIGNALS.get_all_records()
    if not rows:
        print("⚠️ No hay señales registradas.")
        return

    df = pd.DataFrame(rows)
    if "Estado" not in df.columns:
        print("⚠️ No se encontró columna 'Estado'.")
        return

    for i, row in enumerate(rows, start=2):
        try:
            estado = row.get("Estado", "")
            ticker = row.get("Ticker", "")
            side = row.get("Side", "Buy").lower()
            scheduled = row.get("ScheduledConfirm", "")
            sl = float(row.get("SL") or 0)
            tp = float(row.get("TP") or 0)

            # Confirmaciones (Pre → Confirmado / Cancelado)
            if estado == "Pre" and scheduled:
                sc_dt = dt.datetime.fromisoformat(scheduled).astimezone(TZ)
                if sc_dt <= now_et():
                    y_ticker = map_ticker_yf(ticker)
                    df_now = yf.download(y_ticker, period="1d", interval="1m", progress=False)
                    if df_now.empty:
                        continue
                    price_now = df_now["Close"].iloc[-1]
                    estado2 = "Confirmado" if price_now else "Cancelado"
                    SHEET_SIGNALS.update_cell(i, df.columns.get_loc("Estado")+1, estado2)
                    log_action("Confirmación", ticker, side, estado, estado2)

            # Resultados (Win / Loss)
            if estado in ["Pre", "Confirmado"] and row.get("Resultado", "-") in ["-", ""]:
                y_ticker = map_ticker_yf(ticker)
                df_now = yf.download(y_ticker, period="1d", interval="1m", progress=False)
                if df_now.empty:
                    continue
                last_price = float(df_now["Close"].iloc[-1])
                resultado = None

                if side == "buy":
                    if last_price <= sl:
                        resultado = "Loss"
                    elif last_price >= tp:
                        resultado = "Win"
                else:
                    if last_price >= sl:
                        resultado = "Loss"
                    elif last_price <= tp:
                        resultado = "Win"

                if resultado:
                    SHEET_SIGNALS.update_cell(i, df.columns.get_loc("Resultado")+1, resultado)
                    log_action("Resultado", ticker, side, estado, resultado)
        except Exception as e:
            log_action("Error", row.get("Ticker", ""), row.get("Side", ""), "", "", str(e))

    print("✅ Actualización completada correctamente.")

# =========================
# 🧹 Limpieza automática
# =========================
def cleanup_old_logs(days=7):
    print("🧹 Limpiando logs antiguos...")
    vals = SHEET_LOG.get_all_records()
    if not vals:
        return
    cutoff = now_et() - dt.timedelta(days=days)
    new_vals = [v for v in vals if dt.datetime.fromisoformat(v["Timestamp"]) >= cutoff]
    SHEET_LOG.clear()
    SHEET_LOG.update("A1", [["Timestamp", "Action", "Ticker", "Side", "Old", "New", "Note"]])
    for v in new_vals:
        SHEET_LOG.append_row([
            v["Timestamp"], v["Action"], v["Ticker"], v["Side"], v["Old"], v["New"], v["Note"]
        ])
    print(f"🧾 {len(vals)-len(new_vals)} registros antiguos eliminados.")

# =========================
# ▶️ MAIN
# =========================
if __name__ == "__main__":
    update_market_status()                  # registrar apertura/cierre
    update_confirmations_and_results()      # confirmar operaciones
    cleanup_old_logs(7)                     # limpiar logs semanales
