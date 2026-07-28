# Impressum.ps1
# Besucht die Arzt-Homepage / deren Impressum, extrahiert die E-Mail-Adresse und
# verifiziert die Adresse (Ort/PLZ) gegen die TK-Daten.

# Domains, die zwar im Impressum auftauchen, aber NICHT die Praxis-Adresse sind
# (Datenschutzbeauftragte, KV, Aufsichtsbehoerden, Webdesigner, Tracking).
$Global:EmailBlacklist = @(
  'kvsachsen', 'kvno', 'kbv.de', 'aerztekammer', 'datenschutz', 'dsgvo',
  'sentry', 'example', 'wixpress', 'domain.de', 'muster', 'ihre-domain',
  'sitejet', 'jimdo', 'wordpress', 'googlemail-noreply',
  # Widgets / Tracking / Standard-Bibliotheken (keine Praxis-Adressen)
  'hcaptcha', 'recaptcha', 'captcha', 'gstatic', 'googleapis', 'cloudflare',
  'w3.org', 'schema.org', 'sentry.io', 'noreply', 'no-reply',
  'osmfoundation', 'openstreetmap', 'mapbox', 'leafletjs',
  # KIM / Telematikinfrastruktur (sichere Arzt-Kommunikation, KEINE nutzbare E-Mail)
  'telematik', '.kim.'
)

function Get-HostRoot {
  # Liefert die "registrierbare" Domain grob als letzte zwei Labels (ohne www).
  param([string]$UrlOrHost)
  if (-not $UrlOrHost) { return '' }
  $h = $UrlOrHost
  if ($h -match '^https?://') { try { $h = ([uri]$h).Host } catch { } }
  $h = $h -replace '^www\.', ''
  $parts = $h.Split('.')
  if ($parts.Count -ge 2) { return ($parts[($parts.Count-2)..($parts.Count-1)] -join '.').ToLower() }
  return $h.ToLower()
}

function Invoke-HttpGetOnce {
  # Ein einzelner GET ohne Retry; gibt bei Fehler/Non-200 $null zurueck (fuer Impressum-Probing).
  param([string]$Uri, [int]$TimeoutSec = 20)
  try {
    $resp = Invoke-WebRequest -Uri $Uri -UseBasicParsing -UserAgent $Global:TkUserAgent -TimeoutSec $TimeoutSec -ErrorAction Stop
    return [string]$resp.Content
  } catch {
    return $null
  }
}

function Get-EmailCandidates {
  # Sammelt E-Mail-Adressen aus HTML: mailto-Links, Klartext, einfache (at)/(dot)-Verschleierung.
  param([string]$Html)
  $found = New-Object System.Collections.Generic.List[string]
  if (-not $Html) { return @() }

  # 1) mailto:-Links (haeufig prozent-kodiert -> dekodieren)
  foreach ($m in [regex]::Matches($Html, 'mailto:([^"''?\s>&]+)')) {
    $addr = $m.Groups[1].Value
    try { $addr = [uri]::UnescapeDataString($addr) } catch { }
    $found.Add($addr)
  }

  # 2) Klartext-Adressen
  foreach ($m in [regex]::Matches($Html, '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')) {
    $found.Add($m.Value)
  }

  # 3) Einfache Verschleierung: name (at) domain (dot) tld
  foreach ($m in [regex]::Matches($Html, '([A-Za-z0-9._%+-]+)\s*(?:\(at\)|\[at\]|\sat\s|&#64;)\s*([A-Za-z0-9.-]+)\s*(?:\(dot\)|\[dot\]|\sdot\s|\.)\s*([A-Za-z]{2,})')) {
    $found.Add(('{0}@{1}.{2}' -f $m.Groups[1].Value, $m.Groups[2].Value, $m.Groups[3].Value))
  }

  # Normalisieren, filtern, deduplizieren
  $clean = @{}
  $result = New-Object System.Collections.Generic.List[string]
  foreach ($e in $found) {
    $e = $e.Trim().TrimEnd('.').ToLower()
    if ($e -notmatch '^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$') { continue }
    if ($e -match '\.(png|jpg|jpeg|gif|svg|webp|css|js|ico)$') { continue }
    $isBlacklisted = $false
    foreach ($b in $Global:EmailBlacklist) { if ($e -like "*$b*") { $isBlacklisted = $true; break } }
    if ($isBlacklisted) { continue }
    if (-not $clean.ContainsKey($e)) { $clean[$e] = $true; $result.Add($e) }
  }
  return $result.ToArray()
}

function Select-BestEmail {
  # Waehlt bevorzugt eine Adresse mit gleicher Domain wie die Homepage.
  param([string[]]$Emails, [string]$Homepage)
  if (-not $Emails -or $Emails.Count -eq 0) { return '' }
  $siteRoot = Get-HostRoot $Homepage
  if ($siteRoot) {
    foreach ($e in $Emails) {
      $dom = $e.Split('@')[1]
      if ((Get-HostRoot $dom) -eq $siteRoot) { return $e }
    }
  }
  return $Emails[0]
}

function Test-AddressMatch {
  # Vergleicht Ort/PLZ aus dem Impressum mit den TK-Daten.
  # Rueckgabe: 'verifiziert' | 'andere-stadt' | 'nicht-pruefbar'
  param([string]$Html, [string]$TkOrt, [string]$TkPlz)
  if (-not $Html) { return 'nicht-pruefbar' }

  $normalize = {
    param($s)
    if (-not $s) { return '' }
    $x = $s.ToLower()
    $x = [regex]::Replace($x, '\(.*?\)', ' ')          # (Saale) etc. entfernen
    $x = [regex]::Replace($x, '[^a-zäöüß]', ' ')
    return ([regex]::Replace($x, '\s+', ' ')).Trim()
  }
  $tkOrtN = & $normalize $TkOrt

  # Alle "PLZ Ort"-Paare aus dem Impressum sammeln
  $pairs = New-Object System.Collections.Generic.List[object]
  foreach ($m in [regex]::Matches($Html, '\b(\d{5})\s+([A-Za-zÄÖÜäöüß.\-()]+(?:[ /][A-Za-zÄÖÜäöüß.\-()]+){0,2})')) {
    $pairs.Add([PSCustomObject]@{ Plz = $m.Groups[1].Value; Ort = (& $normalize $m.Groups[2].Value) })
  }

  if ($pairs.Count -eq 0) { return 'nicht-pruefbar' }

  foreach ($p in $pairs) {
    if ($TkPlz -and $p.Plz -eq $TkPlz) { return 'verifiziert' }
    if ($tkOrtN -and $p.Ort) {
      if ($p.Ort -eq $tkOrtN -or $p.Ort -like "*$tkOrtN*" -or $tkOrtN -like "*$($p.Ort)*") {
        return 'verifiziert'
      }
    }
  }
  # Es gibt Adressangaben, aber keine passt -> andere Stadt.
  return 'andere-stadt'
}

function Resolve-DoctorContact {
  # Orchestriert: laedt Homepage + Impressum, extrahiert E-Mail und prueft die Adresse.
  # Liefert ein Objekt mit email, adresse_status und impressum_url.
  param(
    [Parameter(Mandatory)][string]$Homepage,
    [string]$TkOrt = '',
    [string]$TkPlz = ''
  )

  $base = $Homepage.TrimEnd('/')
  $rootHtml = Invoke-HttpGetOnce -Uri $base

  # Impressum-Kandidatenpfade der Reihe nach probieren
  $impressumUrl = ''
  $impressumHtml = $null
  foreach ($path in @('/impressum', '/impressum/', '/impressum.html', '/impressum.php', '/imprint', '/kontakt', '/kontakt/')) {
    $html = Invoke-HttpGetOnce -Uri ($base + $path)
    if ($html) { $impressumHtml = $html; $impressumUrl = $base + $path; break }
  }

  # E-Mail: zuerst Impressum, dann Homepage-Root
  $emails = @()
  if ($impressumHtml) { $emails = Get-EmailCandidates -Html $impressumHtml }
  if ((-not $emails -or $emails.Count -eq 0) -and $rootHtml) { $emails = Get-EmailCandidates -Html $rootHtml }
  $email = Select-BestEmail -Emails $emails -Homepage $Homepage

  # Adress-Verifikation: bevorzugt gegen Impressum, sonst gegen Homepage-Root
  $htmlForAddr = if ($impressumHtml) { $impressumHtml } else { $rootHtml }
  $status = Test-AddressMatch -Html $htmlForAddr -TkOrt $TkOrt -TkPlz $TkPlz

  return [PSCustomObject]@{
    email          = $email
    adresse_status = $status
    impressum_url  = $impressumUrl
  }
}
