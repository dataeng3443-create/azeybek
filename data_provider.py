from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

import pandas as pd

from models import SemanticSchema


class DataProvider(ABC):
    @abstractmethod
    def get_schema(self) -> SemanticSchema: ...

    @abstractmethod
    def execute_dax(self, query: str, filters: dict[str, str] | None = None) -> pd.DataFrame: ...

    @abstractmethod
    def test_connection(self) -> tuple[bool, str]: ...

    @abstractmethod
    def filter_values(self, field: str) -> list[str]: ...

    def latest_date(self) -> date | None:
        """Most recent date in the model; used to anchor "last N months" questions."""
        return None
