# Maintenance: BM25 growth-recall regression

## Scope and reproduction

Baseline: `3cddd2adcd85362fba6627dedb87ac431aa7e518`, clean
`automation/hh-maintenance`, equal to fetched `origin/main`. All 30 baseline
runner steps passed, but the separately inspected growth fixture failed at every
size. The existing eval drift gate compares aggregate groups, not growth success;
its green result did not mean this known failure was resolved. Git history across
available branches showed no later change to `src/hungry_hippa/retrieval.py`.
The provider registration fix already exists on another branch and was not duplicated.

The original query is `what is the fixture jig torque value?`; the invented answer
is `45Nm`. The existing six-topic fixture supplies competing routine episodes.
FTS returns the precise belief first, but final recall previously drops it.

## Root cause and bounded fix

SQLite FTS5 BM25 is negative-is-better. `_rank` took
`max(vector_score, fts_score / 10, term_hits * 0.12)`, so nonnegative term/vector
scores always masked BM25. High-salience repetitive episodes outranked the fact.
Use `-fts_score / 10` instead. No other weights, limits, schemas, trust checks or
interfaces changed. Vector and term fallback remain available.

A fresh 100-episode probe returned raw BM25 scores -15.564372142504627 for the
belief and -4.6337741234179655 for the leading episode. After correction,
`explain` reports relevance 1.5564 versus 0.4634, and total scores 0.9594 versus
0.8559. This relevance heuristic is not a probability and is not bounded to one.

## Actual outcomes

| Synthetic episodes | Before: answer in context | After: answer in context |
|---|---|---|
| 100 | false | true |
| 500 | false | true |
| 2,000 | false | true |

Growth outcome: **0/3 before, 3/3 after**. All nine non-growth scenarios retained
`with.correct = true`. No comparative latency or general retrieval-quality claim.
Before measurement used clean baseline HEAD; after measurement used the same HEAD
with the retrieval fix and regression test uncommitted (`git_dirty = true`).
Historical `eval/results.json` is retained as a historical measurement, not silently
relabeled as this run. Full fresh outputs are in the maintenance state directory
(`before.json`, `before.md`, `after.json`, `after.md`).

Hardware: AMD Ryzen 9 9950X3D, 16 cores / 32 threads. Python 3.14.7,
Linux 7.2.5-3-omarchy x86_64, glibc 2.44. The harness disables vectors; deterministic
controller, no LLM judge, invented data and fresh temporary SQLite databases only.

## Verification

- `.venv/bin/python tests/test_memory_architecture.py`: first **FAIL 8/9**, specifically
  the new cross-process growth assertion; after the fix **PASS 9/9**.
- New regression writes 100 routine episodes plus a sourced belief, verifies FTS
  selection and negative score, then opens SQLite from a **second interpreter**.
  It checks the answer, belief ID, visible document provenance, source reference
  and configured context-character budget.
- `.venv/bin/python eval/harness.py --out /home/djr/.local/state/hungry-hippa-maintenance/before.json --report /home/djr/.local/state/hungry-hippa-maintenance/before.md --stdout`
  reproduced the three failures before the fix.
- The same command with `after.json` / `after.md` measured all three successes.
- `.venv/bin/python scripts/check_all.py`: **30/30 runner steps succeeded** before
  and after, including acceptance, migrations, SDK MCP, authorization/security,
  provenance, quarantine, ChatGPT/Hermes imports, extraction/reconciliation/E2E,
  vectors, backup, Hippo-Pot, demo, eval drift, benchmark smoke and wheel install.
- **SKIPPED / ENVIRONMENTAL:** two live chat checks (configured chat model unavailable)
  and two live embedding checks (default embedding service unavailable). Their
  containing suites report success; those four individual checks are not passes.
- `.venv/bin/python -m hungry_hippa.cli --help`: exit 0. Gate also exercises CLI
  import, quarantine and installed-wheel behavior using isolated stores.
- `git diff --check`: pass.

## Limits and next action

This fixes a demonstrated scoring defect, not every retrieval weakness. The
candidate window, word matching and BM25 scaling are unchanged. Growth results
are synthetic exact-token context checks, not imported-history answer quality.
No live stores, installed providers, model services or main branch were modified.
Next: audit integrated extraction/reconciliation against the ledger's pending
trust/checkpoint acceptance criteria and reproduce any remaining P1 failure.
