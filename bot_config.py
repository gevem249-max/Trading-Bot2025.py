# ==========================================================
# ⚙️ CONFIGURACIÓN BASE — v5.0 (Corregido y mejorado)
# ==========================================================
import os
import pytz
import gspread
import json
import pandas as pd
from google.oauth2.service_account import Credentials
from datetime import datetime as dt, timedelta

# =========================
# 🕒 ZONA HORARIA Y CICLOS
# =========================
TZ_ET = pytz.timezone("US/Eastern")
WATCHLIST = ["ES", "DKNG"]

# =========================
# 🔐 CONEXIÓN GOOGLE SHEETS
# =========================
def load_google_credentials():
    """Carga credenciales de Google de forma segura."""
    creds_json = os.getenv("GOOGLE_CREDS_JSON")
    spreadsheet_id = os.getenv("SPREADSHEET_ID")
    
    if not creds_json:
        raise ValueError("❌ Falta variable de entorno: GOOGLE_CREDS_JSON")
    if not spreadsheet_id:
        raise ValueError("❌ Falta variable de entorno: SPREADSHEET_ID")
    
    try:
        # Intentar cargar JSON
        data = json.loads(creds_json)
    except json.JSONDecodeError as e:
        raise ValueError(f"❌ JSON de credenciales mal formado: {e}")
    
    # Auto-fix del private_key (GitHub Secrets puede romper los \n)
    if "private_key" in data and "\\n" in data["private_key"]:
        data["private_key"] = data["private_key"].replace("\\n", "\n")
        print("✅ Private key reparada automáticamente")
    
    return data, spreadsheet_id

# Cargar credenciales
GOOGLE_CREDS_DATA, SPREADSHEET_ID = load_google_credentials()

# Scopes necesarios
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

# Autenticación
try:
    creds = Credentials.from_service_account_info(GOOGLE_CREDS_DATA, scopes=SCOPES)
    gc = gspread.authorize(creds)
    SS = gc.open_by_key(SPREADSHEET_ID)
    print(f"✅ Conectado a Google Sheets: {SS.title}")
except Exception as e:
    raise RuntimeError(f"❌ Error conectando a Google Sheets: {e}")

# =========================
# 🧾 GARANTIZAR HOJAS
# =========================
def ensure_ws(title, headers):
    """Crea o verifica una hoja con sus encabezados."""
    try:
        ws = SS.worksheet(title)
        print(f"✅ Hoja encontrada: {title}")
    except gspread.WorksheetNotFound:
        ws = SS.add_worksheet(title=title, rows=1000, cols=len(headers))
        ws.update("A1", [headers])
        print(f"🆕 Hoja creada: {title}")
        return ws
    
    # Verificar encabezados
    vals = ws.get_all_values()
    if not vals or len(vals[0]) != len(headers):
        ws.update("A1", [headers])
        print(f"📝 Encabezados actualizados: {title}")
    
    return ws

# === HOJAS PRINCIPALES ===
WS_SIGNALS = ensure_ws("signals", [
    "FechaISO", "HoraLocal", "HoraRegistro", "Ticker", "Side", "Entrada",
    "Prob_1m", "Prob_5m", "Prob_15m", "Prob_1h", "ProbFinal", "ProbClasificación",
    "Estado", "Tipo", "Resultado", "Nota", "Mercado", "pattern", "pat_score",
    "macd_val", "sr_score", "atr", "SL", "TP", "Recipients", "ScheduledConfirm"
])

WS_DEBUG = ensure_ws("debug", [
    "Fecha", "Hora", "Mensaje"
])

WS_STATE = ensure_ws("state", [
    "clave", "valor", "timestamp"
])

WS_PERFORMANCE = ensure_ws("performance", [
    "FechaISO", "HoraRegistro", "Ticker", "Side", "Entrada",
    "ProbFinal", "Resultado", "PnL", "ExitISO", "ExitHora", "Notas"
])

# =========================
# 📧 CONFIGURACIÓN DE ALERTAS
# =========================
ALERT_DEFAULT = os.getenv("ALERT_DEFAULT", "")
ALERT_ES = os.getenv("ALERT_ES", ALERT_DEFAULT)
ALERT_DKNG = os.getenv("ALERT_DKNG", ALERT_DEFAULT)

if not ALERT_DEFAULT:
    print("⚠️ Advertencia: No hay email configurado en ALERT_DEFAULT")

def send_mail_many(subject, body, recipients):
    """
    Simula envío de correo para testing en GitHub Actions.
    En producción, integrar con servicio SMTP real.
    """
    timestamp = now_et().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'='*60}")
    print(f"📧 EMAIL SIMULADO [{timestamp}]")
    print(f"{'='*60}")
    print(f"Para: {', '.join(recipients)}")
    print(f"Asunto: {subject}")
    print(f"\n{body}")
    print(f"{'='*60}\n")
    
    # Registrar en debug
    log_debug("email_sent", f"To: {recipients} | Subject: {subject}")

# =========================
# 🧩 UTILIDADES GENERALES
# =========================
def now_et():
    """Retorna datetime actual en zona horaria ET."""
    return dt.now(TZ_ET)

def log_debug(tag, msg):
    """Registra mensajes en la hoja de debug."""
    try:
        now = now_et()
        WS_DEBUG.append_row([
            now.strftime("%Y-%m-%d"),
            now.strftime("%H:%M:%S"),
            f"[{tag}] {msg}"
        ])
    except Exception as e:
        print(f"⚠️ Error guardando log: {e}")

def purge_old_debug(days=7):
    """Limpia registros antiguos de debug."""
    try:
        all_vals = WS_DEBUG.get_all_records()
        if not all_vals:
            return
        
        df = pd.DataFrame(all_vals)
        df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce")
        cutoff = now_et() - timedelta(days=days)
        df_filtered = df[df["Fecha"] >= cutoff]
        
        # Limpiar y reescribir
        WS_DEBUG.clear()
        WS_DEBUG.update("A1", [["Fecha", "Hora", "Mensaje"]])
        
        if not df_filtered.empty:
            rows = df_filtered.values.tolist()
            WS_DEBUG.append_rows(rows)
        
        print(f"✅ Debug limpiado: {len(all_vals) - len(df_filtered)} registros eliminados")
        
    except Exception as e:
        print(f"⚠️ Error limpiando debug: {e}")

def read_state_today():
    """Lee el estado global actual."""
    try:
        vals = WS_STATE.get_all_records()
        return {v["clave"]: v["valor"] for v in vals if v.get("clave")}
    except Exception as e:
        log_debug("read_state_error", str(e))
        return {}

def upsert_state(kv):
    """Actualiza o inserta valores en el estado."""
    try:
        vals = WS_STATE.get_all_records()
        df = pd.DataFrame(vals) if vals else pd.DataFrame(columns=["clave", "valor", "timestamp"])
        
        for k, v in kv.items():
            timestamp = now_et().strftime("%Y-%m-%d %H:%M:%S")
            
            if not df.empty and k in df["clave"].values:
                # Actualizar existente
                row_idx = df.index[df["clave"] == k][0] + 2  # +2 por header y 0-index
                WS_STATE.update_cell(row_idx, 2, str(v))
                WS_STATE.update_cell(row_idx, 3, timestamp)
            else:
                # Insertar nuevo
                WS_STATE.append_row([k, str(v), timestamp])
        
    except Exception as e:
        log_debug("upsert_state_error", str(e))

# =========================
# 📈 ESTADO DE MERCADO
# =========================
def market_status(ticker):
    """
    Determina si el mercado está abierto para el ticker.
    Retorna: (estado, sesión)
    """
    now = now_et()
    hour = now.hour + now.minute / 60
    weekday = now.weekday()  # 0=Lunes, 6=Domingo
    
    ticker_upper = ticker.upper()
    
    # Futuros (ES, NQ, etc.) - Globex 24/5
    if ticker_upper in ["ES", "NQ", "YM", "RTY"]:
        # Cerrado sábados y domingos
        if weekday >= 5:  # Sábado o Domingo
            return ("closed", "Globex")
        
        # Viernes: cierra a las 17:00 ET
        if weekday == 4 and hour >= 17:
            return ("closed", "Globex")
        
        # Domingo: abre a las 18:00 ET
        if weekday == 6 and hour < 18:
            return ("closed", "Globex")
        
        return ("open", "Globex")
    
    # Acciones y ETFs - NYSE
    else:
        # Fin de semana
        if weekday >= 5:
            return ("closed", "NYSE")
        
        # Horario regular: 9:30 - 16:00 ET
        if 9.5 <= hour <= 16:
            return ("open", "NYSE")
        else:
            return ("closed", "NYSE")

# =========================
# 🧪 TEST DE CONEXIÓN
# =========================
def test_connection():
    """Prueba la conexión a Google Sheets."""
    try:
        print(f"\n🔍 Probando conexión...")
        print(f"📊 Spreadsheet: {SS.title}")
        print(f"📝 Hojas disponibles:")
        
        for ws in SS.worksheets():
            print(f"  - {ws.title}")
        
        print(f"✅ Conexión verificada correctamente\n")
        return True
        
    except Exception as e:
        print(f"❌ Error en test de conexión: {e}")
        return False

# =========================
# 🚀 INICIALIZACIÓN
# =========================
if __name__ == "__main__":
    print("\n" + "="*60)
    print("⚙️  CONFIGURACIÓN DEL BOT")
    print("="*60)
    print(f"📍 Zona horaria: {TZ_ET}")
    print(f"📊 Watchlist: {', '.join(WATCHLIST)}")
    print(f"📧 Email default: {ALERT_DEFAULT or '(no configurado)'}")
    test_connection()
    print("="*60 + "\n")
