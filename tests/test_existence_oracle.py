"""Existence-oracle tests: an unauthorized caller must not learn what exists.

Finding: recall as an untrusted caller returned
``excluded=[{"item": "belief:B-0002", "reason": "other-actor"}]`` for a topic that
matched a protected memory, and ``[]`` for a topic that matched nothing. That
difference answers "does the operator hold a memory about X", and the row id
leaks sequential identifiers. Graph entity names were returned unfiltered too.

run_all() -> list of {name, passed, detail}.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

REPO_DIR = Path(__file__).resolve().parent.parent


sys.path.insert(0, str(Path(__file__).resolve().parent))   # tests/ (shared helpers)
from _package import import_package  # noqa: E402

PACKAGE_DIR = REPO_DIR / "src" / "hungry_hippa"   # src layout
_PLUGIN = import_package()
from hungry_hippa import trust  # noqa: E402
from hungry_hippa.config import load_config  # noqa: E402
from hungry_hippa.controller import MemoryController  # noqa: E402


def _pair():
    """(owner_controller, untrusted_controller) over one throwaway database."""
    tmp = tempfile.mkdtemp(prefix="hh_oracle_")
    db = os.path.join(tmp, "hungry_hippa.db")
    cfg = load_config()
    cfg["retrieval"]["vectors_enabled"] = False

    owner = MemoryController(cfg, db_path=db)
    owner.bind_session(session_id="owner", platform="cli",
                       trust=trust.local_binding("primary"))

    untrusted = MemoryController(cfg, db_path=db)
    untrusted.bind_session(session_id="probe", platform="mcp",
                           trust=trust.external_binding("probe-client"))
    return owner, untrusted


def _shape(value: Any) -> str:
    """A structural fingerprint: does the shape give anything away?"""
    return json.dumps(value, sort_keys=True)


def _leak_surface(out: Dict[str, Any]) -> str:
    """Everything in a recall response that describes *withheld* records.

    The caller's own query is echoed back (``context_package.query``) and it
    obviously knows what it asked; the oracle is about metadata C: the
    exclusions, the matched entities, the item list and the score parts.
    """
    return _shape({"excluded": out.get("excluded"), "entities": out.get("entities"),
                   "count": out.get("count"), "items": out.get("items"),
                   "sources": out.get("sources"),
                   "explain": out.get("explain", [])})


def check_supplement_only_rows_keep_actor_boundary():
    import sqlite3

    for quarantined in (False, True):
        owner, outsider = _pair()
        for _ in range(4):
            owner.semantic.add_belief("cobalt", source_class="document")
        with sqlite3.connect(owner.db.path) as conn:
            conn.execute("UPDATE beliefs SET status='archived'")
        ev = owner.db.add_evidence("invented hidden evidence", "document", "test:hidden", "")
        b = owner.semantic.add_belief("cobalt concealed belief detail", source_class="user_explicit",
                                      quarantined=quarantined, evidence_ids=[ev])
        e = owner.remember_episode(context="cobalt concealed episode detail",
                                   quarantined=quarantined, embed=False)
        hidden_ids = {b["belief_id"], e["episode_id"]}
        historical = owner.db.fts_search("cobalt", kinds=["belief", "episode"], limit=2)
        assert not hidden_ids & {h["target_id"] for h in historical}, historical
        active = owner.db.fts_search("cobalt", kinds=["belief", "episode"], limit=2, active_only=True)
        assert hidden_ids == {h["target_id"] for h in active}, active
        for review in (False, True):
            out = outsider.recall("cobalt", limit=1, include_quarantined=review, explain=True)
            miss = outsider.recall("unmatched wombat", limit=1, include_quarantined=review, explain=True)
            assert _leak_surface(out) == _leak_surface(miss), (out, miss)
            assert out["context"] == "" and out["context_package"]["items"] == []
            assert out["context_package"]["excluded"] == miss["context_package"]["excluded"]
            blob = json.dumps(out)
            assert all(token not in blob for token in [*hidden_ids, ev, "concealed", "hidden evidence"]), out
        # Operator-created row assigned to this actor is readable; selecting it
        # through the supplement must not rewrite its origin or duplicate it.
        allowed_ev = owner.db.add_evidence("invented shared evidence", "document", "test:shared", "")
        allowed = owner.semantic.add_belief(
            "cobalt", actor_id="probe-client", identity=trust.OWNER,
            provenance=trust.PROVENANCE_USER, source_class="document", evidence_ids=[allowed_ev])
        out = outsider.recall("cobalt", limit=1, explain=True)
        assert [r.get("belief_id") for r in out["items"]] == [allowed["belief_id"]], out
        assert out["items"][0]["claimed_source_class"] == "document"
        assert out["items"][0]["verified_source_class"] == "document"
        assert allowed_ev in out["sources"], out
        overlap = outsider.recall("cobalt", limit=10, explain=True)
        assert [r.get("belief_id") for r in overlap["items"]] == [allowed["belief_id"]], overlap
    return "supplement-only beliefs/episodes preserve actor denial, evidence, provenance and deduplication"


def check_other_actors_cannot_starve_own_recall():
    import subprocess

    for kind in ("belief", "episode"):
        owner, outsider = _pair()
        for _ in range(6):
            owner.semantic.add_belief("cobalt", source_class="document")
        ev = owner.db.add_evidence("invented actor evidence", "document", "test:actor", "")
        if kind == "belief":
            own = owner.semantic.add_belief(
                "cobalt assigned workshop detail", actor_id="probe-client", identity=trust.OWNER,
                provenance=trust.PROVENANCE_USER, source_class="document", evidence_ids=[ev])
            key = "belief_id"
        else:
            own = owner.episodic.remember_episode(
                context="cobalt assigned workshop detail", actor_id="probe-client",
                identity=trust.OWNER, evidence_ids=[ev])
            key = "episode_id"
        historical = owner.db.fts_search("cobalt", limit=2, active_only=True,
                                         exclude_quarantined=True)
        assert own[key] not in {h["target_id"] for h in historical}, historical
        # New interpreter: source data and evidence must survive process boundaries.
        code = """
import json, sys
from hungry_hippa.config import load_config
from hungry_hippa.controller import MemoryController
from hungry_hippa import trust
cfg = load_config()
cfg['retrieval']['vectors_enabled'] = False
cfg['manager'] = {'enabled': False}
c = MemoryController(cfg, db_path=sys.argv[1])
c.bind_session(session_id='fresh', platform='mcp', trust=trust.external_binding('probe-client'))
print(json.dumps(c.recall('cobalt', limit=1, explain=True)))
"""
        result = subprocess.run([sys.executable, "-c", code, owner.db.path],
                                capture_output=True, text=True, check=True)
        out = json.loads(result.stdout)
        assert [r.get(key) for r in out["items"]] == [own[key]], out
        assert ev in out["sources"], out
        assert "assigned workshop detail" in out["context"], out
        assert out["excluded"] == {"unauthorized": True,
                                    "note": "excluded items are not enumerated for this caller"}
        assert out["context_package"]["trust"]["authority"] == "none"
    return "other-actor FTS crowding cannot hide own durable beliefs/episodes or evidence"


def check_actor_window_selection_boundaries():
    import sqlite3
    from hungry_hippa import policy

    owner, _ = _pair()
    for _ in range(6):
        owner.semantic.add_belief("cobalt", source_class="document")
    actor = "probe'client"
    own = owner.semantic.add_belief(
        "cobalt assigned workshop detail", actor_id=actor, identity=trust.OWNER,
        source_class="document")
    q = owner.semantic.add_belief(
        "cobalt quarantined workshop detail", actor_id=actor, identity=trust.OWNER,
        source_class="document", quarantined=True)
    retired = owner.semantic.add_belief(
        "cobalt historical workshop detail", actor_id=actor, identity=trust.OWNER,
        source_class="document")
    with sqlite3.connect(owner.db.path) as conn:
        conn.execute("UPDATE beliefs SET status='archived' WHERE belief_id=?", (retired['belief_id'],))
    for active in (False, True):
        for exclude in (False, True):
            hits = owner.db.fts_search("cobalt", limit=20, actor_id=actor,
                                       active_only=active, exclude_quarantined=exclude)
            expected = {own['belief_id']}
            if not active:
                expected.add(retired['belief_id'])
            if not exclude:
                expected.add(q['belief_id'])
            assert {h['target_id'] for h in hits} == expected, hits
    recall = owner.retrieval.recall
    for label in (actor, "  " + actor + "  "):
        out = recall("cobalt", limit=1, actor_id=label, identity=trust.UNTRUSTED)
        assert [r.get('belief_id') for r in out['items']] == [own['belief_id']], out
    review = recall("cobalt", limit=10, actor_id=actor, identity=trust.UNTRUSTED,
                    include_quarantined=True)
    assert q['belief_id'] in {r.get('belief_id') for r in review['items']}, review
    for label in ("primary", "owner", "   "):
        out = recall("cobalt", limit=1, actor_id=label, identity=trust.UNTRUSTED)
        assert out['items'] == [], out
    for label, identity in (("non-owner-label", trust.OWNER),
                             ("background", policy.IDENTITY_SYSTEM), ("primary", None)):
        out = recall("cobalt", limit=1, actor_id=label, identity=identity)
        assert out['count'] == 1, out
        assert out['items'][0]['actor_id'] == 'primary', out

    # Same-actor private rows reach the supplemental query, but may_read must
    # still deny them. This directly exercises post-selection authorization.
    for kind in ('belief', 'episode'):
        c, outsider = _pair()
        for _ in range(6):
            c.semantic.add_belief('cobalt', source_class='document')
        if kind == 'belief':
            hidden = c.semantic.add_belief('cobalt private detail', actor_id='probe-client',
                                           identity=trust.OWNER, sensitivity='private')
            key = 'belief_id'
        else:
            hidden = c.episodic.remember_episode(context='cobalt private detail',
                actor_id='probe-client', identity=trust.OWNER, sensitivity='restricted')
            key = 'episode_id'
        hits = c.db.fts_search('cobalt', limit=2, active_only=True, actor_id='probe-client')
        assert [h['target_id'] for h in hits] == [hidden[key]], hits
        out = outsider.recall('cobalt', limit=1, explain=True)
        assert _leak_surface(out) == _leak_surface(outsider.recall('wombat', limit=1, explain=True))
        assert 'private detail' not in json.dumps(out), out

    # Direct SQL can create noncanonical labels that normal writers never emit.
    # Exact candidate selection does not normalize stored labels; the historical
    # window still passes such rows through the existing normalized read policy.
    with sqlite3.connect(owner.db.path) as conn:
        conn.execute('UPDATE beliefs SET actor_id=? WHERE belief_id=?',
                     ('  ' + actor + '  ', own['belief_id']))
    assert own['belief_id'] not in {h['target_id'] for h in owner.db.fts_search(
        'cobalt', actor_id=actor, limit=20)}
    out = recall('cobalt', actor_id=actor, identity=trust.UNTRUSTED, limit=20)
    assert own['belief_id'] in {r.get('belief_id') for r in out['items']}, out
    return 'actor filter flags, identity exemptions, normalized callers and downstream sensitivity denial'


def check_hit_and_miss_are_indistinguishable():
    """A protected match and no match must produce identical metadata."""
    owner, untrusted = _pair()
    owner.semantic.add_belief("private note about the Ridgeline bid", kind="fact",
                              source_class="user_explicit", sensitivity="private")
    owner.semantic.add_belief("private note about the Cascade estimate",
                              kind="fact", source_class="user_explicit",
                              sensitivity="private")

    hit = untrusted.recall("Ridgeline bid", explain=True)
    other_hit = untrusted.recall("Cascade estimate", explain=True)
    miss = untrusted.recall("wombat sanctuary", explain=True)

    assert _shape(hit["excluded"]) == _shape(miss["excluded"]), (hit, miss)
    assert _shape(hit["excluded"]) == _shape(other_hit["excluded"]), (hit, other_hit)
    assert _shape(hit["entities"]) == _shape(miss["entities"]) == "[]", hit
    assert _shape(hit["explain"]) == _shape(miss["explain"]) == "[]", hit
    assert hit["count"] == miss["count"] == 0
    assert _leak_surface(hit) == _leak_surface(miss), "protected match is distinguishable"
    return "identical metadata surface for a protected match, another match, and no match"


def check_no_protected_ids_or_counts_leak():
    """No row ids, no per-reason counts, not even a withheld-count."""
    owner, untrusted = _pair()
    for i in range(5):
        owner.semantic.add_belief(f"secret plan number {i} for the Ridgeline bid",
                                  kind="fact", source_class="user_explicit",
                                  sensitivity="private")
    out = untrusted.recall("Ridgeline bid")
    blob = json.dumps(out)
    assert "belief:" not in blob, blob
    assert "B-000" not in blob, blob
    assert "other-actor" not in blob and "sensitivity" not in blob, blob
    assert "denied" not in blob and "count_denied" not in blob, blob
    assert out["excluded"] == {"unauthorized": True,
                               "note": "excluded items are not enumerated for this caller"}, \
        out["excluded"]
    return f"5 protected rows matched; response carries none of their identifiers: {out['excluded']}"


def check_owner_keeps_rich_diagnostics():
    """The owner (and only the owner) still gets the full exclusion reasons."""
    owner, untrusted = _pair()
    owner.semantic.add_belief("private note about the Cascade estimate", kind="fact",
                              source_class="user_explicit", sensitivity="private")
    out = owner.recall("Cascade estimate")
    assert isinstance(out["excluded"], list), out["excluded"]

    # a superseded row is excluded with its reason, visible to the owner only
    first = owner.semantic.add_belief("the crane slot is Tuesday", kind="fact",
                                      source_class="user_explicit")
    owner.semantic.supersede(first["belief_id"], "the crane slot is Thursday")
    owner_out = owner.recall("crane slot")
    reasons = json.dumps(owner_out["excluded"])
    assert "crane slot" in owner_out["context"] or "superseded" in reasons, owner_out
    probe = untrusted.recall("crane slot")
    assert probe["excluded"]["unauthorized"] is True, probe["excluded"]
    assert "superseded" not in json.dumps(probe), probe
    return "owner sees item-level reasons; the probing caller sees only the summary"


def check_untrusted_cannot_see_own_rows_ids_of_others():
    """An untrusted caller still reads its own rows, but learns nothing else."""
    owner, untrusted = _pair()
    owner.semantic.add_belief("owner private note about the Hollis job",
                              kind="fact", source_class="user_explicit",
                              sensitivity="private")
    mine = untrusted.semantic.add_belief("my own untrusted note", kind="fact",
                                         identity=trust.UNTRUSTED)
    assert mine.get("quarantined") is True, mine

    own = untrusted.recall("my own untrusted note")
    others = untrusted.recall("Hollis job")
    assert own["excluded"]["unauthorized"] is True, own["excluded"]
    assert own["count"] == 0, "quarantined own rows are still not in normal recall"
    assert _leak_surface(own) == _leak_surface(others), (own, others)
    return "own-write round trip is not a channel for other rows' ids"


def check_entity_names_are_not_leaked():
    """Graph entity names from owner memories must not reach an outsider."""
    owner, untrusted = _pair()
    owner.relate("Ridgeline", "OWNS", "Bay 4", src_type="project", dst_type="location")
    owner.relate("Bay 4", "HAS_PROBLEM", "seized housing",
                 src_type="location", dst_type="problem")
    owner_out = owner.recall("Ridgeline")
    assert any(e for e in owner_out["entities"]), owner_out["entities"]
    probe = untrusted.recall("Ridgeline")
    assert probe["entities"] == [], probe["entities"]
    assert probe["items"] == [] and probe["count"] == 0, probe
    # the entity name may only appear because the caller asked about it
    assert "Bay 4" not in json.dumps(probe), probe
    assert "seized housing" not in json.dumps(probe), probe
    return f"owner saw {owner_out['entities'][:3]}; outsider saw none"


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

    check("actor_window_selection_boundaries", check_actor_window_selection_boundaries)
    check("other_actors_cannot_starve_own_recall", check_other_actors_cannot_starve_own_recall)
    check("supplement_only_rows_keep_actor_boundary", check_supplement_only_rows_keep_actor_boundary)
    check("hit_and_miss_are_indistinguishable", check_hit_and_miss_are_indistinguishable)
    check("no_protected_ids_or_counts_leak", check_no_protected_ids_or_counts_leak)
    check("owner_keeps_rich_diagnostics", check_owner_keeps_rich_diagnostics)
    check("untrusted_own_rows_learn_nothing_else",
          check_untrusted_cannot_see_own_rows_ids_of_others)
    check("entity_names_are_not_leaked", check_entity_names_are_not_leaked)
    return results


if __name__ == "__main__":
    results = run_all()
    passed = sum(1 for r in results if r["passed"])
    for r in results:
        print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['name']}: {r['detail']}")
    print(f"\n{passed}/{len(results)} passed")
    sys.exit(0 if passed == len(results) else 1)
