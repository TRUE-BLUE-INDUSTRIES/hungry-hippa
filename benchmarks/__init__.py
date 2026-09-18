"""Hungry Hippa benchmark campaign.

Public CLI goals (target):

    python -m benchmarks.run longmemeval --system hungry_hippa
    python -m benchmarks.compare longmemeval --systems hungry_hippa,no_memory,vector_rag

Implemented incrementally; the campaign directory is the source of truth.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATASETS = REPO / "benchmarks" / "datasets"
RESULTS = REPO / "benchmarks" / "results"
REPORTS = REPO / "benchmarks" / "reports"
CONFIGS = REPO / "benchmarks" / "configs"


def ingest_db() -> str:
    """Resolve the database path used by ingestion benchmarks."""
    return os.environ.get("HUNGRY_HIPPA_DB", str(REPO / ".bench" / "hungry_hippa.db"))
