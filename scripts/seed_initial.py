"""One-time idempotent seed of core entities/beliefs into the Living Cortex.

Run:  python seed_initial.py
Safe to re-run: entities are get_or_create; beliefs are deduped by claim.
All seeded beliefs carry source_class=user_explicit (facts DJ has stated).
"""

import sys
import types
import importlib.util
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
pkg = types.ModuleType("livingcortex")
pkg.__path__ = [str(PLUGIN)]
sys.modules["livingcortex"] = pkg
spec = importlib.util.spec_from_file_location(
    "livingcortex", str(PLUGIN / "__init__.py"),
    submodule_search_locations=[str(PLUGIN)])
mod = importlib.util.module_from_spec(spec)
sys.modules["livingcortex"] = mod
spec.loader.exec_module(mod)

from livingcortex.controller import MemoryController
from livingcortex.config import load_config

c = MemoryController(load_config())
c.bind_session(session_id="seed", platform="cli")

# ---------------------------------------------------------------- entities
PEOPLE = {
    "Dennis Rotherham": "person",
    "Alexus": "person",
    "Oaklynn": "person",
    "Alvin": "person",
}
PROJECTS = {
    "Voxvil": "project",
    "AD Audit": "project",
    "TRUE BLUE INVENTION ENGINE": "project",
    "engineering-agent": "project",
    "agent-bridge": "project",
    "Meat plant enclosure project": "project",
}
DEVICES = {
    "Prusa XL": "device",
    "Xreal One": "device",
    "Meta Fury glasses": "device",
    "D's S25 Ultra": "device",
    "RTX 5070 Ti": "device",
    "LAFVIN ESP32-S3": "device",
}

for name, t in {**PEOPLE, **PROJECTS, **DEVICES}.items():
    c.graph.get_or_create_entity(name, t, session_id="seed")

# ---------------------------------------------------------- relationships
R = c.relate
R("Dennis Rotherham", "WORKS_ON", "Voxvil")
R("Dennis Rotherham", "WORKS_ON", "AD Audit")
R("Dennis Rotherham", "WORKS_ON", "TRUE BLUE INVENTION ENGINE")
R("Dennis Rotherham", "WORKS_ON", "engineering-agent")
R("Dennis Rotherham", "WORKS_ON", "agent-bridge")
R("Dennis Rotherham", "WORKS_ON", "Meat plant enclosure project")
R("Alvin", "WORKS_ON", "Meat plant enclosure project")
R("Alvin", "WORKS_ON", "engineering-agent")
R("Dennis Rotherham", "OWNS", "Prusa XL")
R("Dennis Rotherham", "OWNS", "Xreal One")
R("Dennis Rotherham", "OWNS", "Meta Fury glasses")
R("Dennis Rotherham", "OWNS", "D's S25 Ultra")
R("Dennis Rotherham", "OWNS", "RTX 5070 Ti")
R("Voxvil", "USES", "Prusa XL")
R("Meat plant enclosure project", "REQUIRES", "sealed wet/cold cabinet")
R("Alexus", "RELATED_TO", "Dennis Rotherham")
R("Oaklynn", "RELATED_TO", "Dennis Rotherham")

# ---------------------------------------------------------------- beliefs
FACTS = [
    ("Dennis prefers OpenSCAD (local) over SolidWorks (cloud).", "preference"),
    ("Dennis wants Grok and Gemini CLI raw responses shown verbatim, never summarized.", "preference"),
    ("Dennis prefers autonomous keep-going execution on complex builds over step-by-step check-ins.", "preference"),
    ("Prusa XL build volume is 360x360x348mm with 2 toolheads.", "fact"),
    ("Alvin's meat plant cabinet project budget is about $4k; cabinet is 305x450x300mm sealed wet/cold, no louvres.", "fact"),
    ("UAV arm design (DJ patent): PLA-tube core + TPU clamshell sleeve, 0.5mm air gap + gyroid + nubs.", "fact"),
    ("Projects must stay strictly separated: Voxvil, AD Audit, TRUE BLUE INVENTION ENGINE. No cross-imports; hallucinated cross-project links are a hard fail.", "fact"),
    ("ACE TRIDENT, EXOVEX, AFWERX, MCWL, NDAs, Blended Blueprint AI Architecture are sensitive/privileged material.", "fact"),
    ("Alvin is Discord user 'ep'; Dennis is 'trueblue92' (seen as Truubluu92).", "fact"),
    ("Hardware: RTX 5070 Ti 16GB GPU, 64GB RAM; Yoga webcam/mic; Xreal One S+Eye+Hub HUD.", "fact"),
    ("Agent bridge is a Redis task bus at C:\\Users\\TBI-Admin\\agent-bridge (Hermes + OpenClaw + Codex workers, gateway port 18789).", "fact"),
    ("LAFVIN ESP32-S3 dev board: TFT200C 240x320 V1.3 (likely ST7789, ~8MB OPI PSRAM); TFT pins BLK=IO42 SDA=IO40 CLK=IO41 CS=IO47 DC=IO39; audio on ES8311.", "fact"),
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

print(f"seeded: {created} new beliefs, "
      f"{len(c.graph.search_entities(''))} entities (see status)")
print(c.status()["counts"])
