<#
.SYNOPSIS
  Doctor Finder - findet Aerztinnen/Aerzte im TK-Aerztefuehrer, ermittelt ueber die
  Praxis-Homepage (Impressum) die E-Mail-Adresse und verifiziert die Adresse.

.DESCRIPTION
  Ablauf:
    1. Suche im TK-Aerztefuehrer nach Fachgebiet + Ort (optional Geschlecht).
    2. Detailseite je Treffer -> Name, Geschlecht, Adresse, Abrechnungsart, Homepage.
    3. Aerzte OHNE Homepage-Link werden ignoriert.
    4. Homepage/Impressum -> E-Mail + Adress-Verifikation.
       Weicht die Impressum-Adresse deutlich ab (andere Stadt), wird der Arzt ignoriert.
    5. Ergebnis als JSON in .\assets\ .

.PARAMETER Fachgebiet
  Eine oder mehrere Fachgebiets-Nummern (siehe -Help fuer die vollstaendige Liste).
  Mehrere Nummern koennen komma- und/oder leerzeichengetrennt angegeben werden, z. B.
  "-Fachgebiet 23,24,25" oder "-Fachgebiet 23 24 25" (auch gemischt). Z. B. 1 = Allergologie.

.PARAMETER Ort
  Ort / Stadtteil / PLZ (Pflichtfeld des TK-Aerztefuehrers). Z. B. "Hannover" oder "30159".

.PARAMETER Geschlecht
  Optionaler Geschlechtsfilter: m / maennlich  oder  w / weiblich.
  Ohne Angabe werden Aerzte jeden Geschlechts beruecksichtigt.
  Hinweis: Der TK-Aerztefuehrer kennt nur maennlich/weiblich - "divers" ist nicht filterbar.

.PARAMETER Punkte
  Anzahl der PLZ-Suchpunkte fuer die Ortsabdeckung (Standard: 5). Die TK-Suche zentriert nur
  auf einen Punkt mit adaptivem Radius; "Hannover" trifft daher nur die Mitte. Der Sweep ermittelt
  via Nominatim mehrere weit auseinanderliegende PLZ und fuehrt die Treffer zusammen (Dedup ueber
  e_id/E-Mail). 1 = kein Sweep (nur der Ort-Text). Mehr Punkte = mehr TK-Abfragen (Tageskontingent).

.PARAMETER Out
  Optionaler Zielpfad fuer die JSON-Datei. Standard: .\assets\aerzte_<Fachgebiet>_<Ort>_<Zeitstempel>.json

.PARAMETER Help
  Zeigt Bedienhinweise und die vollstaendige Fachgebiets-Tabelle.

.EXAMPLE
  .\Find-Doctors.ps1 -Help

.EXAMPLE
  .\Find-Doctors.ps1 -Fachgebiet 1 -Ort Hannover

.EXAMPLE
  .\Find-Doctors.ps1 -Fachgebiet 23,24,25 -Ort Hannover

.EXAMPLE
  .\Find-Doctors.ps1 -Fachgebiet 23 24 25 -Ort Hannover -Geschlecht w
#>
# PositionalBinding=$false: nur benannte Parameter binden positional; alle uebrigen
# Tokens (z. B. leerzeichengetrennte Fachgebiets-Nummern) landen in $Rest.
[CmdletBinding(PositionalBinding=$false)]
param(
  [string[]]$Fachgebiet,
  [string]$Ort,
  [string]$Geschlecht,
  [int]$Punkte = 5,
  [string]$Out,
  [switch]$Help,
  # Faengt zusaetzliche, leerzeichengetrennte Fachgebiets-Nummern auf, z. B.
  #   -Fachgebiet 23 24 25   ->  Fachgebiet=@('23'), Rest=@('24','25')
  [Parameter(ValueFromRemainingArguments=$true)]
  [string[]]$Rest
)

$ErrorActionPreference = 'Stop'
# TLS 1.2 erzwingen (Windows PowerShell 5.1 nutzt sonst veraltete Protokolle)
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch { }

# --- Module laden ---
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $here 'lib\Fachgebiete.ps1')
. (Join-Path $here 'lib\TkSearch.ps1')
. (Join-Path $here 'lib\TkDetail.ps1')
. (Join-Path $here 'lib\Impressum.ps1')
. (Join-Path $here 'lib\GeoSweep.ps1')

function Show-Usage {
  Write-Host ''
  Write-Host 'Doctor Finder - TK-Aerztefuehrer Crawler' -ForegroundColor Cyan
  Write-Host '========================================'
  Write-Host 'Verwendung:'
  Write-Host '  .\Find-Doctors.ps1 -Fachgebiet <Nr[,Nr,...]> -Ort <Ort> [-Geschlecht m|w] [-Out <Datei>]'
  Write-Host ''
  Write-Host '  -Fachgebiet   Eine oder mehrere Nummern (siehe Tabelle unten). Beispiel: 1 = Allergologie'
  Write-Host '                Mehrere: -Fachgebiet 23,24,25  oder  -Fachgebiet 23 24 25  (auch gemischt).'
  Write-Host '  -Ort          Ort / Stadtteil / PLZ (Pflichtfeld). Beispiel: Hannover'
  Write-Host '  -Geschlecht   Optional: m (maennlich) oder w (weiblich). Ohne Angabe: alle.'
  Write-Host '                Hinweis: "divers" wird vom TK-Aerztefuehrer nicht unterstuetzt.'
  Write-Host '  -Punkte       Anzahl der PLZ-Suchpunkte fuer die Ortsabdeckung (Standard: 5).'
  Write-Host '                Deckt das Stadtgebiet mit mehreren weit auseinanderliegenden PLZ ab'
  Write-Host '                (sonst trifft z. B. "Hannover" nur die Mitte). 1 = kein Sweep.'
  Write-Host '                Achtung: mehr Punkte = mehr TK-Abfragen (Tageskontingent!).'
  Write-Host '  -Out          Optionaler JSON-Zielpfad (Standard: .\assets\...).'
  Write-Host ''
  Write-Host 'Ohne -Fachgebiet/-Ort werden die Angaben interaktiv abgefragt.'
  Show-FachgebietTabelle
}

# --- Fachgebiets-Eingaben in eine eindeutige Nummernliste normalisieren ---
function ConvertTo-FachgebietListe {
  # Nimmt beliebig viele Roh-Tokens (aus -Fachgebiet und $Rest) und liefert eine
  # deduplizierte Liste von Nummern-Strings. Trennt an Komma UND/ODER Whitespace,
  # akzeptiert also "23,24", "23, 24", "23 ,24", "23 24" und Mischformen.
  param([string[]]$Tokens)
  $out = New-Object System.Collections.Generic.List[string]
  $seen = @{}
  foreach ($t in $Tokens) {
    if ($null -eq $t) { continue }
    foreach ($part in ($t -split '[,\s]+')) {
      $p = $part.Trim()
      if ($p -eq '') { continue }
      if (-not $seen.ContainsKey($p)) { $seen[$p] = $true; $out.Add($p) }
    }
  }
  return $out.ToArray()
}

# --- Geschlecht -> TK-Parameter Sl ---
function Resolve-GeschlechtSl {
  param([string]$G)
  if (-not $G) { return @{ Sl = ''; Label = 'alle' } }
  switch -Regex ($G.Trim().ToLower()) {
    '^(m|mann|maennlich|male)$'  { return @{ Sl = '1'; Label = 'maennlich' } }
    '^(w|f|frau|weiblich|female)$' { return @{ Sl = '2'; Label = 'weiblich' } }
    '^(d|divers)$' {
      Write-Warning 'Der TK-Aerztefuehrer kennt kein Geschlecht "divers" - es wird ohne Geschlechtsfilter gesucht.'
      return @{ Sl = ''; Label = 'alle (divers nicht filterbar)' }
    }
    default {
      Write-Warning "Unbekannter Geschlechtswert '$G' - es wird ohne Geschlechtsfilter gesucht."
      return @{ Sl = ''; Label = 'alle' }
    }
  }
}

# ============================ Hauptprogramm ============================

if ($Help) { Show-Usage; return }

# --- Fachgebiets-Nummern einsammeln (aus -Fachgebiet + $Rest) ---
$fgList = ConvertTo-FachgebietListe -Tokens (@($Fachgebiet) + @($Rest))

# --- Interaktive Abfrage, falls keine Nummer uebergeben wurde ---
if ($fgList.Count -eq 0) {
  Write-Host 'Tipp: Mit  .\Find-Doctors.ps1 -Help  sehen Sie alle Fachgebiets-Nummern.' -ForegroundColor DarkGray
  $raw = (Read-Host 'Fachgebiets-Nummer(n) (z. B. 23,24,25 - "?" fuer Liste)').Trim()
  if ($raw -eq '?') { Show-FachgebietTabelle; $raw = (Read-Host 'Fachgebiets-Nummer(n)').Trim() }
  $fgList = ConvertTo-FachgebietListe -Tokens @($raw)
}
if ($fgList.Count -eq 0) {
  Write-Host 'Keine Fachgebiets-Nummer angegeben - Abbruch.' -ForegroundColor Red
  return
}

# --- Nummern validieren: ungueltige aussortieren (mit Hinweis) ---
$fgValid = New-Object System.Collections.Generic.List[string]
$fgInvalid = New-Object System.Collections.Generic.List[string]
foreach ($nr in $fgList) {
  if (Test-Fachgebiet -Nummer $nr) { $fgValid.Add($nr) } else { $fgInvalid.Add($nr) }
}
if ($fgInvalid.Count -gt 0) {
  Write-Host ("Ungueltige Fachgebiets-Nummer(n) ignoriert: {0}" -f ($fgInvalid -join ', ')) -ForegroundColor Yellow
  Write-Host 'Gueltige Nummern siehe -Help.' -ForegroundColor Yellow
}
if ($fgValid.Count -eq 0) {
  Write-Host 'Keine gueltige Fachgebiets-Nummer angegeben - Abbruch.' -ForegroundColor Red
  return
}
$fgList = $fgValid.ToArray()

# Nummer -> Name (fuer Anzeige, JSON und pro-Arzt-Zuordnung)
$fgNames = [ordered]@{}
foreach ($nr in $fgList) { $fgNames[$nr] = Get-FachgebietName -Nummer $nr }
$fachLabel = (($fgList | ForEach-Object { '{0} (Nr. {1})' -f $fgNames[$_], $_ }) -join ', ')

if (-not $Ort) {
  $Ort = (Read-Host 'Ort / Stadtteil / PLZ (Pflichtfeld, z. B. Hannover)').Trim()
}
if (-not $Ort) { Write-Host 'Kein Ort angegeben - Abbruch.' -ForegroundColor Red; return }

$g = Resolve-GeschlechtSl -G $Geschlecht

# --- Suchpunkte (PLZ-Sweep) bestimmen ---
# Die TK-Suche ist "Punkt + adaptiver Radius": ein einzelnes "Hannover" trifft nur die Mitte.
# Wir decken das Stadtgebiet mit mehreren, weit auseinanderliegenden PLZ ab und fuehren die
# Treffer zusammen. -Punkte 1 deaktiviert den Sweep (nur der Ort-Text als Einzelpunkt).
$sweep = @()
if ($Punkte -gt 1) {
  Write-Host ("Ermittle bis zu {0} Suchpunkte (PLZ) fuer '{1}' via Nominatim ..." -f $Punkte, $Ort) -ForegroundColor DarkGray
  $sweep = @(Get-OrtSweepPunkte -Ort $Ort -Anzahl $Punkte)
}
if ($sweep.Count -gt 0) {
  $searchLocs = @($sweep | ForEach-Object { $_.plz })
} else {
  if ($Punkte -gt 1) {
    Write-Warning "Keine Sweep-Punkte ermittelt (Nominatim nicht erreichbar?) - nutze '$Ort' als Einzelpunkt."
  }
  $searchLocs = @($Ort)
}

Write-Host ''
Write-Host "Suche nach:   $fachLabel" -ForegroundColor Yellow
Write-Host "Ort:          $Ort" -ForegroundColor Yellow
if ($sweep.Count -gt 0) {
  Write-Host ("Suchpunkte:   {0}" -f (($sweep | ForEach-Object {
    '{0} ({1}{2})' -f $_.plz, $_.richtung, ($(if ($_.ortsteil) { ', ' + $_.ortsteil } else { '' }))
  }) -join ' | ')) -ForegroundColor Yellow
} else {
  Write-Host "Suchpunkte:   1 (Ort-Text, kein Sweep)" -ForegroundColor Yellow
}
Write-Host "Geschlecht:   $($g.Label)" -ForegroundColor Yellow
Write-Host ''

# --- 1) Suche je Fachgebiet x Suchpunkt; e_ids global deduplizieren ---
# Ein Arzt kann in mehreren Fachgebieten/Punkten auftauchen -> jede e_id nur EINMAL bearbeiten.
# $eidToFg merkt sich, welches gesuchte Fachgebiet die e_id zuerst geliefert hat.
# Zusaetzlich wird pro Suchpunkt protokolliert, wie viele NEUE (nicht schon gesehene) Aerzte
# er beisteuert und wie stark sich die Punkte ueberschneiden (Feedback fuer den Nutzer).

# Anzeige-Label je Suchort (PLZ -> "PLZ (Richtung, Ortsteil)")
$locLabel = @{}
foreach ($sp in $sweep) {
  $locLabel[$sp.plz] = ('{0} ({1}{2})' -f $sp.plz, $sp.richtung, `
    ($(if ($sp.ortsteil) { ', ' + $sp.ortsteil } else { '' })))
}

$eidToFg       = [ordered]@{}
$rawTotal      = 0                # Summe aller roh gefundenen Treffer (mit Ueberschneidungen)
$beitragProLoc = [ordered]@{}     # Suchort -> Anzahl NEU beigesteuerter Aerzte
foreach ($loc in $searchLocs) { $beitragProLoc[$loc] = 0 }
$quotaHit = $false

foreach ($nr in $fgList) {
  if ($fgList.Count -gt 1) {
    Write-Host ("--- Fachgebiet {0} (Nr. {1}) ---" -f $fgNames[$nr], $nr) -ForegroundColor Cyan
  }
  foreach ($loc in $searchLocs) {
    $ids = @(Search-TkAerzte -FachgebietNr $nr -Ort $loc -GeschlechtSl $g.Sl -Quiet)
    if ($ids -contains '__QUOTA__') { $quotaHit = $true; break }
    $rawTotal += $ids.Count
    $neu = 0
    foreach ($id in $ids) {
      if (-not $eidToFg.Contains($id)) { $eidToFg[$id] = $nr; $neu++; $beitragProLoc[$loc]++ }
    }
    $ueberlappt = $ids.Count - $neu
    $label = if ($locLabel.ContainsKey($loc)) { $locLabel[$loc] } else { $loc }
    $olTxt = if ($ueberlappt -gt 0) { ", $ueberlappt bereits bekannt" } else { '' }
    Write-Host ("  Suchpunkt {0}: {1} Treffer, {2} neu{3}" -f $label, $ids.Count, $neu, $olTxt) -ForegroundColor Gray
    Start-Sleep -Milliseconds 800   # Hoeflichkeit zwischen Suchabfragen
  }
  if ($quotaHit) { break }
}
if ($quotaHit) {
  Write-Host ''
  Write-Host 'Abbruch: TK-Tageskontingent fuer diese IP erschoepft (Fehler 601).' -ForegroundColor Red
  Write-Host 'Die Suche steht erst am naechsten Tag wieder zur Verfuegung.' -ForegroundColor Red
  return
}
$eIds = @($eidToFg.Keys)
if ($eIds.Count -eq 0) {
  Write-Host 'Keine Treffer.' -ForegroundColor Red
  return
}

# --- Sweep-/Suchpunkt-Zusammenfassung (Feedback an den Nutzer) ---
$ueberschneidungen = $rawTotal - $eIds.Count
Write-Host ''
Write-Host '--------- Suchpunkt-Zusammenfassung ---------' -ForegroundColor Cyan
Write-Host ("Suchpunkte (PLZ):            {0}" -f $searchLocs.Count)
Write-Host ("Suchlaeufe (Fachg. x Punkt): {0}" -f ($fgList.Count * $searchLocs.Count))
Write-Host ("Treffer gesamt (roh):        {0}" -f $rawTotal)
Write-Host ("Eindeutige Aerzte (Merge):   {0}" -f $eIds.Count)
Write-Host ("Ueberschneidungen:           {0}" -f $ueberschneidungen)
if ($searchLocs.Count -gt 1) {
  Write-Host 'Neue Aerzte je Suchpunkt:'
  foreach ($loc in $searchLocs) {
    $label = if ($locLabel.ContainsKey($loc)) { $locLabel[$loc] } else { $loc }
    Write-Host ("  {0}: {1}" -f $label, $beitragProLoc[$loc])
  }
}
Write-Host ''

# Beitrag (neue Aerzte) an die Sweep-Punkte anheften (fuer die JSON-Ausgabe)
foreach ($sp in $sweep) {
  $sp | Add-Member -NotePropertyName beitrag -NotePropertyValue ([int]$beitragProLoc[$sp.plz]) -Force
}

# --- 2..4) Detailseiten + Impressum ---
$ergebnisse = New-Object System.Collections.Generic.List[object]
$stat = [ordered]@{
  treffer            = $eIds.Count
  such_punkte        = $searchLocs.Count
  such_laeufe        = ($fgList.Count * $searchLocs.Count)
  treffer_roh        = $rawTotal
  ueberschneidungen  = $ueberschneidungen
  ohne_homepage      = 0
  andere_stadt       = 0
  ohne_email         = 0
  duplikat_email     = 0
  uebernommen        = 0
}

# Bereits gesehene E-Mail-Adressen (Deduplizierung ueber alle Treffer)
$seenEmails = @{}

$idx = 0
foreach ($eId in $eIds) {
  $idx++
  Write-Host ("[{0}/{1}] Eintrag {2} ..." -f $idx, $eIds.Count, $eId) -ForegroundColor DarkCyan

  $detailHtml = Invoke-TkHttpGet -Uri (Get-TkDetailUrl -EId $eId)
  if (-not $detailHtml) { continue }
  # Kontingent kann mitten im Lauf greifen -> abbrechen, bisher Gefundenes behalten
  if (Test-TkQuotaError -Html $detailHtml) {
    Write-Host ''
    Write-Host 'Abbruch: TK-Tageskontingent waehrend des Laufs erschoepft (Fehler 601).' -ForegroundColor Red
    Write-Host ('Bis hierhin gefundene Treffer ({0}) werden gespeichert.' -f $ergebnisse.Count) -ForegroundColor Yellow
    break
  }
  $doc = ConvertFrom-TkDetail -Html $detailHtml -EId $eId
  if (-not $doc) { continue }

  # Regel: Geschlechtsfilter zur Sicherheit auch clientseitig anwenden
  if ($g.Sl -eq '1' -and $doc.geschlecht -ne 'maennlich') { continue }
  if ($g.Sl -eq '2' -and $doc.geschlecht -ne 'weiblich')  { continue }

  # Regel: ohne Homepage-Link -> ignorieren
  if (-not $doc.homepage) {
    $stat.ohne_homepage++
    Write-Host "        keine Homepage -> ignoriert" -ForegroundColor DarkGray
    continue
  }

  # Impressum: E-Mail + Adressverifikation
  $contact = Resolve-DoctorContact -Homepage $doc.homepage -TkOrt $doc.ort -TkPlz $doc.plz

  # Regel: deutlich abweichende Adresse (andere Stadt) -> ignorieren
  if ($contact.adresse_status -eq 'andere-stadt') {
    $stat.andere_stadt++
    Write-Host ("        Impressum-Adresse in anderer Stadt -> ignoriert ({0})" -f $doc.homepage) -ForegroundColor DarkGray
    continue
  }

  # Regel: ohne E-Mail -> verwerfen (bringt uns nicht weiter)
  if (-not $contact.email) {
    $stat.ohne_email++
    Write-Host "        keine E-Mail -> verworfen" -ForegroundColor DarkGray
    continue
  }

  # Regel: doppelte E-Mail-Adresse -> nur den ersten Treffer behalten
  $emailKey = $contact.email.Trim().ToLower()
  if ($seenEmails.ContainsKey($emailKey)) {
    $stat.duplikat_email++
    Write-Host ("        doppelte E-Mail ({0}) -> uebersprungen" -f $contact.email) -ForegroundColor DarkGray
    continue
  }
  $seenEmails[$emailKey] = $true

  $eintrag = [PSCustomObject]@{
    name            = $doc.name
    vorname         = $doc.vorname
    nachname        = $doc.nachname
    titel           = $doc.titel
    geschlecht      = $doc.geschlecht
    fachgebiet      = $doc.fachgebiet
    fachgebiet_such = $fgNames[$eidToFg[$eId]]
    strasse         = $doc.strasse
    plz             = $doc.plz
    ort             = $doc.ort
    telefon         = $doc.telefon
    abrechnungsart  = $doc.abrechnungsart
    homepage        = $doc.homepage
    email           = $contact.email
    adresse_status  = $contact.adresse_status
    impressum_url   = $contact.impressum_url
    profil_url      = $doc.profil_url
  }
  $ergebnisse.Add($eintrag)
  $stat.uebernommen++
  Write-Host ("        OK - {0} | {1} | Adresse: {2}" -f `
      $doc.name, $contact.email, $contact.adresse_status) -ForegroundColor Green

  Start-Sleep -Milliseconds 1000  # Hoeflichkeit gegenueber den Servern
}

# --- 5) JSON-Ausgabe nach assets\ ---
$assetsDir = Join-Path $here 'assets'
if (-not (Test-Path $assetsDir)) { New-Item -ItemType Directory -Path $assetsDir | Out-Null }

if (-not $Out) {
  $ortSlug  = ($Ort -replace '[^A-Za-z0-9]', '_')
  $fgSlug   = ($fgList -join '-')
  $stamp    = Get-Date -Format 'yyyyMMdd_HHmmss'
  $Out = Join-Path $assetsDir ("aerzte_{0}_{1}_{2}.json" -f $fgSlug, $ortSlug, $stamp)
}
# Relativen -Out-Pfad in absoluten Pfad aufloesen (.NET nutzt sonst ein abweichendes CWD)
if (-not [System.IO.Path]::IsPathRooted($Out)) { $Out = Join-Path (Get-Location).Path $Out }
$outDir = Split-Path -Parent $Out
if ($outDir -and -not (Test-Path $outDir)) { New-Item -ItemType Directory -Path $outDir -Force | Out-Null }

$payload = [PSCustomObject]@{
  suche = [PSCustomObject]@{
    fachgebiete     = @($fgList | ForEach-Object { [PSCustomObject]@{ nr = $_; name = $fgNames[$_] } })
    ort             = $Ort
    such_punkte     = @($searchLocs)
    sweep           = @($sweep)
    geschlecht      = $g.Label
    zeitpunkt       = (Get-Date).ToString('s')
  }
  statistik = [PSCustomObject]$stat
  aerzte    = $ergebnisse
}

$json = $payload | ConvertTo-Json -Depth 6
# UTF-8 ohne BOM schreiben (Out-File -Encoding utf8 wuerde in PS 5.1 ein BOM setzen)
[System.IO.File]::WriteAllText($Out, $json, (New-Object System.Text.UTF8Encoding($false)))

# --- Zusammenfassung ---
Write-Host ''
Write-Host '================ Zusammenfassung ================' -ForegroundColor Cyan
Write-Host ("TK-Treffer gesamt:             {0}" -f $stat.treffer)
Write-Host ("  ohne Homepage (ignoriert):   {0}" -f $stat.ohne_homepage)
Write-Host ("  andere Stadt  (ignoriert):   {0}" -f $stat.andere_stadt)
Write-Host ("  ohne E-Mail   (verworfen):   {0}" -f $stat.ohne_email)
Write-Host ("  doppelte Mail (uebersprungen): {0}" -f $stat.duplikat_email)
Write-Host ("uebernommen (mit E-Mail):      {0}" -f $stat.uebernommen)
Write-Host ''
Write-Host ("Ergebnis gespeichert: {0}" -f $Out) -ForegroundColor Green
