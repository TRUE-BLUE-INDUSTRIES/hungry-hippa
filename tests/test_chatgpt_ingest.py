"""ChatGPT export parser tests (historical ingestion, Slice 1).

The parser is the part of ingestion that everything else will stand on, so these
tests are about *fidelity*, not features:

  * a regenerated answer or an edited prompt is still in the export and must still
    be in the parse result — dropping it would silently rewrite history;
  * the branch the export considered active is recoverable by walking backwards
    from ``current_node``, and is reported separately from the full turn set;
  * structural nodes (no message, no text) leave no turn but must not break the
    lineage of the turns below them;
  * malformed input degrades into a warning, never into a lost conversation.

Fixtures are written to temporary files as real JSON and parsed through
``parse_chatgpt_export(path)``, so the tests exercise the file path, not a
convenience in-memory shortcut. No fixture touches the operator's database: every
path here comes from ``tempfile``.

run_all() -> list of {name, passed, detail}.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

REPO_DIR = Path(__file__).resolve().parent.parent


sys.path.insert(0, str(Path(__file__).resolve().parent))   # tests/ (shared helpers)
from _package import import_package  # noqa: E402

PACKAGE_DIR = REPO_DIR / "src" / "hungry_hippa"   # src layout
_PLUGIN = import_package()
from hungry_hippa.ingest import parse_chatgpt_export  # noqa: E402
from hungry_hippa.ingest.models import NormalizedTurn  # noqa: E402


# ----------------------------------------------------------------------- fixtures

def _message(role: str, text: Any, *, create_time: Any = 1_700_000_000.0,
             content_type: str = "text", message_id: str = "",
             name: str = "", metadata: Dict[str, Any] | None = None) -> Dict[str, Any]:
    if content_type == "text":
        content: Any = {"content_type": "text", "parts": [text]}
    elif content_type == "parts":            # caller passes the parts list itself
        content = {"content_type": "text", "parts": text}
    elif content_type == "raw":
        content = text                        # for malformed-payload cases
    else:
        content = {"content_type": content_type, "parts": [text]}
    out: Dict[str, Any] = {"author": {"role": role}, "content": content,
                           "create_time": create_time, "id": message_id}
    if name:
        out["author"]["name"] = name
    if metadata is not None:
        out["metadata"] = metadata
    return out


def _node(node_id: str, parent: Any = None, children: Any = None,
          message: Any = None) -> Dict[str, Any]:
    return {"id": node_id, "parent": parent, "children": children or [],
            "message": message}


def _write(payload: Any, name: str = "conversations.json") -> str:
    where = tempfile.mkdtemp(prefix="hh_ingest_")
    path = os.path.join(where, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    return path


def _conversation(conv_id: str, mapping: Dict[str, Any], current: str,
                  *, title: str = "A conversation",
                  create_time: Any = 1_699_000_000.0) -> Dict[str, Any]:
    return {"id": conv_id, "title": title, "create_time": create_time,
            "update_time": create_time + 60, "current_node": current,
            "mapping": mapping}


def _linear_export() -> List[Dict[str, Any]]:
    """root(no message) -> user A -> assistant B, current_node = B."""
    mapping = {
        "root": _node("root", None, ["n-a"]),
        "n-a": _node("n-a", "root", ["n-b"],
                     _message("user", "how do I hang a 4x12 on a metal stud wall?")),
        "n-b": _node("n-b", "n-a", [],
                     _message("assistant", "Frame, insulate, then hang from the top down.")),
    }
    return [_conversation("conv-linear", mapping, "n-b", title="Hanging board")]


def _regenerated_reply_export():
    """The critical shape: an answer that was regenerated away plus the kept path.

        root -> user A
                  -> assistant B1        (regenerated away: historical)
                  -> assistant B2 -> user C     (kept)
        current_node = C
    """
    mapping = {
        "root": _node("root", None, ["n-a"]),
        "n-a": _node("n-a", "root", ["n-b1", "n-b2"],
                     _message("user", "what solvent frees a seized housing?",
                              create_time=1_700_000_100.0)),
        "n-b1": _node("n-b1", "n-a", [],
                      _message("assistant", "Try heat first.",
                               create_time=1_700_000_200.0)),
        "n-b2": _node("n-b2", "n-a", ["n-c"],
                      _message("assistant", "Soak it in solvent X for twenty minutes.",
                               create_time=1_700_000_300.0)),
        "n-c": _node("n-c", "n-b2", [],
                     _message("user", "it cracked", create_time=1_700_000_400.0)),
    }
    return [_conversation("conv-regen", mapping, "n-c", title="Seized housing")]


def _edited_prompt_export():
    """An edited user prompt: the first wording is abandoned, the second kept."""
    mapping = {
        "root": _node("root", None, ["n-sys"]),
        "n-sys": _node("n-sys", "root", ["n-a"],
                       _message("system", "You are a helpful assistant.",
                                create_time=1_700_001_000.0)),
        "n-a": _node("n-a", "n-sys", ["n-p1", "n-p2"],
                     _message("assistant", "What are you trying to do?",
                              create_time=1_700_001_100.0)),
        "n-p1": _node("n-p1", "n-a", [],
                      _message("user", "fix the drywall",
                               create_time=1_700_001_200.0)),
        "n-p2": _node("n-p2", "n-a", ["n-b"],
                      _message("user", "fix the ceiling drywall above the door frame",
                               create_time=1_700_001_300.0)),
        "n-b": _node("n-b", "n-p2", [],
                     _message("assistant", "Here is how to fix that seam.",
                              create_time=1_700_001_400.0)),
    }
    return [_conversation("conv-edit", mapping, "n-b", title="Drywall seam")]


# ------------------------------------------------------------------------- checks

def check_normalized_fields_match_the_spec():
    fields = set(NormalizedTurn.__dataclass_fields__)
    expected = {"source", "session_id", "session_title", "turn_id", "parent_turn_id",
                "role", "content", "occurred_at", "branch_path", "source_metadata"}
    assert expected <= fields, sorted(expected - fields)
    convo = parse_chatgpt_export(_write(_linear_export()))[0]
    turn = convo.turns[0]
    assert turn.source == "chatgpt", turn.source
    assert turn.session_id == "conv-linear" and turn.session_title == "Hanging board"
    assert isinstance(turn.branch_path, tuple) and isinstance(turn.source_metadata, dict)
    return "NormalizedTurn carries the documented fields; ids come from the export"


def check_simple_linear_conversation():
    convo = parse_chatgpt_export(_write(_linear_export()))[0]
    assert [t.turn_id for t in convo.turns] == ["n-a", "n-b"], convo.turn_ids
    assert [t.role for t in convo.turns] == ["user", "assistant"]
    assert convo.turns[0].content == "how do I hang a 4x12 on a metal stud wall?"
    assert convo.turns[0].parent_turn_id == "root"      # structural parent kept
    assert convo.turns[1].parent_turn_id == "n-a"
    assert convo.current_path_turn_ids == ("n-a", "n-b")
    assert convo.alternate_branch_turns == ()
    return "2 turns, roles and parentage intact, one active branch"


def check_regenerated_answer_is_retained_and_path_is_exact():
    convo = parse_chatgpt_export(_write(_regenerated_reply_export()))[0]

    # B1 is historical evidence and must survive the parse
    assert "n-b1" in convo.turn_ids, convo.turn_ids
    b1 = convo.turn("n-b1")
    assert b1 is not None and b1.content == "Try heat first.", b1
    assert b1.source_metadata.get("on_current_path") is False, b1.source_metadata

    # ...while the active branch is A -> B2 -> C
    assert convo.current_path_turn_ids == ("n-a", "n-b2", "n-c"), \
        convo.current_path_turn_ids
    assert "n-b1" not in convo.current_path_turn_ids
    assert [t.turn_id for t in convo.current_path_turns] == ["n-a", "n-b2", "n-c"]
    assert [t.turn_id for t in convo.alternate_branch_turns] == ["n-b1"]

    # the fork is visible in the provenance, not just in the counts
    b2 = convo.turn("n-b2")
    assert b2.parent_turn_id == "n-a", b2.parent_turn_id
    assert b1.parent_turn_id == "n-a", b1.parent_turn_id
    assert convo.turn("n-c").parent_turn_id == "n-b2"
    assert convo.turn("n-c").branch_path == ("root", "n-a", "n-b2", "n-c")
    assert convo.turn("n-b1").branch_path == ("root", "n-a", "n-b1")
    return "regenerated answer kept as branch evidence; active path is A -> B2 -> C"


def check_edited_prompt_branch():
    convo = parse_chatgpt_export(_write(_edited_prompt_export()))[0]
    assert "n-p1" in convo.turn_ids, convo.turn_ids
    p1 = convo.turn("n-p1")
    assert p1.content == "fix the drywall" and p1.role == "user"
    assert p1.source_metadata.get("on_current_path") is False, p1.source_metadata
    assert convo.current_path_turn_ids == ("n-sys", "n-a", "n-p2", "n-b")
    assert convo.turn("n-p2").content == "fix the ceiling drywall above the door frame"
    assert [t.turn_id for t in convo.alternate_branch_turns] == ["n-p1"]
    return "abandoned prompt wording retained; kept wording is on the active path"


def check_current_node_path_reconstruction():
    convo = parse_chatgpt_export(_write(_regenerated_reply_export()))[0]
    # the full node path includes structural nodes; the turn path does not
    assert convo.current_path_node_ids == ("root", "n-a", "n-b2", "n-c"), \
        convo.current_path_node_ids
    assert convo.current_node == "n-c"
    assert set(convo.current_path_turn_ids) <= set(convo.current_path_node_ids)
    assert len(convo.current_path_turn_ids) == 3 and len(convo.current_path_node_ids) == 4
    # order is root -> current, not the reverse
    assert convo.current_path_node_ids[0] == "root"
    assert convo.current_path_node_ids[-1] == convo.current_node
    return "current path reconstructed from current_node, structural nodes included"


def check_structural_nodes_preserve_lineage():
    mapping = {
        "root": _node("root", None, ["mid"]),
        "mid": _node("mid", "root", ["n-a"]),          # no message at all
        "n-a": _node("n-a", "mid", ["n-empty"],
                     _message("user", "does the seam need tape?")),
        "n-empty": _node("n-empty", "n-a", [], _message("assistant", "")),
    }
    convo = parse_chatgpt_export(_write([_conversation("conv-struct", mapping, "n-a")]))[0]
    assert [t.turn_id for t in convo.turns] == ["n-a"], convo.turn_ids
    assert convo.turn("n-a").branch_path == ("root", "mid", "n-a")
    assert convo.turn("n-a").parent_turn_id == "mid"      # structural parent kept
    assert convo.current_path_node_ids == ("root", "mid", "n-a")
    return "message-less nodes leave no turn but stay in the lineage"


def check_missing_timestamps():
    mapping = {
        "root": _node("root", None, ["n-a", "n-b", "n-c"]),
        "n-a": _node("n-a", "root", [],
                     _message("user", "no timestamp here", create_time=None)),
        "n-b": _node("n-b", "root", [],
                     _message("assistant", "textual timestamp",
                              create_time="not-a-number")),
        "n-c": _node("n-c", "root", [],
                     _message("user", "numeric string", create_time="1700000000.5")),
    }
    convo = parse_chatgpt_export(_write([_conversation("conv-time", mapping, "n-c")]))[0]
    assert convo.turn("n-a").occurred_at is None
    assert convo.turn("n-b").occurred_at is None
    assert convo.turn("n-c").occurred_at == 1700000000.5
    assert any("create_time" in w and "n-b" in w for w in convo.warnings), convo.warnings
    return "absent/null/garbage timestamps tolerated; numeric strings converted"


def check_empty_and_nonsupported_content():
    parts_mixed = [
        "look at this screenshot",
        {"content_type": "image_asset_pointer", "asset_pointer": "file-abc123"},
        "\nand this code:\n```py\nprint('x')\n```",
    ]
    mapping = {
        "root": _node("root", None, ["n-empty", "n-none", "n-thoughts", "n-mixed",
                                     "n-tool"]),
        "n-empty": _node("n-empty", "root", [],
                         _message("user", [], content_type="parts")),
        "n-none": _node("n-none", "root", [], _message("assistant", None,
                                                      content_type="raw")),
        "n-thoughts": _node("n-thoughts", "root", [],
                            _message("assistant", "internal reasoning",
                                     content_type="thoughts")),
        "n-mixed": _node("n-mixed", "root", [],
                         _message("user", parts_mixed, content_type="parts")),
        "n-tool": _node("n-tool", "root", [],
                        _message("tool", "tool output body",
                                 content_type="execution_output")),
    }
    convo = parse_chatgpt_export(_write([_conversation("conv-content", mapping,
                                                       "n-mixed")]))[0]

    assert "n-empty" not in convo.turn_ids, convo.turn_ids        # parts: []
    assert "n-none" not in convo.turn_ids, convo.turn_ids         # content: None
    assert "n-thoughts" not in convo.turn_ids, convo.turn_ids     # reasoning trace
    assert any("thoughts" in w for w in convo.warnings), convo.warnings

    mixed = convo.turn("n-mixed")
    assert mixed is not None
    assert mixed.content.startswith("look at this screenshot")
    assert "print('x')" in mixed.content                    # text parts kept in order
    assert mixed.source_metadata["unsupported_content_types"] == \
        ["image_asset_pointer"], mixed.source_metadata

    tool = convo.turn("n-tool")                              # tool role + code content
    assert tool is not None and tool.role == "tool" and tool.content == "tool output body"
    return "empty/non-text payloads skipped with diagnostics; usable parts kept"


def check_roles_preserved():
    convo = parse_chatgpt_export(_write(_edited_prompt_export()))[0]
    roles = {t.turn_id: t.role for t in convo.turns}
    assert roles["n-sys"] == "system", roles
    assert roles["n-a"] == "assistant" and roles["n-p1"] == "user", roles
    assert convo.turn("n-sys").content == "You are a helpful assistant."
    return "user/assistant/system preserved verbatim (tool covered elsewhere)"


def check_code_blocks_preserved_verbatim():
    code = ("Here is the fix:\n\n```bash\n# keep the studs 16\" on center\n"
            "for f in a b c; do\n    echo \"$f\"\ndone\n```\n\nthen tape it.")
    mapping = {
        "root": _node("root", None, ["n-a"]),
        "n-a": _node("n-a", "root", [], _message("assistant", code)),
    }
    convo = parse_chatgpt_export(_write([_conversation("conv-code", mapping, "n-a")]))[0]
    assert convo.turn("n-a").content == code, repr(convo.turn("n-a").content)
    # multi-part content keeps every part, separated by exactly one newline
    two = ["line one", "```py\nx = 1\n```"]
    mapping2 = {
        "root": _node("root", None, ["n-b"]),
        "n-b": _node("n-b", "root", [], _message("assistant", two,
                                                 content_type="parts")),
    }
    convo2 = parse_chatgpt_export(_write([_conversation("conv-code2", mapping2,
                                                        "n-b")]))[0]
    assert convo2.turn("n-b").content == "line one\n```py\nx = 1\n```"
    return "code fences, indentation and part boundaries survive byte-for-byte"


def check_deterministic_ordering():
    export = _regenerated_reply_export()
    path = _write(export)
    first = parse_chatgpt_export(path)[0]
    second = parse_chatgpt_export(path)[0]
    assert first.turn_ids == second.turn_ids == ("n-a", "n-b1", "n-b2", "n-c"), \
        (first.turn_ids, second.turn_ids)
    assert first.warnings == second.warnings

    # mapping insertion order must not influence the result
    reversed_mapping = dict(reversed(list(export[0]["mapping"].items())))
    shuffled = _conversation(export[0]["id"], reversed_mapping, "n-c",
                             title=export[0]["title"])
    other = parse_chatgpt_export(_write([shuffled]))[0]
    assert other.turn_ids == first.turn_ids, (other.turn_ids, first.turn_ids)
    assert [t.branch_path for t in other.turns] == [t.branch_path for t in first.turns]
    return "same order across runs and across mapping key order (DFS, export order)"


def check_duplicate_ids_handled_deterministically():
    mapping = {
        "root": _node("root", None, ["n-a", "n-a", "ghost"]),   # duplicate + unknown
        "n-a": _node("n-alias", "root", [],                     # id != mapping key
                     _message("user", "first wording")),
        "n-b": _node("n-b", "root", ["n-c"],
                     _message("assistant", "second")),
        "n-c": _node("n-c", "n-b", [], _message("user", "third")),
    }
    convo = parse_chatgpt_export(_write([_conversation("conv-dupe", mapping, "n-b")]))[0]
    assert convo.turn_ids == ("n-a", "n-b", "n-c"), convo.turn_ids
    joined = " | ".join(convo.warnings)
    assert "duplicate child 'n-a'" in joined, convo.warnings
    assert "declares a different id 'n-alias'" in joined, convo.warnings
    assert "'ghost'" in joined, convo.warnings
    # deterministic: parsing again yields the same ids and the same warnings
    again = parse_chatgpt_export(_write([_conversation("conv-dupe", mapping, "n-b")]))[0]
    assert again.turn_ids == convo.turn_ids and again.warnings == convo.warnings
    return "duplicate/unknown children and id mismatches handled with warnings"


def check_malformed_node_does_not_kill_conversation():
    mapping = {
        "root": _node("root", None, ["n-a", "n-bad-object", "n-bad-message",
                                     "n-bad-content", "n-c"]),
        "n-a": _node("n-a", "root", ["n-bad-object"],
                     _message("user", "the good question")),
        "n-bad-object": "this node is a string, not an object",     # malformed node
        "n-bad-message": _node("n-bad-message", "root", [],
                               "message should be an object"),      # malformed message
        "n-bad-content": _node("n-bad-content", "root", [],
                               _message("assistant", 42, content_type="raw")),
        "n-c": _node("n-c", "n-a", ["n-bad-children"],
                     _message("assistant", "the good answer")),
        "n-bad-children": {"id": "n-bad-children", "parent": "n-c",
                           "children": "not-a-list", "message": None},
    }
    convo = parse_chatgpt_export(_write([_conversation("conv-bad", mapping, "n-c")]))[0]
    assert "n-a" in convo.turn_ids and "n-c" in convo.turn_ids, convo.turn_ids
    assert convo.turn("n-a").content == "the good question"
    assert convo.turn("n-c").content == "the good answer"
    assert convo.current_path_turn_ids == ("n-a", "n-c")
    joined = " | ".join(convo.warnings)
    assert "not an object; skipped" in joined, convo.warnings
    assert "message is str" in joined, convo.warnings
    assert "children is str" in joined, convo.warnings
    # a conversation entry that is not even an object still yields a report
    broken = parse_chatgpt_export(_write(["not a conversation"]))
    assert len(broken) == 1 and broken[0].turn_count == 0 and broken[0].warnings
    # and junk that is not a list of conversations parses to nothing, not a crash
    assert parse_chatgpt_export(_write({"unexpected": True})) == []
    return "malformed nodes warn and are skipped; valid turns still parse"


def check_parser_is_offline_and_writes_nothing():
    # 1. the parser modules import only the standard library. store.py is Slice 2
    # (persist) and is allowed to talk to the database; it is not imported here.
    parser_modules = ("__init__.py", "chatgpt.py", "models.py")
    sources = {name: (PACKAGE_DIR / "ingest" / name).read_text(encoding="utf-8")
               for name in parser_modules}
    forbidden = ("sqlite3", "import mcp", "requests", "urllib", "socket",
                 "openai", "controller", "from .db", "from ..")
    for name, src in sources.items():
        for token in forbidden:
            assert token not in src, (name, token)
    store_path = PACKAGE_DIR / "ingest" / "store.py"
    assert store_path.is_file(), "Slice 2 persist module missing"
    store_src = store_path.read_text(encoding="utf-8")
    assert "eval(" not in store_src and "exec(" not in store_src

    # 2. parsing an export creates no database, even when one is configured
    workdir = tempfile.mkdtemp(prefix="hh_ingest_nod_")
    db_path = os.path.join(workdir, "hungry_hippa.db")
    export = _write(_regenerated_reply_export(), name="conversations.json")
    env = dict(os.environ, HUNGRY_HIPPA_DB=db_path)
    script = (
        "import sys; sys.path.insert(0, %r);"
        "from hungry_hippa.ingest import parse_chatgpt_export;"
        "c = parse_chatgpt_export(%r);"
        "print(len(c), c[0].turn_count)"
        % (str(PACKAGE_DIR.parent), export))
    out = subprocess.run([sys.executable, "-c", script], env=env, cwd=workdir,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-400:]
    assert out.stdout.strip() == "1 4", out.stdout
    assert not os.path.exists(db_path), "parsing created a database file"
    assert not [f for f in os.listdir(workdir) if f.endswith(".db")], os.listdir(workdir)

    # 3. the CLI dry run parses and reports, and also writes no database
    cli_env = dict(os.environ, HUNGRY_HIPPA_DB=db_path)
    cli = subprocess.run([sys.executable, "-m", "hungry_hippa.cli", "ingest", "chatgpt",
                          export, "--dry-run"], env=cli_env, cwd=workdir,
                         capture_output=True, text=True, timeout=120)
    assert cli.returncode == 0, cli.stderr[-400:]
    assert "No database writes" in cli.stdout, cli.stdout
    assert "Conversations: 1" in cli.stdout and "Turns:" in cli.stdout, cli.stdout
    assert not os.path.exists(db_path), "the CLI dry run created a database"

    # 4. without --dry-run the command refuses rather than pretending to import
    refused = subprocess.run([sys.executable, "-m", "hungry_hippa.cli", "ingest",
                              "chatgpt", export], env=cli_env, cwd=workdir,
                             capture_output=True, text=True, timeout=120)
    assert refused.returncode == 1, refused.returncode
    assert "only --dry-run" in refused.stdout, refused.stdout
    return "stdlib-only imports; parses without creating a database; dry run enforced"


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

    check("normalized_fields_match_the_spec", check_normalized_fields_match_the_spec)
    check("simple_linear_conversation", check_simple_linear_conversation)
    check("regenerated_answer_retained_with_exact_active_path",
          check_regenerated_answer_is_retained_and_path_is_exact)
    check("edited_prompt_branch", check_edited_prompt_branch)
    check("current_node_path_reconstruction", check_current_node_path_reconstruction)
    check("structural_nodes_preserve_lineage", check_structural_nodes_preserve_lineage)
    check("missing_timestamps", check_missing_timestamps)
    check("empty_and_nonsupported_content", check_empty_and_nonsupported_content)
    check("roles_preserved", check_roles_preserved)
    check("code_blocks_preserved_verbatim", check_code_blocks_preserved_verbatim)
    check("deterministic_ordering", check_deterministic_ordering)
    check("duplicate_ids_handled_deterministically",
          check_duplicate_ids_handled_deterministically)
    check("malformed_node_does_not_kill_conversation",
          check_malformed_node_does_not_kill_conversation)
    check("parser_is_offline_and_writes_nothing", check_parser_is_offline_and_writes_nothing)
    return results


if __name__ == "__main__":
    results = run_all()
    passed = sum(1 for r in results if r["passed"])
    for r in results:
        print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['name']}: {r['detail']}")
    print(f"\n{passed}/{len(results)} passed")
    sys.exit(0 if passed == len(results) else 1)
