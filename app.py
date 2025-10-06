# app.py — Panel de Señales Trading Bot 2025 (recientes arriba)

import os, json, pytz, datetime as dt
import pandas as pd
import numpy as np
import gspread
from google.oauth2.service_account import Credentials
import streamlit as st
import matplotlib.pyplot as plt

# =========================
# 🔧 Configuración
# =========================
TZ = pytz.timezone("America/New_York")

SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
GS_JSON = json.loads(os.getenv("GOOGLE_SHEETS_JSON"))
CREDS = Credentials.from_service_account_info(
    GS_JSON, scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
GC = gspread.authorize(CREDS)
SHEET = GC.open_by_key(SPREADSHEET_ID).sheet1

# =========================
# 🧭 Utilidades tiempo/mercado
# =========================
def now_et() -> dt.datetime:
    return dt.datetime.now(TZ)

def is_market_open(market: str, t: dt.datetime) -> bool:
    wd = t.weekday()
    h, m = t.hour, t.minute
    minutes = h * 60 + m

    if market == "equity":
        if wd >= 5:  # fin de semana
            return False
        return (9*60 + 30) <= minutes < (16*60)

    if market == "cme_micro":
        if wd == 5: return False
        if wd == 6 and minutes < (18*60): return False
        if wd == 4 and minutes >= (17*60): return False
        if (17*60) <= minutes < (18*60): return False
        return True

    if market == "forex":
        if wd == 5: return False
        if wd == 6 and minutes < (17*60): return False
        if wd == 4 and minutes >= (17*60): return False
        return True

    if market == "crypto":
        return True

    return False

# =========================
# 📄 Datos de Google Sheets
# =========================
def load_data() -> pd.DataFrame:
    values = SHEET.get_all_records()
    if not values:
        return pd.DataFrame(columns=[
            "FechaISO","HoraLocal","HoraRegistro","Ticker","Side","Entrada",
            "Prob_1m","Prob_5m","Prob_15m","Prob_1h","ProbFinal",
            "Estado","Resultado","Nota","Mercado"
        ])
    df = pd.DataFrame(values)

    # 🔧 Normalizar tipos
    for col in df.columns:
        if col.startswith("Prob") or col in ["Entrada"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        else:
            df[col] = df[col].astype(str)

    # Ordenar de más reciente a más antiguo (Fecha + HoraRegistro si existen)
    if "FechaISO" in df.columns and "HoraRegistro" in df.columns:
        try:
            df["_ts"] = pd.to_datetime(df["FechaISO"] + " " + df["HoraRegistro"], errors="coerce")
            df = df.sort_values("_ts", ascending=False).drop(columns=["_ts"])
        except Exception:
            pass

    return df

# =========================
# 🎨 UI — Streamlit
# =========================
st.set_page_config(page_title="Panel de Señales", layout="wide")

hora_actual = now_et()
labels = {"equity":"Equities", "cme_micro":"CME Micros", "forex":"Forex", "crypto":"Crypto"}
st.markdown("### ⏰ Hora local (ET): " + hora_actual.strftime("%Y-%m-%d %H:%M:%S"))
cols = st.columns(4)
for i, mkt in enumerate(["equity","cme_micro","forex","crypto"]):
    opened = is_market_open(mkt, hora_actual)
    icon = "🟢" if opened else "🔴"
    with cols[i]:
        st.markdown(f"**{labels[mkt]}**")
        st.markdown(f"{icon} **{'Abierto' if opened else 'Cerrado'}**")

st.title("🤖 Bot 2025")
st.success("😊 Bot Activo – corriendo en tiempo real")

df = load_data()

# =========================
# 📑 Pestañas
# =========================
tabs = st.tabs([
    "✅ Señales Enviadas",
    "❌ Descartadas",
    "📈 Resultados Hoy",
    "📊 Histórico",
    "📉 Distribución Probabilidades",
    "🕒 Últimas Señales",
    "📊 Resumen Global"
])

# 1) Señales enviadas
with tabs[0]:
    st.subheader("✅ Señales enviadas (≥80%)")
    sent = df[df["Estado"].isin(["Pre","Confirmada","Confirmado"])] if not df.empty else pd.DataFrame()
    if sent.empty:
        st.warning("⚠️ No hay señales enviadas registradas.")
    else:
        st.dataframe(sent, use_container_width=True)

# 2) Descartadas
with tabs[1]:
    st.subheader("❌ Señales descartadas (<80%)")
    disc = df[df["Estado"].eq("Descartada")] if not df.empty else pd.DataFrame()
    if disc.empty:
        st.warning("⚠️ No hay señales descartadas.")
    else:
        st.dataframe(disc, use_container_width=True)

# 3) Resultados hoy
with tabs[2]:
    st.subheader("📈 Resultados de Hoy")
    if df.empty:
        st.warning("⚠️ No hay resultados hoy.")
    else:
        today = hora_actual.strftime("%Y-%m-%d")
        today_df = df[df["FechaISO"].eq(today)]
        if today_df.empty:
            st.warning("⚠️ No hay resultados hoy.")
        else:
            st.dataframe(today_df, use_container_width=True)
            winloss_data = today_df["Resultado"].value_counts()
            fig, ax = plt.subplots()
            winloss_data.reindex(["Win","Loss","-"]).fillna(0).plot(kind="bar", color=["green","red","gray"], ax=ax)
            ax.set_title("Resultados Win/Loss (Hoy)")
            ax.set_ylabel("Cantidad")
            st.pyplot(fig)

# 4) Histórico
with tabs[3]:
    st.subheader("📊 Histórico Completo")
    if df.empty:
        st.warning("⚠️ No hay histórico todavía.")
    else:
        st.dataframe(df, use_container_width=True)

# 5) Distribución Probabilidades
with tabs[4]:
    st.subheader("📉 Distribución de Probabilidades")
    if df.empty or "ProbFinal" not in df.columns:
        st.warning("⚠️ No hay datos de probabilidades.")
    else:
        fig, ax = plt.subplots()
        pd.to_numeric(df["ProbFinal"], errors="coerce").dropna().hist(bins=20, ax=ax, color="skyblue", edgecolor="black")
        ax.set_title("Distribución de Probabilidades")
        ax.set_xlabel("Probabilidad final")
        ax.set_ylabel("Frecuencia")
        st.pyplot(fig)

# 6) Últimas señales
with tabs[5]:
    st.subheader("🕒 Últimas Señales Registradas")
    if df.empty:
        st.warning("⚠️ No hay señales recientes.")
    else:
        st.dataframe(df.head(10), use_container_width=True)  # 👈 head en lugar de tail

# 7) Resumen Global
with tabs[6]:
    st.subheader("📊 Resumen Global de Señales")
    if df.empty:
        st.warning("⚠️ No hay datos aún.")
    else:
        ticker_counts = df["Ticker"].value_counts()
        result_counts = df["Resultado"].value_counts()
        total_ops = int(result_counts.sum())
        winrate = round((result_counts.get("Win", 0) / total_ops) * 100, 2) if total_ops else 0.0

        c1, c2, c3 = st.columns(3)
        c1.metric("Total de señales", len(df))
        c2.metric("Ganadas", int(result_counts.get("Win", 0)))
        c3.metric("Winrate (%)", f"{winrate}%")

        st.subheader("📌 Señales por Ticker")
        fig1, ax1 = plt.subplots()
        ticker_counts.plot(kind="bar", color="skyblue", ax=ax1)
        ax1.set_ylabel("Señales")
        st.pyplot(fig1)

        st.subheader("🏆 Distribución de Resultados")
        fig2, ax2 = plt.subplots()
        ordered = ["Win","Loss","-"]
        result_counts.reindex(ordered).fillna(0).plot(kind="bar", color=["green","red","gray"], ax=ax2)
        ax2.set_ylabel("Cantidad")
        st.pyplot(fig2)
