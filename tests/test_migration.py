"""Hungry Hippa migration and compatibility tests (Phase 2).

Throwaway directories only. Never opens the live $HERMES_HOME database.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import types
import warnings
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent


def _import_plugin():
    import importlib.util

    if sys.modules.get("livingcortex") is not None and getattr(
        sys.modules["livingcortex"], "__file__", None
    ):
        return sys.modules["livingcortex"]

    pkg = types.ModuleType("livingcortex")
    pkg.__path__ = [str(PLUGIN_DIR)]
    pkg.__file__ = str(PLUGIN_DIR / "__init__.py")
    sys.modules["livingcortex"] = pkg
    spec = importlib.util.spec_from_file_location(
        "livingcortex",
        str(PLUGIN_DIR / "__init__.py"),
        submodule_search_locations=[str(PLUGIN_DIR)],
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["livingcortex"] = mod
    spec.loader.exec_module(mod)
    return mod


_PLUGIN = _import_plugin()


def _clear_db_env():
    os.environ.pop("HUNGRY_HIPPA_DB", None)
    os.environ.pop("LIVING_CORTEX_DB", None)


def test_hungry_hippa_db_env_wins():
    _clear_db_env()
    path = os.path.join(tempfile.gettempdir(), "hh_env_wins.db")
    os.environ["HUNGRY_HIPPA_DB"] = path
    os.environ["LIVING_CORTEX_DB"] = os.path.join(tempfile.gettempdir(), "old.db")
    try:
        from livingcortex.config import load_config, resolve_db_path

        cfg = load_config()
        assert resolve_db_path(cfg) == path
    finally:
        _clear_db_env()


def test_living_cortex_db_env_still_works_with_warning():
    _clear_db_env()
    path = os.path.join(tempfile.gettempdir(), "lc_compat.db")
    os.environ["LIVING_CORTEX_DB"] = path
    try:
        from livingcortex.config import load_config, resolve_db_path

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            cfg = load_config()
            assert resolve_db_path(cfg) == path
        assert any("LIVING_CORTEX_DB" in str(w.message) for w in caught), caught
    finally:
        _clear_db_env()


def test_existing_living_cortex_file_is_discovered():
    from livingcortex.config import discover_default_db_path

    home = Path(tempfile.mkdtemp(prefix="hh_disc_"))
    old = home / "living_cortex.db"
    old.write_bytes(b"sqlite-placeholder")
    assert discover_default_db_path(home) == str(old)
    assert Path(discover_default_db_path(home)).name == "living_cortex.db"


def test_new_install_defaults_to_hungry_hippa_db():
    from livingcortex.config import discover_default_db_path

    home = Path(tempfile.mkdtemp(prefix="hh_new_"))
    path = discover_default_db_path(home)
    assert path.endswith("hungry_hippa.db")
    assert not Path(path).exists()


def test_migrate_backs_up_and_preserves_memories():
    from livingcortex.config import load_config
    from livingcortex.controller import MemoryController
    from livingcortex.db import migrate_database

    tmp = tempfile.mkdtemp(prefix="hh_mig_")
    src = os.path.join(tmp, "living_cortex.db")
    for f in (src, src + "-wal", src + "-shm"):
        if os.path.exists(f):
            os.remove(f)

    cfg = load_config()
    cfg["retrieval"]["vectors_enabled"] = False
    c = MemoryController(cfg, db_path=src)
    c.bind_session(session_id="mig-test", platform="cli")
    remembered = c.remember_episode(
        context="migration probe: cracked bracket decision",
        user_request="fix the bracket",
        actions_taken="larger fillet",
        outcome="failure",
        project="mig_probe",
        embed=False,
    )
    belief = c.semantic.add_belief(
        "4mm fillet failed on this bracket",
        kind="fact",
        confidence=0.9,
        source_class="user_explicit",
        session_id="mig-test",
    )
    episode_id = remembered["episode_id"]
    belief_id = belief["belief_id"]

    report = migrate_database(src)
    assert report.get("backup"), report
    assert os.path.isfile(report["backup"]), report
    assert os.path.getsize(report["backup"]) > 0
    assert report.get("product_name") == "Hungry Hippa"
    assert "Living Cortex" in (report.get("formerly") or "")

    conn = sqlite3.connect(src)
    try:
        versions = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
        assert 3 in versions, versions
        ep = conn.execute(
            "SELECT context, outcome FROM episodes WHERE episode_id = ?",
            (episode_id,),
        ).fetchone()
        assert ep is not None
        assert "cracked bracket" in ep[0]
        assert ep[1] == "failure"
        bel = conn.execute(
            "SELECT claim FROM beliefs WHERE belief_id = ?",
            (belief_id,),
        ).fetchone()
        assert bel is not None
        assert "4mm fillet failed" in bel[0]
        meta = conn.execute(
            "SELECT product_name, formerly FROM product_meta WHERE id = 1"
        ).fetchone()
        assert meta[0] == "Hungry Hippa"
        assert "Living Cortex" in meta[1]
    finally:
        conn.close()


def test_rollback_instructions_exist():
    doc = (PLUGIN_DIR / "docs" / "MIGRATION.md").read_text(encoding="utf-8")
    assert "Rollback" in doc
    assert "living_cortex.db" in doc
    assert "Hungry Hippa" in doc
    assert "formerly living cortex" in doc.lower()


def run_all() -> list:
    results = []

    def check(name, fn):
        try:
            detail = fn() or "ok"
            results.append({"name": name, "passed": True, "detail": str(detail)[:300]})
        except AssertionError as e:
            results.append({"name": name, "passed": False, "detail": f"assert: {e}"})
        except Exception as e:
            results.append(
                {"name": name, "passed": False, "detail": f"{type(e).__name__}: {e}"}
            )

    check("hungry_hippa_db_env_wins", test_hungry_hippa_db_env_wins)
    check(
        "living_cortex_db_env_still_works_with_warning",
        test_living_cortex_db_env_still_works_with_warning,
    )
    check("existing_living_cortex_file_is_discovered", test_existing_living_cortex_file_is_discovered)
    check("new_install_defaults_to_hungry_hippa_db", test_new_install_defaults_to_hungry_hippa_db)
    check("migrate_backs_up_and_preserves_memories", test_migrate_backs_up_and_preserves_memories)
    check("rollback_instructions_exist", test_rollback_instructions_exist)
    return results


if __name__ == "__main__":
    results = run_all()
    passed = sum(1 for r in results if r["passed"])
    for r in results:
        print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['name']}: {r['detail']}")
    print(f"\n{passed}/{len(results)} passed")
    sys.exit(0 if passed == len(results) else 1)
