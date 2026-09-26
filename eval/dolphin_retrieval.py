#!/usr/bin/env python3
"""Retrieval-only probe against a local DolphinBench checkout.

This is NOT an official DolphinBench score. Official scoring requires an agent
to process every history message, then complete 600 tool-using tasks, with
cost, latency, and Azure gpt-5.6-sol grading. This probe never calls a model.

What it measures: after storing each persona's user messages as episodes in a
throwaway database, does hybrid recall (embeddings off) surface the source
sessions cited by the benchmark's load-bearing facts? Fact statements, expected
answers, and grading criteria are never written into the store. Queries are the
test requests only.

The dataset is read from DOLPHIN_ROOT (default: /home/djr/Work/dolphinbench).
Results contain ids and scores, not message text.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


PERSONAS = ("morgan", "alex", "riley")


def norm_id(value: Any) -> str:
    text = str(value).strip().strip("'\"")
    if text.isdigit():
        return text.zfill(6)
    return text


def score_retrieval(retrieved: Sequence[str], gold: Sequence[str], k: int) -> Dict[str, Any]:
    """Score source-session retrieval. Invented ids only; no benchmark text."""
    if not gold:
        raise ValueError("gold session ids are required")
    top = list(retrieved[:k])
    hits = [g for g in gold if g in top]
    first = None
    for index, item in enumerate(retrieved, start=1):
        if item in gold:
            first = index
            break
    return {
        "hit": bool(hits),
        "complete": len(hits) == len(set(gold)),
        "first_rank": first,
        "reciprocal_rank": (1.0 / first) if first else 0.0,
    }


def _self_check() -> None:
    empty = score_retrieval(["s2", "s9"], ["s1"], 5)
    assert empty["hit"] is False and empty["reciprocal_rank"] == 0.0
    hit = score_retrieval(["s9", "s1", "s2"], ["s1", "s2"], 2)
    assert hit["hit"] is True and hit["complete"] is False and hit["first_rank"] == 2
    complete = score_retrieval(["s1", "s2"], ["s2", "s1"], 5)
    assert complete["complete"] is True and complete["reciprocal_rank"] == 1.0
    try:
        score_retrieval(["s1"], [], 5)
    except ValueError:
        pass
    else:
        raise AssertionError("empty gold must be rejected")
    print("PASS dolphin retrieval scorer self-check")


def _load_yaml(path: Path) -> Any:
    import yaml  # local probe dependency; not a Hungry Hippa package dependency
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _sessions(root: Path, persona: str) -> List[Dict[str, str]]:
    doc = _load_yaml(root / "registry" / "personas" / persona / "life_sim.yaml")
    rows: List[Dict[str, str]] = []
    for session in doc.get("sessions") or []:
        sid = norm_id(session.get("id"))
        parts = []
        for message in session.get("messages") or []:
            if isinstance(message, str):
                parts.append(message)
            elif isinstance(message, dict) and isinstance(message.get("text"), str):
                parts.append(message["text"])
        text = "\n".join(parts).strip()
        if sid and text:
            rows.append({"id": sid, "text": text, "date": str(session.get("narrative_date") or "")})
    return rows


def _facts(root: Path, persona: str) -> Dict[str, List[str]]:
    doc = _load_yaml(root / "registry" / "personas" / persona / "facts.yaml")
    out: Dict[str, List[str]] = {}
    for fact in doc.get("facts") or []:
        out[str(fact.get("id"))] = [norm_id(s) for s in (fact.get("source_session_ids") or [])]
    return out


def _tests(root: Path, persona: str) -> List[Dict[str, Any]]:
    folder = root / "tests" / persona
    rows = []
    for path in sorted(folder.glob("*.yaml")):
        doc = _load_yaml(path)
        request = doc.get("test")
        if not isinstance(request, str) or not request.strip():
            continue
        rows.append({
            "id": str(doc.get("id") or path.stem),
            "request": request.strip(),
            "fact_ids": [str(x) for x in (doc.get("load_bearing_facts") or [])],
        })
    return rows


def _overlap(query: str, texts: Sequence[str]) -> bool:
    tokens = {t.lower() for t in query.split() if len(t) > 3}
    blob = " ".join(texts).lower()
    return any(token in blob for token in tokens)


def _git(path: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def run_persona(root: Path, persona: str, *, k: int) -> Dict[str, Any]:
    from hungry_hippa.config import load_config
    from hungry_hippa.controller import MemoryController

    sessions = _sessions(root, persona)
    facts = _facts(root, persona)
    tests = _tests(root, persona)
    by_id = {row["id"]: row["text"] for row in sessions}

    tmp = tempfile.mkdtemp(prefix=f"hh_dolphin_{persona}_")
    db_path = os.path.join(tmp, "hungry_hippa.db")
    cfg = load_config()
    cfg["retrieval"]["vectors_enabled"] = False
    cfg["manager"] = {"enabled": False}
    cfg["consolidation"]["on_session_end"] = False
    ctrl = MemoryController(cfg, db_path=db_path)
    ctrl.bind_session(session_id=f"dolphin-{persona}", platform="eval")

    started = time.perf_counter()
    episode_to_session: Dict[str, str] = {}
    for row in sessions:
        saved = ctrl.remember_episode(
            context=row["text"], project=persona, outcome="success", embed=False)
        episode_to_session[saved["episode_id"]] = row["id"]
    ingest_s = time.perf_counter() - started

    cases = []
    latencies = []
    for test in tests:
        gold: List[str] = []
        for fact_id in test["fact_ids"]:
            for sid in facts.get(fact_id, []):
                if sid not in gold:
                    gold.append(sid)
        if not gold:
            cases.append({"id": test["id"], "skipped": "no_load_bearing_source"})
            continue
        t0 = time.perf_counter()
        recalled = ctrl.recall(test["request"], limit=k)
        latencies.append((time.perf_counter() - t0) * 1000.0)
        retrieved = []
        for item in recalled.get("items") or []:
            eid = item.get("episode_id")
            if eid and eid in episode_to_session:
                sid = episode_to_session[eid]
                if sid not in retrieved:
                    retrieved.append(sid)
        top = retrieved[:k]
        scored = score_retrieval(top, gold, k)
        source_texts = [by_id[sid] for sid in gold if sid in by_id]
        gold_set = set(gold)
        false_positives = [sid for sid in top if sid not in gold_set]
        missed_sessions = [sid for sid in gold if sid not in top]
        missed_facts = []
        hit_facts = []
        for fact_id in test["fact_ids"]:
            sources = facts.get(fact_id) or []
            if sources and any(sid in top for sid in sources):
                hit_facts.append(fact_id)
            else:
                missed_facts.append(fact_id)
        relevant = len([sid for sid in top if sid in gold_set])
        cases.append({
            "id": test["id"],
            "request": test["request"],
            "fact_ids": test["fact_ids"],
            "gold_session_ids": gold,
            "retrieved_session_ids": top,
            "missed_session_ids": missed_sessions,
            "false_positive_session_ids": false_positives,
            "missed_fact_ids": missed_facts,
            "hit_fact_ids": hit_facts,
            "gold_sessions": len(gold),
            "retrieved_sessions": len(top),
            "precision_at_k": round(relevant / len(top), 4) if top else 0.0,
            "hit_at_k": scored["hit"],
            "complete_at_k": scored["complete"],
            "first_rank": scored["first_rank"],
            "reciprocal_rank": round(scored["reciprocal_rank"], 4),
            "latency_ms": round(latencies[-1], 3),
            "query_overlaps_source": _overlap(test["request"], source_texts),
            "missing_source_in_history": [sid for sid in gold if sid not in by_id],
        })

    scored_cases = [c for c in cases if "hit_at_k" in c]
    n = len(scored_cases) or 1
    db_bytes = os.path.getsize(db_path)
    for suffix in ("-wal", "-shm"):
        side = db_path + suffix
        if os.path.exists(side):
            db_bytes += os.path.getsize(side)
    return {
        "persona": persona,
        "sessions_ingested": len(sessions),
        "tests": len(tests),
        "scored_tests": len(scored_cases),
        "ingest_seconds": round(ingest_s, 3),
        "db_bytes": db_bytes,
        "recall_ms_p50": round(statistics.median(latencies), 3) if latencies else None,
        "recall_ms_p95": round(sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)], 3) if latencies else None,
        "hit_at_k": round(sum(1 for c in scored_cases if c["hit_at_k"]) / n, 4),
        "complete_at_k": round(sum(1 for c in scored_cases if c["complete_at_k"]) / n, 4),
        "precision_at_k": round(sum(c["precision_at_k"] for c in scored_cases) / n, 4),
        "mrr": round(sum(c["reciprocal_rank"] for c in scored_cases) / n, 4),
        "facts": sum(len(c["fact_ids"]) for c in scored_cases),
        "facts_hit": sum(len(c["hit_fact_ids"]) for c in scored_cases),
        "facts_missed": sum(len(c["missed_fact_ids"]) for c in scored_cases),
        "false_positive_sessions": sum(len(c["false_positive_session_ids"]) for c in scored_cases),
        "gold_ids_missing_from_history": sum(len(c["missing_source_in_history"]) for c in scored_cases),
        "overlap_and_hit": sum(1 for c in scored_cases if c["hit_at_k"] and c["query_overlaps_source"]),
        "no_overlap_and_hit": sum(1 for c in scored_cases if c["hit_at_k"] and not c["query_overlaps_source"]),
        "no_overlap_tests": sum(1 for c in scored_cases if not c["query_overlaps_source"]),
        "failures": [c for c in scored_cases if not c["hit_at_k"]],
        "cases": cases,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Retrieval-only DolphinBench probe")
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--root", default=os.environ.get("DOLPHIN_ROOT", "/home/djr/Work/dolphinbench"))
    parser.add_argument("--persona", action="append", choices=PERSONAS)
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--output", default="")
    args = parser.parse_args(argv)
    if args.self_check:
        _self_check()
        return 0

    root = Path(args.root)
    if not (root / "registry" / "personas").is_dir():
        print(f"DolphinBench checkout not found at {root}", flush=True)
        return 2
    personas = args.persona or list(PERSONAS)
    report = {
        "label": "retrieval_probe_not_official_dolphinbench_accuracy",
        "ranking_modified": False,
        "embeddings": False,
        "dolphin_commit": _git(root),
        "embeddings": False,
        "k": args.k,
        "python": platform.python_version(),
        "cpu": platform.processor(),
        "personas": [],
    }
    for persona in personas:
        print(f"ingesting {persona}", flush=True)
        report["personas"].append(run_persona(root, persona, k=args.k))
        last = report["personas"][-1]
        print(
            f"{persona}: hit@{args.k}={last['hit_at_k']} precision@{args.k}={last['precision_at_k']} "
            f"complete@{args.k}={last['complete_at_k']} mrr={last['mrr']} "
            f"facts_missed={last['facts_missed']}/{last['facts']} "
            f"false_positive_sessions={last['false_positive_sessions']} "
            f"gold_missing={last['gold_ids_missing_from_history']} "
            f"ingest_s={last['ingest_seconds']} recall_p50_ms={last['recall_ms_p50']}",
            flush=True,
        )
    text = json.dumps(report, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
        print(f"wrote {args.output}", flush=True)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
