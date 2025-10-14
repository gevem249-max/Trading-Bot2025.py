# ==================================================
# ⚙️ CONFIGURACIÓN BASE — v4.3 SELF-HEALING (Auto-fix Secrets & Sheets)
# ==================================================
import os, pytz, gspread, pandas as pd
from google.oauth2.service_account import Credentials
from datetime import datetime as dt, timedelta

# =========================
# 🕒 ZONA HORARIA Y CICLOS
# =========================
TZ_ET = pytz.timezone("US/Eastern")
SLEEP_SECONDS = 300          # cada 5 min
CYCLES = 12                  # 1 hora por ejecución
WATCHLIST = ["ES", "DKNG"]

# =========================
# 🔐 CONEXIÓN GOOGLE SHEETS (con fallback)
# =========================
# Soporta ambos nombres de secret: GOOGLE_CREDS o GOOGLE_CREDS_JSON
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS") or os.getenv("GOOGLE_CREDS_JSON")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")

if not GOOGLE_CREDS_JSON or not SPREADSHEET_ID:
    raise ValueError("❌ Falta credencial o ID de hoja")

try:
    creds = Credentials.from_service_account_info(eval(GOOGLE_CREDS_JSON))
    gc = gspread.authorize(creds)
    SS = gc.open_by_key(SPREADSHEET_ID)
    print(f"✅ Conectado a Google Sheets: {SS.title}")
except Exception as e:
    raise RuntimeError(f"❌ Error al conectar con Google Sheets: {e}")

# =========================
# 🧾 ASEGURAR HOJAS Y ENCABEZADOS
# =========================
def ensure_ws(title, headers):
    """Crea hoja si no existe y valida encabezados"""
    try:
        ws = SS.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = SS.add_worksheet(title=title, rows=1000, cols=len(headers))
        ws.update("A1", [headers])
        print(f"🆕 Hoja creada: {title}")
    vals = ws.get_all_values()
    if not vals:
        ws.update("A1", [headers])
    return ws

WS_SIGNALS = ensure_ws("signals", [
    "FechaISO","HoraLocal","HoraRegistro","Ticker","Side","Entrada",
    "Prob_1m","Prob_5m","Prob_15m","Prob_1h","ProbFinal","ProbClasificación",
    "Estado","Tipo","Resultado","Nota","Mercado","pattern","pat_score",
    "macd_val","sr_score","atr","SL","TP","Recipients","ScheduledConfirm"
])

WS_DEBUG = ensure_ws("debug", ["Fecha","Hora","Mensaje"])
WS_STATE = ensure_ws("state", ["clave","valor","timestamp"])

# =========================
# 📧 CORREO / ALERTAS
# =========================
ALERT_DEFAULT = os.getenv("ALERT_DEFAULT", "youremail@gmail.com")
ALERT_ES = os.getenv("ALERT_ES", ALERT_DEFAULT)
ALERT_DKNG = os.getenv("ALERT_DKNG", ALERT_DEFAULT)

def send_mail_many(subject, body, recipients):
    """Envía correo simulado (para despliegue local o GitHub Logs)"""
    print(f"\n📧 [{subject}] → {recipients}\n{body}\n")

# =========================
# 🧩 UTILIDADES GENERALES
# =========================
def now_et(): 
    return dt.now(TZ_ET)

def log_debug(tag, msg):
    """Guarda logs en hoja debug"""
    try:
        now = now_et()
        WS_DEBUG.append_row([now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"), f"{tag}: {msg}"])
    except Exception as e:
        print("⚠️ Log failed:", e)

def purge_old_debug(days=7):
    """Elimina logs viejos para mantener liviana la hoja"""
    try:
        df = pd.DataFrame(WS_DEBUG.get_all_records())
        if df.empty: return
        df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce")
        df = df[df["Fecha"] >= now_et() - timedelta(days=days)]
        WS_DEBUG.clear()
        WS_DEBUG.update("A1", [["Fecha","Hora","Mensaje"]])
        for _, r in df.iterrows():
            WS_DEBUG.append_row(r.tolist())
    except Exception as e:
        print("⚠️ purge_old_debug:", e)

def read_state_today():
    """Lee variables guardadas (ej. cierres, aperturas)"""
    vals = WS_STATE.get_all_records()
    return {v["clave"]: v["valor"] for v in vals if v.get("clave")}

def upsert_state(kv):
    """Actualiza o inserta variables en hoja state"""
    vals = WS_STATE.get_all_records()
    df = pd.DataFrame(vals)
    for k, v in kv.items():
        if not df.empty and k in df["clave"].values:
            row = df.index[df["clave"] == k][0] + 2
            WS_STATE.update_cell(row, 2, v)
            WS_STATE.update_cell(row, 3, now_et().strftime("%Y-%m-%d %H:%M:%S"))
        else:
            WS_STATE.append_row([k, v, now_et().strftime("%Y-%m-%d %H:%M:%S")])

# =========================
# 📈 ESTADO DE MERCADO
# =========================
def market_status(ticker):
    """Determina si un mercado está abierto o cerrado"""
    now = now_et()
    hour = now.hour + now.minute / 60

    # 🌙 Globex (ES)
    if ticker.upper() == "ES":
        # Globex abre a las 18:00 ET y cierra a las 17:00 del siguiente día (domingo a viernes)
        if (hour >= 18) or (hour < 17):
            return ("open", "Globex")
        else:
            return ("closed", "Globex")
            # === Hoja PERFORMANCE (resultados de operaciones) ===
WS_PERFORMANCE = ensure_ws("performance", [
    "FechaISO",          # fecha de la señal
    "HoraRegistro",      # hora de la señal
    "Ticker",
    "Side",
    "Entrada",           # "AUTO" u otra
    "ProbFinal",
    "Resultado",         # Open | Win | Loss | BE | Cancel
    "PnL",               # numérico, opcional
    "ExitISO",           # fecha de cierre
    "ExitHora",          # hora de cierre
    "Notas"              # comentario libre
])

    # 🏛️ NYSE (DKNG y similares)
    else:
        return ("open", "NYSE") if 9.5 <= hour <= 16 else ("closed", "NYSE")
