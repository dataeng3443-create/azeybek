#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tek giriş noktası: kural tabanlı denetim + (Ollama erişilebilirse) AI yorumu.

Kullanım:
    python3 main.py Test_0.pbit                 # kurallar + AI yorumu + HTML rapor
    python3 main.py Test_0.pbit --no-ai         # sadece kural motoru
    python3 main.py Test_0.pbit --model qwen3:14b --json sonuc.json
"""

import sys

from comprehensive_analyzer import main

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Lütfen bir .pbit dosya yolu belirtin. Örnek: python3 main.py Test_0.pbit")
        sys.exit(1)
    sys.exit(main())
