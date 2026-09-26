#!/usr/bin/env python3
"""Hungry Hippa demo — eight scripted steps, no LLM, no network, throwaway DB.

Run it:

    python demo/demo.py --reset     # recreate the demo database from seed.json
    python demo/demo.py             # play the scripted demo
    python demo/demo.py --check     # play it and diff against expected_output.txt
    python demo/demo.py --tmp       # use a fresh temp database instead of demo/.demo_db

The demo never opens the operator's own database. The database it uses is a
throwaway under ``demo/.demo_db`` (or a temp dir with ``--tmp``).

Every step prints what it is doing, so the transcript doubles as the
demonstration script. ``--check`` normalises dates/ids and compares the run
against ``demo/expected_output.txt`` so drift is visible instead of being
hand-waved.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

DEMO_DIR = Path(__file__).resolve().parent
REPO_DIR = DEMO_DIR.parent
PACKAGE_DIR = REPO_DIR / "src" / "hungry_hippa"   # src layout
SEED_PATH = DEMO_DIR / "seed.json"
EXPECTED_PATH = DEMO_DIR / "expected_output.txt"
DEFAULT_DB_DIR = DEMO_DIR / ".demo_db"

YEAR_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
# mkdtemp(prefix="hh_demo_") follows TMPDIR, which is not always /tmp.
DEMO_DB_RE = re.compile(
    r"(?:/[^\s'\"]*)?\.demo_db/hungry_hippa\.db|/[^\s'\"]*hh_demo_[^\s'\"]*")
# The only difference between the default and --tmp runs is the closing note.
CLEANUP_RE = re.compile(
    r"^(Reset it with: python demo/demo\.py --reset"
    r"|This run used a temporary database \(--tmp\) and leaves nothing behind\.)$",
    re.MULTILINE)


try:                     # normal import: the package is installed (editable install)
    import hungry_hippa  # noqa: F401
    from hungry_hippa import trust
except ModuleNotFoundError:   # running from a clone: use this checkout's src/
    sys.path.insert(0, str(REPO_DIR / "src"))
    import hungry_hippa  # noqa: F401
    from hungry_hippa import trust


# ------------------------------------------------------------- transcript

class Transcript:
    def __init__(self, echo: bool = True) -> None:
        self.lines: List[str] = []
        self.echo = echo

    def emit(self, text: str = "") -> None:
        if self.echo:
            print(text)
        self.lines.append(text)


def normalise(text: str) -> str:
    """Strip the parts of the transcript that are legitimately machine-specific."""
    out = DEMO_DB_RE.sub("<demo-db>", text)
    out = YEAR_RE.sub("<timestamp>", out)
    out = DATE_RE.sub("<date>", out)
    out = CLEANUP_RE.sub("<cleanup-note>", out)
    return "\n".join(line.rstrip() for line in out.strip().splitlines())


# ---------------------------------------------------------------- database

def demo_db_path(use_tmp: bool) -> str:
    if use_tmp:
        return os.path.join(tempfile.mkdtemp(prefix="hh_demo_"), "hungry_hippa.db")
    env = os.environ.get("HUNGRY_HIPPA_DEMO_DB")
    if env:
        return env
    return str(DEFAULT_DB_DIR / "hungry_hippa.db")


def demo_owner_token(db_path: str):
    """A demo-scoped owner token file and value, never the operator's real one.

    The demo shows the identity boundary honestly: the owner instance is a server
    *launched with* a token that only the operator's user could read, instead of a
    client typing actor_id "primary" and being believed. Returns
    ``(token_file, token)``.
    """
    from hungry_hippa import trust

    path = os.path.join(os.path.dirname(os.path.abspath(db_path)), "owner.token")
    return path, trust.ensure_owner_token(path)


def fresh_controller(db_path: str, session_id: str, actor: str = "primary"):
    from hungry_hippa.config import load_config
    from hungry_hippa.controller import MemoryController

    cfg = load_config()
    cfg["retrieval"]["vectors_enabled"] = False          # offline, deterministic
    cfg["consolidation"]["on_session_end"] = False
    cfg["retrieval"]["max_context_chars"] = 1200
    ctrl = MemoryController(cfg, db_path=db_path)
    ctrl.bind_session(session_id=session_id, platform="demo",
                      agent_context="primary", actor_id=actor)
    return ctrl


def reset_database(db_path: str) -> Dict[str, Any]:
    """Recreate the demo database and apply the seed's background history.

    The seed contributes earlier, unrelated project history (so the store is not
    empty); the scripted demo records its own decision, failed attempt and
    outcome at run time.
    """
    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    for path in (db_path, db_path + "-wal", db_path + "-shm"):
        if os.path.exists(path):
            os.remove(path)
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)

    ctrl = fresh_controller(db_path, session_id="seed", actor="primary")
    for item in seed.get("background", []):
        if item.get("type") == "episode":
            ctrl.remember_episode(context=item["context"], result=item.get("result", ""),
                                  outcome=item.get("outcome", "unknown"),
                                  project=item.get("project", ""),
                                  importance=item.get("importance", 0.6), embed=False)
        elif item.get("type") == "belief":
            ctrl.semantic.add_belief(item["claim"], kind=item.get("kind", "fact"),
                                     confidence=item.get("confidence"),
                                     source_class=item.get("source_class", "document"))
    return seed


# ------------------------------------------------------------ MCP client

def mcp_calls(db_path: str, calls, *, token_file: str = "", token: str = ""):
    """Talk to a Hungry Hippa MCP server with the *official* MCP SDK client.

    Each call starts a fresh server process over the SDK's stdio transport and
    initialises a session — nothing here re-implements JSON-RPC. Identity is a
    property of the *server launch context*: ``token`` is placed in the server's
    environment, and the server verifies it against the token file before it will
    act as the owner. An untrusted instance is the same server started without it.
    """
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    env = dict(os.environ)
    env["HUNGRY_HIPPA_DB"] = db_path
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("LIVING_CORTEX_DB", None)
    env.pop("HUNGRY_HIPPA_OWNER_TOKEN", None)
    if token_file:
        env["HUNGRY_HIPPA_OWNER_TOKEN_FILE"] = token_file
    if token:
        env["HUNGRY_HIPPA_OWNER_TOKEN"] = token

    params = StdioServerParameters(
        command=sys.executable, args=[str(PACKAGE_DIR / "mcp_server.py")],
        env=env, cwd=str(REPO_DIR))

    async def _run():
        out = []
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                for name, args in calls:
                    result = await session.call_tool(name, args or {})
                    text = "".join(getattr(b, "text", "") or ""
                                   for b in getattr(result, "content", []) or [])
                    try:
                        out.append(json.loads(text) if text else {})
                    except json.JSONDecodeError:
                        out.append({"_raw": text})
        return out

    return asyncio.run(_run())



# ------------------------------------------------------------------ steps

def run_demo(db_path: str, use_tmp: bool) -> Transcript:
    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    q = seed["questions"]
    t = Transcript()

    t.emit("Hungry Hippa demo — local-first memory runtime for AI agents")
    t.emit("=" * 72)
    t.emit(f"demo database: {db_path}")
    t.emit("(throwaway; the production database is never opened)")
    t.emit("")

    # ---------------------------------------------------------------- step 1
    t.emit("STEP 1 — an agent starts work on a small project")
    t.emit("-" * 72)
    session_a = fresh_controller(db_path, session_id="demo-session-A")
    t.emit("session A begins. The agent is asked to free a seized housing on Project A.")
    t.emit(f"  project: {seed['project']}   actor: {seed['actor']}")
    t.emit("")

    # ---------------------------------------------------------------- step 2
    t.emit("STEP 2 — it records a decision, an attempted fix and the outcome")
    t.emit("-" * 72)
    decision = seed["decision"]
    failed = seed["failed_attempt"]
    belief = session_a.semantic.add_belief(decision["claim"], kind="fact",
                                           confidence=decision["confidence"],
                                           source_class="user_explicit")
    attempt = session_a.remember_episode(
        context=failed["context"], user_request=failed["user_request"],
        actions_taken=failed["actions_taken"], result=failed["result"],
        outcome=failed["outcome"], project=seed["project"],
        importance=failed["importance"], embed=False)
    t.emit(f"  recorded decision  {belief['belief_id']}: {decision['claim']}")
    t.emit(f"  recorded attempt   {attempt['episode_id']}: {failed['context']}")
    t.emit(f"                     outcome={failed['outcome']} result={failed['result']}")
    t.emit("")

    # ---------------------------------------------------------------- step 3
    t.emit("STEP 3 — the session ends")
    t.emit("-" * 72)
    changes = session_a.db._run(lambda conn: conn.execute(
        "SELECT COUNT(*) AS n FROM mutation_log").fetchone()["n"])
    t.emit(f"session A ends. Its context window is discarded. {changes} audit rows remain.")
    t.emit("")

    # ---------------------------------------------------------------- step 4
    t.emit("STEP 4 — a new session begins with no conversation history")
    t.emit("-" * 72)
    session_b = fresh_controller(db_path, session_id="demo-session-B")
    t.emit("session B starts empty: no messages, no summary, only the memory runtime.")
    t.emit("")

    # ---------------------------------------------------------------- step 5
    t.emit("STEP 5 — Hungry Hippa restores the relevant context")
    t.emit("-" * 72)
    t.emit(f"  agent asks: {q['restore']}")
    restored = session_b.build_context(q["restore"])
    t.emit("  restored context:")
    for line in (restored.get("rendering") or "(nothing)").splitlines():
        t.emit(f"    {line}")
    t.emit(f"  items: {len(restored.get('items', []))}  "
           f"chars: {restored.get('chars_used')}  "
           f"token_estimate: {restored.get('token_estimate')}")
    t.emit("")

    # ---------------------------------------------------------------- step 6
    t.emit("STEP 6 — the agent avoids repeating the failed fix")
    t.emit("-" * 72)
    context = (restored.get("rendering") or "").lower()
    aware = failed["result"].lower() in context or failed["outcome"] in context
    if aware:
        t.emit(f"  the restored context contains the failed attempt "
               f"({failed['context']} -> {failed['result']}).")
        t.emit("  the agent does not repeat it; it proposes the warm-soak approach instead.")
    else:
        t.emit("  WARNING: the failed attempt was not restored — the demo premise is broken.")
    working = seed["working_attempt"]
    fixed = session_b.remember_episode(context=working["context"],
                                       actions_taken=working["actions_taken"],
                                       result=working["result"],
                                       outcome=working["outcome"],
                                       project=seed["project"],
                                       importance=working["importance"], embed=False)
    t.emit(f"  selected approach recorded as {fixed['episode_id']} "
           f"(outcome={working['outcome']})")
    t.emit("")

    # ---------------------------------------------------------------- step 7
    t.emit("STEP 7 — a second compatible agent gets only what it is authorized to read")
    t.emit("-" * 72)
    # The owner token file must exist before the owner instance starts; the
    # token itself is passed in the *server's* environment, never as an argument.
    token_file, owner_token = demo_owner_token(db_path)
    t.emit("  starting a separate MCP server process via the official SDK client "
           "(stdio, local only)...")
    (untrusted,) = mcp_calls(
        db_path,
        [("hippa_recall", {"actor_id": "mcp-untrusted", "query": q["decision"]})],
        token_file=token_file)
    t.emit(f"  untrusted instance -> count={untrusted.get('count')} "
           f"items={len(untrusted.get('items', []))} "
           f"excluded={untrusted.get('excluded')}")
    t.emit("  (excluded items are not enumerated for a caller that may not read "
           "them: ids and counts are an existence oracle)")
    owner, status = mcp_calls(
        db_path,
        [("hippa_recall", {"actor_id": "primary", "query": q["decision"]}),
         ("hippa_status", {"actor_id": "mcp-untrusted"})],
        token_file=token_file, token=owner_token)
    t.emit(f"  owner-authorized  -> count={owner.get('count')} "
           f"items={[(i['id'], i['type']) for i in owner.get('items', [])]}")
    t.emit(f"  status (counts only) -> {status.get('counts')}")
    t.emit("  the untrusted instance received nothing; the owner-authorized "
           "instance received the history.")
    t.emit("")

    # ---------------------------------------------------------------- step 8
    t.emit("STEP 8 — the operator can inspect, correct and forget a memory")
    t.emit("-" * 72)
    from hungry_hippa.observability import Observability

    obs = Observability(session_b.db, session_b.cfg, controller=session_b)
    before = session_b.semantic.get_belief(belief["belief_id"])
    t.emit(f"  inspect : {before['belief_id']} = \"{before['claim']}\" "
           f"(confidence {before['confidence']:.2f}, source {before['source_class']})")
    trace = obs.why(belief["belief_id"])
    t.emit(f"  why     : verdict={trace['verdict']}")

    corrected = session_b.update_belief(
        belief["belief_id"], new_claim=seed["corrected_claim"],
        reason="operator correction during the demo", confidence=0.95,
        source_class="user_explicit")
    old = session_b.semantic.get_belief(belief["belief_id"])
    t.emit(f"  correct : {old['belief_id']} is now status={old['status']}")
    t.emit(f"            {corrected['belief_id']} = \"{seed['corrected_claim']}\"")
    current = session_b.build_context(q["inspect"])
    t.emit("  recall  : current answer only ->")
    for line in (current.get("rendering") or "(nothing)").splitlines():
        t.emit(f"            {line}")
    t.emit(f"            excluded={current.get('excluded')}")

    forgotten = session_b.forget("belief", corrected["belief_id"], mode="archival",
                                 reason="operator asked to forget")
    after = session_b.build_context(q["inspect"])
    still_there = seed["corrected_claim"] in (after.get("rendering") or "")
    t.emit(f"  forget  : archived={forgotten.get('archived')} "
           f"(reversible; the row is retained as status='archived')")
    t.emit(f"            the corrected claim is now recalled: {still_there} "
           f"(other memories for the project stay)")
    t.emit(f"            recall returns {len(after.get('items', []))} item(s)")
    t.emit("")
    t.emit("STEP 8b — the audit trail explains what happened")
    t.emit("-" * 72)
    for row in obs.recent_changes(limit=6):
        t.emit(f"  {row['ts']}  {row['action']:<18} {row['target_kind']:<8} "
               f"{row['target_id']:<8} {str(row['detail'])[:60]}")
    t.emit("")
    t.emit("=" * 72)
    t.emit("demo complete. Nothing was sent anywhere; the database above is a throwaway.")
    if use_tmp:
        t.emit("This run used a temporary database (--tmp) and leaves nothing behind.")
    else:
        t.emit(f"Reset it with: python demo/demo.py --reset")
    return t


# ------------------------------------------------------------------- main

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Hungry Hippa scripted demo")
    parser.add_argument("--reset", action="store_true",
                        help="recreate the demo database from demo/seed.json and exit")
    parser.add_argument("--tmp", action="store_true",
                        help="use a fresh temporary database instead of demo/.demo_db")
    parser.add_argument("--check", action="store_true",
                        help="compare the run against demo/expected_output.txt")
    parser.add_argument("--check-normaliser", action="store_true",
                        help="assert transcript paths normalise under the live temp dir")
    args = parser.parse_args(argv)

    if args.check_normaliser:
        scratch = tempfile.mkdtemp(prefix="hh_demo_")
        live = os.path.join(scratch, "hungry_hippa.db")
        samples = [
            live,
            "/tmp/hh_demo_example/hungry_hippa.db",
            str(DEFAULT_DB_DIR / "hungry_hippa.db"),
        ]
        for sample in samples:
            normalised = normalise(f"demo database: {sample}\n")
            if sample in normalised or "<demo-db>" not in normalised:
                print(f"normaliser left a machine path: {sample}", file=sys.stderr)
                return 1
        print("PASS demo path normaliser")
        return 0

    db_path = demo_db_path(args.tmp)

    if args.reset and not args.tmp:
        seed = reset_database(db_path)
        background = seed.get("background", [])
        episodes = sum(1 for i in background if i.get("type") == "episode")
        beliefs = sum(1 for i in background if i.get("type") == "belief")
        print(f"reset: {db_path}")
        print(f"seeded background history: {episodes} episode(s) + {beliefs} belief(s) "
              f"(from {SEED_PATH.name})")
        return 0

    if args.check:
        # a comparison run must start from the seed or it is not reproducible
        reset_database(db_path)
    elif args.tmp or not os.path.exists(db_path):
        # a fresh database is seeded automatically so the demo always runs
        reset_database(db_path)

    transcript = run_demo(db_path, args.tmp)

    if args.check:
        if not EXPECTED_PATH.exists():
            print(f"\n--check: {EXPECTED_PATH.name} is missing", file=sys.stderr)
            return 2
        actual = normalise("\n".join(transcript.lines))
        expected = normalise(EXPECTED_PATH.read_text(encoding="utf-8"))
        if actual == expected:
            print("\n--check: transcript matches expected_output.txt")
            return 0
        import difflib

        diff = list(difflib.unified_diff(expected.splitlines(), actual.splitlines(),
                                         "expected_output.txt", "actual",
                                         lineterm=""))
        print("\n--check: transcript differs from expected_output.txt",
              file=sys.stderr)
        for line in diff[:80]:
            print(line, file=sys.stderr)
        return 1

    if args.tmp:
        shutil.rmtree(os.path.dirname(db_path), ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
