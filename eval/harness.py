#!/usr/bin/env python3
"""Hungry Hippa Memory Challenge — a reproducible evaluation harness.

What it does
------------
Runs ten scenarios twice: once with a **session-transcript-only agent** (the
"without Hungry Hippa" arm) and once with **Hungry Hippa** (the "with" arm). Both
arms use the *same deterministic reader*, so the only variable is where the
context came from.

What it deliberately is not
---------------------------
No LLM is involved. A live model would make the numbers unreproducible
(non-deterministic sampling, network dependency, cost) and this harness is meant
to be re-runnable by a stranger offline. Scenario answers are graded by exact
token matching on the assembled context, which is coarse but real. Anything that
needs a model to judge is reported under ``unsupported`` rather than estimated.

Run it:

    python eval/harness.py            # writes eval/results.json and eval/REPORT.md
    python eval/harness.py --stdout   # also print the summary table

Every scenario uses its own throwaway temporary database. The live
The operator's own database is never opened. Embeddings are disabled, so
nothing here talks to the network.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
import types
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

EVAL_DIR = Path(__file__).resolve().parent
REPO_DIR = EVAL_DIR.parent
PLUGIN_DIR = REPO_DIR / "src" / "hungry_hippa"   # src layout
FIXTURES = json.loads((EVAL_DIR / "fixtures.json").read_text(encoding="utf-8"))

HARNESS_NAME = "hungry-hippa-memory-challenge"
HARNESS_VERSION = "1.0"

# Scenario 10 growth points (episodes in the store).
GROWTH_POINTS = (100, 500, 2000)
GROWTH_LATENCY_RUNS = 5


# ------------------------------------------------------------------ plugin

def _import_plugin():
    if sys.modules.get("hungry_hippa") is not None and getattr(
        sys.modules["hungry_hippa"], "__file__", None
    ):
        return sys.modules["hungry_hippa"]
    pkg = types.ModuleType("hungry_hippa")
    pkg.__path__ = [str(PLUGIN_DIR)]
    pkg.__file__ = str(PLUGIN_DIR / "__init__.py")
    sys.modules["hungry_hippa"] = pkg
    spec = importlib.util.spec_from_file_location(
        "hungry_hippa", str(PLUGIN_DIR / "__init__.py"),
        submodule_search_locations=[str(PLUGIN_DIR)])
    mod = importlib.util.module_from_spec(spec)
    sys.modules["hungry_hippa"] = mod
    spec.loader.exec_module(mod)
    return mod


PLUGIN = _import_plugin()


def _temp_db() -> str:
    return os.path.join(tempfile.mkdtemp(prefix="hh_eval_"), "hungry_hippa.db")


def _db_bytes(path: str) -> int:
    total = 0
    for suffix in ("", "-wal", "-shm"):
        try:
            total += os.path.getsize(path + suffix)
        except OSError:
            pass
    return total


# ---------------------------------------------------------------- context

def _context(text: str, *, chars: Optional[int] = None, token_estimate: int = 0,
             items: int = 0, excluded: int = 0, latency_ms: float = 0.0,
             budget_chars: Optional[int] = None, extra: Optional[Dict] = None) -> Dict:
    return {
        "text": text,
        "chars": chars if chars is not None else len(text),
        "token_estimate": token_estimate,
        "items": items,
        "excluded": excluded,
        "latency_ms": round(latency_ms, 3),
        "budget_chars": budget_chars,
        **(extra or {}),
    }


class SessionReader:
    """The "without Hungry Hippa" arm.

    Models an agent that has nothing but the current session transcript: no
    persistent store, no ranking, no budget, no access policy, and no notion of
    supersession. When the session ends the transcript is gone — that is the
    whole point of the comparison.
    """

    name = "session-transcript-only"

    def __init__(self) -> None:
        self.transcript: List[str] = []

    def say(self, text: str) -> None:
        self.transcript.append(text)

    def end_session(self) -> None:
        self.transcript = []

    def fetch(self, question: str, max_chars: Optional[int] = None,
              limit: Optional[int] = None) -> Dict:
        # No retrieval, no ranking, no budget: everything the session saw.
        return _context("\n".join(self.transcript))


class HippaReader:
    """The "with Hungry Hippa" arm: the real runtime on a throwaway database."""

    name = "hungry-hippa"

    def __init__(self, db_path: str, *, actor: str = "primary",
                 session_id: str = "eval", untrusted: bool = False) -> None:
        from hungry_hippa.config import load_config
        from hungry_hippa.controller import MemoryController
        from hungry_hippa import trust as _trust

        cfg = load_config()
        cfg["retrieval"]["vectors_enabled"] = False
        self.cfg = cfg
        self.ctrl = MemoryController(cfg, db_path=db_path)
        # Trust comes from the channel, not from a name: the untrusted arm is the
        # MCP boundary without the owner token, so it is bound explicitly rather
        # than by passing actor="mcp-untrusted" and hoping the name is enforced.
        binding = (_trust.external_binding(actor) if untrusted
                   else _trust.local_binding(actor))
        self.ctrl.bind_session(session_id=session_id, platform="eval",
                               agent_context="primary", trust=binding)

    def fetch(self, question: str, max_chars: Optional[int] = None,
              limit: Optional[int] = None) -> Dict:
        started = time.perf_counter()
        pkg = self.ctrl.build_context(question, max_chars=max_chars, limit=limit,
                                      actor_id=self.ctrl.actor_id)
        elapsed = (time.perf_counter() - started) * 1000.0
        return _context(
            pkg.get("rendering", ""),
            token_estimate=pkg.get("token_estimate", 0),
            items=len(pkg.get("items", [])),
            excluded=len(pkg.get("excluded", [])),
            latency_ms=elapsed,
            budget_chars=pkg.get("budget_chars"),
        )


def grade(text: str, expect: List[str], forbid: List[str]) -> Dict[str, Any]:
    """Grade an assembled context by exact token match.

    Deliberately the same logic for both arms: the reader is the constant, the
    context source is the variable.
    """
    low = (text or "").lower()
    present_forbid = [f for f in forbid if f.lower() in low]
    found = next((e for e in expect if e.lower() in low), None)
    return {
        "answered": bool(found) or bool(present_forbid),
        "answer": found or (present_forbid[0] if present_forbid else ""),
        "correct": bool(found) and not present_forbid,
        "incorrect_memory": bool(present_forbid),
        "forbidden_in_context": present_forbid,
    }


def _arm(ctx: Dict, grade_result: Dict) -> Dict:
    return {
        "context_chars": ctx["chars"],
        "context_token_estimate": ctx["token_estimate"],
        "items": ctx["items"],
        "excluded": ctx["excluded"],
        "latency_ms": ctx["latency_ms"],
        "budget_chars": ctx.get("budget_chars"),
        **grade_result,
    }


# --------------------------------------------------------------- scenarios

def scenario_1_cross_session_recall() -> Dict[str, Any]:
    fact = FIXTURES["facts"][0]
    db = _temp_db()
    writer = HippaReader(db, session_id="s1")
    baseline = SessionReader()
    writer.ctrl.semantic.add_belief(fact["claim"], kind=fact["kind"],
                                    confidence=fact["confidence"],
                                    source_class=fact["source_class"])
    baseline.say(f"operator: {fact['claim']}")

    # session ends; the transcript is dropped, the database is not
    baseline.end_session()
    reader = HippaReader(db, session_id="s2")          # new session, same store
    with_ctx = reader.fetch(fact["question"])
    without_ctx = baseline.fetch(fact["question"])
    return {
        "id": 1,
        "name": "cross_session_factual_recall",
        "question": fact["question"],
        "with": _arm(with_ctx, grade(with_ctx["text"], fact["expect"], fact["forbid"])),
        "without": _arm(without_ctx, grade(without_ctx["text"], fact["expect"],
                                          fact["forbid"])),
        "metrics": {},
        "notes": ("Same deterministic reader; the only difference is that the "
                  "with-arm reopens the store in a new session."),
    }


def scenario_2_decision_rationale() -> Dict[str, Any]:
    d = FIXTURES["decision"]
    db = _temp_db()
    writer = HippaReader(db, session_id="s1")
    baseline = SessionReader()
    writer.ctrl.semantic.add_belief(d["claim"], kind="fact", confidence=0.9,
                                    source_class="user_explicit")
    writer.ctrl.remember_episode(context=d["claim"], decisions=d["claim"],
                                 result=d["rationale"], outcome="success",
                                 embed=False)
    baseline.say(f"operator: {d['claim']} because {d['rationale']}")

    baseline.end_session()
    reader = HippaReader(db, session_id="s2")
    with_ctx = reader.fetch(d["question"])
    without_ctx = baseline.fetch(d["question"])
    return {
        "id": 2,
        "name": "decision_and_rationale_recall",
        "question": d["question"],
        "with": _arm(with_ctx, grade(with_ctx["text"], d["expect"], d["forbid"])),
        "without": _arm(without_ctx, grade(without_ctx["text"], d["expect"],
                                          d["forbid"])),
        "metrics": {},
        "notes": "Measures whether the rationale, not just the decision, comes back.",
    }


def scenario_3_avoid_failed_attempt() -> Dict[str, Any]:
    f = FIXTURES["failed_attempt"]
    db = _temp_db()
    writer = HippaReader(db, session_id="s1")
    baseline = SessionReader()
    writer.ctrl.remember_episode(context=f["context"], result=f["result"],
                                 outcome=f["outcome"], project=f["project"],
                                 importance=0.9, embed=False)
    baseline.say(f"operator: we tried {f['context']}; {f['result']}")

    baseline.end_session()
    reader = HippaReader(db, session_id="s2")
    with_ctx = reader.fetch(f["proposal"])
    without_ctx = baseline.fetch(f["proposal"])

    def repeated(ctx: Dict) -> Dict[str, Any]:
        """Would the agent repeat the failed approach? It repeats it unless the
        prior failure is in front of it."""
        low = ctx["text"].lower()
        aware = any(t in low for t in f["failure_tokens"])
        return {"aware_of_failure": aware, "repeated_failed_attempt": not aware}

    return {
        "id": 3,
        "name": "avoid_previously_failed_solution",
        "question": f["proposal"],
        "with": _arm(with_ctx, {**grade(with_ctx["text"], f["expect"], f["forbid"]),
                                **repeated(with_ctx)}),
        "without": _arm(without_ctx, {**grade(without_ctx["text"], f["expect"],
                                              f["forbid"]),
                                      **repeated(without_ctx)}),
        "metrics": {},
        "notes": ("'repeated_failed_attempt' is derived: the prior failure is "
                  "absent from the context, so the agent has nothing to stop it."),
    }


def scenario_4_superseded_information() -> Dict[str, Any]:
    s = FIXTURES["supersession"]
    db = _temp_db()
    writer = HippaReader(db, session_id="s1")
    baseline = SessionReader()
    b1 = writer.ctrl.semantic.add_belief(s["old_claim"], kind="fact", confidence=0.8,
                                         source_class="document")
    writer.ctrl.semantic.supersede(b1["belief_id"], s["new_claim"],
                                   reason=s["reason"], source_class="user_explicit")
    # the baseline sees both statements in order and has no way to know which wins
    baseline.say(f"operator: {s['old_claim']}")
    baseline.say(f"operator: {s['new_claim']}")

    reader = HippaReader(db, session_id="s2")
    with_ctx = reader.fetch(s["question"])
    without_ctx = baseline.fetch(s["question"])
    return {
        "id": 4,
        "name": "resolve_superseded_information",
        "question": s["question"],
        "with": _arm(with_ctx, grade(with_ctx["text"], s["expect"], s["forbid"])),
        "without": _arm(without_ctx, grade(without_ctx["text"], s["expect"],
                                          s["forbid"])),
        "metrics": {},
        "notes": ("The baseline holds both statements and no supersession state, "
                  "so the stale token remains in its context."),
    }


def scenario_5_fixed_token_budget() -> Dict[str, Any]:
    b = FIXTURES["budget"]
    budget = 400
    db = _temp_db()
    writer = HippaReader(db, session_id="s1")
    baseline = SessionReader()
    for i in range(40):
        chatter = f"Project A log entry {i}: " + ("detail " * 30)
        writer.ctrl.remember_episode(context=chatter, project="Project A",
                                     outcome="success", embed=False)
        baseline.say(chatter)
    for step in b["chatter"]:
        writer.ctrl.remember_episode(context=step, project="Project A",
                                     outcome="success", embed=False)
        baseline.say(step)

    reader = HippaReader(db, session_id="s2")
    with_ctx = reader.fetch(b["question"], max_chars=budget)
    without_ctx = baseline.fetch(b["question"])   # no budget concept at all
    return {
        "id": 5,
        "name": "retrieval_within_a_fixed_budget",
        "question": b["question"],
        "with": _arm(with_ctx, {**grade(with_ctx["text"], b["expect"], []),
                                "budget_respected": with_ctx["chars"] <= budget}),
        "without": _arm(without_ctx, {**grade(without_ctx["text"], b["expect"], []),
                                      "budget_respected": False}),
        "metrics": {"budget_chars": budget},
        "notes": ("The baseline has no budget mechanism, so it supplies the whole "
                  "session transcript; the with-arm is capped by the compiler."),
    }


def scenario_6_cross_agent_portability() -> Dict[str, Any]:
    fact = FIXTURES["facts"][1]
    db = _temp_db()
    agent_a = HippaReader(db, session_id="agent-a")
    agent_a.ctrl.semantic.add_belief(fact["claim"], kind=fact["kind"],
                                     confidence=fact["confidence"],
                                     source_class=fact["source_class"])
    # a second, separately constructed client process on the same store
    agent_b = HippaReader(db, session_id="agent-b")
    with_ctx = agent_b.fetch(fact["question"])
    baseline = SessionReader()   # no store to share at all
    without_ctx = baseline.fetch(fact["question"])
    return {
        "id": 6,
        "name": "cross_agent_memory_portability",
        "question": fact["question"],
        "with": _arm(with_ctx, grade(with_ctx["text"], fact["expect"], fact["forbid"])),
        "without": _arm(without_ctx, grade(without_ctx["text"], fact["expect"],
                                          fact["forbid"])),
        "metrics": {"separate_controller_instances": 2},
        "notes": ("Two independent MemoryController instances on the same SQLite "
                  "file, i.e. two client processes. Cross-agent sharing for the "
                  "owner actor only; see scenario 9 for the untrusted case."),
    }


def scenario_7_user_directed_forgetting() -> Dict[str, Any]:
    f = FIXTURES["forgetting"]
    db = _temp_db()
    writer = HippaReader(db, session_id="s1")
    baseline = SessionReader()
    belief = writer.ctrl.semantic.add_belief(f["claim"], kind="fact",
                                             confidence=0.9,
                                             source_class="user_explicit")
    baseline.say(f"operator: {f['claim']}")

    reader = HippaReader(db, session_id="s2")
    before = reader.fetch(f["question"])
    before_result = grade(before["text"], f["expect"], f["forbid"])
    # the operator asks for it to be forgotten
    forgotten = reader.ctrl.forget("belief", belief["belief_id"], mode="archival",
                                   reason="operator request")
    after = reader.fetch(f["question"])
    after_result = grade(after["text"], f["expect"], f["forbid"])
    row_still_there = reader.ctrl.semantic.get_belief(belief["belief_id"]) is not None
    forget_effective = not after_result["answered"]

    # the baseline has no forget operation: the statement stays in the transcript
    baseline_before = baseline.fetch(f["question"])
    baseline_after = baseline.fetch(f["question"])
    baseline_effective = not grade(baseline_after["text"], f["expect"],
                                   f["forbid"])["answered"]

    return {
        "id": 7,
        "name": "user_directed_forgetting",
        "question": f["question"],
        "with": {
            "recalled_before_forget": before_result["correct"],
            "forget_effective": forget_effective,
            "archived": bool(forgotten.get("archived")),
            "row_retained_for_rollback": row_still_there,
            "correct": before_result["correct"] and forget_effective,
            "incorrect_memory": False,
            "context_chars": after["chars"],
            "items": after["items"],
            "excluded": after["excluded"],
            "latency_ms": after["latency_ms"],
            "before_context_chars": before["chars"],
        },
        "without": {
            "recalled_before_forget": grade(baseline_before["text"], f["expect"],
                                           f["forbid"])["correct"],
            "forget_effective": baseline_effective,
            "archived": False,
            "row_retained_for_rollback": None,
            "correct": False,
            "incorrect_memory": False,
            "context_chars": baseline_after["chars"],
            "items": 0,
            "excluded": 0,
            "latency_ms": 0.0,
        },
        "metrics": {},
        "notes": ("Archival is reversible: the row survives with status 'archived'. "
                  "The baseline has no forgetting operation, so in-context text "
                  "simply stays — 'correct' is false because the operator's intent "
                  "cannot be carried out."),
    }


def scenario_8_poison_resistance() -> Dict[str, Any]:
    p = FIXTURES["poison"]
    db = _temp_db()
    from hungry_hippa.policy import is_owner

    # untrusted = the MCP boundary without the owner token (channel-resolved),
    # not a caller that merely names itself "mcp-untrusted".
    poisoned = HippaReader(db, actor="mcp-untrusted", session_id="untrusted",
                           untrusted=True)
    result = poisoned.ctrl.semantic.add_belief(p["content"], kind="fact",
                                               confidence=0.9,
                                               source_class="user_explicit",
                                               actor_id="mcp-untrusted")
    owner = HippaReader(db, session_id="owner")
    with_ctx = owner.fetch(p["question"])
    leaked = any(t.lower() in with_ctx["text"].lower()
                 for t in p["forbidden_answer_tokens"])
    baseline = SessionReader()   # the poisoned text never entered its transcript
    without_ctx = baseline.fetch(p["question"])
    return {
        "id": 8,
        "name": "resistance_to_poisoned_memory",
        "question": p["question"],
        "with": _arm(with_ctx, {"poison_leaked": leaked, "correct": not leaked,
                                "answered": False, "answer": "",
                                "incorrect_memory": leaked}),
        "without": {
            "supported": False,
            "reason": ("the baseline has no persistent store, so there is nothing "
                       "an untrusted writer could poison and no result to compare"),
        },
        "metrics": {"write_quarantined": bool(result.get("quarantined"))},
        "notes": ("An untrusted actor's write is quarantined and never reaches the "
                  "owner's context. The baseline arm is marked unsupported rather "
                  "than scored zero."),
    }


def scenario_9_unauthorized_retrieval() -> Dict[str, Any]:
    prot = FIXTURES["protected"]
    db = _temp_db()
    owner = HippaReader(db, session_id="owner")
    owner.ctrl.semantic.add_belief(prot["claim"], kind="fact", confidence=0.9,
                                   source_class="user_explicit",
                                   sensitivity=prot["sensitivity"])
    untrusted = HippaReader(db, actor="mcp-untrusted", session_id="untrusted",
                            untrusted=True)
    denied_ctx = untrusted.fetch(prot["question"])
    owner_ctx = owner.fetch(prot["question"])

    deny_result = grade(denied_ctx["text"], prot["expect"], prot["forbid"])
    owner_result = grade(owner_ctx["text"], prot["expect"], prot["forbid"])
    denied_correctly = not deny_result["answered"] and not deny_result["incorrect_memory"]
    return {
        "id": 9,
        "name": "unauthorized_retrieval_attempt",
        "question": prot["question"],
        "with": {
            "denial": _arm(denied_ctx, deny_result),
            "owner_read": _arm(owner_ctx, owner_result),
            "denial_correct": denied_correctly,
            "owner_read_correct": owner_result["correct"],
            "policy": "actor + policy checks",
            # scored as: the untrusted read is denied AND the owner can still read it
            "correct": bool(denied_correctly and owner_result["correct"]),
            "incorrect_memory": bool(deny_result["incorrect_memory"]),
            "context_chars": denied_ctx["chars"],
            "items": denied_ctx["items"],
            "excluded": denied_ctx["excluded"],
            "latency_ms": denied_ctx["latency_ms"],
        },
        "without": {
            "supported": False,
            "reason": ("the baseline has no access control, so denial accuracy is "
                       "not measurable for it"),
        },
        "metrics": {
            "sensitivity": prot["sensitivity"],
            "denial_accuracy": 1.0 if denied_correctly else 0.0,
            "owner_read_accuracy": 1.0 if owner_result["correct"] else 0.0,
        },
        "notes": "Sensitivity is a read-policy label, not encryption.",
    }


def scenario_10_growth_and_latency() -> Dict[str, Any]:
    g = FIXTURES["growth"]
    topics = g["topics"]
    points: List[Dict[str, Any]] = []
    for n in GROWTH_POINTS:
        db = _temp_db()
        reader = HippaReader(db, session_id="growth")
        baseline = SessionReader()
        started = time.perf_counter()
        for i in range(n):
            text = f"{topics[i % len(topics)]} (record {i})"
            reader.ctrl.remember_episode(context=text, project=f"Project {chr(65 + i % 2)}",
                                         outcome="success", embed=False)
            baseline.say(text)
        write_ms = (time.perf_counter() - started) * 1000.0
        reader.ctrl.semantic.add_belief(f"the fixture jig torque value is {g['expect'][0]}",
                                        kind="fact", confidence=0.9,
                                        source_class="document")
        baseline.say(f"the fixture jig torque value is {g['expect'][0]}")

        latencies = []
        for _ in range(GROWTH_LATENCY_RUNS):
            ctx = reader.fetch(g["question"])
            latencies.append(ctx["latency_ms"])
        with_ctx = reader.fetch(g["question"])
        without_ctx = baseline.fetch(g["question"])
        points.append({
            "episodes": n,
            "db_bytes": _db_bytes(db),
            "bytes_per_episode": round(_db_bytes(db) / max(1, n), 1),
            "ingest_ms_total": round(write_ms, 1),
            "ingest_ms_per_episode": round(write_ms / max(1, n), 3),
            "retrieval_latency_ms_median": round(statistics.median(latencies), 3),
            "retrieval_latency_ms_p95": round(sorted(latencies)[-1], 3),
            "with_context_chars": with_ctx["chars"],
            "without_context_chars": without_ctx["chars"],
            "with": _arm(with_ctx, grade(with_ctx["text"], g["expect"], [])),
            "without": _arm(without_ctx, grade(without_ctx["text"], g["expect"], [])),
        })
    return {
        "id": 10,
        "name": "performance_as_storage_grows",
        "question": g["question"],
        "points": points,
        "metrics": {
            "growth_points": list(GROWTH_POINTS),
            "retrieval_latency_ms_median": [p["retrieval_latency_ms_median"] for p in points],
            "db_bytes": [p["db_bytes"] for p in points],
            "with_context_chars": [p["with_context_chars"] for p in points],
            "without_context_chars": [p["without_context_chars"] for p in points],
        },
        "notes": ("Latency is the median of "
                  f"{GROWTH_LATENCY_RUNS} build_context calls on the same store; "
                  "ingest is single-threaded with embeddings disabled. The "
                  "baseline's context grows with the session because it has no "
                  "budget."),
    }


SCENARIOS = (
    scenario_1_cross_session_recall,
    scenario_2_decision_rationale,
    scenario_3_avoid_failed_attempt,
    scenario_4_superseded_information,
    scenario_5_fixed_token_budget,
    scenario_6_cross_agent_portability,
    scenario_7_user_directed_forgetting,
    scenario_8_poison_resistance,
    scenario_9_unauthorized_retrieval,
    scenario_10_growth_and_latency,
)


UNSUPPORTED = [
    {
        "metric": "natural-language answer quality",
        "reason": ("grading here is exact token matching on the assembled context; "
                   "judging whether an answer is well phrased or subtly correct "
                   "needs a model to judge, which would make the harness "
                   "non-deterministic and network-dependent"),
    },
    {
        "metric": "semantic-equivalence recall (paraphrase matching)",
        "reason": ("would need an embedding model or an LLM judge; vectors are "
                   "disabled so the run stays offline and repeatable"),
    },
    {
        "metric": "embedding/vector recall quality",
        "reason": ("local embeddings require an Ollama server; enabling them would "
                   "make results depend on a model version, so the harness pins "
                   "vectors off and reports keyword+graph recall only"),
    },
    {
        "metric": "baseline poison resistance (scenario 8, without arm)",
        "reason": ("the baseline has no persistent store, so it cannot be poisoned "
                   "and there is no comparable result — scored unsupported, not zero"),
    },
    {
        "metric": "baseline permission-denial accuracy (scenario 9, without arm)",
        "reason": ("the baseline has no access control, so denial accuracy is "
                   "undefined for it — scored unsupported, not zero"),
    },
    {
        "metric": "multi-user / cross-tenant isolation",
        "reason": ("not implemented in the runtime, so there is nothing to measure"),
    },
]


# ------------------------------------------------------------------ output

def _git(*args: str) -> str:
    try:
        out = subprocess.run(["git", *args], cwd=str(REPO_DIR),
                             capture_output=True, text=True, timeout=20)
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def _aggregate(scenarios: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate only where both arms are actually comparable.

    "Comparable" means both arms were graded on the same question with the same
    reader. Scenarios whose baseline arm is unsupported (no store to poison, no
    access control to test) are reported separately instead of being scored as
    zero for the baseline.
    """
    gradable = [s for s in scenarios if "correct" in s.get("with", {})]
    comparable = [s for s in gradable if "correct" in s.get("without", {})]
    with_only = [s for s in gradable if "correct" not in s.get("without", {})]

    def rate(items, arm, key="correct"):
        if not items:
            return None
        return round(sum(1 for s in items if s[arm].get(key)) / len(items), 3)

    w_chars = [s["with"]["context_chars"] for s in comparable]
    wo_chars = [s["without"]["context_chars"] for s in comparable]
    w_lat = [s["with"]["latency_ms"] for s in comparable if s["with"].get("latency_ms")]
    denial = [s["metrics"]["denial_accuracy"] for s in scenarios
              if "denial_accuracy" in s.get("metrics", {})]
    growth = next((s for s in scenarios if "points" in s), None)
    return {
        "scored_scenarios": len(gradable),
        "comparable_scenarios": [s["id"] for s in comparable],
        "with_arm_only_scenarios": [s["id"] for s in with_only],
        "unsupported_baseline_scenarios": [s["id"] for s in gradable
                                           if s.get("without", {}).get("supported") is False],
        "not_scored_scenarios": [s["id"] for s in scenarios if s not in gradable],
        "recall_rate": {
            "scope": "scenarios comparable on both arms",
            "with_hungry_hippa": rate(comparable, "with"),
            "without": rate(comparable, "without"),
        },
        "incorrect_memory_rate": {
            "scope": "scenarios comparable on both arms",
            "with_hungry_hippa": rate(comparable, "with", "incorrect_memory"),
            "without": rate(comparable, "without", "incorrect_memory"),
        },
        "context_chars_median": {
            "with_hungry_hippa": round(statistics.median(w_chars), 1) if w_chars else None,
            "without": round(statistics.median(wo_chars), 1) if wo_chars else None,
        },
        "retrieval_latency_ms_median": round(statistics.median(w_lat), 3) if w_lat else None,
        "permission_denial_accuracy": (round(sum(denial) / len(denial), 3)
                                       if denial else None),
        "repeat_failed_attempt_rate": {
            "with_hungry_hippa": rate([s for s in scenarios if s["id"] == 3],
                                      "with", "repeated_failed_attempt"),
            "without": rate([s for s in scenarios if s["id"] == 3],
                            "without", "repeated_failed_attempt"),
        },
        "growth": ({
            "episodes": [p["episodes"] for p in growth["points"]],
            "db_bytes": [p["db_bytes"] for p in growth["points"]],
            "retrieval_latency_ms_median": [p["retrieval_latency_ms_median"]
                                            for p in growth["points"]],
        } if growth else None),
    }


def _report(results: Dict[str, Any]) -> str:
    agg = results["aggregate"]
    lines: List[str] = []
    add = lines.append

    add("# Hungry Hippa Memory Challenge — results")
    add("")
    add(f"Generated by `eval/harness.py` ({results['harness_version']}) at "
        f"`{results['generated_at']}`.")
    add("")
    add("This file is generated from `eval/results.json`, which was produced by an "
        "actual run. Nothing in it is estimated by hand.")
    add("")
    add("## Run metadata")
    add("")
    add("| Field | Value |")
    add("|---|---|")
    add(f"| Commit | `{results['git_rev'] or 'unknown'}`"
        f"{' (uncommitted files present at run time)' if results['git_dirty'] else ''} |")
    add(f"| Python | {results['python']} |")
    add(f"| Platform | {results['platform']} |")
    add(f"| Controller | {results['controller']} |")
    add(f"| Embeddings | {results['embedding']} |")
    add(f"| Arms | with Hungry Hippa vs {results['baseline']} |")
    add(f"| Fixtures | `{results['fixtures']}` (no personal information) |")
    add("")
    add("## Aggregate")
    add("")
    add("| Metric | With Hungry Hippa | Without (session transcript only) |")
    add("|---|---|---|")
    add(f"| Recall rate (scenarios comparable on both arms) | "
        f"{agg['recall_rate']['with_hungry_hippa']} | {agg['recall_rate']['without']} |")
    add(f"| Incorrect-memory rate | {agg['incorrect_memory_rate']['with_hungry_hippa']} | "
        f"{agg['incorrect_memory_rate']['without']} |")
    add(f"| Repeated-failed-attempt rate (scenario 3) | "
        f"{agg['repeat_failed_attempt_rate']['with_hungry_hippa']} | "
        f"{agg['repeat_failed_attempt_rate']['without']} |")
    add(f"| Median context supplied (chars) | {agg['context_chars_median']['with_hungry_hippa']} | "
        f"{agg['context_chars_median']['without']} |")
    add(f"| Retrieval latency (median ms) | {agg['retrieval_latency_ms_median']} | n/a (no retrieval) |")
    add(f"| Permission-denial accuracy | {agg['permission_denial_accuracy']} | "
        f"unsupported |")
    if agg.get("growth"):
        g = agg["growth"]
        lat = " / ".join(str(v) for v in g["retrieval_latency_ms_median"])
        eps = " / ".join(str(v) for v in g["episodes"])
        add(f"| Retrieval latency across growth points | {lat} ms at {eps} episodes | n/a |")
    add("")
    add(f"Scenarios graded: {agg['scored_scenarios']} of {len(results['scenarios'])}.")
    add(f"Comparable on both arms: {agg['comparable_scenarios']}.")
    add(f"With-arm only (baseline not comparable): {agg['with_arm_only_scenarios']}.")
    add(f"Baseline marked unsupported: {agg['unsupported_baseline_scenarios']}.")
    add("")
    add("Rates are computed over the comparable set only. A baseline arm that is "
        "marked unsupported is never counted as a zero.")
    add("")
    add("## Scenarios")
    add("")
    for s in results["scenarios"]:
        add(f"### {s['id']}. {s['name'].replace('_', ' ')}")
        add("")
        if s.get("question"):
            add(f"Question: `{s['question']}`")
            add("")
        w = s.get("with", {})
        if "points" in s:
            add("| Episodes | DB bytes | Ingest ms/ep | Retrieval ms (median) | "
                "Context chars (with) | Context chars (without) |")
            add("|---|---|---|---|---|---|")
            for p in s["points"]:
                add(f"| {p['episodes']} | {p['db_bytes']} | {p['ingest_ms_per_episode']} | "
                    f"{p['retrieval_latency_ms_median']} | {p['with_context_chars']} | "
                    f"{p['without_context_chars']} |")
        else:
            add("| Arm | Correct | Incorrect memory | Context chars | Items | Excluded | Latency ms |")
            add("|---|---|---|---|---|---|---|")
            for arm_name in ("with", "without"):
                arm = s.get(arm_name, {})
                if arm.get("supported") is False:
                    add(f"| {arm_name} | unsupported | unsupported | – | – | – | – |")
                    continue
                if "correct" not in arm and "forget_effective" not in arm:
                    add(f"| {arm_name} | – | – | – | – | – | – |")
                    continue
                add(f"| {arm_name} | {arm.get('correct')} | {arm.get('incorrect_memory')} | "
                    f"{arm.get('context_chars')} | {arm.get('items')} | "
                    f"{arm.get('excluded')} | {arm.get('latency_ms')} |")
        if s.get("metrics"):
            add("")
            add(f"Metrics: `{json.dumps(s['metrics'])}`")
        if s.get("notes"):
            add("")
            add(s["notes"])
        if s.get("without", {}).get("supported") is False:
            add("")
            add(f"Without-arm: unsupported — {s['without']['reason']}")
        add("")
    add("## Metrics that could not be measured")
    add("")
    for item in results["unsupported"]:
        add(f"- **{item['metric']}** — {item['reason']}")
    add("")
    add("## How to reproduce")
    add("")
    add("```bash")
    add("python eval/harness.py          # rewrites eval/results.json and eval/REPORT.md")
    add("```")
    add("")
    add("Every scenario builds its own throwaway database under the system temp "
        "directory. The harness never opens the operator's database, needs "
        "no network, and uses no LLM.")
    add("")
    return "\n".join(lines) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stdout", action="store_true",
                        help="print a one-line-per-scenario summary")
    parser.add_argument("--out", default=str(EVAL_DIR / "results.json"))
    parser.add_argument("--report", default=str(EVAL_DIR / "REPORT.md"))
    args = parser.parse_args(argv)

    started = time.perf_counter()
    scenarios = []
    for fn in SCENARIOS:
        t0 = time.perf_counter()
        result = fn()
        result["wall_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
        scenarios.append(result)

    results = {
        "harness": HARNESS_NAME,
        "harness_version": HARNESS_VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_rev": _git("rev-parse", "HEAD"),
        "git_dirty": bool(_git("status", "--porcelain")),
        "git_rev_note": (
            "git_rev is the commit the measurement ran against, recorded from a clean "
            "tree. This file is normally committed afterwards, so the commit that "
            "contains it is one commit newer; that commit changes only eval/REPORT.md "
            "and eval/results.json, so the measured code is exactly git_rev. Check with "
            "`git show --stat <containing commit>`."
        ),
        "python": sys.version.split()[0],
        "platform": f"{platform.system()} {platform.release()}",
        "controller": "deterministic Python controller (no LLM judge)",
        "embedding": "disabled (offline, repeatable)",
        "baseline": "session-transcript-only agent (no memory runtime)",
        "fixtures": "eval/fixtures.json",
        "wall_ms": round((time.perf_counter() - started) * 1000.0, 1),
        "unsupported": UNSUPPORTED,
        "scenarios": scenarios,
    }
    results["aggregate"] = _aggregate(scenarios)

    Path(args.out).write_text(json.dumps(results, indent=2, default=str) + "\n",
                              encoding="utf-8")
    Path(args.report).write_text(_report(results), encoding="utf-8")

    if args.stdout:
        agg = results["aggregate"]
        print(f"{HARNESS_NAME} {HARNESS_VERSION} @ {results['git_rev'][:8]}")
        for s in scenarios:
            if "points" in s:
                detail = ", ".join(f"n={p['episodes']}:{p['retrieval_latency_ms_median']}ms"
                                   for p in s["points"])
            else:
                detail = (f"with={s['with'].get('correct')} "
                          f"without={s['without'].get('correct', 'unsupported')}")
            print(f"  {s['id']:>2}. {s['name']:<38} {detail}")
        print(f"  recall rate with={agg['recall_rate']['with_hungry_hippa']} "
              f"without={agg['recall_rate']['without']}")
        print(f"  wrote {args.out} and {args.report} in {results['wall_ms']} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
