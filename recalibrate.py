# ==========================================================
# 🔧 RECALIBRATE.PY — Script de Recalibración (v2.0 Corregido)
# ==========================================================
# ✅ Usa las mismas variables de entorno que bot.py
# ✅ Analiza resultados históricos
# ✅ Calcula métricas de performance
# ✅ Ajusta umbrales automáticamente
# ==========================================================

import os
import json
import datetime as dt
import pandas as pd
import numpy as np
import gspread
from google.oauth2.service_account import Credentials
import yfinance as yf

# =========================
# 🔐 CONFIGURACIÓN
# =========================
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")  # ✅ Mismo nombre que bot.py

if not SPREADSHEET_ID or not GOOGLE_CREDS_JSON:
    raise ValueError("❌ Faltan variables de entorno: SPREADSHEET_ID o GOOGLE_CREDS_JSON")

# Cargar credenciales
try:
    creds_data = json.loads(GOOGLE_CREDS_JSON)
    
    # Auto-fix del private_key
    if "\\n" in creds_data.get("private_key", ""):
        creds_data["private_key"] = creds_data["private_key"].replace("\\n", "\n")
    
except json.JSONDecodeError as e:
    raise ValueError(f"❌ Error al decodificar GOOGLE_CREDS_JSON: {e}")

# Scopes
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

# Autenticación
try:
    CREDS = Credentials.from_service_account_info(creds_data, scopes=SCOPES)
    GC = gspread.authorize(CREDS)
    SHEET = GC.open_by_key(SPREADSHEET_ID)
    print(f"✅ Conectado a: {SHEET.title}")
except Exception as e:
    raise RuntimeError(f"❌ Error conectando a Google Sheets: {e}")

# =========================
# 🧾 OBTENER HOJAS
# =========================
try:
    WS_PERFORMANCE = SHEET.worksheet("performance")
    print("✅ Hoja 'performance' encontrada")
except gspread.WorksheetNotFound:
    print("⚠️ Hoja 'performance' no existe. Creándola...")
    WS_PERFORMANCE = SHEET.add_worksheet("performance", rows=1000, cols=11)
    WS_PERFORMANCE.update("A1", [[
        "FechaISO", "HoraRegistro", "Ticker", "Side", "Entrada",
        "ProbFinal", "Resultado", "PnL", "ExitISO", "ExitHora", "Notas"
    ]])

try:
    WS_DEBUG = SHEET.worksheet("debug")
except gspread.WorksheetNotFound:
    WS_DEBUG = SHEET.add_worksheet("debug", rows=1000, cols=3)
    WS_DEBUG.update("A1", [["Fecha", "Hora", "Mensaje"]])

try:
    WS_CALIBRATION = SHEET.worksheet("calibration")
except gspread.WorksheetNotFound:
    WS_CALIBRATION = SHEET.add_worksheet("calibration", rows=100, cols=6)
    WS_CALIBRATION.update("A1", [[
        "Fecha", "Winrate", "AvgWinProb", "AvgLossProb", "SniperRate", "NuevoThreshold"
    ]])

# =========================
# 📝 LOG
# =========================
def log_debug(message):
    """Registra mensaje en hoja debug."""
    try:
        now = dt.datetime.now()
        WS_DEBUG.append_row([
            now.strftime("%Y-%m-%d"),
            now.strftime("%H:%M:%S"),
            f"[recalibrate] {message}"
        ])
        print(f"📝 {message}")
    except Exception as e:
        print(f"⚠️ Error guardando log: {e}")

# =========================
# 🔄 MAPEO DE TICKERS
# =========================
def map_ticker_yf(ticker):
    """Mapea tickers a símbolos de Yahoo Finance."""
    mapping = {
        "ES": "^GSPC",
        "NQ": "^NDX",
        "YM": "^DJI",
        "RTY": "^RUT",
        "MES": "^GSPC",
        "MNQ": "^NDX",
        "MYM": "^DJI",
        "M2K": "^RUT",
        "BTCUSD": "BTC-USD",
        "ETHUSD": "ETH-USD",
        "SOLUSD": "SOL-USD",
        "ADAUSD": "ADA-USD",
        "XRPUSD": "XRP-USD"
    }
    return mapping.get(ticker.upper(), ticker.upper())

# =========================
# 📊 INDICADORES TÉCNICOS
# =========================
def ema(series, span):
    """Calcula EMA."""
    return series.ewm(span=span, adjust=False).mean()

def rsi(series, period=14):
    """Calcula RSI."""
    delta = series.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = -delta.where(delta < 0, 0).rolling(period).mean()
    rs = gain / (loss + 1e-9)
    return 100 - (100 / (1 + rs))

def macd(series, fast=12, slow=26, signal=9):
    """Calcula MACD."""
    exp1 = series.ewm(span=fast, adjust=False).mean()
    exp2 = series.ewm(span=slow, adjust=False).mean()
    macd_line = exp1 - exp2
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line

# =========================
# 🎯 ANÁLISIS SNIPER
# =========================
def analyze_sniper_rate(tickers):
    """
    Analiza tasa de éxito del sistema Sniper:
    - EMA8 > EMA21
    - RSI > 50
    - MACD > Signal
    """
    sniper_hits = 0
    sniper_miss = 0
    
    for ticker in tickers:
        try:
            yf_ticker = map_ticker_yf(ticker)
            data = yf.download(yf_ticker, period="5d", interval="5m", progress=False)
            
            if data.empty:
                log_debug(f"⚠️ Sin datos para {ticker}")
                continue
            
            close = data["Close"]
            
            # Calcular indicadores
            e8 = ema(close, 8)
            e21 = ema(close, 21)
            rsi_val = rsi(close).iloc[-1]
            macd_line, signal_line = macd(close)
            
            # Condiciones Sniper
            ema_ok = e8.iloc[-1] > e21.iloc[-1]
            rsi_ok = rsi_val > 50
            macd_ok = macd_line.iloc[-1] > signal_line.iloc[-1]
            
            sniper_ok = ema_ok and rsi_ok and macd_ok
            
            if sniper_ok:
                sniper_hits += 1
            else:
                sniper_miss += 1
            
            log_debug(f"{ticker}: EMA={ema_ok} RSI={rsi_ok} MACD={macd_ok} → {'✅' if sniper_ok else '❌'}")
            
        except Exception as e:
            log_debug(f"⚠️ Error analizando {ticker}: {e}")
    
    total = sniper_hits + sniper_miss
    sniper_rate = round((sniper_hits / total) * 100, 2) if total > 0 else 0
    
    log_debug(f"📈 Sniper Rate: {sniper_rate}% ({sniper_hits}/{total})")
    return sniper_rate

# =========================
# 🔧 RECALIBRACIÓN PRINCIPAL
# =========================
def recalibrate():
    """Ejecuta el proceso de recalibración completo."""
    log_debug("🔧 Iniciando recalibración...")
    
    try:
        # Leer datos de performance
        vals = WS_PERFORMANCE.get_all_records()
        
        if not vals:
            log_debug("⚠️ No hay datos en 'performance'. Nada que recalibrar.")
            return
        
        df = pd.DataFrame(vals)
        
        # Filtrar solo Win/Loss
        df = df[df["Resultado"].isin(["Win", "Loss"])]
        
        if df.empty:
            log_debug("⚠️ No hay suficientes resultados (Win/Loss) para recalibrar.")
            return
        
        # =========================
        # 📊 MÉTRICAS BÁSICAS
        # =========================
        total = len(df)
        wins = (df["Resultado"] == "Win").sum()
        losses = (df["Resultado"] == "Loss").sum()
        winrate = round((wins / total) * 100, 2)
        
        log_debug(f"📊 Total operaciones: {total}")
        log_debug(f"✅ Wins: {wins} ({winrate}%)")
        log_debug(f"❌ Losses: {losses}")
        
        # =========================
        # 📈 PROBABILIDADES
        # =========================
        # Convertir ProbFinal a numérico
        df["ProbFinal"] = pd.to_numeric(df["ProbFinal"], errors="coerce")
        
        avg_win_prob = df[df["Resultado"] == "Win"]["ProbFinal"].mean()
        avg_loss_prob = df[df["Resultado"] == "Loss"]["ProbFinal"].mean()
        
        avg_win_prob = round(avg_win_prob, 2) if not pd.isna(avg_win_prob) else 0
        avg_loss_prob = round(avg_loss_prob, 2) if not pd.isna(avg_loss_prob) else 0
        
        log_debug(f"📈 Prob promedio (Win): {avg_win_prob}%")
        log_debug(f"📉 Prob promedio (Loss): {avg_loss_prob}%")
        
        # =========================
        # 🎯 SNIPER RATE
        # =========================
        unique_tickers = df["Ticker"].unique().tolist()
        sniper_rate = analyze_sniper_rate(unique_tickers)
        
        # =========================
        # 🔧 NUEVO THRESHOLD
        # =========================
        # Ajustar threshold basado en promedio de wins
        if avg_win_prob > 0:
            new_threshold = max(70, min(90, int(avg_win_prob)))
        else:
            new_threshold = 80
        
        log_debug(f"🎯 Nuevo threshold sugerido: {new_threshold}%")
        
        # =========================
        # 💾 GUARDAR RESULTADOS
        # =========================
        now = dt.datetime.now().isoformat()
        
        WS_CALIBRATION.append_row([
            now,
            winrate,
            avg_win_prob,
            avg_loss_prob,
            sniper_rate,
            new_threshold
        ])
        
        log_debug("✅ Recalibración completada y guardada en 'calibration'")
        
        # =========================
        # 📊 RESUMEN
        # =========================
        print("\n" + "="*60)
        print("📊 RESUMEN DE RECALIBRACIÓN")
        print("="*60)
        print(f"Fecha: {now}")
        print(f"Total operaciones: {total}")
        print(f"Winrate: {winrate}%")
        print(f"Probabilidad promedio (Win): {avg_win_prob}%")
        print(f"Probabilidad promedio (Loss): {avg_loss_prob}%")
        print(f"Sniper Rate: {sniper_rate}%")
        print(f"Nuevo threshold: {new_threshold}%")
        print("="*60 + "\n")
        
    except Exception as e:
        log_debug(f"❌ Error en recalibración: {e}")
        raise

# =========================
# 🚀 EJECUCIÓN
# =========================
if __name__ == "__main__":
    print("\n🚀 Iniciando script de recalibración...")
    
    try:
        recalibrate()
        print("✅ Recalibración completada correctamente")
    except Exception as e:
        print(f"❌ Error fatal: {e}")
        log_debug(f"Fatal error: {e}")
    
    print("🏁 Script finalizado\n")
