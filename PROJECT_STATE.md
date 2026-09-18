# Project state

Verified baseline: [2026-09-18 inspection](docs/baseline-2026-09-18.md).
Released version is 1.0.0, main/tag SHA
`9b9593f62b76c044470f9bc5684656aadb3f07d9`. This branch is
`codex/first-usable-ingestion`; branch work is not yet released.

Current cycle: preserve and harden the existing canonical ingestion prototype
for safe ChatGPT import. Existing checkouts, unmerged feature branches and
operator memory stores are preserved. Git remains authoritative for code.

Baseline validation is running in an isolated environment. Next: reuse the
canonical store and explicit CLI apply path, add adversarial input/provenance
checks, run regression and packaging gates, measure ingestion, document and
push the verified feature branch. Do not claim the full import-to-memory
milestone is complete until extraction, review, recall and restore are tested.
