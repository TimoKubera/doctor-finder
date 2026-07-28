# Mailer – Versand an die gefundenen Adressen

Zweiter Teil des Projekts: verschickt eine Mail-Vorlage an die vom **Doctor Finder**
(`Find-Doctors.ps1`) gefundenen Arzt-Adressen. Das Backend ist in **Python**
geschrieben (Standardbibliothek, keine Zusatzpakete nötig).

## Überblick

```
mailer/
  send.py        Orchestrierung / Entry-Point (python -m mailer)
  recipients.py  Fund-JSON (assets/aerzte_*.json) laden, E-Mails säubern/validieren
  template.py    mail.md parsen (# Title / # Body), {{platzhalter}} rendern, Anrede ableiten
  providers.py   Versand-Backends: SmtpProvider (SSO-Login-Popup) und BrevoProvider (API)
  config.py      Konfiguration aus Umgebungsvariablen / optionaler .env
assets/
  mail.md        Mail-Vorlage: Betreff (# Title) und Text (# Body)
  aerzte_*.json  Fundliste aus Teil 1
```

## Ablauf

1. **Fundliste laden** – standardmäßig die neueste `assets/aerzte_*.json`. Adressen
   werden gesäubert, validiert und dedupliziert; ungültige/leere werden aussortiert.
2. **Vorlage laden** – `assets/mail.md` mit den Abschnitten `# Title` (Betreff) und
   `# Body` (Text). Platzhalter `{{...}}` werden pro Empfänger ersetzt.
3. **SSO-Login (Tkinter)** – ein Popup fragt Absender-**E-Mail** und **Passwort**
   ab. Die Zugangsdaten bleiben nur im Arbeitsspeicher und werden **nie gespeichert**.
   Ohne Display/Tkinter gibt es einen Konsolen-Fallback (`getpass`).
4. **Versand** – nach einem Login-/Verbindungstest wird die (personalisierte) Mail
   über SMTP (STARTTLS, Port 587) an alle Empfänger geschickt. Abschließend gibt es
   eine Erfolg-/Fehler-Zusammenfassung.

## Verwendung

```bash
# Vorschau der ersten gerenderten Mail – sendet NICHTS, kein Login:
python -m mailer --dry-run

# Testversand an genau eine Adresse (öffnet das Login-Popup):
python -m mailer --to test@example.com

# Echter Versand an alle Empfänger der neuesten Fund-JSON:
python -m mailer

# Bestimmte Fund-JSON, nur die ersten 3 Empfänger, ohne Rückfrage:
python -m mailer --json assets/aerzte_23_Hannover_20260711_205704.json --limit 3 --yes
```

Alternativ lässt sich der Versand auch **direkt aus dem Browser** starten:
`python -m server` ausführen und in der Weboberfläche den Abschnitt
**„Mailer – Anfrage versenden"** nutzen (Fund-JSON-Auswahl, Vorschau,
Versand mit Live-Fortschritt – siehe `README-server.md`).

| Option        | Bedeutung |
|---------------|-----------|
| `--dry-run`   | Rendert die erste Mail und zeigt sie an, **ohne** zu senden (kein Login). |
| `--to ADRESSE`| Testversand an nur eine Adresse (neutrale Anrede). |
| `--json PFAD` | Bestimmte Fund-JSON statt der automatisch gewählten neuesten. |
| `--template PFAD` | Andere Vorlage als `assets/mail.md`. |
| `--limit N`   | Nur die ersten N Empfänger. |
| `--yes`       | Überspringt die Sicherheitsabfrage vor dem Massenversand. |

## Mail-Vorlage (`assets/mail.md`)

```markdown
# Title
Terminanfrage – neue Patientin/neuer Patient

# Body
{{anrede}}

… Ihr Anschreiben …

Mit freundlichen Grüßen
Vorname Nachname
```

**Platzhalter** (werden je Empfänger ersetzt): `{{anrede}}`, `{{name}}`, `{{vorname}}`,
`{{nachname}}`, `{{titel}}`, `{{fachgebiet}}`, `{{strasse}}`, `{{plz}}`, `{{ort}}`,
`{{telefon}}`, `{{homepage}}`, `{{email}}`, `{{suchort}}`.

`{{anrede}}` wird aus Geschlecht, Titel und Nachname gebildet – z. B.
„Sehr geehrte Frau Dr. Meyer,". Bei Institutionen oder unbekanntem Geschlecht
wird auf „Sehr geehrte Damen und Herren," zurückgefallen. Ein unbekannter
Platzhalter ist ein Fehler (Schutz vor Tippfehlern).

## Zugangsdaten / SMTP

- Der SMTP-Server wird aus der Absender-Domain abgeleitet (Yahoo, Gmail, Outlook,
  GMX, Web.de, T-Online, Posteo, Mailbox.org …). Unbekannte Domains: `SMTP_HOST`
  (und ggf. `SMTP_PORT`) in `mailer/.env` setzen (siehe `mailer/.env.example`).
- **Gmail** akzeptiert für SMTP grundsätzlich **kein** normales Konto-Passwort mehr –
  es wird immer ein **App-Passwort** benötigt (siehe Anleitung unten). Bei **Yahoo**
  gilt dasselbe, sobald Zwei-Faktor-Authentifizierung aktiv ist.

### Gmail einrichten (einmalig, kostenlos)

1. **2FA aktivieren:** <https://myaccount.google.com/signinoptions/two-step-verification>
   („Bestätigung in zwei Schritten", z. B. per Telefonnummer oder Authenticator-App).
   Ohne 2FA bietet Google keine App-Passwörter an.
2. **App-Passwort erstellen:** <https://myaccount.google.com/apppasswords> –
   beliebigen Namen vergeben (z. B. „Doctor Finder"). Google zeigt ein
   16-stelliges Passwort im Format `abcd efgh ijkl mnop` an.
3. **Verwenden:** Das App-Passwort im Login-Popup bzw. im Web-Formular statt des
   Konto-Passworts eingeben. Leerzeichen sind egal – sie werden automatisch entfernt.
   Das App-Passwort lässt sich jederzeit unter demselben Link widerrufen.
- Alternatives Backend **Brevo** (Transaktions-API, 300 Mails/Tag gratis):
  `MAILER_PROVIDER=brevo`, `BREVO_API_KEY` und eine verifizierte `MAIL_FROM` setzen.

## Konfiguration

Alle Einstellungen sind **optional** und kommen aus Umgebungsvariablen oder einer
`mailer/.env` (Vorlage: `mailer/.env.example`). Bereits gesetzte Umgebungsvariablen
haben Vorrang. **Es werden keine Secrets im Code oder in versionierten Dateien
gespeichert.**
