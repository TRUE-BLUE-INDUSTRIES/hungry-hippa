"""HH-08 ChatGPT ingest e2e: persist → (optional extract) → recall with evidence.

Always-on path is offline: synthetic conversations.json, throwaway DB, ingest
--apply, then recall of a directly stored owner memory whose evidence points at
the planted ingest turn. Live LM Studio extract is attempted and SKIPPED
(still pass) when the chat model is down.

Never opens live Hermes/Grok stores. Fixture is invented; no personal data.

run_all() -> list of {name, passed, detail}.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

REPO_DIR = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _package import import_package  # noqa: E402

PACKAGE_DIR = REPO_DIR / "src" / "hungry_hippa"
SRC_DIR = PACKAGE_DIR.parent
_PLUGIN = import_package()

E2E = REPO_DIR / "eval" / "ingest_e2e.py"
FIXTURE = REPO_DIR / "eval" / "fixtures" / "chatgpt_e2e_conversations.json"
EXPECTED_TOOLS = [
    "hippa_build_context", "hippa_forget", "hippa_recall",
    "hippa_record_outcome", "hippa_remember", "hippa_status",
]


def _cli_env(db_path: str) -> Dict[str, str]:
    env = dict(os.environ)
    env["HUNGRY_HIPPA_DB"] = db_path
    env["PYTHONPATH"] = str(SRC_DIR)
    work = os.path.dirname(os.path.abspath(db_path)) or tempfile.mkdtemp(prefix="hh_e2e_")
    env["XDG_DATA_HOME"] = work
    env["XDG_STATE_HOME"] = work
    env["XDG_CONFIG_HOME"] = work
    return env


def _run_e2e(args: List[str], *, env: Dict[str, str],
             timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(E2E), *args],
        env=env, cwd=str(REPO_DIR), capture_output=True, text=True, timeout=timeout,
    )


def _fresh_db() -> str:
    return os.path.join(tempfile.mkdtemp(prefix="hh_e2e_test_"), "hungry_hippa.db")


def check_fixture_is_synthetic_and_planted():
    assert FIXTURE.is_file(), FIXTURE
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(payload, list) and payload
    blob = json.dumps(payload)
    assert "52Nm" in blob and "12 March 2026" in blob
    assert "Arch Linux (Omarchy)" in blob
    assert "e2e-turn-torque-52nm" in blob
    assert "synthetic fixture" in blob.lower()
    # Guard against accidentally committing a real export.
    for needle in ("@gmail.com", "sk-", "chatgpt.com/c/", "https://chat.openai.com"):
        assert needle not in blob, needle
    titles = [c.get("title", "") for c in payload if isinstance(c, dict)]
    assert all("synthetic" in t.lower() for t in titles), titles
    return f"synthetic fixture conversations={len(payload)} planted=52Nm/Omarchy"


def check_refuses_live_operator_stores():
    from hungry_hippa.ingest.extract import forbidden_db_paths

    env = _cli_env("/tmp/hh_e2e_unused.db")
    for live in forbidden_db_paths():
        env["HUNGRY_HIPPA_DB"] = live
        out = _run_e2e(["--offline", "--json", "--db", live], env=env, timeout=60)
        assert out.returncode != 0, (live, out.stdout)
        text = (out.stdout or "") + (out.stderr or "")
        assert "refusing" in text.lower(), text[-400:]
        # Must not have created/opened the live file as this process.
        assert "Turns inserted" not in text
    unset = dict(env)
    home_db = os.path.join(os.path.expanduser("~"), "hungry_hippa.db")
    unset["HUNGRY_HIPPA_DB"] = home_db
    out = _run_e2e(["--offline", "--json", "--db", home_db], env=unset, timeout=60)
    assert out.returncode != 0
    assert "refusing" in ((out.stdout or "") + (out.stderr or "")).lower()
    return "e2e refuses live Hermes/Grok stores and $HOME paths"


def check_offline_ingest_persist_and_direct_recall():
    db_path = _fresh_db()
    env = _cli_env(db_path)
    out = _run_e2e(
        ["--offline", "--json", "--db", db_path, "--fixture", str(FIXTURE)],
        env=env, timeout=180,
    )
    assert out.returncode == 0, (out.stdout[-1500:], out.stderr[-800:])
    report = json.loads(out.stdout)
    assert report["ok"] is True, report
    assert report["mode"] == "offline-direct-store"
    ingest = report["ingest"]
    assert ingest["ok"] and ingest["planted_turn_present"]
    assert ingest["archive_sha256"] and ingest["turns"] >= 10
    assert ingest["alternate_branch_turns"] >= 1
    assert ingest["archived_copy_exists"] is True
    conn = sqlite3.connect(db_path)
    try:
        turns = conn.execute(
            "SELECT content FROM ingest_turns WHERE turn_id = ?",
            ("e2e-turn-torque-52nm",),
        ).fetchone()
        assert turns and "52Nm" in turns[0]
        assert conn.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0] >= 1
        assert conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0] == 0
        raw = conn.execute("SELECT sha256, archived_path FROM ingest_archives").fetchone()
        assert raw and raw[0] and os.path.isfile(raw[1])
    finally:
        conn.close()
    recall = report["recall"]
    assert recall["matched"] is True, recall
    assert recall["latency_ms"] >= 0
    why = report["why"]
    assert why.get("evidence_count", 0) >= 1, why
    assert why.get("evidence_ids"), why
    supported = bool(recall.get("supported_by_evidence") or why.get("evidence_count"))
    assert supported, (recall, why)
    assert report["mcp_tools"] == EXPECTED_TOOLS
    assert report["extract"]["skipped"] is True
    return (f"offline ingest turns={ingest['turns']} "
            f"recall_ms={recall['latency_ms']} "
            f"evidence={why.get('evidence_ids')}")


def check_mcp_still_six_tools():
    env = dict(os.environ, PYTHONPATH=str(SRC_DIR),
               HUNGRY_HIPPA_DB=_fresh_db())
    out = subprocess.run(
        [sys.executable, str(PACKAGE_DIR / "mcp_server.py"), "--print-schemas"],
        capture_output=True, text=True, timeout=180, env=env, cwd="/tmp",
    )
    assert out.returncode == 0, out.stderr[-300:]
    tools = sorted(t["name"] for t in json.loads(out.stdout)["tools"])
    assert tools == EXPECTED_TOOLS, tools
    return "MCP still exactly six tools"


def check_live_extract_recall_or_skip():
    from hungry_hippa.config import load_config
    from hungry_hippa.ingest.extract import ExtractorUnavailable, extractor_from_config

    db_path = _fresh_db()
    env = _cli_env(db_path)
    os.environ["HUNGRY_HIPPA_DB"] = db_path
    try:
        extractor_from_config(load_config()).health()
    except ExtractorUnavailable as e:
        return f"SKIP: live chat model unavailable ({e})"
    except Exception as e:
        return f"SKIP: live chat model unavailable ({type(e).__name__}: {e})"

    out = _run_e2e(
        ["--json", "--db", db_path, "--fixture", str(FIXTURE)],
        env=env, timeout=400,
    )
    report = json.loads(out.stdout) if out.stdout.strip().startswith("{") else {}
    if out.returncode != 0:
        raise AssertionError(
            f"live e2e failed: {out.stdout[-1200:]}\n{out.stderr[-400:]}"
        )
    assert report.get("ok") is True, report
    extract = report.get("extract") or {}
    if extract.get("skipped"):
        return f"SKIP: extract skipped after health ({extract.get('skip_reason')})"
    recall = report.get("recall") or {}
    assert recall.get("matched") is True, recall
    assert recall.get("include_quarantined") is True
    assert report.get("recall", {}).get("default_recall_hides_quarantine") is True
    why = report.get("why") or {}
    assert why.get("evidence_count", 0) >= 1, why
    return (f"live extract beliefs={extract.get('beliefs_written')} "
            f"recall_ms={recall.get('latency_ms')} "
            f"evidence={why.get('evidence_ids')}")


def run_all() -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []

    def check(name: str, fn) -> None:
        try:
            detail = fn() or "ok"
            results.append({"name": name, "passed": True, "detail": str(detail)[:400]})
        except AssertionError as e:
            results.append({"name": name, "passed": False, "detail": f"assert: {e}"})
        except Exception as e:
            results.append({"name": name, "passed": False,
                            "detail": f"{type(e).__name__}: {e}"})

    check("fixture_is_synthetic_and_planted", check_fixture_is_synthetic_and_planted)
    check("refuses_live_operator_stores", check_refuses_live_operator_stores)
    check("offline_ingest_persist_and_direct_recall",
          check_offline_ingest_persist_and_direct_recall)
    check("mcp_still_six_tools", check_mcp_still_six_tools)
    check("live_extract_recall_or_skip", check_live_extract_recall_or_skip)
    return results


if __name__ == "__main__":
    results = run_all()
    passed = sum(1 for r in results if r["passed"])
    for r in results:
        print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['name']}: {r['detail']}")
    print(f"\n{passed}/{len(results)} passed")
    sys.exit(0 if passed == len(results) else 1)
