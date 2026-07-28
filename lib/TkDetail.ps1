# TkDetail.ps1
# Parst eine TK-Detailseite (a=DD) zu einem Arzt-Objekt.
# Die zuverlaessigste Quelle auf der Seite ist der clientseitige vCard-Aufbau
# (addName / addAddress) sowie die itemprop-Auszeichnungen.

function Get-TkDetailUrl {
  param([Parameter(Mandatory)][string]$EId)
  return ('{0}?a=DD&sid=&e_id={1}&Db=' -f $Global:TkBaseUrl, $EId)
}

function ConvertFrom-TkDetail {
  # Nimmt das rohe HTML einer Detailseite und liefert ein PSCustomObject.
  # Gibt $null zurueck, wenn kein Name gefunden wird (unbrauchbarer Eintrag).
  param(
    [Parameter(Mandatory)][string]$Html,
    [string]$EId = ''
  )

  # --- Name + Titel/Anrede aus vCard: addName("Vorname","Nachname","Anrede ...", ...) ---
  $vorname = ''; $nachname = ''; $anrede = ''
  $mName = [regex]::Match($Html, 'addName\("([^"]*)",\s*"([^"]*)",\s*"([^"]*)"')
  if ($mName.Success) {
    $vorname  = $mName.Groups[1].Value.Trim()
    $nachname = $mName.Groups[2].Value.Trim()
    $anrede   = $mName.Groups[3].Value.Trim()
  }
  if (-not $nachname) { return $null }

  # --- Geschlecht aus Anrede (Frau/Herr). TK kennt nur diese beiden. ---
  $geschlecht = 'unbekannt'
  if     ($anrede -match '(?i)\bFrau\b') { $geschlecht = 'weiblich' }
  elseif ($anrede -match '(?i)\bHerr\b') { $geschlecht = 'maennlich' }

  # Reiner akademischer Titel ohne Anrede (z. B. "Dr. med.")
  $titel = ($anrede -replace '(?i)\b(Frau|Herr)\b', '').Trim()

  # --- Adresse aus vCard: addAddress("Strasse","PLZ","Ort","Land", ...) ---
  $strasse = ''; $plz = ''; $ort = ''
  $mAddr = [regex]::Match($Html, 'addAddress\("([^"]*)",\s*"([^"]*)",\s*"([^"]*)"')
  if ($mAddr.Success) {
    $strasse = $mAddr.Groups[1].Value.Trim()
    $plz     = $mAddr.Groups[2].Value.Trim()
    $ort     = $mAddr.Groups[3].Value.Trim()
  }

  # --- Telefon (itemprop) ---
  $telefon = ''
  $mTel = [regex]::Match($Html, 'itemprop="telephone">([^<]+)<')
  if ($mTel.Success) { $telefon = ($mTel.Groups[1].Value.Trim() -replace '\s+', ' ') }

  # --- Fachgebiet (Block "<strong>Fachgebiet</strong><br /> ...") ---
  $fachgebiet = ''
  $mFach = [regex]::Match($Html, '<strong>Fachgebiet</strong><br\s*/?>\s*([^<]+)')
  if ($mFach.Success) { $fachgebiet = $mFach.Groups[1].Value.Trim() }

  # --- Abrechnungsart (Liste unter "Abrechnungsart") ---
  $abrechnung = ''
  $mAbrBlock = [regex]::Match($Html, 'Abrechnungsart</span>(.*?)</ul>', 'Singleline')
  if ($mAbrBlock.Success) {
    $items = New-Object System.Collections.Generic.List[string]
    foreach ($li in [regex]::Matches($mAbrBlock.Groups[1].Value, '<li>(.*?)</li>', 'Singleline')) {
      $text = $li.Groups[1].Value
      $text = [regex]::Replace($text, '<!--.*?-->', '', 'Singleline')  # HTML-Kommentare weg
      $text = [regex]::Replace($text, '<[^>]+>', '')                    # Tags weg
      $text = ($text -replace '\s+', ' ').Trim()
      if ($text) { $items.Add($text) }
    }
    $abrechnung = ($items -join '; ')
  }

  # --- Homepage-URL (Arzt-Homepage, itemprop="url") ---
  # href kann vor ODER nach itemprop="url" stehen -> beide Varianten pruefen.
  $homepage = ''
  $mUrl = [regex]::Match($Html, 'href="(https?://[^"]+)"[^>]*itemprop="url"')
  if (-not $mUrl.Success) {
    $mUrl = [regex]::Match($Html, 'itemprop="url"[^>]*href="(https?://[^"]+)"')
  }
  if ($mUrl.Success) { $homepage = $mUrl.Groups[1].Value.Trim() }

  return [PSCustomObject]@{
    e_id           = $EId
    vorname        = $vorname
    nachname       = $nachname
    name           = (($anrede + ' ' + $vorname + ' ' + $nachname) -replace '\s+', ' ').Trim()
    titel          = $titel
    geschlecht     = $geschlecht
    fachgebiet     = $fachgebiet
    strasse        = $strasse
    plz            = $plz
    ort            = $ort
    telefon        = $telefon
    abrechnungsart = $abrechnung
    homepage       = $homepage
    profil_url     = (Get-TkDetailUrl -EId $EId)
  }
}
