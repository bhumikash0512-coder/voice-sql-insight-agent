from __future__ import annotations

import json
import os
from typing import Any
import requests


SYSTEM_PROMPT = """You convert analytics questions into a safe JSON query plan.
Return JSON only.

Allowed output schema:
{
  "metric": "revenue|profit|cost|units|incidents|churn|csat|risk",
  "dimension": "region|product_line|month|risk",
  "mode": "ranking|trend|risk",
  "sort": "desc|asc",
  "filters": {
    "region": "North|South|East|West",
    "product_line": "Alpha|Beta",
    "month": "2025-01-01|2025-02-01|2025-03-01|2025-04-01"
  }
}

Rules:
- Use only the allowed schema, fields, and enum values.
- Never output SQL.
- Never invent columns or tables.
- For trend questions, use dimension=month and mode=trend.
- For anomaly/risk/issues questions, use mode=risk and dimension=risk.
- For "highest/top/best" use sort=desc.
- For "lowest/bottom/worst" use sort=asc.
""".strip()


class LLMPlanner:
    def __init__(self) -> None:
        # Ollama configuration (Priority: Local/Configured Ollama)
        self.ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").strip().rstrip("/")
        self.ollama_model = os.getenv("OLLAMA_MODEL", "llama2").strip()
        self.ollama_api_key = os.getenv("OLLAMA_API_KEY", "").strip()

        # Fallback to remote API (e.g. OpenAI-compatible endpoint)
        self.api_key = os.getenv("LLM_API_KEY", "").strip()
        self.api_base_url = os.getenv("LLM_API_BASE_URL", "").strip()
        self.model = os.getenv("LLM_MODEL", "").strip()

    @property
    def enabled(self) -> bool:
        """Check if either Ollama or API is available"""
        return bool(self.ollama_base_url) or bool(self.api_key and self.api_base_url and self.model)

    def build_plan(self, question: str, context: dict[str, Any]) -> dict[str, Any] | None:
        """Build query plan using Ollama (local) or API (remote)"""
        if not self.enabled:
            return None

        # Try Ollama first (local, faster, no API key needed)
        plan = self._try_ollama_plan(question, context)
        if plan:
            return plan

        # Fallback to remote API
        return self._try_api_plan(question, context)

    def _try_ollama_plan(self, question: str, context: dict[str, Any]) -> dict[str, Any] | None:
        """Use Ollama instance (local or remote) for query planning"""
        if not self.ollama_base_url:
            return None

        try:
            user_message = f"""Convert this analytics question to a query plan.

Question: {question}
Prior Context: {json.dumps(context)}
Schema: business_metrics table with dimensions [region, product_line, month] and metrics [revenue, profit, cost, units, incidents, churn, csat, risk]

Return ONLY valid JSON matching the schema. No markdown, no explanations."""

            headers = {"Content-Type": "application/json"}
            if self.ollama_api_key:
                headers["Authorization"] = f"Bearer {self.ollama_api_key}"

            response = requests.post(
                f"{self.ollama_base_url}/api/generate",
                json={
                    "model": self.ollama_model,
                    "prompt": user_message,
                    "system": SYSTEM_PROMPT,
                    "stream": False,
                    "temperature": 0,
                },
                headers=headers,
                timeout=30,
            )
            response.raise_for_status()

            data = response.json()
            content = data.get("response", "").strip()

            if not content:
                return None

            # Clean markdown wrappers if present
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]

            content = content.strip()

            try:
                plan = json.loads(content)
                return plan if isinstance(plan, dict) else None
            except json.JSONDecodeError:
                return None

        except (requests.RequestException, requests.Timeout, KeyError):
            return None

    def _try_api_plan(self, question: str, context: dict[str, Any]) -> dict[str, Any] | None:
        """Fallback to remote HTTP API (OpenAI-compatible)"""
        if not (self.api_key and self.api_base_url and self.model):
            return None

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "question": question,
                            "prior_context": context,
                            "schema": {
                                "table": "business_metrics",
                                "dimensions": ["region", "product_line", "month"],
                                "metrics": [
                                    "revenue",
                                    "profit",
                                    "cost",
                                    "units",
                                    "incidents",
                                    "churn",
                                    "csat",
                                    "risk",
                                ],
                            },
                        }
                    ),
                },
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }

        try:
            import urllib.request
            import urllib.error

            request = urllib.request.Request(
                self.api_base_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
                method="POST",
            )

            with urllib.request.urlopen(request, timeout=20) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except (Exception, TimeoutError):
            return None

        content = self._extract_content(response_payload)
        if not content:
            return None

        try:
            plan = json.loads(content)
        except json.JSONDecodeError:
            return None

        return plan if isinstance(plan, dict) else None

    @staticmethod
    def _extract_content(payload: dict[str, Any]) -> str:
        """Extract text content from API response"""
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        message = choices[0].get("message", {})
        content = message.get("content", "")

        if isinstance(content, str):
            return content
        if isinstance(content, list):
            text_parts = [item.get("text", "") for item in content if isinstance(item, dict)]
            return "".join(text_parts)
        return ""