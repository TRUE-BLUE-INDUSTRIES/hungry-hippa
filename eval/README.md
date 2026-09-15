# Hungry Hippa Memory Challenge

Run from the repository root with Python 3 and SQLite FTS5:

```sh
python eval/harness.py
```

Always writes `eval/results.json` and `eval/REPORT.md` after all ten scenarios. Exit 1 means a measured check failed; the Phase 2 renderer currently exceeds its character cap for an oversized first item. Unsupported scenarios do not count as passes or cause failure.

The standard-library harness uses synthetic Operator / Project A data from `seed.json`, explicit throwaway DB paths, copied built-in configuration, disabled vectors, and disabled session-end consolidation. It never loads operator configuration or the production database. Temporary databases are removed automatically. No model, network, or Hermes installation is required.

Scenarios 1–3 compare a seeded controller with an empty controller DB using the same query. This is a no-memory retrieval control, not an LLM/agent A/B test. A new controller and session ID read persisted rows. Decision fields and failure outcome/result are checked in structured items; the renderer does not include every structured field. Authorized cross-agent sharing, quarantine, and permissions remain unsupported.

Growth uses fresh DBs of 10, 100, and 1,000 episodes, one warm-up and 15 timed recalls per size. Raw timings and DB/WAL/SHM sizes are saved. Functional checks are deterministic; IDs, timestamps, storage allocation and timings may vary. Reruns overwrite the two result artifacts. No core changes are made to make a failing check pass.
