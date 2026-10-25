"""Future on-device classifier: Gemma 4 E2B served by any OpenAI-compatible server.

Examples:
  Ollama:  ollama pull gemma4:e2b   ->  GEMMA_BASE_URL=http://127.0.0.1:11434/v1  GEMMA_MODEL=gemma4:e2b
  vLLM:    vllm serve google/gemma-4-E2B-it --port 8001
           ->  GEMMA_BASE_URL=http://127.0.0.1:8001/v1  GEMMA_MODEL=google/gemma-4-E2B-it
Then set CLASSIFIER=gemma. Same prompt, same schema, same validation as Claude, so results are comparable
(`python -m app compare` runs both on stored articles).
"""
from __future__ import annotations

import json

import httpx
from pydantic import ValidationError

from ..config import settings
from ..schema import ArticleAnalysis
from ..scraper import Article
from .base import Classifier, ClassifierError, system_prompt, user_message


class GemmaClassifier(Classifier):
    def __init__(self, base_url: str | None = None, model: str | None = None, timeout: float = 300):
        self.base_url = (base_url or settings.gemma_base_url).rstrip("/")
        self.model = model or settings.gemma_model
        self.name = f"gemma:{self.model}"
        self.http = httpx.Client(timeout=timeout)

    def classify(self, article: Article) -> ArticleAnalysis:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system_prompt()},
                         {"role": "user", "content": user_message(article)}],
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "article_analysis", "schema": ArticleAnalysis.model_json_schema(), "strict": True}},
            "temperature": 0,
        }
        last_error = ""
        for _ in range(2):  # small models occasionally emit invalid JSON; retry once
            try:
                r = self.http.post(f"{self.base_url}/chat/completions", json=body)
                r.raise_for_status()
                content = r.json()["choices"][0]["message"]["content"]
                return ArticleAnalysis.model_validate(json.loads(content))
            except httpx.HTTPError as e:
                raise ClassifierError(f"Gemma server unreachable or failed: {e}") from e
            except (KeyError, IndexError, ValueError, ValidationError) as e:
                last_error = str(e)[:300]
        raise ClassifierError(f"Gemma returned invalid output: {last_error}")
