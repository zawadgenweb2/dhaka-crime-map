from ..config import settings
from .base import Classifier, ClassifierError


def get_classifier(name: str | None = None) -> Classifier:
    """Factory keyed by CLASSIFIER in .env: gemma (in-house model server) | rules (offline keyword baseline)."""
    name = (name or settings.classifier).lower()
    if name == "gemma":
        from .gemma import GemmaClassifier
        return GemmaClassifier()
    if name == "rules":
        from .rules import RulesClassifier
        return RulesClassifier()
    raise ValueError(f"Unknown classifier {name!r}; use gemma or rules")


__all__ = ["Classifier", "ClassifierError", "get_classifier"]
