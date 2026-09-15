# License notes

Hungry Hippa is released under the **MIT License** — see [../LICENSE](../LICENSE).
Copyright (c) 2026 True Blue Industries.

This file records the license review: what the project depends on, what it does not, and
which parts of the repository are covered by what.

## Runtime dependencies

**None beyond the Python standard library.** The runtime imports only `sqlite3`, `json`,
`os`, `sys`, `re`, `math`, `time`, `threading`, `logging`, `hashlib`, `argparse`,
`importlib`, `io`, `struct`, `subprocess`, `tempfile`, `shutil`, `platform`, `statistics`,
`datetime`, `pathlib`, `typing`, `warnings`, `difflib`, `types`, `ast`, `urllib` and
`__future__`, plus the official Model Context Protocol SDK, which is the one runtime
dependency and is declared in `pyproject.toml`.

Hungry Hippa imports nothing from any host application: it owns its own
configuration (`$XDG_CONFIG_HOME/hungry-hippa/config.json`), data
(`$XDG_DATA_HOME/hungry-hippa/`) and state (`$XDG_STATE_HOME/hungry-hippa/`)
locations. The MCP surface is built on the official SDK; the in-process adapter is
plain library code for whatever host wants it.

`urllib` is used only for the optional local Ollama embedding request to
`http://127.0.0.1:11434`. It is stdlib, not a dependency, and it is not called when
`retrieval.vectors_enabled` is false.

That means there are no transitive dependency licenses to reconcile, and no third-party
code shipped in this repository.

## Optional, not bundled

| Thing | Status |
|---|---|
| Ollama + `nomic-embed-text` | Optional local embedding server. Not bundled, not required, not called unless `retrieval.vectors_enabled` is true. Governed by its own licenses (Ollama's MIT, and the model's own license). Recall degrades to keyword + graph without it. |
| Hermes Agent | The host application this plugin targets. Separate project, separate license. Not included here. |
| MCP client software (Grok CLI, Claude Code, Cursor, …) | Third-party, not bundled. `docs/MCP.md` shows configuration only, and no client has been run against this server. |
| SQLite | Used through Python's standard `sqlite3` module (public domain). No vendored amalgamation. |

## Content licenses

- Source code, tests, harness, demo and fixtures: MIT (this repository).
- Documentation in `docs/`, `README.md`, `CONTRIBUTING.md`, `SECURITY.md`,
  `CHANGELOG.md`: MIT (this repository).
- `demo/seed.json`, `eval/fixtures.json`: authored for this project, invented values, MIT.
  They contain no personal information and no third-party text.
- The Grok CLI `[mcp_servers.*]` configuration snippet in `docs/MCP.md` was transcribed
  from Grok's own user guide installed on the author's machine, for interoperability
  documentation. It is configuration syntax, not copyrightable expression, and no Grok
  code is copied. No client was tested.

## Trademarks and naming

- **Hungry Hippa** is the product name. It is not related to HIPAA, and this project
  makes no healthcare or compliance claims.
- **Living Cortex** is the former name of this same project; the rename and its
  compatibility path are described in `docs/MIGRATION.md`.
- **Hermes**, **Grok**, **Claude**, **Cursor**, **Ollama** and their marks belong to their
  respective owners. They are referenced for interoperability and compatibility only; this
  project is not affiliated with or endorsed by any of them.
- **MCP** (Model Context Protocol) is a specification, not a product of this project.
  Implementing a transport for a public specification does not make the protocol
  proprietary to anyone.

## Contributions

Contributions are accepted under the MIT License (see `CONTRIBUTING.md`). There is no
contributor license agreement and no copyright assignment.

## Review outcome

- [x] No third-party runtime dependency, so no dependency-license obligations
- [x] No vendored or copied third-party source
- [x] No bundled binary, model weights or dataset
- [x] Fixtures and demo data are authored and contain no personal information
- [x] `LICENSE` matches the intent: permissive, MIT, no warranty
- [x] No patent or trademark claim is made by this repository
