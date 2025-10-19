# ==========================================================
# ⚙️ CONFIGURACIÓN BASE — v4.5 (Google Sheets + Auto-Fix Key)
# ==========================================================
import os, pytz, gspread, json, pandas as pd
from google.oauth2.service_account import Credentials
from datetime import datetime as dt, timedelta

# =========================
# 🕒 ZONA HORARIA Y CICLOS
# =========================
TZ_ET = pytz.timezone("US/Eastern")
SLEEP_SECONDS = 300
CYCLES = 12
WATCHLIST = ["ES", "DKNG"]

# =========================
# 🔐 CONEXIÓN GOOGLE SHEETS
# =========================
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")
SPREADSHEET_ID    = os.getenv("SPREADSHEET_ID")

if not GOOGLE_CREDS_JSON or not SPREADSHEET_ID:
    raise ValueError("❌ Falta credencial o ID de hoja")

# ✅ Scopes correctos para Sheets + Drive
scopes = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

# ✅ Carga segura del JSON (sin eval)
try:
    data = json.loads(GOOGLE_CREDS_JSON)
except json.JSONDecodeError as e:
    raise ValueError(f"❌ Error al decodificar GOOGLE_CREDS_JSON: {e}")

# ✅ Auto-fix del private_key (corrige \\n rotos en GitHub Secrets)
if "\\n" in data.get("private_key", ""):
    data["private_key"] = data["private_key"].replace("\\n", "\n")

# ✅ Autenticación con Google
try:
    creds = Credentials.from_service_account_info(data, scopes=scopes)
    gc    = gspread.authorize(creds)
    SS    = gc.open_by_key(SPREADSHEET_ID)
    print("✅ Google Sheets conectado correctamente.")
except Exception as e:
    raise RuntimeError(f"❌ Error al conectar con Google Sheets: {e}")

# ----------------------------------------------------------
# 🧾 Crear o garantizar hojas existentes
# ----------------------------------------------------------
def ensure_ws(title, headers):
    """Crea la hoja si no existe y garantiza los encabezados."""
    try:
        ws = SS.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = SS.add_worksheet(title=title, rows=1000, cols=len(headers))
        ws.update("A1", [headers])
        print(f"🆕 Hoja creada: {title}")
        return ws
    vals = ws.get_all_values()
    if not vals:
        ws.update("A1", [headers])
        print(f"📄 Hoja inicializada: {title}")
    return ws

# === Hojas principales ===
WS_SIGNALS = ensure_ws("signals", [
    "FechaISO","HoraLocal","HoraRegistro","Ticker","Side","Entrada",
    "Prob_1m","Prob_5m","Prob_15m","Prob_1h","ProbFinal","ProbClasificación",
    "Estado","Tipo","Resultado","Nota","Mercado","pattern","pat_score",
    "macd_val","sr_score","atr","SL","TP","Recipients","ScheduledConfirm"
])

WS_DEBUG = ensure_ws("debug", ["Fecha","Hora","Mensaje"])
WS_STATE = ensure_ws("state", ["clave","valor","timestamp"])
WS_PERFORMANCE = ensure_ws("performance", [
    "FechaISO","HoraRegistro","Ticker","Side","Entrada",
    "ProbFinal","Resultado","PnL","ExitISO","ExitHora","Notas"
])

# ----------------------------------------------------------
# 📧 CORREOS / ALERTAS
# ----------------------------------------------------------
ALERT_DEFAULT = os.getenv("ALERT_DEFAULT", "youremail@gmail.com")
ALERT_ES  = os.getenv("ALERT_ES",  ALERT_DEFAULT)
ALERT_DKNG= os.getenv("ALERT_DKNG",ALERT_DEFAULT)

def send_mail_many(subject, body, recipients):
    """Simula envío de correo (para pruebas en GitHub Actions)."""
    print(f"\n📧 [{subject}] → {recipients}\n{body}\n")

# ----------------------------------------------------------
# 🧩 UTILIDADES GENERALES
# ----------------------------------------------------------
def now_et(): 
    return dt.now(TZ_ET)

def log_debug(tag, msg):
    """Registra mensajes de debug en la hoja correspondiente."""
    try:
        now = now_et()
        WS_DEBUG.append_row([
            now.strftime("%Y-%m-%d"),
            now.strftime("%H:%M:%S"),
            f"{tag}: {msg}"
        ])
    except Exception as e:
        print("⚠️ Log failed:", e)

def purge_old_debug(days=7):
    """Limpia registros antiguos en la hoja debug."""
    try:
        df = pd.DataFrame(WS_DEBUG.get_all_records())
        if df.empty: 
            return
        df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce")
        df = df[df["Fecha"] >= now_et() - timedelta(days=days)]
        WS_DEBUG.clear()
        WS_DEBUG.update("A1", [["Fecha","Hora","Mensaje"]])
        for _, r in df.iterrows():
            WS_DEBUG.append_row(r.tolist())
    except Exception as e:
        print("⚠️ purge_old_debug:", e)

def read_state_today():
    """Lee el estado global del día."""
    vals = WS_STATE.get_all_records()
    return {v["clave"]: v["valor"] for v in vals if v.get("clave")}

def upsert_state(kv):
    """Actualiza o inserta valores en la hoja de estado."""
    vals = WS_STATE.get_all_records()
    df = pd.DataFrame(vals)
    for k, v in kv.items():
        if not df.empty and k in df["clave"].values:
            row = df.index[df["clave"] == k][0] + 2
            WS_STATE.update_cell(row, 2, v)
            WS_STATE.update_cell(row, 3, now_et().strftime("%Y-%m-%d %H:%M:%S"))
        else:
            WS_STATE.append_row([k, v, now_et().strftime("%Y-%m-%d %H:%M:%S")])

# ----------------------------------------------------------
# 📈 ESTADO DE MERCADO
# ----------------------------------------------------------
def market_status(ticker):
    """Determina si el mercado está abierto o cerrado."""
    now = now_et()
    hour = now.hour + now.minute/60
    if ticker.upper() == "ES":
        return ("open","Globex") if (hour >= 18 or hour <= 17) else ("closed","Globex")
    else:
        return ("open","NYSE") if 9.5 <= hour <= 16 else ("closed","NYSE")
