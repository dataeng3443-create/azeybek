"""Power BI-style model view: table cards connected by 1 → * relationship lines.

Pure functions (no Streamlit) so the diagram can be tested and reused.
"""
from __future__ import annotations

from html import escape

import pandas as pd

from models import SemanticSchema, TableSchema

CARD_WIDTH = 230
HEADER_HEIGHT = 36
ROW_HEIGHT = 21
CARD_PADDING = 10
CARD_GAP = 30
SIDE_MARGIN = 40
CANVAS_WIDTH = 1080

FACT_COLOR = "#6D5CE7"
DIMENSION_COLOR = "#172554"
LINE_COLOR = "#8B95A9"
KEY_FILL = "#F1F0FF"
TEXT_COLOR = "#172554"
MUTED_COLOR = "#94A3B8"

TYPE_LABELS = {"string": "abc", "integer": "123", "number": "1.2", "date": "date"}


def _fact_tables(schema: SemanticSchema) -> set[str]:
    """A table that only ever sits on the many side of relationships is a fact table."""
    targets = {rel.to_table for rel in schema.relationships}
    sources = {rel.from_table for rel in schema.relationships}
    return targets - sources


def _card_height(table: TableSchema, is_fact: bool) -> int:
    rows = len(table.columns) + (1 if is_fact and table.measures else 0)
    return HEADER_HEIGHT + rows * ROW_HEIGHT + CARD_PADDING


def _cardinality(frames: dict[str, pd.DataFrame] | None, table: str, column: str) -> str:
    if not frames or table not in frames or column not in frames[table].columns:
        return "1"
    return "1" if frames[table][column].is_unique else "*"


def relationship_table(schema: SemanticSchema, frames: dict[str, pd.DataFrame] | None = None) -> pd.DataFrame:
    rows = []
    for rel in schema.relationships:
        one = _cardinality(frames, rel.from_table, rel.from_column)
        many = _cardinality(frames, rel.to_table, rel.to_column)
        kind = {"1*": "Many-to-one (*:1)", "11": "One-to-one (1:1)", "**": "Many-to-many (*:*)", "*1": "One-to-many (1:*)"}[one + many]
        rows.append({
            "From": f"{rel.to_table}[{rel.to_column}]",
            "To": f"{rel.from_table}[{rel.from_column}]",
            "Cardinality": kind,
            "Cross-filter": f"Single ({rel.from_table} → {rel.to_table})",
            "Active": "Yes",
        })
    return pd.DataFrame(rows)


def relationship_svg(schema: SemanticSchema, frames: dict[str, pd.DataFrame] | None = None) -> str:
    facts = _fact_tables(schema)
    tables = {table.name: table for table in schema.tables}
    fact_names = [name for name in tables if name in facts] or [schema.tables[-1].name]
    dimension_names = [name for name in tables if name not in fact_names]

    # Balance dimension cards between the left and right columns, keeping model order.
    left: list[str] = []
    right: list[str] = []
    left_height = right_height = 0
    for name in dimension_names:
        height = _card_height(tables[name], False) + CARD_GAP
        if left_height <= right_height:
            left.append(name)
            left_height += height
        else:
            right.append(name)
            right_height += height

    fact_heights = sum(_card_height(tables[name], True) + CARD_GAP for name in fact_names)
    canvas_height = max(left_height, right_height, fact_heights) + 40

    positions: dict[str, tuple[int, int]] = {}

    def stack(names: list[str], x: int, is_fact: bool, total: int) -> None:
        y = (canvas_height - total) // 2 + CARD_GAP // 2
        for name in names:
            positions[name] = (x, y)
            y += _card_height(tables[name], is_fact) + CARD_GAP

    stack(left, SIDE_MARGIN, False, left_height)
    stack(fact_names, (CANVAS_WIDTH - CARD_WIDTH) // 2, True, fact_heights)
    stack(right, CANVAS_WIDTH - SIDE_MARGIN - CARD_WIDTH, False, right_height)

    key_columns: dict[str, set[str]] = {}
    for rel in schema.relationships:
        key_columns.setdefault(rel.from_table, set()).add(rel.from_column)
        key_columns.setdefault(rel.to_table, set()).add(rel.to_column)

    def row_center(table: str, column: str) -> int:
        _, y = positions[table]
        index = [col.name for col in tables[table].columns].index(column)
        return y + HEADER_HEIGHT + index * ROW_HEIGHT + ROW_HEIGHT // 2 + 4

    parts: list[str] = [
        f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {CANVAS_WIDTH} {canvas_height}' width='100%' "
        "style='font-family:\"Source Sans Pro\",-apple-system,Segoe UI,sans-serif;max-width:1080px;display:block;margin:auto'>",
        f"<defs><pattern id='grid' width='20' height='20' patternUnits='userSpaceOnUse'><circle cx='1' cy='1' r='1' fill='#E2E8F0'/></pattern></defs>",
        f"<rect width='{CANVAS_WIDTH}' height='{canvas_height}' rx='14' fill='#F8FAFC'/>",
        f"<rect width='{CANVAS_WIDTH}' height='{canvas_height}' rx='14' fill='url(#grid)'/>",
    ]

    # Relationship lines first so the cards sit on top of them.
    for rel in schema.relationships:
        if rel.from_table not in positions or rel.to_table not in positions:
            continue
        one_x, _ = positions[rel.from_table]
        many_x, _ = positions[rel.to_table]
        one_on_left = one_x < many_x
        x0 = one_x + CARD_WIDTH if one_on_left else one_x
        x3 = many_x if one_on_left else many_x + CARD_WIDTH
        y0, y3 = row_center(rel.from_table, rel.from_column), row_center(rel.to_table, rel.to_column)
        bend = (x3 - x0) * 0.5
        x1, x2 = x0 + bend, x3 - bend
        parts.append(f"<path d='M{x0},{y0} C{x1},{y0} {x2},{y3} {x3},{y3}' fill='none' stroke='{LINE_COLOR}' stroke-width='1.6'/>")
        # Cardinality labels at each end.
        step = 12 if one_on_left else -12
        one_label = _cardinality(frames, rel.from_table, rel.from_column)
        many_label = _cardinality(frames, rel.to_table, rel.to_column)
        parts.append(f"<text x='{x0 + step}' y='{y0 - 6}' font-size='13' font-weight='700' fill='{TEXT_COLOR}' text-anchor='middle'>{one_label}</text>")
        parts.append(f"<text x='{x3 - step}' y='{y3 - 6}' font-size='15' font-weight='700' fill='{TEXT_COLOR}' text-anchor='middle'>{many_label}</text>")
        # Filter-direction arrow at the curve midpoint (dimension → fact).
        mx, my = (x0 + 3 * x1 + 3 * x2 + x3) / 8, (y0 + 3 * y0 + 3 * y3 + y3) / 8
        d = 1 if one_on_left else -1
        parts.append(f"<circle cx='{mx:.1f}' cy='{my:.1f}' r='9' fill='#FFFFFF' stroke='{LINE_COLOR}' stroke-width='1.2'/>")
        parts.append(f"<path d='M{mx - 3 * d:.1f},{my - 4:.1f} L{mx + 4 * d:.1f},{my:.1f} L{mx - 3 * d:.1f},{my + 4:.1f} Z' fill='{LINE_COLOR}'/>")

    for name, (x, y) in positions.items():
        table = tables[name]
        is_fact = name in fact_names
        height = _card_height(table, is_fact)
        color = FACT_COLOR if is_fact else DIMENSION_COLOR
        parts.append(f"<g><rect x='{x}' y='{y + 3}' width='{CARD_WIDTH}' height='{height}' rx='10' fill='#0F172A' opacity='0.05'/>")
        parts.append(f"<rect x='{x}' y='{y}' width='{CARD_WIDTH}' height='{height}' rx='10' fill='#FFFFFF' stroke='#DDE3EE'/>")
        parts.append(f"<path d='M{x},{y + 10} a10,10 0 0 1 10,-10 h{CARD_WIDTH - 20} a10,10 0 0 1 10,10 v{HEADER_HEIGHT - 10} h-{CARD_WIDTH} Z' fill='{color}'/>")
        parts.append(f"<text x='{x + 14}' y='{y + 23}' font-size='14' font-weight='700' fill='#FFFFFF'>{escape(name)}</text>")
        parts.append(f"<text x='{x + CARD_WIDTH - 14}' y='{y + 23}' font-size='10.5' fill='#FFFFFF' opacity='0.75' text-anchor='end' letter-spacing='0.06em'>{'FACT' if is_fact else 'DIMENSION'}</text>")
        keys = key_columns.get(name, set())
        for index, column in enumerate(table.columns):
            row_y = y + HEADER_HEIGHT + index * ROW_HEIGHT + 4
            is_key = column.name in keys
            if is_key:
                parts.append(f"<rect x='{x + 1}' y='{row_y}' width='{CARD_WIDTH - 2}' height='{ROW_HEIGHT}' fill='{KEY_FILL}'/>")
                parts.append(f"<path d='M{x + 14},{row_y + 6.5} l4,4 l-4,4 l-4,-4 Z' fill='{FACT_COLOR}'/>")
            weight = "700" if is_key else "400"
            parts.append(f"<text x='{x + 26}' y='{row_y + 15}' font-size='12.5' font-weight='{weight}' fill='{TEXT_COLOR}'>{escape(column.name)}</text>")
            parts.append(f"<text x='{x + CARD_WIDTH - 14}' y='{row_y + 15}' font-size='10.5' fill='{MUTED_COLOR}' text-anchor='end'>{TYPE_LABELS.get(column.data_type, column.data_type)}</text>")
        if is_fact and table.measures:
            row_y = y + HEADER_HEIGHT + len(table.columns) * ROW_HEIGHT + 4
            parts.append(f"<line x1='{x + 10}' y1='{row_y}' x2='{x + CARD_WIDTH - 10}' y2='{row_y}' stroke='#E7EAF1'/>")
            parts.append(f"<text x='{x + 12}' y='{row_y + 15}' font-size='12.5' font-weight='700' fill='{FACT_COLOR}'>Σ  {len(table.measures)} measures</text>")
        parts.append("</g>")

    parts.append("</svg>")
    return "".join(parts)
