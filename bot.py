# bot.py
import datetime

def ejecutar_bot():
    # Aquí va la lógica real de tu bot (trading, análisis, correos, etc.)
    ahora = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"Bot ejecutado correctamente a las {ahora}"

# Esto permite correrlo directo con: python bot.py
if __name__ == "__main__":
    print(ejecutar_bot())
