# Contributing to Hungry Hippa

Thanks for looking. This is a local-first memory runtime for AI agents, written in plain
Python with SQLite. It is small on purpose.

## Before you send a change

Run all of these and make sure they pass. They are the project's gate; there is no other
CI requirement.

```bash
python scripts/check_all.py               # runs everything below, one after another
```

Individually:

```bash
python tests/test_acceptance.py           # 10/10 — spec acceptance tests T1-T10
python tests/test_migration.py            # 6/6  — rename + DB migration compatibility
python tests/test_memory_architecture.py  # 8/8  — quarantine, explain, context budget
python tests/test_mcp_schema.py           # 11/11 — MCP schemas, policy, stdio
python tests/test_security.py             # 10/10 — limits, redaction, injection, no-export
python demo/demo.py --check               # demo transcript matches the captured output
python eval/harness.py                    # regenerates eval/results.json + REPORT.md
```

Each file is standalone: it has a `run_all()` function and a `__main__` block, and exits
non-zero on failure. Pytest is optional and not required.

If your change alters behaviour, update the relevant document (`README.md`,
`docs/…`) in the same change. Documentation that contradicts the code is a bug.

## Hard rules

1. **Standard library only.** No third-party runtime dependency without a one-line
   documented benefit in the commit message. This is what keeps installation a copy and
   an offline runtime possible.
2. **Never silently delete or rewrite a memory.** Supersede, contradict, compress or
   archive. Purge is explicit, owner-only and confirm-gated.
3. **Never introduce a claim that no test, measurement or file supports.** If it is
   unverified, say so in the text (the existing docs do this constantly — see
   `docs/MCP.md`'s untested client snippet and `eval/README.md`'s unsupported metrics).
4. **Tests use throwaway databases only.** Never open `$HERMES_HOME/living_cortex.db` or
   `hungry_hippa.db` from a test, demo or harness. Use `tempfile`.
5. **Do not print secrets or private memories**, in tests, logs, commits or issues.
   Fixtures must be invented (`Operator`, `Project A`, `Vendor A`), not scraped.
6. **Do not call the project** unhackable, conscious, self-learning, enterprise-ready, or
   a healthcare product. The name is *Hungry Hippa*, not HIPAA.
7. **Additive compatibility.** The Hermes plugin name (`living-cortex`), the `cortex`
   tool name and existing table names stay. New behaviour goes behind new fields,
   new actions or new modules.
8. **Migrations are reversible.** Every entry in `schema.py`'s `MIGRATIONS` needs a
   `down` script and constant defaults for new columns, so existing rows are untouched.

## Style

- Match the surrounding code: `from __future__ import annotations`, type hints on public
  functions, docstrings that explain *why* rather than restating the code.
- Keep SQL parameterized. The only string interpolation into SQL should be fixed internal
  table/column names chosen from literals.
- Prefer a small, testable function over a configurable framework.
- Comments should carry information the code does not (a constraint, a past failure, a
  reason a simpler approach was rejected).

## Commits

Conventional-prefix messages, one logical change per commit:

```
feat: add quarantine, explainable recall, and context compiler
test: add Hungry Hippa memory challenge harness and results
security: add request limits, threat model, and MCP auth tests
docs: package Hungry Hippa for a first-time installer
fix: ...
```

In the body, record what you actually ran: the commands and their real results. Do not
claim a test passed if you did not run it, and do not describe work you intend to do as
if it were done.

## Adding a test

Put it in the relevant `tests/test_*.py` file using the existing pattern:

```python
def check_something():
    ctrl, db_path = _fresh("hh_prefix_")     # throwaway temp database
    ...
    assert expected, debug_context
    return "one line describing what was verified"
```

Register it in `run_all()` with `check("name", check_something)`. New suites follow the
same shape (`run_all()` + `__main__`) so CI can just call the file.

## Reporting a bug

Include: the command you ran, what you expected, what happened, and whether the memory
database, the MCP surface or the Hermes plugin is involved. **Do not attach a real
memory database or real credentials.** A redacted or invented reproduction is enough.

Security issues: see [SECURITY.md](SECURITY.md).

## License

By contributing you agree your contribution is licensed under the MIT License
(see [LICENSE](LICENSE)).
