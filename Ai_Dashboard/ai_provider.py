from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class AIProvider(ABC):
    @abstractmethod
    def generate(self, prompt: str) -> str: ...

    @abstractmethod
    def generate_json(self, prompt: str) -> dict[str, Any]: ...

    @abstractmethod
    def health_check(self) -> tuple[bool, str]: ...
