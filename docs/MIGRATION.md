# Migrating Living Cortex to Hungry Hippa

Hungry Hippa is the product name for this local-first memory runtime. It was
formerly Living Cortex. This is not a healthcare-compliance product.

Do not run these steps against a database you cannot restore. Tests in this
repository use throwaway copies only.

## What changes

- Product name: Hungry Hippa
- Default new-install filename: `hungry_hippa.db`
- Environment: `HUNGRY_HIPPA_DB` (preferred)
- Schema migration v3 adds `product_meta` only
- Episode, belief, evidence, and graph **ids are not rewritten**
- Hermes plugin name stays `living-cortex` so `memory.provider` keeps working
- The `cortex` tool name stays the same

## What does not change

- Table names
- Existing memory rows
- WAL/FTS5 storage
- Acceptance tests T1–T10

## Backup and migrate

```bash
# Optional: point at a copy, never the only copy of production data
export HUNGRY_HIPPA_DB=/path/to/copy.db

hermes living-cortex migrate
# or
hermes living-cortex migrate --db /path/to/copy.db
```

`migrate` creates `*.pre-hippa-<UTC>.bak` via the SQLite backup API (WAL-safe)
then applies pending schema migrations in place.

An existing `$HERMES_HOME/living_cortex.db` is still discovered if
`hungry_hippa.db` is not present, so memories are not stranded by the rename.

## Deprecated configuration

| Old | New | Behavior |
|---|---|---|
| `LIVING_CORTEX_DB` | `HUNGRY_HIPPA_DB` | Still honored; emits `DeprecationWarning` |
| `living_cortex.db` | `hungry_hippa.db` | Existing file is preferred until a new file exists |
| `living_cortex_config.json` | `hungry_hippa_config.json` | Both are merged; new sidecar wins |

## Rollback

1. Stop agents using the database.
2. Restore the backup created by `migrate`:

   ```bash
   # Example: replace the migrated file with the pre-Hippa backup
   cp /path/to/living_cortex.db.pre-hippa-YYYYMMDDTHHMMSSZ.bak /path/to/living_cortex.db
   ```

3. Optionally set the old environment key while rolling back:

   ```bash
   export LIVING_CORTEX_DB=/path/to/living_cortex.db
   ```

4. Checkout the previous Git commit if you also need the pre-migration code:

   ```bash
   git checkout HEAD~1 -- schema.py config.py db.py
   ```

5. Confirm with `hermes living-cortex status` (counts only; do not export
   private memories to a ticket or log).

Schema v3 `down_sql` drops `product_meta` only. It does not delete episodes or
beliefs. There is no automatic down-migrator in the CLI; restoring the `.bak`
file is the supported rollback.

## Hermes compatibility

Keep:

```bash
hermes config set memory.provider living-cortex
```

The provider `name` remains `living-cortex`. Help text and the system prompt
identify the product as Hungry Hippa (formerly Living Cortex).
