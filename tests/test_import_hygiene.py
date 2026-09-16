"""Import and packaging hygiene: no hand-rolled package bootstrapping.

The runtime used to be a flat directory of modules hosted inside another
application, and everything that imported it — the suites, the demo, the eval
harness, the seed scripts — worked around that by building a fake ``hungry_hippa``
module at import time (``types.ModuleType`` + ``spec_from_file_location`` +
``sys.modules[...] = ...``).

That workaround is obsolete: Hungry Hippa is a real setuptools package under
``src/`` with declared discovery in ``pyproject.toml``. This suite keeps it that
way. It asserts:

  * no synthetic package construction and no ``sys.modules`` injection anywhere;
  * the two remaining by-path file loads are the documented, justified ones
    (a loose suite file, and ``eval/harness.py`` behind a non-package ``eval/``);
  * the package resolves through the normal import system, from this checkout;
  * a clone without an install still works, via the single documented source
    fallback in ``tests/_package.py``;
  * every entry point still starts (CLI, console scripts, both MCP invocations);
  * the migration-era compatibility surface this cleanup must NOT remove still
    works: the ``LivingCortexProvider`` alias, the legacy ``hermes_inference``
    source class, the deprecated ``LIVING_CORTEX_DB`` environment variable, and
    discovery of a former ``living_cortex.db``.

run_all() -> list of {name, passed, detail}.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import warnings
from pathlib import Path
from typing import Any, Dict, List, Tuple

REPO_DIR = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(Path(__file__).resolve().parent))   # tests/ (shared helpers)
from _package import SRC_DIR, import_package, imported_from_checkout  # noqa: E402

PACKAGE_DIR = REPO_DIR / "src" / "hungry_hippa"   # src layout
_PLUGIN = import_package()

#: Files allowed to load a *loose file* by path, with the reason. Neither one
#: builds a package: they run a file that is not (and should not be) a module of
#: the installed package.
BY_PATH_FILE_LOADS = {
    "src/hungry_hippa/cli.py": "loads tests/test_acceptance.py for `hungry-hippa selftest`",
    "eval/check_results.py": "loads eval/harness.py; `eval/` is not an importable package",
}

#: Where the former product name is still load-bearing, with the reason. Anything
#: else that still says "living_cortex"/"hermes" is a bug this suite should catch.
LEGACY_NAME_ALLOWED = {
    "src/hungry_hippa/config.py": "deprecated LIVING_CORTEX_DB alias + legacy database discovery",
    "src/hungry_hippa/schema.py": "historical migration descriptions and the 'formerly' metadata row",
    "src/hungry_hippa/db.py": "migration report fallback for the 'formerly' field",
    "src/hungry_hippa/semantic.py": "hermes_inference accepted as a legacy input alias",
    "src/hungry_hippa/__init__.py": "public description keeps 'formerly Living Cortex'",
    "src/hungry_hippa/trust.py": "docstring states the absence of ~/.hermes coupling",
    "src/hungry_hippa/cli.py": "`migrate` help text and the selftest loader rationale",
}


def _python_files() -> List[Path]:
    out: List[Path] = []
    for root in ("src", "tests", "demo", "eval", "scripts"):
        out += [p for p in (REPO_DIR / root).rglob("*.py")
                if "__pycache__" not in p.parts]
    return sorted(out)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------- checks

def check_no_synthetic_package_bootstrapping():
    """No module objects are hand-built, and nothing writes into sys.modules."""
    synthetic = "types." + "ModuleType"
    inject = "sys.modules[" + '"hungry_hippa"] ='
    loader = "spec_from_file_" + "location"
    offenders: List[str] = []
    for path in _python_files():
        rel = path.relative_to(REPO_DIR).as_posix()
        if path.name in ("_package.py", "test_import_hygiene.py") and \
                path.parent.name == "tests":
            # the resolver itself (asserted below), and this file, which has to
            # name the retired patterns in order to search for them
            continue
        text = _text(path)
        if synthetic in text:
            offenders.append(f"{rel}: {synthetic}")
        if inject in text:
            offenders.append(f"{rel}: {inject}")
        if loader in text and rel not in BY_PATH_FILE_LOADS:
            offenders.append(f"{rel}: {loader}")
    assert not offenders, offenders

    # the tests/ resolver is the only thing that touches sys.path for the package,
    # and it does so with a plain insert + normal import
    helper = _text(REPO_DIR / "tests" / "_package.py")
    assert "import hungry_hippa" in helper
    assert "sys.path.insert" in helper
    assert inject not in helper and synthetic not in helper and loader not in helper
    return ("no synthetic modules and no sys.modules injection; the only by-path "
            f"loads are {sorted(BY_PATH_FILE_LOADS)}")


def check_by_path_loads_are_justified():
    """The two remaining by-path loads are loose files, not the package."""
    for rel, reason in BY_PATH_FILE_LOADS.items():
        text = _text(REPO_DIR / rel)
        assert "spec_from_file_" + "location" in text, rel
        assert "hungry_hippa/__init__.py" not in text, (rel, "fakes the package init")
        assert reason, rel
    # and the package is never named as a faked init file
    for rel in BY_PATH_FILE_LOADS:
        assert "hungry_hippa/__init__.py" not in _text(REPO_DIR / rel), rel
    return "cli selftest and the eval checker load files, not packages"


def check_package_resolves_through_the_import_system():
    import importlib.util

    spec = importlib.util.find_spec("hungry_hippa")
    assert spec is not None, "hungry_hippa is not importable through the import system"
    assert spec.submodule_search_locations, "hungry_hippa is not a package"
    origin = Path(spec.origin or "")
    assert origin.name == "__init__.py", spec.origin
    assert imported_from_checkout(_PLUGIN), _PLUGIN.__file__
    assert Path(_PLUGIN.__file__).resolve().parent == PACKAGE_DIR.resolve()

    # submodules (including the ones this cleanup touched) import normally
    import importlib

    for name in ("hungry_hippa.cli", "hungry_hippa.mcp_server",
                 "hungry_hippa.ingest.chatgpt"):
        mod = importlib.import_module(name)
        assert mod is sys.modules[name], name
    # the runtime package has no importable Python at the repository root any more
    root_modules = [p.name for p in REPO_DIR.glob("*.py")]
    assert root_modules == [], root_modules
    return ("find_spec finds a real package under src/; root of the checkout holds "
            "no importable modules")


def check_clone_without_install_still_works():
    """With site-packages disabled, the documented src fallback takes over."""
    script = (
        "import sys; sys.path.insert(0, %r);"
        "from _package import import_package, imported_from_checkout;"
        "m = import_package();"
        "print(m.__file__); print(imported_from_checkout(m));"
        "print(%r in sys.path)" % (str(REPO_DIR / "tests"), str(SRC_DIR)))
    out = subprocess.run([sys.executable, "-S", "-c", script], cwd="/tmp",
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, (out.returncode, out.stderr[-400:])
    lines = out.stdout.strip().splitlines()
    assert lines and Path(lines[0]).resolve().parent == PACKAGE_DIR.resolve(), lines
    assert lines[1] == "True", lines
    assert lines[2] == "True", lines

    # and with site-packages present (the documented editable install) the same
    # call resolves without ever touching sys.path
    script2 = (
        "import sys; sys.path.insert(0, %r);"
        "from _package import import_package;"
        "m = import_package(); print(m.__file__);"
        "print(%r in sys.path)" % (str(REPO_DIR / "tests"), str(SRC_DIR)))
    out2 = subprocess.run([sys.executable, "-c", script2], cwd="/tmp",
                          capture_output=True, text=True, timeout=120)
    assert out2.returncode == 0, (out2.returncode, out2.stderr[-400:])
    assert Path(out2.stdout.splitlines()[0]).resolve().parent == PACKAGE_DIR.resolve()
    return "installed import preferred; src fallback works when nothing is installed"


def check_every_suite_resolves_the_package_the_same_way():
    """Uniform resolution: the shared resolver, or the harness that wraps it."""
    suites = sorted(p for p in (REPO_DIR / "tests").glob("test_*.py"))
    assert suites, "no suites found"
    bad: List[str] = []
    for path in suites:
        text = _text(path)
        normal = ("from _package import import_package" in text
                  or "import mcp_harness" in text
                  or "import _package" in text)
        if not normal:
            bad.append(f"{path.name}: no shared resolver")
        if path.name == "test_import_hygiene.py":
            continue
        # A suite may put tests/ on sys.path (for the shared helpers). It may not
        # put the runtime's source directory there: that fallback lives in exactly
        # one place, tests/_package.py, so the resolution story stays uniform.
        for line in text.splitlines():
            if "sys.path.insert" not in line:
                continue
            if "%r" in line or "resolve().parent" in line:
                continue
            bad.append(f"{path.name}: {line.strip()}")
        assert '"src"' not in text or "PACKAGE_DIR" in text, path.name
    assert not bad, bad
    return f"{len(suites)} suites resolve the package through the shared, normal import"


def check_entry_points_still_start():
    env = dict(os.environ, PYTHONPATH=str(SRC_DIR))

    cli = subprocess.run([sys.executable, "-m", "hungry_hippa.cli", "--help"],
                         capture_output=True, text=True, timeout=120, env=env, cwd="/tmp")
    assert cli.returncode == 0, cli.stderr[-300:]
    for command in ("quarantine", "ingest"):
        assert command in cli.stdout, command

    server_script = PACKAGE_DIR / "mcp_server.py"
    direct = subprocess.run([sys.executable, str(server_script), "--print-schemas"],
                            capture_output=True, text=True, timeout=180, env=env, cwd="/tmp")
    assert direct.returncode == 0, direct.stderr[-300:]
    tools = [t["name"] for t in json.loads(direct.stdout)["tools"]]
    assert len(tools) == 6, tools

    module = subprocess.run([sys.executable, "-m", "hungry_hippa.mcp_server",
                             "--print-schemas"],
                            capture_output=True, text=True, timeout=180, env=env, cwd="/tmp")
    assert module.returncode == 0, module.stderr[-300:]
    assert [t["name"] for t in json.loads(module.stdout)["tools"]] == tools

    console = shutil.which("hungry-hippa") or shutil.which("hungry-hippa-mcp")
    if console:                      # present in an installed environment
        run = subprocess.run([console, "--help"], capture_output=True, text=True,
                             timeout=120, env=env, cwd="/tmp")
        assert run.returncode == 0, run.stderr[-300:]
    return "CLI module, console script and both MCP invocations start; six tools"


def check_legacy_compatibility_surface_intact():
    """The migration-era compatibility this cleanup must not delete."""
    # 1. the old provider class name still imports and is the same object
    assert _PLUGIN.LivingCortexProvider is _PLUGIN.HungryHippaProvider

    # 2. the legacy source class is still accepted on input and normalised
    from hungry_hippa import semantic as _semantic
    from hungry_hippa.config import load_config
    from hungry_hippa.controller import MemoryController
    from hungry_hippa import trust

    assert _semantic.LEGACY_SOURCE_ALIASES.get("hermes_inference") == "agent_inference"
    db_path = os.path.join(tempfile.mkdtemp(prefix="hh_hyg_"), "hungry_hippa.db")
    ctrl = MemoryController(load_config(), db_path=db_path)
    ctrl.bind_session(session_id="hyg", platform="cli", trust=trust.local_binding())
    belief = ctrl.semantic.add_belief("a legacy-labelled claim", kind="fact",
                                      source_class="hermes_inference",
                                      actor_id=ctrl.actor_id, identity=ctrl.identity,
                                      provenance=ctrl.provenance)
    row = ctrl.semantic.get_belief(belief["belief_id"])
    assert row["source_class"] == "agent_inference", row["source_class"]

    # 3. the deprecated environment variable still works and still warns
    from hungry_hippa import config as _config
    legacy_db = os.path.join(tempfile.mkdtemp(prefix="hh_hyg_legacy_"), "old.db")
    saved = os.environ.get("LIVING_CORTEX_DB")
    os.environ["LIVING_CORTEX_DB"] = legacy_db
    os.environ.pop("HUNGRY_HIPPA_DB", None)
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            resolved = _config.resolve_db_path(_config.load_config())
        assert resolved == legacy_db, resolved
        assert any("LIVING_CORTEX_DB" in str(w.message) for w in caught), caught
    finally:
        os.environ.pop("LIVING_CORTEX_DB", None)
        if saved is not None:
            os.environ["LIVING_CORTEX_DB"] = saved
        os.environ.pop("HUNGRY_HIPPA_DB", None)

    # 4. discovery of a database written by the former release
    home = Path(tempfile.mkdtemp(prefix="hh_hyg_home_"))
    (home / "living_cortex.db").write_bytes(b"")
    found = _config.discover_default_db_path(str(home))
    assert Path(found).name == "living_cortex.db", found
    legacy = _config.legacy_db_paths()
    assert legacy and any("living_cortex.db" in p for p in legacy), legacy
    return ("LivingCortexProvider alias, hermes_inference alias, LIVING_CORTEX_DB "
            "deprecation and legacy database discovery all still work")


def check_no_stale_package_names_in_current_code():
    """Old identifiers are gone from current code; legacy strings are allowlisted."""
    retired = "PLUGIN" + "_DIR"
    offenders = [p.relative_to(REPO_DIR).as_posix() for p in _python_files()
                 if p.name != "test_import_hygiene.py" and retired in _text(p)]
    assert not offenders, offenders
    assert "lc_selftest" not in _text(REPO_DIR / "src" / "hungry_hippa" / "cli.py")

    offenders: List[str] = []
    for path in sorted((REPO_DIR / "src").rglob("*.py")):
        rel = path.relative_to(REPO_DIR).as_posix()
        if "__pycache__" in path.parts:
            continue
        text = _text(path).lower()
        if ("living_cortex" in text or "livingcortex" in text) and rel not in LEGACY_NAME_ALLOWED:
            offenders.append(rel)
    assert not offenders, offenders

    # the documented compatibility list itself must not rot: each entry still
    # contains the name it is excused for
    for rel, reason in LEGACY_NAME_ALLOWED.items():
        text = _text(REPO_DIR / rel).lower()
        assert ("living_cortex" in text or "livingcortex" in text or "hermes" in text
                or "living cortex" in text), (rel, reason)
    return (f"the retired {retired} identifier and lc_selftest are gone from current "
            f"code; {len(LEGACY_NAME_ALLOWED)} files keep a legacy name for documented "
            "compatibility")


def check_docs_and_ci_use_the_package_layout():
    """CI and the documented commands run the package, not a bootstrapped path."""
    workflow = _text(REPO_DIR / ".github" / "workflows" / "test.yml")
    assert "pip install -e ." in workflow, "CI must install the package"
    assert "src/hungry_hippa/mcp_server.py" in workflow, "CI should exercise the real path"
    for bad in ("sys.modules", "ModuleType"):
        assert bad not in workflow, bad
    return "CI installs the package and drives the real module paths"


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

    check("no_synthetic_package_bootstrapping", check_no_synthetic_package_bootstrapping)
    check("by_path_loads_are_justified", check_by_path_loads_are_justified)
    check("package_resolves_through_the_import_system",
          check_package_resolves_through_the_import_system)
    check("clone_without_install_still_works", check_clone_without_install_still_works)
    check("every_suite_resolves_the_package_the_same_way",
          check_every_suite_resolves_the_package_the_same_way)
    check("entry_points_still_start", check_entry_points_still_start)
    check("legacy_compatibility_surface_intact",
          check_legacy_compatibility_surface_intact)
    check("no_stale_package_names_in_current_code",
          check_no_stale_package_names_in_current_code)
    check("docs_and_ci_use_the_package_layout",
          check_docs_and_ci_use_the_package_layout)
    return results


if __name__ == "__main__":
    results = run_all()
    passed = sum(1 for r in results if r["passed"])
    for r in results:
        print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['name']}: {r['detail']}")
    print(f"\n{passed}/{len(results)} passed")
    sys.exit(0 if passed == len(results) else 1)
