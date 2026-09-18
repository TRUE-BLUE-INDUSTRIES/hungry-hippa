"""Hermes session ingest tests (parse + CLI --apply).

Fixtures are synthetic and written to temporary files. They match the inspected
Hermes export shape (session object with ``messages``, JSONL session-per-line,
legacy ``{session_id}.jsonl`` message-per-line) without copying anyone's
personal transcripts. CLI output is asserted *not* to contain turn bodies.

run_all() -> list of {name, passed, detail}.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

REPO_DIR = Path(__file__).resolve().parent.parent


sys.path.insert(0, str(Path(__file__).resolve().parent))   # tests/ (shared helpers)
from _package import import_package  # noqa: E402

PACKAGE_DIR = REPO_DIR / "src" / "hungry_hippa"   # src layout
SRC_DIR = PACKAGE_DIR.parent
_PLUGIN = import_package()
from hungry_hippa.ingest import parse_hermes_export  # noqa: E402
from hungry_hippa.ingest.models import NormalizedTurn  # noqa: E402


def _cli_env(db_path: str) -> Dict[str, str]:
    env = dict(os.environ)
    env["HUNGRY_HIPPA_DB"] = db_path
    env["PYTHONPATH"] = str(SRC_DIR)
    work = os.path.dirname(os.path.abspath(db_path)) or tempfile.mkdtemp(prefix="hh_hermes_xdg_")
    env["XDG_DATA_HOME"] = work
    env["XDG_STATE_HOME"] = work
    env["XDG_CONFIG_HOME"] = work
    return env


def _run_cli(argv: List[str], *, env: Dict[str, str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "hungry_hippa.cli", *argv],
        env=env, cwd=cwd, capture_output=True, text=True, timeout=120,
    )


# ----------------------------------------------------------------------- fixtures

USER_Q = "how do I hang a 4x12 on a metal stud wall?"
ASSISTANT_A = "Frame, insulate, then hang from the top down."
TOOL_BODY = "synthetic fixture: contents of /tmp/example.txt"
SECRET = "SECRET_TOKEN_SHOULD_NOT_APPEAR_IN_LOGS"
ABANDONED = "abandoned wording that was rewound"


def _msg(msg_id: Any, role: str, content: Any, *, timestamp: Any = 1_700_000_000.0,
         active: Any = None, tool_name: str = "", tool_calls: Any = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "id": msg_id,
        "role": role,
        "content": content,
        "timestamp": timestamp,
    }
    if active is not None:
        out["active"] = active
    if tool_name:
        out["tool_name"] = tool_name
    if tool_calls is not None:
        out["tool_calls"] = tool_calls
    return out


def _session(session_id: str, messages: List[Dict[str, Any]], *,
             title: str = "Hanging board", started_at: Any = 1_699_000_000.0,
             source: str = "cli", model: str = "test/model") -> Dict[str, Any]:
    return {
        "id": session_id,
        "source": source,
        "model": model,
        "title": title,
        "started_at": started_at,
        "last_activity_at": started_at + 60,
        "message_count": len(messages),
        "messages": messages,
    }


def _linear_session() -> Dict[str, Any]:
    return _session("20260903_192003_62e0e5", [
        _msg(1, "user", USER_Q, timestamp=1_700_000_100.0),
        _msg(2, "assistant", ASSISTANT_A, timestamp=1_700_000_200.0),
    ])


def _tool_session() -> Dict[str, Any]:
    return _session("20260904_160245_c16882", [
        _msg(10, "user", "read the example file", timestamp=1_700_000_100.0),
        _msg(11, "assistant", "", timestamp=1_700_000_200.0,
             tool_calls=[{"id": "call_1", "type": "function",
                          "function": {"name": "read_file",
                                       "arguments": "{\"path\": \"/tmp/example.txt\"}"}}]),
        _msg(12, "tool", TOOL_BODY, timestamp=1_700_000_300.0, tool_name="read_file"),
        _msg(13, "assistant", "The example file is a synthetic fixture.",
             timestamp=1_700_000_400.0),
    ], title="Read example")


def _write_json(payload: Any, *, name: str = "hermes_session.json",
                where: str | None = None) -> str:
    root = where or tempfile.mkdtemp(prefix="hh_hermes_")
    os.makedirs(root, exist_ok=True)
    path = os.path.join(root, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    return path


def _write_jsonl(rows: List[Any], *, name: str, where: str | None = None) -> str:
    root = where or tempfile.mkdtemp(prefix="hh_hermes_")
    os.makedirs(root, exist_ok=True)
    path = os.path.join(root, name)
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


# ------------------------------------------------------------------------- checks

def check_normalized_fields_and_provider_ids():
    fields = set(NormalizedTurn.__dataclass_fields__)
    expected = {"source", "session_id", "session_title", "turn_id", "parent_turn_id",
                "role", "content", "occurred_at", "branch_path", "source_metadata"}
    assert expected <= fields, sorted(expected - fields)
    path = _write_json(_linear_session(), name="hermes_session_20260903_192003_62e0e5.json")
    convo = parse_hermes_export(path)[0]
    assert convo.source == "hermes"
    assert convo.session_id == "20260903_192003_62e0e5", convo.session_id
    assert convo.title == "Hanging board"
    turn = convo.turns[0]
    assert turn.turn_id == "1" and turn.parent_turn_id is None
    assert convo.turns[1].turn_id == "2" and convo.turns[1].parent_turn_id == "1"
    assert turn.session_id == "20260903_192003_62e0e5"
    return "NormalizedTurn fields present; Hermes session and message ids preserved"


def check_save_json_snapshot():
    convo = parse_hermes_export(_write_json(_linear_session()))[0]
    assert [t.role for t in convo.turns] == ["user", "assistant"]
    assert convo.turns[0].content == USER_Q
    assert convo.turns[1].content == ASSISTANT_A
    assert convo.current_path_turn_ids == ("1", "2")
    assert convo.alternate_branch_turns == ()
    assert convo.turns[1].branch_path == ("1", "2")
    return "/save json snapshot: 2 turns, linear parentage, one active path"


def check_export_jsonl_session_per_line():
    other = _session("20260914_214341_0a7634", [
        _msg(1, "user", "what solvent frees a seized housing?"),
        _msg(2, "assistant", "Soak it in solvent X for twenty minutes."),
    ], title="Seized housing")
    path = _write_jsonl([_linear_session(), other], name="backup.jsonl")
    convos = parse_hermes_export(path)
    assert [c.session_id for c in convos] == [
        "20260903_192003_62e0e5", "20260914_214341_0a7634"
    ], [c.session_id for c in convos]
    assert convos[0].turn_count == 2 and convos[1].turn_count == 2
    return "hermes sessions export JSONL: one session object per line"


def check_legacy_message_jsonl_uses_filename_stem():
    sid = "20260903_192003_62e0e5"
    path = _write_jsonl([
        _msg(1, "user", USER_Q),
        _msg(2, "assistant", ASSISTANT_A),
    ], name=f"{sid}.jsonl")
    convo = parse_hermes_export(path)[0]
    assert convo.session_id == sid, convo.session_id
    assert convo.turn_ids == ("1", "2")
    assert any("filename stem" in w for w in convo.warnings), convo.warnings
    return "legacy {session_id}.jsonl: filename stem is the provider session id"


def check_directory_walk_is_confined():
    root = tempfile.mkdtemp(prefix="hh_hermes_dir_")
    inside = os.path.join(root, "sessions")
    os.mkdir(inside)
    _write_json(_linear_session(), name="keep.json", where=inside)
    # a sibling outside the given root must not be read
    outside = tempfile.mkdtemp(prefix="hh_hermes_out_")
    _write_json(_session("should-not-see", [
        _msg(1, "user", SECRET),
    ], title="outside"), name="escape.json", where=outside)
    # symlink to the outside file, and a routing index, must be skipped
    os.symlink(os.path.join(outside, "escape.json"), os.path.join(inside, "link.json"))
    with open(os.path.join(inside, "sessions.json"), "w", encoding="utf-8") as fh:
        json.dump({"agent:main:cli:dm": {
            "session_key": "agent:main:cli:dm",
            "session_id": "20260903_192003_62e0e5",
        }}, fh)
    nested = os.path.join(inside, "saved")
    os.mkdir(nested)
    _write_json(_tool_session(), name="hermes_session_20260904_160245_c16882.json",
                where=nested)

    convos = parse_hermes_export(inside)
    ids = sorted(c.session_id for c in convos)
    assert "20260903_192003_62e0e5" in ids, ids
    assert "20260904_160245_c16882" in ids, ids
    assert "should-not-see" not in ids, ids
    joined = " ".join(t.content for c in convos for t in c.turns)
    assert SECRET not in joined
    return "directory walk stays in root; symlinks and sessions.json skipped"


def check_tool_calls_without_text_are_structural():
    convo = parse_hermes_export(_write_json(_tool_session()))[0]
    assert "11" not in convo.turn_ids, convo.turn_ids
    assert "12" in convo.turn_ids and convo.turn("12").role == "tool"
    assert convo.turn("12").content == TOOL_BODY
    assert convo.turn("12").parent_turn_id == "11"  # structural parent kept
    assert convo.turn("12").branch_path == ("10", "11", "12")
    assert any("tool_calls" in w for w in convo.warnings), convo.warnings
    # arguments must not be copied into metadata
    meta_blob = json.dumps(convo.turn("12").source_metadata)
    assert "/tmp/example.txt" not in meta_blob
    assert "arguments" not in meta_blob
    return "empty assistant tool_calls produce no turn; tool result kept; args not copied"


def check_inactive_messages_are_alternate_path():
    mapping = _session("20260914_220513_cfea59", [
        _msg(1, "user", USER_Q, active=1),
        _msg(2, "assistant", ABANDONED, active=0),
        _msg(3, "assistant", ASSISTANT_A, active=1),
    ], title="Rewound reply")
    convo = parse_hermes_export(_write_json(mapping))[0]
    assert "2" in convo.turn_ids
    assert convo.turn("2").source_metadata.get("on_current_path") is False
    assert convo.current_path_turn_ids == ("1", "3"), convo.current_path_turn_ids
    assert [t.turn_id for t in convo.alternate_branch_turns] == ["2"]
    return "active=0 messages retained off the current path"


def check_multimodal_and_code_preserved():
    code = ("Here is the fix:\n\n```bash\n# keep the studs 16\" on center\n"
            "for f in a b c; do\n    echo \"$f\"\ndone\n```\n\nthen tape it.")
    parts = [
        "look at this screenshot",
        {"type": "image_url", "image_url": {"url": "file://synthetic"}},
        "\nand this code:\n```py\nprint('x')\n```",
    ]
    session = _session("conv-content", [
        _msg(1, "assistant", code),
        _msg(2, "user", parts),
    ])
    convo = parse_hermes_export(_write_json(session))[0]
    assert convo.turn("1").content == code
    mixed = convo.turn("2")
    assert mixed.content.startswith("look at this screenshot")
    assert "print('x')" in mixed.content
    assert mixed.source_metadata["unsupported_content_types"] == ["image_url"]
    return "code fences kept; image parts skipped with diagnostics"


def check_missing_timestamps_and_iso():
    session = _session("conv-time", [
        _msg(1, "user", "no timestamp here", timestamp=None),
        _msg(2, "assistant", "garbage", timestamp="not-a-number"),
        _msg(3, "user", "numeric string", timestamp="1700000000.5"),
        _msg(4, "assistant", "iso", timestamp="2024-01-01T00:00:00Z"),
    ])
    convo = parse_hermes_export(_write_json(session))[0]
    assert convo.turn("1").occurred_at is None
    assert convo.turn("2").occurred_at is None
    assert convo.turn("3").occurred_at == 1700000000.5
    assert convo.turn("4").occurred_at == 1_704_067_200.0
    assert any("timestamp" in w and "2" in w for w in convo.warnings), convo.warnings
    return "absent/garbage timestamps tolerated; numeric and ISO converted"


def check_malformed_file_does_not_kill_directory():
    root = tempfile.mkdtemp(prefix="hh_hermes_bad_")
    _write_json(_linear_session(), name="good.json", where=root)
    with open(os.path.join(root, "bad.json"), "w", encoding="utf-8") as fh:
        fh.write("{not json")
    with open(os.path.join(root, "skip.txt"), "w", encoding="utf-8") as fh:
        fh.write("not a session file")
    convos = parse_hermes_export(root)
    ids = [c.session_id for c in convos]
    assert "20260903_192003_62e0e5" in ids, ids
    assert any(c.warnings and c.turn_count == 0 for c in convos), [c.warnings for c in convos]
    return "malformed json in a directory warns; valid session still parses"


def check_refuse_disallowed_path_kinds():
    from hungry_hippa.ingest.hermes import resolve_hermes_path

    work = tempfile.mkdtemp(prefix="hh_hermes_kind_")
    txt = os.path.join(work, "notes.md")
    with open(txt, "w", encoding="utf-8") as fh:
        fh.write("# not a session\n")
    try:
        resolve_hermes_path(txt)
        raise AssertionError("markdown file was accepted")
    except OSError:
        pass
    link = os.path.join(work, "sessions.jsonl")
    target = _write_jsonl([_linear_session()], name="real.jsonl")
    os.symlink(target, link)
    try:
        resolve_hermes_path(link)
        raise AssertionError("leaf symlink was accepted")
    except OSError as e:
        assert "symlink" in str(e).lower(), e
    missing = os.path.join(work, "nope")
    try:
        resolve_hermes_path(missing)
        raise AssertionError("missing path was accepted")
    except FileNotFoundError:
        pass
    return "non-json files, leaf symlinks, and missing paths refused"


def check_json_does_not_open_extra_paths():
    decoy = tempfile.mkdtemp(prefix="hh_hermes_decoy_")
    bait = os.path.join(decoy, "bait.json")
    with open(bait, "w", encoding="utf-8") as fh:
        json.dump({"id": "bait", "messages": [_msg(1, "user", SECRET)]}, fh)
    payload = _linear_session()
    payload["attachment_path"] = bait
    payload["messages"][0]["file"] = bait
    path = _write_json(payload)
    convos = parse_hermes_export(path)
    assert convos[0].session_id == "20260903_192003_62e0e5"
    joined = " ".join(t.content for t in convos[0].turns)
    assert SECRET not in joined
    return "paths inside JSON are not opened"


def check_parser_is_offline_and_writes_nothing():
    src = (PACKAGE_DIR / "ingest" / "hermes.py").read_text(encoding="utf-8")
    forbidden = ("import sqlite3", "from .store", "ingest.store", "import mcp",
                 "requests", "urllib", "socket", "openai", "from .db", "from ..",
                 "eval(", "exec(")
    for token in forbidden:
        assert token not in src, token
    assert "sqlite3" not in src

    workdir = tempfile.mkdtemp(prefix="hh_hermes_nod_")
    db_path = os.path.join(workdir, "hungry_hippa.db")
    export = _write_json(_linear_session(), name="session.json")
    env = dict(os.environ, HUNGRY_HIPPA_DB=db_path)
    script = (
        "import sys; sys.path.insert(0, %r);"
        "from hungry_hippa.ingest import parse_hermes_export;"
        "c = parse_hermes_export(%r);"
        "print(len(c), c[0].turn_count, c[0].session_id)"
        % (str(PACKAGE_DIR.parent), export)
    )
    out = subprocess.run([sys.executable, "-c", script], env=env, cwd=workdir,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-400:]
    assert out.stdout.strip() == "1 2 20260903_192003_62e0e5", out.stdout
    assert not os.path.exists(db_path), "parsing created a database file"

    cli_env = _cli_env(db_path)
    cli = _run_cli(["ingest", "hermes", export, "--dry-run"], env=cli_env, cwd=workdir)
    assert cli.returncode == 0, cli.stderr[-400:]
    assert "No database writes" in cli.stdout, cli.stdout
    assert "Conversations: 1" in cli.stdout and "Turns:" in cli.stdout, cli.stdout
    assert USER_Q not in cli.stdout and ASSISTANT_A not in cli.stdout
    assert not os.path.exists(db_path), "the CLI dry run created a database"

    refused = _run_cli(["ingest", "hermes", export], env=cli_env, cwd=workdir)
    assert refused.returncode == 1, refused.returncode
    assert "refusing to write" in refused.stdout, refused.stdout
    assert "--apply" in refused.stdout, refused.stdout
    assert not os.path.exists(db_path), "a refused ingest created a database"
    return "stdlib-only hermes parser; dry-run enforced; turn bodies not printed"


def check_apply_persists_canonical_turns_not_memories():
    workdir = tempfile.mkdtemp(prefix="hh_hermes_apply_")
    db_path = os.path.join(workdir, "hungry_hippa.db")
    export_dir = os.path.join(workdir, "sessions")
    os.mkdir(export_dir)
    _write_json(_linear_session(), name="a.json", where=export_dir)
    _write_json(_tool_session(), name="b.json", where=export_dir)
    env = _cli_env(db_path)
    first = _run_cli(["ingest", "hermes", export_dir, "--apply"], env=env, cwd=workdir)
    assert first.returncode == 0, (first.stderr[-400:], first.stdout[-400:])
    assert "Hermes sessions ingested" in first.stdout, first.stdout
    assert "Conversations: 2" in first.stdout
    # linear 2 + tool session 3 textual turns (empty tool_calls skipped)
    assert "Turns: 5" in first.stdout, first.stdout
    assert "Turns inserted: 5" in first.stdout
    assert "No episodes" in first.stdout
    assert USER_Q not in first.stdout
    assert ASSISTANT_A not in first.stdout
    assert TOOL_BODY not in first.stdout
    assert SECRET not in first.stdout
    assert os.path.isfile(db_path)

    conn = sqlite3.connect(db_path)
    try:
        turns = conn.execute(
            "SELECT source, session_id, turn_id, role FROM ingest_turns ORDER BY rowid"
        ).fetchall()
        assert {row[0] for row in turns} == {"hermes"}
        sessions = {row[1] for row in turns}
        assert sessions == {"20260903_192003_62e0e5", "20260904_160245_c16882"}, sessions
        assert conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM memory_fts").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM ingest_archives").fetchone()[0] == 2
    finally:
        conn.close()

    second = _run_cli(["ingest", "hermes", export_dir, "--apply"], env=env, cwd=workdir)
    assert second.returncode == 0, (second.stderr[-400:], second.stdout[-400:])
    assert "Turns inserted: 0" in second.stdout, second.stdout
    assert "Turns already present: 5" in second.stdout
    return "apply writes hermes turns + archives; second run is a no-op; no memories"


def check_apply_single_file_hashes_like_chatgpt():
    workdir = tempfile.mkdtemp(prefix="hh_hermes_file_")
    db_path = os.path.join(workdir, "hungry_hippa.db")
    export = _write_json(_linear_session(), name="session.json")
    env = _cli_env(db_path)
    result = _run_cli(["ingest", "hermes", export, "--apply"], env=env, cwd=workdir)
    assert result.returncode == 0, (result.stderr[-400:], result.stdout[-400:])
    raw = open(export, "rb").read()
    digest = hashlib.sha256(raw).hexdigest()
    assert digest in result.stdout, result.stdout
    conn = sqlite3.connect(db_path)
    try:
        archive = conn.execute(
            "SELECT sha256, byte_length, original_path, archived_path FROM ingest_archives"
        ).fetchone()
        assert archive[0] == digest
        assert archive[1] == len(raw)
        assert archive[2] == os.path.abspath(export)
        assert archive[3] and os.path.isfile(archive[3])
        mode = os.stat(archive[3]).st_mode & 0o777
        assert mode == 0o600, oct(mode)
    finally:
        conn.close()
    return "single session file --apply stores archive hash and 0600 copy"


def check_mcp_surface_unchanged():
    env = dict(os.environ, PYTHONPATH=str(SRC_DIR))
    out = subprocess.run(
        [sys.executable, str(PACKAGE_DIR / "mcp_server.py"), "--print-schemas"],
        capture_output=True, text=True, timeout=180, env=env, cwd="/tmp",
    )
    assert out.returncode == 0, out.stderr[-300:]
    tools = sorted(t["name"] for t in json.loads(out.stdout)["tools"])
    expected = ["hippa_build_context", "hippa_forget", "hippa_recall",
                "hippa_record_outcome", "hippa_remember", "hippa_status"]
    assert tools == expected, tools
    return "MCP still exactly six tools"


# --------------------------------------------------------------------------- runner

def run_all() -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []

    def check(name: str, fn) -> None:
        try:
            detail = fn() or "ok"
            results.append({"name": name, "passed": True, "detail": str(detail)[:300]})
        except AssertionError as e:
            results.append({"name": name, "passed": False, "detail": f"assert: {e}"})
        except Exception as e:
            results.append({"name": name, "passed": False,
                            "detail": f"{type(e).__name__}: {e}"})

    check("normalized_fields_and_provider_ids", check_normalized_fields_and_provider_ids)
    check("save_json_snapshot", check_save_json_snapshot)
    check("export_jsonl_session_per_line", check_export_jsonl_session_per_line)
    check("legacy_message_jsonl_uses_filename_stem",
          check_legacy_message_jsonl_uses_filename_stem)
    check("directory_walk_is_confined", check_directory_walk_is_confined)
    check("tool_calls_without_text_are_structural",
          check_tool_calls_without_text_are_structural)
    check("inactive_messages_are_alternate_path",
          check_inactive_messages_are_alternate_path)
    check("multimodal_and_code_preserved", check_multimodal_and_code_preserved)
    check("missing_timestamps_and_iso", check_missing_timestamps_and_iso)
    check("malformed_file_does_not_kill_directory",
          check_malformed_file_does_not_kill_directory)
    check("refuse_disallowed_path_kinds", check_refuse_disallowed_path_kinds)
    check("json_does_not_open_extra_paths", check_json_does_not_open_extra_paths)
    check("parser_is_offline_and_writes_nothing",
          check_parser_is_offline_and_writes_nothing)
    check("apply_persists_canonical_turns_not_memories",
          check_apply_persists_canonical_turns_not_memories)
    check("apply_single_file_hashes_like_chatgpt",
          check_apply_single_file_hashes_like_chatgpt)
    check("mcp_surface_unchanged", check_mcp_surface_unchanged)
    return results


if __name__ == "__main__":
    results = run_all()
    passed = sum(1 for r in results if r["passed"])
    for r in results:
        print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['name']}: {r['detail']}")
    print(f"\n{passed}/{len(results)} passed")
    sys.exit(0 if passed == len(results) else 1)
