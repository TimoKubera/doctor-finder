# GeoSweep.ps1
# Ermittelt fuer einen Ort mehrere weit auseinanderliegende Suchpunkte (PLZ).
#
# Hintergrund (siehe findings-ort-radius.md): Die TK-Suche ist "Punkt + adaptiver Radius".
# "Hannover" loest serverseitig nur zum Stadt-Zentroid (Mitte) auf, deshalb fehlen aeussere
# Stadtteile. Der Server ignoriert uebergebene Koordinaten (Ftg_e) und zentriert auf die
# BEKANNTE PLZ/Ort im Textfeld (Ftg). Wir decken das Stadtgebiet daher mit mehreren echten
# PLZ ab und fuehren die Treffer zusammen (Dedup ueber e_id/E-Mail im Hauptskript).
#
# Die PLZ werden generisch fuer JEDEN Ort ermittelt:
#   1. Ort via Nominatim geokodieren  -> Bounding-Box.
#   2. Zentrum + 4 Quadranten-Punkte (moeglichst weit auseinander) berechnen.
#   3. Jeden Punkt per Reverse-Geocoding auf seine PLZ abbilden, PLZ deduplizieren.

$Global:NominatimBase      = 'https://nominatim.openstreetmap.org'
# Nominatim verlangt einen aussagekraeftigen User-Agent (kein Browser-Default).
$Global:NominatimUserAgent = 'doctor-finder/1.0 (TK-Aerztefuehrer PLZ-Sweep)'

function Invoke-NominatimJson {
  # Einzelne Nominatim-Anfrage; $null bei Fehler.
  param([string]$Url, [int]$TimeoutSec = 25)
  try {
    return Invoke-RestMethod -Uri $Url -Headers @{ 'User-Agent' = $Global:NominatimUserAgent } -TimeoutSec $TimeoutSec -ErrorAction Stop
  } catch {
    Write-Warning "Nominatim-Anfrage fehlgeschlagen ($Url): $($_.Exception.Message)"
    return $null
  }
}

function Get-OrtSweepPunkte {
  # Liefert bis zu $Anzahl deduplizierte Suchpunkte (PLZ) fuer den Ort.
  # Rueckgabe: Array von PSCustomObject { plz, richtung, ortsteil, lat, lon }.
  # Leeres Array => Aufrufer faellt auf den Ort-Text als Einzelpunkt zurueck.
  param(
    [Parameter(Mandatory)][string]$Ort,
    [int]$Anzahl = 5,
    [double]$Streuung = 0.6   # 0..1: Anteil der halben Bounding-Box-Ausdehnung Richtung Ecke
  )

  # 1) Ort geokodieren -> Bounding-Box
  $geo = @(Invoke-NominatimJson ("{0}/search?q={1}&format=jsonv2&limit=1" -f `
            $Global:NominatimBase, [uri]::EscapeDataString($Ort)))
  if ($geo.Count -lt 1 -or -not $geo[0].boundingbox) { return @() }

  $bb    = $geo[0].boundingbox            # [south, north, west, east] (Strings)
  $south = [double]$bb[0]; $north = [double]$bb[1]
  $west  = [double]$bb[2]; $east  = [double]$bb[3]
  $cLat  = ($south + $north) / 2
  $cLon  = ($west + $east) / 2
  $f     = $Streuung
  $halfH = ($north - $south) / 2
  $halfW = ($east  - $west)  / 2

  # 2) Kandidatenraster ueber die Bounding-Box erzeugen (dicht genug fuer $Anzahl PLZ).
  #    fx/fy in -1..1 (skaliert mit $f), symmetrisch um das Zentrum.
  $steps = [Math]::Max(3, [int][Math]::Ceiling([Math]::Sqrt([double]$Anzahl)) + 2)
  $kandidaten = New-Object System.Collections.Generic.List[object]
  for ($iy = 0; $iy -lt $steps; $iy++) {
    for ($ix = 0; $ix -lt $steps; $ix++) {
      $fx = ($ix / ($steps - 1)) * 2 - 1     # -1 .. 1
      $fy = ($iy / ($steps - 1)) * 2 - 1
      $ns = if ($fy -gt 0.15) { 'N' } elseif ($fy -lt -0.15) { 'S' } else { '' }
      $we = if ($fx -gt 0.15) { 'O' } elseif ($fx -lt -0.15) { 'W' } else { '' }
      $ri = "$ns$we"; if (-not $ri) { $ri = 'Zentrum' }
      $kandidaten.Add([PSCustomObject]@{
        lat = $cLat + $f * $fy * $halfH
        lon = $cLon + $f * $fx * $halfW
        fx  = $fx; fy = $fy; ri = $ri
      })
    }
  }

  # 3) Kandidaten per Farthest-Point-Sampling ordnen (maximale Streuung):
  #    Start beim zentrumsnaechsten Punkt, dann jeweils der Punkt mit groesstem
  #    Mindestabstand zu den bereits gewaehlten.
  $latRad = $cLat * [Math]::PI / 180
  $sqDist = {
    param($a, $b)
    $dx = ($a.lon - $b.lon) * [Math]::Cos($latRad)
    $dy = ($a.lat - $b.lat)
    return $dx*$dx + $dy*$dy
  }
  $pool = [System.Collections.Generic.List[object]]$kandidaten
  $geordnet = New-Object System.Collections.Generic.List[object]
  # zentrumsnaechsten Kandidaten zuerst
  $start = $pool | Sort-Object { $_.fx*$_.fx + $_.fy*$_.fy } | Select-Object -First 1
  $geordnet.Add($start); $pool.Remove($start) | Out-Null
  while ($pool.Count -gt 0) {
    $best = $null; $bestMin = -1
    foreach ($c in $pool) {
      $min = [double]::MaxValue
      foreach ($s in $geordnet) { $d = & $sqDist $c $s; if ($d -lt $min) { $min = $d } }
      if ($min -gt $bestMin) { $bestMin = $min; $best = $c }
    }
    $geordnet.Add($best); $pool.Remove($best) | Out-Null
  }

  # 4) In dieser Reihenfolge reverse-geocoden, bis $Anzahl eindeutige PLZ zusammen sind.
  $ergebnis = New-Object System.Collections.Generic.List[object]
  $seenPlz  = @{}
  $maxTry   = [Math]::Min($geordnet.Count, ($Anzahl * 3 + 5))   # Nominatim-Aufrufe begrenzen
  $tries    = 0
  Start-Sleep -Seconds 1   # Rate-Limit nach dem search-Call (Nominatim: max ~1 Req/s)

  $inv = [System.Globalization.CultureInfo]::InvariantCulture
  foreach ($k in $geordnet) {
    if ($ergebnis.Count -ge $Anzahl) { break }
    if ($tries -ge $maxTry) { break }
    $tries++
    # Koordinaten IMMER mit Punkt als Dezimaltrenner (invariant), sonst 400 von Nominatim.
    $latS = $k.lat.ToString($inv); $lonS = $k.lon.ToString($inv)
    $rev = Invoke-NominatimJson ("{0}/reverse?lat={1}&lon={2}&format=jsonv2&addressdetails=1" -f `
             $Global:NominatimBase, $latS, $lonS)
    Start-Sleep -Seconds 1
    if (-not $rev -or -not $rev.address) { continue }

    $plz = [string]$rev.address.postcode
    if (-not $plz) { continue }
    if ($seenPlz.ContainsKey($plz)) { continue }
    $seenPlz[$plz] = $true

    $label = $rev.address.suburb
    if (-not $label) { $label = $rev.address.city_district }
    if (-not $label) { $label = $rev.address.town }
    if (-not $label) { $label = $rev.address.village }

    $ergebnis.Add([PSCustomObject]@{
      plz      = $plz
      richtung = $k.ri
      ortsteil = [string]$label
      lat      = [math]::Round($k.lat, 5)
      lon      = [math]::Round($k.lon, 5)
    })
  }

  return $ergebnis.ToArray()
}
