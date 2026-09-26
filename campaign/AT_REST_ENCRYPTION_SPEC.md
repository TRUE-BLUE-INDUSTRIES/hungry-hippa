# At-rest encryption for the memory database (SQLCipher)

**Status:** implemented on `feat/dolphinbench-campaign` — not yet committed/pushed
**Branch:** `feat/dolphinbench-campaign`
**Owner:** DJ (operator) — commit/push gated on your go

## Why

The memory DB is plaintext SQLite. The code already says so in three places
(`db.py:112`, `policy.py:22`, `hippo_pot.py:341` warns "database is plaintext
SQLite; use OS/disk encryption"). `0600` perms stop *other local users*; they do
nothing against a stolen laptop, a forensic image, or a `dd` of the disk. For an
always-on appliance (the hippo pot) that holds private conversations, the file
must be unreadable without the key even while the box is running.

## Decision

**SQLCipher** (column-level, transparent to the app), keyed off the **existing
owner token** (`$XDG_STATE_HOME/hungry-hippa/owner.token`, already `0600`, already
the identity root). Not LUKS: an always-on appliance is usually running, so a
disk-level key is in memory anyway; SQLCipher protects the file regardless of
process state.

## Design

### 1. Dependency
- Added `sqlcipher3>=0.6.2` as an optional extra, not a hard dep:
  `[project.optional-dependencies] encrypt = ["sqlcipher3>=0.6.2"]`.
- Hard dep stays `mcp` only. Encryption is opt-in; a plaintext install keeps
  working unchanged. This preserves the "no new hard deps" discipline.
- **Driver note:** the original `pysqlcipher3` (1.2.0) does not build on
  Python 3.14 (uses removed CPython APIs `PyObject_AsCharBuffer`,
  `_PyLong_AsInt`). The maintained fork `sqlcipher3` 0.6.2 ships a prebuilt
  cp314 wheel and is the driver actually used. The system `sqlcipher` C library
  (Arch `extra/sqlcipher` 4.18) was installed to support it.

### 2. Config toggle
- New key in `config.DEFAULTS`:
  ```python
  "encryption": {
      "enabled": False,          # opt-in; default off
      "key_source": "owner_token",  # only supported source for now
  }
  ```
- Env override: `HUNGRY_HIPPA_ENCRYPT=1` (mirrors `HUNGRY_HIPPA_DB`).
- `hippo_pot.py` and `cli.py` read this; when enabled and the driver is missing,
  fail loudly at startup with an actionable message ("install the encrypt extra:
  `pip install hungry-hippa[encrypt]`"), not a silent plaintext fallback.

### 3. Connection layer (`db.py`)
- `_connect()` becomes key-aware. When encryption is enabled:
  ```python
  import pysqlcipher3.dbapi2 as sqlite3   # drop-in, same API
  conn = sqlite3.connect(self.path, timeout=30.0)
  conn.execute(f"PRAGMA key = '{key}'")   # key from owner token
  ```
  then the existing PRAGMAs (WAL, busy_timeout, foreign_keys, synchronous).
- Key derivation: **not** the raw token as the passphrase. Derive a 32-byte key
  with `hashlib.scrypt(token, salt=db_path, n=2**14, r=8, p=1)` so the token and
  the key are not the same secret, and a copied DB file doesn't carry a
  reusable key. Salt is the absolute DB path (stable per file, not secret).
- The driver import is isolated in one helper (`_sqlite_driver()`); every other
  module imports `sqlite3` from `db` or uses `Database._connect()`, so the swap
  is contained. **Audit all `import sqlite3` sites** — `cli.py`, `semantic.py`,
  `episodic.py`, `ingest/*`, `mcp_server.py` must route through `Database`, not
  open the file directly. Any direct `sqlite3.connect(path)` bypasses the key.

### 4. Migration path (plaintext → encrypted)
- New CLI subcommand `hungry-hippa encrypt <db>` (and `decrypt` for recovery):
  1. Verify the target is currently plaintext (open without key succeeds).
  2. Create `<db>.encrypted` with the key set.
  3. Copy via `ATTACH ... KEY ''` + `sqlcipher_export` (the canonical SQLCipher
     migration path). `backup()` is NOT used: it rejects a keyed destination
     and mixed driver types. The WAL-mode source is checkpointed first so the
     attach sees all data.
  4. `PRAGMA integrity_check` on the new file.
  5. Atomic swap: rename old → `.bak`, new → live. Keep the `.bak` (matches the
     standing "never delete" rule — a backup is a superseded artifact, kept).
     `decrypt` uses a distinct `.encrypted.bak` suffix so an encrypt-then-decrypt
     round trip does not collide.
  6. Operator-only: requires the owner token; refuses without it.
- Reverse (`decrypt`) is the same in the other direction, for operator recovery.
- **Never auto-migrate on open.** A plaintext DB must not silently become
  encrypted (or vice versa) without an explicit operator command.

### 5. Sidecars
- WAL/SHM files are covered by the same key (SQLCipher encrypts the whole file
  family). `file_permissions()` note text updates: "permissions are not
  encryption" → "encryption is on/off" as appropriate.

### 6. Tests (one named regression test per property, wired into `check_all.py`)
- `check_encrypted_db_unreadable_without_key` — write with key, open with
  `sqlite3` (no key) → `DatabaseError`/garbage, not rows.
- `check_encrypted_db_readable_with_key` — same file, key set → rows read.
- `check_encrypt_migration_preserves_rows` — plaintext → `encrypt` → counts and
  a sample claim match; integrity_check passes.
- `check_encrypt_requires_operator` — untrusted actor / no owner token → refused,
  audited.
- `check_plaintext_default_unchanged` — encryption off → file is plaintext,
  existing suite still green (no behavior change when off).
- `check_missing_driver_fails_loudly` — enabled but `pysqlcipher3` absent →
  clear error, no silent plaintext fallback.

### 7. Docs
- `docs/` note: encryption is opt-in, keyed off the owner token, and the token
  file is the single secret that unlocks it — losing it loses the memories
  (no recovery). State the limitation in a test (per the security skill: write
  the limitation into a test so a later session can't upgrade the claim).

## Out of scope (explicitly)
- No per-field encryption (breaks FTS/retrieval; sensitivity stays a read-policy
  label, not crypto).
- No TCP/HTTP listener or per-request auth (stdio + startup token is correct).
- No auto-migration on open.
- No new hard dependency.

## Decisions made (2026-09-25, "do what you think is best")
1. **Key source:** owner token only. A separate passphrase would be a second
   secret to lose; the token is already the identity root.
2. **Default:** opt-in (off). Existing installs and the `check_all.py` suite are
   untouched; encryption is enabled by `HUNGRY_HIPPA_ENCRYPT=1` or the `encrypt`
   command.
3. **Timing:** built now. The migration command is operator-invoked, so building
   the feature never touches the live DB; the running extract writes to the
   dedicated ChatGPT DB, not the production store.

## Deliverable when implemented
Per the security skill: one commit per fix, a named regression test per fix
wired into `check_all.py`, a report that states what was attacked, what changed,
and what remains weak (token file is the single point of failure; a lost token
is unrecoverable). No push without your go.
