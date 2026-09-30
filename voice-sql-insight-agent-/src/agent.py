from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from src.data_setup import TABLE_NAME, open_connection, parameter_placeholder
from src.llm_planner import LLMPlanner


ALLOWED_DIMENSIONS = {"region", "product_line", "month", "risk"}
ALLOWED_MODES = {"ranking", "trend", "risk"}
ALLOWED_SORTS = {"desc", "asc"}
METRIC_CONFIG = {
    "revenue": {"sql": "SUM(revenue)", "label": "revenue", "format": "currency"},
    "profit": {"sql": "SUM(revenue - cost)", "label": "profit", "format": "currency"},
    "cost": {"sql": "SUM(cost)", "label": "cost", "format": "currency"},
    "units": {"sql": "SUM(units_sold)", "label": "units sold", "format": "integer"},
    "incidents": {"sql": "SUM(incident_count)", "label": "incidents", "format": "integer"},
    "churn": {"sql": "AVG(customer_churn)", "label": "customer churn", "format": "percent"},
    "csat": {"sql": "AVG(csat)", "label": "customer satisfaction", "format": "decimal"},
}
MONTH_ALIASES = {
    "january": "2025-01-01",
    "february": "2025-02-01",
    "march": "2025-03-01",
    "april": "2025-04-01",
}

LABEL_TRANSLATIONS = {
    "north": "उत्तरी",
    "south": "दक्षिणी",
    "east": "पूर्वी",
    "west": "पश्चिमी",
    "alpha": "अल्फा",
    "beta": "बीटा",
}

# Hindi keywords for language detection
HINDI_KEYWORDS = {
    "kya", "kaun", "kaunse", "kaunsa", "kis", "kisne", "kaise", "kab", "kahan", "kahaan",
    "kyun", "kyo", "kyoki", "mujhe", "mujh", "main", "mein", "hum", "ham", "tum",
    "aap", "hai", "hain", "ha", "haaye", "na", "nahi", "nahin", "chahiye", "chahta", "chahti",
    "chahte", "zaroor", "jaroor", "apna", "apne", "apki", "apka", "vyapar",
    "dhanda", "bech", "raj", "labh", "lagat", "bikri", "kamai", "munafa", "grahak",
    "grahakon", "kharid", "sabse", "kuch", "kaisa", "kis prakar", "kam", "adhik", "zyada",
    "bahut", "thoda", "thode", "accha", "acha", "behtar", "achha", "bura",
    "nuksan", "faayda", "kahan", "kaun", "kaunsi", "kaunse", "kuchh"
}


def format_value(value: float | int | None, style: str) -> str:
    """Format values according to style"""
    if value is None:
        return "n/a"
    if style == "currency":
        return f"${value:,.0f}"
    if style == "integer":
        return f"{int(round(value)):,}"
    if style == "percent":
        return f"{value:.1f}%"
    return f"{value:.2f}"


@dataclass
class ConversationContext:
    """Track conversation state across queries"""
    metric: str = "revenue"
    dimension: str = "region"
    filters: dict[str, str] = field(default_factory=dict)
    last_sql: str = ""
    last_title: str = ""
    language: str = "en"  # Track detected language


class VoiceSQLAgent:
    def __init__(self, db_config: dict[str, Any]):
        self.db_config = db_config
        self.sessions: dict[str, ConversationContext] = {}
        self.llm_planner = LLMPlanner()

        # Load dimension values from database
        self.regions: dict[str, str] = self._load_dimension_values("region")
        self.products: dict[str, str] = self._load_dimension_values("product_line")
        self.months: dict[str, str] = self._load_dimension_values("month")

        self.allowed_filters: dict[str, set[str]] = {
            "region": set(self.regions.values()),
            "product_line": set(self.products.values()),
            "month": set(self.months.values()),
        }

    def _load_dimension_values(self, column: str) -> dict[str, str]:
        """Fetch distinct values for a column from the live database"""
        sql = f"SELECT DISTINCT {column} FROM {TABLE_NAME} WHERE {column} IS NOT NULL"
        values: dict[str, str] = {}
        try:
            with open_connection(self.db_config) as connection:
                if self.db_config["backend"] == "sqlite":
                    connection.row_factory = sqlite3.Row
                    rows = connection.execute(sql).fetchall()
                    raw_values = [row[0] for row in rows]
                else:
                    with connection.cursor() as cursor:
                        cursor.execute(sql)
                        fetched = cursor.fetchall()
                        raw_values = []
                        for row in fetched:
                            if isinstance(row, dict):
                                raw_values.append(list(row.values())[0])
                            else:
                                raw_values.append(row[0])
            for value in raw_values:
                if value:
                    values[str(value).lower()] = str(value)
        except Exception:
            pass
        return values

    def handle_query(self, session_id: str, question: str) -> dict[str, Any]:
        """Main entry point for processing a query"""
        context = self.sessions.setdefault(session_id, ConversationContext())

        # Detect language
        language = self._detect_language(question)
        context.language = language

        # Build query plan
        plan = self._build_plan(question, context)

        # Execute query
        rows = self._run_query(plan["sql"], plan["params"])

        # Build response
        response = self._build_response(question, plan, rows, context)

        # Update context
        context.metric = plan["metric"]
        context.dimension = plan["dimension"]
        context.filters = plan["filters"]
        context.last_sql = plan["sql"]
        context.last_title = response["title"]

        return {
            "question": question,
            "title": response["title"],
            "summary": response["summary"],
            "spoken_response": response["spoken_response"],
            "insights": response["insights"],
            "sql": plan["sql"],
            "params": plan["params"],
            "table": rows,
            "chart": {
                "label_key": plan["dimension_key"],
                "value_key": "value",
                "format": METRIC_CONFIG[plan["metric"]]["format"],
            },
            "context": {
                "metric": context.metric,
                "dimension": context.dimension,
                "filters": context.filters,
                "language": context.language,
            },
            "planner": plan.get("planner", "rules"),
        }

    def _detect_language(self, question: str) -> str:
        """Detect if question is in Hindi or English"""
        # Check for Devanagari script
        if re.search(r"[\u0900-\u097F]", question):
            return "hi"

        # Check for Hindi keywords
        normalized = question.lower()
        tokens = re.findall(r"\b[\w']+\b", normalized)
        if any(token in HINDI_KEYWORDS for token in tokens):
            return "hi"

        return "en"

    def _build_plan(self, question: str, context: ConversationContext) -> dict[str, Any]:
        """Build query execution plan using LLM or rules"""
        # Try LLM planner first (Ollama or API)
        llm_plan = self._try_llm_plan(question, context)
        if llm_plan is not None:
            return llm_plan

        # Fallback to rule-based planning
        normalized = question.lower().strip()
        metric = self._detect_metric(normalized, context)
        dimension = self._detect_dimension(normalized, context)
        filters = self._detect_filters(normalized, context)

        # Detect query type
        if any(term in normalized for term in ["risk", "risks", "anomaly", "anomalies", "issue", "issues"]):
            return self._risk_plan(metric, filters, planner="rules")
        if any(term in normalized for term in ["trend", "over time", "monthly", "month wise"]):
            return self._trend_plan(metric, filters, planner="rules")
        if any(term in normalized for term in ["top", "highest", "best", "leading"]):
            return self._ranking_plan(metric, dimension, filters, descending=True, planner="rules")
        if any(term in normalized for term in ["bottom", "lowest", "worst"]):
            return self._ranking_plan(metric, dimension, filters, descending=False, planner="rules")

        if self._is_broad_business_question(normalized):
            return self._ranking_plan(metric, dimension, filters, descending=True, planner="rules")

        return self._ranking_plan(metric, dimension, filters, descending=True, planner="rules")

    def _detect_metric(self, normalized: str, context: ConversationContext) -> str:
        """Detect which metric the user is asking about"""
        if any(term in normalized for term in ["what about", "follow up", "same", "that", "those", "and "]):
            return context.metric
        if "profit" in normalized or "margin" in normalized:
            return "profit"
        if "cost" in normalized or "expense" in normalized:
            return "cost"
        if "unit" in normalized or "volume" in normalized:
            return "units"
        if "incident" in normalized or "ticket" in normalized:
            return "incidents"
        if "churn" in normalized or "retention" in normalized:
            return "churn"
        if "csat" in normalized or "satisfaction" in normalized or "customer score" in normalized:
            return "csat"
        if any(term in normalized for term in ["sales", "business", "growth", "performance", "company", "financial"]):
            return "revenue"
        return "revenue"

    def _detect_dimension(self, normalized: str, context: ConversationContext) -> str:
        """Detect which dimension to group by"""
        if any(term in normalized for term in ["what about", "follow up", "same", "those", "them"]):
            return context.dimension
        if "product" in normalized or "alpha" in normalized or "beta" in normalized:
            return "product_line"
        if "month" in normalized or "trend" in normalized or "time" in normalized:
            return "month"
        if any(term in normalized for term in ["business", "company", "financial", "overall", "sales", "performance"]):
            return "region"
        return "region"

    def _detect_filters(self, normalized: str, context: ConversationContext) -> dict[str, str]:
        """Extract filter values from question"""
        filters: dict[str, str] = {}
        for region_lower, region_original in self.regions.items():
            if region_lower in normalized:
                filters["region"] = region_original
        for product_lower, product_original in self.products.items():
            if product_lower in normalized:
                filters["product_line"] = product_original
        for name, iso_date in MONTH_ALIASES.items():
            if name in normalized:
                filters["month"] = iso_date

        if any(term in normalized for term in ["what about", "follow up", "same", "that region", "that product", "there", "and "]):
            merged = context.filters.copy()
            merged.update(filters)
            return merged
        return filters

    def _is_broad_business_question(self, normalized: str) -> bool:
        """Check if question is general business inquiry"""
        return any(term in normalized for term in [
            "business", "sales", "growth", "performance", "company", "organization",
            "overall", "financial", "revenue", "profit", "cost", "churn", "customers", "customer", "trend",
        ])

    def _ranking_plan(
        self,
        metric: str,
        dimension: str,
        filters: dict[str, str],
        descending: bool,
        planner: str,
    ) -> dict[str, Any]:
        """Plan for ranking queries"""
        where_clause, params = self._build_where(filters, exclude_dimension=dimension)
        order = "DESC" if descending else "ASC"
        sql = f"""
            SELECT {dimension} AS label,
                   ROUND({METRIC_CONFIG[metric]["sql"]}, 2) AS value
            FROM {TABLE_NAME}
            {where_clause}
            GROUP BY {dimension}
            ORDER BY value {order}
            LIMIT 6
        """
        return {
            "metric": metric,
            "dimension": dimension,
            "dimension_key": "label",
            "filters": filters,
            "sql": self._compact_sql(sql),
            "params": params,
            "planner": planner,
        }

    def _trend_plan(self, metric: str, filters: dict[str, str], planner: str) -> dict[str, Any]:
        """Plan for trend queries"""
        where_clause, params = self._build_where(filters, exclude_dimension="month")
        sql = f"""
            SELECT month AS label,
                   ROUND({METRIC_CONFIG[metric]["sql"]}, 2) AS value
            FROM {TABLE_NAME}
            {where_clause}
            GROUP BY month
            ORDER BY month ASC
        """
        return {
            "metric": metric,
            "dimension": "month",
            "dimension_key": "label",
            "filters": filters,
            "sql": self._compact_sql(sql),
            "params": params,
            "planner": planner,
        }

    def _risk_plan(self, metric: str, filters: dict[str, str], planner: str) -> dict[str, Any]:
        """Plan for risk/anomaly detection queries"""
        where_clause, params = self._build_where(filters)
        label_sql = self._risk_label_sql()
        sql = f"""
            SELECT {label_sql} AS label,
                   ROUND(
                       ((customer_churn * 220) + (incident_count * 18) - (csat * 7) + ((cost / revenue) * 100)),
                       2
                   ) AS value
            FROM {TABLE_NAME}
            {where_clause}
            ORDER BY value DESC
            LIMIT 8
        """
        return {
            "metric": metric,
            "dimension": "risk",
            "dimension_key": "label",
            "filters": filters,
            "sql": self._compact_sql(sql),
            "params": params,
            "planner": planner,
        }

    def _risk_label_sql(self) -> str:
        """Generate risk label SQL based on database backend"""
        if self.db_config["backend"] == "mysql":
            return "CONCAT(month, ' / ', region, ' / ', product_line)"
        return "month || ' / ' || region || ' / ' || product_line"

    def _try_llm_plan(self, question: str, context: ConversationContext) -> dict[str, Any] | None:
        """Try to get plan from LLM (Ollama or API)"""
        try:
            payload = self.llm_planner.build_plan(
                question,
                {
                    "metric": context.metric,
                    "dimension": context.dimension,
                    "filters": context.filters,
                    "language": context.language,
                },
            )
            if payload is None:
                return None

            metric = payload.get("metric")
            dimension = payload.get("dimension")
            mode = payload.get("mode")
            sort = payload.get("sort", "desc")
            filters = payload.get("filters", {})

            # Validate response
            if metric not in METRIC_CONFIG:
                return None
            if dimension not in ALLOWED_DIMENSIONS:
                return None
            if mode not in ALLOWED_MODES:
                return None
            if sort not in ALLOWED_SORTS:
                return None
            if not isinstance(filters, dict):
                return None

            # Validate filters (guard against malformed LLM output, e.g. a list
            # instead of a string value, which would otherwise crash the
            # membership check below)
            safe_filters: dict[str, str] = {}
            for key, value in filters.items():
                if key not in self.allowed_filters:
                    return None
                if not isinstance(value, str):
                    return None
                if value not in self.allowed_filters[key]:
                    return None
                safe_filters[key] = value

            # Generate plan based on mode
            if mode == "risk":
                return self._risk_plan(metric, safe_filters, planner="llm")
            if mode == "trend":
                return self._trend_plan(metric, safe_filters, planner="llm")
            return self._ranking_plan(
                metric,
                dimension,
                safe_filters,
                descending=(sort == "desc"),
                planner="llm",
            )
        except Exception:
            # Any unexpected/malformed LLM output should never crash the
            # request — fall back to the deterministic rule-based planner.
            return None

    def _build_where(self, filters: dict[str, str], exclude_dimension: str | None = None) -> tuple[str, list[str]]:
        """Build SQL WHERE clause from filters"""
        clauses = []
        params: list[str] = []
        placeholder = parameter_placeholder(self.db_config)
        for key, value in filters.items():
            if key == exclude_dimension:
                continue
            clauses.append(f"{key} = {placeholder}")
            params.append(value)
        if not clauses:
            return "", params
        return "WHERE " + " AND ".join(clauses), params

    def _run_query(self, sql: str, params: list[str]) -> list[dict[str, Any]]:
        """Execute SQL query against database"""
        with open_connection(self.db_config) as connection:
            if self.db_config["backend"] == "sqlite":
                connection.row_factory = sqlite3.Row
                rows = connection.execute(sql, params).fetchall()
                return [dict(row) for row in rows]
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                return list(cursor.fetchall())

    def _translate_label(self, label: str, dimension: str, language: str) -> str:
        """Translate label to Hindi if needed"""
        if language != "hi":
            return label
        if dimension == "risk":
            parts = [part.strip() for part in label.split("/")]
            translated_parts = [LABEL_TRANSLATIONS.get(part.lower(), part) for part in parts]
            return " / ".join(translated_parts)
        return LABEL_TRANSLATIONS.get(label.lower().strip(), label)

    def _metric_label_for_language(self, metric_label: str, language: str) -> str:
        """Get metric label in appropriate language"""
        if language != "hi":
            return metric_label.title()

        hindi_labels = {
            "revenue": "राजस्व",
            "profit": "लाभ",
            "cost": "लागत",
            "units sold": "इकाइयाँ",
            "incidents": "घटनाएँ",
            "customer churn": "ग्राहक छोड़ने की दर",
            "customer satisfaction": "ग्राहक संतुष्टि",
        }
        return hindi_labels.get(metric_label, metric_label.title())

    def _build_response(
        self,
        question: str,
        plan: dict[str, Any],
        rows: list[dict[str, Any]],
        context: ConversationContext,
    ) -> dict[str, Any]:
        """Build natural language response"""
        language = context.language
        metric_info = METRIC_CONFIG[plan["metric"]]
        metric_label = metric_info["label"]
        label_text = self._metric_label_for_language(metric_label, language)
        title = f"{label_text} analysis" if language == "en" else f"{label_text} विश्लेषण"

        # Handle empty results
        if not rows:
            if language == "hi":
                message = "मैं इस प्रश्न के लिए मिलान करने वाले रिकॉर्ड नहीं ढूंढ पाया।"
                insight = "कृपया किसी विशेष क्षेत्र, उत्पाद या महीने के बारे में पूछें।"
            else:
                message = "I could not find matching records for that request."
                insight = "Try asking about a specific region, product, or month."
            return {
                "title": title,
                "summary": message,
                "spoken_response": message,
                "insights": [insight],
            }

        top_row = rows[0]
        bottom_row = rows[-1]
        top_label = self._translate_label(top_row["label"], plan["dimension"], language)
        bottom_label = self._translate_label(bottom_row["label"], plan["dimension"], language)
        top_value = format_value(top_row["value"], metric_info["format"])
        bottom_value = format_value(bottom_row["value"], metric_info["format"])

        # Build insights based on dimension and language
        if plan["dimension"] == "month":
            if language == "hi":
                direction = "ऊर्ध्वगामी" if rows[-1]["value"] >= rows[0]["value"] else "घटता हुआ"
                summary = (
                    f"{label_text} में {rows[0]['label']} से {rows[-1]['label']} तक {direction} रुझान देखा गया, अंत में {format_value(rows[-1]['value'], metric_info['format'])}."
                )
                insights = [
                    f"अंतिम माह: {rows[-1]['label']} पर {format_value(rows[-1]['value'], metric_info['format'])}.",
                    f"प्रारंभिक माह: {rows[0]['label']} पर {format_value(rows[0]['value'], metric_info['format'])}.",
                ]
                if rows[-1]["value"] > rows[0]["value"]:
                    insights.append("यह संकेत है कि प्रदर्शन मजबूत है; मौजूदा रणनीति जारी रखें।")
                else:
                    insights.append("यह संकेत है कि प्रदर्शन गिर रहा है; सुधार के उपाय जल्द लागू करें।")
            else:
                direction = "upward" if rows[-1]["value"] >= rows[0]["value"] else "downward"
                summary = (
                    f"{metric_label.title()} shows a {direction} trend from "
                    f"{rows[0]['label']} to {rows[-1]['label']}, ending at {format_value(rows[-1]['value'], metric_info['format'])}."
                )
                insights = [
                    f"Latest month: {rows[-1]['label']} at {format_value(rows[-1]['value'], metric_info['format'])}.",
                    f"Starting month: {rows[0]['label']} at {format_value(rows[0]['value'], metric_info['format'])}.",
                ]
                if rows[-1]["value"] > rows[0]["value"]:
                    insights.append("This indicates momentum; sustain the current strategy.")
                else:
                    insights.append("This signals a need for corrective action.")

        elif plan["dimension"] == "risk":
            if language == "hi":
                summary = f"उच्चतम जोखिम: {top_label} ({top_value})।"
                insights = [
                    f"सर्वोच्च जोखिम: {top_label} ({top_value}).",
                    f"न्यूनतम जोखिम: {bottom_label} ({bottom_value}).",
                    "ग्राहक प्रतिधारण पर तुरंत ध्यान दें।"
                ]
            else:
                summary = f"Highest risk: {top_row['label']} with score {top_value}."
                insights = [
                    f"Top risk: {top_row['label']} ({top_value}).",
                    f"Lowest risk: {bottom_row['label']} ({bottom_value}).",
                    "Prioritize customer retention immediately."
                ]

        else:
            if language == "hi":
                summary = f"{top_label} {label_text} में सबसे आगे है {top_value} के साथ।"
                insights = [
                    f"शीर्ष: {top_label} ({top_value}).",
                    f"न्यूनतम: {bottom_label} ({bottom_value}).",
                ]
            else:
                summary = f"{top_row['label']} leads for {metric_label} at {top_value}."
                insights = [
                    f"Top: {top_row['label']} ({top_value}).",
                    f"Lowest: {bottom_row['label']} ({bottom_value}).",
                ]

        spoken_response = " ".join([summary] + insights[:2])
        return {
            "title": title,
            "summary": summary,
            "spoken_response": spoken_response,
            "insights": insights,
        }

    @staticmethod
    def _compact_sql(sql: str) -> str:
        """Compact SQL by removing extra whitespace"""
        return re.sub(r"\s+", " ", sql).strip()