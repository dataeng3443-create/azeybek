from __future__ import annotations

import json
import re
from typing import Any

import httpx

from ai_provider import AIProvider


class OllamaUnavailableError(RuntimeError):
    pass


class OllamaProvider(AIProvider):
    def __init__(self, base_url: str, model: str, timeout_seconds: int = 120, temperature: float = 0):
        self.base_url, self.model, self.timeout_seconds, self.temperature = base_url.rstrip("/"), model, timeout_seconds, temperature

    @staticmethod
    def _normalize(name: str | None) -> str:
        # Ollama lists untagged models as "<name>:latest".
        name = (name or "").strip()
        return name if ":" in name else f"{name}:latest"

    def health_check(self) -> tuple[bool, str]:
        try:
            response = httpx.get(f"{self.base_url}/api/tags", timeout=min(self.timeout_seconds, 5))
            response.raise_for_status()
            installed = {self._normalize(model.get("name")) for model in response.json().get("models", [])}
            # Exact match: "qwen3:8b" must not be satisfied by e.g. "qwen3:4b".
            if self._normalize(self.model) not in installed:
                return False, f"Ollama is running, but model '{self.model}' is not installed."
            return True, f"Connected ({self.model})"
        except (httpx.HTTPError, ValueError):
            return False, "Ollama service is unavailable. Please verify that Ollama is running and the configured model is installed."

    def generate(self, prompt: str, json_mode: bool = False) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            # Qwen3 and other reasoning models emit <think> blocks by default; they are
            # slow and can break JSON extraction. Models without thinking ignore this.
            "think": False,
            "options": {"temperature": self.temperature},
        }
        if json_mode:
            payload["format"] = "json"  # Ollama constrains the output to valid JSON.
        try:
            response = httpx.post(f"{self.base_url}/api/generate", json=payload, timeout=self.timeout_seconds)
            response.raise_for_status()
            return _strip_thinking(str(response.json()["response"]))
        except (httpx.HTTPError, KeyError, ValueError) as error:
            raise OllamaUnavailableError("Ollama generation failed.") from error

    def generate_json(self, prompt: str) -> dict[str, Any]:
        raw = self.generate(f"{prompt}\nReturn only a valid JSON object. Do not use markdown fences.", json_mode=True)
        try:
            # Local models sometimes wrap otherwise valid JSON in prose or Markdown.
            cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            if not cleaned.startswith("{"):
                start, end = cleaned.find("{"), cleaned.rfind("}")
                cleaned = cleaned[start:end + 1] if start >= 0 and end > start else cleaned
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as error:
            raise ValueError("Ollama returned malformed JSON.") from error
        if not isinstance(parsed, dict):
            raise ValueError("Ollama returned JSON that is not an object.")
        return parsed


_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _strip_thinking(text: str) -> str:
    """Remove reasoning blocks in case the model ignores think=false."""
    text = _THINK_BLOCK.sub("", text)
    if "</think>" in text:  # opening tag may be missing
        text = text.split("</think>", 1)[1]
    return text.strip()
