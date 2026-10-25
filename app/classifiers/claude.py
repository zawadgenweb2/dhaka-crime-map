"""Prototype classifier: Claude Opus 5.5 with structured output and prompt caching."""
from __future__ import annotations

import logging
import os

import anthropic

from ..config import settings
from ..schema import ArticleAnalysis
from ..scraper import Article
from .base import Classifier, ClassifierError, system_prompt, user_message

log = logging.getLogger(__name__)

# US$ per million tokens for Claude Opus 5.5 (cache writes: 1.25x input for the 5-minute cache).
PRICES = {"input": 4.00, "output": 20.00, "cache_read": 0.20, "cache_write": 5.00}


def cost_usd(usage) -> float:
    def g(name):
        return getattr(usage, name, 0) or 0
    return round((g("input_tokens") * PRICES["input"] + g("output_tokens") * PRICES["output"]
                  + g("cache_read_input_tokens") * PRICES["cache_read"]
                  + g("cache_creation_input_tokens") * PRICES["cache_write"]) / 1_000_000, 5)


class ClaudeClassifier(Classifier):
    def __init__(self, model: str | None = None, effort: str | None = None, client: anthropic.Anthropic | None = None):
        self.model = model or settings.claude_model
        self.effort = effort or settings.claude_effort
        self.name = f"claude:{self.model}"
        if client is None and not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")):
            raise ClassifierError("ANTHROPIC_API_KEY is not set", permanent=True)
        # Retries live here (bounded); the job queue counts one dispatch per classify call.
        self.client = client or anthropic.Anthropic(max_retries=2, timeout=120)

    def classify(self, article: Article) -> ArticleAnalysis:
        return self.classify_with_meta(article)[0]

    def classify_with_meta(self, article: Article) -> tuple[ArticleAnalysis, dict]:
        try:
            response = self.client.beta.messages.parse(
                model=self.model,
                max_tokens=16000,
                # The long, unchanging prompt + place catalogue is cached across articles.
                system=[{"type": "text", "text": system_prompt(), "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user_message(article)}],
                output_format=ArticleAnalysis,
                thinking={"type": "adaptive"},
                output_config={"effort": self.effort},
                # If a safety classifier declines, the API retries on Anthropic's recommended fallback model.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
            raise ClassifierError(f"Claude credentials rejected ({e.status_code})", permanent=True) from e
        except anthropic.NotFoundError as e:
            raise ClassifierError(f"Claude model {self.model!r} not found", permanent=True) from e
        except anthropic.RateLimitError as e:
            raise ClassifierError("Claude rate limit reached; retry later") from e
        except anthropic.APIStatusError as e:
            raise ClassifierError(f"Claude API error {e.status_code}") from e
        except anthropic.APIConnectionError as e:
            raise ClassifierError("Could not reach the Claude API") from e

        if response.stop_reason == "refusal":
            raise ClassifierError("Claude declined to classify this article")
        if response.stop_reason == "max_tokens" or response.parsed_output is None:
            raise ClassifierError(f"Incomplete Claude response (stop_reason={response.stop_reason})")
        u = response.usage
        meta = {
            "model": getattr(response, "model", self.model),
            "input_tokens": getattr(u, "input_tokens", None),
            "cache_read_tokens": getattr(u, "cache_read_input_tokens", None),
            "cache_write_tokens": getattr(u, "cache_creation_input_tokens", None),
            "output_tokens": getattr(u, "output_tokens", None),
            "cost_usd": cost_usd(u),
        }
        log.info("claude %s in=%s cache_read=%s cache_write=%s out=%s $%.4f", article.url.rsplit("/", 1)[-1],
                 meta["input_tokens"], meta["cache_read_tokens"], meta["cache_write_tokens"], meta["output_tokens"],
                 meta["cost_usd"])
        return response.parsed_output, meta
