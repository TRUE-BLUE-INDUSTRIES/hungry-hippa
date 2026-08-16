"""Living Cortex SQLite schema and reversible migrations (§19.10).

Every migration carries ``up_sql`` and ``down_sql`` so the schema can be
rolled back. Raw evidence rows are immutable; every mutation writes a row to
``mutation_log`` (enforced in db.py, not by triggers, so the log carries
rich context).
"""

from __future__ import annotations

from typing import Dict, List

# version -> {description, up, down}
MIGRATIONS: Dict[int, Dict[str, str]] = {
    1: {
        "description": "Initial Living Cortex schema: episodes, evidence, graph, beliefs, procedures, vectors, consolidation, forgetting, retrieval.",
        "up": """
CREATE TABLE counters (
  name TEXT PRIMARY KEY,
  value INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE mutation_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  action TEXT NOT NULL,
  target_kind TEXT NOT NULL,
  target_id TEXT NOT NULL DEFAULT '',
  detail TEXT NOT NULL DEFAULT '',
  session_id TEXT NOT NULL DEFAULT ''
);
CREATE INDEX ix_mutation_ts ON mutation_log(ts);

-- ---------------------------------------------------------------- episodes
CREATE TABLE episodes (
  episode_id TEXT PRIMARY KEY,
  ts_start TEXT NOT NULL,
  ts_end TEXT,
  context TEXT NOT NULL DEFAULT '',
  participants TEXT NOT NULL DEFAULT '',
  location TEXT NOT NULL DEFAULT '',
  visual_entities TEXT NOT NULL DEFAULT '',
  audio_transcript TEXT NOT NULL DEFAULT '',
  user_request TEXT NOT NULL DEFAULT '',
  actions_taken TEXT NOT NULL DEFAULT '',
  tools_used TEXT NOT NULL DEFAULT '',
  files_used TEXT NOT NULL DEFAULT '',
  decisions TEXT NOT NULL DEFAULT '',
  result TEXT NOT NULL DEFAULT '',
  outcome TEXT NOT NULL DEFAULT 'unknown',     -- success/failure/mixed/unknown
  importance REAL NOT NULL DEFAULT 0.5,
  confidence REAL NOT NULL DEFAULT 0.5,
  project TEXT NOT NULL DEFAULT '',
  related_entities TEXT NOT NULL DEFAULT '[]',
  source_refs TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'active',       -- active/archived/compressed/purged
  reinforcement_count INTEGER NOT NULL DEFAULT 0,
  last_accessed TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX ix_episodes_ts ON episodes(ts_start);
CREATE INDEX ix_episodes_project ON episodes(project);
CREATE INDEX ix_episodes_status ON episodes(status);

-- --------------------------------------------------------------- evidence
CREATE TABLE evidence (
  evidence_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,       -- user_explicit|document|tool_result|visual_observation|audio_observation|external_source|hermes_inference|derived_pattern
  content TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  captured_at TEXT NOT NULL,
  source_ref TEXT NOT NULL DEFAULT '',
  immutable INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX ix_evidence_hash ON evidence(content_hash);

CREATE TABLE episode_evidence (
  episode_id TEXT NOT NULL,
  evidence_id TEXT NOT NULL,
  PRIMARY KEY (episode_id, evidence_id)
);

-- ----------------------------------------------------------------- graph
CREATE TABLE entities (
  entity_id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  type TEXT NOT NULL DEFAULT 'object',   -- person|project|device|object|concept|goal|decision|event|episode|file|skill|procedure|problem|solution|preference|hypothesis|fact|location|tool|model|outcome
  properties TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX ix_entities_type ON entities(type);

CREATE TABLE relationships (
  rel_id TEXT PRIMARY KEY,
  src TEXT NOT NULL,
  rel TEXT NOT NULL,        -- OWNS|USES|WORKS_ON|CREATED|DEPENDS_ON|PART_OF|RELATED_TO|CAUSED|CAUSED_BY|FAILED_BECAUSE|SOLVED_BY|REPLACED_BY|SUPERSEDES|PREFERS|PREFERS_FOR|REJECTED|REQUIRES|PRODUCED|OBSERVED_IN|SUPPORTED_BY|CONTRADICTED_BY|DERIVED_FROM|LEARNED_FROM|APPLIES_TO
  dst TEXT NOT NULL,
  valid_from TEXT,
  valid_until TEXT,
  confidence REAL NOT NULL DEFAULT 0.5,
  importance REAL NOT NULL DEFAULT 0.5,
  source_type TEXT NOT NULL DEFAULT 'hermes_inference',
  source_ref TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  last_verified TEXT,
  last_accessed TEXT,
  reinforcement_count INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'active'  -- active|superseded|contradicted|archived
);
CREATE INDEX ix_rel_src ON relationships(src);
CREATE INDEX ix_rel_dst ON relationships(dst);
CREATE INDEX ix_rel_status ON relationships(status);

-- -------------------------------------------------------------- beliefs
CREATE TABLE beliefs (
  belief_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL DEFAULT 'belief',   -- fact|belief|hypothesis|procedural_belief
  claim TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 0.5,
  importance REAL NOT NULL DEFAULT 0.5,
  status TEXT NOT NULL DEFAULT 'active', -- active|superseded|contradicted|archived
  derived_from TEXT NOT NULL DEFAULT '[]',
  related_entities TEXT NOT NULL DEFAULT '[]',
  valid_from TEXT,
  last_verified TEXT,
  reinforcement_count INTEGER NOT NULL DEFAULT 0,
  source_class TEXT NOT NULL DEFAULT 'hermes_inference',
  contradictions TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX ix_beliefs_status ON beliefs(status);
CREATE INDEX ix_beliefs_kind ON beliefs(kind);

CREATE TABLE belief_evidence (
  belief_id TEXT NOT NULL,
  evidence_id TEXT NOT NULL,
  PRIMARY KEY (belief_id, evidence_id)
);

-- ----------------------------------------------------------- procedures
CREATE TABLE procedures (
  procedure_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  steps TEXT NOT NULL DEFAULT '[]',
  prerequisites TEXT NOT NULL DEFAULT '[]',
  applicability TEXT NOT NULL DEFAULT '',
  confidence REAL NOT NULL DEFAULT 0.5,
  status TEXT NOT NULL DEFAULT 'candidate',   -- candidate|validated|skill_promoted
  derived_from TEXT NOT NULL DEFAULT '[]',
  success_count INTEGER NOT NULL DEFAULT 0,
  failure_count INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX ix_proc_status ON procedures(status);

-- -------------------------------------------------------------- vectors
CREATE TABLE vectors (
  vector_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,            -- episode|belief|entity
  target_id TEXT NOT NULL,
  dim INTEGER NOT NULL,
  vec BLOB NOT NULL,             -- float32 little-endian
  model TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE INDEX ix_vectors_target ON vectors(kind, target_id);

-- -------------------------------------------------------- consolidation
CREATE TABLE consolidation_runs (
  run_id TEXT PRIMARY KEY,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  summary TEXT NOT NULL DEFAULT '',
  changes TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE forget_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  target_kind TEXT NOT NULL,
  target_id TEXT NOT NULL,
  action TEXT NOT NULL,          -- access_decay|importance_decay|compression|supersession|archival|purge
  reason TEXT NOT NULL DEFAULT '',
  detail TEXT NOT NULL DEFAULT ''
);

CREATE TABLE retrieval_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  query TEXT NOT NULL,
  recalled TEXT NOT NULL DEFAULT '[]',
  session_id TEXT NOT NULL DEFAULT ''
);

-- ------------------------------------------------------- turn staging
CREATE TABLE turn_staging (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  turn_number INTEGER NOT NULL DEFAULT 0,
  ts TEXT NOT NULL,
  user_content TEXT NOT NULL DEFAULT '',
  assistant_content TEXT NOT NULL DEFAULT '',
  tools_used TEXT NOT NULL DEFAULT '[]',
  outcome TEXT NOT NULL DEFAULT 'unknown',
  importance_signals TEXT NOT NULL DEFAULT '[]',
  processed INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX ix_turn_staging_session ON turn_staging(session_id);

-- -------------------------------------------------------------- FTS5
CREATE VIRTUAL TABLE memory_fts USING fts5(
  body,
  target_kind UNINDEXED,
  target_id UNINDEXED
);
""",
        "down": """
DROP TABLE IF EXISTS memory_fts;
DROP TABLE IF EXISTS turn_staging;
DROP TABLE IF EXISTS retrieval_log;
DROP TABLE IF EXISTS forget_log;
DROP TABLE IF EXISTS consolidation_runs;
DROP TABLE IF EXISTS vectors;
DROP TABLE IF EXISTS procedures;
DROP TABLE IF EXISTS belief_evidence;
DROP TABLE IF EXISTS beliefs;
DROP TABLE IF EXISTS relationships;
DROP TABLE IF EXISTS entities;
DROP TABLE IF EXISTS episode_evidence;
DROP TABLE IF EXISTS evidence;
DROP TABLE IF EXISTS episodes;
DROP TABLE IF EXISTS mutation_log;
DROP TABLE IF EXISTS counters;
""",
    },
    2: {
        "description": "Rebuild memory_fts as a readable (non-contentless) FTS5 table; rows are reindexed from source tables automatically.",
        "up": """
DROP TABLE IF EXISTS memory_fts;
CREATE VIRTUAL TABLE memory_fts USING fts5(
  body,
  target_kind UNINDEXED,
  target_id UNINDEXED
);
""",
        "down": """
DROP TABLE IF EXISTS memory_fts;
CREATE VIRTUAL TABLE memory_fts USING fts5(
  body,
  target_kind UNINDEXED,
  target_id UNINDEXED,
  content=''
);
""",
    },
}

CURRENT_VERSION = max(MIGRATIONS.keys())


def migration_list() -> List[Dict[str, str]]:
    return [
        {"version": v, "description": MIGRATIONS[v]["description"],
         "up": MIGRATIONS[v]["up"], "down": MIGRATIONS[v]["down"]}
        for v in sorted(MIGRATIONS)
    ]
