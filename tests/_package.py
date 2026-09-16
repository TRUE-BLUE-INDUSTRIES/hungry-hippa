"""Locate the ``hungry_hippa`` package for the standalone suites.

The runtime is an ordinary setuptools package under ``src/`` (see
``pyproject.toml``), so the suites import it the ordinary way. The documented
setup is an editable install (``python -m pip install -e .``); if the package is
not installed, this puts the checkout's ``src/`` on ``sys.path`` and imports it
from there, so a fresh clone can still run the suites.

Either way this is a normal package import. Nothing here constructs a synthetic
module, fakes a package ``__path__``, or writes into ``sys.modules`` — that
machinery existed only because the runtime used to be a flat directory of modules
that had to be re-declared as a package. It is a real package now.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_DIR / "src"


def import_package():
    """Return the imported ``hungry_hippa`` package.

    Prefers whatever ``import hungry_hippa`` resolves to (an editable install of
    this checkout in CI and in the documented dev setup), and falls back to the
    checkout's ``src/`` when the package is not installed at all.
    """
    try:
        import hungry_hippa  # noqa: F401
    except ModuleNotFoundError:
        if str(SRC_DIR) not in sys.path:
            sys.path.insert(0, str(SRC_DIR))
        import hungry_hippa  # noqa: F811
    return hungry_hippa


def imported_from_checkout(package) -> bool:
    """Whether the imported package resolves inside this checkout.

    Used by the import-hygiene suite so a stale install elsewhere cannot quietly
    satisfy a test run against this repository.
    """
    path = getattr(package, "__file__", "") or ""
    try:
        return REPO_DIR.resolve() in Path(path).resolve().parents
    except (OSError, ValueError):        # pragma: no cover - defensive
        return False
