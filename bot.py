# ==================================================
# 🔁 BLOQUE FINAL — MONITOREO, RESÚMENES Y ESTADÍSTICAS
# ==================================================
# (Agregar al final del archivo sin borrar código anterior)

# =========================
# 🕓 LOG DE TIEMPO POR CICLO
# =========================
def log_cycle_time(cycle_num, start_time):
    """Guarda en debug la duración de cada ciclo"""
    try:
        elapsed = round(time.time() - start_time, 2)
        log_debug("cycle_time", f"Ciclo {cycle_num} finalizado en {elapsed} segundos")
    except Exception as e:
        log_debug("cycle_time_error", str(e))


# =========================
# 📊 RESUMEN DIARIO AUTOMÁTICO (correo + hoja summary)
# =========================
def ensure_ws_summary():
    """Crea hoja summary si no existe"""
    try:
        ws = SS.worksheet("summary")
    except gspread.WorksheetNotFound:
        ws = SS.add_worksheet(title="summary", rows=500, cols=12)
        ws.update(
            "A1",
            [["Fecha", "Total", "Pre", "Confirmadas", "Canceladas", "Dormidas",
              "Activos", "Promedio_ProbFinal", "Máx_ProbFinal", "Mín_ProbFinal",
              "Mercados", "Notas"]]
        )
        return ws
    vals = ws.get_all_values()
    if not vals:
        ws.update(
            "A1",
            [["Fecha", "Total", "Pre", "Confirmadas", "Canceladas", "Dormidas",
              "Activos", "Promedio_ProbFinal", "Máx_ProbFinal", "Mín_ProbFinal",
              "Mercados", "Notas"]]
        )
    return ws


def send_daily_summary():
    """Analiza señales del día, las guarda en summary y envía correo"""
    try:
        today = now_et().strftime("%Y-%m-%d")
        vals = WS_SIGNALS.get_all_records()
        if not vals:
            log_debug("daily_summary", "sin datos para analizar")
            return

        df = pd.DataFrame(vals)
        df_today = df[df["FechaISO"] == today]
        if df_today.empty:
            log_debug("daily_summary", f"sin registros para {today}")
            return

        total = len(df_today)
        pre = (df_today["Estado"] == "Pre").sum()
        conf = (df_today["Estado"] == "Confirmada").sum()
        canc = (df_today["Estado"] == "Cancelada").sum()
        dorm = (df_today["Estado"] == "Dormido").sum()
        activos = ", ".join(sorted(df_today["Ticker"].unique()))
        mercados = ", ".join(sorted(df_today["Mercado"].unique()))

        # estadísticas de probabilidad
        prob_series = df_today["ProbFinal"].astype(float)
        prom = round(prob_series.mean(), 2)
        pmax = round(prob_series.max(), 2)
        pmin = round(prob_series.min(), 2)

        # guardar en hoja summary
        ws_sum = ensure_ws_summary()
        ws_sum.append_row([
            today, total, pre, conf, canc, dorm, activos,
            prom, pmax, pmin, mercados, "OK"
        ])

        # correo resumen
        subject = f"📊 Resumen Diario {today}"
        body = (
            f"Total señales: {total}\n"
            f"Pre: {pre} | Confirmadas: {conf} | Canceladas: {canc} | Dormidas: {dorm}\n"
            f"Activos: {activos}\n"
            f"Promedio ProbFinal: {prom}% | Máx: {pmax}% | Mín: {pmin}%\n"
            f"Mercados: {mercados}"
        )
        send_mail_many(subject, body, ALERT_DEFAULT)
        log_debug("daily_summary", f"Resumen diario generado con {total} registros")
    except Exception as e:
        log_debug("daily_summary_error", str(e))


# =========================
# 🗓️ RESUMEN SEMANAL EN LOGS
# =========================
def weekly_log_summary():
    """Calcula totales de los últimos 7 días y los deja en debug"""
    try:
        vals = WS_SIGNALS.get_all_records()
        if not vals:
            return
        df = pd.DataFrame(vals)
        df["FechaISO"] = pd.to_datetime(df["FechaISO"], errors="coerce")
        cutoff = now_et() - dt.timedelta(days=7)
        df7 = df[df["FechaISO"] >= cutoff]
        if df7.empty:
            return

        total = len(df7)
        pre = (df7["Estado"] == "Pre").sum()
        conf = (df7["Estado"] == "Confirmada").sum()
        canc = (df7["Estado"] == "Cancelada").sum()
        prom = round(df7["ProbFinal"].astype(float).mean(), 2)
        log_debug("weekly_summary",
                  f"Últimos 7 días → Total {total}, Pre {pre}, Confirmadas {conf}, Canceladas {canc}, Promedio {prom}%")
    except Exception as e:
        log_debug("weekly_summary_error", str(e))


# =========================
# 🚀 MAIN EXTENDIDO (mantiene todo lo anterior)
# =========================
def main():
    log_debug("main", "run start")
    notify_open_close()
    purge_old_debug(days=7)

    # 🔹 Correr los ciclos internos con medición de tiempo
    for i in range(CYCLES):
        start_time = time.time()
        for tk in WATCHLIST:
            process_ticker(tk, "buy", None)
        check_pending_confirmations()
        log_cycle_time(i + 1, start_time)
        if i < CYCLES - 1:
            time.sleep(SLEEP_SECONDS)

    # 🔹 Registrar resumen semanal
    weekly_log_summary()

    log_debug("main", "run end")


# =========================
# 📣 EXTENSIÓN DE NOTIFY_OPEN_CLOSE
# =========================
def notify_open_close():
    st = read_state_today()
    t = now_et().strftime("%Y-%m-%d %H:%M:%S")

    # DKNG
    m_dk, _ = market_status("DKNG")
    if m_dk == "open" and not st.get("dkng_open_sent"):
        send_mail_many("🟢 Apertura DKNG", f"DKNG abierto {t} ET", ALERT_DKNG)
        upsert_state({"dkng_open_sent": "1"})
    if m_dk == "closed" and not st.get("dkng_close_sent"):
        send_mail_many("🔴 Cierre DKNG", f"DKNG cerrado {t} ET", ALERT_DKNG)
        upsert_state({"dkng_close_sent": "1"})
        send_daily_summary()  # ✅ resumen diario automático

    # ES (Globex)
    m_es, _ = market_status("ES")
    if m_es == "open" and not st.get("es_open_sent"):
        send_mail_many("🟢 Apertura ES", f"ES abierto {t} ET", ALERT_ES)
        upsert_state({"es_open_sent": "1"})
    if m_es == "closed" and not st.get("es_close_sent"):
        send_mail_many("🔴 Cierre ES", f"ES cerrado {t} ET", ALERT_ES)
        upsert_state({"es_close_sent": "1"})
