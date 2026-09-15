"""Existence-oracle tests: an unauthorized caller must not learn what exists.

Finding: recall as an untrusted caller returned
``excluded=[{"item": "belief:B-0002", "reason": "other-actor"}]`` for a topic that
matched a protected memory, and ``[]`` for a topic that matched nothing. That
difference answers "does the operator hold a memory about X", and the row id
leaks sequential identifiers. Graph entity names were returned unfiltered too.

run_all() -> list of {name, passed, detail}.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import types
from pathlib import Path
from typing import Any, Dict, List

PLUGIN_DIR = Path(__file__).resolve().parent.parent


def _import_plugin():
    if sys.modules.get("livingcortex") is not None and getattr(
        sys.modules["livingcortex"], "__file__", None
    ):
        return sys.modules["livingcortex"]
    pkg = types.ModuleType("livingcortex")
    pkg.__path__ = [str(PLUGIN_DIR)]
    pkg.__file__ = str(PLUGIN_DIR / "__init__.py")
    sys.modules["livingcortex"] = pkg
    spec = importlib.util.spec_from_file_location(
        "livingcortex", str(PLUGIN_DIR / "__init__.py"),
        submodule_search_locations=[str(PLUGIN_DIR)])
    mod = importlib.util.module_from_spec(spec)
    sys.modules["livingcortex"] = mod
    spec.loader.exec_module(mod)
    return mod


_PLUGIN = _import_plugin()
from livingcortex import trust  # noqa: E402
from livingcortex.config import load_config  # noqa: E402
from livingcortex.controller import MemoryController  # noqa: E402


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
