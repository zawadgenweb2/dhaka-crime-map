"""Self-hosted classifier: any OpenAI-compatible server (llama.cpp llama-server, Ollama, vLLM).

Deployed on the in-house GPU server as llama.cpp (see deploy/inhouse-llm/). Same prompt, same schema and the same
validation as Claude, so results are comparable (`python -m app compare --with gemma`).
"""
from __future__ import annotations

import json
import os
import time

import httpx
from pydantic import ValidationError

from ..config import settings
from ..schema import ArticleAnalysis
from ..scraper import Article
from .base import (Classifier, ClassifierError, candidate_places, compact_system_prompt, compact_user_message,
                   system_prompt, user_message)

SCHEMA_NOTE = (
    "\n\nAnswer with one JSON object only, matching the provided JSON schema exactly. "
    "Field meanings: victims = number of people killed or injured (0 if none or unknown); "
    "incident_date = YYYY-MM-DD or null when the article does not let you work it out; "
    "place_id must be an id from the catalogue above or null; evidence must be copied character-for-character "
    "from the article body.")


class GemmaClassifier(Classifier):
    def __init__(self, base_url: str | None = None, model: str | None = None, timeout: float = 300,
                 api_key: str | None = None, transport: httpx.BaseTransport | None = None):
        self.base_url = (base_url or settings.gemma_base_url).rstrip("/")
        self.model = model or settings.gemma_model
        key = api_key if api_key is not None else os.getenv("GEMMA_API_KEY", "")
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        self.http = httpx.Client(timeout=timeout, headers=headers, transport=transport)
        # compact (default): per-article place shortlist + grammar-enforced ids; full: same prompt as Claude
        self.prompt_mode = os.getenv("GEMMA_PROMPT", "compact")
        self.name = f"gemma:{self.model}" + ("" if self.prompt_mode == "compact" else ":full")

    @staticmethod
    def _schema(candidate_ids: list[str] | None) -> dict:
        schema = ArticleAnalysis.model_json_schema()
        props = schema["$defs"]["Incident"]["properties"]
        props["victims"]["minimum"] = 0
        if candidate_ids:
            props["place_id"] = {"anyOf": [{"type": "string", "enum": candidate_ids}, {"type": "null"}],
                                 "description": props["place_id"].get("description", "")}
        return schema

    def classify(self, article: Article) -> ArticleAnalysis:
        return self.classify_with_meta(article)[0]

    def classify_with_meta(self, article: Article) -> tuple[ArticleAnalysis, dict]:
        if self.prompt_mode == "compact":
            candidates = candidate_places(article)
            messages = [{"role": "system", "content": compact_system_prompt() + SCHEMA_NOTE},
                        {"role": "user", "content": compact_user_message(article, candidates)}]
            schema = self._schema([p.id for p in candidates])
        else:
            messages = [{"role": "system", "content": system_prompt() + SCHEMA_NOTE},
                        {"role": "user", "content": user_message(article)}]
            schema = self._schema(None)
        body = {
            "model": self.model, "messages": messages, "temperature": 0, "max_tokens": 4096,
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "article_analysis", "schema": schema, "strict": True}},
            "cache_prompt": True,                                   # llama.cpp: reuse the shared prompt prefix
            "chat_template_kwargs": {"enable_thinking": False},     # plain extraction, no reasoning trace
        }
        usage = {"input_tokens": 0, "output_tokens": 0}
        started = time.monotonic()
        last_error = ""
        for attempt in range(2):
            try:
                r = self.http.post(f"{self.base_url}/chat/completions", json=body)
            except httpx.HTTPError as e:
                raise ClassifierError(f"local model server unreachable: {type(e).__name__}") from e
            if r.status_code in (401, 403):
                raise ClassifierError("local model server rejected the API key", permanent=True)
            if r.status_code == 404:
                raise ClassifierError(f"local model {self.model!r} or endpoint not found", permanent=True)
            if r.status_code >= 400:
                raise ClassifierError(f"local model server error {r.status_code}: {r.text[:200]}")
            data = r.json()
            u = data.get("usage") or {}
            usage["input_tokens"] += u.get("prompt_tokens", 0)
            usage["output_tokens"] += u.get("completion_tokens", 0)
            choice = (data.get("choices") or [{}])[0]
            content = (choice.get("message") or {}).get("content") or ""
            if choice.get("finish_reason") == "length":
                last_error = "output was cut off (finish_reason=length)"
            else:
                try:
                    analysis = ArticleAnalysis.model_validate(json.loads(content))
                    meta = {"model": data.get("model") or self.model, **usage, "cost_usd": 0,
                            "latency_s": round(time.monotonic() - started, 2), "attempts": attempt + 1}
                    return analysis, meta
                except (ValueError, ValidationError) as e:
                    last_error = str(e)[:400]
            # One corrective retry: show the model what was wrong instead of repeating the same request.
            body = {**body, "messages": messages + [
                {"role": "assistant", "content": content[:2000]},
                {"role": "user", "content": f"That answer was invalid ({last_error}). Return one complete, valid "
                                            f"JSON object that matches the schema."}]}
        raise ClassifierError(f"local model returned invalid output: {last_error}")
