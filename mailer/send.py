"""send.py - Orchestriert den Mailversand an die im Doctor Finder gefundenen Adressen.

Ablauf:
  1. Fund-JSON (``assets/aerzte_*.json`` aus Teil 1) laden und Empfaenger extrahieren.
  2. Mail-Vorlage ``assets/mail.md`` laden (Abschnitte ``# Title`` / ``# Body``).
  3. Absender per **SSO-Login-Popup (tkinter)** anmelden - E-Mail + Passwort werden
     nur zur Laufzeit abgefragt und nie gespeichert (siehe providers.ask_login_popup).
  4. Pro Empfaenger Titel/Body mit dessen Feldern rendern und versenden.
  5. Zusammenfassung (Erfolg/Fehler) ausgeben.

Aufruf:
    python -m mailer                       # neueste Fund-JSON, echter Versand nach Login
    python -m mailer --dry-run             # nur rendern/anzeigen, NICHT senden
    python -m mailer --json <pfad.json>    # bestimmte Fund-JSON verwenden
    python -m mailer --limit 3             # nur die ersten 3 Empfaenger
    python -m mailer --to test@example.com # Testversand an EINE Adresse
    python -m mailer --yes                 # ohne Rueckfrage direkt senden
"""

import argparse
import sys
from pathlib import Path

# Sowohl als Paket (python -m mailer) als auch direkt (python mailer/send.py) nutzbar.
if __package__:
    from . import config
    from .providers import BrevoProvider, SmtpProvider, ask_login_popup
    from .recipients import load_recipients
    from .template import anrede, load_template, render
else:  # pragma: no cover - Fallback fuer den direkten Skriptaufruf
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import config  # type: ignore
    from providers import BrevoProvider, SmtpProvider, ask_login_popup  # type: ignore
    from recipients import load_recipients  # type: ignore
    from template import anrede, load_template, render  # type: ignore

ASSETS_DIR = config.ASSETS_DIR
DEFAULT_TEMPLATE = ASSETS_DIR / "mail.md"


def find_latest_json() -> Path:
    """Neueste ``assets/aerzte_*.json`` finden (Dateiname enthaelt Zeitstempel)."""
    candidates = sorted(ASSETS_DIR.glob("aerzte_*.json"))
    if not candidates:
        raise FileNotFoundError(
            f"Keine Fund-JSON in {ASSETS_DIR} gefunden. Bitte zuerst "
            "Find-Doctors.ps1 ausfuehren (erzeugt aerzte_*.json)."
        )
    return candidates[-1]


def build_mapping(rec: dict, suche: dict) -> dict:
    """Platzhalter-Werte fuer einen Empfaenger (fuer {{...}} in mail.md)."""
    return {
        "anrede": anrede(rec),
        "name": rec.get("name", ""),
        "vorname": rec.get("vorname", ""),
        "nachname": rec.get("nachname", ""),
        "titel": rec.get("titel", ""),
        "fachgebiet": rec.get("fachgebiet", ""),
        "strasse": rec.get("strasse", ""),
        "plz": rec.get("plz", ""),
        "ort": rec.get("ort", ""),
        "telefon": rec.get("telefon", ""),
        "homepage": rec.get("homepage", ""),
        "email": rec.get("email", ""),
        "suchort": (suche or {}).get("ort", ""),
    }


def make_provider(sender_email: str, sender_password: str):
    """Waehlt das Versand-Backend anhand von MAILER_PROVIDER (Standard: SMTP)."""
    provider = config.get("MAILER_PROVIDER", "smtp").strip().lower()
    if provider == "brevo":
        return BrevoProvider(
            api_key=config.get("BREVO_API_KEY"),
            from_addr=config.get("MAIL_FROM", sender_email),
            from_name=config.get("MAIL_FROM_NAME"),
        )
    return SmtpProvider(
        user=sender_email,
        password=sender_password,
        host=config.get("SMTP_HOST"),
        port=int(config.get("SMTP_PORT", "587") or "587"),
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m mailer",
        description="Versendet die Mail-Vorlage an die gefundenen Arzt-Adressen.",
    )
    parser.add_argument("--json", type=Path, help="Pfad zur Fund-JSON (Standard: neueste in assets/).")
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE, help="Mail-Vorlage (Standard: assets/mail.md).")
    parser.add_argument("--to", help="Testversand nur an diese eine Adresse.")
    parser.add_argument("--limit", type=int, help="Nur die ersten N Empfaenger verarbeiten.")
    parser.add_argument("--dry-run", action="store_true", help="Nur rendern/anzeigen, NICHT senden (kein Login).")
    parser.add_argument("--yes", action="store_true", help="Ohne Sicherheitsabfrage direkt senden.")
    return parser.parse_args(argv)


def _confirm(prompt: str) -> bool:
    try:
        return input(prompt).strip().lower() in ("j", "ja", "y", "yes")
    except EOFError:
        return False


def main(argv: list[str] | None = None) -> int:
    config.load_env()
    args = parse_args(argv)

    # 1) Vorlage laden.
    try:
        title_tmpl, body_tmpl = load_template(args.template)
    except (OSError, ValueError) as exc:
        print(f"Fehler beim Laden der Vorlage: {exc}", file=sys.stderr)
        return 2

    # 2) Empfaenger bestimmen.
    json_path = args.json or find_latest_json()
    empfaenger, aussortiert, suche = load_recipients(json_path)
    if args.to:
        # Testmodus: kuenstlicher Empfaenger mit neutraler Anrede.
        empfaenger = [{"email": args.to, "geschlecht": "unbekannt", "nachname": ""}]
        aussortiert = []
    if args.limit is not None:
        empfaenger = empfaenger[: args.limit]

    print(f"Vorlage : {args.template}")
    print(f"Funde   : {json_path.name}")
    print(f"Empfaenger: {len(empfaenger)} (aussortiert: {len(aussortiert)})")
    if not empfaenger:
        print("Keine gueltigen Empfaenger - Abbruch.", file=sys.stderr)
        return 1

    # 3) Nachrichten rendern (Fehler in der Vorlage fallen hier sofort auf).
    nachrichten = []
    for rec in empfaenger:
        mapping = build_mapping(rec, suche)
        try:
            subject = render(title_tmpl, mapping)
            body = render(body_tmpl, mapping)
        except ValueError as exc:
            print(f"Fehler beim Rendern fuer {rec.get('email')}: {exc}", file=sys.stderr)
            return 2
        nachrichten.append((rec["email"], subject, body, rec))

    # 4) Dry-Run: nur Vorschau, kein Versand, kein Login.
    if args.dry_run:
        first_email, first_subject, first_body, _ = nachrichten[0]
        print("\n--- Vorschau (erste Mail, DRY-RUN, es wird nichts gesendet) ---")
        print(f"An     : {first_email}")
        print(f"Betreff: {first_subject}")
        print("-" * 60)
        print(first_body)
        print("-" * 60)
        print(f"({len(nachrichten)} Mails wuerden gesendet.)")
        return 0

    # 5) SSO-Login-Popup (tkinter) fuer Absenderadresse + Passwort.
    provider_name = config.get("MAILER_PROVIDER", "smtp").strip().lower()
    if provider_name == "brevo":
        sender_email, sender_password = config.get("MAIL_FROM"), ""
    else:
        login = ask_login_popup(prefill_email=config.get("MAIL_FROM"))
        if login is None:
            print("Login abgebrochen - kein Versand.", file=sys.stderr)
            return 1
        sender_email, sender_password = login

    try:
        provider = make_provider(sender_email, sender_password)
    except ValueError as exc:
        print(f"Konfigurationsfehler: {exc}", file=sys.stderr)
        return 2

    # Login-/Verbindungstest vor dem Massenversand.
    err = provider.check_login()
    if err:
        print(f"Anmeldung fehlgeschlagen: {err}", file=sys.stderr)
        return 1
    print(f"Angemeldet als: {getattr(provider, 'user', sender_email)} ({provider.name})")

    # 6) Sicherheitsabfrage vor dem echten Versand.
    if not args.yes:
        if not _confirm(f"{len(nachrichten)} Mails jetzt wirklich senden? [j/N] "):
            print("Abgebrochen.")
            return 1

    # 7) Versand.
    from_name = config.get("MAIL_FROM_NAME")
    reply_to = config.get("REPLY_TO")
    ok, fehler = 0, 0
    for email, subject, body, _rec in nachrichten:
        result = provider.send(email, subject, body, from_name=from_name, reply_to=reply_to)
        if result.ok:
            ok += 1
            print(f"  OK   {email}")
        else:
            fehler += 1
            print(f"  FEHL {email}: {result.error}")

    print(f"\nFertig: {ok} gesendet, {fehler} fehlgeschlagen.")
    return 0 if fehler == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
