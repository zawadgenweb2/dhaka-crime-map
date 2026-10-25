from ..config import settings
from .base import Classifier, ClassifierError


def get_classifier(name: str | None = None) -> Classifier:
    """Factory keyed by CLASSIFIER in .env: claude | gemma | rules."""
    name = (name or settings.classifier).lower()
    if name == "claude":
        from .claude import ClaudeClassifier
        return ClaudeClassifier()
    if name == "gemma":
        from .gemma import GemmaClassifier
        return GemmaClassifier()
    if name == "rules":
        from .rules import RulesClassifier
        return RulesClassifier()
    raise ValueError(f"Unknown classifier {name!r}; use claude, gemma or rules")


__all__ = ["Classifier", "ClassifierError", "get_classifier"]
