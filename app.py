import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import json, os
import matplotlib.pyplot as plt
from streamlit_autorefresh import st_autorefresh
import datetime as dt
import pytz

# =============================
# 🔄 Auto-refresh cada 60 segundos
# =============================
st_autorefresh(interval=60 * 1000, key="refresh")

# =============================
# 🔧 Config
# =============================
TZ = pytz.timezone("America/New_York")  # ET/NJ
def now_et():
    return dt.datetime.now(TZ)

def is_market_open(market: str, t: dt.datetime) -> bool:
    wd = t.weekday()
    h, m = t.hour, t.minute
    if market == "equity":
        if wd >= 5: return False
        return (h*60+m) >= (9*60+30) and (h*60+m) < (16*60)
    if market == "cme_micro":
        if wd == 5: return False
        if wd == 6 and h < 18: return False
        if wd == 4 and h >= 17: return False
        if h == 17: return False
        return True
    if market == "forex":
        if wd == 5: return False
        if wd == 6 and h < 17: return False
        if wd == 4 and h >= 17: return False
        return True
    if market == "crypto":
        return True
    return False

# =============================
# 🔑 Conexión con Google Sheets
# =============================
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
GS_JSON = json.loads(os.getenv("GOOGLE_SHEETS_JSON"))
CREDS = Credentials.from_service_account_info(GS_JSON, scopes=["https://www.googleapis.com/auth/spreadsheets"])
GC = gspread.authorize(CREDS)
SHEET = GC.open_by_key(SPREADSHEET_ID).sheet1

# =============================
# 📥 Cargar datos
# =============================
def load_data():
    values = SHEET.get_all_records()
    if not values:
        return pd.DataFrame()
    return pd.DataFrame(values)

df = load_data()

# =============================
# 🔔 Alerta sonora si hay nueva confirmada
# =============================
if "last_count" not in st.session_state:
    st.session_state["last_count"] = 0

current_count = len(df[df["Estado"]=="Confirmada"]) if not df.empty else 0

if current_count > st.session_state["last_count"]:
    st.markdown(
        """
        <audio autoplay>
            <source src="https://actions.google.com/sounds/v1/alarms/beep_short.ogg" type="audio/ogg">
        </audio>
        """,
        unsafe_allow_html=True
    )

st.session_state["last_count"] = current_count

# =============================
# 🟢 Encabezado de estado
# =============================
st.title("📊 Panel de Señales - Trading Bot 2025")

col1, col2 = st.columns(2)

with col1:
    st.success("🤖 Bot Activo – corriendo en tiempo real")
    st.markdown(f"🕒 **Hora local (NJ/ET):** {now_et().strftime('%Y-%m-%d %H:%M:%S')}")

with col2:
    t = now_et()
    estados = []
    for mkt in ["equity","cme_micro","forex","crypto"]:
        if is_market_open(mkt, t):
            estados.append(f"🟢 {mkt.upper()} abierto")
        else:
            estados.append(f"🔴 {mkt.upper()} cerrado")
    st.markdown("**Mercados ahora:**<br>" + "<br>".join(estados), unsafe_allow_html=True)

# =============================
# 📌 Expander por TICKER
# =============================
if not df.empty and "Ticker" in df.columns:
    with st.expander("📌 Activos en seguimiento (por ticker)"):
        st.markdown("Resumen de señales por activo:")

        activos = df["Ticker"].unique().tolist()
        for i in range(0, len(activos), 3):
            cols = st.columns(3)
            for j, ticker in enumerate(activos[i:i+3]):
                with cols[j]:
                    subdf = df[df["Ticker"] == ticker]
                    total = len(subdf)
                    wins = (subdf["Resultado"] == "Win").sum()
                    losses = (subdf["Resultado"] == "Loss").sum()
                    descartadas = (subdf["Estado"] == "Descartada").sum()

                    st.markdown(f"### 📍 {ticker}")
                    st.caption(f"Total: {total} | ✅ {wins} | ❌ {losses} | 🚫 {descartadas}")

                    # Mini gráfico
                    fig, ax = plt.subplots(figsize=(2.8,2.5))
                    valores = [wins, losses, descartadas]
                    labels = ["✅","❌","🚫"]
                    colores = ["green","red","blue"]

                    bars = ax.bar(labels, valores, color=colores)
                    for bar, val in zip(bars, valores):
                        if total > 0:
                            pct = (val/total)*100
                            ax.text(
                                bar.get_x() + bar.get_width()/2,
                                bar.get_height() + 0.05,
                                f"{pct:.0f}%",
                                ha="center", va="bottom", fontsize=8, fontweight="bold"
                            )
                    ax.set_ylim(0, max(1, max(valores)))  
                    st.pyplot(fig)

# =============================
# 📊 Panel principal con Tabs
# =============================
if df.empty:
    st.warning("⚠️ No hay señales registradas aún en la hoja.")
else:
    tabs = st.tabs([
        "✅ Señales Enviadas", 
        "❌ Descartadas", 
        "📈 Resultados Hoy", 
        "📊 Histórico", 
        "📉 Distribución Probabilidades", 
        "🕒 Últimas Señales"
    ])

    # --- Tab 1: Señales Enviadas
    with tabs[0]:
        enviadas = df[df["ProbFinal"] >= 80]
        if enviadas.empty:
            st.info("No hay señales enviadas aún.")
        else:
            st.dataframe(enviadas)

    # --- Tab 2: Señales Descartadas
    with tabs[1]:
        descartadas = df[df["ProbFinal"] < 80]
        if descartadas.empty:
            st.info("No hay señales descartadas aún.")
        else:
            st.dataframe(descartadas)

    # --- Tab 3: Resultados HOY
    with tabs[2]:
        hoy = dt.date.today().isoformat()
        df_hoy = df[df["FechaISO"] == hoy] if "FechaISO" in df.columns else df.copy()
        if df_hoy.empty:
            st.info("Todavía no hay señales registradas hoy.")
        else:
            resultados = df_hoy["Resultado"].value_counts()
            st.bar_chart(resultados)

            total = len(df_hoy[df_hoy["Estado"] == "Confirmada"])
            wins = (df_hoy["Resultado"] == "Win").sum()
            losses = (df_hoy["Resultado"] == "Loss").sum()
            descartadas = (df_hoy["Estado"] == "Descartada").sum()

            st.markdown(f"""
            ### 📋 Resumen HOY
            - Confirmadas: {total}  
            - ✅ Wins: {wins}  
            - ❌ Losses: {losses}  
            - 🚫 Descartadas: {descartadas}  
            """)

    # --- Tab 4: Histórico
    with tabs[3]:
        if "Resultado" in df.columns and "FechaISO" in df.columns:
            # Totales
            total_h = len(df[df["Estado"] == "Confirmada"])
            wins_h = (df["Resultado"] == "Win").sum()
            losses_h = (df["Resultado"] == "Loss").sum()
            descartadas_h = (df["Estado"] == "Descartada").sum()

            st.markdown(f"""
            ### 📋 Resumen Histórico
            - Confirmadas: {total_h}  
            - ✅ Wins: {wins_h}  
            - ❌ Losses: {losses_h}  
            - 🚫 Descartadas: {descartadas_h}  
            """)

            # Evolución acumulada
            df["FechaISO"] = pd.to_datetime(df["FechaISO"], errors="coerce")
            df_daily = df.groupby("FechaISO").agg(
                wins=("Resultado", lambda x: (x=="Win").sum()),
                losses=("Resultado", lambda x: (x=="Loss").sum())
            ).cumsum().reset_index()
            df_daily["winrate"] = df_daily.apply(lambda r: (r["wins"]/max(1, r["wins"]+r["losses"]))*100, axis=1)

            st.subheader("📈 Evolución acumulada")
            fig, ax = plt.subplots()
            ax.plot(df_daily["FechaISO"], df_daily["wins"], marker="o", label="Wins", color="green")
            ax.plot(df_daily["FechaISO"], df_daily["losses"], marker="o", label="Losses", color="red")
            ax2 = ax.twinx()
            ax2.plot(df_daily["FechaISO"], df_daily["winrate"], marker="x", linestyle="--", label="Winrate %", color="blue")
            ax.legend(loc="upper left"); ax2.legend(loc="upper right")
            st.pyplot(fig)

            # 📌 Expander por mercado
            with st.expander("📊 Resumen por MERCADO"):
                mercados = df["Mercado"].unique().tolist() if "Mercado" in df.columns else []
                for i in range(0, len(mercados), 2):
                    cols = st.columns(2)
                    for j, mkt in enumerate(mercados[i:i+2]):
                        with cols[j]:
                            subdf = df[df["Mercado"] == mkt]
                            total = len(subdf)
                            wins = (subdf["Resultado"] == "Win").sum()
                            losses = (subdf["Resultado"] == "Loss").sum()
                            descartadas = (subdf["Estado"] == "Descartada").sum()

                            st.markdown(f"### 🌐 {mkt.upper()}")
                            st.caption(f"Total: {total} | ✅ {wins} | ❌ {losses} | 🚫 {descartadas}")

                            fig, ax = plt.subplots(figsize=(3,2.5))
                            valores = [wins, losses, descartadas]
                            labels = ["✅","❌","🚫"]
                            colores = ["green","red","blue"]

                            bars = ax.bar(labels, valores, color=colores)
                            for bar, val in zip(bars, valores):
                                if total > 0:
                                    pct = (val/total)*100
                                    ax.text(bar.get_x()+bar.get_width()/2, bar.get_height()+0.05,
                                            f"{pct:.0f}%", ha="center", va="bottom", fontsize=8, fontweight="bold")
                            ax.set_ylim(0, max(1, max(valores)))
                            st.pyplot(fig)

    # --- Tab 5: Distribución Probabilidades
    with tabs[4]:
        if "ProbFinal" in df.columns:
            fig, ax = plt.subplots()
            df["ProbFinal"].hist(bins=10, ax=ax, color="skyblue", edgecolor="black")
            ax.set_xlabel("Probabilidad Final (%)")
            ax.set_ylabel("Número de Señales")
            st.pyplot(fig)

    # --- Tab 6: Últimas Señales
    with tabs[5]:
        st.dataframe(df.tail(10))
