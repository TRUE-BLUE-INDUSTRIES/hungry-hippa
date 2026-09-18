#!/usr/bin/env python3
"""HH-08: ChatGPT export → persist → (optional extract) → recall with evidence.

Synthetic fixture only. Never the operator's real conversations.json.
Throwaway HUNGRY_HIPPA_DB only; live Hermes/Grok stores are refused.

    python eval/ingest_e2e.py              # ingest + live extract if LM Studio is up
    python eval/ingest_e2e.py --offline    # ingest + owner-stored memory (CI path)
    python eval/ingest_e2e.py --json       # machine-readable report on stdout

Extracted hypotheses stay quarantined (HH-06). Owner CLI recall uses
``--quarantined`` so the demo can see them; default recall must not. That is
not a production-quarantine bypass.

When LM Studio chat is down, extract is skipped and a directly stored owner
memory (evidence pointing at the planted ingest turn) proves recall/why.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

EVAL_DIR = Path(__file__).resolve().parent
REPO_DIR = EVAL_DIR.parent
SRC_DIR = REPO_DIR / "src"
FIXTURE = EVAL_DIR / "fixtures" / "chatgpt_e2e_conversations.json"

# Prefer this checkout over a different editable install (other worktrees).
sys.path.insert(0, str(SRC_DIR))

PLANTED_TORQUE = "52Nm"
PLANTED_WHEN = "12 March 2026"
PLANTED_OS = "Arch Linux (Omarchy)"
PLANTED_SESSION = "e2e-mill-setup-2026"
PLANTED_TURN = "e2e-turn-torque-52nm"
QUERY = "what is the fixture-jig torque after the March 2026 change?"
EXPECT_TOKENS = ("52Nm", "52 nm", "52 Nm")
DIRECT_CLAIM = (
    "On 12 March 2026 the fixture-jig torque was set to 52Nm "
    "(the previous 45Nm setting warped the housing)."
)

LIVE_HERMES = os.path.abspath(os.path.expanduser("~/.hermes/living_cortex.db"))
LIVE_GROK = os.path.abspath(os.path.expanduser(
    "~/.grok/hungry-hippa-demo/hungry_hippa.db"))


def _forbidden_db_paths() -> Tuple[str, ...]:
    from hungry_hippa.ingest.extract import forbidden_db_paths

    extra = (LIVE_HERMES, LIVE_GROK)
    return tuple(dict.fromkeys(forbidden_db_paths() + extra))


def assert_throwaway_db(path: str) -> str:
    resolved = os.path.abspath(os.path.expanduser(path or ""))
    if not resolved:
        raise SystemExit("refusing: empty HUNGRY_HIPPA_DB")
    for live in _forbidden_db_paths():
        if resolved == live:
            raise SystemExit(
                "refusing to run e2e against a live operator store; "
                "set HUNGRY_HIPPA_DB to a throwaway path under /tmp"
            )
    if not resolved.startswith("/tmp/") and "/hh_e2e" not in resolved:
        # Allow pytest/tempfile dirs (often /tmp) and explicit operator temps.
        # Anything that looks like a home store is refused.
        home = os.path.abspath(os.path.expanduser("~"))
        if resolved.startswith(home + os.sep):
            raise SystemExit(
                f"refusing e2e database under $HOME: {resolved}. "
                "Use HUNGRY_HIPPA_DB=/tmp/..."
            )
    return resolved


def _cli_env(db_path: str) -> Dict[str, str]:
    env = dict(os.environ)
    env["HUNGRY_HIPPA_DB"] = db_path
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(SRC_DIR) + ((":" + existing) if existing else "")
    work = os.path.dirname(os.path.abspath(db_path))
    env["XDG_DATA_HOME"] = work
    env["XDG_STATE_HOME"] = work
    env["XDG_CONFIG_HOME"] = work
    return env


def _run_cli(argv: Sequence[str], *, env: Dict[str, str],
             timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "hungry_hippa.cli", *argv],
        env=env, cwd=str(REPO_DIR), capture_output=True, text=True, timeout=timeout,
    )


def _contains_planted(text: str) -> bool:
    blob = (text or "").lower().replace(" ", "")
    return "52nm" in blob


def _item_text(item: Dict[str, Any]) -> str:
    parts = [
        str(item.get("claim") or ""),
        str(item.get("context") or ""),
        str(item.get("result") or ""),
        str(item.get("user_request") or ""),
    ]
    return " ".join(parts)


def _fresh_db() -> str:
    work = tempfile.mkdtemp(prefix="hh_e2e_")
    return os.path.join(work, "hungry_hippa.db")


class Run:
    def __init__(self, echo: bool = True) -> None:
        self.echo = echo
        self.lines: List[str] = []

    def emit(self, text: str = "") -> None:
        if self.echo:
            print(text)
        self.lines.append(text)


def _sqlite(db_path: str, sql: str, params: Sequence[Any] = ()) -> List[sqlite3.Row]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return list(conn.execute(sql, params))
    finally:
        conn.close()


def _lms_available(env: Dict[str, str]) -> Tuple[bool, str]:
    from hungry_hippa.config import load_config
    from hungry_hippa.ingest.extract import ExtractorUnavailable, extractor_from_config

    os.environ["HUNGRY_HIPPA_DB"] = env["HUNGRY_HIPPA_DB"]
    try:
        extractor_from_config(load_config()).health()
    except ExtractorUnavailable as e:
        return False, str(e)
    except Exception as e:  # health must never crash the offline path
        return False, f"{type(e).__name__}: {e}"
    return True, "ok"


def _store_direct_owner_memory(db_path: str) -> Dict[str, Any]:
    """CI fallback: owner-stored fact with evidence pointing at the ingest turn."""
    from hungry_hippa.config import load_config
    from hungry_hippa.controller import MemoryController
    from hungry_hippa.db import Database
    from hungry_hippa import trust

    rows = _sqlite(
        db_path,
        "SELECT source, session_id, turn_id, content FROM ingest_turns "
        "WHERE session_id = ? AND turn_id = ?",
        (PLANTED_SESSION, PLANTED_TURN),
    )
    if not rows:
        raise RuntimeError("planted ingest turn missing; cannot store direct memory")
    turn = dict(rows[0])
    ref = json.dumps(
        {"kind": "ingest_turn", "source": turn["source"],
         "session_id": turn["session_id"], "turn_id": turn["turn_id"]},
        ensure_ascii=False, separators=(",", ":"),
    )
    db = Database(db_path)
    eid = db.add_evidence(turn["content"] or DIRECT_CLAIM, "document", ref, "e2e")
    cfg = load_config()
    cfg["retrieval"]["vectors_enabled"] = False
    ctrl = MemoryController(cfg, db_path=db_path)
    ctrl.bind_session(session_id="cli", platform="cli", trust=trust.local_binding())
    written = ctrl.semantic.add_belief(
        DIRECT_CLAIM, kind="fact", confidence=0.95, source_class="user_explicit",
        evidence_ids=[eid] if eid else None, quarantined=False,
        actor_id="primary", identity=trust.OWNER,
        provenance=trust.PROVENANCE_USER, channel=trust.CHANNEL_CLI,
        session_id="e2e-direct",
    )
    if written.get("error"):
        raise RuntimeError(f"direct store failed: {written['error']}")
    return {
        "belief_id": written.get("belief_id", ""),
        "evidence_id": eid,
        "quarantined": bool(written.get("quarantined")),
        "verified_source_class": written.get("verified_source_class"),
    }


def _mcp_tool_names(env: Dict[str, str]) -> List[str]:
    out = subprocess.run(
        [sys.executable, str(SRC_DIR / "hungry_hippa" / "mcp_server.py"),
         "--print-schemas"],
        env=env, cwd="/tmp", capture_output=True, text=True, timeout=180,
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr[-300:] or out.stdout[-300:])
    tools = sorted(t["name"] for t in json.loads(out.stdout)["tools"])
    return tools


def _parse_json_stdout(raw: str) -> Dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        return {}
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else {}
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return {}
        try:
            obj = json.loads(text[start:end + 1])
            return obj if isinstance(obj, dict) else {}
        except json.JSONDecodeError:
            return {}


def _recall_hit(payload: Dict[str, Any]) -> Dict[str, Any]:
    items = payload.get("items") or []
    context = str(payload.get("context") or "")
    hit_item: Optional[Dict[str, Any]] = None
    for it in items:
        if not isinstance(it, dict):
            continue
        if _contains_planted(_item_text(it)) or _contains_planted(str(it)):
            hit_item = it
            break
    evidence_ids: List[str] = []
    if hit_item:
        raw_ev = hit_item.get("evidence_ids") or []
        if isinstance(raw_ev, str):
            try:
                raw_ev = json.loads(raw_ev)
            except json.JSONDecodeError:
                raw_ev = [raw_ev]
        evidence_ids = [str(x) for x in raw_ev if x]
    sources = [str(s) for s in (payload.get("sources") or [])]
    for s in sources:
        if s.startswith("ev_") or "ingest_turn" in s:
            if s not in evidence_ids:
                evidence_ids.append(s)
    supported = bool(evidence_ids) or any("ingest_turn" in str(s) for s in sources)
    return {
        "matched": bool(hit_item) or _contains_planted(context),
        "in_context": _contains_planted(context),
        "belief_id": (hit_item or {}).get("belief_id") or "",
        "episode_id": (hit_item or {}).get("episode_id") or "",
        "quarantined": bool((hit_item or {}).get("quarantined")),
        "evidence_ids": evidence_ids,
        "sources": sources,
        "supported_by_evidence": supported and (
            bool(hit_item) or _contains_planted(context)
        ),
        "count": int(payload.get("count") or 0),
    }


def run_e2e(
    *,
    db_path: str = "",
    fixture: str = "",
    offline: bool = False,
    require_live: bool = False,
    echo: bool = True,
) -> Dict[str, Any]:
    log = Run(echo=echo)
    fixture_path = os.path.abspath(fixture or str(FIXTURE))
    if not os.path.isfile(fixture_path):
        raise SystemExit(f"missing synthetic fixture: {fixture_path}")

    report: Dict[str, Any] = {
        "ok": False,
        "mode": "offline-direct-store" if offline else "auto",
        "db_path": "",
        "fixture": fixture_path,
        "planted": {
            "torque": PLANTED_TORQUE,
            "when": PLANTED_WHEN,
            "os": PLANTED_OS,
            "session_id": PLANTED_SESSION,
            "turn_id": PLANTED_TURN,
            "query": QUERY,
        },
        "ingest": {},
        "extract": {"attempted": False, "skipped": True, "skip_reason": ""},
        "reconcile": {"attempted": False},
        "recall": {},
        "why": {},
        "mcp_tools": [],
        "limitations": [],
    }

    db_path = assert_throwaway_db(db_path or os.environ.get("HUNGRY_HIPPA_DB") or _fresh_db())
    report["db_path"] = db_path
    env = _cli_env(db_path)
    os.environ["HUNGRY_HIPPA_DB"] = db_path

    log.emit(f"HH-08 ingest e2e  db={db_path}")
    log.emit(f"fixture (synthetic): {fixture_path}")
    log.emit("")

    # --- ingest chatgpt --dry-run then --apply ---
    dry = _run_cli(["ingest", "chatgpt", fixture_path, "--dry-run"], env=env)
    log.emit("$ hungry-hippa ingest chatgpt <synthetic> --dry-run")
    log.emit((dry.stdout or "").rstrip())
    if dry.returncode != 0:
        report["ingest"] = {"ok": False, "error": dry.stdout or dry.stderr}
        report["limitations"].append("ingest dry-run failed")
        return report

    applied = _run_cli(["ingest", "chatgpt", fixture_path, "--apply"], env=env)
    log.emit("$ hungry-hippa ingest chatgpt <synthetic> --apply")
    log.emit((applied.stdout or "").rstrip())
    if applied.returncode != 0:
        report["ingest"] = {"ok": False, "error": applied.stdout or applied.stderr}
        report["limitations"].append("ingest --apply failed")
        return report

    archives = _sqlite(db_path, "SELECT sha256, original_path, archived_path, byte_length "
                       "FROM ingest_archives")
    convos = _sqlite(db_path, "SELECT source, session_id, title FROM ingest_conversations")
    turns = _sqlite(db_path, "SELECT source, session_id, turn_id, content, on_current_path "
                    "FROM ingest_turns")
    planted_rows = [dict(r) for r in turns
                    if r["session_id"] == PLANTED_SESSION and r["turn_id"] == PLANTED_TURN]
    alt = sum(1 for r in turns if not r["on_current_path"])
    archive = dict(archives[0]) if archives else {}
    copy_path = archive.get("archived_path") or ""
    ingest_info = {
        "ok": True,
        "conversations": len(convos),
        "turns": len(turns),
        "alternate_branch_turns": alt,
        "turns_inserted_line": next(
            (ln for ln in (applied.stdout or "").splitlines() if ln.startswith("Turns inserted:")),
            "",
        ),
        "archive_sha256": archive.get("sha256", ""),
        "archive_bytes": archive.get("byte_length", 0),
        "archived_copy_exists": bool(copy_path) and os.path.isfile(copy_path),
        "planted_turn_present": bool(planted_rows) and _contains_planted(
            planted_rows[0]["content"] if planted_rows else ""
        ),
        "raw_pointer_original_path": archive.get("original_path", ""),
    }
    report["ingest"] = ingest_info
    if not ingest_info["planted_turn_present"] or not ingest_info["archive_sha256"]:
        report["limitations"].append("raw/normalized persist incomplete")
        return report
    log.emit(f"Layer 1 archive sha256={ingest_info['archive_sha256'][:12]}… "
             f"copy={ingest_info['archived_copy_exists']}")
    log.emit(f"Layer 2 turns={ingest_info['turns']} "
             f"alt_branch={ingest_info['alternate_branch_turns']} "
             f"planted_turn={ingest_info['planted_turn_present']}")
    log.emit("")

    # --- extract (optional live LM Studio) ---
    extract_info: Dict[str, Any] = {
        "attempted": False, "skipped": True, "skip_reason": "",
        "beliefs_written": 0, "episodes_written": 0, "turns_processed": 0,
        "planted_in_candidates": False,
    }
    live_ok, live_detail = (False, "offline flag") if offline else _lms_available(env)
    if require_live and not live_ok:
        report["extract"] = {**extract_info, "skip_reason": live_detail}
        report["limitations"].append(f"require-live but LM Studio unavailable: {live_detail}")
        return report

    used_extract = False
    if live_ok:
        extract_info["attempted"] = True
        extract_info["skipped"] = False
        log.emit("$ hungry-hippa ingest extract --apply")
        ext = _run_cli(["ingest", "extract", "--apply"], env=env, timeout=360)
        log.emit((ext.stdout or "").rstrip())
        if ext.returncode != 0:
            extract_info["skipped"] = True
            extract_info["skip_reason"] = (ext.stdout or ext.stderr or "extract failed")[:400]
            if require_live:
                report["extract"] = extract_info
                report["limitations"].append("live extract --apply failed")
                return report
            log.emit(f"extract failed; falling back to direct owner store ({extract_info['skip_reason'][:120]})")
        else:
            used_extract = True
            for line in (ext.stdout or "").splitlines():
                if line.startswith("Beliefs written:"):
                    extract_info["beliefs_written"] = int(line.split(":")[1].replace(",", "").strip())
                elif line.startswith("Episodes written:"):
                    extract_info["episodes_written"] = int(line.split(":")[1].replace(",", "").strip())
                elif line.startswith("Turns processed:"):
                    extract_info["turns_processed"] = int(line.split(":")[1].replace(",", "").strip())
            claims = [r[0] for r in _sqlite(db_path, "SELECT claim FROM beliefs")]
            extract_info["planted_in_candidates"] = any(_contains_planted(c) for c in claims)
            extract_info["candidate_count"] = len(claims)
    else:
        extract_info["skip_reason"] = live_detail
        log.emit(f"extract skipped ({live_detail})")
    report["extract"] = extract_info
    log.emit("")

    # --- reconcile ---
    rec_info: Dict[str, Any] = {"attempted": True, "ok": False}
    log.emit("$ hungry-hippa ingest reconcile --apply")
    rec = _run_cli(["ingest", "reconcile", "--apply"], env=env, timeout=120)
    log.emit((rec.stdout or "").rstrip())
    rec_info["ok"] = rec.returncode == 0
    rec_info["stdout_tail"] = "\n".join((rec.stdout or "").splitlines()[-12:])
    report["reconcile"] = rec_info
    log.emit("")

    # --- fallback owner memory if extract did not run ---
    direct = None
    if not used_extract:
        log.emit("storing owner memory from planted ingest turn (extract skipped)")
        direct = _store_direct_owner_memory(db_path)
        log.emit(f"direct belief_id={direct['belief_id']} evidence={direct['evidence_id']}")
        report["mode"] = "offline-direct-store"
        report["direct_store"] = direct
        report["limitations"].append(
            "live extract skipped; recall is of a directly stored owner memory "
            "whose evidence points at the planted ingest turn"
        )
    else:
        report["mode"] = "live-extract-quarantined"
        report["limitations"].append(
            "extracted hypotheses are quarantined; owner CLI used --quarantined "
            "(include_quarantined). Default recall must hide them. Production "
            "quarantine is unchanged."
        )
    log.emit("")

    # --- recall ---
    include_q = bool(used_extract)
    recall_argv = ["recall", QUERY]
    if include_q:
        recall_argv.append("--quarantined")
    log.emit("$ hungry-hippa " + " ".join(recall_argv))
    t0 = time.perf_counter()
    rec_run = _run_cli(recall_argv, env=env, timeout=60)
    latency_ms = (time.perf_counter() - t0) * 1000.0
    rec_payload = _parse_json_stdout(rec_run.stdout)
    hit = _recall_hit(rec_payload)
    hit["latency_ms"] = round(latency_ms, 3)
    hit["include_quarantined"] = include_q
    hit["cli_ok"] = rec_run.returncode == 0
    hit["query"] = QUERY
    hit["context_chars"] = len(str(rec_payload.get("context") or ""))
    if not hit["matched"]:
        retry_q = "52Nm fixture-jig torque March 2026"
        retry_argv = ["recall", retry_q] + (["--quarantined"] if include_q else [])
        log.emit("$ hungry-hippa " + " ".join(retry_argv) + "  # retry")
        t1 = time.perf_counter()
        retry_run = _run_cli(retry_argv, env=env, timeout=60)
        retry_ms = (time.perf_counter() - t1) * 1000.0
        retry_payload = _parse_json_stdout(retry_run.stdout)
        retry_hit = _recall_hit(retry_payload)
        if retry_hit["matched"]:
            retry_hit["latency_ms"] = round(latency_ms + retry_ms, 3)
            retry_hit["include_quarantined"] = include_q
            retry_hit["cli_ok"] = retry_run.returncode == 0
            retry_hit["query"] = retry_q
            retry_hit["retried"] = True
            retry_hit["context_chars"] = len(str(retry_payload.get("context") or ""))
            hit = retry_hit
    report["recall"] = hit
    log.emit(f"recall latency_ms={hit['latency_ms']} matched={hit['matched']} "
             f"evidence={hit['evidence_ids'] or hit['sources']}")
    log.emit("")

    default_hides = None
    if used_extract:
        log.emit("$ hungry-hippa recall '<query>'   # default, no --quarantined")
        bare = _run_cli(["recall", QUERY], env=env, timeout=60)
        bare_payload = _parse_json_stdout(bare.stdout)
        bare_hit = _recall_hit(bare_payload)
        default_hides = not bare_hit["matched"]
        report["recall"]["default_recall_hides_quarantine"] = default_hides
        log.emit(f"default recall matched_planted={bare_hit['matched']} "
                 f"(expect false while quarantined)")
        log.emit("")

    # --- why ---
    why_id = hit.get("belief_id") or (direct or {}).get("belief_id") or ""
    if not why_id and used_extract:
        rows = _sqlite(
            db_path,
            "SELECT belief_id, claim FROM beliefs WHERE quarantined = 1 ORDER BY created_at",
        )
        for row in rows:
            if _contains_planted(row["claim"]):
                why_id = row["belief_id"]
                break
        if not why_id and rows:
            why_id = rows[0]["belief_id"]
    why_info: Dict[str, Any] = {"belief_id": why_id}
    if why_id:
        log.emit(f"$ hungry-hippa why {why_id}")
        why_run = _run_cli(["why", why_id], env=env, timeout=60)
        why_payload = _parse_json_stdout(why_run.stdout)
        evidence = why_payload.get("evidence") or []
        why_info = {
            "belief_id": why_id,
            "cli_ok": why_run.returncode == 0,
            "claim_has_planted": _contains_planted(str(why_payload.get("claim") or "")),
            "evidence_count": len(evidence),
            "evidence_ids": [e.get("evidence_id") for e in evidence if isinstance(e, dict)],
            "evidence_has_planted_text": any(
                _contains_planted(str(e.get("content") or ""))
                for e in evidence if isinstance(e, dict)
            ),
            "ingestion_channel": why_payload.get("ingestion_channel"),
            "verified_source_class": why_payload.get("verified_source_class"),
            "quarantine_note": (
                "owner why on a quarantined import hypothesis"
                if used_extract else "owner why on a directly stored fact"
            ),
        }
        log.emit(f"why evidence_count={why_info['evidence_count']} "
                 f"planted_in_evidence={why_info['evidence_has_planted_text']}")
    else:
        why_info["error"] = "no belief_id to trace"
        log.emit("why skipped: no belief_id")
    report["why"] = why_info
    log.emit("")

    tools = _mcp_tool_names(env)
    report["mcp_tools"] = tools
    expected = ["hippa_build_context", "hippa_forget", "hippa_recall",
                "hippa_record_outcome", "hippa_remember", "hippa_status"]
    mcp_ok = tools == expected
    log.emit(f"MCP tools ({len(tools)}): {', '.join(tools)}")

    planted_ok = bool(ingest_info["planted_turn_present"] and ingest_info["archive_sha256"])
    recall_ok = bool(hit.get("matched"))
    evidence_ok = bool(hit.get("supported_by_evidence") or why_info.get("evidence_count"))
    quarantine_ok = (default_hides is True) if used_extract else True
    if used_extract and not extract_info.get("planted_in_candidates") and not recall_ok:
        report["limitations"].append(
            "live extract ran but neither candidates nor recall contained 52Nm"
        )
    report["ok"] = bool(
        planted_ok and rec_info.get("ok") and recall_ok and evidence_ok
        and mcp_ok and quarantine_ok and rec_run.returncode == 0
    )
    if require_live:
        report["ok"] = bool(
            report["ok"] and used_extract and extract_info.get("planted_in_candidates")
        )
    log.emit("")
    log.emit(f"RESULT ok={report['ok']} mode={report['mode']} "
             f"latency_ms={hit.get('latency_ms')} "
             f"supported_by_evidence={bool(evidence_ok)}")
    report["transcript"] = log.lines
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--offline", action="store_true",
                        help="skip live LM Studio extract; store an owner memory")
    parser.add_argument("--require-live", action="store_true",
                        help="fail if LM Studio extract does not surface the planted fact")
    parser.add_argument("--json", action="store_true",
                        help="print the machine-readable report as JSON")
    parser.add_argument("--db", default="",
                        help="throwaway HUNGRY_HIPPA_DB path (default: /tmp/hh_e2e_*)")
    parser.add_argument("--fixture", default="",
                        help="synthetic conversations.json (default: eval/fixtures/...)")
    parser.add_argument("--quiet", action="store_true",
                        help="no human transcript (JSON still prints with --json)")
    args = parser.parse_args(list(argv) if argv is not None else None)

    echo = not args.quiet and not args.json
    try:
        report = run_e2e(
            db_path=args.db, fixture=args.fixture, offline=args.offline,
            require_live=args.require_live, echo=echo,
        )
    except SystemExit:
        raise
    except Exception as e:
        print(f"e2e crashed: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    if args.json:
        slim = dict(report)
        slim.pop("transcript", None)
        print(json.dumps(slim, ensure_ascii=False, indent=2, default=str))
    elif args.quiet:
        print(f"ok={report['ok']} mode={report['mode']} "
              f"latency_ms={report.get('recall', {}).get('latency_ms')}")
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
