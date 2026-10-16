from __future__ import annotations

import re

from models import SemanticSchema
from semantic_fields import column_refs


class DaxValidationError(ValueError):
    pass


class DaxValidator:
    MAX_LENGTH = 4_000
    FORBIDDEN = (";", "CREATE", "ALTER", "DELETE", "INSERT", "UPDATE", "DROP", "DEFINE", "EXECUTE")
    ALLOWED_FUNCTIONS = ("EVALUATE", "SUMMARIZECOLUMNS", "FILTER", "TOPN", "CALCULATE", "SUM", "AVERAGE", "COUNTROWS", "DIVIDE", "ORDER BY", "DATE", "KEEPFILTERS")

    def __init__(self, schema: SemanticSchema):
        self.schema = schema
        self.fields = {f"{table.name}.{column.name}" for table in schema.tables for column in table.columns}
        self.measures = {measure.name for table in schema.tables for measure in table.measures}

    def validate(self, query: str) -> str:
        normalized = " ".join(query.strip().split())
        if not normalized:
            raise DaxValidationError("Query is empty.")
        if len(normalized) > self.MAX_LENGTH:
            raise DaxValidationError("Query exceeds the maximum length.")
        if not normalized.upper().startswith("EVALUATE "):
            raise DaxValidationError("Synthetic DAX must start with EVALUATE.")
        upper = normalized.upper()
        if any(token in upper for token in self.FORBIDDEN):
            raise DaxValidationError("The query contains a forbidden operation or multiple statements.")
        for table, column in column_refs(normalized):
            if f"{table}.{column}" not in self.fields:
                raise DaxValidationError(f"Unknown schema field: {table}.{column}")
        for measure in re.findall(r"\[([^\]]+)\]", normalized):
            if measure not in self.measures and not any(measure == field.split(".")[-1] for field in self.fields):
                raise DaxValidationError(f"Unknown measure or field: {measure}")
        if not any(function in upper for function in self.ALLOWED_FUNCTIONS):
            raise DaxValidationError("Unsupported synthetic DAX query.")
        return normalized
