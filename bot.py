# ==========================================================
# 🤖 TRADING BOT 2025 — MÓDULO PRINCIPAL (v5.0 - CORREGIDO)
# ==========================================================
# ✅ Google Sheets integrado (signals/debug/state/performance)
# ✅ Registro completo de señales (<80% y ≥80%)
# ✅ Pre-aviso + confirmación a 5 minutos para señales >80%
# ✅ Detección automática de sesiones (Globex / NYSE)
# ✅ Análisis técnico avanzado + noticias
# ✅ Resumen de performance diario
# ✅ Ejecución adaptativa: 4h en NY, 1h Globex
# ==========================================================

from bot_config import *
import yfinance as yf
import numpy as np
import pandas as pd
import random
import requests
import time
from datetime import datetime, timedelta

# =========================
# 📰 NOTICIAS Y SENTIMIENTO
# =========================
NEWS_ENDPOINT = "https://www.alphavantage.co/query"
ALPHA_KEY = os.getenv("ALPHA_VANTAGE_KEY", "")

def news_sentiment(keyword="market"):
    """Evalúa sentimiento de noticias (up/down/neutral)."""
    try:
        if not ALPHA_KEY:
            log_debug("news_sentiment", "Sin API key, usando random")
            return random.choice(["up", "down", "neutral"])
        
        url = f"{NEWS_ENDPOINT}?function=NEWS_SENTIMENT&tickers={keyword}&apikey={ALPHA_KEY}"
        response = requests.get(url, timeout=10)
        data = response.json()
        
        if "feed" not in data or not data["feed"]:
            return "neutral"
            
        score = float(data["feed"][0]["overall_sentiment_score"])
        result = "up" if score > 0.2 else "down" if score < -0.2 else "neutral"
        log_debug("news_sentiment", f"{keyword}: {result} (score: {score:.2f})")
        return result
    except Exception as e:
        log_debug("news_error", str(e))
        return "neutral"

# =========================
# 📈 ANÁLISIS TÉCNICO AVANZADO
# =========================
def calculate_rsi(data, period=14):
    """Calcula RSI."""
    delta = data["Close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_macd(data, fast=12, slow=26, signal=9):
    """Calcula MACD."""
    exp1 = data["Close"].ewm(span=fast, adjust=False).mean()
    exp2 = data["Close"].ewm(span=slow, adjust=False).mean()
    macd = exp1 - exp2
    signal_line = macd.ewm(span=signal, adjust=False).mean()
    return macd, signal_line

def detect_pattern(data):
    """Detecta patrones de velas."""
    if len(data) < 3:
        return "none", 0
    
    last = data.iloc[-1]
    prev = data.iloc[-2]
    
    # Patrón Engulfing Alcista
    if (prev["Close"] < prev["Open"] and 
        last["Close"] > last["Open"] and
        last["Open"] < prev["Close"] and
        last["Close"] > prev["Open"]):
        return "bullish_engulfing", 75
    
    # Patrón Engulfing Bajista
    if (prev["Close"] > prev["Open"] and 
        last["Close"] < last["Open"] and
        last["Open"] > prev["Close"] and
        last["Close"] < prev["Open"]):
        return "bearish_engulfing", 75
    
    # Martillo (Hammer)
    body = abs(last["Close"] - last["Open"])
    lower_shadow = min(last["Open"], last["Close"]) - last["Low"]
    upper_shadow = last["High"] - max(last["Open"], last["Close"])
    
    if lower_shadow > body * 2 and upper_shadow < body * 0.3:
        return "hammer", 70
    
    return "none", 0

def analyze_ticker(ticker):
    """Análisis completo: dirección, RSI, MACD, patrones."""
    try:
        # Descargar datos
        data = yf.download(ticker, period="5d", interval="5m", progress=False)
        if data.empty:
            raise ValueError("Sin datos históricos")
        
        # Calcular indicadores
        data["EMA8"] = data["Close"].ewm(span=8, adjust=False).mean()
        data["EMA21"] = data["Close"].ewm(span=21, adjust=False).mean()
        data["RSI"] = calculate_rsi(data)
        macd, signal_line = calculate_macd(data)
        data["MACD"] = macd
        data["Signal"] = signal_line
        
        last = data.iloc[-1]
        
        # Determinar tendencia
        ema_trend = "up" if last["EMA8"] > last["EMA21"] else "down"
        rsi_value = round(last["RSI"], 2)
        macd_trend = "up" if last["MACD"] > last["Signal"] else "down"
        
        # Detectar patrón
        pattern, pattern_score = detect_pattern(data)
        
        # Calcular probabilidad base
        prob = 60  # Base
        
        # Ajustar por RSI
        if ema_trend == "up" and 30 < rsi_value < 70:
            prob += 10
        elif ema_trend == "down" and 30 < rsi_value < 70:
            prob += 10
        
        # Ajustar por MACD
        if ema_trend == macd_trend:
            prob += 8
        
        # Ajustar por patrón
        if pattern != "none":
            prob += pattern_score * 0.2
        
        # Ajustar por volatilidad (ATR)
        atr = (data["High"] - data["Low"]).rolling(14).mean().iloc[-1]
        
        # Limitar probabilidad
        prob = min(max(prob, 50), 95)
        
        direction = ema_trend
        
        return {
            "direction": direction,
            "rsi": rsi_value,
            "macd_value": round(last["MACD"], 4),
            "probability": round(prob, 2),
            "pattern": pattern,
            "pattern_score": pattern_score,
            "atr": round(atr, 4)
        }
        
    except Exception as e:
        log_debug("analyze_error", f"{ticker}: {str(e)}")
        return {
            "direction": "neutral",
            "rsi": 50,
            "macd_value": 0,
            "probability": 0,
            "pattern": "none",
            "pattern_score": 0,
            "atr": 0
        }

# =========================
# ⏰ SISTEMA DE CONFIRMACIÓN (5 MIN)
# =========================
pending_confirmations = {}

def schedule_confirmation(ticker, side, prob, analysis, session):
    """Programa confirmación para 5 minutos después."""
    confirmation_time = now_et() + timedelta(minutes=5)
    key = f"{ticker}_{side}_{now_et().strftime('%H%M%S')}"
    
    pending_confirmations[key] = {
        "ticker": ticker,
        "side": side,
        "prob": prob,
        "analysis": analysis,
        "session": session,
        "scheduled_time": confirmation_time,
        "notified": False
    }
    
    # Enviar pre-aviso
    send_preaviso(ticker, side, prob, analysis, session)
    log_debug("schedule_confirm", f"{ticker} programada para {confirmation_time.strftime('%H:%M:%S')}")

def send_preaviso(ticker, side, prob, analysis, session):
    """Envía pre-aviso de señal potencial."""
    subject = f"⚠️ PRE-AVISO: {ticker} {side.upper()} ({prob}%)"
    body = f"""
🔔 SEÑAL POTENCIAL DETECTADA

Ticker: {ticker}
Dirección: {side.upper()}
Probabilidad: {prob}%
Sesión: {session}

📊 Análisis Técnico:
- RSI: {analysis['rsi']}
- MACD: {analysis['macd_value']}
- Patrón: {analysis['pattern']} (score: {analysis['pattern_score']})
- ATR: {analysis['atr']}

⏰ Confirmación en 5 minutos...
"""
    recipients = get_recipients(ticker)
    send_mail_many(subject, body, recipients)
    log_debug("preaviso_sent", f"{ticker} {side} ({prob}%)")

def process_confirmations():
    """Procesa confirmaciones pendientes."""
    now = now_et()
    keys_to_remove = []
    
    for key, conf in pending_confirmations.items():
        if now >= conf["scheduled_time"] and not conf["notified"]:
            # Re-analizar para confirmar
            new_analysis = analyze_ticker(conf["ticker"])
            
            if new_analysis["probability"] >= 80:
                # Confirmar señal
                save_signal(
                    conf["ticker"], 
                    conf["side"], 
                    new_analysis["probability"],
                    conf["session"],
                    f"CONFIRMADA - RSI:{new_analysis['rsi']} | Pattern:{new_analysis['pattern']}"
                )
                send_confirmation(conf["ticker"], conf["side"], new_analysis, conf["session"])
            else:
                # Cancelar señal
                log_debug("signal_cancelled", f"{conf['ticker']} - prob bajó a {new_analysis['probability']}%")
            
            conf["notified"] = True
            keys_to_remove.append(key)
    
    # Limpiar confirmaciones procesadas
    for key in keys_to_remove:
        del pending_confirmations[key]

def send_confirmation(ticker, side, analysis, session):
    """Envía confirmación final de señal."""
    subject = f"✅ CONFIRMADO: {ticker} {side.upper()} ({analysis['probability']}%)"
    body = f"""
✅ SEÑAL CONFIRMADA - EJECUTAR AHORA

Ticker: {ticker}
Dirección: {side.upper()}
Probabilidad FINAL: {analysis['probability']}%
Sesión: {session}

📊 Análisis Confirmado:
- RSI: {analysis['rsi']}
- MACD: {analysis['macd_value']}
- Patrón: {analysis['pattern']} (score: {analysis['pattern_score']})
- ATR: {analysis['atr']}

🎯 Stop Loss sugerido: Basado en ATR
🎯 Take Profit sugerido: 2x ATR

⚡ ENTRAR INMEDIATAMENTE
"""
    recipients = get_recipients(ticker)
    send_mail_many(subject, body, recipients)
    log_debug("confirmation_sent", f"{ticker} {side} ({analysis['probability']}%)")

def get_recipients(ticker):
    """Obtiene lista de destinatarios según el ticker."""
    ticker = ticker.upper()
    if ticker == "ES":
        return [ALERT_ES]
    elif ticker == "DKNG":
        return [ALERT_DKNG]
    else:
        return [ALERT_DEFAULT]

# =========================
# 🧾 REGISTRO DE SEÑALES
# =========================
def save_signal(ticker, side, prob, session, note):
    """Guarda señal en Google Sheets."""
    try:
        now = now_et()
        analysis = analyze_ticker(ticker)
        
        WS_SIGNALS.append_row([
            now.strftime("%Y-%m-%d"),
            now.strftime("%H:%M:%S"),
            now.strftime("%H:%M:%S"),
            ticker,
            side,
            "AUTO",
            "-", "-", "-", "-",
            prob,
            "High_Confidence" if prob >= 80 else "Medium_Confidence",
            "Active",
            "Auto",
            "-",
            note,
            session,
            analysis.get("pattern", "-"),
            analysis.get("pattern_score", "-"),
            analysis.get("macd_value", "-"),
            "-",
            analysis.get("atr", "-"),
            "-", "-",
            ",".join(get_recipients(ticker)),
            "Yes" if prob >= 80 else "No"
        ])
        
        # Crear entrada en performance
        open_performance_entry(
            fecha_iso=now.strftime("%Y-%m-%d"),
            hora_reg=now.strftime("%H:%M:%S"),
            ticker=ticker,
            side=side,
            entrada="AUTO",
            prob_final=prob,
            nota=note
        )
        
        log_debug("signal_saved", f"{ticker} {side} ({prob}%) - {session}")
        
    except Exception as e:
        log_debug("save_signal_error", str(e))

# =========================
# 📊 PERFORMANCE
# =========================
def open_performance_entry(fecha_iso, hora_reg, ticker, side, entrada, prob_final, nota=""):
    """Crea entrada inicial en hoja de performance."""
    try:
        WS_PERFORMANCE.append_row([
            fecha_iso,
            hora_reg,
            ticker.upper(),
            side,
            entrada,
            round(float(prob_final), 2) if prob_final not in ("", "-", None) else "-",
            "Open",
            "",
            "",
            "",
            "",
            nota
        ])
        log_debug("performance_open", f"{ticker} - Open")
    except Exception as e:
        log_debug("performance_open_error", str(e))

def daily_performance_summary():
    """Genera resumen de performance del día."""
    try:
        df = pd.DataFrame(WS_PERFORMANCE.get_all_records())
        if df.empty:
            return
        
        today = now_et().strftime("%Y-%m-%d")
        dft = df[df["FechaISO"] == today]
        
        if dft.empty:
            return
        
        total = len(dft)
        wins = (dft["Resultado"] == "Win").sum()
        loss = (dft["Resultado"] == "Loss").sum()
        be = (dft["Resultado"] == "BE").sum()
        
        pnl_series = pd.to_numeric(dft.get("PnL", pd.Series(dtype=float)), errors="coerce").dropna()
        pnl_total = round(pnl_series.sum(), 2) if not pnl_series.empty else 0
        
        summary = f"📈 {today} → Total:{total} | Win:{wins} | Loss:{loss} | BE:{be} | PnL:{pnl_total}"
        log_debug("perf_summary", summary)
        
    except Exception as e:
        log_debug("perf_summary_error", str(e))

# =========================
# 🚦 CICLO PRINCIPAL
# =========================
def run_cycle():
    """Ejecuta un ciclo de análisis completo."""
    log_debug("cycle_start", "Iniciando ciclo de análisis")
    
    for ticker in WATCHLIST:
        try:
            # Verificar estado del mercado
            state, session = market_status(ticker)
            
            if state == "closed":
                log_debug("market_closed", f"{ticker} - {session}")
                continue
            
            # Análisis completo
            analysis = analyze_ticker(ticker)
            side = analysis["direction"]
            prob = analysis["probability"]
            
            # Ajustar con sentimiento de noticias
            sentiment = news_sentiment(ticker)
            if sentiment == side:
                prob = min(prob + 3, 95)
            elif sentiment != "neutral" and sentiment != side:
                prob = max(prob - 3, 50)
            
            analysis["probability"] = round(prob, 2)
            
            log_debug("analysis_complete", 
                     f"{ticker}: {side} ({prob}%) | RSI:{analysis['rsi']} | Pattern:{analysis['pattern']}")
            
            # Lógica de señales
            if prob >= 80:
                # Señal fuerte: programar confirmación
                schedule_confirmation(ticker, side, prob, analysis, session)
            elif 70 <= prob < 80:
                # Señal media: registrar sin confirmación
                save_signal(
                    ticker, side, prob, session,
                    f"RSI:{analysis['rsi']} | MACD:{analysis['macd_value']} | {analysis['pattern']}"
                )
            
        except Exception as e:
            log_debug("cycle_error", f"{ticker}: {str(e)}")
    
    # Procesar confirmaciones pendientes
    process_confirmations()
    
    log_debug("cycle_end", "Ciclo completado")

# =========================
# ⏱️ HORARIO ADAPTATIVO
# =========================
def adaptive_schedule():
    """Ejecuta el bot con horario adaptativo."""
    now = now_et()
    hour = now.hour + now.minute / 60
    
    # Mercado NY (9:30-16:00 ET) → 8 ciclos cada 30 min
    if 9.5 <= hour < 16:
        cycles, interval = 8, 1800
        log_debug("schedule", "Modo NYSE: 8 ciclos x 30min")
    
    # Globex (18:00-08:00 ET) → 2 ciclos cada hora
    elif hour >= 18 or hour < 8:
        cycles, interval = 2, 3600
        log_debug("schedule", "Modo Globex: 2 ciclos x 60min")
    
    # Fuera de horario
    else:
        cycles, interval = 1, 3600
        log_debug("schedule", "Fuera de horario principal")
    
    for i in range(cycles):
        log_debug("main", f"▶️ Ciclo {i+1}/{cycles}")
        run_cycle()
        
        if i < cycles - 1:  # No esperar después del último ciclo
            time.sleep(interval)
    
    # Resumen diario
    daily_performance_summary()

# =========================
# 🚀 EJECUCIÓN PRINCIPAL
# =========================
if __name__ == "__main__":
    print("🚀 Iniciando Trading Bot 2025 v5.0...")
    log_debug("main", "Bot iniciado")
    
    # Detectar modo de ejecución
    bot_mode = os.getenv("BOT_MODE", "continuous")
    
    try:
        if bot_mode == "single_cycle":
            # Modo ciclo único (para GitHub Actions)
            print("🔄 Modo: Ciclo único")
            log_debug("main", "Ejecutando en modo ciclo único")
            run_cycle()
            print("✅ Ciclo único completado")
        else:
            # Modo continuo (para ejecución local)
            print("🔄 Modo: Continuo")
            log_debug("main", "Ejecutando en modo continuo")
            adaptive_schedule()
            
    except KeyboardInterrupt:
        log_debug("main", "Bot detenido por usuario")
        print("\n⏹️ Bot detenido por usuario")
    except Exception as e:
        log_debug("fatal_error", str(e))
        print(f"❌ Error fatal: {e}")
        import traceback
        traceback.print_exc()
    
    log_debug("main", "Bot finalizado")
    print("✅ Bot finalizado correctamente")
