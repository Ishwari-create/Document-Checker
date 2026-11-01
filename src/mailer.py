"""
Sends the confirmed deficiency letter to the institute by email, with the PDF attached.

Configure with environment variables:
    SMTP_HOST, SMTP_PORT (587 = STARTTLS, 465 = SSL), SMTP_USER, SMTP_PASSWORD, MAIL_FROM
Without SMTP_HOST the message is written to data/outbox/ as a .eml file (opens in
Outlook / Thunderbird), so the demo works offline and nothing is sent by accident.
"""
from __future__ import annotations

import os
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Dict

OUTBOX = Path(__file__).resolve().parent.parent / "data" / "outbox"


def smtp_configured() -> bool:
    return bool(os.environ.get("SMTP_HOST"))


def send_letter(to: str, subject: str, body: str, pdf: bytes, filename: str, cc: str = "") -> Dict[str, str]:
    msg = EmailMessage()
    msg["From"] = os.environ.get("MAIL_FROM", "scrutiny-desk@regional-office.example.in")
    msg["To"] = to
    if cc:
        msg["Cc"] = cc
    msg["Subject"] = subject
    msg["Date"] = datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0530")
    msg.set_content(body)
    msg.add_attachment(pdf, maintype="application", subtype="pdf", filename=filename)
    at = datetime.now().isoformat(timespec="seconds")
    if not smtp_configured():
        OUTBOX.mkdir(parents=True, exist_ok=True)
        path = OUTBOX / f"{datetime.now():%Y%m%d-%H%M%S}-{filename.replace('.pdf', '')}.eml"
        path.write_bytes(bytes(msg))
        return {"status": "saved", "to": to, "at": at, "where": str(path),
                "note": "SMTP is not configured, so the email was saved to the outbox instead of being sent."}
    host, port = os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587"))
    user, pwd = os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASSWORD")
    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=20) as s:
            if user:
                s.login(user, pwd)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=20) as s:
            s.starttls(context=ctx)
            if user:
                s.login(user, pwd)
            s.send_message(msg)
    return {"status": "sent", "to": to, "at": at, "where": host, "note": "Email sent."}
