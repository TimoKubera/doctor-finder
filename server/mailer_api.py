"""mailer_api.py - Bruecke zwischen Web-Backend und dem Mailer (Teil 2).

Stellt die Bausteine fuer die /api/mailer/*-Endpunkte bereit:
  - Fund-JSONs aus assets/ und server/runs/ auflisten (mit Empfaenger-Zahlen),
  - Vorschau der ersten gerenderten Mail (wie ``python -m mailer --dry-run``),
  - Versand vorbereiten und als Hintergrund-Job ausfuehren.

Die SMTP-Zugangsdaten kommen aus dem Formular im Browser, bleiben nur im
Arbeitsspeicher (in der Job-Closure) und werden nie gespeichert oder geloggt.
Die Quellen-Auswahl laeuft ueber eine Allowlist der tatsaechlich vorhandenen
aerzte_*.json-Dateien - kein Directory-Traversal ueber den Parameter moeglich.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from .runner import ASSETS_DIR, REPO_ROOT, RUNS_DIR, ProgressFn, ValidationError

# mailer/ liegt neben server/ im Projektordner; bei Start via `python -m server`
# ist das Repo-Root bereits auf sys.path - der Eintrag hier ist ein Sicherheitsnetz.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mailer import config as mailer_config  # noqa: E402
from mailer.recipients import load_recipients  # noqa: E402
from mailer.send import DEFAULT_TEMPLATE, build_mapping, make_provider  # noqa: E402
from mailer.template import load_template, render  # noqa: E402

MAX_LIMIT = 500


# -- Quellen (Fund-JSONs) -------------------------------------------------------


def _iter_source_paths():
    """Alle aerzte_*.json aus assets/ und server/runs/ (Allowlist)."""
    seen: set[Path] = set()
    for folder in (ASSETS_DIR, RUNS_DIR):
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("aerzte_*.json")):
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                yield path


def list_sources() -> list[dict]:
    """Verfuegbare Fund-JSONs mit Metadaten, neueste zuerst."""
    items: list[tuple[float, dict]] = []
    for path in _iter_source_paths():
        mtime = path.stat().st_mtime
        entry = {
            "id": path.relative_to(REPO_ROOT).as_posix(),
            "name": path.name,
            "ordner": path.parent.relative_to(REPO_ROOT).as_posix(),
            "geaendert": datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M"),
        }
        try:
            empfaenger, aussortiert, suche = load_recipients(path)
        except Exception as exc:  # noqa: BLE001 - defekte Datei nur markieren
            entry.update({"empfaenger": 0, "aussortiert": 0, "fehler": str(exc)[:200]})
        else:
            entry.update({
                "empfaenger": len(empfaenger),
                "aussortiert": len(aussortiert),
                "ort": (suche or {}).get("ort", ""),
            })
        items.append((mtime, entry))
    items.sort(key=lambda t: t[0], reverse=True)
    return [entry for _, entry in items]


def resolve_source(source_id: str) -> Path:
    """Loest die vom Frontend gewaehlte Quelle gegen die Allowlist auf."""
    wanted = str(source_id or "").strip()
    for path in _iter_source_paths():
        if path.relative_to(REPO_ROOT).as_posix() == wanted:
            return path
    raise ValidationError("Unbekannte Fund-JSON - bitte aus der Liste waehlen.")


# -- Rendern / Vorschau ---------------------------------------------------------


def _parse_limit(raw) -> int | None:
    if raw in (None, "", 0, "0"):
        return None
    try:
        limit = int(raw)
    except (TypeError, ValueError):
        raise ValidationError("Limit muss eine ganze Zahl sein.")
    if not 1 <= limit <= MAX_LIMIT:
        raise ValidationError(f"Limit muss zwischen 1 und {MAX_LIMIT} liegen.")
    return limit


def build_messages(json_path: Path, limit: int | None) -> tuple[list[tuple[str, str, str]], int, dict]:
    """Rendert alle Mails einer Fund-JSON: [(email, betreff, text), ...].

    Fehler in Vorlage oder Fund-JSON (ValueError/OSError) sollen beim Aufrufer
    zu HTTP 400 fuehren - genau wie im CLI-Ablauf von mailer/send.py.
    """
    title_tmpl, body_tmpl = load_template(DEFAULT_TEMPLATE)
    empfaenger, aussortiert, suche = load_recipients(json_path)
    if limit is not None:
        empfaenger = empfaenger[:limit]
    nachrichten = []
    for rec in empfaenger:
        mapping = build_mapping(rec, suche)
        nachrichten.append((rec["email"], render(title_tmpl, mapping), render(body_tmpl, mapping)))
    return nachrichten, len(aussortiert), suche


def preview(raw: dict) -> dict:
    """Dry-Run fuer das Frontend: erste gerenderte Mail + Anzahl."""
    source = str(raw.get("source", "")).strip()
    if not source:
        raise ValidationError("Bitte eine Fund-JSON auswaehlen.")
    path = resolve_source(source)
    nachrichten, aussortiert, suche = build_messages(path, _parse_limit(raw.get("limit")))
    if not nachrichten:
        raise ValidationError("Diese Fund-JSON enthaelt keine gueltigen E-Mail-Adressen.")
    to_addr, subject, body = nachrichten[0]
    return {
        "quelle": path.name,
        "an": to_addr,
        "betreff": subject,
        "text": body,
        "gesamt": len(nachrichten),
        "aussortiert": aussortiert,
        "ort": (suche or {}).get("ort", ""),
    }


# -- Versand --------------------------------------------------------------------


def validate_send_params(raw: dict) -> dict:
    """Prueft die Versand-Parameter aus dem Frontend."""
    mailer_config.load_env()
    source = str(raw.get("source", "")).strip()
    if not source:
        raise ValidationError("Bitte eine Fund-JSON auswaehlen.")
    limit = _parse_limit(raw.get("limit"))
    email = str(raw.get("email", "")).strip()
    password = str(raw.get("password", ""))
    provider = mailer_config.get("MAILER_PROVIDER", "smtp").strip().lower()
    if provider != "brevo":  # Brevo holt Key/Absender aus der .env
        if "@" not in email:
            raise ValidationError("Bitte eine gueltige Absender-E-Mail-Adresse angeben.")
        if not password:
            raise ValidationError("Bitte das Passwort/App-Passwort angeben.")
    return {"source": source, "email": email, "password": password, "limit": limit}


def prepare_send(raw: dict) -> dict:
    """Validiert alles, rendert die Mails und liefert {'work': fn, 'anzahl': n}.

    ``work(on_progress)`` ist fuer JobManager.start gedacht; die Zugangsdaten
    leben nur in der Provider-Instanz innerhalb dieser Closure.
    """
    params = validate_send_params(raw)
    path = resolve_source(params["source"])
    nachrichten, _aussortiert, _suche = build_messages(path, params["limit"])
    if not nachrichten:
        raise ValidationError("Diese Fund-JSON enthaelt keine gueltigen E-Mail-Adressen.")
    provider = make_provider(params["email"], params["password"])

    def work(on_progress: ProgressFn) -> dict:
        return _run_send(nachrichten, provider, on_progress)

    return {"work": work, "anzahl": len(nachrichten)}


def _run_send(nachrichten: list[tuple[str, str, str]], provider, on_progress: ProgressFn) -> dict:
    """Laeuft im Job-Thread: Login-Test, Versand pro Empfaenger, Zusammenfassung."""
    ziel = getattr(provider, "host", "") or provider.name
    on_progress(f"Melde an bei {ziel} ...")
    err = provider.check_login()
    if err:
        raise RuntimeError(err)
    on_progress(f"Angemeldet als {provider.user} ({provider.name}).")
    on_progress(f"Sende {len(nachrichten)} Mail(s) ...")

    from_name = mailer_config.get("MAIL_FROM_NAME")
    reply_to = mailer_config.get("REPLY_TO")
    ok, fehler = 0, 0
    details = []
    for email, subject, body in nachrichten:
        result = provider.send(email, subject, body, from_name=from_name, reply_to=reply_to)
        if result.ok:
            ok += 1
            on_progress(f"  OK   {email}")
        else:
            fehler += 1
            on_progress(f"  FEHL {email}: {result.error}")
        details.append({"email": email, "ok": result.ok, "fehler": result.error})

    on_progress(f"Fertig: {ok} gesendet, {fehler} fehlgeschlagen.")
    return {"result": {"gesendet": ok, "fehlgeschlagen": fehler, "details": details}}
