# Roadmap

The first milestone is install → import → review/extract → recall with provenance
→ correct/delete → backup/restore. It is not yet complete. Status and evidence
live in [PROJECT_STATE.md](PROJECT_STATE.md) and [tasks.json](tasks.json).

1. **Current increment:** bounded ChatGPT import, exact raw bytes, stable repeat
   imports, per-export provenance, inspection, integrity and backup recovery.
2. **Safe extraction:** fix malformed-response checkpointing and prompt truncation
   in existing prototypes. Persist candidates and checkpoints transactionally;
   retain evidence links, quarantine and explicit review before ordinary recall.
   Rebase experimental migrations before integration.
3. **Corrections and recall:** prevent quarantined reconciliation from strengthening
   or superseding approved facts. Add explicit correction/delete/restore CLI flows.
   Capture the existing growth-recall/BM25 regression before changing ranking.
4. **Adapters and dogfooding:** reuse canonical shapes for Hermes, Claude, generic
   JSON/JSONL, Markdown/TXT and later Gemini/Grok/HTML. Add format detection with
   bounded adapter-specific validation. Use authorized real development histories
   locally after adapter and extraction checks; never publish private fixtures.
5. **External evaluation:** pinned LongMemEval evidence retrieval first, then
   complementary datasets, vector/hybrid ablations and supported quality metrics.
   See [BENCHMARKS.md](BENCHMARKS.md); no ranking claims before comparable runs.
6. **Security and interoperability:** encrypted backup design/key recovery,
   dependency scanning, revocable scoped clients, audit integrity, optional hardened
   API. Local mode remains independent of cloud services.
7. **Control Center and demo:** build on stable APIs; show correct recall, original
   evidence and a propagated correction in a short demo. UI does not block the CLI.

Sponsorship supports open-source delivery of these priorities, not private
functionality; [SUPPORT.md](SUPPORT.md) records the remaining account-owner steps.
