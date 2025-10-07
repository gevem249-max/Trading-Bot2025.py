# bot.py — Trading-Bot Full con Sniper + Confirmaciones + SL/TP + Logs + Threshold dinámico
import os, json, re, pytz, datetime as dt, smtplib, traceback
from email.mime.text import MIMEText
import pandas as pd, numpy as np, yfinance as yf, gspread
from google.oauth2.service_account import Credentials

# =========================
# 🔧 Configuración / env
# =========================
TZ = pytz.timezone("America/New_York")
MICRO_TICKERS = {"MES","MNQ","MYM","M2K","MGC","MCL","M6E","M6B","M6A"}
CRYPTO_TICKERS = {"BTCUSD","ETHUSD","SOLUSD","ADAUSD","XRPUSD"}
FOREX_RE = re.compile(r"^[A-Z]{6}$")

SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
GS_JSON = json.loads(os.getenv("GOOGLE_SHEETS_JSON", "{}"))
CREDS = Credentials.from_service_account_info(GS_JSON, scopes=["https://www.googleapis.com/auth/spreadsheets"])
GC = gspread.authorize(CREDS)
SHEET = GC.open_by_key(SPREADSHEET_ID).sheet1

# Gmail
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_PASS = os.getenv("GMAIL_APP_PASS")

# Routing de alertas
ALERT_DEFAULT = os.getenv("ALERT_DEFAULT", "gevem249@gmail.com")
ALERT_DKNG = os.getenv("ALERT_DKNG", "gevem249@gmail.com,adri_touma@hotmail.com")
ALERT_MICROS = os.getenv("ALERT_MICROS", "gevem249@gmail.com")

# =========================
# 🧭 Utils
# =========================
def now_et(): return dt.datetime.now(TZ)

def classify_market(ticker):
    t = ticker.upper().replace("/", "")
    if t in MICRO_TICKERS: return "cme_micro"
    if t in CRYPTO_TICKERS: return "crypto"
    if FOREX_RE.match(t): return "forex"
    return "equity"

# =========================
# 📬 Email
# =========================
def send_mail_many(subject, body, to_emails):
    if not to_emails or not GMAIL_USER or not GMAIL_PASS: return
    recipients = [e.strip() for e in to_emails.split(",") if e.strip()]
    if not recipients: return
    msg = MIMEText(body); msg["Subject"]=subject; msg["From"]=GMAIL_USER; msg["To"]=", ".join(recipients)
    with smtplib.SMTP_SSL("smtp.gmail.com",465) as srv:
        srv.login(GMAIL_USER,GMAIL_PASS); srv.sendmail(GMAIL_USER,recipients,msg.as_string())

# =========================
# 📈 Indicadores
# =========================
def ema(series, span): return series.ewm(span=span, adjust=False).mean()
def rsi(series, period=14):
    delta=series.diff(); up=np.where(delta>0,delta,0.0); down=np.where(delta<0,-delta,0.0)
    roll_up=pd.Series(up,index=series.index).rolling(period).mean()
    roll_down=pd.Series(down,index=series.index).rolling(period).mean()
    rs=roll_up/(roll_down+1e-9); return 100-(100/(1+rs))

def frame_prob(df, side):
    if df is None or df.empty: return 50.0
    close=df["Close"].squeeze(); e8,e21=ema(close,8),ema(close,21); r=rsi(close,14).fillna(50).iloc[-1]
    trend=(e8.iloc[-1]-e21.iloc[-1]); score=50.0
    if side.lower()=="buy":
        if trend>0: score+=20; 
        if 45<=r<=70: score+=15
        if r<35: score-=15
    else:
        if trend<0: score+=20
        if 30<=r<=55: score+=15
        if r>65: score-=15
    return max(0,min(100,score))

def fetch_yf(ticker, interval, lookback):
    y=ticker
    if ticker.upper()=="MES": y="^GSPC"
    if ticker.upper()=="MNQ": y="^NDX"
    if ticker.upper()=="MYM": y="^DJI"
    if ticker.upper()=="M2K": y="^RUT"
    try: return yf.download(y, period=lookback, interval=interval, progress=False, threads=False)
    except: return pd.DataFrame()

def prob_multi_frame(ticker, side):
    frames={"1m":("1m","2d"),"5m":("5m","5d"),"15m":("15m","1mo"),"1h":("60m","3mo")}
    probs={k:frame_prob(fetch_yf(t,itv,lb),side) for k,(itv,lb) in frames.items()}
    return {"per_frame":probs,"final":round(sum(probs.values())/len(probs),1)}

# =========================
# Sniper
# =========================
def sniper_score(ticker, side):
    df5=fetch_yf(ticker,"5m","5d"); base=frame_prob(df5,side) if not df5.empty else 50.0
    return {"score":base,"frame_probs":prob_multi_frame(ticker,side)}

# =========================
# Google Sheets helpers
# =========================
HEADERS=["FechaISO","HoraLocal","Ticker","Side","Entrada","ProbFinal","Estado","Resultado","SL","TP"]
def ensure_headers():
    vals=SHEET.get_all_values()
    if not vals: SHEET.append_row(HEADERS)

def append_signal(row):
    ensure_headers(); SHEET.append_row([row.get(h,"") for h in HEADERS])

# =========================
# Threshold dinámico
# =========================
def get_threshold():
    try:
        ws=GC.open_by_key(SPREADSHEET_ID).worksheet("calibration")
        vals=ws.get_all_records()
        if vals: return int(vals[-1].get("NuevoThreshold",80))
    except: return 80
    return 80

# =========================
# Core signal
# =========================
def process_signal(ticker, side, entry):
    t=now_et(); pm=prob_multi_frame(ticker,side); pf=pm["final"]; sn=sniper_score(ticker,side)
    sniper_val=sn["score"]; th=get_threshold()
    estado="Pre" if sniper_val>=th else "Descartada"
    sl, tp = entry*0.99, entry*1.01

    recipients=ALERT_DEFAULT
    if ticker.upper()=="DKNG": recipients=ALERT_DKNG
    elif ticker.upper() in MICRO_TICKERS: recipients=ALERT_MICROS

    row={"FechaISO":t.strftime("%Y-%m-%d"),"HoraLocal":t.strftime("%H:%M"),
         "Ticker":ticker,"Side":side,"Entrada":entry,"ProbFinal":pf,
         "Estado":estado,"Resultado":"-","SL":sl,"TP":tp}
    append_signal(row)

    subject=f"📊 Señal {ticker} {side} {entry} – {sniper_val}% (th={th})"
    body=f"{ticker} {side} @ {entry}\nProbFinal {pf}% | Estado: {estado}\nSL {sl} | TP {tp}"
    send_mail_many(subject,body,recipients)
    return row

# =========================
# Confirmaciones + resultados
# =========================
def check_pending():
    rows=SHEET.get_all_records(); now=now_et()
    for i,r in enumerate(rows,start=2):
        if r.get("Estado")=="Pre" and r.get("Resultado")=="-":
            pf2=prob_multi_frame(r["Ticker"],r["Side"])["final"]
            estado2="Confirmado" if pf2>=get_threshold() else "Cancelado"
            SHEET.update_cell(i,HEADERS.index("Estado")+1,estado2)

def check_outcomes():
    rows=SHEET.get_all_records()
    for i,r in enumerate(rows,start=2):
        if r.get("Estado") in ["Pre","Confirmado"] and r.get("Resultado")=="-":
            last=float(fetch_yf(r["Ticker"],"1m","1d")["Close"].iloc[-1])
            if r["Side"].lower()=="buy":
                if last<=float(r["SL"]): res="Loss"
                elif last>=float(r["TP"]): res="Win"
                else: continue
            else:
                if last>=float(r["SL"]): res="Loss"
                elif last<=float(r["TP"]): res="Win"
                else: continue
            SHEET.update_cell(i,HEADERS.index("Resultado")+1,res)

# =========================
# ▶️ Main
# =========================
def main():
    print("🚀 Bot activo"); 
    process_signal("DKNG","buy",30.0)
    check_pending(); check_outcomes()

if __name__=="__main__": main()
