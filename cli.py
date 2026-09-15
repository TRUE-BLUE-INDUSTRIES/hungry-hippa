"""``hermes living-cortex`` CLI — observability + operations (§21).

Hungry Hippa (formerly Living Cortex). Command name stays ``living-cortex``
so existing Hermes configs keep working. ``migrate`` backs up and upgrades
an existing Living Cortex database in place.

Commands: status | recall | episodes | graph | why | consolidate | learned |
changed | forgotten | export | selftest | migrate
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict

from .config import load_config, resolve_db_path
from .controller import MemoryController
from . import trust as _trust
from .observability import Observability


def _controller() -> MemoryController:
    cfg = load_config()
    ctrl = MemoryController(cfg, db_path=resolve_db_path(cfg))
    # This is the human's own terminal: owner identity, user provenance. It is the
    # only channel allowed to mint user_explicit provenance without a token.
    ctrl.bind_session(session_id="cli", platform="cli", trust=_trust.local_binding())
    return ctrl


def _print_json(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def living_cortex_command(args) -> None:
    sub = getattr(args, "living_cortex_command", None) or "status"
    if sub == "selftest":
        return _cmd_selftest(args)
    if sub == "migrate":
        return _cmd_migrate(args)
    if sub == "owner-token":
        return _cmd_owner_token(args)
    if sub == "fix-permissions":
        return _cmd_fix_permissions(args)
    if sub == "verify":
        return _cmd_verify(args)
    c = _controller()
    obs = Observability(c.db, c.cfg, controller=c)
    if sub == "status":
        _print_json(c.status())
    elif sub == "recall":
        q = getattr(args, "query", "")
        if not q:
            print("Usage: hermes living-cortex recall '<query>' [--quarantined]")
            return
        _print_json(c.recall(q, project=getattr(args, "project", ""),
                             include_quarantined=bool(
                                 getattr(args, "quarantined", False))))
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
        # Same rule as the cortex tool's export action: operator-only, and audited
        # whether it succeeds or is refused. This is a full SELECT * dump to a
        # caller-chosen path, so it must leave a trace in mutation_log.
        from . import policy as _policy
        if not _policy.is_owner(c.actor_id):
            c.db.log_mutation("export_denied", "database", "",
                              f"actor={c.actor_id} reason=owner-only", c.session_id)
            _print_json({"error": "export is operator-only; unavailable to this actor",
                         "actor_id": c.actor_id})
            return
        out_path = getattr(args, "path", "living_cortex_export.json")
        kind = getattr(args, "kind", "all")
        result = obs.export(out_path, kind)
        c.db.log_mutation("export", "database", "",
                          f"kind={kind} path={out_path} actor={c.actor_id}",
                          c.session_id)
        _print_json(result)
    else:
        print("Unknown living-cortex command. Available: status, recall, "
              "episodes, graph, why, consolidate, learned, changed, "
              "forgotten, export, selftest, migrate, owner-token, "
              "fix-permissions, verify")


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


def _cmd_migrate(args) -> None:
    """Backup the resolved DB and apply pending Hungry Hippa migrations."""
    from .db import migrate_database

    path = getattr(args, "db", "") or resolve_db_path(load_config())
    report = migrate_database(path)
    _print_json(report)
    if report.get("error"):
        sys.exit(1)


def _cmd_owner_token(args) -> None:
    """Create (or show) the owner token that lets an MCP client act as owner."""
    from . import trust

    token = trust.ensure_owner_token()
    path = trust.token_path()
    mode = trust.token_file_mode()
    report = {
        "token_file": str(path),
        "mode": oct(mode) if mode is not None else None,
        "created": True,
        "how_to_use": ("pass the token as the owner_token argument to an MCP tool "
                       "call; without it an MCP caller is untrusted"),
    }
    if getattr(args, "print_token", False):
        report["token"] = token
    else:
        report["note"] = "add --print to display the token value"
    if mode is not None and (mode & 0o077):
        report["warning"] = (
            f"token file mode {oct(mode)} is readable by other local users; "
            "run `chmod 600 <file>`")
    _print_json(report)


def _cmd_fix_permissions(args) -> None:
    """Set 0600 on the database, its sidecars and its backups.

    An explicit operator action: the runtime reports lax permissions but never
    changes an existing file behind the operator's back. This is a permission,
    not encryption — the file stays plaintext.
    """
    import stat

    path = getattr(args, "db", "") or resolve_db_path(load_config())
    targets = [path, path + "-wal", path + "-shm"]
    parent = os.path.dirname(os.path.abspath(path))
    if os.path.isdir(parent):
        base = os.path.basename(path)
        targets += [os.path.join(parent, n) for n in sorted(os.listdir(parent))
                    if n.startswith(base) and n.endswith(".bak")]
    changed, already, missing, failed = [], [], [], []
    for target in targets:
        try:
            mode = stat.S_IMODE(os.stat(target).st_mode)
        except OSError:
            missing.append(target)
            continue
        if not (mode & 0o077):
            already.append(f"{target} ({oct(mode)})")
            continue
        try:
            os.chmod(target, mode & ~0o077)
            changed.append(f"{target} {oct(mode)} -> {oct(mode & ~0o077)}")
        except OSError as e:
            failed.append(f"{target}: {e}")
    _print_json({
        "database": path,
        "tightened": changed,
        "already_restrictive": already,
        "absent": missing,
        "failed": failed,
        "note": ("permissions are not encryption; the files remain plaintext. "
                 "Backups are only tightened here when you ask."),
    })
    if failed:
        sys.exit(1)


def _cmd_verify(args) -> None:
    """Operator confirmation: promote a belief's verified provenance.

    This is the trusted boundary for provenance. The model cannot promote its own
    text to ``user_explicit``; the operator, at their own terminal, can state that
    a memory is indeed something they said.
    """
    from . import db as _db
    from . import trust as _trust

    ctrl = _controller()
    b = ctrl.semantic.get_belief(args.belief_id)
    if not b:
        _print_json({"error": f"unknown belief {args.belief_id}"})
        sys.exit(1)
    source_class = args.source_class
    if source_class not in ("user_explicit", "document", "tool_result"):
        _print_json({"error": "source_class must be one of user_explicit, document, "
                              "tool_result"})
        sys.exit(1)

    def _upd(conn) -> int:
        cur = conn.execute(
            "UPDATE beliefs SET source_class = ?, verified_source_class = ?,"
            " source_actor = ?, ingestion_channel = 'operator_cli', updated_at = ?"
            " WHERE belief_id = ?",
            (source_class, source_class, _trust.CHANNEL_CLI, _db.now_iso(),
             args.belief_id))
        return cur.rowcount

    changed = ctrl.db._run(_upd, write=True)
    ctrl.db.log_mutation("verify_provenance", "belief", args.belief_id,
                         f"operator set verified_source_class={source_class} "
                         f"(claimed was {b.get('claimed_source_class', '')})",
                         ctrl.session_id)
    _print_json({
        "belief_id": args.belief_id,
        "claimed_source_class": b.get("claimed_source_class", ""),
        "verified_source_class": source_class,
        "rows_changed": changed,
        "note": "verified provenance is what the trust weighting uses",
    })


def register_cli(subparser) -> None:
    """Build the ``hermes living-cortex`` argparse tree.

    The dynamic CLI harness calls this with the plugin parser. We set the
    default handler here (the harness cannot resolve a hyphenated name via
    getattr), so ``hermes living-cortex <cmd>`` always routes.
    """
    subparser.set_defaults(func=living_cortex_command)
    subs = subparser.add_subparsers(dest="living_cortex_command")

    subs.add_parser("status", help="Hungry Hippa health and table counts")
    subs.add_parser("selftest", help="Run acceptance tests on a throwaway DB")
    otok = subs.add_parser(
        "owner-token",
        help="Show or create the owner token that lets an MCP client act as owner",
    )
    otok.add_argument("--print", dest="print_token", action="store_true",
                      help="Also print the token value (it is a secret: shell history!)")
    fix = subs.add_parser(
        "fix-permissions",
        help="Set 0600 on the database, its WAL/SHM sidecars and its backups",
    )
    fix.add_argument("--db", default="", help="Database path (default: resolved config path)")
    ver = subs.add_parser(
        "verify",
        help="Operator confirmation: set a belief's verified provenance (trust boundary)",
    )
    ver.add_argument("belief_id")
    ver.add_argument("--source-class", dest="source_class", default="user_explicit",
                     help="user_explicit (default), document, or tool_result")
    mig = subs.add_parser(
        "migrate",
        help="Backup an existing Living Cortex DB and apply Hungry Hippa migrations",
    )
    mig.add_argument(
        "--db",
        default="",
        help="Database path (default: resolved config path; never guess a production path silently)",
    )

    recall = subs.add_parser("recall", help="Hybrid recall for a query")
    recall.add_argument("query")
    recall.add_argument("--project", default="")
    recall.add_argument("--quarantined", action="store_true",
                        help="Owner review: include quarantined memories, clearly labelled")

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
