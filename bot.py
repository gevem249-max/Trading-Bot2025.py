# ==================================================
# 🔁 BLOQUE FINAL — MONITOREO, ANÁLISIS, SIMULACIÓN Y REGISTRO COMPLETO
# ==================================================

def safe_to_datetime(df, col):
    if col in df.columns:
        try:
            df[col] = pd.to_datetime(df[col], errors="coerce")
        except Exception as e:
            log_debug("safe_to_datetime", f"Error convirtiendo {col}: {e}")
    return df

def recalibrate_global():
    try:
        log_debug("recalibrate_global", "Inicio de recalibración global")
        vals = WS_SIGNALS.get_all_records()
        if not vals:
            return
        df = pd.DataFrame(vals)
        df = safe_to_datetime(df, "FechaISO")
        if "ProbFinal" in df.columns:
            df["ProbFinal"] = pd.to_numeric(df["ProbFinal"], errors="coerce").fillna(0)
        cutoff = now_et() - dt.timedelta(days=7)
        df = df[df["FechaISO"] >= cutoff]
        def clasificar_prob(p):
            if p >= 90: return "Alta"
            elif p >= 70: return "Media"
            else: return "Baja"
        df["ProbClasificación"] = df["ProbFinal"].apply(clasificar_prob)
        WS_SIGNALS.clear()
        WS_SIGNALS.update("A1", [list(df.columns)] + df.fillna("").astype(str).values.tolist())
        log_debug("recalibrate_global", f"Recalibradas {len(df)} filas")
    except Exception as e:
        log_debug("recalibrate_global_error", str(e))

def ensure_all_sheets_exist():
    required = {
        "signals": HEADERS_SIGNALS,
        "summary": ["Fecha","Total","Pre","Confirmadas","Canceladas","Dormidas","Activos",
                    "Promedio_ProbFinal","Máx_ProbFinal","Mín_ProbFinal","Mercados","Notas"],
        "state": ["date","dkng_open_sent","dkng_close_sent","es_open_sent","es_close_sent","last_purge_ts"],
        "market_status": ["FechaISO","Ticker","Hora","TipoMercado","Estado","Sesión","ProbFinal","Tiempo","Nota"],
        "debug": ["ts","ctx","msg"]
    }
    for title, headers in required.items():
        try:
            try:
                SS.worksheet(title)
            except gspread.WorksheetNotFound:
                ws = SS.add_worksheet(title=title, rows=1000, cols=len(headers))
                ws.update("A1", [headers])
                log_debug("ensure_sheet", f"Creada hoja: {title}")
        except Exception as e:
            log_debug("ensure_sheet_error", f"{title}: {e}")

def simulate_result(ticker: str, side: str, df: pd.DataFrame) -> tuple[str, str]:
    try:
        if df is None or df.empty or "Close" not in df.columns or len(df) < 3:
            return ("N/A", "Sin datos")
        prev_price = df["Close"].iloc[-2]
        current_price = df["Close"].iloc[-1]
        direction = "↑" if current_price > prev_price else "↓" if current_price < prev_price else "→"
        resultado = (
            "✅ A favor (simulada)" if (side.lower() == "buy" and direction == "↑") or
                                     (side.lower() == "sell" and direction == "↓")
            else "❌ En contra (simulada)" if direction != "→"
            else "🕓 Sin cambio"
        )
        return (direction, resultado)
    except Exception as e:
        return ("N/A", f"Error simulación: {e}")

def notify_open_close():
    st = read_state_today()
    t = now_et().strftime("%Y-%m-%d %H:%M:%S")
    m_dk, _ = market_status("DKNG")
    if m_dk == "open" and not st.get("dkng_open_sent"):
        send_mail_many("🟢 Apertura DKNG", f"DKNG abierto {t} ET", ALERT_DKNG)
        upsert_state({"dkng_open_sent": "1"})
    if m_dk == "closed" and not st.get("dkng_close_sent"):
        send_mail_many("🔴 Cierre DKNG", f"DKNG cerrado {t} ET", ALERT_DKNG)
        upsert_state({"dkng_close_sent": "1"})
        send_daily_summary()
    m_es, _ = market_status("ES")
    prev_state = getattr(notify_open_close, "_prev_es_state", None)
    if m_es == "open":
        if prev_state != "open":
            log_debug("market_status", "ES reabierto — análisis nocturno (Globex)")
        if not st.get("es_open_sent"):
            send_mail_many("🟢 Apertura ES", f"ES abierto {t} ET", ALERT_ES)
            upsert_state({"es_open_sent": "1"})
    elif m_es == "closed":
        if prev_state != "closed":
            log_debug("market_status", "ES en pausa — fuera de sesión (Globex)")
        if not st.get("es_close_sent"):
            send_mail_many("🔴 Cierre ES", f"ES cerrado {t} ET", ALERT_ES)
            upsert_state({"es_close_sent": "1"})
    notify_open_close._prev_es_state = m_es

def log_market_state():
    try:
        ws = ensure_ws("market_status", ["FechaISO","Ticker","Hora","TipoMercado",
                                         "Estado","Sesión","ProbFinal","Tiempo","Nota"])
        t = now_et()
        fecha = t.strftime("%Y-%m-%d")
        hora = t.strftime("%H:%M:%S")
        vals = WS_SIGNALS.get_all_records()
        df = pd.DataFrame(vals) if vals else pd.DataFrame()
        prob_final = "-"
        tendencia = "Sin datos"
        if not df.empty and "ProbFinal" in df.columns:
            df_today = df[df["FechaISO"] == fecha]
            prob_final = round(df_today["ProbFinal"].astype(float).mean(), 2) if not df_today.empty else "-"
            alcistas = (df_today["Side"].str.lower() == "buy").sum()
            bajistas = (df_today["Side"].str.lower() == "sell").sum()
            if alcistas > bajistas: tendencia = "📈 Alcista"
            elif bajistas > alcistas: tendencia = "📉 Bajista"
            else: tendencia = "➖ Neutral"
        for tk in WATCHLIST:
            estado, tipo = market_status(tk)
            sesion = "Globex" if tk.upper() == "ES" else "NYSE"
            nota = "Analizando" if estado == "open" else "Fuera de horario"
            ws.append_row([fecha, tk.upper(), hora, tipo, estado.capitalize(),
                           sesion, prob_final, f"{SLEEP_SECONDS}s", tendencia + " | " + nota])
            log_debug("market_state", f"{tk} → {estado} ({sesion})")
    except Exception as e:
        log_debug("market_state_error", str(e))

def process_ticker(ticker: str, side: str = "buy", entry: float|None = None):
    try:
        status, market_kind = market_status(ticker)
        t = now_et()
        pm = prob_multi_frame(ticker, side)
        p1,p5,p15,p1h = (pm["per_frame"]["1m"], pm["per_frame"]["5m"], pm["per_frame"]["15m"], pm["per_frame"]["1h"])
        pf = pm["final"]
        df = fetch_yf(ticker, "1m", "1d")
        direction, result = simulate_result(ticker, side, df)
        entry = float(df["Close"].iloc[-1]) if entry is None and not df.empty else entry or 0.0
        clasif = "≥80" if pf >= PRE_THRESHOLD else "<80"
        estado = "Pre" if pf >= PRE_THRESHOLD else "Observada"
        tipo = "Real" if pf >= PRE_THRESHOLD else "Simulada"
        sched = (t + dt.timedelta(minutes=CONFIRM_WAIT_MIN)).isoformat() if pf >= PRE_THRESHOLD else ""
        recipients = ALERT_DKNG if ticker.upper()=="DKNG" else ALERT_ES
        sl, tp = compute_sl_tp(entry, side, 0.0)
        row = {
            "FechaISO": t.strftime("%Y-%m-%d"),
            "HoraLocal": t.strftime("%H:%M"),
            "HoraRegistro": t.strftime("%H:%M:%S"),
            "Ticker": ticker.upper(),
            "Side": side.title(),
            "Entrada": entry,
            "Prob_1m": p1, "Prob_5m": p5, "Prob_15m": p15, "Prob_1h": p1h,
            "ProbFinal": pf, "ProbClasificación": clasif,
            "Estado": estado, "Tipo": tipo,
            "Resultado": result,
            "Nota": f"{status} {direction}",
            "Mercado": market_kind,
            "pattern": "none", "pat_score": 0,
            "macd_val": 0.0, "sr_score": 0, "atr": 0.0,
            "SL": sl, "TP": tp, "Recipients": recipients,
            "ScheduledConfirm": sched
        }
        append_signal_row(row)
        if pf >= PRE_THRESHOLD:
            subject = f"📊 Pre-señal {ticker} {side} {entry} – {pf}%"
            body = (f"{ticker} {side} @ {entry}\n"
                    f"ProbFinal {pf}% (1m {p1} / 5m {p5} / 15m {p15} / 1h {p1h})\n"
                    f"SL {sl} | TP {tp}\nResultado simulado: {result}")
            send_mail_many(subject, body, recipients)
    except Exception as e:
        log_debug("process_ticker", f"{ticker}: {e}")

def main():
    log_debug("main", "run start")
    ensure_all_sheets_exist()
    notify_open_close()
    purge_old_debug(days=7)
    log_market_state()
    current_hour = now_et().hour
    CYCLES_MORNING = 16
    CYCLES_EVENING = 8
    SLEEP_SECONDS_MORNING = 900
    SLEEP_SECONDS_EVENING = 3600
    cycles = CYCLES_MORNING if current_hour < 13 else CYCLES_EVENING
    sleep_time = SLEEP_SECONDS_MORNING if current_hour < 13 else SLEEP_SECONDS_EVENING
    for i in range(cycles):
        start_time = time.time()
        for tk in WATCHLIST:
            process_ticker(tk, "buy", None)
        check_pending_confirmations()
        recalibrate_global()
        log_cycle_time(i + 1, start_time)
        if i < cycles - 1:
            time.sleep(sleep_time)
    weekly_log_summary()
    log_debug("main", "run end")
