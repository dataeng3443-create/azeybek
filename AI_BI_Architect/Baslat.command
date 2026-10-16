#!/bin/bash
# Çift tıklayınca BI Skorlama'yı başlatır ve tarayıcıda açar.
cd "$(dirname "$0")"
echo "BI Skorlama başlatılıyor..."
if ! pgrep -xq ollama && ! pgrep -q -f "Ollama.app"; then
    open -a Ollama 2>/dev/null && sleep 2
fi
python3 app.py
