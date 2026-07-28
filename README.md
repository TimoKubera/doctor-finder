# Doctor Finder

Findet Ärztinnen/Ärzte im [TK-Ärzteführer](https://www.tk-aerztefuehrer.de/), ermittelt über
die Praxis-Homepage (Impressum) die E-Mail-Adresse und verifiziert die Adresse. Um **das ganze
Stadtgebiet** abzudecken (nicht nur die Innenstadt), wird der Ort mit mehreren weit
auseinanderliegenden PLZ abgesucht (PLZ-Sweep) und die Treffer werden zusammengeführt. Die Funde
werden als JSON im Ordner `assets/` gespeichert.

> Der Versand an die gefundenen Adressen ist der **zweite Teil** des Projekts (Python-Backend im
> Ordner `mailer/`, Details in [`README-mailer.md`](README-mailer.md)); er setzt auf die hier
> erzeugten Einträge mit `email != ""` auf.

## Web-Oberfläche (Parameter zusammenstellen)

`web/index.html` ist eine eigenständige, statische Single-Page-Oberfläche zum bequemen
Zusammenstellen der Suchparameter: durchsuchbare **Fachgebiet**-Auswahl (Mehrfachauswahl),
**Ort**, **Geschlecht**, **PLZ-Suchpunkte** und optionale **Ausgabedatei**. Daraus wird live
der passende `Find-Doctors.ps1`-Aufruf erzeugt, den man per Klick kopiert und in PowerShell
ausführt. Die Datei kommt ohne Build-Schritt und ohne externe Abhängigkeiten aus – einfach im
Browser öffnen oder auf einem beliebigen Static-Host bereitstellen.

Mit dem **Web-Backend** (`python -m server`, siehe [`README-server.md`](README-server.md)) wird
daraus eine echte Live-Suche: Der Dienst liefert dieselbe Oberfläche aus, startet auf Klick
`Find-Doctors.ps1` und zeigt Fortschritt und Ergebnisse direkt im Browser an.

## Voraussetzungen

- Windows PowerShell 5.1 (auf Windows vorinstalliert) – **keine** Installation weiterer Pakete.
- **Internet-Zugriff** auf den TK-Ärzteführer und (für den PLZ-Sweep) auf
  [Nominatim/OpenStreetMap](https://nominatim.openstreetmap.org/). Ohne Nominatim fällt das Tool
  auf den Ort-Text als Einzelpunkt zurück (`-Punkte 1`).

## Verwendung

```powershell
# Hilfe + vollständige Fachgebiets-Tabelle anzeigen
.\Find-Doctors.ps1 -Help

# Nicht-interaktiv (ein Fachgebiet)
.\Find-Doctors.ps1 -Fachgebiet 1 -Ort Hannover
.\Find-Doctors.ps1 -Fachgebiet 2 -Ort Leipzig -Geschlecht w

# Mehrere Fachgebiete (Komma und/oder Leerzeichen, auch gemischt)
.\Find-Doctors.ps1 -Fachgebiet 23,24,25 -Ort Hannover
.\Find-Doctors.ps1 -Fachgebiet 23 24 25 -Ort Hannover

# Abdeckung steuern: Anzahl der PLZ-Suchpunkte (Standard 5)
.\Find-Doctors.ps1 -Fachgebiet 23 -Ort Hannover -Punkte 10   # mehr Abdeckung, mehr Abfragen
.\Find-Doctors.ps1 -Fachgebiet 23 -Ort Hannover -Punkte 1    # nur Ort-Text (kein Sweep)

# Interaktiv (fragt Fachgebiet + Ort ab)
.\Find-Doctors.ps1
```

### Parameter

| Parameter     | Bedeutung |
|---------------|-----------|
| `-Fachgebiet` | Eine **oder mehrere** Nummern (siehe `-Help`). Z. B. `1` = Allergologie. Mehrere komma- und/oder leerzeichengetrennt: `23,24,25` oder `23 24 25` (auch gemischt). Duplikate und ungültige Nummern werden automatisch aussortiert. |
| `-Ort`        | Ort / Stadtteil / PLZ – **Pflichtfeld** des TK-Ärzteführers. Z. B. `Hannover` oder `30159`. |
| `-Geschlecht` | Optional: `m` (männlich) oder `w` (weiblich). Ohne Angabe: alle Geschlechter. |
| `-Punkte`     | Anzahl der PLZ-Suchpunkte für die Ortsabdeckung (Standard `5`). Deckt das Stadtgebiet mit mehreren weit auseinanderliegenden PLZ ab (sonst trifft z. B. `Hannover` nur die Mitte). `1` = kein Sweep. **Mehr Punkte = mehr TK-Abfragen** (Tageskontingent, s. u.). |
| `-Out`        | Optionaler JSON-Zielpfad. Standard: `assets\aerzte_<Nrn>_<Ort>_<Zeitstempel>.json`. |
| `-Help`       | Bedienhinweise + Fachgebiets-Tabelle. |

## PLZ-Sweep (Ortsabdeckung)

Die TK-Suche ist technisch **„Punkt + adaptiver Radius"**: Ein einzelnes `Hannover` löst
serverseitig nur zum Stadt-Zentroid (Mitte) auf, der Radius wächst nur bis „genug" Treffer da
sind – äußere Stadtteile fehlen. (Details: [`findings-ort-radius.md`](findings-ort-radius.md).)

Deshalb ermittelt das Tool für den Ort mehrere Suchpunkte:

1. Ort via **Nominatim** geokodieren → Bounding-Box.
2. Ein Kandidaten-Raster über die Box legen und per **Farthest-Point-Sampling** die `-Punkte`
   am weitesten auseinanderliegenden Punkte wählen (maximiert disjunkte Treffer).
3. Jeden Punkt per Reverse-Geocoding auf seine **PLZ** abbilden (die PLZ als `Ftg`-Text steuert
   das TK-Suchzentrum zuverlässig; übergebene Koordinaten ignoriert der Server).
4. Je Fachgebiet **×** Suchpunkt suchen und alle Treffer über die `e_id` **zusammenführen**.

Das CLI zeigt dabei die gewählten PLZ, je Punkt die Zahl neuer vs. bereits bekannter Treffer und
eine Zusammenfassung (roh/​eindeutig/​Überschneidungen). Randpunkte können in **angrenzende
Nachbargemeinden** reichen – das erhöht die Abdeckung des Ballungsraums bewusst; Duplikate werden
per e_id/E-Mail entfernt.

## Ablauf / Filterregeln

1. **Suche** im TK-Ärzteführer je Fachgebiet **×** PLZ-Suchpunkt (optional Geschlecht via
   TK-Parameter `Sl`). Alle Treffer werden zusammengeführt; jeder Arzt (`e_id`) wird nur
   **einmal** bearbeitet (dem zuerst findenden Fachgebiet zugeordnet, Feld `fachgebiet_such`).
2. **Detailseite** je Treffer → Name, Geschlecht (aus Anrede), Adresse, Abrechnungsart, Homepage.
3. Ärzte **ohne Homepage-Link werden ignoriert**.
4. **Impressum** (`/impressum` + Fallbacks) → E-Mail-Adresse (bevorzugt gleiche Domain wie die
   Homepage) und Adress-Verifikation gegen die TK-Adresse.
   - Weicht die Impressum-Adresse **deutlich ab (andere Stadt)**, wird der Arzt **ignoriert**.
   - `adresse_status`: `verifiziert` | `nicht-pruefbar` (keine Adresse im Impressum gefunden).
   - E-Mails von Widgets/Tracking sowie **KIM/Telematik-Adressen** (`…telematik`, keine echte
     E-Mail) werden herausgefiltert.
5. Ärzte **ohne E-Mail** werden **verworfen**; **doppelte E-Mail-Adressen** werden übersprungen
   (jede Adresse nur einmal).
6. Ergebnis als **JSON in `assets/`** inkl. Suchparametern, Sweep-Punkten und Statistik.

## Projektstruktur

```
Find-Doctors.ps1        # CLI / Orchestrierung
lib/
  Fachgebiete.ps1       # Nummer -> Fachgebiet (Mapping + -Help-Tabelle)
  GeoSweep.ps1          # PLZ-Suchpunkte via Nominatim (Bounding-Box + Farthest-Point-Sampling)
  TkSearch.ps1          # Suche -> Eintrags-IDs (+ Kontingent-Erkennung)
  TkDetail.ps1          # Detailseite parsen
  Impressum.ps1         # E-Mail finden + Adresse verifizieren
assets/                 # JSON-Ergebnisse
findings-ort-radius.md  # Recherche zum Such-Radius / PLZ-Sweep
```

## Bekannte Grenzen

- **TK-Tageskontingent:** Der TK-Ärzteführer begrenzt die Datenbankabfragen **pro IP und Tag**
  (jede Suche **und** jede Detailseite zählt). Der PLZ-Sweep **vervielfacht** die Suchabfragen
  (Fachgebiete × `-Punkte`) und deckt entsprechend mehr Ärzte (= mehr Detailseiten) auf. Ist das
  Kontingent erschöpft, liefert der Server eine Fehlerseite (Code `601`); das Tool erkennt das und
  bricht mit klarem Hinweis ab (bereits gefundene Treffer werden gespeichert). Am Folgetag steht
  die Suche wieder zur Verfügung. → `-Punkte` bewusst wählen; ggf. auf mehrere Tage verteilen.
- **Nominatim/OpenStreetMap** (für den Sweep) ist ein öffentlicher Dienst mit Fair-Use-Limit
  (~1 Anfrage/s). Das Tool hält das Limit ein; bei Ausfall wird auf den Ort-Text zurückgefallen.
- **Randpunkte** des Sweeps können in **Nachbargemeinden** reichen (z. B. „Hannover" → Empelde/
  Ronnenberg). Das ist gewollt (Ballungsraum-Abdeckung); die Adress-Verifikation prüft gegen die
  **eigene** TK-Adresse des Arztes, nicht gegen den Suchort.
- **Nur Ärzte mit Praxis-Homepage** liefern eine E-Mail; ohne Homepage-Link werden sie
  (gewollt) übersprungen.
- Bei **großen Kliniken/MVZ** kann die gefundene E-Mail eine zentrale bzw. fremde Adresse sein,
  und die Impressum-Adresse (Rechtsträger) kann von der Praxisadresse abweichen.
- Der TK-Ärzteführer kennt nur **männlich/weiblich** – „divers" ist nicht filterbar.
