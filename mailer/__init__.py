"""mailer - Versand der im Doctor Hunter gefundenen Arzt-Adressen.

Bausteine:
  - config.py      Konfiguration aus Umgebungsvariablen / optionaler .env
  - recipients.py  Fund-JSON (aerzte_*.json) laden, E-Mails saeubern/validieren
  - template.py    mail.md parsen (# Title / # Body) und {{platzhalter}} rendern
  - providers.py   Versand-Backends (SMTP mit SSO-Login-Popup, Brevo-API)
  - send.py        Orchestrierung (Entry-Point: ``python -m mailer``)
"""

__all__ = ["config", "recipients", "template", "providers", "send"]
