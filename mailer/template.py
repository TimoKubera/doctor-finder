"""template.py - mail.md parsen ('# Title' / '# Body'), Platzhalter rendern,
Anrede aus den Arzt-Feldern (geschlecht/titel/nachname) ableiten."""

import re
from pathlib import Path

PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


def load_template(path: Path) -> tuple[str, str]:
    """Liest mail.md und liefert (titel, body).

    Erwartetes Format:
        # Title
        <Betreffzeile>

        # Body
        <Mailtext ...>
    """
    text = Path(path).read_text(encoding="utf-8")

    m_title = re.search(r"^#\s*Title\s*$(.*?)(?=^#\s|\Z)", text, re.M | re.S)
    m_body = re.search(r"^#\s*Body\s*$(.*)\Z", text, re.M | re.S)
    if not m_title or not m_body:
        raise ValueError(
            f"{path}: erwartet die Abschnitte '# Title' und '# Body' (siehe README-mailer.md)."
        )

    title = " ".join(m_title.group(1).split())
    body = m_body.group(1).strip("\n").rstrip() + "\n"
    if not title:
        raise ValueError(f"{path}: '# Title' ist leer.")
    if not body.strip():
        raise ValueError(f"{path}: '# Body' ist leer.")
    return title, body


def titel_kurz(titel: str) -> str:
    """Akademischen Titel fuer die Anrede kuerzen.

    'Prof. Dr. med.' -> 'Prof. Dr.' | 'Dr. med.' -> 'Dr.' | sonst ''.
    Fachzusaetze (med., phil., Dipl.-...) gehoeren nicht in die Anrede.
    """
    t = (titel or "").lower()
    is_prof = "prof" in t
    is_dr = re.search(r"\bdr\b|dr\.", t) is not None
    if is_prof and is_dr:
        return "Prof. Dr."
    if is_prof:
        return "Prof."
    if is_dr:
        return "Dr."
    return ""


def anrede(rec: dict) -> str:
    """Persoenliche Anrede; bei Institutionen/unbekanntem Geschlecht die neutrale Form."""
    geschlecht = (rec.get("geschlecht") or "").lower()
    nachname = (rec.get("nachname") or "").strip()
    kurz = titel_kurz(rec.get("titel", ""))

    # Institutionen (z. B. "Med. Hochschule Hannover") haben kein Geschlecht/keinen
    # echten Nachnamen -> neutrale Anrede.
    if geschlecht not in ("weiblich", "maennlich") or not nachname:
        return "Sehr geehrte Damen und Herren,"

    name_teil = " ".join(part for part in (kurz, nachname) if part)
    if geschlecht == "weiblich":
        return f"Sehr geehrte Frau {name_teil},"
    return f"Sehr geehrter Herr {name_teil},"


def render(text: str, mapping: dict) -> str:
    """Ersetzt {{platzhalter}}; unbekannte Platzhalter sind ein Fehler (Tippfehlerschutz)."""
    unresolved = []

    def _sub(match: re.Match) -> str:
        key = match.group(1)
        if key in mapping:
            return str(mapping[key])
        unresolved.append(key)
        return match.group(0)

    result = PLACEHOLDER_RE.sub(_sub, text)
    if unresolved:
        raise ValueError(
            "Unbekannte Platzhalter im Template: "
            + ", ".join(sorted(set(unresolved)))
            + f" (verfuegbar: {', '.join(sorted(mapping))})"
        )
    return result
