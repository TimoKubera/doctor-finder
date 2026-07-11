"""providers.py - austauschbare Versand-Backends.

- SmtpProvider (Standard): Versand ueber das eigene Postfach. Die Zugangsdaten
  (E-Mail + Passwort/App-Passwort) werden zur Laufzeit per Login-Popup abgefragt
  und NIE gespeichert - das ist der gewuenschte "SSO-artige" Ablauf.
  Hinweis: Ein echtes OAuth-SSO ueber die Login-Seite des Providers wuerde eine
  registrierte OAuth-Client-ID (z. B. Google Cloud Console) voraussetzen; fuer
  Yahoo/Gmail mit 2FA ist stattdessen ein App-Passwort noetig (siehe README).
- BrevoProvider: Transaktions-API (300 Mails/Tag gratis), API-Key aus BREVO_API_KEY.
"""

import getpass
import json
import smtplib
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr

# Bekannte SMTP-Server je Absender-Domain (STARTTLS auf Port 587).
SMTP_HOSTS = {
    "yahoo.com": "smtp.mail.yahoo.com",
    "yahoo.de": "smtp.mail.yahoo.com",
    "gmail.com": "smtp.gmail.com",
    "googlemail.com": "smtp.gmail.com",
    "outlook.com": "smtp-mail.outlook.com",
    "hotmail.com": "smtp-mail.outlook.com",
    "live.com": "smtp-mail.outlook.com",
    "gmx.de": "mail.gmx.net",
    "gmx.net": "mail.gmx.net",
    "web.de": "smtp.web.de",
    "t-online.de": "securesmtp.t-online.de",
    "posteo.de": "posteo.de",
    "mailbox.org": "smtp.mailbox.org",
}


@dataclass
class SendResult:
    ok: bool
    message_id: str = ""
    error: str = ""


def ask_login_popup(prefill_email: str = "") -> tuple[str, str] | None:
    """Login-Dialog (tkinter): E-Mail + Passwort. None bei Abbruch.

    Faellt auf eine Konsolenabfrage (getpass) zurueck, wenn kein Display/tkinter
    verfuegbar ist. Die Daten bleiben nur im Arbeitsspeicher.
    """
    try:
        import tkinter as tk
    except ImportError:
        return _ask_login_console(prefill_email)

    result: dict = {}

    try:
        root = tk.Tk()
    except tk.TclError:
        return _ask_login_console(prefill_email)

    root.title("Doctor Hunter - Mail-Login")
    root.resizable(False, False)
    root.attributes("-topmost", True)

    tk.Label(root, text="Anmeldung beim Mail-Provider (SMTP)",
             font=("Segoe UI", 10, "bold")).grid(
        row=0, column=0, columnspan=2, padx=12, pady=(12, 6), sticky="w")
    tk.Label(root, text="Die Zugangsdaten werden nur fuer diesen\n"
                        "Versand verwendet und nicht gespeichert.",
             justify="left", fg="#555555").grid(
        row=1, column=0, columnspan=2, padx=12, pady=(0, 8), sticky="w")

    tk.Label(root, text="E-Mail-Adresse:").grid(row=2, column=0, padx=12, pady=4, sticky="e")
    email_var = tk.StringVar(value=prefill_email)
    email_entry = tk.Entry(root, textvariable=email_var, width=36)
    email_entry.grid(row=2, column=1, padx=(0, 12), pady=4)

    tk.Label(root, text="Passwort / App-Passwort:").grid(row=3, column=0, padx=12, pady=4, sticky="e")
    pass_var = tk.StringVar()
    pass_entry = tk.Entry(root, textvariable=pass_var, width=36, show="*")
    pass_entry.grid(row=3, column=1, padx=(0, 12), pady=4)

    status = tk.Label(root, text="", fg="#aa0000")
    status.grid(row=4, column=0, columnspan=2, padx=12, sticky="w")

    def on_ok(_event=None):
        email = email_var.get().strip()
        password = pass_var.get()
        if "@" not in email or not password:
            status.config(text="Bitte E-Mail-Adresse und Passwort angeben.")
            return
        result["email"] = email
        result["password"] = password
        root.destroy()

    def on_cancel():
        root.destroy()

    buttons = tk.Frame(root)
    buttons.grid(row=5, column=0, columnspan=2, pady=(8, 12))
    tk.Button(buttons, text="Anmelden", width=12, command=on_ok).pack(side="left", padx=6)
    tk.Button(buttons, text="Abbrechen", width=12, command=on_cancel).pack(side="left", padx=6)

    root.bind("<Return>", on_ok)
    (pass_entry if prefill_email else email_entry).focus_set()
    root.eval("tk::PlaceWindow . center")
    root.mainloop()

    if "email" in result:
        return result["email"], result["password"]
    return None


def _ask_login_console(prefill_email: str = "") -> tuple[str, str] | None:
    print("Login beim Mail-Provider (Eingaben werden nicht gespeichert).")
    email = input(f"E-Mail-Adresse [{prefill_email}]: ").strip() or prefill_email
    if not email:
        return None
    password = getpass.getpass("Passwort / App-Passwort: ")
    if not password:
        return None
    return email, password


class SmtpProvider:
    """Versand ueber das eigene Postfach (STARTTLS, Port 587)."""

    name = "smtp"

    def __init__(self, user: str, password: str, host: str = "", port: int = 587):
        self.user = user
        self.password = password
        self.host = host or self.detect_host(user)
        self.port = port
        if not self.host:
            domain = user.partition("@")[2]
            raise ValueError(
                f"Kein SMTP-Server fuer '{domain}' bekannt - bitte SMTP_HOST in der .env setzen."
            )

    @staticmethod
    def detect_host(email: str) -> str:
        return SMTP_HOSTS.get(email.partition("@")[2].lower(), "")

    def check_login(self) -> str:
        """Verbindungs- und Login-Test ohne Versand. Leerer String = OK."""
        try:
            with smtplib.SMTP(self.host, self.port, timeout=30) as smtp:
                smtp.starttls()
                smtp.login(self.user, self.password)
            return ""
        except smtplib.SMTPAuthenticationError as exc:
            return (f"Login fehlgeschlagen ({exc.smtp_code}): bei Yahoo/Gmail mit "
                    f"2FA wird ein App-Passwort benoetigt (siehe README-mailer.md).")
        except (smtplib.SMTPException, OSError, socket.timeout) as exc:
            return f"SMTP-Verbindung fehlgeschlagen ({self.host}:{self.port}): {exc}"

    def send(self, to_addr: str, subject: str, body: str,
             from_name: str = "", reply_to: str = "") -> SendResult:
        msg = EmailMessage()
        msg["From"] = formataddr((from_name, self.user)) if from_name else self.user
        msg["To"] = to_addr
        msg["Subject"] = subject
        if reply_to and reply_to != self.user:
            msg["Reply-To"] = reply_to
        msg.set_content(body, charset="utf-8")

        try:
            with smtplib.SMTP(self.host, self.port, timeout=60) as smtp:
                smtp.starttls()
                smtp.login(self.user, self.password)
                smtp.send_message(msg)
            return SendResult(ok=True, message_id=msg.get("Message-ID", ""))
        except (smtplib.SMTPException, OSError, socket.timeout) as exc:
            return SendResult(ok=False, error=str(exc))


class BrevoProvider:
    """Brevo Transaktions-API (https://api.brevo.com/v3/smtp/email)."""

    name = "brevo"
    API_URL = "https://api.brevo.com/v3/smtp/email"

    def __init__(self, api_key: str, from_addr: str, from_name: str = ""):
        if not api_key:
            raise ValueError("BREVO_API_KEY ist nicht gesetzt (siehe .env.example).")
        if not from_addr:
            raise ValueError("MAIL_FROM ist nicht gesetzt (verifizierte Brevo-Absenderadresse).")
        self.api_key = api_key
        self.from_addr = from_addr
        self.from_name = from_name
        self.user = from_addr  # einheitliche Schnittstelle zu SmtpProvider

    def check_login(self) -> str:
        req = urllib.request.Request(
            "https://api.brevo.com/v3/account",
            headers={"api-key": self.api_key, "accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30):
                return ""
        except urllib.error.HTTPError as exc:
            return f"Brevo-API-Key ungueltig (HTTP {exc.code})."
        except OSError as exc:
            return f"Brevo nicht erreichbar: {exc}"

    def send(self, to_addr: str, subject: str, body: str,
             from_name: str = "", reply_to: str = "") -> SendResult:
        payload: dict = {
            "sender": {"email": self.from_addr},
            "to": [{"email": to_addr}],
            "subject": subject,
            "textContent": body,
        }
        name = from_name or self.from_name
        if name:
            payload["sender"]["name"] = name
        if reply_to:
            payload["replyTo"] = {"email": reply_to}

        req = urllib.request.Request(
            self.API_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "api-key": self.api_key,
                "accept": "application/json",
                "content-type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8") or "{}")
            return SendResult(ok=True, message_id=data.get("messageId", ""))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            return SendResult(ok=False, error=f"HTTP {exc.code}: {detail}")
        except OSError as exc:
            return SendResult(ok=False, error=str(exc))
