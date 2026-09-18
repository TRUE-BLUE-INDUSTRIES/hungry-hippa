#!/usr/bin/env python3
"""One command: run every test suite, the demo check and the eval drift check.

    python scripts/check_all.py

This is the same set of steps the CI workflow runs, so a green local run and a
green CI run mean the same thing. Exit code is non-zero if anything fails, and
each suite's own output is streamed through unchanged.

Nothing here touches a production database: every suite uses throwaway temp
databases, the demo uses a throwaway database, and the eval check writes only to
a temp directory.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Sequence, Tuple

REPO = Path(__file__).resolve().parent.parent

STEPS: Sequence[Tuple[str, List[str]]] = (
    ("acceptance (T1-T10)", ["python", "tests/test_acceptance.py"]),
    ("migration + compatibility", ["python", "tests/test_migration.py"]),
    ("memory architecture", ["python", "tests/test_memory_architecture.py"]),
    ("MCP integration (official SDK)", ["python", "tests/test_mcp_integration.py"]),
    ("identity binding", ["python", "tests/test_trust_boundary.py"]),
    ("owner token", ["python", "tests/test_trust_token.py"]),
    ("existence oracle", ["python", "tests/test_existence_oracle.py"]),
    ("file permissions", ["python", "tests/test_file_permissions.py"]),
    ("provenance", ["python", "tests/test_provenance.py"]),
    ("injection framing", ["python", "tests/test_injection_framing.py"]),
    ("supersession", ["python", "tests/test_supersession.py"]),
    ("confused deputy", ["python", "tests/test_confused_deputy.py"]),
    ("resource limits", ["python", "tests/test_resource_limits.py"]),
    ("quarantine review CLI", ["python", "tests/test_quarantine_cli.py"]),
    ("chatgpt export parser", ["python", "tests/test_chatgpt_ingest.py"]),
    ("hermes session ingest", ["python", "tests/test_hermes_ingest.py"]),
