from __future__ import annotations

from models import SemanticSchema


class SchemaRetriever:
    """Small deterministic retrieval layer; replace scoring with embeddings/RAG later."""
    KEYWORDS = {
        "fund": {"Fund", "Total Allocation", "Average Return %"},
        "fon": {"Fund", "Total Allocation", "Average Return %"},
        "risk": {"Fund", "Allocation Variance %"},
        "allocation": {"Allocation", "Fund", "Total Allocation"},
        "tahsis": {"Allocation", "Fund", "Total Allocation"},
        "trend": {"Date", "Total Allocation", "MoM Growth %"},
        "ay": {"Date", "Total Allocation", "MoM Growth %"},
        "month": {"Date", "Total Allocation", "MoM Growth %"},
        "investor": {"Investor", "Total Allocation"},
        "yatırımcı": {"Investor", "Total Allocation"},
        "asset": {"Asset", "Total Allocation"},
        "varlık": {"Asset", "Total Allocation"},
        "return": {"Fund", "Average Return %"},
        "getiri": {"Fund", "Average Return %"},
    }

    def retrieve(self, question: str, schema: SemanticSchema) -> dict[str, object]:
        terms = question.lower().split()
        matches = set().union(*(self.KEYWORDS.get(term, set()) for term in terms)) if terms else set()
        tables = [table for table in schema.tables if table.name in matches] or [next(table for table in schema.tables if table.name == "Allocation")]
        measures = [measure for table in schema.tables for measure in table.measures if measure.name in matches]
        return {"tables": [table.model_dump() for table in tables], "measures": [measure.model_dump() for measure in measures[:6]]}
