"""Self-hosted classifier: any OpenAI-compatible server (llama.cpp llama-server, Ollama, vLLM).

Deployed on the in-house GPU server as llama.cpp (see deploy/inhouse-llm/). Same prompt, same schema and the same
validation for every model, so runs are comparable (`python -m app compare --with gemma`).
"""
from __future__ import annotations

import json
import os
import time

import httpx
from pydantic import ValidationError

from ..config import settings
from ..gazetteer import load as load_gazetteer
from ..schema import ArticleAnalysis
from ..scraper import Article
from .base import (Classifier, ClassifierError, candidate_places, compact_system_prompt, compact_user_message,
                   system_prompt, user_message)

SCHEMA_NOTE = (
    "\n\nAnswer with one JSON object only, matching the provided JSON schema exactly. "
    "Field meanings: victims = number of people killed or injured (0 if none or unknown); "
    "incident_date = YYYY-MM-DD or null when the article does not let you work it out; "
    "place_id must be one of the allowed ids or null; evidence must be copied character-for-character "
    "from the article body.")


class GemmaClassifier(Classifier):
    def __init__(self, base_url: str | None = None, model: str | None = None, timeout: float = 300,
                 api_key: str | None = None, transport: httpx.BaseTransport | None = None):
        self.base_url = (base_url or settings.gemma_base_url).rstrip("/")
        self.model = model or settings.gemma_model
        key = api_key if api_key is not None else os.getenv("GEMMA_API_KEY", "")
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        self.http = httpx.Client(timeout=timeout, headers=headers, transport=transport)
        # compact (default): per-article place shortlist + grammar-enforced ids; full: whole 163-place catalogue
        self.prompt_mode = os.getenv("GEMMA_PROMPT", "compact")
        self.stream = os.getenv("GEMMA_STREAM", "0") == "1"   # streaming = measure prefill/decode speed
        self.name = f"gemma:{self.model}" + ("" if self.prompt_mode == "compact" else ":full")

    @staticmethod
    def _schema(candidate_ids: list[str] | None) -> dict:
        schema = ArticleAnalysis.model_json_schema()
        props = schema["$defs"]["Incident"]["properties"]
        props["victims"]["minimum"] = 0
        if candidate_ids is not None:  # [] = no candidates: null only (never "any string")
            allowed = [{"type": "string", "enum": candidate_ids}] if candidate_ids else []
            props["place_id"] = {"anyOf": allowed + [{"type": "null"}],
                                 "description": props["place_id"].get("description", "")}
        return schema

    def _send(self, body: dict) -> tuple[int, dict | str]:
        """One chat completion. Returns (status, result) where result has model, usage, finish, content and,
        when streaming (GEMMA_STREAM=1, used for speed benchmarks), time to first token and total time."""
        url = f"{self.base_url}/chat/completions"
        if not self.stream:
            r = self.http.post(url, json=body)
            if r.status_code >= 400:
                return r.status_code, r.text
            data = r.json()
            choice = (data.get("choices") or [{}])[0]
            return 200, {"model": data.get("model"), "usage": data.get("usage") or {}, "timings": data.get("timings"),
                         "finish": choice.get("finish_reason"),
                         "content": (choice.get("message") or {}).get("content") or ""}
        t0, ttft, parts = time.monotonic(), None, []
        out = {"model": None, "usage": {}, "timings": None, "finish": None}
        with self.http.stream("POST", url, json={**body, "stream": True,
                                                 "stream_options": {"include_usage": True}}) as r:
            if r.status_code >= 400:
                r.read()
                return r.status_code, r.text
            for line in r.iter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                ev = json.loads(payload)
                out["model"] = ev.get("model") or out["model"]
                out["usage"] = ev.get("usage") or out["usage"]
                out["timings"] = ev.get("timings") or out["timings"]
                for ch in ev.get("choices") or []:
                    if (ch.get("delta") or {}).get("content"):
                        ttft = ttft if ttft is not None else time.monotonic() - t0
                        parts.append(ch["delta"]["content"])
                    out["finish"] = ch.get("finish_reason") or out["finish"]
        return 200, {**out, "content": "".join(parts), "ttft": ttft, "total": time.monotonic() - t0}

    @staticmethod
    def _speed(res: dict) -> dict:
        """Prefill/decode speed from client-side timing (same method for every server)."""
        if res.get("ttft") is None:
            return {}
        u, ttft, total = res["usage"], res["ttft"], res["total"]
        prompt, completion = u.get("prompt_tokens", 0), u.get("completion_tokens", 0)
        details = u.get("prompt_tokens_details") or {}
        cached = details.get("cached_tokens")
        if cached is None and res.get("timings"):                 # llama.cpp: prompt_n = tokens actually computed
            cached = max(0, prompt - res["timings"].get("prompt_n", prompt))
        computed = prompt - (cached or 0)
        return {"ttft_s": round(ttft, 3), "prompt_tokens": prompt, "cached_tokens": cached,
                "prefill_tps": round(computed / ttft, 1) if ttft > 0 else None,
                "decode_tps": round((completion - 1) / (total - ttft), 1) if completion > 1 and total > ttft else None}

    @staticmethod
    def _keep_allowed_places(analysis: ArticleAnalysis, allowed: set[str]) -> ArticleAnalysis:
        """The grammar should already restrict place_id; this check makes it a guarantee. An id outside the
        allowed set becomes null, and the location phrase is matched locally instead (store.locate)."""
        for inc in analysis.incidents:
            if inc.place_id is not None and inc.place_id not in allowed:
                inc.place_id = None
        return analysis

    def classify(self, article: Article) -> ArticleAnalysis:
        return self.classify_with_meta(article)[0]

    def classify_with_meta(self, article: Article) -> tuple[ArticleAnalysis, dict]:
        if self.prompt_mode == "compact":
            candidates = candidate_places(article)
            allowed = {p.id for p in candidates}
            messages = [{"role": "system", "content": compact_system_prompt() + SCHEMA_NOTE},
                        {"role": "user", "content": compact_user_message(article, candidates)}]
            schema = self._schema([p.id for p in candidates])
        else:
            allowed = {p.id for p in load_gazetteer().places}
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
                status, res = self._send(body)
            except httpx.HTTPError as e:
                raise ClassifierError(f"local model server unreachable: {type(e).__name__}") from e
            if status in (401, 403):
                raise ClassifierError("local model server rejected the API key", permanent=True)
            if status == 404:
                raise ClassifierError(f"local model {self.model!r} or endpoint not found", permanent=True)
            if status >= 400:
                raise ClassifierError(f"local model server error {status}: {str(res)[:200]}")
            u = res["usage"]
            usage["input_tokens"] += u.get("prompt_tokens", 0)
            usage["output_tokens"] += u.get("completion_tokens", 0)
            content = res["content"]
            if res["finish"] == "length":
                last_error = "output was cut off (finish_reason=length)"
            else:
                try:
                    analysis = self._keep_allowed_places(
                        ArticleAnalysis.model_validate(json.loads(content)), allowed)
                    meta = {"model": res["model"] or self.model, **usage, "cost_usd": 0,
                            "latency_s": round(time.monotonic() - started, 2), "attempts": attempt + 1,
                            **self._speed(res)}
                    return analysis, meta
                except (ValueError, ValidationError) as e:
                    last_error = str(e)[:400]
            # One corrective retry: show the model what was wrong instead of repeating the same request.
            body = {**body, "messages": messages + [
                {"role": "assistant", "content": content[:2000]},
                {"role": "user", "content": f"That answer was invalid ({last_error}). Return one complete, valid "
                                            f"JSON object that matches the schema."}]}
        raise ClassifierError(f"local model returned invalid output: {last_error}")
