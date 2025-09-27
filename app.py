# ========================================
# 🔥 BLOQUE MAESTRO STREAMLIT (FINAL)
# ========================================

import os, ssl, smtplib, time, requests, warnings
warnings.filterwarnings("ignore")
import pandas as pd
import numpy as np
from datetime import datetime, time as dtime
import pytz
import streamlit as st
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# =========================
# CONFIGURACIÓN
# =========================
PRIMARY_EMAIL   = os.getenv("EMAIL_TO_PRIMARY",   "gevem249@gmail.com")
SECONDARY_EMAIL = os.getenv("EMAIL_TO_SECONDARY", "adri_touma@hotmail.com")
USER_EMAIL      = os.getenv("EMAIL_USER",         "gevem249@gmail.com")
APP_PASS        = os.getenv("EMAIL_PASS",         "")  # App password seguro

NEWS_API_KEY    = os.getenv("NEWS_API_KEY",       "")

XLSX_NAME = "Bot2025Real.xlsx"
XLSX_PATH = XLSX_NAME

TZ_NJ  = pytz.timezone("America/New_York")   # referencia NJ/ET
TZ_LON = pytz.timezone("Europe/London")

DEFAULT_ASSETS = ["MES", "DKNG"]
SCORE_MIN      = 40
PROB_HIGH      = 80

# =========================
# FUNCIONES DE TIEMPO
# =========================
def now_et(): return datetime.now(TZ_NJ)
def fmt_nj(dt=None): return (dt or now_et()).strftime("%m/%d/%Y %I:%M:%S %p")
def fmt_date(dt=None): return (dt or now_et()).strftime("%m/%d/%Y")

def is_nyse_cash_open(dt=None):
    if dt is None: dt = now_et()
    if dt.weekday() >= 5: return False
    t = dt.time()
    return dtime(9,30) <= t < dtime(16,0)

def is_ny_global_open(dt=None):
    if dt is None: dt = now_et()
    wd, t = dt.weekday(), dt.time()
    if wd == 5: return False
    if wd == 6: return t >= dtime(18,0)
    if wd in (0,1,2,3): return True
    return t < dtime(17,0)

def is_london_open(dt=None):
    lon = (dt or now_et()).astimezone(TZ_LON)
    if lon.weekday() >= 5: return False
    t = lon.time()
    return dtime(8,0) <= t < dtime(16,30)

def badge(b): return "🟢 Abierto" if b else "🔴 Cerrado"

# =========================
# EXCEL
# =========================
SCHEMAS = {
    "signals":    ["symbol","alias","tf","direction","score","time","date","entry","tp","sl","expected_gain","contracts","stage","confirm_at","result"],
    "pending":    ["symbol","alias","tf","direction","score","time","date","entry","tp","sl","confirm_at","notified_pre"],
    "performance":["date","time","symbol","tf","trades","wins","losses","profit","accuracy"],
    "log":        ["timestamp","event","details"],
    "intuition":  ["timestamp","context","intuition_score","note","outcome"]
}

def setup_excel():
    if not os.path.exists(XLSX_PATH):
        with pd.ExcelWriter(XLSX_PATH, engine="openpyxl") as wr:
            for sh, cols in SCHEMAS.items():
                pd.DataFrame(columns=cols).to_excel(wr, sheet_name=sh, index=False)

def read_sheet(sheet):
    setup_excel()
    try: df = pd.read_excel(XLSX_PATH, sheet_name=sheet)
    except: df = pd.DataFrame(columns=SCHEMAS[sheet])
    for c in SCHEMAS[sheet]:
        if c not in df.columns: df[c] = np.nan
    return df[SCHEMAS[sheet]]

def write_sheet(sheet, df):
    for c in SCHEMAS[sheet]:
        if c not in df.columns: df[c] = np.nan
    with pd.ExcelWriter(XLSX_PATH, engine="openpyxl", mode="a", if_sheet_exists="replace") as wr:
        df[SCHEMAS[sheet]].to_excel(wr, sheet_name=sheet, index=False)

def log(event, details=""):
    df = read_sheet("log")
    df = pd.concat([df, pd.DataFrame([{"timestamp": fmt_nj(), "event": event, "details": details}])], ignore_index=True)
    write_sheet("log", df)

# =========================
# EMAIL
# =========================
def send_email_html(subject, body, recipients):
    if not all([USER_EMAIL, APP_PASS, PRIMARY_EMAIL]): return
    try:
        msg = MIMEMultipart("alternative")
        msg["From"], msg["To"], msg["Subject"] = USER_EMAIL, ", ".join(recipients), subject
        msg.attach(MIMEText(body, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as server:
            server.login(USER_EMAIL, APP_PASS)
            server.sendmail(USER_EMAIL, recipients, msg.as_string())
        log("email_sent", f"{subject} -> {recipients}")
    except Exception as e:
        log("email_error", str(e))

def send_all(subject, html): send_email_html(subject, html, [PRIMARY_EMAIL])
def send_preconfirm_dkng(subject, html): send_email_html(subject, html, [PRIMARY_EMAIL, SECONDARY_EMAIL])

# =========================
# STREAMLIT INTERFAZ
# =========================
st.set_page_config(page_title="Trading Bot Panel", layout="wide")

st.sidebar.header("⚙️ Controles")
assets = st.sidebar.multiselect("Activos prioritarios", DEFAULT_ASSETS, DEFAULT_ASSETS)
score_min = st.sidebar.slider("Score mínimo", 0, 100, SCORE_MIN)
st.sidebar.markdown(f"""
**Mercado NY (global):** {badge(is_ny_global_open())}  
**Cash:** {badge(is_nyse_cash_open())}  
**Londres:** {badge(is_london_open())}  
""")

# =========================
# PANEL PRINCIPAL
# =========================
st.title("📊 Trading Bot — Panel (Streamlit)")

# ✅ enviar correo solo 1 vez al abrir app
if "boot_sent" not in st.session_state:
    setup_excel()
    body = f"""
    <h3>🤖 Bot activo (Streamlit)</h3>
    <p>Hora NJ: {fmt_nj()}</p>
    <p>Activos principales: {', '.join(assets)}</p>
    <p>NY Global: {badge(is_ny_global_open())} | Cash: {badge(is_nyse_cash_open())} | Londres: {badge(is_london_open())}</p>
    """
    send_all("🤖 Bot activo (Streamlit)", body)
    st.session_state.boot_sent = True
    st.success("📧 Correo inicial enviado (Bot activo).")

# Tabs
tabs = st.tabs(["⚡ Flash Report", "📝 Autoevaluación", "📉 Cierre", "🙏 Intuición"])

with tabs[0]:
    html, valid = None, pd.DataFrame()
    sig = read_sheet("signals")
    if not sig.empty:
        sig["score"] = pd.to_numeric(sig["score"], errors="coerce").fillna(0)
        valid = sig[sig["score"] >= score_min].copy()
        if not valid.empty:
            last = valid.tail(10)[["symbol","alias","tf","direction","score","entry","tp","sl","contracts","date","time","result"]]
            st.dataframe(last)
    if st.button("📤 Enviar Flash Report"):
        if valid.empty: send_all("⚡ Flash Report", "<p>Sin señales.</p>")
        else: send_all("⚡ Flash Report", valid.to_html(index=False))
        st.success("Correo enviado.")

with tabs[1]:
    if st.button("📤 Autoevaluación"):
        body = f"""
        <h3>📝 Autoevaluación — {fmt_date()}</h3>
        <p>Señales revisadas: {len(sig)}</p>
        """
        send_all("📝 Autoevaluación", body)
        st.success("Autoevaluación enviada.")

with tabs[2]:
    if st.button("📤 Reporte de Cierre"):
        send_all("📉 Cierre Manual", "<p>Cierre enviado manual.</p>")
        st.success("Reporte enviado.")

with tabs[3]:
    note = st.text_area("Escribe tu necesidad / intuición")
    if st.button("🙏 Guardar Intuición"):
        if note.strip():
            df = read_sheet("intuition")
            df = pd.concat([df, pd.DataFrame([{"timestamp": fmt_nj(),"context":"manual","intuition_score":np.nan,"note":note,"outcome":np.nan}])], ignore_index=True)
            write_sheet("intuition", df)
            st.success("Guardado en intuición.")
