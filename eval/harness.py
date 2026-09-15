#!/usr/bin/env python3
"""Deterministic controller checks. Exit 1 means a measured behavior failed."""
from __future__ import annotations
import hashlib
import json
import platform
import sqlite3
import statistics
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from runtime import ROOT, controller

HERE = Path(__file__).resolve().parent


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def ids(out):
    require('error' not in out, str(out.get('error')))
    return {i.get('episode_id') or i.get('belief_id') for i in out['items']}


def scored(c, query, expected):
    start = time.perf_counter_ns()
    out = c.recall(query)
    elapsed = (time.perf_counter_ns() - start) / 1e6
    found = ids(out)
    correct = len(found & expected)
    metrics = dict(precision=correct / len(found) if found else None,
                   recall_rate=correct / len(expected),
                   incorrect_memory_rate=len(found - expected) / len(found) if found else None,
                   context_chars=len(out['context']), latency_ms=elapsed)
    return out, metrics


def run():
    seed = json.loads((HERE / 'seed.json').read_text())
    rows = []
    def check(number, name, fn):
        try:
            detail = fn()
            rows.append(dict(id=number, name=name, status='pass', measurements=detail))
        except Exception as exc:
            rows.append(dict(id=number, name=name, status='fail', reason=f'{type(exc).__name__}: {exc}'))
    def unsupported(number, name, reason):
        rows.append(dict(id=number, name=name, status='unsupported', reason=reason))
    with tempfile.TemporaryDirectory(prefix='hippa-eval-') as tmp:
        base = Path(tmp)
        def recall_case(key, query, fields=None):
            path = base / f'{key}.db'
            c = controller(path)
            if fields is None:
                target = c.semantic.add_belief(seed['fact'], kind='fact', source_class='user_explicit')['belief_id']
            else:
                target = c.remember_episode(**fields, participants=seed['operator'], project=seed['project'], importance=.8, embed=False)['episode_id']
            c.close_session()
            del c
            c = controller(path, 'session-two')
            out, metrics = scored(c, query, {target})
            require(target in ids(out), 'expected memory absent')
            if fields:
                item = next(i for i in out['items'] if i.get('episode_id') == target)
                for field, value in fields.items():
                    require(item[field] == value, f'{field} lost')
            empty = controller(base / f'{key}-without.db', 'session-two')
            _, without = scored(empty, query, {target})
            return dict(with_memory=metrics, without_memory=without,
                        baseline='Empty controller DB; no conversation or model',
                        scope='Structured recall, not proof of an agent choosing an action')
        check(1, 'Cross-session factual recall', lambda: recall_case('fact', 'packaging'))
        check(2, 'Decision and rationale', lambda: recall_case('decision', 'transport', seed['decision']))
        check(3, 'Previously failed solution context', lambda: recall_case('failure', 'timeout', seed['failure']))
        def supersession():
            c = controller(base / 'supersede.db')
            old = c.semantic.add_belief('Project A transport uses polling.', source_class='user_explicit')['belief_id']
            new = c.supersede(old, 'Project A transport uses a queue.', reason='Operator correction')['belief_id']
            out, metrics = scored(c, 'transport', {new})
            require(new in ids(out) and old not in ids(out), 'current replacement must be retrieved alone')
            require(c.semantic.get_belief(old)['status'] == 'superseded', 'history lost')
            return metrics
        check(4, 'Superseded information', supersession)
        def budget():
            c = controller(base / 'budget.db', budget=120)
            c.remember_episode(context='budgetprobe ' + 'long context ' * 100, importance=.8, embed=False)
            out = c.recall('budgetprobe')
            require(bool(ids(out)), 'budget check must retrieve an item')
            actual = len(out['context'])
            # Preserve actual measurements even when the public renderer exceeds its cap.
            return dict(budget_chars=120, actual_chars=actual, within_budget=actual <= 120,
                        structured_items_capped=False)
        check(5, 'Fixed character budget', budget)
        if rows[-1]['status'] == 'pass' and not rows[-1]['measurements']['within_budget']:
            rows[-1].update(status='fail', reason='Renderer accepts an oversized first item; structured items are also uncapped by chars.')
        unsupported(6, 'Cross-agent authorized portability', 'Session IDs share a DB, but no actor ACL exists. Scenario 1 tests session persistence only.')
        def forgetting():
            c = controller(base / 'forget.db')
            target = c.remember_episode(context='forgetprobe temporary note', importance=.8, embed=False)['episode_id']
            require(target in ids(c.recall('forgetprobe')), 'precondition: memory not recalled')
            require(c.forget('episode', target, reason='Operator request')['archived'], 'archive failed')
            require(target not in ids(c.recall('forgetprobe')), 'archived memory still recalled')
            require(c.episodic.get_episode(target)['status'] == 'archived', 'archive not preserved')
            return dict(excluded_from_recall=True, retained_as_archive=True, secure_erasure_tested=False)
        check(7, 'User-directed forgetting', forgetting)
        unsupported(8, 'Poisoned memory resistance', 'No quarantine API or enforcement in this baseline; no LLM injection-resistance test performed.')
        unsupported(9, 'Unauthorized retrieval', 'No caller permission checks on recall; denial accuracy cannot be measured.')
        def growth():
            samples = []
            for n in (10, 100, 1000):
                path = base / f'growth-{n}.db'
                c = controller(path)
                for i in range(n):
                    c.remember_episode(context=f'growthprobe synthetic sample {i:04d}', importance=.5, embed=False)
                require(c.status()['counts']['episodes'] == n, 'seed count mismatch')
                c.recall('growthprobe')  # warm-up; recall includes touch/log writes
                latencies = []
                for _ in range(15):
                    start = time.perf_counter_ns()
                    out = c.recall('growthprobe')
                    latencies.append((time.perf_counter_ns() - start) / 1e6)
                    require(len(ids(out)) == 6, 'growth query did not return six items')
                sizes = {suffix or 'db': Path(str(path) + suffix).stat().st_size
                         for suffix in ('', '-wal', '-shm') if Path(str(path) + suffix).exists()}
                samples.append(dict(episodes=n, repeats=15, median_ms=statistics.median(latencies),
                                    min_ms=min(latencies), max_ms=max(latencies), samples_ms=latencies,
                                    storage_bytes=sum(sizes.values()), file_bytes=sizes))
            return dict(samples=samples, workload='All rows match; top six; one warm-up; sequential calls including reinforcement and retrieval logging')
        check(10, 'Performance as DB grows', growth)
    report = dict(product='Hungry Hippa', generated_at=datetime.now(timezone.utc).isoformat(),
                  revision=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                  python=platform.python_version(), sqlite=sqlite3.sqlite_version, platform=platform.platform(),
                  seed_sha256=hashlib.sha256((HERE / 'seed.json').read_bytes()).hexdigest(),
                  vectors_enabled=False, scenarios=rows,
                  unsupported_metrics={'context_tokens': 'No tokenizer/model; exact characters measured instead.',
                    'repeated_failure_avoidance': 'Stored failure context tested; no acting agent or LLM judge.',
                    'permission_denial_accuracy': 'No actor ACL.',
                    'agent_quality_delta': 'Empty-DB comparison is a retrieval control, not an agent benchmark.'})
    report['summary'] = {s: sum(r['status'] == s for r in rows) for s in ('pass', 'fail', 'unsupported')}
    (HERE / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
    lines = ['# Hungry Hippa Memory Challenge', '', f"Actual run: {report['generated_at']}", '',
             f"Runtime revision: `{report['revision']}`. Vectors disabled; temporary databases only.", '',
             f"Summary: {report['summary']}", '', '| Scenario | Status | Evidence |', '|---|---|---|']
    for row in rows:
        detail = row.get('reason') or json.dumps(row['measurements'])
        if row['id'] == 10 and row['status'] == 'pass':
            detail = '; '.join(f"N={s['episodes']}: median {s['median_ms']:.3f} ms, {s['storage_bytes']} bytes" for s in row['measurements']['samples'])
        lines.append(f"| {row['id']}. {row['name']} | {row['status']} | {detail} |")
    lines += ['', '## Interpretation', '',
              'Small synthetic controller checks establish retrieval behavior only. Exact queries and an empty-DB control make these easy cases; they do not measure model quality, semantic generalization, or autonomous failure avoidance. Precision and incorrect-memory rate use the explicitly expected ID set, not factual truth judgments.', '',
              'The character-budget failure is retained as a baseline defect, not hidden by truncating in the harness. Archival forgetting is not secure deletion. Latency is host-dependent and includes retrieval writes; sizes include DB/WAL/SHM after warm-up and measured queries, not just payload storage. No performance threshold is asserted.', '',
              'Token counts, agent-quality improvement, actual repeated-failure avoidance, and permission-denial accuracy are unsupported. See [results.json](results.json) for raw measurements and environment.']
    (HERE / 'REPORT.md').write_text('\n'.join(lines) + '\n')
    print(json.dumps(report['summary']))
    return int(report['summary']['fail'] > 0)

if __name__ == '__main__':
    raise SystemExit(run())
