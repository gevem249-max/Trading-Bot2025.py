import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import os, json
import matplotlib.pyplot as plt
from streamlit_autorefresh import st_autorefresh

# ====================
# 🔄 Auto Refresh cada 60s
# ====================
st_autorefresh(interval=60 * 1000, key="refresh")

# ====================
# 🔑 Conexión Google Sheets
# ====================
SPREADSHEET_ID = st.secrets["SPREADSHEET_ID"]
google_json = st.secrets["GOOGLE_SHEETS_JSON"]

creds_info = json.loads(google_json)
creds = Credentials.from_service_account_info(
    creds_info, scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
client = gspread.authorize(creds)
sheet = client.open_by_key(SPREADSHEET_ID).sheet1

# ====================
# 📑 Leer datos
# ====================
def load_data():
    values = sheet.get_all_values()
    if not values:
        return pd.DataFrame()
    df = pd.DataFrame(values[1:], columns=values[0])  # primera fila = headers
    return df

# ====================
# 🎨 Interfaz
# ====================
st.set_page_config(page_title="Panel de Señales", layout="wide")
st.title("📊 Panel de Señales - Trading Bot 2025")

df = load_data()

if df.empty:
    st.warning("⚠️ No hay señales registradas aún en la hoja.")
else:
    # --------------------
    # 🎯 Filtros
    # --------------------
    activos = ["Todos"] + sorted(df["Ticker"].unique().tolist()) if "Ticker" in df.columns else ["Todos"]
    activo_sel = st.selectbox("Filtrar por activo", activos)

    dff = df.copy()
    if activo_sel != "Todos":
        dff = dff[dff["Ticker"] == activo_sel]

    # --------------------
    # 📑 Tabla
    # --------------------
    st.subheader("📑 Señales registradas")
    st.dataframe(dff, use_container_width=True)

    # --------------------
    # 📊 Resumen general
    # --------------------
    st.subheader("📈 Resumen general")
    total = len(dff)
    confirmadas = len(dff[dff["Estado"]=="Confirmada"])
    descartadas = len(dff[dff["Estado"]=="Descartada"])
    wins = len(dff[dff["Resultado"]=="Win"])
    losses = len(dff[dff["Resultado"]=="Loss"])

    st.markdown(f"""
    - 📩 **Total señales**: {total}  
    - ✅ **Confirmadas (≥80%)**: {confirmadas}  
    - ❌ **Descartadas (<80%)**: {descartadas}  
    - 🟢 **Ganadas**: {wins}  
    - 🔴 **Perdidas**: {losses}  
    """)

    # --------------------
    # 📊 Gráficos globales
    # --------------------
    col1, col2 = st.columns(2)

    with col1:
        if "Resultado" in dff.columns:
            resultados = dff["Resultado"].value_counts()
            if not resultados.empty:
                fig, ax = plt.subplots()
                resultados.plot(kind="bar", ax=ax, color=["green","red","gray"])
                ax.set_title(f"Resultados ({activo_sel})")
                ax.set_ylabel("Cantidad")
                st.pyplot(fig)

    with col2:
        if "ProbFinal" in dff.columns:
            try:
                dff["ProbFinal"] = pd.to_numeric(dff["ProbFinal"], errors="coerce")
                if not dff["ProbFinal"].dropna().empty:
                    fig2, ax2 = plt.subplots()
                    dff["ProbFinal"].hist(ax=ax2, bins=10, color="skyblue", edgecolor="black")
                    ax2.set_title(f"Distribución Probabilidades ({activo_sel})")
                    ax2.set_xlabel("Probabilidad (%)")
                    ax2.set_ylabel("Cantidad")
                    st.pyplot(fig2)
            except Exception as e:
                st.error(f"Error gráfico probabilidades: {e}")

    # --------------------
    # 📊 Resumenes por periodo (tabs)
    # --------------------
    if "FechaISO" in dff.columns:
        st.subheader("📆 Resúmenes por periodo")

        tab1, tab2, tab3 = st.tabs(["📅 Diario", "📈 Semanal", "📊 Mensual"])

        # ----- Diario -----
        with tab1:
            df_daily = dff.groupby("FechaISO").agg(
                total=("Ticker","count"),
                confirmadas=("Estado", lambda x: (x=="Confirmada").sum()),
                descartadas=("Estado", lambda x: (x=="Descartada").sum()),
                wins=("Resultado", lambda x: (x=="Win").sum()),
                losses=("Resultado", lambda x: (x=="Loss").sum()),
            ).reset_index()

            df_daily["winrate"] = df_daily.apply(
                lambda r: round((r["wins"]/max(1,r["wins"]+r["losses"]))*100,1), axis=1
            )

            st.dataframe(df_daily, use_container_width=True)

            fig3, ax3 = plt.subplots()
            ax3.plot(df_daily["FechaISO"], df_daily["winrate"], marker="o")
            ax3.set_title("Winrate diario (%)")
            ax3.set_xlabel("Fecha")
            ax3.set_ylabel("Winrate (%)")
            plt.xticks(rotation=45)
            st.pyplot(fig3)

        # ----- Semanal -----
        with tab2:
            dff["FechaISO"] = pd.to_datetime(dff["FechaISO"], errors="coerce")
            df_weekly = dff.groupby(dff["FechaISO"].dt.to_period("W")).agg(
                total=("Ticker","count"),
                confirmadas=("Estado", lambda x: (x=="Confirmada").sum()),
                descartadas=("Estado", lambda x: (x=="Descartada").sum()),
                wins=("Resultado", lambda x: (x=="Win").sum()),
                losses=("Resultado", lambda x: (x=="Loss").sum()),
            ).reset_index()

            df_weekly["winrate"] = df_weekly.apply(
                lambda r: round((r["wins"]/max(1,r["wins"]+r["losses"]))*100,1), axis=1
            )
            df_weekly["Semana"] = df_weekly["FechaISO"].astype(str)

            st.dataframe(df_weekly[["Semana","total","confirmadas","descartadas","wins","losses","winrate"]],
                         use_container_width=True)

            fig4, ax4 = plt.subplots()
            ax4.plot(df_weekly["Semana"], df_weekly["winrate"], marker="o")
            ax4.set_title("Winrate semanal (%)")
            ax4.set_xlabel("Semana")
            ax4.set_ylabel("Winrate (%)")
            plt.xticks(rotation=45)
            st.pyplot(fig4)

        # ----- Mensual -----
        with tab3:
            df_monthly = dff.groupby(dff["FechaISO"].dt.to_period("M")).agg(
                total=("Ticker","count"),
                confirmadas=("Estado", lambda x: (x=="Confirmada").sum()),
                descartadas=("Estado", lambda x: (x=="Descartada").sum()),
                wins=("Resultado", lambda x: (x=="Win").sum()),
                losses=("Resultado", lambda x: (x=="Loss").sum()),
            ).reset_index()

            df_monthly["winrate"] = df_monthly.apply(
                lambda r: round((r["wins"]/max(1,r["wins"]+r["losses"]))*100,1), axis=1
            )
            df_monthly["Mes"] = df_monthly["FechaISO"].astype(str)

            st.dataframe(df_monthly[["Mes","total","confirmadas","descartadas","wins","losses","winrate"]],
                         use_container_width=True)

            fig5, ax5 = plt.subplots()
            ax5.plot(df_monthly["Mes"], df_monthly["winrate"], marker="o")
            ax5.set_title("Winrate mensual (%)")
            ax5.set_xlabel("Mes")
            ax5.set_ylabel("Winrate (%)")
            plt.xticks(rotation=45)
            st.pyplot(fig5)
