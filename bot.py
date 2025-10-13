# ==================================================
# 🤖 TRADING BOT 2025 — v4.2 SELF-HEALING
# ==================================================
from bot_config import *
import sys, time, random, requests
import pandas as pd

# ==================================================
# 🔍 ANALISIS DE SEÑALES Y MERCADO
# ==================================================
def analyze_indicators(ticker):
    """Simula indicadores para entrenamiento del bot"""
    return {
        "Prob_1m": round(random.uniform(40, 100), 2),
        "Prob_5m": round(random.uniform(40, 100), 2),
        "Prob_15m": round(random.uniform(40, 100), 2),
        "Prob_1h": round(random.uniform(40, 100), 2),
        "pattern": random.choice(["bullish_engulfing", "bearish_engulfing", "doji", "hammer"]),
        "pat_score": round(random.uniform(0.3, 0.9), 2),
        "macd_val": round(random.uniform(-2, 2), 3),
        "sr_score": round(random.uniform(0, 1), 2),
        "atr": round(random.uniform(0.2, 2.5), 2),
        "SL": round(random.uniform(0.5, 1.5), 2),
        "TP": round(random.uniform(1.0, 3.0), 2),
    }

# ==================================================
# 📰 IMPACTO DE NOTICIAS (DIRECCIONAL)
# ==================================================
def news_sentiment_adjustment(ticker):
    """Ajusta probabilidad según impacto de noticias"""
    try:
        sentiment = random.choice(["bullish", "bearish", "neutral"])
        impact = random.choice(["high", "medium", "low"])
        adj = 0
        if sentiment == "bullish": adj += 5
        elif sentiment == "bearish": adj -= 5
        if impact == "high": adj *= 1.5
        return sentiment, impact, adj
    except Exception as e:
        log_debug("news_error", str(e))
        return "neutral", "low", 0

# ==================================================
# 🧠 PROCESO DE TICKER
# ==================================================
def process_ticker(ticker, side="buy", _=None):
    try:
        now = now_et()
        fecha = now.strftime("%Y-%m-%d")
        hora_local = now.strftime("%H:%M:%S")
        indicators = analyze_indicators(ticker)

        # combinar probabilidades base
        prob_final = round(
            (indicators["Prob_1m"] * 0.1 +
             indicators["Prob_5m"] * 0.2 +
             indicators["Prob_15m"] * 0.3 +
             indicators["Prob_1h"] * 0.4), 2)

        # ajuste por noticias
        sentiment, impact, adj = news_sentiment_adjustment(ticker)
        prob_final = max(0, min(100, prob_final + adj))
        clasif = "Alta" if prob_final >= 80 else "Media" if prob_final >= 60 else "Baja"

        # estado y tipo
        estado = "Pre" if prob_final >= 75 else "Dormido"
        tipo = "Buy" if prob_final >= 50 else "Sell"

        # registrar siempre
        WS_SIGNALS.append_row([
            fecha, hora_local, now.strftime("%H:%M:%S"), ticker.upper(),
            side, "-", indicators["Prob_1m"], indicators["Prob_5m"],
            indicators["Prob_15m"], indicators["Prob_1h"], prob_final,
            clasif, estado, tipo, "-", f"{sentiment}-{impact}",
            "Globex" if ticker.upper()=="ES" else "NYSE",
            indicators["pattern"], indicators["pat_score"],
            indicators["macd_val"], indicators["sr_score"],
            indicators["atr"], indicators["SL"], indicators["TP"],
            ALERT_DEFAULT, "", ])
        log_debug("signal", f"{ticker} {clasif} {prob_final}% ({sentiment}-{impact})")

    except Exception as e:
        log_debug("process_error", str(e))

# ==================================================
# 🕓 LOG DE TIEMPO POR CICLO
# ==================================================
def log_cycle_time(cycle_num, start_time):
    try:
        elapsed = round(time.time() - start_time, 2)
        log_debug("cycle_time", f"Ciclo {cycle_num} finalizado en {elapsed}s")
    except Exception as e:
        log_debug("cycle_time_error", str(e))

# ==================================================
# 📊 RESUMEN DIARIO AUTOMÁTICO
# ==================================================
def ensure_ws_summary():
    try:
        ws = SS.worksheet("summary")
    except gspread.WorksheetNotFound:
        ws = SS.add_worksheet(title="summary", rows=500, cols=12)
        ws.update("A1", [["Fecha","Total","Pre","Confirmadas","Canceladas",
                          "Dormidas","Activos","Promedio_ProbFinal",
                          "Máx_ProbFinal","Mín_ProbFinal","Mercados","Notas"]])
    return ws

def send_daily_summary():
    try:
        today = now_et().strftime("%Y-%m-%d")
        vals = WS_SIGNALS.get_all_records()
        if not vals: return
        df = pd.DataFrame(vals)
        df_today = df[df["FechaISO"] == today]
        if df_today.empty: return

        total = len(df_today)
        pre = (df_today["Estado"] == "Pre").sum()
        conf = (df_today["Estado"] == "Confirmada").sum()
        canc = (df_today["Estado"] == "Cancelada").sum()
        dorm = (df_today["Estado"] == "Dormido").sum()
        activos = ", ".join(sorted(df_today["Ticker"].unique()))
        mercados = ", ".join(sorted(df_today["Mercado"].unique()))
        prob_series = pd.to_numeric(df_today["ProbFinal"], errors="coerce").dropna()
        prom = round(prob_series.mean(),2) if not prob_series.empty else "-"
        pmax = round(prob_series.max(),2) if not prob_series.empty else "-"
        pmin = round(prob_series.min(),2) if not prob_series.empty else "-"

        ws_sum = ensure_ws_summary()
        ws_sum.append_row([today,total,pre,conf,canc,dorm,activos,
                           prom,pmax,pmin,mercados,"OK"])

        subject=f"📊 Resumen Diario {today}"
        body=(f"Total: {total}\nPre:{pre} | Conf:{conf} | Canc:{canc} | Dorm:{dorm}\n"
              f"Activos:{activos}\nProm:{prom}% Máx:{pmax}% Mín:{pmin}%\nMercados:{mercados}")
        send_mail_many(subject,body,ALERT_DEFAULT)
        log_debug("daily_summary", f"{total} registros analizados")
    except Exception as e:
        log_debug("daily_summary_error", str(e))

# ==================================================
# 📣 NOTIFICACIONES DE MERCADO
# ==================================================
def notify_open_close():
    st = read_state_today()
    t = now_et().strftime("%Y-%m-%d %H:%M:%S")

    # DKNG
    m_dk, _ = market_status("DKNG")
    if m_dk=="open" and not st.get("dkng_open_sent"):
        send_mail_many("🟢 Apertura DKNG",f"DKNG abierto {t} ET",ALERT_DKNG)
        upsert_state({"dkng_open_sent":"1"})
    if m_dk=="closed" and not st.get("dkng_close_sent"):
        send_mail_many("🔴 Cierre DKNG",f"DKNG cerrado {t} ET",ALERT_DKNG)
        upsert_state({"dkng_close_sent":"1"})
        send_daily_summary()

    # ES (Globex)
    m_es, _ = market_status("ES")
    prev = getattr(notify_open_close, "_prev_es_state", None)

    if m_es=="open":
        if prev!="open":
            send_mail_many("🌙 Apertura Globex (ES)",f"Globex abierto {t} ET",ALERT_ES)
            upsert_state({"es_open_sent":"1"})
    else:
        if prev!="closed":
            send_mail_many("🌙 Cierre Globex (ES)",f"Globex cerrado {t} ET",ALERT_ES)
            upsert_state({"es_close_sent":"1"})
            send_daily_summary()

    notify_open_close._prev_es_state = m_es

# ==================================================
# 🧾 LOG ESTADO DE MERCADO
# ==================================================
def ensure_ws_market_status():
    try:
        ws = SS.worksheet("market_status")
    except gspread.WorksheetNotFound:
        ws = SS.add_worksheet(title="market_status", rows=1000, cols=9)
        ws.update("A1", [["FechaISO","Ticker","Hora","TipoMercado",
                          "Estado","Sesión","ProbFinal","Tiempo","Nota"]])
    return ws

def log_market_state():
    try:
        ws = ensure_ws_market_status()
        t = now_et()
        fecha, hora = t.strftime("%Y-%m-%d"), t.strftime("%H:%M:%S")
        vals = WS_SIGNALS.get_all_records()
        df = pd.DataFrame(vals) if vals else pd.DataFrame()
        prob = "-"
        if not df.empty and "ProbFinal" in df.columns:
            s = pd.to_numeric(df.loc[df["FechaISO"]==fecha,"ProbFinal"], errors="coerce").dropna()
            if not s.empty: prob = round(s.mean(),2)
        for tk in WATCHLIST:
            estado, tipo = market_status(tk)
            sesion = "Globex" if tk.upper()=="ES" else "NYSE"
            nota = "Analizando" if estado=="open" else "Fuera de horario"
            ws.append_row([fecha,tk.upper(),hora,tipo,estado,sesion,prob,
                           f"{SLEEP_SECONDS}s",nota])
            log_debug("market_state", f"{tk}->{estado}")
    except Exception as e:
        log_debug("market_state_error", str(e))

# ==================================================
# 🚀 MAIN EXTENDIDO CON SUBCICLOS
# ==================================================
def main():
    log_debug("main","run start")
    notify_open_close()
    purge_old_debug(days=7)
    log_market_state()

    for main_cycle in range(CYCLES):
        log_debug("cycle_main", f"Inicio {main_cycle+1}")
        main_start = time.time()

        for sub_cycle in range(3):
            sub_start = time.time()
            log_debug("sub_cycle", f"{main_cycle+1}.{sub_cycle+1}")
            for tk in WATCHLIST:
                process_ticker(tk,"buy",None)
            log_cycle_time(f"{main_cycle+1}.{sub_cycle+1}",sub_start)
            if sub_cycle<2: time.sleep(300)  # 5 min

        log_cycle_time(main_cycle+1, main_start)
        log_debug("cycle_main", f"Fin {main_cycle+1}")

    send_daily_summary()
    log_debug("main","run end")

# ==================================================
# ♻️ AUTO-REINICIO SI FALLA
# ==================================================
if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log_debug("fatal_error", str(e))
        print(f"⚠️ Reinicio automático: {e}")
        time.sleep(10)
        os.execv(sys.executable, ['python'] + sys.argv)
