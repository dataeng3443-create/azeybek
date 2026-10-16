from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    app_mode: str = "synthetic"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:8b"
    ollama_timeout_seconds: int = 180
    ollama_temperature: float = 0
    max_dax_repair_attempts: int = 2
    max_result_rows: int = 10_000
    max_history_items: int = 20
    max_dashboard_kpis: int = 4
    synthetic_seed: int = 42

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        return cls(
            app_mode=os.getenv("APP_MODE", "synthetic"),
            ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/"),
            ollama_model=os.getenv("OLLAMA_MODEL", "qwen3:8b"),
            ollama_timeout_seconds=int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "180")),
            ollama_temperature=float(os.getenv("OLLAMA_TEMPERATURE", "0")),
            max_dax_repair_attempts=int(os.getenv("MAX_DAX_REPAIR_ATTEMPTS", "2")),
            max_result_rows=int(os.getenv("MAX_RESULT_ROWS", "10000")),
            max_history_items=int(os.getenv("MAX_HISTORY_ITEMS", "20")),
            max_dashboard_kpis=int(os.getenv("MAX_DASHBOARD_KPIS", "4")),
            synthetic_seed=int(os.getenv("SYNTHETIC_SEED", "42")),
        )
