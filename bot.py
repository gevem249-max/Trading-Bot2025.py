# ==================================================
# 🔁 BLOQUE FINAL — MONITOREO, RESÚMENES Y ESTADÍSTICAS OPTIMIZADO
# ==================================================
# (Agregar al final del archivo sin borrar lo anterior)

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
        prob_series = pd.to_numeric(df_today["ProbFinal"], errors="coerce").dropna()
        prom = round(prob_series.mean(), 2) if not prob_series.empty else "-"
        pmax = round(prob_series.max(), 2) if not prob_series.empty else "-"
        pmin = round(prob_series.min(), 2) if not prob_series.empty else "-"

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
        prom = round(pd.to_numeric(df7["ProbFinal"], errors="coerce").dropna().mean(), 2)
        log_debug("weekly_summary",
                  f"Últimos 7 días → Total {total}, Pre {pre}, Confirmadas {conf}, Canceladas {canc}, Promedio {prom}%")
    except Exception as e:
        log_debug("weekly_summary_error", str(e))


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
        send_daily_summary()

    # ES (Globex)
    m_es, _ = market_status("ES")
    prev_state = getattr(notify_open_close, "_prev_es_state", None)

    if m_es == "open":
        if prev_state != "open":
            log_debug("market_status", "ES reabierto — comienza análisis nocturno (Globex)")
            vals = WS_SIGNALS.get_all_records()
            df = pd.DataFrame(vals) if vals else pd.DataFrame()
            prob_final = "-"
            if not df.empty and "ProbFinal" in df.columns:
                s = pd.to_numeric(df.loc[df["FechaISO"] == now_et().strftime("%Y-%m-%d"), "ProbFinal"], errors="coerce").dropna()
                if not s.empty:
                    prob_final = round(s.mean(), 2)
            send_mail_many(
                "🌙 Apertura Globex (ES)",
                f"Globex abierto {t} ET\nPromedio ProbFinal actual: {prob_final}%",
                ALERT_ES
            )
        if not st.get("es_open_sent"):
            send_mail_many("🟢 Apertura ES", f"ES abierto {t} ET", ALERT_ES)
            upsert_state({"es_open_sent": "1"})

    elif m_es == "closed":
        if prev_state != "closed":
            log_debug("market_status", "ES en pausa — fuera de sesión (Globex)")
        if not st.get("es_close_sent"):
            today = now_et().strftime("%Y-%m-%d")
            vals = WS_SIGNALS.get_all_records()
            df = pd.DataFrame(vals) if vals else pd.DataFrame()
            if not df.empty:
                try:
                    dfe = df[(df["FechaISO"] == today) & (df["Ticker"].str.upper() == "ES")]
                    total = len(dfe)
                    pre = (dfe["Estado"] == "Pre").sum()
                    conf = (dfe["Estado"] == "Confirmada").sum()
                    canc = (dfe["Estado"] == "Cancelada").sum()
                    s = pd.to_numeric(dfe["ProbFinal"], errors="coerce").dropna()
                    prom = round(s.mean(), 2) if not s.empty else "-"
                    pmax = round(s.max(), 2) if not s.empty else "-"
                    pmin = round(s.min(), 2) if not s.empty else "-"
                except Exception:
                    total = pre = conf = canc = 0
                    prom = pmax = pmin = "-"
            else:
                total = pre = conf = canc = 0
                prom = pmax = pmin = "-"

            send_mail_many(
                "🌙 Cierre Globex (ES) — Resumen",
                (
                    f"ES cerrado {t} ET\n"
                    f"Señales ES hoy: {total}\n"
                    f"Pre: {pre} | Confirmadas: {conf} | Canceladas: {canc}\n"
                    f"ProbFinal (prom/máx/mín): {prom}% / {pmax}% / {pmin}%"
                ),
                ALERT_ES
            )
            upsert_state({"es_close_sent": "1"})

    notify_open_close._prev_es_state = m_es


# =========================
# 📊 ESTADO DE MERCADO DETALLADO
# =========================
def ensure_ws_market_status():
    try:
        ws = SS.worksheet("market_status")
    except gspread.WorksheetNotFound:
        ws = SS.add_worksheet(title="market_status", rows=1000, cols=9)
        ws.update("A1", [["FechaISO","Ticker","Hora","TipoMercado","Estado","Sesión","ProbFinal","Tiempo","Nota"]])
        return ws
    vals = ws.get_all_values()
    if not vals:
        ws.update("A1", [["FechaISO","Ticker","Hora","TipoMercado","Estado","Sesión","ProbFinal","Tiempo","Nota"]])
    return ws


def log_market_state():
    """Registra el estado actual de cada activo"""
    try:
        ws = ensure_ws_market_status()
        t = now_et()
        fecha, hora = t.strftime("%Y-%m-%d"), t.strftime("%H:%M:%S")
        vals = WS_SIGNALS.get_all_records()
        df = pd.DataFrame(vals) if vals else pd.DataFrame()
        prob_final = "-"
        if not df.empty and "ProbFinal" in df.columns:
            s = pd.to_numeric(df.loc[df["FechaISO"] == fecha, "ProbFinal"], errors="coerce").dropna()
            if not s.empty:
                prob_final = round(s.mean(), 2)
        for tk in WATCHLIST:
            estado, tipo = market_status(tk)
            sesion = "Globex" if tk.upper() == "ES" else "NYSE"
            nota = "Analizando" if estado == "open" else "Fuera de horario"
            ws.append_row([fecha, tk.upper(), hora, tipo, estado.capitalize(), sesion, prob_final, f"{SLEEP_SECONDS}s", nota])
            log_debug("market_state", f"{tk} → {estado} ({sesion})")
    except Exception as e:
        log_debug("market_state_error", str(e))


# =========================
# 🚀 MAIN EXTENDIDO CON SUBCICLOS DE 5 MIN
# =========================
def main():
    log_debug("main", "run start")
    notify_open_close()
    purge_old_debug(days=7)
    log_market_state()

    # 🔹 Ciclo principal (CYCLES) con 3 subciclos de 5 min (total ~15 min)
    for main_cycle in range(CYCLES):
        log_debug("cycle_main", f"Inicio ciclo principal {main_cycle + 1}")
        main_start = time.time()

        for sub_cycle in range(3):
            sub_start = time.time()
            log_debug("sub_cycle", f"Subciclo {sub_cycle + 1} del ciclo {main_cycle + 1}")

            # 👉 process_ticker registra SIEMPRE (≥80 y <80)
            for tk in WATCHLIST:
                process_ticker(tk, "buy", None)

            check_pending_confirmations()
            log_cycle_time(f"{main_cycle + 1}.{sub_cycle + 1}", sub_start)

            if sub_cycle < 2:
                time.sleep(300)  # 5 minutos

        log_cycle_time(main_cycle + 1, main_start)
        log_debug("cycle_main", f"Fin ciclo principal {main_cycle + 1}")

    weekly_log_summary()
    send_daily_summary()
    log_debug("main", "run end")
