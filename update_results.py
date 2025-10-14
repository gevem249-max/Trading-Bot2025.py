# ==========================================================
# 🔄 UPDATE & NOTIFY RESULTS — v4.3 (auto-retry)
# ==========================================================
# ✅ Lee hojas con tolerancia a errores (500 API)
# ✅ Reintenta automáticamente hasta 3 veces
# ✅ Actualiza resultados y notifica estado
# ==========================================================

import time, pandas as pd
from bot_config import *

# ----------------------------------------------------------
# 🔁 Función segura para leer una hoja con reintento
# ----------------------------------------------------------
def safe_get_values(ws, max_retries=3, delay=5):
    for attempt in range(max_retries):
        try:
            vals = ws.get_all_values()
            if vals:
                return vals
        except Exception as e:
            log_debug("safe_get_values", f"Intento {attempt+1} falló: {e}")
            time.sleep(delay)
    raise RuntimeError(f"❌ No se pudo leer la hoja {ws.title} después de {max_retries} intentos")

# ----------------------------------------------------------
# 📊 Obtener último estado del mercado
# ----------------------------------------------------------
def get_last_status(ws):
    vals = safe_get_values(ws)
    if not vals or len(vals) < 2:
        return {}
    last_row = vals[-1]
    headers = vals[0]
    return dict(zip(headers, last_row))

# ----------------------------------------------------------
# 🧾 Actualizar hoja de resultados
# ----------------------------------------------------------
def update_results(ws_perf):
    try:
        df = pd.DataFrame(ws_perf.get_all_records())
        if df.empty:
            log_debug("update_results", "Sin datos en performance.")
            return
        wins = (df["Resultado"] == "Win").sum()
        loss = (df["Resultado"] == "Loss").sum()
        be   = (df["Resultado"] == "BE").sum()
        canc = (df["Resultado"] == "Cancel").sum()
        log_debug("update_results",
                  f"Performance total → Win:{wins} Loss:{loss} BE:{be} Cancel:{canc}")
    except Exception as e:
        log_debug("update_results_error", str(e))

# ----------------------------------------------------------
# 📬 Notificar resultados (correo simulado)
# ----------------------------------------------------------
def notify_summary():
    try:
        df = pd.DataFrame(WS_PERFORMANCE.get_all_records())
        if df.empty:
            send_mail_many("📈 Daily Summary", "Sin operaciones registradas hoy.", [ALERT_DEFAULT])
            return
        today = now_et().strftime("%Y-%m-%d")
        dft = df[df["FechaISO"] == today]
        if dft.empty:
            send_mail_many("📈 Daily Summary", "Sin operaciones del día actual.", [ALERT_DEFAULT])
            return

        total = len(dft)
        wins = (dft["Resultado"] == "Win").sum()
        loss = (dft["Resultado"] == "Loss").sum()
        pnl_series = pd.to_numeric(dft.get("PnL", pd.Series(dtype=float)), errors="coerce").dropna()
        pnl_total = round(pnl_series.sum(), 2) if not pnl_series.empty else 0
        body = f"Operaciones de hoy ({today}):\nTotal:{total} | Win:{wins} | Loss:{loss} | PnL:{pnl_total}"
        send_mail_many("📈 Resumen Diario — Trading Bot 2025", body, [ALERT_DEFAULT])
    except Exception as e:
        log_debug("notify_summary_error", str(e))

# ----------------------------------------------------------
# 🚀 EJECUCIÓN PRINCIPAL
# ----------------------------------------------------------
def main():
    log_debug("update_results", "🔄 Iniciando actualización de mercado y señales...")
    try:
        prev = get_last_status(WS_STATE)
        log_debug("update_results", f"Último estado: {prev}")
        update_results(WS_PERFORMANCE)
        notify_summary()
    except Exception as e:
        log_debug("fatal_update", str(e))

if __name__ == "__main__":
    print("🚀 Ejecutando actualización automática de mercado y señales...")
    main()
    print("✅ Actualización completada correctamente.")
