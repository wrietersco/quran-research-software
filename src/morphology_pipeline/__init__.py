"""
Deterministic morphology pipeline: CAMeL (primary) → segments → Stanza (validator) → rules → JSON.

Use :func:`configure_morphology_logging` once at app entry for verbose layer logs.

Note: ``calima-msa-r13`` MLE disambiguation scores each **word** largely in isolation; for
full-sentence neural disambiguation, plug a CAMeL BERT disambiguator into ``CamelEngine``
when your environment supports it.
"""

from __future__ import annotations

import logging

from .ensemble import (
    EnsembleMorphologyPipeline,
    process_sentence_ensemble,
)
from .exporter import export_json, token_record_to_dict
from .orchestrator import MorphologyPipeline, process_single_token
from .scorer import EnsembleConfig

__all__ = [
    "configure_morphology_logging",
    "MorphologyPipeline",
    "process_single_token",
    "export_json",
    "token_record_to_dict",
    "EnsembleConfig",
    "EnsembleMorphologyPipeline",
    "process_sentence_ensemble",
]


def configure_morphology_logging(
    level: int = logging.DEBUG,
    *,
    format_string: str | None = None,
) -> None:
    """Enable detailed logs for all ``src.morphology_pipeline.*`` loggers."""
    fmt = format_string or (
        "%(asctime)s %(levelname)s [%(name)s] %(message)s"
    )
    logging.basicConfig(level=level, format=fmt, force=True)
    logging.getLogger("src.morphology_pipeline").setLevel(level)
