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
    ``--apply`` on chatgpt/hermes writes canonical ingest rows via the persist
    library. ``ingest extract --apply`` reads those rows and writes quarantined
    hypotheses. ``ingest reconcile`` classifies those hypotheses against
    existing memories. None of these paths go through ``_controller()``, so
    they cannot mint ``user_explicit`` provenance.
    """
    action = getattr(args, "ingest_command", "") or ""
    if action == "chatgpt":
        return _cmd_ingest_chatgpt(args)
    if action in ("show", "verify"):
        from .db import Database
        from .ingest.store import fetch_conversation, verify_archive
        path = _ingest_db_path(args)
        if not os.path.isfile(path):
            _print_json({"error": "import database does not exist"})
            sys.exit(1)
        database = Database(path)
        if action == "verify":
            result = verify_archive(database, args.sha256)
        else:
            result = fetch_conversation(database, "chatgpt", args.session_id)
            if result:
                for turn in result["turns"]:
                    turn["archives"] = database.get_ingest_turn_sources(
                        "chatgpt", args.session_id, turn["turn_id"])
                result["note"] = "untrusted historical data; provider roles are not verified identity"
            else:
                result = {"ok": False, "error": "conversation not found"}
        _print_json(result)
        if result.get("ok") is False:
            sys.exit(1)
        return
    if action == "hermes":
        return _cmd_ingest_hermes(args)
    if action == "extract":
        return _cmd_ingest_extract(args)
    if action == "reconcile":
        return _cmd_ingest_reconcile(args)
    print("Usage: hungry-hippa ingest chatgpt <conversations.json> [--dry-run|--apply]")
    print("       hungry-hippa ingest hermes <dir> [--dry-run|--apply]")
    print("       hungry-hippa ingest extract [--dry-run|--apply]")
    print("       hungry-hippa ingest reconcile [--dry-run|--apply]")
    return None


def _print_ingest_counts(counts: Dict[str, int]) -> None:
    print(f"Conversations: {counts['conversations']:,}")
    print(f"Turns: {counts['turns']:,}")
    print(f"Current-path turns: {counts['current_path_turns']:,}")
    print(f"Alternate-branch turns: {counts['alternate_branch_turns']:,}")
    if counts["warnings"]:
        print(f"Warnings: {counts['warnings']:,} (malformed nodes; see the parser)")


def _ingest_db_path(args) -> str:
    path = getattr(args, "db", "") or os.environ.get("HUNGRY_HIPPA_DB", "")
    if not path:
        _print_json({"error": "choose an import database with --db PATH or HUNGRY_HIPPA_DB"})
        sys.exit(1)
    return os.path.abspath(os.path.expanduser(path))


def _cmd_ingest_chatgpt(args) -> None:
    """Parse a ChatGPT export; persist only when ``--apply`` is given."""
    given = getattr(args, "file", "") or ""
    if not given:
        _print_json({"error": "a path to conversations.json is required"})
        sys.exit(1)

    apply = bool(getattr(args, "apply", False))
    dry_run = bool(getattr(args, "dry_run", False))
    if apply and dry_run:
        _print_json({"error": "pass only one of --dry-run or --apply"})
        sys.exit(1)
    if not apply and not dry_run:
        _print_json({"error": ("refusing to write: pass --dry-run to parse and "
                               "report, or --apply to persist canonical turns. "
                               "Writes are not the default.")})
        sys.exit(1)

    from .ingest import resolve_export_path, summarize
    from .ingest.chatgpt import read_export_bytes, parse_chatgpt_bytes

    try:
        path = resolve_export_path(given)
    except FileNotFoundError:
        _print_json({"error": f"no such file: {given}"})
        sys.exit(1)
    except IsADirectoryError:
        _print_json({"error": f"not a file: {given}"})
        sys.exit(1)
    except (OSError, ValueError) as e:
        _print_json({"error": str(e)})
        sys.exit(1)

    try:
        raw = read_export_bytes(path)
        conversations = parse_chatgpt_bytes(raw)
    except json.JSONDecodeError as e:
        _print_json({"error": f"not valid JSON: {e}"})
        sys.exit(1)
    except (OSError, UnicodeDecodeError) as e:
        _print_json({"error": f"could not read export: {type(e).__name__}"})
        sys.exit(1)
    except ValueError as e:
        _print_json({"error": str(e)})
        sys.exit(1)

    counts = summarize(conversations)
    if dry_run:
        print("ChatGPT export parsed")
        _print_ingest_counts(counts)
        print("No database writes, no model calls, no network access (parsing only).")
        return

    from .db import Database
    from .ingest.store import persist_parsed_export

    db_path = _ingest_db_path(args)
    archive_dir = os.path.join(os.path.dirname(os.path.abspath(db_path)), "ingest_archives")
    result = persist_parsed_export(
        Database(db_path), conversations, source_path=path, source_bytes=raw,
        copy_to=archive_dir,
    )
    if not result.ok:
        _print_json({"error": result.error or "persist failed"})
        sys.exit(1)
    already = max(0, result.turns_seen - result.turns_inserted)
    print("ChatGPT export ingested")
    _print_ingest_counts(counts)
    print(f"Archive sha256: {result.sha256}")
    print(f"Database: {db_path}")
    print(f"Turns inserted: {result.turns_inserted:,}")
    print(f"Turns already present: {already:,}")
    print("No episodes, no beliefs, no model calls (canonical history only).")


def _cmd_ingest_hermes(args) -> None:
    """Parse Hermes session files; persist only when ``--apply`` is given."""
    given = getattr(args, "dir", "") or ""
    if not given:
        _print_json({"error": "a Hermes sessions directory (or .json/.jsonl file) is required"})
        sys.exit(1)

    apply = bool(getattr(args, "apply", False))
    dry_run = bool(getattr(args, "dry_run", False))
    if apply and dry_run:
        _print_json({"error": "pass only one of --dry-run or --apply"})
        sys.exit(1)
    if not apply and not dry_run:
        _print_json({"error": ("refusing to write: pass --dry-run to parse and "
                               "report, or --apply to persist canonical turns. "
                               "Writes are not the default.")})
        sys.exit(1)

    from .ingest import parse_hermes_export, resolve_hermes_path, summarize

    try:
        path = resolve_hermes_path(given)
    except FileNotFoundError:
        _print_json({"error": f"no such file or directory: {given}"})
        sys.exit(1)
    except IsADirectoryError:
        _print_json({"error": f"not a directory or session file: {given}"})
        sys.exit(1)
    except (OSError, ValueError) as e:
        _print_json({"error": str(e)})
        sys.exit(1)

    try:
        conversations = parse_hermes_export(path)
    except json.JSONDecodeError as e:
        _print_json({"error": f"not valid JSON: {e}"})
        sys.exit(1)
    except (OSError, UnicodeDecodeError) as e:
        _print_json({"error": f"could not read export: {type(e).__name__}"})
        sys.exit(1)

    counts = summarize(conversations)
    if dry_run:
        print("Hermes sessions parsed")
        _print_ingest_counts(counts)
        print("No database writes, no model calls, no network access (parsing only).")
        return

    from .config import load_config, resolve_db_path
    from .db import Database
    from .ingest.store import persist_parsed_export

    db_path = os.path.abspath(resolve_db_path(load_config()))
    archive_dir = os.path.join(os.path.dirname(db_path), "ingest_archives")
    groups: Dict[str, List[Any]] = {}
    for convo in conversations:
        src = (convo.source_metadata or {}).get("export_path")
        if not isinstance(src, str) or not src:
            src = path
        groups.setdefault(src, []).append(convo)

    if not groups:
        print("Hermes sessions ingested")
        _print_ingest_counts(counts)
        print("Archives: 0")
        print("Turns inserted: 0")
        print("Turns already present: 0")
        print("No episodes, no beliefs, no model calls (canonical history only).")
        return

    db = Database(db_path)
    inserted = 0
    seen = 0
    archives = 0
    last_sha = ""
    for src, convos in sorted(groups.items()):
        if os.path.isdir(src):
            _print_json({"error": "refusing to hash a directory as an archive; "
                         "session files are persisted individually"})
            sys.exit(1)
        result = persist_parsed_export(
            db, convos, source_path=src, copy_to=archive_dir,
        )
        if not result.ok:
            _print_json({"error": result.error or "persist failed",
                         "file": os.path.basename(src)})
            sys.exit(1)
        inserted += result.turns_inserted
        seen += result.turns_seen
        archives += 1
        last_sha = result.sha256

    already = max(0, seen - inserted)
    print("Hermes sessions ingested")
    _print_ingest_counts(counts)
    if archives == 1 and last_sha:
        print(f"Archive sha256: {last_sha}")
    else:
        print(f"Archives: {archives:,}")
    print(f"Turns inserted: {inserted:,}")
    print(f"Turns already present: {already:,}")
    print("No episodes, no beliefs, no model calls (canonical history only).")


def _cmd_ingest_extract(args) -> None:
    """Extract quarantined hypotheses from stored ingest turns."""
    apply = bool(getattr(args, "apply", False))
    dry_run = bool(getattr(args, "dry_run", False))
    if apply and dry_run:
        _print_json({"error": "pass only one of --dry-run or --apply"})
        sys.exit(1)
    if not apply and not dry_run:
        _print_json({"error": ("refusing to write: pass --dry-run to report pending "
                               "turns, or --apply to extract quarantined hypotheses. "
                               "Writes are not the default.")})
        sys.exit(1)

    from .ingest.extract import (
        ExtractRefused,
        ExtractorUnavailable,
        extract_from_store,
        extractor_from_config,
        require_extract_db_env,
    )

    try:
        db_path = require_extract_db_env()
    except ExtractRefused as e:
        _print_json({"error": str(e)})
        sys.exit(1)

    from .config import load_config
    from .db import Database

    cfg = load_config()
    db = Database(db_path)
    source_filter = str(getattr(args, "source", "") or "")
    limit = int(getattr(args, "limit", 0) or 0)
    if dry_run:
        result = extract_from_store(
            db, extractor=None, source_filter=source_filter, dry_run=True, cfg=cfg,
        )
        print("Ingest extract (dry-run)")
        print(f"Conversations pending: {result.conversations_pending:,}")
        print(f"Turns pending: {result.turns_pending:,}")
        print("No beliefs, no episodes, no model calls (pending-count only).")
        return

    try:
        extractor = extractor_from_config(cfg)
        result = extract_from_store(
            db, extractor=extractor, source_filter=source_filter, limit=limit,
            dry_run=False, cfg=cfg,
        )
    except ExtractorUnavailable as e:
        _print_json({"error": str(e)})
        sys.exit(1)
    except ExtractRefused as e:
        _print_json({"error": str(e)})
        sys.exit(1)
    print("Ingest extract applied")
    print(f"Job: {result.job_id or '-'}")
    print(f"Turns pending: {result.turns_pending:,}")
    print(f"Turns processed: {result.turns_processed:,}")
    print(f"Beliefs written: {result.beliefs_written:,}")
    print(f"Episodes written: {result.episodes_written:,}")
    print(f"Candidates skipped: {result.candidates_skipped:,}")
    print("Quarantined hypotheses only; no verified user_explicit; channel=import.")


def _cmd_ingest_reconcile(args) -> None:
    """Classify extract candidates against existing memories (Layer 4)."""
    apply = bool(getattr(args, "apply", False))
    dry_run = bool(getattr(args, "dry_run", False))
    if apply and dry_run:
        _print_json({"error": "pass only one of --dry-run or --apply"})
        sys.exit(1)
    if not apply and not dry_run:
        _print_json({"error": ("refusing to write: pass --dry-run to classify "
                               "pending candidates, or --apply to record decisions. "
                               "Writes are not the default.")})
        sys.exit(1)

    from .ingest.reconcile import (
        CLASSES,
        ExtractRefused,
        reconcile_store,
        require_extract_db_env,
    )

    try:
        db_path = require_extract_db_env()
    except ExtractRefused as e:
        _print_json({"error": str(e)})
        sys.exit(1)

    from .config import load_config
    from .db import Database

    cfg = load_config()
    db = Database(db_path)
    result = reconcile_store(db, dry_run=dry_run, cfg=cfg)
    title = "Ingest reconcile (dry-run)" if dry_run else "Ingest reconcile applied"
    print(title)
    if result.job_id:
        print(f"Job: {result.job_id}")
    print(f"Candidates pending: {result.candidates_pending:,}")
    print(f"Candidates processed: {result.candidates_processed:,}")
    for name in CLASSES:
        print(f"{name}: {result.counts.get(name, 0):,}")
    if dry_run:
        print("No decisions recorded, no Layer 1/2 deletes (classify only).")
    else:
        print("Contradictions left open (both claims + evidence kept).")
        print("No Layer 1/2 deletes; extract stays write-candidates.")


_QUARANTINE_SOURCE_CLASSES = ("user_explicit", "document", "tool_result")


def _shorten(text: Any, limit: int = 120) -> str:
    """One-line, length-capped rendering for list output."""
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[: max(0, limit - 1)] + "\u2026"


def _resolve_quarantined(ctrl, target_id: str):
    """Find one belief or episode by id. Returns ``(kind, row)`` or ``("", None)``."""
    b = ctrl.semantic.get_belief(target_id)
    if b:
        return "belief", b
    e = ctrl.episodic.get_episode(target_id)
    if e:
        return "episode", e
    return "", None


def _quarantine_is_operator_action(ctrl) -> bool:
    """Quarantine review is an operator action; a model channel may never do it.

    The CLI binds owner/user locally, so this is a guard rather than the only
    control: it exists so a host that mounts these commands cannot accidentally
    expose approval to an agent channel.
    """
    return bool(_policy.may_capability(_policy.CAP_APPROVE,
                                       provenance=ctrl.provenance,
                                       identity=ctrl.identity))


def _cmd_quarantine(args) -> None:
    """Operator review of memories an untrusted writer left in quarantine."""
    action = getattr(args, "quarantine_command", "") or ""
    if action == "list":
        return _cmd_quarantine_list(args)
    if action == "show":
        return _cmd_quarantine_show(args)
    if action == "approve":
        return _cmd_quarantine_approve(args)
    if action == "reject":
        return _cmd_quarantine_reject(args)
    print("Usage: hungry-hippa quarantine {list|show|approve|reject}")
    return None


def _cmd_quarantine_list(args) -> None:
    ctrl = _controller()
    limit = int(getattr(args, "limit", 50) or 50)
    kind = (getattr(args, "kind", "") or "").strip()
    rows: List[Dict[str, Any]] = []
    if kind in ("", "belief"):
        rows += [dict(r, kind="belief") for r in ctrl.semantic.list_quarantined(limit)]
    if kind in ("", "episode"):
        rows += [dict(r, kind="episode") for r in ctrl.episodic.list_quarantined(limit)]
    rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    items = [{
        "id": r.get("belief_id") or r.get("episode_id") or "",
        "kind": r.get("kind", ""),
        "actor": r.get("actor_id", ""),
        "claimed_source_class": r.get("claimed_source_class", ""),
        "verified_source_class": r.get("verified_source_class", ""),
        "content": _shorten(r.get("claim") or r.get("context")),
        "created_at": r.get("created_at", ""),
    } for r in rows[:limit]]
    _print_json({
        "quarantined": items,
        "count": len(items),
        "note": ("held from an untrusted writer; excluded from recall, belief "
                 "listing and consolidation until approved"),
    })


def _cmd_quarantine_show(args) -> None:
    ctrl = _controller()
    target_id = getattr(args, "target_id", "") or ""
    kind, row = _resolve_quarantined(ctrl, target_id)
    if not row:
        _print_json({"error": f"unknown memory {target_id}"})
        sys.exit(1)
    quarantined = bool(row.get("quarantined"))
    _print_json({
        "id": target_id,
        "kind": kind,
        "quarantined": quarantined,
        "content": row.get("claim") or row.get("context") or "",
        "actor": row.get("actor_id", ""),
        "source_actor": row.get("source_actor", ""),
        "claimed_source_class": row.get("claimed_source_class", ""),
        "verified_source_class": row.get("verified_source_class", ""),
        "ingestion_channel": row.get("ingestion_channel", ""),
        "kind_detail": row.get("kind", "") if kind == "belief" else row.get("outcome", ""),
        "confidence": row.get("confidence"),
        "importance": row.get("importance"),
        "sensitivity": row.get("sensitivity", ""),
        "status": row.get("status", ""),
        "evidence_ids": row.get("evidence_ids", []),
        "created_at": row.get("created_at", ""),
        "updated_at": row.get("updated_at", ""),
        "note": ("review only: approve to release it into normal recall, or reject "
                 "to archive it" if quarantined
                 else "this row is not quarantined; nothing to approve or reject"),
    })


def _cmd_quarantine_approve(args) -> None:
    ctrl = _controller()
    target_id = getattr(args, "target_id", "") or ""
    source_class = getattr(args, "source_class", "user_explicit") or "user_explicit"
    if not _quarantine_is_operator_action(ctrl):
        _print_json({"error": "quarantine approval is an operator action"})
        sys.exit(1)
    kind, row = _resolve_quarantined(ctrl, target_id)
    if not row:
        _print_json({"error": f"unknown memory {target_id}"})
        sys.exit(1)
    if source_class not in _QUARANTINE_SOURCE_CLASSES:
        _print_json({"error": "source_class must be one of "
                              + ", ".join(_QUARANTINE_SOURCE_CLASSES)})
        sys.exit(1)
    claimed_before = row.get("claimed_source_class", "")
    # The verification rule is not re-implemented here: the operator channel may
    # assert the origin of a memory, which is what trust.verified_source_class
    # already decides, and set_verified_class is the single promotion write.
    verified = _trust.verified_source_class(source_class, _trust.PROVENANCE_USER)
    if kind == "belief":
        changed = ctrl.semantic.set_verified_class(target_id, verified,
                                                   source_actor=ctrl.actor_id,
                                                   clear_quarantine=True)
    else:
        changed = ctrl.episodic.set_verified_class(target_id, verified,
                                                   source_actor=ctrl.actor_id,
                                                   clear_quarantine=True)
    ctrl.db.log_mutation("quarantine_approved", kind, target_id,
                         f"operator released from quarantine; "
                         f"verified_source_class={verified} "
                         f"(claimed was {claimed_before})", ctrl.session_id)
    _print_json({
        "approved": bool(changed),
        "id": target_id,
        "kind": kind,
        "claimed_source_class": claimed_before,
        "verified_source_class": verified,
        "rows_changed": changed,
        "note": "the row is no longer quarantined and is recall-visible again",
    })


def _cmd_quarantine_reject(args) -> None:
    ctrl = _controller()
    target_id = getattr(args, "target_id", "") or ""
    mode = (getattr(args, "mode", "archival") or "archival").strip().lower()
    kind, row = _resolve_quarantined(ctrl, target_id)
    if not row:
        _print_json({"error": f"unknown memory {target_id}"})
        sys.exit(1)
    if mode != "archival":
        # Deliberate: rejection archives. Purge exists only as an explicit,
        # separate operator action on a row the operator chose to destroy.
        _print_json({"error": "reject supports only --mode archival; "
                              "use `hungry-hippa forget` for a confirmed purge"})
        sys.exit(1)
    outcome = ctrl.forget(kind, target_id, mode="archival",
                          reason="quarantine rejected by operator")
    if outcome.get("error"):
        _print_json({"rejected": False, "id": target_id, **outcome})
        sys.exit(1)
    ctrl.db.log_mutation("quarantine_rejected", kind, target_id,
                         f"mode={mode}", ctrl.session_id)
    _print_json({
        "rejected": bool(outcome.get("archived")),
        "id": target_id,
        "kind": kind,
        "mode": mode,
        "note": ("archived, not purged: it leaves recall but stays in the database "
                 "and is audited as an archival"),
    })


def _cmd_init(args) -> None:
    """Initialize Hippo-Pot deployment profile."""
    from .hippo_pot import init_hippo_pot
    from .config import load_config

    profile = getattr(args, "profile", "") or "hippo-pot"
    if profile != "hippo-pot":
        print(f"Unknown profile: {profile}")
        sys.exit(1)

    cfg = load_config()
    result = init_hippo_pot(cfg)
    _print_json(result)
    print("\nHippo-Pot initialized.")
    print(f"Config: {result['config']}")
    print("Systemd units installed.")
    print("\nNext steps:")
    print("  1. Edit config.json to configure the manager (optional)")
    print("  2. Run: systemctl --user enable --now hippo-pot-manager.service")
    print("  3. Run: systemctl --user enable --now hippo-pot-consolidation.timer")
    print("  4. Run: hungry-hippa doctor")


def _cmd_start(args) -> None:
    """Start Hippo-Pot services."""
    from .hippo_pot import _run_systemctl
    units = ["hippo-pot-manager.service", "hippo-pot-consolidation.timer"]
    for unit in units:
        result = _run_systemctl("start", unit)
        if result.returncode != 0:
            print(f"Failed to start {unit}: {result.stderr.strip()}")
        else:
            print(f"Started {unit}")


def _cmd_stop(args) -> None:
    """Stop Hippo-Pot services."""
    from .hippo_pot import _run_systemctl
    units = ["hippo-pot-manager.service", "hippo-pot-consolidation.timer"]
    for unit in units:
        result = _run_systemctl("stop", unit)
        if result.returncode != 0:
            print(f"Failed to stop {unit}: {result.stderr.strip()}")
        else:
            print(f"Stopped {unit}")


def _cmd_restart(args) -> None:
    """Restart Hippo-Pot services."""
    _cmd_stop(args)
    _cmd_start(args)


def _cmd_doctor(args) -> None:
    """Run Hippo-Pot diagnostics."""
    from .hippo_pot import HippoPotDiagnostics
    from .config import load_config

    cfg = load_config()
    diagnostics = HippoPotDiagnostics(cfg)
    result = diagnostics.run_all()
    _print_json(result)

    if result["healthy"]:
        print("\nHippo-Pot is healthy.")
    else:
        print(f"\nHippo-Pot has {result['errors_count']} error(s), {result['warnings_count']} warning(s).")
        sys.exit(1)


def _cmd_uninstall(args) -> None:
    """Uninstall Hippo-Pot (preserves data by default)."""
    from .hippo_pot import uninstall_hippo_pot
    purge = getattr(args, "purge", False)
    confirm_purge = getattr(args, "confirm_purge", "")

    if purge:
        # Destructive purge requires explicit confirmation
        if confirm_purge != "PURGE-HUNGRY-HIPPA":
            print("ERROR: --purge requires --confirm-purge PURGE-HUNGRY-HIPPA")
            print("This will permanently delete all stored Hungry Hippa data.")
            print("To preserve data, run without --purge.")
            sys.exit(1)

    preserve = not purge
    result = uninstall_hippo_pot(preserve_data=preserve)
    _print_json(result)
    if preserve:
        print("\nHippo-Pot uninstalled. Data preserved.")
        print("Run with --purge --confirm-purge PURGE-HUNGRY-HIPPA to destroy all data.")
    else:
        print("\nHippo-Pot fully purged.")


def register_cli(subparser) -> None:
    """Build the ``hungry-hippa`` argparse tree.

    ``main()`` uses this for the console script; a host that mounts Hungry Hippa
    into its own CLI can call it with its own subparser.
    """
    subparser.set_defaults(func=hungry_hippa_command)
    subs = subparser.add_subparsers(dest="hungry_hippa_command")

    init_p = subs.add_parser("init", help="Initialize Hippo-Pot deployment profile")
    init_p.add_argument("--profile", default="hippo-pot", help="Deployment profile")
    subs.add_parser("start", help="Start Hippo-Pot services")
    subs.add_parser("stop", help="Stop Hippo-Pot services")
    subs.add_parser("restart", help="Restart Hippo-Pot services")
    subs.add_parser("doctor", help="Run Hippo-Pot diagnostics")
    uninstall_p = subs.add_parser("uninstall", help="Uninstall Hippo-Pot")
    uninstall_p.add_argument("--purge", action="store_true", help="Destroy all data")
    uninstall_p.add_argument("--confirm-purge", default="", metavar="PURGE-HUNGRY-HIPPA",
                              help="Confirmation phrase required with --purge")
    subs.add_parser("status", help="Hungry Hippa health and table counts")
    subs.add_parser("selftest", help="Run acceptance tests on a throwaway DB")
    otok = subs.add_parser(
        "owner-token",
        help=("Show or create the owner token: set it in the hungry-hippa-mcp "
              "server's launch environment (no tool takes it as an argument)"),
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

    q = subs.add_parser(
        "quarantine",
        help="Operator review of memories held from untrusted writers",
    )
    qsubs = q.add_subparsers(dest="quarantine_command")
    qlist = qsubs.add_parser("list", help="List quarantined memories")
    qlist.add_argument("--limit", type=int, default=50)
    qlist.add_argument("--kind", default="", choices=["", "belief", "episode"])
    qshow = qsubs.add_parser("show", help="Show one quarantined memory in full")
    qshow.add_argument("target_id")
    qappr = qsubs.add_parser(
        "approve",
        help="Release a quarantined memory into normal recall (operator only)",
    )
    qappr.add_argument("target_id")
    qappr.add_argument("--source-class", dest="source_class", default="user_explicit",
                       choices=list(_QUARANTINE_SOURCE_CLASSES),
                       help="the class the operator is asserting for this memory")
    qrej = qsubs.add_parser(
        "reject",
        help="Archive a quarantined memory (reversible; never purges)",
    )
    qrej.add_argument("target_id")
    qrej.add_argument("--mode", default="archival", choices=["archival"],
                      help="archival only: rejection never purges")

    bkp = subs.add_parser(
        "backup",
        help="Snapshot the database and rotate old snapshots (unattended-host safe)",
    )
    bkp.add_argument("--dir", default="",
                     help="Where snapshots go (default: $XDG_DATA_HOME/hungry-hippa/backups)")
    bkp.add_argument("--keep", type=int, default=None,
                     help="Snapshots to retain (default: config backup.keep, 7; 0 keeps all)")
    bkp.add_argument("--label", default="", help="Optional suffix, e.g. nightly")

    ing = subs.add_parser(
        "ingest",
        help="Parse a provider export; persist only with --apply",
    )
    ing_subs = ing.add_subparsers(dest="ingest_command")
    ing_chat = ing_subs.add_parser(
        "chatgpt",
        help="Parse a ChatGPT conversations.json export into normalized turns",
    )
    ing_chat.add_argument("file", help="path to conversations.json")
    ing_chat.add_argument("--db", default="", help="destination database (or HUNGRY_HIPPA_DB)")
    ing_mode = ing_chat.add_mutually_exclusive_group()
    ing_mode.add_argument(
        "--dry-run", dest="dry_run", action="store_true",
        help="parse and report; store nothing (the safe default unless --apply)",
    )
    ing_mode.add_argument(
        "--apply", dest="apply", action="store_true",
        help="preserve exact export bytes and canonical turns (idempotent)",
    )
    ing_hermes = ing_subs.add_parser(
        "hermes",
        help="Parse a Hermes sessions export directory into normalized turns",
    )
    ing_hermes.add_argument(
        "dir",
        help="Hermes sessions directory, or one .json/.jsonl session file",
    )
    hermes_mode = ing_hermes.add_mutually_exclusive_group()
    hermes_mode.add_argument(
        "--dry-run", dest="dry_run", action="store_true",
        help="parse and report; store nothing (the safe default unless --apply)",
    )
    hermes_mode.add_argument(
        "--apply", dest="apply", action="store_true",
        help="persist canonical turns and an archive pointer (idempotent)",
    )
    ing_extract = ing_subs.add_parser(
        "extract",
        help="Extract quarantined hypotheses from stored ingest turns",
    )
    extract_mode = ing_extract.add_mutually_exclusive_group()
    extract_mode.add_argument(
        "--dry-run", dest="dry_run", action="store_true",
        help="report pending turns; write no memories (the safe default unless --apply)",
    )
    extract_mode.add_argument(
        "--apply", dest="apply", action="store_true",
        help="call the local LM Studio chat model and write quarantined hypotheses",
    )
    ing_extract.add_argument(
        "--source", default="",
        help="only this ingest source (chatgpt, hermes, …); default: all",
    )
    ing_extract.add_argument(
        "--limit", type=int, default=0,
        help="max turns to process this run (0 = all pending)",
    )
    ing_reconcile = ing_subs.add_parser(
        "reconcile",
        help="Classify extract candidates against existing memories (Layer 4)",
    )
    reconcile_mode = ing_reconcile.add_mutually_exclusive_group()
    reconcile_mode.add_argument(
        "--dry-run", dest="dry_run", action="store_true",
        help="classify pending candidates; write no decisions (the safe default unless --apply)",
    )
    reconcile_mode.add_argument(
        "--apply", dest="apply", action="store_true",
        help="record classifications; contradictions stay open (both claims kept)",
    )

    ing_verify = ing_subs.add_parser("verify", help="verify source bytes and canonical provenance")
    ing_verify.add_argument("sha256", help="archive digest printed by import")
    ing_verify.add_argument("--db", default="", help="import database (or HUNGRY_HIPPA_DB)")
    ing_show = ing_subs.add_parser("show", help="inspect an untrusted ChatGPT conversation and sources")
    ing_show.add_argument("session_id", help="conversation id from the export")
    ing_show.add_argument("--db", default="", help="import database (or HUNGRY_HIPPA_DB)")

    exp = subs.add_parser("export", help="Export memory as JSON")
    exp.add_argument("--path", default="hungry_hippa_export.json")
    exp.add_argument("--kind", default="all",
                     choices=["all", "episodes", "beliefs", "graph"])


def main(argv: Optional[List[str]] = None) -> int:
    """Console-script entry point: ``hungry-hippa <command>``."""
    import argparse

    parser = argparse.ArgumentParser(prog="hungry-hippa",
                                     description=__doc__.splitlines()[0])
    register_cli(parser)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    handler = getattr(args, "func", hungry_hippa_command)
    handler(args)
    return 0


if __name__ == "__main__":          # `python -m hungry_hippa.cli ...`
    sys.exit(main())
