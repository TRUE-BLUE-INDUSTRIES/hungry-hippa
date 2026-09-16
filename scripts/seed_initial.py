"""Example seed script for a Hungry Hippa store — generic placeholder data.

Copy this file to seed your own store with the people, projects, devices,
and durable facts you want available from day one:

    cp scripts/seed_initial.py scripts/seed_initial.local.py
    # edit the placeholders below
    python scripts/seed_initial.local.py

Safe to re-run: entities are get_or_create; beliefs are deduped by claim.
All seeded beliefs should carry source_class=user_explicit (facts the user
has stated) so they start at high confidence and carry correct provenance.
"""

import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent

try:                     # normal import: the package is installed
    import hungry_hippa  # noqa: F401
except ModuleNotFoundError:   # running from a clone: this checkout
    sys.path.insert(0, str(REPO_DIR / "src"))
    import hungry_hippa  # noqa: F401

from hungry_hippa.controller import MemoryController
from hungry_hippa.config import load_config

c = MemoryController(load_config())
c.bind_session(session_id="seed", platform="cli")

# ---------------------------------------------------------------- entities
PEOPLE = {
    "Operator": "person",
    "Client A": "person",
}
PROJECTS = {
    "Project One": "project",
    "Project Two": "project",
}
DEVICES = {
    "Workstation": "device",
}

for name, t in {**PEOPLE, **PROJECTS, **DEVICES}.items():
    c.graph.get_or_create_entity(name, t, session_id="seed")

# ---------------------------------------------------------- relationships
R = c.relate
R("Operator", "WORKS_ON", "Project One")
R("Client A", "WORKS_ON", "Project Two")
R("Operator", "OWNS", "Workstation")

# ---------------------------------------------------------------- beliefs
FACTS = [
    ("The operator prefers local tools over cloud services.", "preference"),
    ("The operator wants results verified before they are claimed.", "preference"),
    ("Project One depends on Workstation for its build pipeline.", "fact"),
    # add your own durable facts here; keep source_class=user_explicit
]

existing = {b["claim"].strip() for b in c.semantic.list_beliefs(status="active", limit=200)}
existing |= {b["claim"].strip() for b in c.semantic.list_beliefs(status="contradicted", limit=200)}
existing |= {b["claim"].strip() for b in c.semantic.list_beliefs(status="superseded", limit=200)}
created = 0
for claim, kind in FACTS:
    if claim in existing:
        continue
    r = c.semantic.add_belief(claim, kind=kind, confidence=0.95,
                              source_class="user_explicit",
                              importance=0.8, session_id="seed")
    if r.get("belief_id"):
        created += 1
    existing.add(claim)

print(f"seeded: {created} new beliefs")
print(c.status()["counts"])
