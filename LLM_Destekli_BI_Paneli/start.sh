#!/usr/bin/env bash
# FundAllocation AI Dashboard - başlatma betiği (macOS / Linux)
# Kullanım:  ./start.sh            -> kurulum kontrolü + Ollama + Streamlit
#            ./start.sh --no-ai    -> Ollama'yı atla, yalnızca kural tabanlı mod
set -euo pipefail

cd "$(dirname "$0")"

USE_AI=1
[[ "${1:-}" == "--no-ai" ]] && USE_AI=0

say()  { printf "\033[1;34m▸ %s\033[0m\n" "$*"; }
warn() { printf "\033[1;33m! %s\033[0m\n" "$*"; }
fail() { printf "\033[1;31m✗ %s\033[0m\n" "$*"; exit 1; }

# 1) Python 3.11+ bul
PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3; do
  if command -v "$candidate" >/dev/null 2>&1 &&
     "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    PYTHON="$candidate"; break
  fi
done
[[ -n "$PYTHON" ]] || fail "Python 3.11+ bulunamadı. Kurulum: brew install python@3.12"
say "Python: $($PYTHON --version)"

# 2) Sanal ortam
if [[ ! -x .venv/bin/python ]]; then
  say "Sanal ortam oluşturuluyor (.venv)…"
  "$PYTHON" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

# 3) Bağımlılıklar (requirements.txt değiştiyse yeniden kur)
STAMP=".venv/.requirements.sha"
CURRENT="$(shasum requirements.txt | awk '{print $1}')"
if [[ ! -f "$STAMP" || "$(cat "$STAMP")" != "$CURRENT" ]]; then
  say "Bağımlılıklar kuruluyor…"
  python -m pip install --upgrade pip -q
  python -m pip install -r requirements.txt -q
  echo "$CURRENT" > "$STAMP"
else
  say "Bağımlılıklar güncel."
fi

# 4) .env
if [[ ! -f .env ]]; then
  say ".env bulunamadı, .env.example kopyalanıyor."
  cp .env.example .env
fi

# 5) Ollama (isteğe bağlı - yoksa uygulama yedek mantıkla çalışır)
if [[ "$USE_AI" == 1 ]]; then
  OLLAMA_URL="$(grep -E '^OLLAMA_BASE_URL=' .env | cut -d= -f2- || true)"; OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"
  OLLAMA_MODEL="$(grep -E '^OLLAMA_MODEL=' .env | cut -d= -f2- || true)"; OLLAMA_MODEL="${OLLAMA_MODEL:-qwen3:8b}"

  if ! command -v ollama >/dev/null 2>&1; then
    warn "Ollama kurulu değil; kural tabanlı modda devam ediliyor. (Kurulum: brew install ollama)"
  else
    if ! curl -sf "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
      say "Ollama başlatılıyor (log: .ollama.log)…"
      nohup ollama serve > .ollama.log 2>&1 &
      for _ in {1..20}; do curl -sf "$OLLAMA_URL/api/tags" >/dev/null 2>&1 && break; sleep 0.5; done
    fi
    if curl -sf "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
      if ! ollama list | awk 'NR>1 {print $1}' | grep -qx "$OLLAMA_MODEL"; then
        say "Model indiriliyor: $OLLAMA_MODEL (ilk seferde birkaç dakika sürebilir)…"
        ollama pull "$OLLAMA_MODEL"
      fi
      say "Ollama hazır: $OLLAMA_MODEL"
    else
      warn "Ollama'ya ulaşılamadı; kural tabanlı modda devam ediliyor."
    fi
  fi
fi

# 6) Uygulama
say "Dashboard başlatılıyor → http://localhost:8501  (durdurmak için Ctrl+C)"
exec streamlit run app.py
