"""``hermes living-cortex`` CLI — observability + operations (§21).

Commands: status | recall | episodes | graph | why | consolidate | learned |
changed | forgotten | export | selftest
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict

from .config import load_config, resolve_db_path
from .controller import MemoryController
from .observability import Observability


def _controller() -> MemoryController:
    cfg = load_config()
    return MemoryController(cfg, db_path=resolve_db_path(cfg))


def _print_json(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def living_cortex_command(args) -> None:
    sub = getattr(args, "living_cortex_command", None) or "status"
    if sub == "selftest":
        return _cmd_selftest(args)
    c = _controller()
    obs = Observability(c.db, c.cfg, controller=c)
    if sub == "status":
        _print_json(c.status())
    elif sub == "recall":
        q = getattr(args, "query", "")
        if not q:
            print("Usage: hermes living-cortex recall '<query>'")
            return
        _print_json(c.recall(q, project=getattr(args, "project", "")))
    elif sub == "episodes":
        _print_json({"episodes": c.episodic.list_episodes(
            project=getattr(args, "project", ""),
            status=getattr(args, "status", "active"),
            limit=getattr(args, "limit", 20))})
    elif sub == "graph":
        src = getattr(args, "src", "") or ""
        rel = getattr(args, "rel", "") or ""
        dst = getattr(args, "dst", "") or ""
        if not src and not rel and not dst:
            print("Usage: hermes living-cortex graph --src X [--rel R] [--dst Y] [--history]")
            return
        _print_json({"edges": c.retrieve_graph(
            src=src, rel=rel, dst=dst,
            include_history=getattr(args, "history", False))})
    elif sub == "why":
        _print_json(obs.why(getattr(args, "belief_id", "")))
    elif sub == "consolidate":
        _print_json(c.consolidate(getattr(args, "reason", "manual")))
    elif sub == "learned":
        _print_json({"procedures": obs.learned_procedures()})
    elif sub == "changed":
        _print_json({"changes": obs.recent_changes(getattr(args, "limit", 20))})
    elif sub == "forgotten":
        _print_json({"forgotten": obs.forgotten(getattr(args, "limit", 20))})
    elif sub == "export":
        _print_json(obs.export(getattr(args, "path", "living_cortex_export.json"),
                               getattr(args, "kind", "all")))
    else:
        print("Unknown living-cortex command. Available: status, recall, "
              "episodes, graph, why, consolidate, learned, changed, "
              "forgotten, export, selftest")


def _cmd_selftest(args) -> None:
    """Run the acceptance-test suite against a throwaway database."""
    import importlib.util
    import os
    import tempfile
    from pathlib import Path

    test_file = Path(__file__).resolve().parent / "tests" / "test_acceptance.py"
    spec = importlib.util.spec_from_file_location("lc_selftest", str(test_file))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    tmp = os.path.join(tempfile.gettempdir(), "lc_selftest.db")
    for f in (tmp, tmp + "-wal", tmp + "-shm"):
        if os.path.exists(f):
            try:
                os.remove(f)
            except OSError:
                pass
    results = mod.run_all(db_path=tmp, embed_enabled=False)
    passed = sum(1 for r in results if r.get("passed"))
    print(json.dumps({"passed": passed, "total": len(results),
                      "results": results}, indent=2, default=str))
    sys.exit(0 if passed == len(results) else 1)


def register_cli(subparser) -> None:
    """Build the ``hermes living-cortex`` argparse tree.

    The dynamic CLI harness calls this with the plugin parser. We set the
    default handler here (the harness cannot resolve a hyphenated name via
    getattr), so ``hermes living-cortex <cmd>`` always routes.
    """
    subparser.set_defaults(func=living_cortex_command)
    subs = subparser.add_subparsers(dest="living_cortex_command")

    subs.add_parser("status", help="Cortex health and table counts")
    subs.add_parser("selftest", help="Run acceptance tests on a throwaway DB")

    recall = subs.add_parser("recall", help="Hybrid recall for a query")
    recall.add_argument("query")
    recall.add_argument("--project", default="")

    episodes = subs.add_parser("episodes", help="List episodes")
    episodes.add_argument("--project", default="")
    episodes.add_argument("--status", default="active")
    episodes.add_argument("--limit", type=int, default=20)

    graph = subs.add_parser("graph", help="Query the knowledge graph")
    graph.add_argument("--src", default="")
    graph.add_argument("--rel", default="")
    graph.add_argument("--dst", default="")
    graph.add_argument("--history", action="store_true",
                       help="Include superseded/contradicted edges")

    why = subs.add_parser("why", help="Trace a belief to its evidence")
    why.add_argument("belief_id")

    cons = subs.add_parser("consolidate", help="Run the consolidation ('sleep') pass")
    cons.add_argument("--reason", default="manual")

    subs.add_parser("learned", help="Procedures learned from outcomes")

    changed = subs.add_parser("changed", help="Recent memory mutations")
    changed.add_argument("--limit", type=int, default=20)

    forgotten = subs.add_parser("forgotten", help="Recent forgetting actions")
    forgotten.add_argument("--limit", type=int, default=20)

    exp = subs.add_parser("export", help="Export memory as JSON")
    exp.add_argument("--path", default="living_cortex_export.json")
    exp.add_argument("--kind", default="all",
                     choices=["all", "episodes", "beliefs", "graph"])
