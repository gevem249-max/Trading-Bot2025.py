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
# CONFIG INICIAL
# =========================
TZ_NJ = "America/New_York"         # Hora local NJ
TZ_LON = "Europe/London"

DEFAULT_ASSETS = ["MES", "DKNG"]
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

def badge_open(is_open: bool) -> str:
    return "🟢 Abierto" if is_open else "🔴 Cerrado"

def is_market_open_ny(dt=None):
    if dt is None: dt = now_nj()
    wd = dt.weekday()
    if wd == 5: return False
    if wd == 6: return dt.time() >= dtime(18,0)
    return True

def is_market_regular_nyse(dt=None):
    if dt is None: dt = now_nj()
    t = dt.time()
    return (t >= dtime(9,30)) and (t < dtime(16,0))

def is_market_open_london(dt=None):
    if dt is None: dt = now_nj()
    london = dt.astimezone(pytz.timezone(TZ_LON))
    wd = london.weekday()
    t = london.time()
    if wd >= 5: return False
    return (t >= dtime(8,0)) and (t < dtime(16,30))

# =========================
# CORREOS
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
    if not email_enabled():
        st.info("✉️ No hay credenciales configuradas.")
        return
    user = st.secrets["EMAIL_USER"]
    pwd = st.secrets["EMAIL_PASS"]
    to1 = st.secrets["EMAIL_TO_PRIMARY"]
    to2 = st.secrets["EMAIL_TO_SECONDARY"]
    recipients = [to1]
    if to_secondary: recipients.append(to2)

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
# EXCEL
# =========================
def create_blank_book():
    return {
        "signals": pd.DataFrame(columns=["symbol","alias","tf","direction","score","time","date","entry","tp","sl","expected_gain","contracts","stage","confirm_at","result"]),
        "pending": pd.DataFrame(columns=["symbol","alias","tf","direction","score","time","date","entry","tp","sl","confirm_at","notified_pre"]),
        "performance": pd.DataFrame(columns=["date","time","symbol","tf","trades","wins","losses","profit","accuracy"]),
        "log": pd.DataFrame(columns=["timestamp","event","details"]),
        "intuition": pd.DataFrame(columns=["timestamp","context","intuition_score","note","outcome"])
    }

@st.cache_data(show_spinner=False)
def load_book_from_bytes(content: bytes):
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

def save_book_to_bytes(book: dict):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        for sheet, df in book.items():
            df.to_excel(writer, sheet_name=sheet, index=False)
    buf.seek(0)
    return buf.read()

# =========================
# REPORTES
# =========================
def flash_report(book, score_min):
    df = book["signals"]
    if df.empty: return "<p>Sin señales registradas.</p>"
    df = df[df["score"] >= score_min]
    if df.empty: return "<p>Sin señales ≥ umbral.</p>"
    row = df.iloc[-1]
    html = f"""
    <h3>⚡ Flash Report</h3>
    <table border=1>
      <tr><th>Hora</th><th>Activo</th><th>Alias</th><th>TF</th><th>Dirección</th><th>Score</th>
      <th>Entrada</th><th>TP</th><th>SL</th><th>Contratos</th><th>Resultado</th></tr>
      <tr>
        <td>{fmt_nj()}</td><td>{row['symbol']}</td><td>{row['alias']}</td>
        <td>{row['tf']}</td><td>{row['direction']}</td><td>{row['score']}</td>
        <td>{row['entry']}</td><td>{row['tp']}</td><td>{row['sl']}</td>
        <td>{row['contracts']}</td><td>{row.get('result','pendiente')}</td>
      </tr>
    </table>
    """
    return html

def cierre_resumen(book):
    df = book["performance"]
    if df.empty: return "<p>No hubo operaciones hoy.</p>"
    today = now_nj().strftime("%Y-%m-%d")
    df = df[df["date"] == today]
    if df.empty: return "<p>No hubo operaciones hoy.</p>"
    total_trades = df["trades"].sum()
    wins = df["wins"].sum()
    losses = df["losses"].sum()
    profit = df["profit"].sum()
    acc = round((wins/total_trades)*100,2) if total_trades>0 else 0
    return f"""
    <h3>📊 Cierre {today}</h3>
    <ul>
      <li>Trades: {total_trades}</li>
      <li>Ganados: {wins} | Perdidos: {losses}</li>
      <li>Profit: {profit}</li>
      <li>Accuracy: {acc}%</li>
    </ul>
    """

def autoeval(book):
    df = book["signals"]
    today = now_nj().strftime("%Y-%m-%d")
    df = df[df["date"] == today]
    high = df[df["score"]>=PROB_HIGH].shape[0]
    mid  = df[(df["score"]>=PROB_MID_LOW[0]) & (df["score"]<=PROB_MID_LOW[1])].shape[0]
    return f"""
    <h3>📝 Autoevaluación {today}</h3>
    <p>Alta probabilidad: {high} | Media: {mid}</p>
    <p>Patrones: velas impulsivas, soportes/resistencias, confluencias EMA/RSI.</p>
    <p>Reflexión: seguir comparando intuiciones vs señales confirmadas.</p>
    """

def mini_heartbeat(book):
    df = book["signals"]
    if df.empty:
        return "<p>Sin señales en los últimos 10 min.</p>"
    lastN = df.tail(20)
    good = (lastN["score"]>=80).sum()
    mid  = ((lastN["score"]>=60)&(lastN["score"]<80)).sum()
    weak = ((lastN["score"]>=40)&(lastN["score"]<60)).sum()
    return f"""
    <h3>⏱️ Heartbeat</h3>
    <p>Hora: {fmt_nj()}</p>
    <ul>
      <li>Fuertes ≥80: {good}</li>
      <li>Medias 60–79: {mid}</li>
      <li>Básicas 40–59: {weak}</li>
      <li>Mercado NY: {badge_open(is_market_open_ny())}</li>
      <li>Londres: {badge_open(is_market_open_london())}</li>
    </ul>
    """

def preconfirm_process(book):
    df = book["pending"]
    if df.empty: return "No hay pendientes."
    df["score"] = pd.to_numeric(df["score"], errors="coerce").fillna(0)
    mask = df["score"] >= 80
    high = df[mask]
    if high.empty: return "Sin señales ≥80."
    for _, r in high.iterrows():
        sym = r.get("symbol","")
        tf  = r.get("tf","")
        dirc = r.get("direction","")
        score = r.get("score","")
        html = f"""
        <h3>📬 Pre/Confirmación</h3>
        <ul>
          <li>Activo: {sym}</li>
          <li>TF: {tf}</li>
          <li>Dirección: {dirc}</li>
          <li>Score: {score}</li>
        </ul>
        """
        if sym.upper()=="DKNG":
            send_email("📬 Señal DKNG", html, to_secondary=True)
        else:
            send_email("📬 Señal", html)
    return f"Se procesaron {len(high)} señales ≥80."

# =========================
# UI STREAMLIT
# =========================
st.set_page_config(page_title="Trading Bot Dashboard", page_icon="📈", layout="wide")
st.title("📈 Trading Bot — Panel Completo")

with st.sidebar:
    st.header("⚙️ Controles")
    activos = st.multiselect("Activos", DEFAULT_ASSETS, default=DEFAULT_ASSETS)
    score_min = st.slider("Score mínimo", 0, 100, SCORE_MIN, 1)
    st.write(f"Mercado NY: {badge_open(is_market_open_ny())} | Regular: {badge_open(is_market_regular_nyse())}")
    st.write(f"Londres: {badge_open(is_market_open_london())}")
    file = st.file_uploader("Sube Bot2025Real.xlsx", type=["xlsx"])

if "book" not in st.session_state:
    if file: st.session_state["book"] = load_book_from_bytes(file.read())
    else: st.session_state["book"] = create_blank_book()
elif file: st.session_state["book"] = load_book_from_bytes(file.read())

book = st.session_state["book"]

tab1, tab2, tab3, tab4, tab5 = st.tabs(["⚡ Flash", "📝 Autoeval", "📉 Cierre", "⏱️ Heartbeat", "📬 Pre/Confirm"])

with tab1:
    st.subheader("⚡ Flash Report (Manual)")
    html = flash_report(book, score_min)
    st.markdown(html, unsafe_allow_html=True)
    if st.button("✉️ Enviar Flash"):
        send_email("⚡ Flash Report", html)

with tab2:
    st.subheader("📝 Autoevaluación (Manual)")
    txt = autoeval(book)
    st.markdown(txt, unsafe_allow_html=True)
    if st.button("✉️ Enviar Autoeval"):
        send_email("📝 Autoevaluación", txt)

with tab3:
    st.subheader("📉 Reporte Cierre (Manual)")
    html = cierre_resumen(book)
    st.markdown(html, unsafe_allow_html=True)
    if st.button("✉️ Enviar Cierre"):
        send_email("📉 Reporte Cierre", html)

with tab4:
    st.subheader("⏱️ Heartbeat (Manual)")
    html = mini_heartbeat(book)
    st.markdown(html, unsafe_allow_html=True)
    if st.button("✉️ Enviar Heartbeat"):
        send_email("⏱️ Heartbeat", html)

with tab5:
    st.subheader("📬 Pre/Confirmación (Manual ≥80%)")
    st.write(preconfirm_process(book))

st.divider()
st.download_button(
    "⬇️ Descargar Bot2025Real.xlsx",
    save_book_to_bytes(book),
    file_name="Bot2025Real.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
