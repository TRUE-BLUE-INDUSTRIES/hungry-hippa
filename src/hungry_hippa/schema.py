"""Hungry Hippa SQLite schema and reversible migrations (§19.10).

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
  kind TEXT NOT NULL,       -- user_explicit|document|tool_result|visual_observation|audio_observation|external_source|agent_inference|derived_pattern
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
  source_type TEXT NOT NULL DEFAULT 'agent_inference',
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
  source_class TEXT NOT NULL DEFAULT 'agent_inference',
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
    3: {
        "description": "Hungry Hippa product metadata (formerly Living Cortex). No table renames; existing memories unchanged.",
        "up": """
CREATE TABLE IF NOT EXISTS product_meta (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  product_name TEXT NOT NULL,
  formerly TEXT NOT NULL,
  migrated_at TEXT NOT NULL
);
INSERT OR IGNORE INTO product_meta(id, product_name, formerly, migrated_at)
VALUES (1, 'Hungry Hippa', 'Living Cortex', datetime('now'));
""",
        "down": """
DROP TABLE IF EXISTS product_meta;
""",
    },
    4: {
        "description": "Hungry Hippa memory architecture: sensitivity label, quarantine flag and actor_id on episodes and beliefs. Constant defaults only; existing rows and ids are unchanged.",
        "up": """
ALTER TABLE episodes ADD COLUMN sensitivity TEXT NOT NULL DEFAULT 'unclassified';
ALTER TABLE episodes ADD COLUMN quarantined INTEGER NOT NULL DEFAULT 0;
ALTER TABLE episodes ADD COLUMN actor_id TEXT NOT NULL DEFAULT 'primary';
ALTER TABLE beliefs ADD COLUMN sensitivity TEXT NOT NULL DEFAULT 'unclassified';
ALTER TABLE beliefs ADD COLUMN quarantined INTEGER NOT NULL DEFAULT 0;
ALTER TABLE beliefs ADD COLUMN actor_id TEXT NOT NULL DEFAULT 'primary';
CREATE INDEX ix_episodes_quarantined ON episodes(quarantined);
CREATE INDEX ix_beliefs_quarantined ON beliefs(quarantined);
CREATE INDEX ix_episodes_actor ON episodes(actor_id);
CREATE INDEX ix_beliefs_actor ON beliefs(actor_id);
""",
        "down": """
DROP INDEX IF EXISTS ix_beliefs_actor;
DROP INDEX IF EXISTS ix_episodes_actor;
DROP INDEX IF EXISTS ix_beliefs_quarantined;
DROP INDEX IF EXISTS ix_episodes_quarantined;
ALTER TABLE beliefs DROP COLUMN actor_id;
ALTER TABLE beliefs DROP COLUMN quarantined;
ALTER TABLE beliefs DROP COLUMN sensitivity;
ALTER TABLE episodes DROP COLUMN actor_id;
ALTER TABLE episodes DROP COLUMN quarantined;
ALTER TABLE episodes DROP COLUMN sensitivity;
""",
    },
    5: {
        "description": "Provenance split: claimed vs verified source class, plus the writing actor and the ingestion channel, on episodes and beliefs. The existing source_class column keeps its meaning as the effective (verified) class used for trust weighting; existing rows keep their value in both new columns.",
        "up": """
ALTER TABLE episodes ADD COLUMN claimed_source_class TEXT NOT NULL DEFAULT '';
ALTER TABLE episodes ADD COLUMN verified_source_class TEXT NOT NULL DEFAULT '';
ALTER TABLE episodes ADD COLUMN source_actor TEXT NOT NULL DEFAULT '';
ALTER TABLE episodes ADD COLUMN ingestion_channel TEXT NOT NULL DEFAULT '';
ALTER TABLE beliefs ADD COLUMN claimed_source_class TEXT NOT NULL DEFAULT '';
ALTER TABLE beliefs ADD COLUMN verified_source_class TEXT NOT NULL DEFAULT '';
ALTER TABLE beliefs ADD COLUMN source_actor TEXT NOT NULL DEFAULT '';
ALTER TABLE beliefs ADD COLUMN ingestion_channel TEXT NOT NULL DEFAULT '';
UPDATE episodes SET source_actor = actor_id WHERE source_actor = '';
UPDATE beliefs SET claimed_source_class = source_class, verified_source_class = source_class, source_actor = actor_id WHERE claimed_source_class = '';
CREATE INDEX ix_episodes_verified_source ON episodes(verified_source_class);
CREATE INDEX ix_beliefs_verified_source ON beliefs(verified_source_class);
""",
        "down": """
DROP INDEX IF EXISTS ix_beliefs_verified_source;
DROP INDEX IF EXISTS ix_episodes_verified_source;
ALTER TABLE beliefs DROP COLUMN ingestion_channel;
ALTER TABLE beliefs DROP COLUMN source_actor;
ALTER TABLE beliefs DROP COLUMN verified_source_class;
ALTER TABLE beliefs DROP COLUMN claimed_source_class;
ALTER TABLE episodes DROP COLUMN ingestion_channel;
ALTER TABLE episodes DROP COLUMN source_actor;
ALTER TABLE episodes DROP COLUMN verified_source_class;
ALTER TABLE episodes DROP COLUMN claimed_source_class;
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
