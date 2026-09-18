"""Ingest reconcile (Layer 4): classify extract candidates against memories.

Throwaway temp databases only. HUNGRY_HIPPA_DB is always a temp path.
Never opens live Hermes/Grok stores.

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
from typing import Any, Dict, List, Optional, Sequence

REPO_DIR = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _package import import_package  # noqa: E402

PACKAGE_DIR = REPO_DIR / "src" / "hungry_hippa"
SRC_DIR = PACKAGE_DIR.parent
_PLUGIN = import_package()

from hungry_hippa.ingest.extract import (  # noqa: E402
    ExtractedCandidate,
    extract_from_store,
)
from hungry_hippa.ingest.reconcile import (  # noqa: E402
    CLASSES,
    FIXTURE_CANDIDATES,
    MemoryView,
    classify,
    classify_fixture_pack,
    fixture_pack,
    forbidden_db_paths,
    preview_pending,
    reconcile_store,
    require_extract_db_env,
    ExtractRefused,
    assert_extract_db_path,
)
from hungry_hippa.ingest import parse_chatgpt_export  # noqa: E402
from hungry_hippa.ingest.store import persist_parsed_export  # noqa: E402
from hungry_hippa.semantic import protection_reason  # noqa: E402


def _cli_env(db_path: str) -> Dict[str, str]:
    env = dict(os.environ)
    env["HUNGRY_HIPPA_DB"] = db_path
    env["PYTHONPATH"] = str(SRC_DIR)
    work = os.path.dirname(os.path.abspath(db_path)) or tempfile.mkdtemp(prefix="hh_rec_")
    env["XDG_DATA_HOME"] = work
    env["XDG_STATE_HOME"] = work
    env["XDG_CONFIG_HOME"] = work
    return env


def _run_cli(argv: List[str], *, env: Dict[str, str], cwd: str,
             timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "hungry_hippa.cli", *argv],
        env=env, cwd=cwd, capture_output=True, text=True, timeout=timeout,
    )


def _fresh_db() -> str:
    from hungry_hippa.db import Database

    path = os.path.join(tempfile.mkdtemp(prefix="hh_reconcile_"), "hungry_hippa.db")
    Database(path)
    return path


def _ctrl(path: str):
    from hungry_hippa.config import load_config
    from hungry_hippa.controller import MemoryController
    from hungry_hippa import trust

    cfg = load_config()
    cfg["retrieval"]["vectors_enabled"] = False
    ctrl = MemoryController(cfg, db_path=path)
    ctrl.bind_session(session_id="cli", platform="cli", trust=trust.local_binding("primary"))
    return ctrl


def _add_established(path: str, claim: str, *, source_class: str = "user_explicit",
                     confidence: float = 0.95, evidence: str = "established note",
                     kind: str = "fact") -> Dict[str, Any]:
    from hungry_hippa.config import load_config
    from hungry_hippa.db import Database
    from hungry_hippa.semantic import SemanticMemory
    from hungry_hippa import trust

    db = Database(path)
    eid = db.add_evidence(evidence, "document", "test:established", "")
    sem = SemanticMemory(db, load_config())
    row = sem.add_belief(
        claim, kind=kind, confidence=confidence, source_class=source_class,
        evidence_ids=[eid] if eid else None, quarantined=False,
        actor_id="primary", identity=trust.OWNER, provenance=trust.PROVENANCE_USER,
        channel=trust.CHANNEL_CLI, session_id="seed",
    )
    row["evidence_id"] = eid
    return row


def _add_candidate(path: str, claim: str, *, evidence: str = "ingest turn text",
                   source_ref: Optional[Dict[str, str]] = None,
                   evidence_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    from hungry_hippa.config import load_config
    from hungry_hippa.db import Database
    from hungry_hippa.semantic import SemanticMemory
    from hungry_hippa import trust

    db = Database(path)
    if evidence_ids is None:
        ref = json.dumps(source_ref or {
            "kind": "ingest_turn", "source": "chatgpt",
            "session_id": "conv-key", "turn_id": "n-a",
        }, ensure_ascii=False, separators=(",", ":"))
        eid = db.add_evidence(evidence, "document", ref, "")
        ids = [eid] if eid else []
    else:
        ids = list(evidence_ids)
    sem = SemanticMemory(db, load_config())
    row = sem.add_belief(
        claim, kind="hypothesis", confidence=0.4, source_class="document",
        evidence_ids=ids, quarantined=True, actor_id="ingest-extract",
        identity=trust.OWNER, provenance=trust.PROVENANCE_AGENT,
        channel=trust.CHANNEL_IMPORT, session_id="conv-key",
    )
    row["evidence_ids"] = ids
    return row


def _belief(path: str, belief_id: str) -> Dict[str, Any]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM beliefs WHERE belief_id = ?",
                           (belief_id,)).fetchone()
        if not row:
            return {}
        d = dict(row)
        ev = conn.execute(
            "SELECT evidence_id FROM belief_evidence WHERE belief_id = ?",
            (belief_id,),
        ).fetchall()
        d["evidence_ids"] = [r["evidence_id"] for r in ev]
        return d
    finally:
        conn.close()


def _count(path: str, table: str) -> int:
    conn = sqlite3.connect(path)
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    finally:
        conn.close()


def _message(role: str, text: Any, *, create_time: Any = 1_700_000_000.0) -> Dict[str, Any]:
    return {"author": {"role": role},
            "content": {"content_type": "text", "parts": [text]},
            "create_time": create_time, "id": ""}


def _node(node_id: str, parent: Any = None, children: Any = None,
          message: Any = None) -> Dict[str, Any]:
    return {"id": node_id, "parent": parent, "children": children or [],
            "message": message}


def _write_export(payload: Any) -> str:
    where = tempfile.mkdtemp(prefix="hh_rec_export_")
    path = os.path.join(where, "conversations.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    return path


def _key_export() -> List[Dict[str, Any]]:
    mapping = {
        "root": _node("root", None, ["n-a"]),
        "n-a": _node("n-a", "root", ["n-b"],
                     _message("user", "The spare brass key is in the left workshop drawer.")),
        "n-b": _node("n-b", "n-a", [],
                     _message("assistant", "Understood. I will remember that location.")),
    }
    return [{"id": "conv-key", "title": "Workshop key",
             "create_time": 1_699_000_000.0, "update_time": 1_699_000_060.0,
             "current_node": "n-b", "mapping": mapping}]


def _persist(path: str, payload: List[Dict[str, Any]]) -> None:
    from hungry_hippa.db import Database

    export = _write_export(payload)
    persist_parsed_export(Database(path), parse_chatgpt_export(export), source_path=export)


class FakeExtractor:
    model = "fake-extractor"

    def health(self) -> None:
        return None

    def extract_batch(self, turns: Sequence[Any]) -> List[ExtractedCandidate]:
        user = next((t for t in turns if getattr(t, "role", "") == "user"), turns[0])
        return [ExtractedCandidate(
            item_type="belief",
            claim="the spare brass key is in the left workshop drawer",
            turn_ids=(user.turn_id,),
            source_class="document",
        )]


# ---------------------------------------------------------------- classify

def check_v8_tables_on_fresh_db():
    from hungry_hippa.schema import CURRENT_VERSION

    path = _fresh_db()
    assert CURRENT_VERSION >= 9, CURRENT_VERSION
    conn = sqlite3.connect(path)
    try:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        versions = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
    finally:
        conn.close()
    assert "ingest_reconcile_jobs" in tables
    assert "ingest_reconcile_decisions" in tables
    assert "ingest_turns" in tables and "ingest_extract_jobs" in tables
    assert versions == {1, 2, 3, 4, 5, 6, 7, 8}, versions
    return "fresh database is schema v8 with reconcile decision tables"


def check_classify_each_class_on_fixtures():
    existing, candidates = fixture_pack()
    counts = {name: 0 for name in CLASSES}
    mismatches: List[str] = []
    for cand, expect in candidates:
        got = classify(cand, existing)
        counts[got.classification] += 1
        if got.classification != expect:
            mismatches.append(f"{cand.belief_id}: expected {expect} got {got.classification} ({got.reason})")
    assert not mismatches, mismatches
    assert counts == classify_fixture_pack()
    assert all(counts[c] == 1 for c in CLASSES), counts
    n_fix = len(FIXTURE_CANDIDATES)
    return (f"fixture pack {n_fix} candidates → "
            + ", ".join(f"{k}={v}" for k, v in counts.items()))


def check_property_classify_is_deterministic():
    existing, candidates = fixture_pack()
    for cand, expect in candidates:
        a = classify(cand, existing)
        b = classify(cand, existing)
        assert a.classification == b.classification == expect
        assert a.matched_id == b.matched_id
    # case / punctuation of a duplicate is still a duplicate
    key = existing[0]
    variant = MemoryView(
        belief_id="B-var",
        claim="The Spare Brass Key is in the left workshop drawer.",
        evidence_ids=key.evidence_ids,
        quarantined=True,
        kind="hypothesis",
        ingestion_channel="import",
        confidence=0.4,
    )
    assert classify(variant, existing).classification == "duplicate"
    return "classify is deterministic; case/punctuation duplicates still duplicate"


def check_property_contradiction_never_picks_a_winner():
    existing, candidates = fixture_pack()
    contra = next(c for c, exp in candidates if exp == "contradiction")
    decision = classify(contra, existing)
    assert decision.classification == "contradiction"
    assert decision.matched_id
    # the classifier itself does not mutate
    assert contra.status == "active"
    for mem in existing:
        assert mem.status == "active"
    return "contradiction classification does not resolve a winner"


# ---------------------------------------------------------------- apply

def check_duplicate_apply():
    path = _fresh_db()
    established = _add_established(
        path, "the spare brass key is in the left workshop drawer",
        evidence="the spare brass key is in the left workshop drawer",
    )
    est_row = _belief(path, established["belief_id"])
    cand = _add_candidate(
        path, "the spare brass key is in the left workshop drawer",
        evidence_ids=list(est_row["evidence_ids"]),
    )
    from hungry_hippa.db import Database

    db = Database(path)
    result = reconcile_store(db)
    assert result.ok and result.counts["duplicate"] == 1, result
    after_est = _belief(path, established["belief_id"])
    after_cand = _belief(path, cand["belief_id"])
    assert after_est["status"] == "active"
    assert after_cand["status"] == "archived"
    assert after_est["evidence_ids"]
    assert after_cand["evidence_ids"]
    assert set(after_cand["evidence_ids"]) <= set(after_est["evidence_ids"])
    assert _count(path, "evidence") >= 1
    return "duplicate: existing stays active, candidate archived, evidence kept"


def check_reinforcement_apply():
    path = _fresh_db()
    established = _add_established(
        path, "the spare brass key is in the left workshop drawer",
        evidence="first mention of the spare brass key",
    )
    before = _belief(path, established["belief_id"])
    cand = _add_candidate(
        path, "the spare brass key is in the left workshop drawer",
        evidence="second mention from a later turn",
        source_ref={"kind": "ingest_turn", "source": "chatgpt",
                    "session_id": "conv-key", "turn_id": "n-z"},
    )
    from hungry_hippa.db import Database

    db = Database(path)
    result = reconcile_store(db)
    assert result.counts["reinforcement"] == 1, result.counts
    after = _belief(path, established["belief_id"])
    after_cand = _belief(path, cand["belief_id"])
    assert after["status"] == "active"
    assert after["reinforcement_count"] > before["reinforcement_count"]
    assert set(cand["evidence_ids"]).issubset(set(after["evidence_ids"]))
    assert after_cand["status"] == "archived"
    assert _count(path, "evidence") >= 2
    return "reinforcement: evidence attached, confidence nudged, candidate archived"


def check_contradiction_keeps_both_and_evidence():
    path = _fresh_db()
    established = _add_established(
        path, "the crane slot is Tuesday",
        evidence="operator said the crane slot is Tuesday",
    )
    cand = _add_candidate(
        path, "the crane slot is not Tuesday",
        evidence="export turn claims the crane slot is not Tuesday",
        source_ref={"kind": "ingest_turn", "source": "chatgpt",
                    "session_id": "conv-crane", "turn_id": "n-c"},
    )
    from hungry_hippa.db import Database

    db = Database(path)
    turns_before = _count(path, "ingest_turns")
    evidence_before = _count(path, "evidence")
    result = reconcile_store(db)
    assert result.counts["contradiction"] == 1, result.counts
    old = _belief(path, established["belief_id"])
    new = _belief(path, cand["belief_id"])
    assert old["status"] == "active", old
    assert new["status"] == "active", new
    assert new["quarantined"] == 1
    old_contr = json.loads(old["contradictions"] or "[]")
    new_contr = json.loads(new["contradictions"] or "[]")
    assert cand["belief_id"] in old_contr
    assert established["belief_id"] in new_contr
    assert old["evidence_ids"] and new["evidence_ids"]
    assert _count(path, "evidence") == evidence_before
    assert _count(path, "ingest_turns") == turns_before
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        rels = [dict(r) for r in conn.execute(
            "SELECT src, rel, dst, status, valid_until FROM relationships"
        )]
    finally:
        conn.close()
    contra_rels = [r for r in rels if r["rel"] == "CONTRADICTED_BY"]
    assert contra_rels, rels
    assert all(r["status"] == "active" for r in contra_rels)
    return "contradiction: both claims active, evidence kept, no winner, graph linked"


def check_update_keeps_both():
    path = _fresh_db()
    established = _add_established(
        path, "the spare brass key is in the left workshop drawer",
        evidence="key in the drawer",
    )
    cand = _add_candidate(
        path, "the spare brass key is in the left workshop drawer behind the calipers",
        evidence="more specific location",
    )
    from hungry_hippa.db import Database

    result = reconcile_store(Database(path))
    assert result.counts["update"] == 1, result.counts
    old = _belief(path, established["belief_id"])
    new = _belief(path, cand["belief_id"])
    assert old["status"] == "active"
    assert new["status"] == "active"
    assert new["quarantined"] == 1
    derived = json.loads(new["derived_from"] or "[]")
    assert any(str(x).startswith("update_of:") for x in derived), derived
    assert old["evidence_ids"] and new["evidence_ids"]
    return "update: both claims kept, candidate derived_from update_of"


def check_supersession_unprotected():
    path = _fresh_db()
    established = _add_established(
        path, "project x uses method a",
        source_class="agent_inference", confidence=0.5, kind="belief",
        evidence="old method",
    )
    assert not protection_reason(_belief(path, established["belief_id"]))
    cand = _add_candidate(
        path, "project x now uses method b",
        evidence="replacement mentioned in export",
    )
    from hungry_hippa.db import Database

    result = reconcile_store(Database(path))
    assert result.counts["supersession"] == 1, result.counts
    old = _belief(path, established["belief_id"])
    new = _belief(path, cand["belief_id"])
    assert old["status"] == "superseded", old
    assert new["status"] == "active"
    assert new["quarantined"] == 1
    derived = json.loads(new["derived_from"] or "[]")
    assert f"supersedes:{established['belief_id']}" in derived
    assert old["evidence_ids"] and new["evidence_ids"]
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        rels = [dict(r) for r in conn.execute(
            "SELECT src, rel, dst, status, valid_from, valid_until FROM relationships"
            " WHERE rel = 'SUPERSEDES'"
        )]
    finally:
        conn.close()
    assert rels, "expected SUPERSEDES graph edge"
    assert rels[0]["valid_from"]
    return "supersession: old superseded, candidate kept, evidence on both, graph SUPERSEDES"


def check_protected_supersession_does_not_rewrite():
    path = _fresh_db()
    established = _add_established(
        path, "project x uses method a",
        source_class="user_explicit", confidence=0.95, kind="fact",
        evidence="operator attested method a",
    )
    cand = _add_candidate(path, "project x now uses method b", evidence="export says b")
    from hungry_hippa.db import Database

    result = reconcile_store(Database(path))
    assert result.counts["supersession"] == 1, result.counts
    old = _belief(path, established["belief_id"])
    new = _belief(path, cand["belief_id"])
    assert old["status"] == "active", "protected fact was rewritten"
    assert new["status"] == "active" and new["quarantined"] == 1
    assert result.decisions[0].protected == "operator-attested"
    return "protected supersession refused; both claims kept"


def check_low_confidence_and_irrelevant_stay_quarantined():
    path = _fresh_db()
    _add_established(path, "the spare brass key is in the left workshop drawer")
    low = _add_candidate(path, "noted thanks", evidence="chit chat")
    irrel = _add_candidate(
        path, "the weather in paris is mild in april",
        evidence="unrelated turn",
        source_ref={"kind": "ingest_turn", "source": "chatgpt",
                    "session_id": "conv-w", "turn_id": "n-w"},
    )
    from hungry_hippa.db import Database

    result = reconcile_store(Database(path))
    assert result.counts["low-confidence"] == 1, result.counts
    assert result.counts["irrelevant"] == 1, result.counts
    for bid in (low["belief_id"], irrel["belief_id"]):
        row = _belief(path, bid)
        assert row["status"] == "active"
        assert row["quarantined"] == 1
        assert row["evidence_ids"]
    return "low-confidence and irrelevant stay quarantined with evidence"


def check_idempotent_reapply_and_layer12_remain():
    path = _fresh_db()
    from hungry_hippa.db import Database

    _persist(path, _key_export())
    turns_before = _count(path, "ingest_turns")
    archives_before = _count(path, "ingest_archives")
    _add_established(path, "the crane slot is Tuesday")
    _add_candidate(path, "the crane slot is not Tuesday",
                   evidence="counter turn",
                   source_ref={"kind": "ingest_turn", "source": "chatgpt",
                               "session_id": "conv-crane", "turn_id": "n-c"})
    first = reconcile_store(Database(path))
    assert first.candidates_processed == 1
    decisions_n = _count(path, "ingest_reconcile_decisions")
    evidence_n = _count(path, "evidence")
    second = reconcile_store(Database(path))
    assert second.candidates_pending == 0, second
    assert second.candidates_processed == 0
    assert _count(path, "ingest_reconcile_decisions") == decisions_n
    assert _count(path, "ingest_turns") == turns_before
    assert _count(path, "ingest_archives") == archives_before
    assert _count(path, "evidence") == evidence_n
    return "re-apply is a no-op; Layer 1/2 rows and evidence remain"


def check_reextract_same_export_is_noop_at_layer4():
    path = _fresh_db()
    from hungry_hippa.db import Database

    _persist(path, _key_export())
    extract_from_store(Database(path), extractor=FakeExtractor())
    first = reconcile_store(Database(path))
    assert first.ok
    beliefs_n = _count(path, "beliefs")
    decisions_n = _count(path, "ingest_reconcile_decisions")
    turns_n = _count(path, "ingest_turns")
    _persist(path, _key_export())
    extract_from_store(Database(path), extractor=FakeExtractor())
    second = reconcile_store(Database(path))
    assert second.candidates_pending == 0, second
    assert second.candidates_processed == 0
    assert _count(path, "beliefs") == beliefs_n
    assert _count(path, "ingest_reconcile_decisions") == decisions_n
    assert _count(path, "ingest_turns") == turns_n
    return "re-import/re-extract of the same export is a no-op at Layer 4"


def check_existing_contradict_and_supersede_still_work():
    """Layer 4 must not change semantic.contradict / supersede behaviour."""
    path = _fresh_db()
    ctrl = _ctrl(path)
    a = ctrl.semantic.add_belief(
        "Printer A prints PLA best at 210C", kind="fact",
        source_class="user_explicit", confidence=0.9,
        identity=ctrl.identity, provenance=ctrl.provenance, channel=ctrl.channel,
    )
    b = ctrl.semantic.contradict(
        a["belief_id"], "Printer A prints PLA best at 230C",
        confidence=0.85, source_class="user_explicit",
        identity=ctrl.identity, provenance=ctrl.provenance, channel=ctrl.channel,
    )
    winner = ctrl.semantic.get_belief(a["belief_id"])
    loser = ctrl.semantic.get_belief(b["belief_id"])
    assert winner["status"] == "active"
    assert loser["status"] == "contradicted"
    assert b["belief_id"] in winner["contradictions"]
    old = ctrl.semantic.add_belief(
        "the staging area is near bay 2", kind="fact",
        source_class="agent_inference", confidence=0.5,
        identity=ctrl.identity, provenance=ctrl.provenance, channel=ctrl.channel,
    )
    new = ctrl.semantic.supersede(
        old["belief_id"], "the staging area moved to bay 5",
        reason="operator correction",
        identity=ctrl.identity, provenance=ctrl.provenance, channel=ctrl.channel,
    )
    assert new.get("belief_id")
    assert ctrl.semantic.get_belief(old["belief_id"])["status"] == "superseded"
    assert ctrl.semantic.get_belief(new["belief_id"])["status"] == "active"
    return "existing contradict/supersede APIs still resolve as before"


def check_dry_run_writes_nothing():
    path = _fresh_db()
    _add_established(path, "the crane slot is Tuesday")
    _add_candidate(path, "the crane slot is not Tuesday", evidence="counter")
    from hungry_hippa.db import Database

    db = Database(path)
    preview = preview_pending(db)
    assert preview.dry_run
    assert preview.counts["contradiction"] == 1
    assert _count(path, "ingest_reconcile_decisions") == 0
    assert _count(path, "ingest_reconcile_jobs") == 0
    old = [r for r in
           sqlite3.connect(path).execute("SELECT status FROM beliefs").fetchall()]
    result = reconcile_store(db, dry_run=True)
    assert result.dry_run and result.candidates_processed == 0
    assert _count(path, "ingest_reconcile_decisions") == 0
    return "dry-run classifies but writes no decisions"


def check_cli_dry_run_apply_and_refuse():
    workdir = tempfile.mkdtemp(prefix="hh_rec_cli_")
    db_path = os.path.join(workdir, "hungry_hippa.db")
    from hungry_hippa.db import Database

    Database(db_path)
    _add_established(db_path, "the crane slot is Tuesday")
    _add_candidate(db_path, "the crane slot is not Tuesday", evidence="counter")
    env = _cli_env(db_path)
    refused = _run_cli(["ingest", "reconcile"], env=env, cwd=workdir)
    assert refused.returncode == 1, refused.stdout
    assert "refusing to write" in refused.stdout
    dry = _run_cli(["ingest", "reconcile", "--dry-run"], env=env, cwd=workdir)
    assert dry.returncode == 0, (dry.stdout, dry.stderr)
    assert "Candidates pending: 1" in dry.stdout, dry.stdout
    assert "contradiction: 1" in dry.stdout
    assert "crane slot" not in dry.stdout
    assert _count(db_path, "ingest_reconcile_decisions") == 0
    applied = _run_cli(["ingest", "reconcile", "--apply"], env=env, cwd=workdir)
    assert applied.returncode == 0, (applied.stdout, applied.stderr)
    assert "contradiction: 1" in applied.stdout
    assert "both claims" in applied.stdout.lower() or "left open" in applied.stdout.lower()
    assert _count(db_path, "ingest_reconcile_decisions") == 1
    again = _run_cli(["ingest", "reconcile", "--apply"], env=env, cwd=workdir)
    assert again.returncode == 0
    assert "Candidates pending: 0" in again.stdout
    unset = dict(env)
    unset.pop("HUNGRY_HIPPA_DB", None)
    missing = _run_cli(["ingest", "reconcile", "--dry-run"], env=unset, cwd=workdir)
    assert missing.returncode == 1
    assert "HUNGRY_HIPPA_DB" in missing.stdout
    return "CLI dry-run/apply/refuse; claim text not printed; re-apply no-op"


def check_refuses_live_and_mcp_unchanged():
    for live in forbidden_db_paths():
        try:
            assert_extract_db_path(live)
            raise AssertionError(f"should refuse {live}")
        except ExtractRefused:
            pass
    previous = os.environ.get("HUNGRY_HIPPA_DB")
    os.environ.pop("HUNGRY_HIPPA_DB", None)
    try:
        try:
            require_extract_db_env()
            raise AssertionError("unset HUNGRY_HIPPA_DB should refuse")
        except ExtractRefused as e:
            assert "HUNGRY_HIPPA_DB" in str(e)
    finally:
        if previous is None:
            os.environ.pop("HUNGRY_HIPPA_DB", None)
        else:
            os.environ["HUNGRY_HIPPA_DB"] = previous
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
    chatgpt = (PACKAGE_DIR / "ingest" / "chatgpt.py").read_text(encoding="utf-8")
    hermes = (PACKAGE_DIR / "ingest" / "hermes.py").read_text(encoding="utf-8")
    init = (PACKAGE_DIR / "ingest" / "__init__.py").read_text(encoding="utf-8")
    assert "from .reconcile" not in chatgpt and "ingest.reconcile" not in chatgpt
    assert "from .reconcile" not in hermes and "ingest.reconcile" not in hermes
    assert "from .reconcile" not in init
    return "reconcile refuses live stores; MCP still six tools; parsers stay offline"


def check_all_seven_classes_apply_on_one_store():
    """One store, one of each class: report counts after --apply."""
    path = _fresh_db()
    key = _add_established(path, "the spare brass key is in the left workshop drawer",
                           evidence="key location")
    _add_established(path, "the crane slot is Tuesday", evidence="crane day")
    _add_established(path, "project x uses method a",
                     source_class="agent_inference", confidence=0.5, kind="belief",
                     evidence="method a")
    key_ev = list(_belief(path, key["belief_id"])["evidence_ids"])
    _add_candidate(path, "the spare brass key is in the left workshop drawer",
                   evidence_ids=key_ev)
    _add_candidate(path, "the spare brass key is in the left workshop drawer",
                   evidence="later turn repeats the key location",
                   source_ref={"kind": "ingest_turn", "source": "chatgpt",
                               "session_id": "s-re", "turn_id": "t-re"})
    _add_candidate(path, "the crane slot is not Tuesday",
                   evidence="counter",
                   source_ref={"kind": "ingest_turn", "source": "chatgpt",
                               "session_id": "s-c", "turn_id": "t-c"})
    _add_candidate(path, "the spare brass key is in the left workshop drawer behind the calipers",
                   evidence="refinement",
                   source_ref={"kind": "ingest_turn", "source": "chatgpt",
                               "session_id": "s-u", "turn_id": "t-u"})
    _add_candidate(path, "project x now uses method b",
                   evidence="replacement",
                   source_ref={"kind": "ingest_turn", "source": "chatgpt",
                               "session_id": "s-s", "turn_id": "t-s"})
    _add_candidate(path, "noted thanks", evidence="chit")
    _add_candidate(path, "the weather in paris is mild in april",
                   evidence="weather",
                   source_ref={"kind": "ingest_turn", "source": "chatgpt",
                               "session_id": "s-w", "turn_id": "t-w"})
    from hungry_hippa.db import Database

    dry = reconcile_store(Database(path), dry_run=True)
    applied = reconcile_store(Database(path))
    assert applied.candidates_processed == 7, applied
    assert all(applied.counts.get(c, 0) == 1 for c in CLASSES), applied.counts
    assert dry.candidates_pending == 7
    assert dry.counts == applied.counts
    assert _count(path, "ingest_turns") == 0  # we did not persist an export here
    return ("apply counts: " +
            ", ".join(f"{k}={applied.counts.get(k, 0)}" for k in CLASSES) +
            f"; dry pending={dry.candidates_pending}")


# --------------------------------------------------------------------------- runner

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

    check("v8_tables_on_fresh_db", check_v8_tables_on_fresh_db)
    check("classify_each_class_on_fixtures", check_classify_each_class_on_fixtures)
    check("property_classify_is_deterministic", check_property_classify_is_deterministic)
    check("property_contradiction_never_picks_a_winner",
          check_property_contradiction_never_picks_a_winner)
    check("duplicate_apply", check_duplicate_apply)
    check("reinforcement_apply", check_reinforcement_apply)
    check("contradiction_keeps_both_and_evidence",
          check_contradiction_keeps_both_and_evidence)
    check("update_keeps_both", check_update_keeps_both)
    check("supersession_unprotected", check_supersession_unprotected)
    check("protected_supersession_does_not_rewrite",
          check_protected_supersession_does_not_rewrite)
    check("low_confidence_and_irrelevant_stay_quarantined",
          check_low_confidence_and_irrelevant_stay_quarantined)
    check("idempotent_reapply_and_layer12_remain",
          check_idempotent_reapply_and_layer12_remain)
    check("reextract_same_export_is_noop_at_layer4",
          check_reextract_same_export_is_noop_at_layer4)
    check("existing_contradict_and_supersede_still_work",
          check_existing_contradict_and_supersede_still_work)
    check("dry_run_writes_nothing", check_dry_run_writes_nothing)
    check("cli_dry_run_apply_and_refuse", check_cli_dry_run_apply_and_refuse)
    check("refuses_live_and_mcp_unchanged", check_refuses_live_and_mcp_unchanged)
    check("all_seven_classes_apply_on_one_store",
          check_all_seven_classes_apply_on_one_store)
    return results


if __name__ == "__main__":
    results = run_all()
    passed = sum(1 for r in results if r["passed"])
    for r in results:
        print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['name']}: {r['detail']}")
    print(f"\n{passed}/{len(results)} passed")
    sys.exit(0 if passed == len(results) else 1)
