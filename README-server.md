# Web-Backend – Suche aus dem Browser starten

Kleiner Python-Dienst, der die statische Oberfläche (`web/index.html`) ausliefert
**und** `Find-Doctors.ps1` mit den in der GUI eingegebenen Parametern ausführt.
Damit wird aus dem reinen „Befehl kopieren" ein echtes **Klick → Suche läuft →
Ergebnisse im Browser**. Reine Python-Standardbibliothek – keine Zusatzpakete.

## Starten

```bash
python -m server                 # http://127.0.0.1:8765
python -m server --port 9000     # anderer Port
python -m server --mock          # ohne PowerShell (Beispieldaten zum Ausprobieren)
```

Dann `http://127.0.0.1:8765` im Browser öffnen. Findet der Server kein PowerShell,
läuft er automatisch im **Demo-/Mock-Modus** und liefert die Beispieldaten aus
`assets/` – die Oberfläche kennzeichnet das mit einem „Demo"-Badge.

## Voraussetzungen

- **Python 3.9+**
- **PowerShell** für echte Suchen: PowerShell 7+ (`pwsh`, plattformübergreifend)
  oder Windows PowerShell (`powershell.exe`). Der Server erkennt beides selbst.

## Wie es funktioniert

- Ein Suchlauf ist ein **Job**: Der Server startet `Find-Doctors.ps1` als
  Subprozess, streamt dessen Ausgabe als Fortschritt und liest am Ende die
  erzeugte JSON ein. Der Browser fragt den Job-Status per Polling ab und zeigt
  Protokoll und Ergebnistabelle an.
- Wegen des **TK-Tageskontingents** läuft immer nur **ein** Suchlauf gleichzeitig
  (weitere Starts erhalten HTTP 409).
- Ergebnisse werden unter `server/runs/` abgelegt (nicht versioniert) und können
  anschließend direkt an den Mailer übergeben werden (`python -m mailer`).

## API

| Methode & Pfad          | Zweck |
|-------------------------|-------|
| `GET /`                 | Weboberfläche (`web/index.html`) |
| `GET /api/health`       | `{ok, powershell, mock, running}` |
| `GET /api/fachgebiete`  | Fachgebiets-Liste `[{nr, name}, …]` |
| `POST /api/search`      | Startet einen Lauf → `{job_id}` (202) |
| `GET /api/search/{id}`  | Status/Fortschritt/Ergebnis des Laufs |

`POST /api/search` erwartet JSON:

```json
{ "fachgebiet": ["23", "25"], "ort": "Hannover", "geschlecht": "w", "punkte": 5 }
```

Die Parameter werden serverseitig validiert: Fachgebiets-Nummern müssen in
`lib/Fachgebiete.ps1` existieren, `geschlecht` ist `m` / `w` / leer, `punkte`
liegt zwischen 1 und 50. Der Ort wird als einzelnes Argument (ohne Shell) an
PowerShell übergeben – kein Command-Injection-Risiko.

## Sicherheit / Betrieb

- Der Dienst **führt lokal einen Crawler aus** und bindet daher standardmäßig nur
  an `127.0.0.1`. Vor einer Bereitstellung über das offene Internet müssten
  Authentifizierung, Rate-Limiting und Absicherung des Hosts ergänzt werden –
  gedacht ist er als lokales Werkzeug bzw. für ein vertrauenswürdiges Netz.
- Nur die reine statische Oberfläche (`web/index.html`) lässt sich alternativ auf
  jedem Static-Host bereitstellen; dort steht dann der „Befehl kopieren"-Modus zur
  Verfügung, aber nicht die Live-Suche (die braucht dieses Backend mit PowerShell).
