"""recipients.py - aerzte_*.json (aus Teil 1) laden, E-Mail-Adressen saeubern und
validieren, Verdachts-Hinweise fuer die manuelle Freigabe erzeugen."""

import json
import re
from pathlib import Path
from urllib.parse import urlparse

EMAIL_RE = re.compile(r"^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$")

# Artefakte aus dem HTML-Scraping (Teil 1): geschuetzte Leerzeichen, die als
# literales "u00a0" oder als echtes \xa0 vor der Adresse kleben koennen.
_LEADING_JUNK_RE = re.compile(r"^(?:u00a0|\\u00a0|\s| )+", re.I)


def clean_email(raw: str) -> str:
    email = (raw or "").strip().lower()
    email = _LEADING_JUNK_RE.sub("", email)
    email = email.replace(" ", "").replace(" ", "")
    return email.rstrip(".")


def host_root(url_or_host: str) -> str:
    """Registrierbare Domain grob als letzte zwei Labels (wie Get-HostRoot in Teil 1)."""
    h = (url_or_host or "").strip().lower()
    if not h:
        return ""
    if h.startswith(("http://", "https://")):
        h = urlparse(h).netloc
    h = h.split(":")[0].removeprefix("www.")
    parts = [p for p in h.split(".") if p]
    return ".".join(parts[-2:]) if len(parts) >= 2 else h


def build_hinweis(rec: dict, email: str) -> str:
    """Markiert verdaechtige Eintraege fuer die Review-CSV (blockiert nichts)."""
    hinweise = []

    homepage_root = host_root(rec.get("homepage", ""))
    email_root = host_root(email.partition("@")[2])
    freemail = {"gmail.com", "googlemail.com", "yahoo.com", "yahoo.de", "gmx.de",
                "gmx.net", "web.de", "t-online.de", "online.de", "posteo.de",
                "outlook.com", "hotmail.com", "icloud.com", "mail.de", "freenet.de"}
    if homepage_root and email_root and email_root != homepage_root and email_root not in freemail:
        hinweise.append(f"Domain weicht ab ({email_root} statt {homepage_root})")

    if (rec.get("geschlecht") or "").lower() not in ("weiblich", "maennlich"):
        hinweise.append("Institution?")

    return "; ".join(hinweise)


def load_recipients(path: Path) -> tuple[list[dict], list[dict], dict]:
    """Laedt die Fund-JSON aus Teil 1.

    Rueckgabe: (empfaenger, aussortiert, suche-Metadaten).
    Jeder Empfaenger erhaelt die Zusatzfelder 'email' (gesaeubert) und 'hinweis'.
    Ungueltige/leere Adressen und Duplikate werden aussortiert (mit Grund).
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    aerzte = data.get("aerzte") or []
    suche = data.get("suche") or {}

    empfaenger: list[dict] = []
    aussortiert: list[dict] = []
    seen: set[str] = set()

    for rec in aerzte:
        email = clean_email(rec.get("email", ""))
        if not email:
            aussortiert.append({**rec, "grund": "keine E-Mail"})
            continue
        if not EMAIL_RE.match(email):
            aussortiert.append({**rec, "grund": f"ungueltige E-Mail: {email!r}"})
            continue
        if email in seen:
            aussortiert.append({**rec, "grund": f"doppelte E-Mail: {email}"})
            continue
        seen.add(email)
        empfaenger.append({**rec, "email": email, "hinweis": build_hinweis(rec, email)})

    return empfaenger, aussortiert, suche
