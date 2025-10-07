import os, smtplib
from email.mime.text import MIMEText

user = os.getenv("GMAIL_USER")
pwd = os.getenv("GMAIL_APP_PASS")
to = os.getenv("ALERT_DEFAULT")

msg = MIMEText("✅ Prueba exitosa de GitHub Actions con Gmail")
msg["Subject"] = "Test GitHub Actions"
msg["From"] = user
msg["To"] = to

with smtplib.SMTP_SSL("smtp.gmail.com", 465) as srv:
    srv.login(user, pwd)
    srv.sendmail(user, [to], msg.as_string())
