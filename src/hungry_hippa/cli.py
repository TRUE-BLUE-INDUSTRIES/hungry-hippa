"""``hungry-hippa`` CLI — operator observability, maintenance, and Hippo-Pot deployment.

A standalone command (``hungry-hippa status|recall|...``) that is also mountable
into a host's own CLI tree via :func:`register_cli`. ``migrate`` backs up and
upgrades an older database in place.

Commands: status | recall | episodes | graph | why | consolidate | learned |
changed | forgotten | export | quarantine | ingest | backup | selftest | migrate |
owner-token | fix-permissions | verify | init | start | stop | restart |
doctor | uninstall
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List, Optional

from .config import data_dir, load_config, resolve_db_path
from .controller import MemoryController
from . import policy as _policy
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


def hungry_hippa_command(args) -> None:
    sub = getattr(args, "hungry_hippa_command", None) or "status"
    if sub == "selftest":
        return _cmd_selftest(args)
    if sub == "init":
        return _cmd_init(args)
    if sub == "start":
        return _cmd_start(args)
    if sub == "stop":
        return _cmd_stop(args)
    if sub == "restart":
        return _cmd_restart(args)
    if sub == "doctor":
        return _cmd_doctor(args)
    if sub == "uninstall":
        return _cmd_uninstall(args)
    if sub == "migrate":
        return _cmd_migrate(args)
    if sub == "owner-token":
        return _cmd_owner_token(args)
    if sub == "fix-permissions":
        return _cmd_fix_permissions(args)
    if sub == "verify":
        return _cmd_verify(args)
    if sub == "quarantine":
        return _cmd_quarantine(args)
    if sub == "ingest":
        return _cmd_ingest(args)
    if sub == "backup":
        return _cmd_backup(args)
    c = _controller()
    obs = Observability(c.db, c.cfg, controller=c)
    if sub == "status":
        # Check if running as Hippo-Pot profile
        if c.cfg.get("hippo_pot", {}).get("profile") == "hippo-pot":
            from .hippo_pot import build_status
            _print_json(build_status(c.cfg, c.status()))
        else:
            _print_json(c.status())
    elif sub == "recall":
        q = getattr(args, "query", "")
        if not q:
            print("Usage: hungry-hippa recall '<query>' [--quarantined]")
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
            print("Usage: hungry-hippa graph --src X [--rel R] [--dst Y] [--history]")
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
        out_path = getattr(args, "path", "hungry_hippa_export.json")
        kind = getattr(args, "kind", "all")
        result = obs.export(out_path, kind)
        c.db.log_mutation("export", "database", "",
                          f"kind={kind} path={out_path} actor={c.actor_id}",
                          c.session_id)
        _print_json(result)
    else:
        print("Unknown hungry-hippa command. Available: status, recall, "
              "episodes, graph, why, consolidate, learned, changed, "
              "forgotten, export, selftest, migrate, owner-token, "
              "fix-permissions, verify")


def _cmd_selftest(args) -> None:
    """Run the acceptance-test suite against a throwaway database."""
    import importlib.util
    import os
    import tempfile
    from pathlib import Path

    # src layout: walk up to the checkout that holds tests/ (installed wheels do
    # not ship the suites, in which case selftest reports that plainly)
    here = Path(__file__).resolve().parent
    test_file = next(
        (c / "tests" / "test_acceptance.py"
         for c in (here, *here.parents) if (c / "tests" / "test_acceptance.py").is_file()),
        here / "tests" / "test_acceptance.py")
    # The suite is a loose file, not a module of this package, so it is loaded by
    # path. The suite then imports hungry_hippa normally — nothing here fakes a
    # package or injects one into sys.modules.
    spec = importlib.util.spec_from_file_location("hh_selftest", str(test_file))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    tmp = os.path.join(tempfile.gettempdir(), "hh_selftest.db")
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
    """Create (or show) the owner token an MCP *server instance* is launched with.

    The token authorizes the server process, not the caller: it is supplied in the
    environment of ``hungry-hippa-mcp`` when the host starts it. No MCP tool takes
    a token argument, and a model is never asked to handle it.
    """
    from . import trust

    token = trust.ensure_owner_token()
    path = trust.token_path()
    mode = trust.token_file_mode()
    report = {
        "token_file": str(path),
        "mode": oct(mode) if mode is not None else None,
        "created": True,
        "how_to_use": ("set HUNGRY_HIPPA_OWNER_TOKEN in the *launch environment* of "
                       "the hungry-hippa-mcp server process, e.g. "
                       '{"mcpServers": {"hungry-hippa": {"command": '
                       '"hungry-hippa-mcp", "env": {"HUNGRY_HIPPA_OWNER_TOKEN": '
                       '"<token>"}}}}. No MCP tool takes a token argument; an '
                       "instance launched without it is untrusted"),
    }
    if getattr(args, "print_token", False):
        report["token"] = token
    else:
        report["note"] = "add --print to display the token value"
    if mode is not None and (mode & 0o077):
        report["warning"] = (
            f"token file mode {oct(mode)} is readable by other local users; "
            "run `chmod 600 <file>`")
    report["storage_note"] = ("the memory database itself is plaintext SQLite; 0600 "
                              "permissions are not encryption — use OS or disk "
                              "encryption if the memories are sensitive")
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

    # One implementation of the promotion write: the same call quarantine
    # approval makes, so the two entry points cannot drift apart.
    changed = ctrl.semantic.set_verified_class(args.belief_id, source_class,
                                                source_actor=ctrl.actor_id)
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


def _cmd_backup(args) -> None:
    """Snapshot the database and rotate old snapshots.

    Written for an unattended host: it is one process that exits, it refuses to
    overwrite the live database, it names its own files so rotation can never
    delete something a human put in the directory, and ``--keep 0`` means "rotate
    nothing" rather than "delete everything".
    """
    from . import db as _db

    cfg = load_config()
    src = resolve_db_path(cfg)
    if not os.path.isfile(src):
        _print_json({"error": f"no database at {src}"})
        sys.exit(1)

    backup_cfg = cfg.get("backup") or {}
    directory = (getattr(args, "dir", "") or backup_cfg.get("dir")
                 or str(data_dir() / "backups"))
    keep_arg = getattr(args, "keep", None)
    keep = int(backup_cfg.get("keep", 7) if keep_arg is None else keep_arg)
    label = (getattr(args, "label", "") or "").strip()

    dest = os.path.join(directory, _db.backup_name(label))
    if os.path.abspath(dest) == os.path.abspath(src):
        _print_json({"error": "refusing to overwrite the live database"})
        sys.exit(1)
    # Two snapshots in the same second must not collide: bump a suffix instead of
    # silently replacing the previous one.
    bump = 1
    while os.path.exists(dest):
        dest = os.path.join(directory, _db.backup_name(label).replace(
            _db.BACKUP_SUFFIX, f"-{bump}{_db.BACKUP_SUFFIX}"))
        bump += 1

    _db.backup_sqlite(src, dest)
    removed = _db.prune_backups(directory, keep)

    audit = "recorded"
    try:
        _db.Database(src).log_mutation(
            "backup", "database", os.path.basename(dest),
            f"keep={keep} rotated={len(removed)}", "cli")
    except Exception as e:      # the snapshot exists; say so if the log did not
        audit = f"not recorded: {type(e).__name__}: {e}"

    _print_json({
        "backup": dest,
        "source": src,
        "bytes": os.path.getsize(dest),
        "keep": keep,
        "rotated": [os.path.basename(p) for p in removed],
        "retained": [os.path.basename(p) for p in _db.list_backups(directory)],
        "audit": audit,
        "note": ("plaintext snapshot of a plaintext database: the file inherits the "
                 "database's permissions, and encrypting the disk is the operator's call"
                 if keep > 0 else
                 "rotation disabled (keep=0): nothing was deleted"),
    })


def _cmd_ingest(args) -> None:
    """Parse a provider export; persist only with an explicit ``--apply``.

    Dry-run is the safe default: without ``--apply`` this never opens the
    memory database, so there is no path from a forgotten flag to a write.
    ``--apply`` writes canonical ingest rows via the persist library. It does
    not go through ``_controller()``, so it cannot mint ``user_explicit``
    provenance or extract episodes/beliefs.
    """
    action = getattr(args, "ingest_command", "") or ""
    if action == "chatgpt":
        return _cmd_ingest_chatgpt(args)
    if action == "hermes":
        return _cmd_ingest_hermes(args)
