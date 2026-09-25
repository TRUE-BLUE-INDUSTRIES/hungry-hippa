"""Slice 5 / Layer 4: reconcile extract candidates against existing memories.

Extraction writes quarantined hypotheses. This layer classifies each one
against memories already in the store:

    duplicate | reinforcement | contradiction | update | supersession |
    low-confidence | irrelevant

Contradictions are never silently resolved: both claims and their evidence
stay. Re-running reconcile (or re-extracting the same export) is a no-op.
Layer 1 archives and Layer 2 turns are never deleted.

This module is not imported by ``hungry_hippa.ingest`` package init. Parsers
stay stdlib-only and offline. The MCP surface is unchanged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .. import db as _db
from ..config import load_config
from ..graph import KnowledgeGraph
from ..semantic import SemanticMemory, protection_reason
from .extract import (
    ExtractRefused,
    assert_extract_db_path,
    forbidden_db_paths,
    require_extract_db_env,
)

ACTOR_ID = "ingest-reconcile"

CLASSES = (
    "duplicate",
    "reinforcement",
    "contradiction",
    "update",
    "supersession",
    "low-confidence",
    "irrelevant",
)

CLASS_TO_COUNT_FIELD = {
    "duplicate": "duplicate_n",
    "reinforcement": "reinforcement_n",
    "contradiction": "contradiction_n",
    "update": "update_n",
    "supersession": "supersession_n",
    "low-confidence": "low_confidence_n",
    "irrelevant": "irrelevant_n",
}

_STOPWORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "in", "on", "at", "of", "to", "for", "and", "or", "with", "from",
    "that", "this", "it", "its", "as", "by", "into", "for",
})
_NEGATIONS = (
    " no longer ", " not ", " never ", " doesn't ", " does not ",
    " won't ", " cannot ", " can't ", " stopped ", " isn't ", " aren't ",
    " wasn't ", " weren't ", " no ",
)
_REPLACEMENT_CUES = (
    " now ", " instead ", " replaced ", " moved to ", " switched to ",
    " from now on ", " currently ", " replaced by ", " no longer uses ",
)
_TOKEN_RE = re.compile(r"[a-z0-9']+")
LOW_CONFIDENCE = 0.25
MIN_CONTENT_TOKENS = 3
EQUIV_SIM = 0.92
REINFORCE_SIM = 0.75
CONTRADICT_SIM = 0.40
SUPERSEDE_SIM = 0.35
UPDATE_SIM = 0.50
IRRELEVANT_SIM = 0.18
GRAY_SIM = 0.40


@dataclass(frozen=True)
class MemoryView:
    """Synthetic or loaded belief used by the classifier."""
    belief_id: str
    claim: str
    status: str = "active"
    confidence: float = 0.5
    quarantined: bool = False
    evidence_ids: Tuple[str, ...] = ()
    source_class: str = "agent_inference"
    verified_source_class: str = "agent_inference"
    kind: str = "belief"
    ingestion_channel: str = ""
    contradictions: Tuple[str, ...] = ()
    derived_from: Tuple[str, ...] = ()

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "MemoryView":
        ev = row.get("evidence_ids") or []
        if isinstance(ev, str):
            ev = _db.jload(ev, [])
        derived = row.get("derived_from") or []
        if isinstance(derived, str):
            derived = _db.jload(derived, [])
        contr = row.get("contradictions") or []
        if isinstance(contr, str):
            contr = _db.jload(contr, [])
        return cls(
            belief_id=str(row.get("belief_id") or ""),
            claim=str(row.get("claim") or ""),
            status=str(row.get("status") or "active"),
            confidence=float(row.get("confidence") or 0.0),
            quarantined=bool(row.get("quarantined")),
            evidence_ids=tuple(str(x) for x in ev),
            source_class=str(row.get("source_class") or "agent_inference"),
            verified_source_class=str(
                row.get("verified_source_class") or row.get("source_class")
                or "agent_inference"
            ),
            kind=str(row.get("kind") or "belief"),
            ingestion_channel=str(row.get("ingestion_channel") or ""),
            contradictions=tuple(str(x) for x in contr),
            derived_from=tuple(str(x) for x in derived),
        )


@dataclass
class ReconcileDecision:
    classification: str
    candidate_id: str
    matched_id: str = ""
    similarity: float = 0.0
    reason: str = ""
    evidence_ids: Tuple[str, ...] = ()
    applied: bool = False
    protected: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "classification": self.classification,
            "candidate_id": self.candidate_id,
            "matched_id": self.matched_id,
            "similarity": round(self.similarity, 4),
            "reason": self.reason,
            "evidence_ids": list(self.evidence_ids),
            "applied": self.applied,
            "protected": self.protected,
        }


@dataclass
class ReconcileResult:
    ok: bool
    dry_run: bool = False
    job_id: str = ""
    candidates_pending: int = 0
    candidates_processed: int = 0
    counts: Dict[str, int] = field(default_factory=dict)
    decisions: List[ReconcileDecision] = field(default_factory=list)
    error: str = ""
    skipped_already_decided: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "dry_run": self.dry_run,
            "job_id": self.job_id,
            "candidates_pending": self.candidates_pending,
            "candidates_processed": self.candidates_processed,
            "counts": dict(self.counts),
            "skipped_already_decided": self.skipped_already_decided,
            "error": self.error,
        }


def empty_counts() -> Dict[str, int]:
    return {name: 0 for name in CLASSES}


def normalize_claim(text: str) -> str:
    lowered = (text or "").lower()
    cleaned = re.sub(r"[^a-z0-9'\s]+", " ", lowered)
    return " ".join(cleaned.split())


def _padded(text: str) -> str:
    return f" {normalize_claim(text)} "


def content_tokens(text: str) -> Tuple[str, ...]:
    tokens = [t for t in _TOKEN_RE.findall(normalize_claim(text)) if t not in _STOPWORDS]
    return tuple(tokens)


def claim_similarity(a: str, b: str) -> float:
    na, nb = normalize_claim(a), normalize_claim(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ta, tb = set(content_tokens(a)), set(content_tokens(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(len(ta), len(tb))


def has_negation(text: str) -> bool:
    padded = _padded(text)
    return any(neg in padded for neg in _NEGATIONS)


def has_replacement_cue(text: str) -> bool:
    padded = _padded(text)
    return any(cue in padded for cue in _REPLACEMENT_CUES)


def _equivalent(a: str, b: str, sim: float) -> bool:
    if normalize_claim(a) == normalize_claim(b):
        return True
    if sim >= EQUIV_SIM and has_negation(a) == has_negation(b):
        return True
    return False


def _proper_subset(a: Sequence[str], b: Sequence[str]) -> bool:
    sa, sb = set(a), set(b)
    return bool(sa and sb and sa != sb and (sa < sb or sb < sa))


def _value_conflict(a: Sequence[str], b: Sequence[str]) -> bool:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return False
    only_a, only_b = sa - sb, sb - sa
    return bool((sa & sb) and only_a and only_b)


def classify(
    candidate: MemoryView,
    existing: Sequence[MemoryView],
) -> ReconcileDecision:
    """Deterministic comparison of one candidate to existing memories.

    Does not write. Does not pick a contradiction winner.
    """
    evidence = candidate.evidence_ids
    if candidate.confidence < LOW_CONFIDENCE or len(content_tokens(candidate.claim)) < MIN_CONTENT_TOKENS:
        return ReconcileDecision(
            classification="low-confidence",
            candidate_id=candidate.belief_id,
            reason="short or low-confidence claim",
            evidence_ids=evidence,
        )

    best: Optional[MemoryView] = None
    best_sim = 0.0
    for mem in existing:
        if mem.belief_id == candidate.belief_id:
            continue
        sim = claim_similarity(candidate.claim, mem.claim)
        if sim > best_sim:
            best_sim = sim
            best = mem

    if best is None or best_sim < IRRELEVANT_SIM:
        return ReconcileDecision(
            classification="irrelevant",
            candidate_id=candidate.belief_id,
            matched_id=best.belief_id if best else "",
            similarity=best_sim,
            reason="no meaningful overlap with existing memories",
            evidence_ids=evidence,
        )

    same_polarity = has_negation(candidate.claim) == has_negation(best.claim)
    cand_toks = content_tokens(candidate.claim)
    best_toks = content_tokens(best.claim)

    if _equivalent(candidate.claim, best.claim, best_sim):
        cand_ev, best_ev = set(candidate.evidence_ids), set(best.evidence_ids)
        if cand_ev and cand_ev <= best_ev:
            return ReconcileDecision(
                classification="duplicate",
                candidate_id=candidate.belief_id,
                matched_id=best.belief_id,
                similarity=best_sim,
                reason="normalized claim already present with the same evidence",
                evidence_ids=evidence,
            )
        if not cand_ev and not best_ev:
            return ReconcileDecision(
                classification="duplicate",
                candidate_id=candidate.belief_id,
                matched_id=best.belief_id,
                similarity=best_sim,
                reason="normalized claim already present",
                evidence_ids=evidence,
            )
        return ReconcileDecision(
            classification="reinforcement",
            candidate_id=candidate.belief_id,
            matched_id=best.belief_id,
            similarity=best_sim,
            reason="same claim with additional evidence",
            evidence_ids=evidence,
        )

    if (not same_polarity) and best_sim >= CONTRADICT_SIM:
        return ReconcileDecision(
            classification="contradiction",
            candidate_id=candidate.belief_id,
            matched_id=best.belief_id,
            similarity=best_sim,
            reason="opposite polarity about the same subject",
            evidence_ids=evidence,
        )

    if has_replacement_cue(candidate.claim) and best_sim >= SUPERSEDE_SIM:
        return ReconcileDecision(
            classification="supersession",
            candidate_id=candidate.belief_id,
            matched_id=best.belief_id,
            similarity=best_sim,
            reason="replacement language against an existing claim",
            evidence_ids=evidence,
        )

    if same_polarity and best_sim >= CONTRADICT_SIM and _value_conflict(cand_toks, best_toks):
        return ReconcileDecision(
            classification="contradiction",
            candidate_id=candidate.belief_id,
            matched_id=best.belief_id,
            similarity=best_sim,
            reason="conflicting values for the same subject",
            evidence_ids=evidence,
        )

    if same_polarity and best_sim >= UPDATE_SIM and _proper_subset(cand_toks, best_toks):
        return ReconcileDecision(
            classification="update",
            candidate_id=candidate.belief_id,
            matched_id=best.belief_id,
            similarity=best_sim,
            reason="refinement of an existing claim",
            evidence_ids=evidence,
        )

    if same_polarity and best_sim >= REINFORCE_SIM:
        return ReconcileDecision(
            classification="reinforcement",
            candidate_id=candidate.belief_id,
            matched_id=best.belief_id,
            similarity=best_sim,
            reason="near-equivalent claim, treat as support",
            evidence_ids=evidence,
        )

    if best_sim < GRAY_SIM:
        return ReconcileDecision(
            classification="low-confidence",
            candidate_id=candidate.belief_id,
            matched_id=best.belief_id,
            similarity=best_sim,
            reason="weak overlap, not a clean match",
            evidence_ids=evidence,
        )

    return ReconcileDecision(
        classification="irrelevant",
        candidate_id=candidate.belief_id,
        matched_id=best.belief_id,
        similarity=best_sim,
        reason="overlap is not a duplicate, support, conflict, update, or replacement",
        evidence_ids=evidence,
    )


def _append_json_list(database: _db.Database, belief_id: str, field: str, value: str) -> None:
    allowed = {"derived_from", "related_entities", "contradictions"}
    if field not in allowed or not belief_id or not value:
        return

    def _u(conn) -> None:
        row = conn.execute(
            f"SELECT {field} FROM beliefs WHERE belief_id = ?", (belief_id,)
        ).fetchone()
        if not row:
            return
        current = list(_db.jload(row[field], []) or [])
        if value not in current:
            current.append(value)
        conn.execute(
            f"UPDATE beliefs SET {field} = ?, updated_at = ? WHERE belief_id = ?",
            (_db.jdump(current), _db.now_iso(), belief_id),
        )

    database._run(_u, write=True)


def _set_status(database: _db.Database, belief_id: str, status: str) -> None:
    def _u(conn) -> None:
        conn.execute(
            "UPDATE beliefs SET status = ?, updated_at = ? WHERE belief_id = ?",
            (status, _db.now_iso(), belief_id),
        )

    database._run(_u, write=True)


def _entity_name(belief_id: str) -> str:
    return f"belief:{belief_id}"


def _relate(
    graph: Optional[KnowledgeGraph],
    src_id: str,
    rel: str,
    dst_id: str,
    *,
    src_kind: str = "fact",
    dst_kind: str = "hypothesis",
    source_ref: str = "",
    session_id: str = "",
) -> None:
    if graph is None or not src_id or not dst_id:
        return
    graph.relate(
        _entity_name(src_id), rel, _entity_name(dst_id),
        confidence=0.6, source_type="derived_pattern",
        source_ref=source_ref or f"reconcile:{src_id}:{dst_id}",
        src_type=src_kind, dst_type=dst_kind, session_id=session_id,
    )


def apply_decision(
    decision: ReconcileDecision,
    *,
    database: _db.Database,
    semantic: SemanticMemory,
    graph: Optional[KnowledgeGraph] = None,
    session_id: str = "",
) -> ReconcileDecision:
    """Apply one classification. Never deletes Layer 1/2 or evidence rows."""
    candidate = semantic.get_belief(decision.candidate_id)
    matched = semantic.get_belief(decision.matched_id) if decision.matched_id else None
    if not candidate:
        decision.applied = False
        decision.reason = (decision.reason + "; missing candidate").strip("; ")
        return decision

    cand_evidence = list(candidate.get("evidence_ids") or decision.evidence_ids)
    classification = decision.classification

    if classification == "duplicate":
        if matched and cand_evidence:
            database.link_evidence("belief", matched["belief_id"], cand_evidence, session_id)
        _set_status(database, candidate["belief_id"], "archived")
        database.log_mutation(
            "reconcile_duplicate", "belief", candidate["belief_id"],
            f"matched={decision.matched_id}", session_id,
        )

    elif classification == "reinforcement":
        if matched and candidate.get("quarantined") and not matched.get("quarantined"):
            decision.applied = False
            decision.protected = "unapproved-candidate"
            decision.reason += "; unapproved candidate cannot strengthen established memory"
            database.log_mutation(
                "reconcile_reinforcement_denied", "belief", matched["belief_id"],
                f"unapproved candidate={candidate['belief_id']}", session_id,
            )
            return decision
        if matched:
            if cand_evidence:
                database.link_evidence("belief", matched["belief_id"], cand_evidence, session_id)
            semantic.reinforce(matched["belief_id"], 0.05, session_id)
            _relate(graph, matched["belief_id"], "SUPPORTED_BY", candidate["belief_id"],
                    source_ref=f"reconcile:{candidate['belief_id']}", session_id=session_id)
        _set_status(database, candidate["belief_id"], "archived")
        database.log_mutation(
            "reconcile_reinforcement", "belief", candidate["belief_id"],
            f"matched={decision.matched_id}", session_id,
        )

    elif classification == "contradiction":
        # Keep both claims and all evidence. Do not pick a winner.
        if matched:
            semantic.link_open_contradiction(
                matched["belief_id"], candidate["belief_id"], session_id=session_id,
            )
            _relate(graph, matched["belief_id"], "CONTRADICTED_BY", candidate["belief_id"],
                    src_kind="fact", dst_kind="hypothesis",
                    source_ref=f"reconcile:{candidate['belief_id']}", session_id=session_id)
            _relate(graph, candidate["belief_id"], "CONTRADICTED_BY", matched["belief_id"],
                    src_kind="hypothesis", dst_kind="fact",
                    source_ref=f"reconcile:{candidate['belief_id']}", session_id=session_id)
        database.log_mutation(
            "reconcile_contradiction", "belief", candidate["belief_id"],
            f"matched={decision.matched_id} resolved=false", session_id,
        )

    elif classification == "update":
        if matched:
            _append_json_list(database, candidate["belief_id"], "derived_from",
                              f"update_of:{matched['belief_id']}")
            _relate(graph, candidate["belief_id"], "DERIVED_FROM", matched["belief_id"],
                    src_kind="hypothesis", dst_kind="fact",
                    source_ref=f"reconcile:{candidate['belief_id']}", session_id=session_id)
        database.log_mutation(
            "reconcile_update", "belief", candidate["belief_id"],
            f"matched={decision.matched_id}", session_id,
        )

    elif classification == "supersession":
        if matched:
            protected = protection_reason(matched)
            if candidate.get("quarantined") and not matched.get("quarantined"):
                protected = protected or "unapproved-candidate"
            if protected:
                decision.applied = False
                decision.protected = protected
                decision.reason = (
                    f"{decision.reason}; protected:{protected} — existing claim kept, "
                    "candidate stays quarantined"
                ).strip("; ")
                database.log_mutation(
                    "reconcile_supersede_denied", "belief", matched["belief_id"],
                    f"protected:{protected} candidate={candidate['belief_id']}",
                    session_id,
                )
                return decision
            else:
                _set_status(database, matched["belief_id"], "superseded")
                _append_json_list(database, candidate["belief_id"], "derived_from",
                                  f"supersedes:{matched['belief_id']}")
                now = _db.now_iso()
                if graph is not None:
                    graph.supersede_relationship(
                        _entity_name(matched["belief_id"]), "RELATED_TO",
                        _entity_name(candidate["belief_id"]),
                        reason="ingest reconcile supersession", session_id=session_id,
                    )
                    graph.relate(
                        _entity_name(candidate["belief_id"]), "SUPERSEDES",
                        _entity_name(matched["belief_id"]),
                        confidence=0.6, source_type="derived_pattern",
                        source_ref=f"reconcile:{candidate['belief_id']}",
                        valid_from=now, src_type="hypothesis", dst_type="fact",
                        session_id=session_id,
                    )
                database.log_mutation(
                    "reconcile_supersession", "belief", candidate["belief_id"],
                    f"supersedes={matched['belief_id']}", session_id,
                )

    elif classification in ("low-confidence", "irrelevant"):
        database.log_mutation(
            f"reconcile_{classification.replace('-', '_')}", "belief",
            candidate["belief_id"],
            f"matched={decision.matched_id}", session_id,
        )

    decision.applied = True
    decision.evidence_ids = tuple(cand_evidence)
    return decision


def preview_pending(database: _db.Database) -> ReconcileResult:
    pending = database.list_pending_reconcile_candidates()
    existing_rows = database.list_existing_memories_for_reconcile()
    existing = [MemoryView.from_row(r) for r in existing_rows]
    seen: List[MemoryView] = list(existing)
    counts = empty_counts()
    decisions: List[ReconcileDecision] = []
    for row in pending:
        cand = MemoryView.from_row(row)
        decision = classify(cand, seen)
        counts[decision.classification] = counts.get(decision.classification, 0) + 1
        decisions.append(decision)
        seen.append(cand)
    return ReconcileResult(
        ok=True,
        dry_run=True,
        candidates_pending=len(pending),
        candidates_processed=0,
        counts=counts,
        decisions=decisions,
    )


def reconcile_store(
    database: _db.Database,
    *,
    dry_run: bool = False,
    cfg: Optional[Dict[str, Any]] = None,
) -> ReconcileResult:
    """Classify pending extract candidates. ``dry_run`` writes no decisions."""
    if dry_run:
        return preview_pending(database)

    cfg = cfg or load_config()
    semantic = SemanticMemory(database, cfg)
    graph = KnowledgeGraph(database, cfg)
    pending = database.list_pending_reconcile_candidates()
    existing_rows = database.list_existing_memories_for_reconcile()
    seen: List[MemoryView] = [MemoryView.from_row(r) for r in existing_rows]
    counts = empty_counts()
    if not pending:
        return ReconcileResult(
            ok=True, dry_run=False, candidates_pending=0,
            candidates_processed=0, counts=counts,
        )

    job_id = database.create_ingest_reconcile_job(dry_run=False)
    result = ReconcileResult(
        ok=True, job_id=job_id, candidates_pending=len(pending), counts=counts,
    )
    try:
        for row in pending:
            cand = MemoryView.from_row(row)
            already = database.get_ingest_reconcile_decision(cand.belief_id)
            if already:
                result.skipped_already_decided += 1
                seen.append(cand)
                continue
            decision = classify(cand, seen)
            decision = apply_decision(
                decision, database=database, semantic=semantic, graph=graph,
                session_id=job_id,
            )
            database.record_ingest_reconcile_decision(
                job_id=job_id,
                candidate_id=decision.candidate_id,
                matched_id=decision.matched_id,
                classification=decision.classification,
                similarity=decision.similarity,
                reason=decision.reason,
                evidence_ids=list(decision.evidence_ids),
                applied=decision.applied,
            )
            counts[decision.classification] = counts.get(decision.classification, 0) + 1
            result.decisions.append(decision)
            result.candidates_processed += 1
            seen.append(cand)
        fields: Dict[str, Any] = {
            "status": "completed",
            "finished_at": _db.now_iso(),
            "candidates_seen": result.candidates_pending,
            "candidates_processed": result.candidates_processed,
        }
        for cls, col in CLASS_TO_COUNT_FIELD.items():
            fields[col] = counts.get(cls, 0)
        database.update_ingest_reconcile_job(job_id, **fields)
    except Exception as e:
        database.update_ingest_reconcile_job(
            job_id, status="failed", error=f"{type(e).__name__}: {e}"[:500],
            finished_at=_db.now_iso(),
        )
        raise
    result.counts = counts
    return result


# ---------------------------------------------------------------------------
# Synthetic fixture pack used by tests (no personal data).
# ---------------------------------------------------------------------------

FIXTURE_EXISTING: Tuple[Dict[str, Any], ...] = (
    {
        "belief_id": "B-key",
        "claim": "the spare brass key is in the left workshop drawer",
        "evidence_ids": ("EV-key-1",),
        "source_class": "user_explicit",
        "verified_source_class": "user_explicit",
        "confidence": 0.95,
        "kind": "fact",
    },
    {
        "belief_id": "B-crane",
        "claim": "the crane slot is Tuesday",
        "evidence_ids": ("EV-crane-1",),
        "source_class": "user_explicit",
        "verified_source_class": "user_explicit",
        "confidence": 0.95,
        "kind": "fact",
    },
    {
        "belief_id": "B-method",
        "claim": "project x uses method a",
        "evidence_ids": ("EV-method-1",),
        "source_class": "agent_inference",
        "verified_source_class": "agent_inference",
        "confidence": 0.5,
        "kind": "belief",
    },
    {
        "belief_id": "B-print",
        "claim": "printer a prints pla best at 210c",
        "evidence_ids": ("EV-print-1",),
        "source_class": "tool_result",
        "verified_source_class": "tool_result",
        "confidence": 0.7,
        "kind": "fact",
    },
)

FIXTURE_CANDIDATES: Tuple[Dict[str, Any], ...] = (
    {
        "belief_id": "B-cand-dup",
        "claim": "the spare brass key is in the left workshop drawer",
        "evidence_ids": ("EV-key-1",),
        "expect": "duplicate",
    },
    {
        "belief_id": "B-cand-reinf",
        "claim": "the spare brass key is in the left workshop drawer",
        "evidence_ids": ("EV-key-2",),
        "expect": "reinforcement",
    },
    {
        "belief_id": "B-cand-contra",
        "claim": "the crane slot is not Tuesday",
        "evidence_ids": ("EV-crane-2",),
        "expect": "contradiction",
    },
    {
        "belief_id": "B-cand-update",
        "claim": "the spare brass key is in the left workshop drawer behind the calipers",
        "evidence_ids": ("EV-key-3",),
        "expect": "update",
    },
    {
        "belief_id": "B-cand-super",
        "claim": "project x now uses method b",
        "evidence_ids": ("EV-method-2",),
        "expect": "supersession",
    },
    {
        "belief_id": "B-cand-low",
        "claim": "noted thanks",
        "evidence_ids": ("EV-low-1",),
        "expect": "low-confidence",
    },
    {
        "belief_id": "B-cand-irrel",
        "claim": "the weather in paris is mild in april",
        "evidence_ids": ("EV-weather-1",),
        "expect": "irrelevant",
    },
)


def fixture_pack() -> Tuple[List[MemoryView], List[Tuple[MemoryView, str]]]:
    """Synthetic memories for unit tests: one candidate per class."""
    existing = [
        MemoryView(
            belief_id=str(row["belief_id"]),
            claim=str(row["claim"]),
            confidence=float(row.get("confidence") or 0.5),
            evidence_ids=tuple(row.get("evidence_ids") or ()),
            source_class=str(row.get("source_class") or "agent_inference"),
            verified_source_class=str(row.get("verified_source_class") or "agent_inference"),
            kind=str(row.get("kind") or "belief"),
        )
        for row in FIXTURE_EXISTING
    ]
    candidates = [
        (
            MemoryView(
                belief_id=str(row["belief_id"]),
                claim=str(row["claim"]),
                confidence=0.4,
                quarantined=True,
                evidence_ids=tuple(row.get("evidence_ids") or ()),
                kind="hypothesis",
                ingestion_channel="import",
            ),
            str(row["expect"]),
        )
        for row in FIXTURE_CANDIDATES
    ]
    return existing, candidates


def classify_fixture_pack() -> Dict[str, int]:
    existing, candidates = fixture_pack()
    counts = empty_counts()
    for cand, _expect in candidates:
        decision = classify(cand, existing)
        counts[decision.classification] = counts.get(decision.classification, 0) + 1
    return counts


__all__ = [
    "ACTOR_ID",
    "CLASSES",
    "ExtractRefused",
    "FIXTURE_CANDIDATES",
    "FIXTURE_EXISTING",
    "MemoryView",
    "ReconcileDecision",
    "ReconcileResult",
    "apply_decision",
    "assert_extract_db_path",
    "claim_similarity",
    "classify",
    "classify_fixture_pack",
    "empty_counts",
    "fixture_pack",
    "forbidden_db_paths",
    "normalize_claim",
    "preview_pending",
    "reconcile_store",
    "require_extract_db_env",
]
