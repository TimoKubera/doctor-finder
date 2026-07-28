# TkSearch.ps1
# Fuehrt die Suche im TK-Aerztefuehrer aus und liefert die Eintrags-IDs (e_id) der Treffer.
# Der TK-Aerztefuehrer liefert alle Treffer auf EINER Seite (keine Pagination noetig).

$Global:TkBaseUrl   = 'https://www.tk-aerztefuehrer.de/TK/Suche_SN/index.js'
$Global:TkUserAgent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36'

function Invoke-TkHttpGet {
  # Robuster GET mit Retry. Gibt den Response-Content (String) zurueck oder $null.
  param(
    [string]$Uri,
    [int]$MaxRetries = 3,
    [int]$TimeoutSec = 30
  )
  for ($i = 1; $i -le $MaxRetries; $i++) {
    try {
      $resp = Invoke-WebRequest -Uri $Uri -UseBasicParsing -UserAgent $Global:TkUserAgent -TimeoutSec $TimeoutSec
      return [string]$resp.Content
    } catch {
      if ($i -eq $MaxRetries) {
        Write-Warning "GET fehlgeschlagen ($Uri): $($_.Exception.Message)"
        return $null
      }
      Start-Sleep -Seconds ([Math]::Min(5, $i * 2))
    }
  }
  return $null
}

function Test-TkQuotaError {
  # Erkennt die TK-Fehlerseite "Kontingent fuer heute ausgeschoepft" (Code 601).
  # Der TK-Aerztefuehrer begrenzt DB-Abfragen pro IP und Tag (Suche + jede Detailseite zaehlen).
  param([string]$Html)
  if (-not $Html) { return $false }
  return ($Html -match 'Kontingent' -and $Html -match '(?i)ausgesch') -or ($Html -match '\(601\)')
}

function Search-TkAerzte {
  # Baut die Such-URL und extrahiert die eindeutigen e_ids in Fundreihenfolge.
  # Geschlecht: '1' = maennlich, '2' = weiblich, '' = alle (TK-Parameter Sl).
  param(
    [Parameter(Mandatory)][string]$FachgebietNr,
    [Parameter(Mandatory)][string]$Ort,
    [string]$GeschlechtSl = '',
    [switch]$Quiet   # unterdrueckt die eigene Konsolenausgabe (fuer den PLZ-Sweep)
  )

  $ortEnc = [uri]::EscapeDataString($Ort)
  $uri = '{0}?a=DL&Ft=&Ft_e=&Ftg={1}&Ftg_e=&Sl={2}&Otn1={3}&Otn2=&Sid=&Db=1' -f `
         $Global:TkBaseUrl, $ortEnc, $GeschlechtSl, $FachgebietNr

  if (-not $Quiet) { Write-Host "Suche im TK-Aerztefuehrer ..." -ForegroundColor Cyan }
  $html = Invoke-TkHttpGet -Uri $uri
  if ($null -eq $html) { return @() }

  # TK-Tageskontingent erschoepft? -> klar melden statt "keine Treffer"
  if (Test-TkQuotaError -Html $html) {
    Write-Warning ('TK-Tageskontingent fuer diese IP erschoepft (Fehler 601) - ' +
      'die Suche ist erst morgen wieder verfuegbar.')
    return ,'__QUOTA__'
  }

  # Trefferzahl (nur informativ)
  $count = $null
  $mCount = [regex]::Match($html, '(\d+)\s+Ergebnisse')
  if ($mCount.Success) { $count = $mCount.Groups[1].Value }

  # e_ids einsammeln (Reihenfolge erhalten, Duplikate entfernen)
  $ids = New-Object System.Collections.Generic.List[string]
  $seen = @{}
  foreach ($m in [regex]::Matches($html, 'e_id=(\d+)')) {
    $id = $m.Groups[1].Value
    if (-not $seen.ContainsKey($id)) { $seen[$id] = $true; $ids.Add($id) }
  }

  if (-not $Quiet) {
    if ($count) {
      Write-Host ("TK meldet {0} Ergebnisse, {1} eindeutige Eintraege gefunden." -f $count, $ids.Count) -ForegroundColor Green
    } else {
      Write-Host ("{0} eindeutige Eintraege gefunden." -f $ids.Count) -ForegroundColor Green
    }
  }
  return $ids.ToArray()
}
