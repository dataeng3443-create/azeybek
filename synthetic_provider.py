from __future__ import annotations

from datetime import date
from functools import lru_cache

import pandas as pd

from data_provider import DataProvider
from models import SemanticSchema
from synthetic_dax_engine import SyntheticDaxEngine
from synthetic_model import SyntheticModel, build_synthetic_model


@lru_cache(maxsize=4)
def _cached_model(seed: int) -> SyntheticModel:
    return build_synthetic_model(seed)


class SyntheticProvider(DataProvider):
    def __init__(self, seed: int = 42, max_rows: int = 10_000):
        self.model = _cached_model(seed)
        self.max_rows = max_rows

    def get_schema(self) -> SemanticSchema:
        return self.model.schema

    def test_connection(self) -> tuple[bool, str]:
        return True, "Synthetic semantic model is ready."

    def execute_dax(self, query: str, filters: dict[str, str] | None = None) -> pd.DataFrame:
        return SyntheticDaxEngine(self._joined_frame(filters), self.max_rows).execute(query)

    def filter_values(self, field: str) -> list[str]:
        frame = self._joined_frame()
        return sorted(frame[field].dropna().astype(str).unique().tolist()) if field in frame else []

    def latest_date(self) -> date | None:
        return pd.Timestamp(self.model.allocation["Date"].max()).date()

    def dashboard_frame(self, filters: dict[str, str] | None = None) -> pd.DataFrame:
        """Joined semantic frame used by the overview dashboard and its global filters."""
        return self._joined_frame(filters)

    def _joined_frame(self, filters: dict[str, str] | None = None) -> pd.DataFrame:
        frame = self.model.allocation.merge(self.model.funds, on="FundID", how="left").merge(self.model.investors, on="InvestorID", how="left", suffixes=("", "_Investor")).merge(self.model.assets, on="AssetID", how="left", suffixes=("", "_Asset")).merge(self.model.dates, on="Date", how="left", suffixes=("", "_Date")).merge(self.model.market, on=["Date", "YearMonth"], how="left", suffixes=("", "_Market"))
        for field, value in (filters or {}).items():
            if value and value != "All" and field in frame:
                frame = frame.loc[frame[field].astype(str).eq(value)]
        return frame
