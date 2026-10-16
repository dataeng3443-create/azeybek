from __future__ import annotations

import logging
import re
import time
from typing import Any

from ai_provider import AIProvider
from dashboard_designer import DashboardDesigner
from dax_generator import DaxGenerator, deterministic_dax, window_start
from dax_validator import DaxValidationError, DaxValidator
from data_provider import DataProvider
from models import PipelineResult, QueryPlan
from schema_retriever import SchemaRetriever
from semantic_fields import SUPPORTED_MEASURES, contains_word, frame_column, normalize_field, normalize_measure, requested_chart

logger = logging.getLogger(__name__)

INTENTS = ("overview", "comparison", "time_series", "ranking", "single_metric")

# Order matters: more specific phrases first.
DIMENSION_KEYWORDS: list[tuple[tuple[str, ...], str]] = [
    (("fund type", "fon tür", "fon tip"), "Fund.FundType"),
    (("risk",), "Fund.RiskLevel"),
    (("investor type", "yatırımcı tip", "yatırımcı tür"), "Investor.InvestorType"),
    (("segment",), "Investor.Segment"),
    (("age group", "yaş grub", "yaş"), "Investor.AgeGroup"),
    (("investor region", "yatırımcı bölge"), "Investor.Region"),
    (("region", "bölge"), "Fund.Region"),
    (("strategy", "strateji"), "Fund.Strategy"),
    (("manager", "yönetici"), "Fund.Manager"),
    (("currency", "döviz", "para birim"), "Fund.Currency"),
    (("aum",), "Fund.AUMBand"),
    (("sector", "sektör"), "Asset.Sector"),
    (("country", "ülke"), "Asset.Country"),
    (("credit rating", "kredi not", "rating"), "Asset.CreditRating"),
    (("asset class", "varlık sınıf", "asset", "varlık"), "Asset.AssetClass"),
    (("market regime", "piyasa rejim"), "Market.MarketRegime"),
    (("quarter", "çeyrek"), "Date.Quarter"),
    (("investor", "yatırımcı"), "Investor.Segment"),
    (("fund", "fon"), "Fund.FundName"),
]
MEASURE_KEYWORDS: list[tuple[tuple[str, ...], str]] = [
    (("net flow", "netflow", "flow", "giriş", "çıkış", "akış"), "Total Net Flow"),
    (("fee", "ücret", "masraf"), "Average Fee %"),
    (("exposure", "maruziyet", "pozisyon ağırlığı"), "Average Exposure %"),
    (("variance", "sapma", "hedef"), "Allocation Variance %"),
    (("return", "getiri", "performans", "performance"), "Average Return %"),
    (("nav",), "Average NAV"),
    (("units", "pay adedi"), "Total Units"),
    (("fund count", "number of funds", "fon sayısı"), "Fund Count"),
    (("investor count", "number of investors", "yatırımcı sayısı"), "Investor Count"),
]
RANKING_WORDS = ("top ", "highest", "most", "largest", "biggest", "best", "en yüksek", "en çok", "en fazla", "en büyük", "en iyi", "ilk ", "hangi fon", "which fund", "hangisi", "lider")
TREND_WORDS = ("trend", "over time", "monthly", "aylık", "zaman içinde", "zaman serisi", "zamanla", "evolution", "gelişim", "seyri", "seyir")
GROUPING_WORDS = (" by ", " per ", "each", "breakdown", "compare", "comparison", "versus", " vs", "göre", "bazında", "başına", "kırılım", "dağılım", "karşılaştır", "her ")
TOTAL_WORDS = ("total", "toplam", "how much", "ne kadar", "sum of")
OVERVIEW_WORDS = ("overview", "özet", "genel bakış", "genel durum", "summary")
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "six": 6, "nine": 9, "twelve": 12, "bir": 1, "iki": 2, "üç": 3, "altı": 6, "dokuz": 9, "on iki": 12, "yirmi dört": 24}


def _has(text: str, words) -> bool:
    return contains_word(text, words)


def _first_match(text: str, table: list[tuple[tuple[str, ...], str]]) -> str | None:
    return next((value for words, value in table if _has(text, words)), None)


def _number(token: str) -> int | None:
    return int(token) if token.isdigit() else NUMBER_WORDS.get(token)


def _time_window(text: str) -> int | None:
    number = r"(\d+|one|two|three|six|nine|twelve|bir|iki|üç|altı|dokuz|on iki|yirmi dört)"
    month = re.search(rf"(?:last|past|son|geçen|önceki)\s+{number}\s*(?:months?|ay)", text)
    if month:
        return _number(month.group(1))
    year = re.search(rf"(?:last|past|son|geçen|önceki)\s+{number}\s*(?:years?|yıl|sene)", text)
    if year and _number(year.group(1)):
        return _number(year.group(1)) * 12
    if re.search(r"(?:last|past|son|geçen)\s+(?:year|yıl|sene)", text):
        return 12
    if re.search(r"(?:last|past|son|geçen)\s+(?:quarter|çeyrek)", text):
        return 3
    if re.search(r"(?:last|past|son|geçen)\s+(?:month|ay)\b", text):
        return 1
    return None


def _top_n(text: str) -> int | None:
    match = re.search(r"(?:top|ilk|en iyi|best)\s+(\d+)", text) or re.search(r"(\d+)\s+(?:fon|fund|funds)", text)
    return int(match.group(1)) if match else None


class AnalyticsAgent:
    def __init__(self, provider: DataProvider, ai: AIProvider | None, max_repair_attempts: int, max_kpis: int):
        self.provider, self.ai = provider, ai
        self.schema = provider.get_schema()
        self.validator = DaxValidator(self.schema)
        self.retriever = SchemaRetriever()
        self.generator = DaxGenerator(ai)
        self.designer = DashboardDesigner(ai, max_kpis)
        self.max_repair_attempts = max_repair_attempts

    def answer(self, question: str, filters: dict[str, str] | None = None, manual_dax: str | None = None, prefer_ai: bool = True) -> PipelineResult:
        started = time.perf_counter()
        plan, planner_ai = self._plan(question, prefer_ai)
        start = window_start(self.provider.latest_date(), plan.time_window_months)
        context = self.retriever.retrieve(question, self.schema)
        candidate, dax_ai = (manual_dax, False) if manual_dax else self.generator.generate(plan, context, prefer_ai, start)
        dax, warnings = self._validate_or_repair(candidate or deterministic_dax(plan, start), plan, context, prefer_ai, start)
        if not manual_dax and start and "DATE(" not in dax.upper():
            warnings.append("The generated query ignored the requested time window; a safe query was used instead.")
            dax = self.validator.validate(deterministic_dax(plan, start))
        try:
            frame = self.provider.execute_dax(dax, filters)
        except Exception as error:  # an AI query may use a pattern the synthetic engine cannot run
            if manual_dax:
                raise
            logger.warning("ai_query_execution_failed error=%s", type(error).__name__)
            warnings.append("The generated query could not be executed; a safe query was used instead.")
            dax = self.validator.validate(deterministic_dax(plan, start))
            frame = self.provider.execute_dax(dax, filters)
        if not manual_dax and not self._matches_plan(frame, plan):
            # The AI query ran but did not return the shape the question asks for (e.g. a
            # single total instead of one row per fund). Use the deterministic query instead.
            warnings.append("The generated query did not match the question; a safe query was used instead.")
            dax = self.validator.validate(deterministic_dax(plan, start))
            frame = self.provider.execute_dax(dax, filters)
        dashboard, designer_ai = self.designer.design(question, plan, frame, prefer_ai)
        used_ai = planner_ai or dax_ai or designer_ai
        logger.info("analytics_pipeline duration=%.3fs rows=%s ai=%s", time.perf_counter() - started, len(frame), used_ai)
        return PipelineResult(plan=plan, dax=dax, dashboard=dashboard, result_columns=list(frame.columns), row_count=len(frame), used_ollama=used_ai, answer_text=self._answer_from_result(plan, frame), warnings=warnings, data=frame.to_dict(orient="records"))

    def _matches_plan(self, frame, plan: QueryPlan) -> bool:
        measure = plan.measures[0] if plan.measures else None
        if measure and measure not in frame.columns:
            return False
        if plan.intent == "single_metric":
            return True
        for dimension in plan.dimensions:
            table, column = dimension.split(".", 1)
            if not frame_column(table, column, frame.columns):
                return False
        return True

    @staticmethod
    def _answer_from_result(plan: QueryPlan, frame):
        """A concise answer that is derived only from the executed result."""
        if frame.empty:
            return "Seçili filtreler için sonuç bulunamadı. Filtreleri genişletmeyi deneyebilirsin."
        numeric = frame.select_dtypes("number").columns.tolist()
        metric = plan.measures[0] if plan.measures and plan.measures[0] in frame.columns else (numeric[0] if numeric else None)
        if not metric:
            return f"Sorgu {len(frame):,} satır sonuç döndürdü. Ayrıntıları aşağıdaki tabloda inceleyebilirsin."
        is_percent = "%" in metric or "Return" in metric
        is_average = metric.startswith("Average") or is_percent
        value = float(frame[metric].iloc[0]) if len(frame) == 1 else float(frame[metric].mean() if is_average else frame[metric].sum())

        def fmt(number: float) -> str:
            return f"{number:.2%}" if is_percent else (f"{number / 1_000_000:,.1f}M" if abs(number) >= 1_000_000 else f"{number:,.0f}")

        dimensions = [column for column in frame.columns if column not in numeric]
        period = f" (son {plan.time_window_months} ay)" if plan.time_window_months else ""
        if plan.intent == "time_series" and len(frame) > 1 and "YearMonth" in frame.columns and len(dimensions) == 1:
            first, last = float(frame[metric].iloc[0]), float(frame[metric].iloc[-1])
            change = ((last - first) / abs(first)) if first else 0
            label = "ortalama" if is_average else "toplam"
            return f"{metric}{period} dönem boyunca {label} {fmt(value)}; ilk ve son ay arasında {change:+.1%} değişim var. Trend grafiği aşağıda."
        if dimensions and len(frame) > 1:
            dimension = dimensions[-1] if dimensions[0] == "YearMonth" and len(dimensions) > 1 else dimensions[0]
            totals = frame.groupby(dimension)[metric].mean() if is_average else frame.groupby(dimension)[metric].sum()
            leader = totals.idxmax()
            return f"{metric}{period} için en yüksek sonuç {leader} kategorisinde: {fmt(float(totals.max()))}. Karşılaştırma görseli aşağıda."
        return f"Sorgunun yanıtı{period}: {metric} = {fmt(value)}."

    # ------------------------------------------------------------------ planning
    def _plan(self, question: str, prefer_ai: bool) -> tuple[QueryPlan, bool]:
        fallback = self._heuristic_plan(question)
        if not self.ai or not prefer_ai:
            return fallback, False
        dimensions = [f"{table.name}.{column.name}" for table in self.schema.tables if table.name not in ("Allocation",)
                      for column in table.columns if not column.name.endswith("ID") and column.data_type in ("string", "integer")]
        prompt = ("Classify the analytics question and return a JSON object with this shape:\n"
                  '{"intent": "comparison", "dimensions": ["Fund.RiskLevel"], "measures": ["Total Allocation"], '
                  '"requested_visualization": "bar", "time_window_months": null, "top_n": null}\n'
                  f"intent is one of: {', '.join(INTENTS)}. Use time_series (with dimension Date.YearMonth) for trends over time, "
                  "ranking for top/highest questions, single_metric only when no breakdown is asked.\n"
                  f"dimensions must come from: {', '.join(dimensions)}.\n"
                  f"measures must come from: {', '.join(SUPPORTED_MEASURES)}.\n"
                  "requested_visualization is one of: bar, line, pie, scatter, stacked_bar, table, kpi.\n"
                  f"Question: {question}")
        try:
            return self._merge_plan(self.ai.generate_json(prompt), fallback, question), True
        except (ValueError, RuntimeError, TypeError):
            return fallback, False

    def _merge_plan(self, raw: dict[str, Any], fallback: QueryPlan, question: str) -> QueryPlan:
        """Accept the AI plan only after mapping every field onto the semantic model."""
        if isinstance(raw.get("plan"), dict):  # some models wrap the answer
            raw = raw["plan"]
        text = f" {question.lower()} "
        intent = str(raw.get("intent", "")).strip().lower()
        intent = intent if intent in INTENTS else fallback.intent

        def as_list(value) -> list:
            return value if isinstance(value, list) else ([value] if value else [])

        dimensions = [field for field in (normalize_field(str(item), self.schema) for item in as_list(raw.get("dimensions"))) if field]
        dimensions = list(dict.fromkeys(dimensions))[:2]
        measures = [measure for measure in (normalize_measure(str(item)) for item in as_list(raw.get("measures"))) if measure]
        measures = list(dict.fromkeys(measures)) or fallback.measures
        # Explicit wording in the question beats the model's guess.
        if intent == "single_metric" and _has(text, GROUPING_WORDS) and fallback.intent != "single_metric":
            intent, dimensions = fallback.intent, fallback.dimensions
        if intent == "time_series":
            dimensions = ["Date.YearMonth", *[field for field in dimensions if not field.startswith("Date.")]][:2]
        elif intent != "single_metric" and not dimensions:
            dimensions = fallback.dimensions or ["Fund.FundName"]
        if intent == "single_metric":
            dimensions = []
        visual = requested_chart(question) or str(raw.get("requested_visualization") or "").lower() or fallback.requested_visualization

        def as_int(value, default):
            try:
                return int(value) if value not in (None, "", "null") else default
            except (TypeError, ValueError):
                return default

        window = fallback.time_window_months or as_int(raw.get("time_window_months"), None)
        top_n = fallback.top_n or as_int(raw.get("top_n"), None)
        return QueryPlan(intent=intent, dimensions=dimensions, measures=measures, requested_visualization=visual,
                         time_window_months=window if window and 1 <= window <= 120 else None,
                         top_n=top_n if top_n and 1 <= top_n <= 100 else None,
                         time_analysis=f"last {window} months" if window else None)

    @staticmethod
    def _heuristic_plan(question: str) -> QueryPlan:
        text = f" {question.lower()} "
        measure = _first_match(text, MEASURE_KEYWORDS) or "Total Allocation"
        dimension = _first_match(text, DIMENSION_KEYWORDS)
        visual = requested_chart(question)
        window = _time_window(text)
        top_n = _top_n(text)
        common = {"measures": [measure], "time_window_months": window, "top_n": top_n,
                  "time_analysis": f"last {window} months" if window else None}
        if _has(text, RANKING_WORDS) or top_n:
            return QueryPlan(intent="ranking", dimensions=[dimension or "Fund.FundName"], requested_visualization=visual or "bar", **common)
        if _has(text, TREND_WORDS) or (window and not dimension and not _has(text, TOTAL_WORDS)) or visual == "line":
            split = [dimension] if dimension and dimension not in ("Fund.FundName", "Date.Quarter") else []
            return QueryPlan(intent="time_series", dimensions=["Date.YearMonth", *split], requested_visualization=visual or "line", **common)
        if _has(text, TOTAL_WORDS) and not (dimension and _has(text, GROUPING_WORDS)) and not visual:
            return QueryPlan(intent="single_metric", requested_visualization="kpi", **common)
        if _has(text, OVERVIEW_WORDS) and not dimension:
            return QueryPlan(intent="overview", dimensions=["Fund.FundName"], requested_visualization=visual or "bar", **common)
        return QueryPlan(intent="comparison", dimensions=[dimension or "Fund.FundName"], requested_visualization=visual or "bar", **common)

    def _validate_or_repair(self, candidate: str, plan: QueryPlan, context: dict[str, object], prefer_ai: bool, start=None) -> tuple[str, list[str]]:
        warnings: list[str] = []
        for attempt in range(self.max_repair_attempts + 1):
            try:
                return self.validator.validate(candidate), warnings
            except DaxValidationError as error:
                warnings.append(f"Generated DAX was rejected: {error}")
                if not self.ai or not prefer_ai or attempt >= self.max_repair_attempts:
                    break
                repair_prompt = ("Repair this DAX into one valid read-only synthetic DAX query. Return JSON with a 'dax' property. "
                                 "Write column references with quoted table names like 'Fund'[FundName]. "
                                 f"Rejected DAX: {candidate}. Validation error: {error}. Plan: {plan.model_dump_json()}. Schema: {context}")
                try:
                    candidate = str(self.ai.generate_json(repair_prompt).get("dax", ""))
                except (ValueError, RuntimeError):
                    break
        warnings.append("A safe deterministic DAX query was used after validation.")
        return self.validator.validate(deterministic_dax(plan, start)), warnings
