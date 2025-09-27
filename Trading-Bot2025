# app.py
import io
import os
import smtplib
import ssl
from datetime import datetime, time as dtime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import numpy as np
import pandas as pd
import pytz
import streamlit as st

# =========================
# CONFIG INICIAL (TZ, Activos, Umbrales)
# =========================
TZ_NJ = "America/New_York"         # Hora local NJ
TZ_LON = "Europe/London"

DEFAULT_ASSETS = ["MES", "DKNG"]   # Activos prioritarios
SCORE_MIN = 40
PROB_HIGH = 80
PROB_MID_LOW = (40, 79)

# =========================
# UTILIDADES DE TIEMPO
# =========================
def now_nj():
    return datetime.now(pytz.timezone(TZ_NJ))

def fmt_nj(dt=None):
    if dt is None:
        dt = now_nj()
    # Mes/Día/Año HH:MM:SS AM/PM
    return dt.strftime("%m/%d/%Y %I:%M:%S %p")

# =========================
# MERCADOS (NY y LONDRES)
# =========================
def is_market_open_ny(dt_nj=None):
    """
    Aproximación práctica:
    - Sábado: cerrado
    - Domingo: abre desde 18:00 (futuros como MES)
    - Lun–Vie: abierto (para propósitos de 'mercado global' del bot)
    """
    if dt_nj is None:
        dt_nj = now_nj()
    wd = dt_nj.weekday()  # Mon=0 ... Sun=6
    if wd == 5:  # Sat
        return False
    if wd == 6:  # Sun
        return dt_nj.time() >= dtime(18, 0)
    return True

def is_market_regular_nyse(dt_nj=None):
    """Cash session 9:30–16:00 ET."""
    if dt_nj is None:
        dt_nj = now_nj()
    t = dt_nj.time()
    return (t >= dtime(9,30)) and (t < dtime(16,0))

def is_market_open_london(dt_nj=None):
    """LSE regular 08:00–16:30 London time."""
    if dt_nj is None:
        dt_nj = now_nj()
    london = dt_nj.astimezone(pytz.timezone(TZ_LON))
    t = london.time()
    wd = london.weekday()
    if wd >= 5:  # Sat/Sun
        return False
    return (t >= dtime(8,0)) and (t < dtime(16,30))

def badge_open(is_open: bool) -> str:
    return "🟢 Abierto" if is_open else "🔴 Cerrado"

# =========================
# EMAIL
# =========================
def email_enabled():
    try:
        _ = st.secrets["EMAIL_USER"]
        _ = st.secrets["EMAIL_PASS"]
        _ = st.secrets["EMAIL_TO_PRIMARY"]
        _ = st.secrets["EMAIL_TO_SECONDARY"]
        return True
    except Exception:
        return False

def send_email(subject: str, html_body: str, to_secondary=False):
    """Envía correo: principal siempre; secundario sólo si to_secondary=True (pre/confirmación)."""
    if not email_enabled():
        st.info("✉️ Envío de correo omitido (no hay secretos configurados).")
        return
    user = st.secrets["EMAIL_USER"]
    pwd = st.secrets["EMAIL_PASS"]
    to1 = st.secrets["EMAIL_TO_PRIMARY"]
    to2 = st.secrets["EMAIL_TO_SECONDARY"]
    recipients = [to1]
    if to_secondary:
        recipients.append(to2)

    msg = MIMEMultipart("alternative")
    msg["From"] = user
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html"))

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
        server.login(user, pwd)
        server.sendmail(user, recipients, msg.as_string())

# =========================
# EXCEL: ESTRUCTURA Y CARGA
# =========================
def create_blank_book() -> dict:
    return {
        "signals": pd.DataFrame(columns=["symbol","alias","tf","direction","score","time","date","entry","tp","sl","expected_gain","contracts","stage","confirm_at","result"]),
        "pending": pd.DataFrame(columns=["symbol","alias","tf","direction","score","time","date","entry","tp","sl","confirm_at","notified_pre","stage"]),
        "performance": pd.DataFrame(columns=["date","time","symbol","tf","trades","wins","losses","profit","accuracy"]),
        "log": pd.DataFrame(columns=["timestamp","event","details"]),
        "intuition": pd.DataFrame(columns=["timestamp","context","intuition_score","note","outcome"])
    }

def ensure_columns(df: pd.DataFrame, cols: list):
    for c in cols:
        if c not in df.columns:
            df[c] = np.nan
    return df[cols]

@st.cache_data(show_spinner=False)
def load_book_from_bytes(content: bytes) -> dict:
    try:
        xls = pd.ExcelFile(io.BytesIO(content))
        out = {}
        for name in ["signals","pending","performance","log","intuition"]:
            if name in xls.sheet_names:
                out[name] = pd.read_excel(xls, sheet_name=name)
        # asegurar todas
        base = create_blank_book()
        for k,v in base.items():
            if k not in out:
                out[k] = v.copy()
        return out
    except Exception:
        return create_blank_book()

def save_book_to_bytes(book: dict) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        for sheet, df in book.items():
            ensure_columns(df, list(df.columns)).to_excel(writer, sheet_name=sheet, index=False)
    buf.seek(0)
    return buf.read()

def append_log(book: dict, event: str, details: str=""):
    log = book["log"]
    log.loc[len(log)] = [fmt_nj(), event, details]

# =========================
# ANALÍTICA / REPORTES
# =========================
def latest_good_signal_row(book: dict, score_min=SCORE_MIN):
    df = book["signals"].copy()
    if df.empty:
        return None
    if "score" not in df.columns:
        return None
    df = df[df["score"] >= score_min]
    if df.empty:
        return None
    return df.iloc[-1]

def flash_table_html(row: pd.Series, is_open_ny: bool, is_open_lse: bool):
    def td(v): return f"<td style='padding:6px;border:1px solid #999;text-align:center'>{v}</td>"
    def th(v): return f"<th style='padding:6px;border:1px solid #999;background:#f2f2f2'>{v}</th>"
    estado = f"NY: {badge_open(is_open_ny)} | Londres: {badge_open(is_open_lse)}"
    row = row.fillna("")
    html = f"""
    <h3>⚡ Flash Reporte</h3>
    <table style="border-collapse:collapse;font-family:Arial;font-size:14px">
      <tr>{th("Hora (NJ)")} {th("Activo")} {th("Alias")} {th("TF")} {th("Dirección")} {th("Score")}
          {th("Entrada")} {th("TP")} {th("SL")} {th("Esperada")} {th("Contratos")} {th("Resultado")} {th("Estado Mercado")}</tr>
      <tr>
        {td(fmt_nj())}
        {td(row.get('symbol',''))}
        {td(row.get('alias',''))}
        {td(row.get('tf',''))}
        {td(row.get('direction',''))}
        {td(row.get('score',''))}
        {td(row.get('entry',''))}
        {td(row.get('tp',''))}
        {td(row.get('sl',''))}
        {td(row.get('expected_gain',''))}
        {td(row.get('contracts',''))}
        {td(row.get('result','pendiente'))}
        {td(estado)}
      </tr>
    </table>
    """
    return html

def cierre_resumen_html(book: dict):
    today = now_nj().strftime("%Y-%m-%d")
    df = book["performance"]
    if df.empty or "date" not in df.columns:
        return "<p>No hubo operaciones registradas hoy.</p>"
    dft = df[df["date"] == today]
    if dft.empty:
        return "<p>No hubo operaciones registradas hoy.</p>"
    total_trades = dft["trades"].sum()
    wins = dft["wins"].sum()
    losses = dft["losses"].sum()
    profit = dft["profit"].sum()
    acc = round((wins/total_trades)*100, 2) if total_trades>0 else 0
    rentable = "✅ Rentable" if profit>0 else "❌ No rentable"
    return f"""
    <h3>📊 Reporte de Cierre — {today}</h3>
    <ul>
      <li>Total trades: <b>{total_trades}</b></li>
      <li>Ganados: <b>{wins}</b> | Perdidos: <b>{losses}</b></li>
      <li>Profit acumulado: <b>{profit}</b></li>
      <li>Accuracy: <b>{acc}%</b></li>
      <li>Resultado del día: <b>{rentable}</b></li>
    </ul>
    """

def autoeval_text(book: dict, activos_prioritarios):
    df_sig = book["signals"]
    hoy = now_nj().strftime("%Y-%m-%d")
    dftoday = df_sig[df_sig.get("date","")==hoy] if not df_sig.empty else pd.DataFrame()
    high = dftoday[dftoday.get("score",0)>=PROB_HIGH].shape[0] if not dftoday.empty else 0
    mid = dftoday[(dftoday.get("score",0)>=PROB_MID_LOW[0]) & (dftoday.get("score",0)<=PROB_MID_LOW[1])].shape[0] if not dftoday.empty else 0
    return f"""
<b>Hora local (NJ):</b> {fmt_nj()}<br><br>
<b>Lectura:</b> Se analizaron señales priorizando {', '.join(activos_prioritarios)}. 
Se ponderaron patrones de velas (envolventes, martillos/estrellas, rupturas), 
alineación multi-timeframe, momentum y consistencia con noticias.<br><br>
<b>Resumen señales del día:</b> Alta probabilidad (≥{PROB_HIGH}): {high} | Prob. media ({PROB_MID_LOW[0]}–{PROB_MID_LOW[1]}): {mid}<br><br>
<b>Reflexión:</b> Si el impulso y la volatilidad adelantan confirmaciones, 
considerar “intuiciones” con tamaño reducido y riesgo acotado. 
Seguiremos comparando intuiciones vs resultados para ajustar umbrales.
"""

def mini_heartbeat_html(book: dict):
    df = book["signals"]
    if df.empty:
        det, ok, bad = 0, 0, 0
    else:
        det = df.shape[0]
        if "result" in df.columns:
            ok = (df["result"].astype(str).str.lower()=="win").sum()
            bad = (df["result"].astype(str).str.lower()=="loss").sum()
        else:
            ok, bad = 0, 0
    return f"""
<h3>⏰ Bot trabajando</h3>
<p>Hora (NJ): {fmt_nj()}</p>
<ul>
  <li>Señales detectadas (recientes): <b>{det}</b></li>
  <li>Efectivas: <b>{ok}</b> | Fallidas: <b>{bad}</b></li>
  <li>Estado mercado: NY {badge_open(is_market_open_ny())} | Londres {badge_open(is_market_open_london())}</li>
  <li>Futuros (MES): {"🟢 Abierto" if is_market_open_ny() else "🔴 Cerrado"}</li>
</ul>
"""

def preconfirm_process_and_email(book: dict):
    """Envía preaviso/confirmación al principal y secundario si score ≥ 80."""
    pending = book["pending"]
    if pending.empty:
        return "No hay pendientes."
    msgs = []
    for _, r in pending.iterrows():
        score = r.get("score", 0)
        sym = r.get("symbol","")
        tf = r.get("tf","")
        dirc = r.get("direction","")
        entry = r.get("entry","")
        tline = r.get("time","")
        date = r.get("date","")
        stage = str(r.get("stage","")).lower()
        if score >= PROB_HIGH:
            html = f"""
            <h3>🔔 {'Confirmación' if stage=='confirm' else 'Preaviso'}</h3>
            <ul>
              <li>Activo: <b>{sym}</b></li>
              <li>TF: <b>{tf}</b></li>
              <li>Dirección: <b>{dirc}</b></li>
              <li>Entrada estimada: <b>{entry}</b></li>
              <li>Hora estimada: <b>{date} {tline}</b></li>
              <li>Score: <b>{score}</b></li>
            </ul>
            """
            try:
                send_email("🔔 Señal alta probabilidad", html, to_secondary=True)
                msgs.append(f"Enviado pre/confirmación {sym} (score {score}).")
            except Exception as e:
                msgs.append(f"Error enviando {sym}: {e}")
    return "\n".join(msgs) if msgs else "Sin señales ≥80 en pending."

# =========================
# UI STREAMLIT
# =========================
st.set_page_config(page_title="Trading Bot Dashboard", page_icon="📈", layout="wide")
st.title("📈 Trading Bot — Panel (Streamlit)")
st.caption("Archivo único: Bot2025Real.xlsx • Manual: Flash, Autoevaluación, Cierre, Heartbeat, Pre/Confirmación • NJ & Londres")

# Sidebar — controles
with st.sidebar:
    st.header("⚙️ Controles")
    activos = st.multiselect("Activos prioritarios", DEFAULT_ASSETS, default=DEFAULT_ASSETS)
    score_min = st.slider("Score mínimo (filtrado señales)", 0, 100, SCORE_MIN, 1)
    st.write(f"Mercado NY (global): {badge_open(is_market_open_ny())}  |  Cash: {'🟢' if is_market_regular_nyse() else '🔴'}")
    st.write(f"Mercado Londres: {badge_open(is_market_open_london())}")
    st.divider()
    st.write("📥 Sube tu Excel (deja vacío para usar plantilla):")
    file = st.file_uploader("Bot2025Real.xlsx", type=["xlsx"], accept_multiple_files=False)
    add_demo = st.checkbox("Cargar filas de ejemplo si está vacío (solo vista)", value=False)

# Estado del libro
if "book" not in st.session_state:
    if file is not None:
        book = load_book_from_bytes(file.read())
    else:
        book = create_blank_book()
    st.session_state["book"] = book
else:
    if file is not None and file.size > 0:
        st.session_state["book"] = load_book_from_bytes(file.read())

book = st.session_state["book"]

# Cargar ejemplos si el libro está vacío (opcional)
if add_demo:
    if book["signals"].empty:
        book["signals"] = pd.DataFrame([
            {"symbol":"MES","alias":"Micro S&P","tf":"M5","direction":"LONG","score":85,"time":"09:45","date":now_nj().strftime("%Y-%m-%d"),"entry":5200.25,"tp":5204.75,"sl":5197.00,"expected_gain":"+1R","contracts":1,"stage":"pre","confirm_at":"10:00","result":"win"},
            {"symbol":"DKNG","alias":"DraftKings","tf":"M15","direction":"SHORT","score":62,"time":"11:10","date":now_nj().strftime("%Y-%m-%d"),"entry":35.2,"tp":34.7,"sl":35.6,"expected_gain":"+0.5R","contracts":10,"stage":"watch","confirm_at":"","result":"loss"}
        ])
    if book["pending"].empty:
        book["pending"] = pd.DataFrame([
            {"symbol":"MES","alias":"Micro S&P","tf":"M5","direction":"LONG","score":82,"time":"10:00","date":now_nj().strftime("%Y-%m-%d"),"entry":5201.00,"tp":5206.00,"sl":5198.00,"confirm_at":"10:05","notified_pre":np.nan,"stage":"confirm"}
        ])
    if book["performance"].empty:
        book["performance"] = pd.DataFrame([
            {"date":now_nj().strftime("%Y-%m-%d"),"time":"16:00","symbol":"MES","tf":"M5","trades":3,"wins":2,"losses":1,"profit":125.50,"accuracy":66.7}
        ])

# ========================= TABS =========================
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "⚡ Flash Report", "📝 Autoevaluación", "📉 Cierre", "⏱️ Heartbeat", "📬 Pre/Confirmación", "💡 Intuición"
])

# ============== FLASH (MANUAL) ==============
with tab1:
    st.subheader("⚡ Flash Report (Manual)")
    st.write(f"Hora (NJ): **{fmt_nj()}** — NY {badge_open(is_market_open_ny())} | Londres {badge_open(is_market_open_london())}")

    colA, colB = st.columns([1,1])
    with colA:
        st.markdown("#### Última señal (score ≥ umbral)")
        row = latest_good_signal_row(book, score_min)
        if row is None:
            st.info("No hay señales registradas con ese umbral.")
        else:
            html = flash_table_html(row, is_market_open_ny(), is_market_open_london())
            st.markdown(html, unsafe_allow_html=True)
            if st.button("✉️ Enviar Flash por correo"):
                try:
                    send_email("⚡ Flash Report", html)
                    append_log(book, "email_sent", "Flash Report")
                    st.success("Enviado.")
                except Exception as e:
                    append_log(book, "email_error", str(e))
                    st.error(f"Error enviando: {e}")

    with colB:
        st.markdown("#### Señales de hoy")
        df_sig = book["signals"].copy()
        if not df_sig.empty and "date" in df_sig.columns:
            today = now_nj().strftime("%Y-%m-%d")
            view = df_sig[df_sig["date"]==today]
            if not view.empty:
                st.dataframe(view.tail(80), use_container_width=True, height=360)
            else:
                st.info("Sin señales para hoy.")
        else:
            st.info("No hay señales registradas.")

# ============== AUTOEVALUACIÓN (MANUAL) ==============
with tab2:
    st.subheader("📝 Autoevaluación (Manual)")
    txt = autoeval_text(book, activos)
    st.markdown(txt, unsafe_allow_html=True)
    if st.button("✉️ Enviar Autoevaluación"):
        try:
            send_email("📝 Autoevaluación (Manual)", f"<div>{txt}</div>")
            append_log(book, "email_sent", "Autoevaluación manual")
            st.success("Enviado.")
        except Exception as e:
            append_log(book, "email_error", str(e))
            st.error(f"Error enviando: {e}")

# ============== CIERRE (MANUAL) ==============
with tab3:
    st.subheader("📉 Reporte de Cierre (Manual)")
    html = cierre_resumen_html(book)
    st.markdown(html, unsafe_allow_html=True)
    if st.button("✉️ Enviar Cierre Manual"):
        try:
            send_email("📉 Reporte de Cierre Manual", html)
            append_log(book, "email_sent", "Cierre manual")
            st.success("Enviado.")
        except Exception as e:
            append_log(book, "email_error", str(e))
            st.error(f"Error enviando: {e}")

# ============== HEARTBEAT (MANUAL) ==============
with tab4:
    st.subheader("⏱️ Heartbeat (10 min — Manual)")
    mini = mini_heartbeat_html(book)
    st.markdown(mini, unsafe_allow_html=True)
    if st.button("✉️ Enviar Heartbeat"):
        try:
            send_email("⏱️ Heartbeat (10 min)", mini)
            append_log(book, "email_sent", "Heartbeat manual")
            st.success("Enviado.")
        except Exception as e:
            append_log(book, "email_error", str(e))
            st.error(f"Error enviando: {e}")

# ============== PRE/CONFIRMACIÓN ==============
with tab5:
    st.subheader("📬 Preaviso / Confirmación (≥80)")
    st.write("De la hoja **pending**: si `score ≥ 80`, se envía aviso al **principal** y al **secundario**.")
    if st.button("Procesar y enviar pre/confirmaciones"):
        msg = preconfirm_process_and_email(book)
        append_log(book, "preconfirm_process", msg)
        st.success(msg)

    st.markdown("#### Pendientes actuales")
    if book["pending"].empty:
        st.info("No hay pendientes.")
    else:
        st.dataframe(book["pending"].tail(80), use_container_width=True, height=360)

# ============== INTUICIÓN (CAPTURA) ==============
with tab6:
    st.subheader("💡 Registrar intuición")
    with st.form("intuition_form"):
        col1, col2 = st.columns([2,1])
        with col1:
            context = st.text_input("Contexto (activo/TF/escenario breve)", "")
            note = st.text_area("Nota (qué ves: velas/patrones/noticias)", "")
        with col2:
            intuition_score = st.slider("Confianza (0–100)", 0, 100, 60, 1)
            outcome = st.selectbox("Outcome (más tarde)", ["pendiente","win","loss","n/a"], index=0)
        submitted = st.form_submit_button("➕ Guardar intuición")
    if submitted:
        book["intuition"].loc[len(book["intuition"])] = [fmt_nj(), context, intuition_score, note, outcome]
        append_log(book, "intuition_add", f"{context} ({intuition_score})")
        st.success("Intuición guardada en el Excel.")

# ============== DESCARGA EXCEL ==============
st.divider()
st.markdown("### 💾 Guardar cambios")
bytes_xlsx = save_book_to_bytes(book)
st.download_button(
    "⬇️ Descargar Bot2025Real.xlsx",
    data=bytes_xlsx,
    file_name="Bot2025Real.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

with st.expander("📜 Log de eventos"):
    st.dataframe(book["log"].tail(200), use_container_width=True, height=240)
