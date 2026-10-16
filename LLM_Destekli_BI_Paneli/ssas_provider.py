"""Phase 2 provider. It deliberately has no active use in the synthetic prototype."""
from __future__ import annotations

import pandas as pd

from data_provider import DataProvider
from models import SemanticSchema


class SSASProvider(DataProvider):
    def __init__(self, server: str, database: str, max_rows: int = 10_000):
        self.server, self.database, self.max_rows = server, database, max_rows

    def get_schema(self) -> SemanticSchema:
        raise NotImplementedError("SSAS schema discovery is enabled in Phase 2.")

    def execute_dax(self, query: str, filters: dict[str, str] | None = None) -> pd.DataFrame:
        try:
            from pyadomd import Pyadomd  # type: ignore[import-not-found]
        except ImportError as error:
            raise RuntimeError("Install pyadomd on a Windows host to use APP_MODE=ssas.") from error
        connection = f"Provider=MSOLAP;Data Source={self.server};Initial Catalog={self.database};Integrated Security=SSPI;"
        with Pyadomd(connection) as client:
            with client.execute(query) as cursor:
                return pd.DataFrame(cursor.fetchone(), columns=[column.name for column in cursor.description]).head(self.max_rows)

    def test_connection(self) -> tuple[bool, str]:
        try:
            self.execute_dax("EVALUATE TOPN(1, INFO.TABLES())")
            return True, "SSAS connection succeeded."
        except Exception as error:
            return False, f"SSAS connection failed: {type(error).__name__}"

    def filter_values(self, field: str) -> list[str]:
        return []
