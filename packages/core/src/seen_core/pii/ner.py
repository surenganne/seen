"""Tier 2 (optional): names, locations and organisations with Microsoft Presidio + spaCy.

Off by default (engine = "regex"). Install with the `pii-ner` extra. Runs at ingest only: never
imported by hooks (a test enforces this). Person-name detection in code and logs is noisy.
"""

from __future__ import annotations

from typing import Any

from .. import secret
from .detect import Finding

ENTITIES = {"PERSON": "person", "LOCATION": "location", "ORGANIZATION": "organisation", "NRP": "nrp"}
MIN_SCORE = 0.6


def available() -> bool:
    try:
        import presidio_analyzer  # noqa: F401
    except ImportError:
        return False
    return True


def _analyzer() -> Any:
    from presidio_analyzer import AnalyzerEngine

    return AnalyzerEngine()


def scan(text: str, analyzer: Any | None = None) -> list[Finding]:
    if analyzer is None:
        if not available():
            return []
        analyzer = _analyzer()
    found: dict[str, Finding] = {}
    for r in analyzer.analyze(text=text, language="en"):
        typ = ENTITIES.get(r.entity_type)
        if typ is None or r.score < MIN_SCORE:
            continue
        f = found.setdefault(typ, Finding(type=typ, confidence="medium", detector="presidio"))
        f.count += 1
        f.spans.append((r.start, r.end))
        fp = secret.keyed(text[r.start:r.end].strip().lower(), 16)
        if fp not in f.fingerprints:
            f.fingerprints.append(fp)
        f.distinct = len(f.fingerprints)
    return list(found.values())
