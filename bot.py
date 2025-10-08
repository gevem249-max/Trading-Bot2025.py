# ==================================================
# 🔁 BLOQUE COMPLETO FINAL — SESIONES, MONITOREO, ANÁLISIS Y RESÚMENES
# ==================================================
# (Agregar al final del archivo sin borrar código anterior)

# =========================
# 🕓 UTILIDADES DE TIEMPO / SESIONES
# =========================
def _t_at(hour: int, minute: int = 0, base: dt.datetime | None = None) -> dt.datetime:
    if base is None:
        base = now_et()
    return base.replace(hour=hour, minute=minute, second=0, microsecond=0)

def _is_between(t: dt.datetime, start: dt.datetime, end: dt.datetime) -> bool:
    if end >= start:
        return start <= t < end
    return t >= start or t < end  # cruza medianoche

# =========================
# 📈 ESTADO DE MERCADO (con Globex hasta 08:00 ET)
# =========================
def market_status(ticker: str) -> tuple[str, str]:
    t = now_et()
    wd = t.weekday()
    if ticker.upper() == "DKNG":
        if wd >= 5: return ("closed", "equity")
        if _is_between(t, _t_at(9,30,t), _t_at(16,0,t)): return ("open", "equity")
        return ("closed", "equity")
    pause_start, pause_end, globex_end = _t_at(16,0,t), _t_at(18,5,t), _t_at(8,0,t)
    if _is_between(t, pause_start, pause_end): return ("closed","futures")
    if _is_between(t, pause_end, globex_end):  return ("open","futures")
    return ("open","futures")

def es_session_label() -> str:
    t = now_et()
    pause_start, pause_end, globex_end = _t_at(16,0,t), _t_at(18,5,t), _t_at(8,0,t)
    if _is_between(t, pause_start, pause_end): return "Pause"
    if _is_between(t, pause_end, globex_end):  return "Globex"
    return "Pit"

# =========================
# ⚙️ FRECUENCIA ADAPTATIVA
# =========================
def adaptive_cycle_config(now_dt: dt.datetime | None = None) -> tuple[int, int]:
    if now_dt is None:
        now_dt = now_et()
    morning_start, morning_end = _t_at(9,30,now_dt), _t_at(13,30,now_dt)
    close_et, globex_start, globex_end = _t_at(16,0,now_dt), _t_at(18,5,now_dt), _t_at(8,0,now_dt)
    if _is_between(now_dt, morning_start, morning_end): return (240, 60)
    if _is_between(now_dt, morning_end, close_et): return (3, 600)
    if _is_between(now_dt, globex_start, globex_end): return (6, 300)
    return (2, 900)

# =========================
# 📣 NOTIFICACIONES DE APERTURA / CIERRE
# =========================
def notify_open_close():
    st = read_state_today()
    tstr = now_et().strftime("%Y-%m-%d %H:%M:%S")
    m_dk,_ = market_status("DKNG")
    if m_dk=="open" and not st.get("dkng_open_sent"):
        send_mail_many("🟢 Apertura DKNG", f"DKNG abierto {tstr} ET", ALERT_DKNG)
        upsert_state({"dkng_open_sent":"1"})
    if m_dk=="closed" and not st.get("dkng_close_sent"):
        send_mail_many("🔴 Cierre DKNG", f"DKNG cerrado {tstr} ET", ALERT_DKNG)
        upsert_state({"dkng_close_sent":"1"})
        send_daily_summary()
    m_es,_ = market_status("ES")
    prev_state=getattr(notify_open_close,"_prev_es_state",None)
    session=es_session_label()
    if m_es=="open":
        if prev_state!="open" and session=="Globex":
            log_debug("market_status","ES Globex abierto — análisis nocturno activo")
            send_mail_many("🌙 Apertura Globex (ES)",f"Globex abierto {tstr} ET",ALERT_ES)
        if not st.get("es_open_sent"):
            send_mail_many("🟢 Apertura ES",f"ES abierto {tstr} ET",ALERT_ES)
            upsert_state({"es_open_sent":"1"})
    else:
        if prev_state!="closed":
            log_debug("market_status","ES en pausa (16:00–18:05 ET)")
        last_sess=getattr(notify_open_close,"_prev_es_session",None)
        if last_sess=="Globex" and session!="Globex" and not st.get("es_close_sent"):
            send_mail_many("🌙 Cierre Globex (ES)",f"Globex cerrado {tstr} ET",ALERT_ES)
            upsert_state({"es_close_sent":"1"})
    notify_open_close._prev_es_state=m_es
    notify_open_close._prev_es_session=session

# =========================
# 📊 REGISTRO ESTADO DEL MERCADO
# =========================
def log_market_state():
    try:
        ws = ensure_ws_market_status()
        t = now_et()
        fecha, hora = t.strftime("%Y-%m-%d"), t.strftime("%H:%M:%S")
        for tk in WATCHLIST:
            estado, tipo = market_status(tk)
            sesion = es_session_label() if tk.upper()=="ES" else "NYSE"
            ws.append_row([fecha, tk.upper(), hora, tipo, estado.capitalize(), sesion, "-", f"{estado}_{sesion}", "Registro automático"])
            log_debug("market_state", f"{tk} → {estado} ({sesion})")
    except Exception as e:
        log_debug("market_state_error", str(e))

# =========================
# 📈 ANÁLISIS DE TENDENCIA Y APRENDIZAJE
# =========================
def analyze_market_trend():
    try:
        today = now_et().strftime("%Y-%m-%d")
        vals = WS_SIGNALS.get_all_records()
        if not vals: return
        df = pd.DataFrame(vals)
        df_today = df[df["FechaISO"] == today]
        if df_today.empty: return
        avg_prob = round(df_today["ProbFinal"].astype(float).mean(), 2)
        pos = (df_today["Side"].str.lower() == "buy").sum()
        neg = (df_today["Side"].str.lower() == "sell").sum()
        trend = "Neutral"
        if pos > neg * 1.2: trend = "Alcista"
        elif neg > pos * 1.2: trend = "Bajista"
        subject = f"📊 Análisis Diario {today} — Tendencia {trend}"
        body = (f"Tendencia dominante: {trend}\nPromedio ProbFinal: {avg_prob}%\nBuy: {pos} | Sell: {neg}\nTotal señales: {len(df_today)}")
        send_mail_many(subject, body, ALERT_DEFAULT)
        log_debug("market_analysis", f"{today}: {trend}, Prob={avg_prob}%")
    except Exception as e:
        log_debug("market_analysis_error", str(e))

# =========================
# 🚀 MAIN COMPLETO FINAL
# =========================
def main():
    log_debug("main","run start")
    notify_open_close()
    purge_old_debug(days=7)
    try: log_market_state()
    except Exception as e: log_debug("market_state_call", str(e))
    _cycles,_sleep=adaptive_cycle_config()
    log_debug("cycle_config",f"CYCLES={_cycles}, SLEEP={_sleep}s")
    for i in range(_cycles):
        start_time=time.time()
        for tk in WATCHLIST:
            process_ticker(tk,"buy",None)
        check_pending_confirmations()
        log_cycle_time(i+1,start_time)
        if i<_cycles-1: time.sleep(_sleep)
    weekly_log_summary()
    analyze_market_trend()
    update_prob_chart_sheet()
    send_prob_chart_email()
    log_debug("main","run end")

# ==================================================
# 📈 BLOQUE ADICIONAL — GRÁFICO AUTOMÁTICO DE PROBABILIDAD DIARIA
# ==================================================
import matplotlib.pyplot as plt
from io import BytesIO
import base64

def ensure_ws_prob_chart():
    try:
        ws=SS.worksheet("prob_chart")
    except gspread.WorksheetNotFound:
        ws=SS.add_worksheet(title="prob_chart",rows=500,cols=5)
        ws.update("A1",[["Fecha","Ticker","ProbFinal","Tendencia","Promedio"]])
        return ws
    vals=ws.get_all_values()
    if not vals:
        ws.update("A1",[["Fecha","Ticker","ProbFinal","Tendencia","Promedio"]])
    return ws

def update_prob_chart_sheet():
    try:
        ws=ensure_ws_prob_chart()
        vals=WS_SIGNALS.get_all_records()
        if not vals: return
        df=pd.DataFrame(vals)
        df["ProbFinal"]=pd.to_numeric(df["ProbFinal"],errors="coerce")
        df=df.dropna(subset=["ProbFinal"])
        df_group=df.groupby(["FechaISO","Ticker"])["ProbFinal"].mean().reset_index()
        df_group["Promedio"]=round(df_group["ProbFinal"].mean(),2)
        df_group["Tendencia"]=np.where(df_group["ProbFinal"]>df_group["Promedio"],"Alta","Baja")
        ws.clear()
        ws.update("A1",[list(df_group.columns)])
        ws.update("A2",df_group.astype(str).values.tolist())
        log_debug("prob_chart",f"{len(df_group)} registros actualizados")
    except Exception as e:
        log_debug("prob_chart_error",str(e))

def generate_prob_chart_image():
    try:
        vals=WS_SIGNALS.get_all_records()
        if not vals: return None
        df=pd.DataFrame(vals)
        df["ProbFinal"]=pd.to_numeric(df["ProbFinal"],errors="coerce")
        df=df.dropna(subset=["ProbFinal"])
        df_group=df.groupby("FechaISO")["ProbFinal"].mean().reset_index()
        if df_group.empty: return None
        plt.figure(figsize=(8,4))
        plt.plot(df_group["FechaISO"],df_group["ProbFinal"],marker="o",linestyle="-")
        plt.title("Evolución diaria del ProbFinal")
        plt.xlabel("Fecha")
        plt.ylabel("ProbFinal (%)")
        plt.grid(True)
        plt.tight_layout()
        img_bytes=BytesIO()
        plt.savefig(img_bytes,format="png")
        img_bytes.seek(0)
        plt.close()
        encoded=base64.b64encode(img_bytes.read()).decode("utf-8")
        return encoded
    except Exception as e:
        log_debug("prob_chart_image_error",str(e))
        return None

def send_prob_chart_email():
    try:
        today=now_et().strftime("%Y-%m-%d")
        encoded=generate_prob_chart_image()
        if not encoded: return
        html=f"""
        <html><body>
        <h3>📈 Evolución de ProbFinal — {today}</h3>
        <p>Promedio diario de probabilidades detectadas.</p>
        <img src="data:image/png;base64,{encoded}" alt="ProbChart"/>
        </body></html>"""
        msg=MIMEText(html,"html")
        msg["Subject"]=f"📊 Gráfico Diario ProbFinal — {today}"
        msg["From"]=GMAIL_USER
        msg["To"]=ALERT_DEFAULT
        with smtplib.SMTP_SSL("smtp.gmail.com",465) as s:
            s.login(GMAIL_USER,GMAIL_PASS)
            s.sendmail(GMAIL_USER,ALERT_DEFAULT.split(","),msg.as_string())
        log_debug("prob_chart_email","Gráfico diario enviado")
    except Exception as e:
        log_debug("prob_chart_email_error",str(e))
