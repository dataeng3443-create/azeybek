"""Local, dependency-free web application. Run: python3 server.py."""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parent
JOBS = {}
LOCK = threading.Lock()
TOKEN = secrets.token_urlsafe(32)
MAX_UPLOAD = 50 * 1024 * 1024
MAX_REFERENCE = 12 * 1024 * 1024
import designer as core

MODEL = os.environ.get("UX_MODEL", core.DEFAULT_MODEL)


def model_status():
    try:
        available = core.model_installed(MODEL, core.installed_models(timeout=3))
        return {"ready": available, "model": MODEL,
                "message": f"{MODEL} hazır" if available else
                f"{MODEL} modeli Ollama'da bulunamadı. Terminalde 'ollama pull {MODEL}' çalıştırın."}
    except (OSError, ValueError):
        return {"ready": False, "model": MODEL,
                "message": "Ollama bağlantısı yok. Ollama uygulamasını açıp tekrar deneyin."}


def work(job_id):
    job = JOBS[job_id]
    folder = ROOT / ".runtime" / "jobs" / job_id

    def update(stage, message, **extra):
        with LOCK:
            job.update(stage=stage, message=message, **extra)

    # Remove stale output from a previous run to prevent write_package errors.
    output = folder / "output.pbit"
    output.unlink(missing_ok=True)

    try:
        if job["mode"] == "blank":
            from generator import redesign
            result = redesign(folder / "input.pbit", folder / "output.pbit", MODEL, update)
        else:
            from creative import redesign
            reference = folder / "reference.png" if job["mode"] == "reference" else None
            result = redesign(folder / "input.pbit", folder / "output.pbit", MODEL, update, job["mode"], reference)
        (folder / "audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        update("ready", "Görsel hazır", result=result, download=f"/api/jobs/{job_id}/download")
    except Exception as exc:
        from traceback import format_exc
        (folder / "error.log").write_text(format_exc(), encoding="utf-8")
        update("error", str(exc) if isinstance(exc, (ValueError, RuntimeError)) else
               "Dosya işlenemedi. Lütfen geçerli bir Power BI şablonu ile tekrar deneyin.")


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, body, content_type="application/json; charset=utf-8", headers=None):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'self'; base-uri 'none'")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def valid_host(self):
        return self.headers.get("Host") in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}

    def do_GET(self):
        if not self.valid_host():
            return self.reply(403, {"error": "Geçersiz adres."})
        path = urllib.parse.urlsplit(self.path).path
        if path == "/api/health":
            return self.reply(200, {**model_status(), "token": TOKEN})
        match = re.fullmatch(r"/api/jobs/([a-f0-9]{32})(/download)?", path)
        if match:
            with LOCK:
                job = dict(JOBS.get(match[1], {}))
            if not job:
                return self.reply(404, {"error": "İşlem bulunamadı. Yeni bir dosya yükleyin."})
            if match[2]:
                if job["stage"] != "ready":
                    return self.reply(409, {"error": "Dosya henüz hazır değil."})
                name = Path(job["filename"]).stem + "_UX.pbit"
                return self.reply(200, (ROOT / ".runtime" / "jobs" / match[1] / "output.pbit").read_bytes(),
                                  "application/octet-stream", {"Content-Disposition": "attachment; filename=report_UX.pbit; filename*=UTF-8''" + urllib.parse.quote(name)})
            return self.reply(200, job)
        assets = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css", "/favicon.svg": "favicon.svg"}
        if path in assets:
            file = ROOT / "web" / assets[path]
            return self.reply(200, file.read_bytes(), mimetypes.guess_type(str(file))[0] or "application/octet-stream")
        self.reply(404, {"error": "Sayfa bulunamadı."})

    def do_POST(self):
        if not self.valid_host() or self.headers.get("X-UX-Token") != TOKEN:
            return self.reply(403, {"error": "Sayfayı yenileyip tekrar deneyin."})
        origin = self.headers.get("Origin")
        if origin and origin not in {f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"}:
            return self.reply(403, {"error": "Geçersiz kaynak."})
        reference_match = re.fullmatch(r"/api/jobs/([a-f0-9]{32})/reference", self.path)
        if reference_match:
            return self.upload_reference(reference_match[1])
        if self.path != "/api/jobs": return self.reply(404, {"error": "İşlem bulunamadı."})
        filename = urllib.parse.unquote(self.headers.get("X-Filename", ""))
        filename = filename.replace("\\", "/").split("/")[-1]
        if not filename.lower().endswith(".pbit") or len(filename) > 200:
            return self.reply(400, {"error": "Lütfen .pbit uzantılı bir Power BI şablonu seçin."})
        mode = self.headers.get("X-UX-Mode", "improve")
        if mode not in {"improve", "blank", "reference"}:
            return self.reply(400, {"error": "Geçersiz tasarım modu."})
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_UPLOAD:
            return self.reply(413, {"error": "Dosya boş veya 50 MB sınırını aşıyor."})
        with LOCK:
            if any(j["stage"] not in {"ready", "error"} for j in JOBS.values()):
                return self.reply(409, {"error": "Bir dosya işleniyor. Tamamlanınca tekrar deneyin."})
            job_id = secrets.token_hex(16)
            JOBS[job_id] = {"id": job_id, "filename": filename, "mode": mode, "stage": "upload", "message": "Dosya alınıyor", "created_at": time.time()}
        folder = ROOT / ".runtime" / "jobs" / job_id
        try:
            folder.mkdir(parents=True, mode=0o700)
            self.connection.settimeout(60)
            data = self.rfile.read(length)
            if len(data) != length:
                raise ValueError("Yükleme tamamlanamadı. Tekrar deneyin.")
            (folder / "input.pbit").write_bytes(data)
        except Exception:
            with LOCK:
                JOBS[job_id].update(stage="error", message="Dosya yüklenemedi.")
            return self.reply(400, {"error": "Dosya yüklenemedi. Tekrar deneyin."})
        if mode == "reference":
            with LOCK: JOBS[job_id].update(stage="reference", message="Referans PNG görseli yükleniyor…")
        else:
            threading.Thread(target=work, args=(job_id,), daemon=True).start()
        self.reply(202, {"id": job_id})

    def upload_reference(self, job_id):
        with LOCK: job = JOBS.get(job_id)
        if not job: return self.reply(404, {"error": "İşlem bulunamadı."})
        if job["mode"] != "reference" or job["stage"] != "reference":
            return self.reply(409, {"error": "Bu işlem referans görsel beklemiyor."})
        filename = urllib.parse.unquote(self.headers.get("X-Reference-Filename", "")).replace("\\", "/").split("/")[-1]
        if not filename.lower().endswith(".png") or len(filename) > 200:
            return self.reply(400, {"error": "Referans olarak bir .png dosyası seçin."})
        try: length = int(self.headers.get("Content-Length", "0"))
        except ValueError: length = 0
        if not 0 < length <= MAX_REFERENCE:
            return self.reply(413, {"error": "PNG dosyası boş veya 12 MB sınırını aşıyor."})
        self.connection.settimeout(60); data = self.rfile.read(length)
        if len(data) != length or not data.startswith(b"\x89PNG\r\n\x1a\n"):
            return self.reply(400, {"error": "Referans görsel geçerli bir PNG değil."})
        folder = ROOT / ".runtime" / "jobs" / job_id
        (folder / "reference.png").write_bytes(data)
        with LOCK: JOBS[job_id].update(stage="upload", message="Referans görsel alındı", reference_filename=filename)
        threading.Thread(target=work, args=(job_id,), daemon=True).start()
        self.reply(202, {"id": job_id})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"AI UX Designer: http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
