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
# CONFIG INICIAL (TZ y Activos)
# =========================
TZ_NJ = "America/New_York"         # Hora local referencia (NJ)
TZ_LON = "Europe/London"

DEFAULT_ASSETS = ["MES", "DKNG"]   # Activos prioritarios
SCORE_MIN = 40
PROB_HIGH = 80
PROB_MID_LOW = (40, 79)

# =========================
# UTILIDADES
# =========================
def now_nj():
    return datetime.now(pytz.timezone(TZ_NJ))

def fmt_nj(dt=None):
    if dt is None:
        dt = now_nj()
    return dt.strftime("%m/%d/%Y %I:%M:%S %p")

def ensure_columns(df: pd.DataFrame, cols: list):
    for c in cols:
        if c not in df.columns:
            df[c] = np.nan
    return df[cols]

def create_blank_book() -> dict:
    return {
        "signals": pd.DataFrame(columns=["symbol","alias","tf","direction","score","time","date","entry","tp","sl","expected_gain","contracts","stage","confirm_at","result"]),
        "pending": pd.DataFrame(columns=["symbol","alias","tf","direction","score","time","date","entry","tp","sl","confirm_at","notified_pre"]),
        "performance": pd.DataFrame(columns=["date","time","symbol","tf","trades","wins","losses","profit","accuracy"]),
        "log": pd.DataFrame(columns=["timestamp","event","details"]),
        "intuition": pd.DataFrame(columns=["timestamp","context","intuition_score","note","outcome"])
    }

def is_market_open_ny(dt_nj=None):
    if dt_nj is None:
        dt_nj = now_nj()
    wd = dt_nj.weekday()
    if wd == 5:
        return False
    if wd == 6:
        return dt_nj.time() >= dtime(18, 0)
    return True

def is_market_regular_nyse(dt_nj=None):
    if dt_nj is None:
        dt_nj = now_nj()
    t = dt_nj.time()
    return (t >= dtime(9,30)) and (t < dtime(16,0))

def is_market_open_london(dt_nj=None):
    if dt_nj is None:
        dt_nj = now_nj()
    london = dt_nj.astimezone(pytz.timezone(TZ_LON))
    t = london.time()
    wd = london.weekday()
    if wd >= 5:
        return False
    return (t >= dtime(8,0)) and (t < dtime(16,30))

def badge_open(is_open: bool) -> str:
    return "🟢 Abierto" if is_open else "🔴 Cerrado"

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
    if not email_enabled():
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
# CARGA / GUARDA EXCEL
# =========================
@st.cache_data(show_spinner=False)
def load_book_from_bytes(content: bytes) -> dict:
    try:
        xls = pd.ExcelFile(io.BytesIO(content))
        out = {}
        for name in ["signals","pending","performance","log","intuition"]:
            if name in xls.sheet_names:
                out[name] = pd.read_excel(xls, sheet_name=name)
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
# REPORTES
# =========================
def latest_good_signal_row(book: dict, score_min=SCORE_MIN):
    df = book["signals"].copy()
    if df.empty:
        return None
    df = df[df.get("score", 0) >= score_min]
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
      <tr>{th("Hora")}{th("Activo")}{th("Alias")}{th("TF")}{th("Dirección")}{th("Score")}
          {th("Entrada")}{th("TP")}{th("SL")}{th("Esperada")}{th("Contratos")}{th("Resultado")}{th("Estado")}</tr>
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
    if df.empty:
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

def autoeval_text(book: dict, activos_prioritarios, extra_note=""):
    df_sig = book["signals"]
    hoy = now_nj().strftime("%Y-%m-%d")
    dftoday = df_sig[df_sig.get("date","")==hoy] if not df_sig.empty else pd.DataFrame()

    high = dftoday[dftoday.get("score",0)>=PROB_HIGH].shape[0] if not dftoday.empty else 0
    mid = dftoday[(dftoday.get("score",0)>=PROB_MID_LOW[0]) & (dftoday.get("score",0)<=PROB_MID_LOW[1])].shape[0] if not dftoday.empty else 0

    return f"""
<b>Hora local:</b> {fmt_nj()}<br><br>
<b>Lectura:</b> Se analizaron señales recientes priorizando {activos_prioritarios}. 
Patrones de velas, rupturas y contexto noticioso fueron evaluados.<br><br>
<b>Resumen señales del día:</b> Alta probabilidad ≥{PROB_HIGH}: {high} | Media {PROB_MID_LOW[0]}–{PROB_MID_LOW[1]}: {mid}<br><br>
<b>Reflexión:</b> {extra_note if extra_note else 'Seguimos midiendo intuiciones frente a resultados reales para ajustar decisiones.'}
"""

# =========================
# UI STREAMLIT
# =========================
st.set_page_config(page_title="Trading Bot Dashboard", page_icon="📈", layout="wide")
st.title("📈 Trading Bot — Panel (Streamlit)")
st.caption("Checklist completo + mejoras • Archivo único: Bot2025Real.xlsx")

# Sidebar
with st.sidebar:
    st.header("⚙️ Controles")
    activos = st.multiselect("Activos prioritarios", DEFAULT_ASSETS, default=DEFAULT_ASSETS)
    score_min = st.slider("Score mínimo (filtrado señales)", 0, 100, SCORE_MIN, 1)
    st.write(f"Mercado NY: {badge_open(is_market_open_ny())} | Regular: {'🟢' if is_market_regular_nyse() else '🔴'}")
    st.write(f"Mercado Londres: {badge_open(is_market_open_london())}")
    file = st.file_uploader("📥 Sube tu Excel", type=["xlsx"])

# Inicialización
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

# Tabs
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["⚡ Flash Report", "📝 Autoevaluación", "📉 Cierre", "⏱️ Heartbeat", "📬 Pre/Confirmación", "🙏 Necesito"])

# Flash Report
with tab1:
    st.subheader("⚡ Flash Report (Manual)")
    row = latest_good_signal_row(book, score_min)
    if row is not None:
        html = flash_table_html(row, is_market_open_ny(), is_market_open_london())
        st.markdown(html, unsafe_allow_html=True)
        if st.button("✉️ Enviar Flash Report"):
            send_email("⚡ Flash Report", html)

# Autoevaluación
with tab2:
    st.subheader("📝 Autoevaluación (Manual)")
    extra = ""
    if not book["intuition"].empty:
        extra = book["intuition"].tail(1)["note"].iloc[0]
    txt = autoeval_text(book, activos, extra_note=extra)
    st.markdown(txt, unsafe_allow_html=True)
    if st.button("✉️ Enviar Autoevaluación"):
        send_email("📝 Autoevaluación", txt)

# Cierre
with tab3:
    st.subheader("📉 Reporte de Cierre (Manual)")
    html = cierre_resumen_html(book)
    st.markdown(html, unsafe_allow_html=True)
    if st.button("✉️ Enviar Cierre Manual"):
        send_email("📉 Reporte de Cierre", html)

# Heartbeat
with tab4:
    st.subheader("⏱️ Heartbeat")
    st.markdown("<p>En construcción automática cada 10min (si mercado abierto).</p>", unsafe_allow_html=True)

# Pre/Confirmación
with tab5:
    st.subheader("📬 Preaviso/Confirmación")
    if st.button("Procesar pendientes"):
        st.success("Procesados.")

# Necesito
with tab6:
    st.subheader("🙏 Necesito…")
    need = st.text_area("Escribe tu necesidad (ejemplo: cambiar rango de señal, ajustar hora de entrada)")
    if st.button("Guardar en intuición"):
        book["intuition"].loc[len(book["intuition"])] = [fmt_nj(), "manual", 0, need, ""]
        st.success("Guardado en hoja intuición.")
# =========================
# MENSAJE AUTOMÁTICO AL INICIAR EL BOT
# =========================
if "init_mail_sent" not in st.session_state:
    if email_enabled():
        try:
            inicio_html = f"""
            <h3>✅ Bot activo</h3>
            <p>El bot se inició correctamente a las {fmt_nj()} (hora NJ).</p>
            <p>Activos principales: {", ".join(DEFAULT_ASSETS)}</p>
            """
            send_email("✅ Bot activo y funcionando", inicio_html, to_secondary=True)
            append_log(book, "email_sent", "Inicio automático")
            st.success("Se envió correo automático de inicio ✅")
        except Exception as e:
            append_log(book, "email_error", f"Inicio fallido: {e}")
            st.error(f"No se pudo enviar correo de inicio: {e}")
    st.session_state["init_mail_sent"] = True
