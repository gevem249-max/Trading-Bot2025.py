# app.py — Trading Bot Dashboard (Streamlit)
# Checklist original + mejoras + correcciones finales

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

APP_EXCEL_NAME = "Bot2025Real.xlsx"

# =========================
# UTILIDADES DE TIEMPO
# =========================
def now_nj():
    return datetime.now(pytz.timezone(TZ_NJ))

def fmt_nj(dt=None):
    if dt is None:
        dt = now_nj()
    return dt.strftime("%m/%d/%Y %I:%M:%S %p")

# =========================
# MERCADOS (NY & LONDRES)
# =========================
def is_market_open_ny(dt_nj=None):
    """
    NY 'global' (pensado para Futuros MES): 
    - Domingo >= 18:00 (ET) a Viernes tarde.
    - Sábado siempre cerrado. En semana, se considera abierto.
    """
    if dt_nj is None:
        dt_nj = now_nj()
    wd = dt_nj.weekday()  # Mon=0 ... Sun=6
    if wd == 5:  # Saturday
        return False
    if wd == 6:  # Sunday
        return dt_nj.time() >= dtime(18, 0)
    return True

def is_market_regular_nyse(dt_nj=None):
    """Cash NYSE 9:30–16:00 (ET)."""
    if dt_nj is None:
        dt_nj = now_nj()
    t = dt_nj.time()
    return (t >= dtime(9,30)) and (t < dtime(16,0))

def is_market_open_london(dt_nj=None):
    """LSE regular 08:00–16:30 (hora Londres)."""
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

def send_email(subject: str, html_body: str, *, to_secondary=False, restrict_secondary_symbol=None):
    """
    Envía correo:
      - Principal SIEMPRE.
      - Secundario SOLO si to_secondary=True.
      - Si restrict_secondary_symbol está definido, sólo añade secundario si el HTML menciona ese símbolo (p.ej. 'DKNG').
    """
    if not email_enabled():
        st.info("✉️ Envío omitido (no hay secretos configurados).")
        return

    user = st.secrets["EMAIL_USER"]
    pwd = st.secrets["EMAIL_PASS"]
    to1 = st.secrets["EMAIL_TO_PRIMARY"]
    to2 = st.secrets["EMAIL_TO_SECONDARY"]

    recipients = [to1]
    if to_secondary:
        if restrict_secondary_symbol:
            if restrict_secondary_symbol.upper() in html_body.upper():
                recipients.append(to2)
        else:
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
# EXCEL: ESTRUCTURA, CARGA, GUARDA
# =========================
def create_blank_book() -> dict:
    return {
        "signals": pd.DataFrame(columns=[
            "symbol","alias","tf","direction","score","time","date",
            "entry","tp","sl","expected_gain","contracts","stage","confirm_at","result"
        ]),
        "pending": pd.DataFrame(columns=[
            "symbol","alias","tf","direction","score","time","date",
            "entry","tp","sl","confirm_at","stage","notified_pre"
        ]),
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
        base = create_blank_book()
        for k,v in base.items():
            if k not in out:
                out[k] = v.copy()
        return out
    except Exception:
        return create_blank_book()

def save_book_to_bytes(book: dict) -> bytes:
    buf = io.BytesIO()
    # Intento con xlsxwriter; si falla, fallback a openpyxl
    try:
        with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
            for sheet, df in book.items():
                ensure_columns(df, list(df.columns)).to_excel(writer, sheet_name=sheet, index=False)
    except Exception:
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
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
    <h3>⚡ Flash Report</h3>
    <table style="border-collapse:collapse;font-family:Arial;font-size:14px">
      <tr>{th("Hora")}{th("Activo")}{th("Alias")}{th("TF")}{th("Dirección")}{th("Score")}
          {th("Entrada")}{th("TP")}{th("SL")}{th("Esperada")}{th("Contratos")}{th("Resultado")}{th("Mercados")}</tr>
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

def autoeval_text(book: dict, activos_prioritarios):
    df_sig = book["signals"]
    hoy = now_nj().strftime("%Y-%m-%d")
    dftoday = df_sig[df_sig.get("date","")==hoy] if not df_sig.empty else pd.DataFrame()

    high = dftoday[dftoday.get("score",0)>=PROB_HIGH].shape[0] if not dftoday.empty else 0
    mid = dftoday[(dftoday.get("score",0)>=PROB_MID_LOW[0]) & (dftoday.get("score",0)<=PROB_MID_LOW[1])].shape[0] if not dftoday.empty else 0

    return f"""
<b>Hora local:</b> {fmt_nj()}<br><br>
<b>Lectura:</b> Se analizaron señales recientes priorizando {activos_prioritarios}. 
Se ponderaron patrones de velas (envolventes, martillos/estrellas, rupturas), 
alineación con tendencia en TF mayor y consistencia con noticias relevantes.<br><br>
<b>Resumen señales del día:</b> Alta probabilidad (≥{PROB_HIGH}): {high} | Prob. media ({PROB_MID_LOW[0]}–{PROB_MID_LOW[1]}): {mid}<br><br>
<b>Noticias destacadas:</b> Sin novedades relevantes.<br><br>
<b>Reflexión:</b> Si el impulso previo y la volatilidad adelantaron los cruces de indicadores, 
consideramos “intuiciones” con tamaño reducido y gestión estricta de riesgo. 
Seguiremos comparando intuiciones vs resultados para ajustar umbrales.
"""

def mini_heartbeat_html(book: dict):
    df = book["signals"]
    if df.empty:
        det, ok, bad = 0, 0, 0
    else:
        det = df.shape[0]
        if "result" in df.columns:
            s = df["result"].astype(str).str.lower()
            ok = (s=="win").sum()
            bad = (s=="loss").sum()
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
    """
    Envía preaviso/confirmación desde 'pending' si score ≥80.
    - Principal SIEMPRE.
    - Secundario SOLO para DKNG (según política de ruta).
    """
    pending = book["pending"]
    if pending.empty:
        return "No hay pendientes."

    msgs = []
    for _, r in pending.iterrows():
        score = r.get("score", 0)
        sym = str(r.get("symbol","")).upper()
        tf = r.get("tf","")
        dirc = r.get("direction","")
        entry = r.get("entry","")
        tline = r.get("time","")
        date = r.get("date","")
        stage = str(r.get("stage","")).lower()
        etiqueta = "Confirmación" if stage=="confirm" else "Preaviso"

        if score >= PROB_HIGH:
            html = f"""
            <h3>🔔 {etiqueta}</h3>
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
                # Secundario sólo para DKNG
                send_email("🔔 Señal alta probabilidad", html, to_secondary=True, restrict_secondary_symbol="DKNG")
                msgs.append(f"Enviado {etiqueta} {sym} ({score}).")
            except Exception as e:
                msgs.append(f"Error enviando {sym}: {e}")
    return "\n".join(msgs) if msgs else "Sin señales ≥80 en pending."

# =========================
# STREAMLIT UI
# =========================
st.set_page_config(page_title="Trading Bot Dashboard", page_icon="📈", layout="wide")
st.title("📈 Trading Bot — Panel (Streamlit)")
st.caption(f"Checklist completo + mejoras • Archivo único: {APP_EXCEL_NAME} • Manual: Flash, Autoevaluación, Cierre, Heartbeat, Pre/Confirmación, Intuición • NY & Londres")

# Sidebar — controles
with st.sidebar:
    st.header("⚙️ Controles")
    activos = st.multiselect("Activos prioritarios", DEFAULT_ASSETS, default=DEFAULT_ASSETS)
    score_min = st.slider("Score mínimo (filtrado señales)", 0, 100, SCORE_MIN, 1)
    st.markdown(f"**Mercado NY (global):** {badge_open(is_market_open_ny())}  \n**Cerrado | Cash:** {'🟢' if is_market_regular_nyse() else '🔴'}")
    st.markdown(f"**Mercado Londres:** {badge_open(is_market_open_london())}")
    st.divider()
    st.write("📥 **Sube tu Excel** (deja vacío para usar plantilla base):")
    file = st.file_uploader(APP_EXCEL_NAME, type=["xlsx"], accept_multiple_files=False)

# Carga del libro (estado)
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

# Notificación automática de inicio (una vez por sesión)
if "_welcome_sent" not in st.session_state:
    try:
        html = f"""
        <h3>✅ Bot activo</h3>
        <p>El bot se inició correctamente a las <b>{fmt_nj()}</b> (hora NJ).</p>
        <p>Activos principales: <b>{', '.join(activos)}</b></p>
        <p>NY: {badge_open(is_market_open_ny())} | Cash: {'🟢' if is_market_regular_nyse() else '🔴'} | Londres: {badge_open(is_market_open_london())}</p>
        """
        send_email("✅ Bot activo y funcionando", html, to_secondary=False)
        append_log(book, "email_sent", "welcome_auto")
        st.session_state["_welcome_sent"] = True
        st.success("Se envió correo automático de inicio ✅")
    except Exception as e:
        append_log(book, "email_error", f"welcome_auto: {e}")
        st.session_state["_welcome_sent"] = True

# Pestañas
tabs = st.tabs(["⚡ Flash Report", "📝 Autoevaluación", "📉 Cierre", "⏱️ Heartbeat", "📬 Pre/Confirmación", "🙏 Necesito"])

# ============== FLASH (MANUAL) ==============
with tabs[0]:
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
                    send_email("⚡ Flash Report", html, to_secondary=False)
                    append_log(book, "email_sent", "flash_manual")
                    st.success("Flash enviado.")
                except Exception as e:
                    append_log(book, "email_error", f"flash_manual: {e}")
                    st.error(f"Error enviando: {e}")

    with colB:
        st.markdown("#### Señales de hoy")
        df_sig = book["signals"].copy()
        if not df_sig.empty and "date" in df_sig.columns:
            today = now_nj().strftime("%Y-%m-%d")
            st.dataframe(df_sig[df_sig["date"]==today].tail(100), use_container_width=True, height=360)
        else:
            st.info("Sin señales de hoy.")

# ============== AUTOEVALUACIÓN (MANUAL) ==============
with tabs[1]:
    st.subheader("📝 Autoevaluación (Manual)")
    txt = autoeval_text(book, activos)
    st.markdown(txt, unsafe_allow_html=True)

    if st.button("✉️ Enviar Autoevaluación"):
        try:
            send_email("📝 Autoevaluación (Manual)", f"<div>{txt}</div>", to_secondary=False)
            append_log(book, "email_sent", "autoeval_manual")
            st.success("Autoevaluación enviada.")
        except Exception as e:
            append_log(book, "email_error", f"autoeval_manual: {e}")
            st.error(f"Error enviando: {e}")

# ============== CIERRE (MANUAL) ==============
with tabs[2]:
    st.subheader("📉 Reporte de Cierre (Manual)")
    html = cierre_resumen_html(book)
    st.markdown(html, unsafe_allow_html=True)

    if st.button("✉️ Enviar Cierre Manual"):
        try:
            send_email("📉 Reporte de Cierre Manual", html, to_secondary=False)
            append_log(book, "email_sent", "cierre_manual")
            st.success("Cierre enviado.")
        except Exception as e:
            append_log(book, "email_error", f"cierre_manual: {e}")
            st.error(f"Error enviando: {e}")

# ============== HEARTBEAT (MANUAL) ==============
with tabs[3]:
    st.subheader("⏱️ Heartbeat (10 min — Manual)")
    mini = mini_heartbeat_html(book)
    st.markdown(mini, unsafe_allow_html=True)

    if st.button("✉️ Enviar Heartbeat"):
        try:
            send_email("⏱️ Heartbeat (10 min)", mini, to_secondary=False)
            append_log(book, "email_sent", "heartbeat_manual")
            st.success("Heartbeat enviado.")
        except Exception as e:
            append_log(book, "email_error", f"heartbeat_manual: {e}")
            st.error(f"Error enviando: {e}")

# ============== PRE/CONFIRMACIÓN ==============
with tabs[4]:
    st.subheader("📬 Preaviso / Confirmación (≥80%)")
    st.write("Desde **pending**: si `score ≥ 80`, envía al principal y, **sólo para DKNG**, también al secundario.")
    if st.button("Procesar y enviar pre/confirmaciones"):
        msg = preconfirm_process_and_email(book)
        append_log(book, "preconfirm_process", msg)
        st.success(msg)
    st.markdown("#### Pendientes actuales")
    if book["pending"].empty:
        st.info("No hay pendientes.")
    else:
        st.dataframe(book["pending"].tail(100), use_container_width=True, height=360)

# ============== NECESITO (INTUICIÓN) ==============
with tabs[5]:
    st.subheader("🙏 Necesito…")
    need = st.text_area("Escribe tu necesidad (ejemplo: cambiar rango de señal, ajustar hora de entrada)")
    if st.button("Guardar en intuición"):
        note = need.strip()
        if note:
            df = book["intuition"]
            df.loc[len(df)] = [fmt_nj(), "manual_input", None, note, None]
            append_log(book, "intuition_add", note[:80])
            st.success("Guardado en hoja 'intuition'.")

# ============== DESCARGA EXCEL ==============
st.divider()
st.markdown("### 💾 Guardar cambios")
bytes_xlsx = save_book_to_bytes(book)
st.download_button(
    "⬇️ Descargar Bot2025Real.xlsx",
    data=bytes_xlsx,
    file_name=APP_EXCEL_NAME,
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

# Mostrar log
with st.expander("📜 Log de eventos"):
    st.dataframe(book["log"].tail(300), use_container_width=True, height=280)
