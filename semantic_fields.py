"""Shared helpers that map loosely written field / measure names onto the semantic model.

Local LLMs write the same field in many ways (``Fund.FundName``, ``Fund[FundName]``,
``'Fund'[FundName]``, ``FundName``). Everything the AI returns is normalised here so the
rest of the pipeline only ever sees canonical ``Table.Column`` names and supported measures.
"""
from __future__ import annotations

import re

from models import SemanticSchema

# A column reference, with or without quotes around the table name: 'Fund'[FundName] or Fund[FundName].
COLUMN_REF = re.compile(r"(?:'([^']+)'|\b([A-Za-z_][A-Za-z0-9_]*))\[([^\]]+)\]")
# A column reference used as a filter condition, e.g. 'Date'[Date] >= DATE(2025, 1, 1).
FILTER_REF = re.compile(r"(?:'([^']+)'|\b([A-Za-z_][A-Za-z0-9_]*))\[([^\]]+)\]\s*(?:>=|<=|<>|=|>|<)")

# Measures the synthetic engine can actually compute (kept in sync with synthetic_dax_engine).
SUPPORTED_MEASURES = (
    "Total Allocation", "Average Allocation", "Total Target Allocation", "Allocation Variance",
    "Allocation Variance %", "Average Return %", "Total Units", "Average NAV", "Fund Count",
    "Investor Count", "Asset Count", "Top Fund Allocation", "Total Net Flow", "Average Fee %",
    "Average Exposure %",
)

MEASURE_ALIASES = {
    "allocationamount": "Total Allocation", "allocation": "Total Allocation", "sum of allocation": "Total Allocation",
    "targetallocation": "Total Target Allocation", "returnpercent": "Average Return %", "return": "Average Return %",
    "return %": "Average Return %", "netflow": "Total Net Flow", "net flow": "Total Net Flow",
    "managementfeepercent": "Average Fee %", "fee": "Average Fee %", "exposurepercent": "Average Exposure %",
    "units": "Total Units", "nav": "Average NAV",
}


def column_refs(query: str) -> list[tuple[str, str]]:
    return [(quoted or bare, column) for quoted, bare, column in COLUMN_REF.findall(query)]


def filter_refs(query: str) -> set[tuple[str, str]]:
    return {(quoted or bare, column) for quoted, bare, column in FILTER_REF.findall(query)}


def normalize_field(raw: str | None, schema: SemanticSchema) -> str | None:
    """Return the canonical ``Table.Column`` for a loosely written field, or None."""
    if not raw:
        return None
    text = str(raw).strip().strip('"')
    match = COLUMN_REF.fullmatch(text)
    if match:
        table, column = match.group(1) or match.group(2), match.group(3)
    elif "." in text:
        table, column = text.split(".", 1)
    else:
        table, column = None, text
    table = table.strip("' ") if table else None
    column = column.strip("[] ")
    for schema_table in schema.tables:
        if table and schema_table.name.lower() != table.lower():
            continue
        for schema_column in schema_table.columns:
            if schema_column.name.lower() == column.lower():
                return f"{schema_table.name}.{schema_column.name}"
    return None


def normalize_measure(raw: str | None) -> str | None:
    if not raw:
        return None
    text = str(raw).strip().strip('"[]')
    if "." in text:
        text = text.split(".", 1)[1]
    text = text.strip("[] ")
    for measure in SUPPORTED_MEASURES:
        if measure.lower() == text.lower():
            return measure
    return MEASURE_ALIASES.get(text.lower())


def frame_column(table: str, column: str, columns) -> str | None:
    """Map a Table[Column] reference onto the joined frame's column name."""
    suffixed = f"{column}_{table}"
    if suffixed in columns:  # e.g. Investor[Region] -> Region_Investor
        return suffixed
    return column if column in columns else None


CHART_KEYWORDS: list[tuple[tuple[str, ...], str]] = [
    (("pie", "donut", "pasta", "halka"), "pie"),
    (("stacked", "yığılmış", "yığın"), "stacked_bar"),
    (("scatter", "saçılım", "nokta grafi"), "scatter"),
    (("line chart", "line graph", "çizgi"), "line"),
    (("table", "tablo"), "table"),
    (("bar chart", "bar graph", "column chart", "sütun", "çubuk", "bar "), "bar"),
]


def contains_word(text: str, words) -> bool:
    """Match at a word start so "most" does not hit "almost"; a trailing space in a keyword
    also requires a word end ("top " must not match "toplam"). Turkish suffixes still match."""
    return any(re.search(r"(?<!\w)" + re.escape(word.strip()) + (r"\b" if word.endswith(" ") else ""), text) for word in words)


def requested_chart(question: str) -> str | None:
    """Chart type the user explicitly asked for in the question, if any."""
    text = f" {question.lower()} "
    return next((value for words, value in CHART_KEYWORDS if contains_word(text, words)), None)
