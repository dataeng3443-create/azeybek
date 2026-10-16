"""Start the local services and open the app; no third-party dependencies."""
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent
URL = "http://127.0.0.1:8765"

def reachable(url):
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return response.status == 200
    except OSError:
        return False

def main():
    runtime = ROOT / ".runtime"
    runtime.mkdir(exist_ok=True)
    if not reachable("http://127.0.0.1:11434/api/tags"):
        ollama = shutil.which("ollama")
        if ollama:
            with (runtime / "ollama.log").open("ab") as log:
                subprocess.Popen([ollama, "serve"], stdout=log, stderr=log, start_new_session=True)
        else:
            print("Ollama bulunamadı. Ollama'yı kurup 'ollama pull qwen3:8b' ile modeli indirin.")
    if not reachable(URL + "/api/health"):
        with (runtime / "server.log").open("ab") as log:
            process = subprocess.Popen([sys.executable, "-u", str(ROOT / "server.py")], cwd=ROOT,
                                       stdout=log, stderr=log, start_new_session=True)
        (runtime / "server.pid").write_text(str(process.pid))
    for _ in range(30):
        if reachable(URL + "/api/health"):
            webbrowser.open(URL)
            print("AI UX Designer açıldı: " + URL)
            return
        time.sleep(1)
    raise SystemExit("Uygulama başlatılamadı. .runtime/server.log dosyasını kontrol edin.")

if __name__ == "__main__":
    main()
