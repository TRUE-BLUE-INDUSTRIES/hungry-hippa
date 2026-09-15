"""Standalone loader using only repository defaults and an explicit scratch DB."""
import copy
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = '_hippa_challenge_runtime'
if PACKAGE not in sys.modules:
    package = types.ModuleType(PACKAGE)
    package.__path__ = [str(ROOT)]
    sys.modules[PACKAGE] = package
from _hippa_challenge_runtime.config import DEFAULTS
from _hippa_challenge_runtime.controller import MemoryController


def controller(path, session='session-one', budget=1500):
    cfg = copy.deepcopy(DEFAULTS)
    cfg['retrieval']['vectors_enabled'] = False
    cfg['retrieval']['max_context_chars'] = budget
    cfg['consolidation']['on_session_end'] = False
    c = MemoryController(cfg, db_path=str(path))
    c.bind_session(session_id=session, platform='offline-challenge')
    return c
