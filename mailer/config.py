"""config.py - Konfiguration aus Umgebungsvariablen und optionaler .env-Datei.

Es werden KEINE Secrets im Code oder in versionierten Dateien gespeichert.
Eine .env (siehe .env.example) wird - falls vorhanden - eingelesen; bereits
gesetzte Umgebungsvariablen haben Vorrang. Beim SMTP-Popup-Login werden
Zugangsdaten ohnehin nur zur Laufzeit abgefragt und nie gespeichert.
"""

import os
from pathlib import Path

MAILER_DIR = Path(__file__).resolve().parent
PROJECT_DIR = MAILER_DIR.parent
ASSETS_DIR = PROJECT_DIR / "assets"


def _parse_env_file(path: Path) -> dict:
    """Minimaler .env-Parser: KEY=VALUE-Zeilen, '#'-Kommentare, optionale Quotes."""
    values = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return values
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def load_env() -> None:
    """Laedt .env aus dem mailer/-Ordner bzw. dem Projektordner in os.environ
    (ohne bereits gesetzte Umgebungsvariablen zu ueberschreiben)."""
    for candidate in (MAILER_DIR / ".env", PROJECT_DIR / ".env"):
        if candidate.is_file():
            for key, value in _parse_env_file(candidate).items():
                os.environ.setdefault(key, value)


def get(key: str, default: str = "") -> str:
    return os.environ.get(key, default)
