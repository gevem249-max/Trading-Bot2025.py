import imaplib, email
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import os
import json

# ------------------------------------------------------
# 1. Conectar a Google Sheets
# ------------------------------------------------------
def conectar_sheets():
    # El JSON de credenciales lo guardas en Secrets como GOOGLE_SHEETS_JSON
    google_json = os.getenv("GOOGLE_SHEETS_JSON")
    if not google_json:
        raise Exception("No se encontró GOOGLE_SHEETS_JSON en secrets")

    creds_info = json.loads(google_json)
    scope = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(creds_info, scopes=scope)
    cliente = gspread.authorize(creds)

    # Cambia el nombre por tu hoja real
    sheet = cliente.open("SeñalesBot").sheet1
    return sheet

# ------------------------------------------------------
# 2. Leer correos de Gmail
# ------------------------------------------------------
def recibir_alertas():
    usuario = os.getenv("GMAIL_USER")       # tu correo Gmail (desde Secrets)
    clave = os.getenv("GMAIL_PASS")         # tu contraseña de aplicación

    if not usuario or not clave:
        raise Exception("Faltan credenciales de Gmail en secrets")

    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(usuario, clave)
    mail.select("inbox")

    # Buscar los últimos 20 correos
    status, mensajes = mail.search(None, "ALL")
    mensajes = mensajes[0].split()[-20:]

    alertas = []
    for num in mensajes:
        status, data = mail.fetch(num, "(RFC822)")
        msg = email.message_from_bytes(data[0][1])
        asunto = msg["subject"] or ""
        fecha = msg["date"]

        # Clasificación PRE / CONFIRM
        if "PRE" in asunto.upper():
            tipo = "PRE"
        elif "CONFIRM" in asunto.upper():
            tipo = "CONFIRM"
        else:
            tipo = "OTRO"

        alertas.append([fecha, asunto, tipo])

    df = pd.DataFrame(alertas, columns=["Fecha", "Asunto", "Tipo"])
    return df

# ------------------------------------------------------
# 3. Guardar señales en Google Sheets
# ------------------------------------------------------
def guardar_alertas_en_sheets(df):
    sheet = conectar_sheets()
    for _, row in df.iterrows():
        fecha = row["Fecha"]
        asunto = row["Asunto"]
        tipo = row["Tipo"]
        # Por defecto resultado "Pendiente"
        sheet.append_row([fecha, asunto, tipo, "Pendiente"])

# ------------------------------------------------------
# 4. Función principal del bot
# ------------------------------------------------------
def ejecutar_bot():
    df = recibir_alertas()
    guardar_alertas_en_sheets(df)
    return f"{len(df)} alertas procesadas y guardadas en Google Sheets"

# ------------------------------------------------------
# 5. Ejecutar directo si corres: python bot.py
# ------------------------------------------------------
if __name__ == "__main__":
    print(ejecutar_bot())
