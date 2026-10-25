"""Prototype classifier: Claude Opus 5.5 with structured output."""
from __future__ import annotations

import logging
import os

import anthropic

from ..config import settings
from ..schema import ArticleAnalysis
from ..scraper import Article
from .base import Classifier, ClassifierError, system_prompt, user_message

log = logging.getLogger(__name__)


class ClaudeClassifier(Classifier):
    def __init__(self, model: str | None = None, effort: str | None = None, client: anthropic.Anthropic | None = None):
        self.model = model or settings.claude_model
        self.effort = effort or settings.claude_effort
        self.name = f"claude:{self.model}"
        if client is None and not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")):
            raise ClassifierError("ANTHROPIC_API_KEY is not set (put it in .env)")
        self.client = client or anthropic.Anthropic(max_retries=3, timeout=300)

    def classify(self, article: Article) -> ArticleAnalysis:
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
        log.info("claude %s in=%s cache_read=%s out=%s", article.url.rsplit("/", 1)[-1],
                 u.input_tokens, getattr(u, "cache_read_input_tokens", 0), u.output_tokens)
        return response.parsed_output
