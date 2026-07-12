"""runner.py - baut den Find-Doctors.ps1-Aufruf und fuehrt ihn aus.

Kapselt alles, was mit dem PowerShell-Crawler zu tun hat:
  - Fachgebiets-Liste aus lib/Fachgebiete.ps1 lesen (einzige Quelle der Wahrheit),
  - PowerShell finden (pwsh / powershell.exe),
  - Parameter validieren und als Argumentliste (KEINE Shell) uebergeben,
  - den Prozess starten, stdout zeilenweise als Fortschritt melden und die
    erzeugte JSON einlesen.

Ohne verfuegbares PowerShell (oder mit force_mock=True) laeuft ein Mock-Modus,
der die Beispiel-JSON aus assets/ zurueckgibt - nuetzlich zum Testen der
Oberflaeche ohne echten TK-Abruf.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "Find-Doctors.ps1"
ASSETS_DIR = REPO_ROOT / "assets"
RUNS_DIR = REPO_ROOT / "server" / "runs"

ProgressFn = Callable[[str], None]

# Zeile im ordered-hash von Fachgebiete.ps1:  '23' = 'Psychiatrie ...'
_FG_LINE = re.compile(r"'([^']+)'\s*=\s*'((?:[^']|'')*)'")


def load_fachgebiete() -> dict[str, str]:
    """Liest lib/Fachgebiete.ps1 und liefert {Nummer: Bezeichnung}."""
    path = REPO_ROOT / "lib" / "Fachgebiete.ps1"
    text = path.read_text(encoding="utf-8")
    block = text.split("[ordered]@{", 1)[1].split("function Test-Fachgebiet", 1)[0]
    result: dict[str, str] = {}
    for nr, name in _FG_LINE.findall(block):
        result[nr] = name.replace("''", "'")
    return result


def find_powershell() -> list[str] | None:
    """Ermittelt das PowerShell-Kommando-Praefix (Liste) oder None.

    Bevorzugt PowerShell 7+ (pwsh, plattformuebergreifend), faellt auf die
    Windows-PowerShell zurueck.
    """
    pwsh = shutil.which("pwsh")
    if pwsh:
        return [pwsh, "-NoProfile", "-NonInteractive"]
    for name in ("powershell.exe", "powershell"):
        found = shutil.which(name)
        if found:
            return [found, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass"]
    return None


class ValidationError(ValueError):
    """Ungueltige Suchparameter (fuehrt zu HTTP 400)."""


def validate_params(raw: dict, valid_fachgebiete: dict[str, str]) -> dict:
    """Prueft und normalisiert die vom Frontend gesendeten Parameter."""
    fg = raw.get("fachgebiet") or []
    if isinstance(fg, str):
        fg = [t for t in re.split(r"[,\s]+", fg) if t]
    fg = [str(x).strip() for x in fg if str(x).strip()]
    if not fg:
        raise ValidationError("Mindestens ein Fachgebiet ist erforderlich.")
    unknown = [x for x in fg if x not in valid_fachgebiete]
    if unknown:
        raise ValidationError(f"Unbekannte Fachgebiets-Nummer(n): {', '.join(unknown)}")

    ort = str(raw.get("ort", "")).strip()
    if not ort:
        raise ValidationError("Der Ort ist ein Pflichtfeld.")
    if len(ort) > 80:
        raise ValidationError("Der Ort ist zu lang.")

    geschlecht = str(raw.get("geschlecht", "")).strip().lower()
    if geschlecht in ("weiblich", "w"):
        geschlecht = "w"
    elif geschlecht in ("maennlich", "männlich", "m"):
        geschlecht = "m"
    elif geschlecht in ("", "alle"):
        geschlecht = ""
    else:
        raise ValidationError("Geschlecht muss 'm', 'w' oder leer sein.")

    try:
        punkte = int(raw.get("punkte", 5))
    except (TypeError, ValueError):
        raise ValidationError("Punkte muss eine ganze Zahl sein.")
    if not 1 <= punkte <= 50:
        raise ValidationError("Punkte muss zwischen 1 und 50 liegen.")

    return {"fachgebiet": fg, "ort": ort, "geschlecht": geschlecht, "punkte": punkte}


def build_command(ps_prefix: list[str], params: dict, out_path: Path) -> list[str]:
    """Baut die Argumentliste fuer den Subprozess (keine Shell, kein Quoting noetig)."""
    cmd = [*ps_prefix, "-File", str(SCRIPT)]
    cmd += ["-Fachgebiet", ",".join(params["fachgebiet"])]
    cmd += ["-Ort", params["ort"]]
    if params["geschlecht"]:
        cmd += ["-Geschlecht", params["geschlecht"]]
    cmd += ["-Punkte", str(params["punkte"])]
    cmd += ["-Out", str(out_path)]
    return cmd


def _out_path_for(params: dict) -> Path:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    fg = "-".join(params["fachgebiet"])
    safe_ort = re.sub(r"[^A-Za-z0-9]+", "_", params["ort"]).strip("_") or "ort"
    return RUNS_DIR / f"aerzte_{fg}_{safe_ort}_{stamp}.json"


def run_search(
    params: dict,
    on_progress: ProgressFn,
    *,
    force_mock: bool = False,
    timeout: float = 1800.0,
) -> dict:
    """Fuehrt die Suche aus und liefert das geparste JSON-Ergebnis.

    :param on_progress: Callback fuer jede Fortschrittszeile (stdout).
    :returns: dict mit Schluesseln 'result' (JSON-Inhalt) und 'out_path'.
    """
    out_path = _out_path_for(params)
    ps_prefix = None if force_mock else find_powershell()

    if ps_prefix is None:
        return _run_mock(params, on_progress, out_path)

    cmd = build_command(ps_prefix, params, out_path)
    on_progress(f"Starte: {' '.join(cmd[len(ps_prefix):])}")
    proc = subprocess.Popen(
        cmd,
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip("\n")
            if line.strip():
                on_progress(line)
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise RuntimeError(f"Zeitueberschreitung nach {int(timeout)} s - Suche abgebrochen.")

    if not out_path.is_file():
        raise RuntimeError(
            f"PowerShell endete mit Code {proc.returncode}, aber es wurde keine "
            "Ergebnisdatei erzeugt (siehe Protokoll)."
        )
    result = json.loads(out_path.read_text(encoding="utf-8"))
    return {"result": result, "out_path": str(out_path)}


def _run_mock(params: dict, on_progress: ProgressFn, out_path: Path) -> dict:
    """Mock-Lauf ohne PowerShell: liefert die Beispiel-JSON aus assets/."""
    on_progress("PowerShell nicht gefunden - MOCK-Modus (Beispieldaten, kein TK-Abruf).")
    samples = sorted(ASSETS_DIR.glob("aerzte_*.json"))
    if not samples:
        raise RuntimeError("Kein Beispiel-JSON in assets/ fuer den Mock-Modus vorhanden.")
    on_progress(f"Fachgebiet(e): {', '.join(params['fachgebiet'])}  Ort: {params['ort']}")
    for step, plz in enumerate(("Zentrum", "Nord", "Ost", "Sued", "West"), 1):
        if step > params["punkte"]:
            break
        on_progress(f"Suchpunkt {step} ({plz}) - frage TK-Aerztefinder ab ...")
        time.sleep(0.25)
    data = json.loads(samples[-1].read_text(encoding="utf-8"))
    data.setdefault("suche", {})["ort"] = params["ort"]
    n = len(data.get("aerzte", []))
    on_progress(f"Fertig (Mock): {n} Treffer mit E-Mail-Adresse.")
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"result": data, "out_path": str(out_path)}
