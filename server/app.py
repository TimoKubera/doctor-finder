"""app.py - HTTP-Server fuer Doctor Finder.

Liefert die statische Weboberflaeche (web/) aus und stellt eine kleine API
bereit, die Find-Doctors.ps1 mit den in der GUI eingegebenen Parametern
ausfuehrt. Reine Python-Standardbibliothek - keine Zusatzpakete.

Endpunkte:
  GET  /                 -> web/index.html
  GET  /<datei>          -> statische Datei aus web/
  GET  /api/health       -> {ok, powershell, mock, running}
  GET  /api/fachgebiete  -> [{nr, name}, ...]
  POST /api/search       -> startet einen Suchlauf -> {job_id}
  GET  /api/search/<id>  -> Status/Fortschritt/Ergebnis des Laufs

Der Crawler wird lokal als Subprozess gestartet; der Server bindet daher
standardmaessig nur an 127.0.0.1. Wegen des TK-Tageskontingents laeuft
hoechstens EIN Suchlauf gleichzeitig.

Aufruf:
    python -m server                 # http://127.0.0.1:8765
    python -m server --port 9000
    python -m server --mock          # ohne PowerShell, Beispieldaten
"""

from __future__ import annotations

import argparse
import json
import threading
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import runner

WEB_DIR = runner.REPO_ROOT / "web"

# Statische Dateitypen, die wir ausliefern (Whitelist).
_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".png": "image/png",
    ".webmanifest": "application/manifest+json",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class JobManager:
    """Verwaltet Suchlaeufe in Hintergrund-Threads (max. ein aktiver Lauf)."""

    def __init__(self, force_mock: bool) -> None:
        self.force_mock = force_mock
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._valid_fg = runner.load_fachgebiete()

    @property
    def valid_fachgebiete(self) -> dict[str, str]:
        return self._valid_fg

    def has_running(self) -> bool:
        with self._lock:
            return any(j["status"] == "running" for j in self._jobs.values())

    def snapshot(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            # flache Kopie ohne interne Felder
            return {
                "job_id": job_id,
                "status": job["status"],
                "log": list(job["log"]),
                "result": job["result"],
                "out_path": job["out_path"],
                "error": job["error"],
                "started": job["started"],
                "finished": job["finished"],
            }

    def start(self, params: dict) -> str:
        job_id = uuid.uuid4().hex[:12]
        job = {
            "status": "running",
            "log": [],
            "result": None,
            "out_path": None,
            "error": None,
            "started": _now(),
            "finished": None,
            "params": params,
        }
        with self._lock:
            self._jobs[job_id] = job

        def on_progress(line: str) -> None:
            with self._lock:
                job["log"].append(line)

        def worker() -> None:
            try:
                outcome = runner.run_search(
                    params, on_progress, force_mock=self.force_mock
                )
                with self._lock:
                    job["result"] = outcome["result"]
                    job["out_path"] = outcome["out_path"]
                    job["status"] = "done"
            except Exception as exc:  # noqa: BLE001 - Fehler an den Client melden
                with self._lock:
                    job["error"] = str(exc)
                    job["status"] = "error"
                    job["log"].append(f"FEHLER: {exc}")
            finally:
                with self._lock:
                    job["finished"] = _now()

        threading.Thread(target=worker, name=f"search-{job_id}", daemon=True).start()
        return job_id


class Handler(BaseHTTPRequestHandler):
    server_version = "DoctorFinder/1.0"
    jobs: JobManager  # von make_server gesetzt

    # -- Hilfen ---------------------------------------------------------------

    def _send_json(self, obj: dict, status: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, status: int, message: str) -> None:
        self._send_json({"error": message}, status)

    def log_message(self, fmt: str, *args) -> None:  # ruhiger Log
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    # -- Routing --------------------------------------------------------------

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/health":
            self._send_json({
                "ok": True,
                "powershell": runner.find_powershell() is not None,
                "mock": self.jobs.force_mock or runner.find_powershell() is None,
                "running": self.jobs.has_running(),
            })
            return
        if path == "/api/fachgebiete":
            items = [{"nr": nr, "name": name} for nr, name in self.jobs.valid_fachgebiete.items()]
            self._send_json({"fachgebiete": items})
            return
        if path.startswith("/api/search/"):
            job_id = path[len("/api/search/"):]
            snap = self.jobs.snapshot(job_id)
            if snap is None:
                self._send_error_json(404, "Unbekannter Job.")
            else:
                self._send_json(snap)
            return
        self._serve_static(path)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/api/search":
            self._send_error_json(404, "Nicht gefunden.")
            return
        if self.jobs.has_running():
            self._send_error_json(
                409, "Es laeuft bereits eine Suche. Bitte warten, bis sie fertig ist "
                     "(TK-Tageskontingent)."
            )
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b"{}"
            payload = json.loads(raw.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            self._send_error_json(400, "Ungueltiger JSON-Body.")
            return
        try:
            params = runner.validate_params(payload, self.jobs.valid_fachgebiete)
        except runner.ValidationError as exc:
            self._send_error_json(400, str(exc))
            return
        job_id = self.jobs.start(params)
        self._send_json({"job_id": job_id}, status=202)

    # -- Statische Dateien ----------------------------------------------------

    def _serve_static(self, path: str) -> None:
        rel = unquote(path.lstrip("/")) or "index.html"
        target = (WEB_DIR / rel).resolve()
        # Directory-Traversal verhindern.
        if not str(target).startswith(str(WEB_DIR.resolve())) or not target.is_file():
            self._send_error_json(404, "Datei nicht gefunden.")
            return
        ctype = _CONTENT_TYPES.get(target.suffix.lower())
        if ctype is None:
            self._send_error_json(403, "Dateityp nicht erlaubt.")
            return
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def make_server(host: str, port: int, force_mock: bool) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"jobs": JobManager(force_mock)})
    return ThreadingHTTPServer((host, port), handler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m server", description="Doctor Finder Web-Backend.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind-Adresse (Standard: 127.0.0.1).")
    parser.add_argument("--port", type=int, default=8765, help="Port (Standard: 8765).")
    parser.add_argument("--mock", action="store_true", help="Ohne PowerShell laufen (Beispieldaten).")
    args = parser.parse_args(argv)

    httpd = make_server(args.host, args.port, args.mock)
    ps = runner.find_powershell()
    mode = "MOCK (Beispieldaten)" if (args.mock or ps is None) else f"PowerShell: {ps[0]}"
    print(f"Doctor Finder laeuft auf http://{args.host}:{args.port}  [{mode}]")
    print("Zum Beenden Strg+C druecken.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServer wird beendet.")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
