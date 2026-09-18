# Hungry Hippa Memory Challenge

Actual run: 2026-09-15T05:13:13.731904+00:00

Runtime revision: `710b604575a074c1c740c32145f312cdded03a20`. Vectors disabled; temporary databases only.

Summary: {'pass': 6, 'fail': 1, 'unsupported': 3}

| Scenario | Status | Evidence |
|---|---|---|
| 1. Cross-session factual recall | pass | {"with_memory": {"precision": 1.0, "recall_rate": 1.0, "incorrect_memory_rate": 0.0, "context_chars": 86, "latency_ms": 1.942801}, "without_memory": {"precision": null, "recall_rate": 0.0, "incorrect_memory_rate": null, "context_chars": 0, "latency_ms": 0.55319}, "baseline": "Empty controller DB; no conversation or model", "scope": "Structured recall, not proof of an agent choosing an action"} |
| 2. Decision and rationale | pass | {"with_memory": {"precision": 1.0, "recall_rate": 1.0, "incorrect_memory_rate": 0.0, "context_chars": 166, "latency_ms": 0.879621}, "without_memory": {"precision": null, "recall_rate": 0.0, "incorrect_memory_rate": null, "context_chars": 0, "latency_ms": 0.51118}, "baseline": "Empty controller DB; no conversation or model", "scope": "Structured recall, not proof of an agent choosing an action"} |
| 3. Previously failed solution context | pass | {"with_memory": {"precision": 1.0, "recall_rate": 1.0, "incorrect_memory_rate": 0.0, "context_chars": 210, "latency_ms": 0.858521}, "without_memory": {"precision": null, "recall_rate": 0.0, "incorrect_memory_rate": null, "context_chars": 0, "latency_ms": 0.504221}, "baseline": "Empty controller DB; no conversation or model", "scope": "Structured recall, not proof of an agent choosing an action"} |
| 4. Superseded information | pass | {"precision": 1.0, "recall_rate": 1.0, "incorrect_memory_rate": 0.0, "context_chars": 117, "latency_ms": 0.834031} |
| 5. Fixed character budget | fail | Renderer accepts an oversized first item; structured items are also uncapped by chars. |
| 6. Cross-agent authorized portability | unsupported | Session IDs share a DB, but no actor ACL exists. Scenario 1 tests session persistence only. |
| 7. User-directed forgetting | pass | {"excluded_from_recall": true, "retained_as_archive": true, "secure_erasure_tested": false} |
| 8. Poisoned memory resistance | unsupported | No quarantine API or enforcement in this baseline; no LLM injection-resistance test performed. |
| 9. Unauthorized retrieval | unsupported | No caller permission checks on recall; denial accuracy cannot be measured. |
| 10. Performance as DB grows | pass | N=10: median 2.668 ms, 217088 bytes; N=100: median 2.973 ms, 262144 bytes; N=1000: median 3.595 ms, 724992 bytes |

## Interpretation

Small synthetic controller checks establish retrieval behavior only. Exact queries and an empty-DB control make these easy cases; they do not measure model quality, semantic generalization, or autonomous failure avoidance. Precision and incorrect-memory rate use the explicitly expected ID set, not factual truth judgments.

The character-budget failure is retained as a baseline defect, not hidden by truncating in the harness. Archival forgetting is not secure deletion. Latency is host-dependent and includes retrieval writes; sizes include DB/WAL/SHM after warm-up and measured queries, not just payload storage. No performance threshold is asserted.

Token counts, agent-quality improvement, actual repeated-failure avoidance, and permission-denial accuracy are unsupported. See [results.json](results.json) for raw measurements and environment.
