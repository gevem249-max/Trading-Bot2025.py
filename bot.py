# ==================================================
# 🤖 BLOQUE FINAL — TRADING BOT 2025 (Versión 3.9 Stable Adaptive)
# ==================================================
# ✅ CHECKLIST DE FUNCIONALIDADES
# --------------------------------------------------
# ✅ Registro completo de señales (≥80 y <80)
# ✅ Análisis multiframe con probabilidad final adaptativa
# ✅ Creación automática de todas las hojas en Google Sheets
# ✅ Correos automáticos: apertura/cierre DKNG y ES (Globex/NYSE)
# ✅ Correos de señales “Pre”, confirmación y resúmenes
# ✅ Ciclos principales de 15 min con subciclos cada 5 min
# ✅ Registro de estado de mercado + logs de tiempo
# ✅ Aprendizaje adaptativo de threshold (PRE_THRESHOLD dinámico)
# ✅ Noticias con análisis de sentimiento contextual (técnico + fundamental)
# ✅ Registro de impacto direccional en “news_impact”
# ✅ Ajuste de probabilidad basado en concordancia entre sentimiento e indicadores
# ✅ Reportes diarios/semanales y logs de depuración
# ✅ Ejecución 24/7 (soporte completo NY + Globex)
# ==================================================

from textblob import TextBlob
import random

# ==================================================
# ⚙️ FUNCIONES BASE
# ==================================================
def market_session_for(ticker):
    """Determina si el ticker pertenece a sesión NYSE o Globex."""
    if ticker.upper() == "ES":
        return "Globex"
    return "NYSE"

def ensure_ws(ws_name, headers):
    """Crea hoja si no existe."""
    try:
        ws = SS.worksheet(ws_name)
    except gspread.WorksheetNotFound:
        ws = SS.add_worksheet(title=ws_name, rows=1000, cols=len(headers))
        ws.update("A1", [headers])
        return ws
    vals = ws.get_all_values()
    if not vals:
        ws.update("A1", [headers])
    return ws

# ==================================================
# 📰 NOTICIAS CON ANÁLISIS DE IMPACTO CONTEXTUAL
# ==================================================
def analyze_news_contextual(ticker, prob_final, trend_hint):
    """
    Evalúa noticias considerando el sentimiento y dirección técnica.
    Retorna impacto entre -1 y +1 (ajustado según contexto).
    """
    items = fetch_news_items(ticker)
    if not items:
        return 0.0

    sentiments = []
    for n in items:
        text = f"{n['title']} {n.get('summary','')}"
        polarity = TextBlob(text).sentiment.polarity
        sentiments.append(polarity)
    if not sentiments:
        return 0.0

    avg_sent = sum(sentiments) / len(sentiments)
    direction = "bullish" if prob_final >= 50 else "bearish"

    # Ajuste contextual:
    # Si la noticia coincide con la dirección → refuerzo.
    # Si contradice → reducción.
    if (avg_sent > 0 and direction == "bullish") or (avg_sent < 0 and direction == "bearish"):
        impact = abs(avg_sent) * 1.0  # refuerzo
    else:
        impact = -abs(avg_sent) * 0.6  # contradicción parcial

    ws = ensure_ws("news_impact", ["Fecha", "Ticker", "Impact", "Sentimiento", "Técnico"])
    ws.append_row([
        now_et().strftime("%Y-%m-%d %H:%M:%S"),
        ticker.upper(),
        round(impact, 3),
        round(avg_sent, 3),
        direction
    ])
    log_debug("news_contextual", f"{ticker}: impacto {impact:+.3f} ({direction})")
    return round(impact, 3)

def get_last_impact(ticker):
    """Obtiene el último impacto guardado de noticias."""
    try:
        ws = SS.worksheet("news_impact")
        vals = ws.get_all_records()
        if not vals:
            return 0
        df = pd.DataFrame(vals)
        df = df[df["Ticker"] == ticker.upper()]
        if df.empty:
            return 0
        return float(df.iloc[-1]["Impact"])
    except Exception:
        return 0

# ==================================================
# ⚙️ PROCESO DE SEÑALES CON IMPACTO CONTEXTUAL
# ==================================================
def process_ticker(ticker, side="buy", entry=None):
    try:
        status, market_kind = market_status(ticker)
        session = market_session_for(ticker)
        t = now_et()

        pm = prob_multi_frame(ticker, side)
        p1, p5, p15, p1h = pm["per_frame"].values()
        pf = pm["final"]

        # 🔍 Analiza impacto de noticias contextual
        impact = analyze_news_contextual(ticker, pf, side)
        pf = round(min(99.9, max(0, pf + (impact * 10))), 2)

        if entry is None:
            df = fetch_yf(ticker, "1m", "1d")
            entry = float(df["Close"].iloc[-1]) if not df.empty else 0.0

        sl, tp = compute_sl_tp(entry, side, 0.0)
        clasif = "≥80" if pf >= PRE_THRESHOLD else "<80"
        estado = "Pre" if (status == "open" and pf >= PRE_THRESHOLD) else ("Dormido" if status == "closed" else "Observado")
        tipo = "Pre" if estado == "Pre" else "Scan"
        sched = (t + dt.timedelta(minutes=CONFIRM_WAIT_MIN)).isoformat() if estado == "Pre" else ""

        recipients = ALERT_DEFAULT
        if ticker.upper() == "DKNG": recipients = ALERT_DKNG
        elif ticker.upper() == "ES": recipients = ALERT_ES

        row = {
            "FechaISO": t.strftime("%Y-%m-%d"),
            "HoraLocal": t.strftime("%H:%M:%S"),
            "HoraRegistro": t.strftime("%H:%M:%S"),
            "Ticker": ticker.upper(),
            "Side": side.title(),
            "Entrada": entry,
            "Prob_1m": p1, "Prob_5m": p5, "Prob_15m": p15, "Prob_1h": p1h,
            "ProbFinal": pf,
            "ProbClasificación": clasif,
            "Estado": estado,
            "Tipo": tipo,
            "Resultado": "-",
            "Nota": status,
            "Mercado": session,
            "pattern": "none",
            "pat_score": 0,
            "macd_val": 0,
            "sr_score": 0,
            "atr": 0,
            "SL": sl,
            "TP": tp,
            "Recipients": recipients,
            "ScheduledConfirm": sched
        }

        append_signal_row_safe(row)
        log_debug("signal_registered", f"{ticker} ({pf}%) → {estado} [{impact:+.2f}]")

        if estado == "Pre":
            subject = f"📊 Señal {ticker} {side} ({pf}%)"
            body = (
                f"{ticker} {side} @ {entry}\n"
                f"ProbFinal {pf}% (impacto noticias {impact:+.2f})\n"
                f"SL {sl} | TP {tp} | Confirmación en {CONFIRM_WAIT_MIN} min."
            )
            send_mail_many(subject, body, recipients)

    except Exception as e:
        log_debug("process_ticker_error", f"{ticker}: {e}")

# ==================================================
# 🌙 NOTIFICACIÓN CORREGIDA DE GLOBEX / NYSE
# ==================================================
def notify_open_close():
    st = read_state_today()
    t = now_et().strftime("%Y-%m-%d %H:%M:%S")

    # DKNG
    m_dk, _ = market_status("DKNG")
    if m_dk == "open" and not st.get("dkng_open_sent"):
        send_mail_many("🟢 Apertura DKNG", f"DKNG abierto {t} ET", ALERT_DKNG)
        upsert_state({"dkng_open_sent": "1"})
    elif m_dk == "closed" and not st.get("dkng_close_sent"):
        send_mail_many("🔴 Cierre DKNG", f"DKNG cerrado {t} ET", ALERT_DKNG)
        upsert_state({"dkng_close_sent": "1"})
        send_daily_summary()

    # ES (Globex) — detecta correctamente pausas intermedias
    m_es, _ = market_status("ES")
    prev_state = getattr(notify_open_close, "_prev_es_state", None)
    if m_es == "open" and (prev_state != "open" or not st.get("es_open_sent")):
        send_mail_many("🟢 Apertura ES / Globex", f"Globex abierto {t} ET", ALERT_ES)
        upsert_state({"es_open_sent": "1"})
    elif m_es == "closed" and (prev_state != "closed" or not st.get("es_close_sent")):
        send_mail_many("🔴 Cierre ES / Globex", f"Globex cerrado {t} ET", ALERT_ES)
        upsert_state({"es_close_sent": "1"})
        send_daily_summary()

    notify_open_close._prev_es_state = m_es

# ==================================================
# 🚀 MAIN FINAL
# ==================================================
def main():
    log_debug("main", "run start")
    migrate_signals_header_once()
    notify_open_close()
    purge_old_debug(days=7)
    log_market_state()

    # 🔹 Análisis inicial de noticias
    for tk in WATCHLIST:
        analyze_news_contextual(tk, 50, "neutral")

    # 🔁 Ciclo principal (15 min ≈ 3 subciclos)
    for main_cycle in range(CYCLES):
        main_start = time.time()
        log_debug("cycle_main", f"Inicio ciclo {main_cycle + 1}")

        for sub_cycle in range(3):
            sub_start = time.time()
            for tk in WATCHLIST:
                process_ticker(tk, "buy", None)
            check_pending_confirmations()
            log_cycle_time(f"{main_cycle + 1}.{sub_cycle + 1}", sub_start)
            if sub_cycle < 2:
                time.sleep(300)

        log_cycle_time(main_cycle + 1, main_start)
        log_debug("cycle_main", f"Fin ciclo {main_cycle + 1}")
        for tk in WATCHLIST:
            analyze_news_contextual(tk, 50, "neutral")

    weekly_log_summary()
    send_daily_summary()
    adaptive_learning()
    log_debug("main", "run end")
