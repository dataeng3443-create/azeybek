from __future__ import annotations

import re

import pandas as pd

from semantic_fields import column_refs, filter_refs, frame_column


class SyntheticDaxError(ValueError):
    pass


MEASURE_COLUMNS = {
    "Total Allocation": ("AllocationAmount", "sum"), "Average Allocation": ("AllocationAmount", "mean"),
    "Total Target Allocation": ("TargetAllocation", "sum"), "Allocation Variance": ("_variance", "sum"),
    "Allocation Variance %": ("_variance_pct", "mean"), "Average Return %": ("ReturnPercent", "mean"),
    "Total Units": ("Units", "sum"), "Average NAV": ("NAV", "mean"),
    "Fund Count": ("FundID", "nunique"), "Investor Count": ("InvestorID", "nunique"), "Asset Count": ("AssetID", "nunique"),
    "Top Fund Allocation": ("AllocationAmount", "sum"),
    "Total Net Flow": ("NetFlow", "sum"), "Average Fee %": ("ManagementFeePercent", "mean"), "Average Exposure %": ("ExposurePercent", "mean"),
}


class SyntheticDaxEngine:
    """A deliberately small, read-only DAX-like execution layer for the prototype."""

    def __init__(self, frame: pd.DataFrame, max_rows: int = 10_000):
        self.frame = frame.copy()
        self.max_rows = max_rows

    def execute(self, query: str) -> pd.DataFrame:
        if "SUMMARIZECOLUMNS" not in query.upper() and "TOPN" not in query.upper():
            return self._single_metric(query)
        # Group by every column reference (quoted or not) that is not used as a filter condition.
        conditions = filter_refs(query)
        group_columns = []
        for table, column in column_refs(query):
            if (table, column) in conditions:
                continue
            resolved = frame_column(table, column, self.frame.columns)
            if resolved and resolved not in group_columns:
                group_columns.append(resolved)
        measures = [name for name in MEASURE_COLUMNS if f'"{name}"' in query or f"[{name}]" in query]
        if not measures:
            measures = ["Total Allocation"]
        filtered = self._apply_query_filters(self.frame, query)
        result = self._aggregate(filtered, group_columns, measures)
        top_match = re.search(r"TOPN\(\s*(\d+)", query, re.IGNORECASE)
        order_match = re.search(r"ORDER BY\s+\[([^\]]+)\]\s*(DESC|ASC)?", query, re.IGNORECASE)
        if top_match:
            result = result.sort_values(measures[0], ascending=False).head(int(top_match.group(1)))
        elif order_match and order_match.group(1) in result.columns:
            result = result.sort_values(order_match.group(1), ascending=(order_match.group(2) or "ASC").upper() != "DESC")
        elif "YearMonth" in result.columns:
            result = result.sort_values("YearMonth")
        return result.head(self.max_rows).reset_index(drop=True)

    def _apply_query_filters(self, frame: pd.DataFrame, query: str) -> pd.DataFrame:
        output = frame
        for column, value in re.findall(r"\[([^\]]+)\]\s*=\s*\"([^\"]+)\"", query):
            if column in output.columns:
                output = output.loc[output[column].astype(str).eq(value)]
        date_match = re.search(r"DATE\((\d{4}),\s*(\d{1,2}),\s*(\d{1,2})\)", query)
        if date_match:
            lower_bound = pd.Timestamp(year=int(date_match.group(1)), month=int(date_match.group(2)), day=int(date_match.group(3)))
            output = output.loc[output.Date.ge(lower_bound)]
        return output

    def _aggregate(self, frame: pd.DataFrame, columns: list[str], measures: list[str]) -> pd.DataFrame:
        working = frame.assign(_variance=frame.ActualAllocation - frame.TargetAllocation, _variance_pct=(frame.ActualAllocation - frame.TargetAllocation) / frame.TargetAllocation)
        if columns:
            grouped = working.groupby(columns, dropna=False)
            result = pd.DataFrame(index=grouped.size().index).reset_index()
            for measure in measures:
                column, operation = MEASURE_COLUMNS[measure]
                series = getattr(grouped[column], operation)()
                result[measure] = series.to_numpy()
            return result
        return self._single_metric_from_frame(working, measures)

    def _single_metric(self, query: str) -> pd.DataFrame:
        measures = [name for name in MEASURE_COLUMNS if f"[{name}]" in query]
        return self._single_metric_from_frame(self._apply_query_filters(self.frame, query), measures or ["Total Allocation"])

    def _single_metric_from_frame(self, frame: pd.DataFrame, measures: list[str]) -> pd.DataFrame:
        working = frame.assign(_variance=frame.ActualAllocation - frame.TargetAllocation, _variance_pct=(frame.ActualAllocation - frame.TargetAllocation) / frame.TargetAllocation)
        values = {}
        for measure in measures:
            column, operation = MEASURE_COLUMNS[measure]
            values[measure] = getattr(working[column], operation)()
        return pd.DataFrame([values])
