#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BI Skorlama — yerel web arayüzü.

    python3 app.py            # http://127.0.0.1:8765 adresini tarayıcıda açar

Sadece Python'un standart kütüphanesini kullanır; ek kurulum gerekmez.
Sunucu yalnızca bu bilgisayardan (127.0.0.1) erişilebilir.

Akış:
  1. Tarayıcı .pbit dosyasını POST /api/analyze ile gönderir (ham gövde).
  2. Sunucu arka planda bir iş başlatır: dosya okunur -> kurallar -> AI yorumu.
  3. Tarayıcı GET /api/jobs/<id> ile aşamayı takip eder.
  4. İş bitince rapor reports/<id>.html olarak saklanır ve /reports/<id> adresinden açılır.
"""

import argparse
import html
import json
import os
import sys
import tempfile
import threading
import time
import traceback
import uuid
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse, parse_qs

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from agents import DEFAULT_MODEL, BIAgents  # noqa: E402
from comprehensive_analyzer import ComprehensiveAnalyzer  # noqa: E402

WEB_DIR = BASE_DIR / "web"
REPORTS_DIR = BASE_DIR / "reports"
HISTORY_FILE = REPORTS_DIR / "history.json"
MAX_UPLOAD_BYTES = 200 * 1024 * 1024
DEFAULT_PORT = 8765

JOBS = {}
JOBS_LOCK = threading.Lock()
HISTORY_LOCK = threading.Lock()
# Ollama aynı anda tek istekte en verimli; AI aşamasını sıraya sokuyoruz.
AI_LOCK = threading.Lock()

STAGES = ["upload", "rules", "ai", "done"]


# ------------------------------------------------------------------ geçmiş
def load_history():
    try:
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def append_history(entry):
    with HISTORY_LOCK:
        history = load_history()
        history.insert(0, entry)
        REPORTS_DIR.mkdir(exist_ok=True)
        HISTORY_FILE.write_text(json.dumps(history[:200], ensure_ascii=False, indent=2), encoding="utf-8")


# ------------------------------------------------------------------- işler
def update_job(job_id, **fields):
    with JOBS_LOCK:
        JOBS[job_id].update(fields)


def nav_html(filename):
    return (
        '<nav class="app-nav">'
        '<a href="/">Yeni rapor analiz et</a>'
        f'<span class="muted">{_escape(filename)}</span>'
        '</nav>'
    )


def _escape(value):
    return html.escape(str(value), quote=True)


def run_job(job_id, pbit_path, filename, use_ai, model_name):
    started = time.time()
    try:
        update_job(job_id, stage="rules", message="Model, sorgular ve DAX inceleniyor")
        analyzer = ComprehensiveAnalyzer(
            str(pbit_path),
            model_name=model_name,
            use_ai=use_ai,
            verbose=False,
            display_name=filename,
        )
        if not analyzer.ok:
            raise ValueError(
                "Dosya okunamadı. Power BI şablonu (.pbit) olduğundan emin ol. "
                f"Ayrıntı: {analyzer.metadata}"
            )

        total = analyzer.run_rules()
        update_job(job_id, score=round(total, 1), findings=sum(1 for f in analyzer.findings if f.penalty > 0))

        if use_ai:
            update_job(job_id, stage="ai", message=f"{model_name} bulguları yorumluyor", ai_started=time.time())
            with AI_LOCK:
                analyzer.run_ai_commentary(total)
            if not analyzer.ai_commentary:
                update_job(job_id, ai_warning=analyzer.ai_note)
        else:
            analyzer.ai_note = "Bu analizde AI yorumu istenmedi."

        REPORTS_DIR.mkdir(exist_ok=True)
        report_path = REPORTS_DIR / f"{job_id}.html"
        report_path.write_text(analyzer.render_html(nav_html=nav_html(filename)), encoding="utf-8")

        summary = analyzer.summary()
        summary.update({
            "id": job_id,
            "file": filename,
            "report_url": f"/reports/{job_id}",
            "duration_sec": round(time.time() - started, 1),
        })
        append_history(summary)
        update_job(job_id, stage="done", message="Rapor hazır", report_url=summary["report_url"])
    except Exception as exc:  # noqa: BLE001 - kullanıcıya anlamlı hata dönmeli
        traceback.print_exc()
        update_job(job_id, stage="error", message=str(exc))
    finally:
        try:
            os.remove(pbit_path)
        except OSError:
            pass


# ------------------------------------------------------------------ sunucu
class Handler(BaseHTTPRequestHandler):
    server_version = "BISkorlama/1.0"

    # Konsolu her istekle (durum sorgulama dahil) doldurmamak için erişim logunu kapat.
    # Analiz hataları run_job içinde traceback olarak yazılır.
    def log_message(self, fmt, *args):
        return

    # ---- yardımcılar
    def _send(self, status, body, content_type="application/json; charset=utf-8", extra_headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path, content_type):
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            self._send(404, {"error": "Bulunamadı"})
            return
        self._send(200, data, content_type)

    def _same_origin(self):
        """Başka sitelerin bu yerel sunucuya istek atmasını engelle."""
        origin = self.headers.get("Origin")
        if not origin:
            return True
        host = self.headers.get("Host", "")
        return urlparse(origin).netloc == host

    # ---- GET
    def do_GET(self):
        path = urlparse(self.path).path

        if path in ("/", "/index.html"):
            return self._send_file(WEB_DIR / "index.html", "text/html; charset=utf-8")

        if path == "/api/status":
            agents = BIAgents(model_name=self.server.model_name)
            ok = agents.available()
            return self._send(200, {
                "model": self.server.model_name,
                "ai_available": ok,
                "ai_error": None if ok else agents.last_error,
            })

        if path == "/api/history":
            return self._send(200, load_history())

        if path.startswith("/api/jobs/"):
            job_id = path.rsplit("/", 1)[-1]
            with JOBS_LOCK:
                job = dict(JOBS.get(job_id) or {})
            if not job:
                return self._send(404, {"error": "İş bulunamadı"})
            job["elapsed"] = round(time.time() - job["created"], 1)
            if job.get("ai_started") and job.get("stage") == "ai":
                job["ai_elapsed"] = round(time.time() - job["ai_started"], 1)
            return self._send(200, job)

        if path.startswith("/reports/"):
            report_id = path.rsplit("/", 1)[-1].replace(".html", "")
            # Sadece bizim ürettiğimiz kimlikler (uuid hex) — dizin dışına çıkışı engeller
            if not report_id.isalnum():
                return self._send(404, {"error": "Bulunamadı"})
            return self._send_file(REPORTS_DIR / f"{report_id}.html", "text/html; charset=utf-8")

        return self._send(404, {"error": "Bulunamadı"})

    # ---- POST
    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/analyze":
            return self._send(404, {"error": "Bulunamadı"})
        if not self._same_origin():
            return self._send(403, {"error": "İzin verilmeyen kaynak"})

        filename = unquote(self.headers.get("X-Filename", "rapor.pbit")).strip() or "rapor.pbit"
        filename = os.path.basename(filename)
        if not filename.lower().endswith(".pbit"):
            hint = ""
            if filename.lower().endswith(".pbix"):
                hint = (" .pbix dosyasını Power BI Desktop'ta Dosya > Dışarı aktar > "
                        "Power BI şablonu ile .pbit olarak kaydedip tekrar dene.")
            return self._send(400, {"error": f"Sadece .pbit dosyaları analiz edilebilir.{hint}"})

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0:
            return self._send(400, {"error": "Dosya boş görünüyor."})
        if length > MAX_UPLOAD_BYTES:
            return self._send(413, {"error": "Dosya 200 MB sınırını aşıyor."})

        query = parse_qs(parsed.query)
        use_ai = query.get("ai", ["1"])[0] == "1"

        job_id = uuid.uuid4().hex
        tmp_dir = Path(tempfile.gettempdir()) / "bi_skorlama"
        tmp_dir.mkdir(exist_ok=True)
        pbit_path = tmp_dir / f"{job_id}.pbit"

        remaining = length
        with open(pbit_path, "wb") as handle:
            while remaining > 0:
                chunk = self.rfile.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                handle.write(chunk)
                remaining -= len(chunk)

        with JOBS_LOCK:
            JOBS[job_id] = {
                "id": job_id,
                "file": filename,
                "stage": "upload",
                "message": "Dosya alındı",
                "use_ai": use_ai,
                "model": self.server.model_name,
                "created": time.time(),
            }

        threading.Thread(
            target=run_job,
            args=(job_id, pbit_path, filename, use_ai, self.server.model_name),
            daemon=True,
        ).start()
        return self._send(202, {"job_id": job_id})


def make_server(port, model_name):
    last_error = None
    for candidate in range(port, port + 10):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", candidate), Handler)
            server.model_name = model_name
            return server
        except OSError as exc:
            last_error = exc
    raise SystemExit(f"Boş port bulunamadı ({port}-{port + 9}): {last_error}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="BI Skorlama yerel web arayüzü")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama modeli (varsayılan: {DEFAULT_MODEL})")
    parser.add_argument("--no-browser", action="store_true", help="Tarayıcıyı otomatik açma")
    args = parser.parse_args(argv)

    REPORTS_DIR.mkdir(exist_ok=True)
    server = make_server(args.port, args.model)
    url = f"http://127.0.0.1:{server.server_address[1]}"

    print("\n  BI Skorlama çalışıyor")
    print(f"  Adres : {url}")
    print(f"  Model : {args.model}")
    print("  Durdurmak için bu pencerede Ctrl+C\n")

    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Kapatıldı.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
