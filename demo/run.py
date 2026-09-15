#!/usr/bin/env python3
"""Run the entire demo against an automatically removed temporary database."""
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'eval'))
from runtime import controller


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def main():
    seed = json.loads((HERE / 'seed.json').read_text())
    with tempfile.TemporaryDirectory(prefix='hippa-demo-') as scratch:
        path = Path(scratch) / 'demo.db'
        c = controller(path, 'demo-one')
        decision = c.remember_episode(**seed['decision'], participants=seed['operator'], project=seed['project'], importance=.8, embed=False)['episode_id']
        failed = c.remember_episode(**seed['failure'], participants=seed['operator'], project=seed['project'], importance=.8, embed=False)['episode_id']
        procedure = c.create_procedure('Project A retry repair', steps=['Increase retries from two to eight.'])['procedure_id']
        require(c.record_outcome(procedure, success=False) is not None, 'procedure outcome not recorded')
        print('1. Recorded decision: ' + seed['decision']['decisions'])
        print('   Recorded failed fix and failure outcome: increase retries.')
        c.close_session()
        del c
        c = controller(path, 'demo-two')
        print('2. New controller, session demo-two; no conversation history supplied.')
        out = c.recall('timeout')
        require('error' not in out, 'recall error')
        item = next((i for i in out['items'] if i.get('episode_id') == failed), None)
        require(item is not None and item['outcome'] == 'failure', 'failure not recalled')
        require(item['actions_taken'] == seed['failure']['actions_taken'], 'failed action lost')
        require(item['result'] == seed['failure']['result'], 'result lost')
        print('3. Recalled action: ' + item['actions_taken'])
        print('   Outcome: ' + item['outcome'] + '. ' + item['result'])
        print('   Scripted next step: try request deduplication; do not repeat the failed retry increase.')
        require(c.forget('episode', failed, reason='Operator request')['archived'], 'forget failed')
        after = c.recall('timeout')
        require('error' not in after, 'post-forget recall error')
        require(all(i.get('episode_id') != failed for i in after['items']), 'forgotten item returned')
        require(c.episodic.get_episode(failed)['status'] == 'archived', 'archive missing')
        require(c.episodic.get_episode(decision)['status'] == 'active', 'decision no longer active')
        print('4. Operator forgot failed-fix episode: archived and excluded from recall.')
        counts = c.status()['counts']
        require(counts['episodes'] == 2 and counts['procedures'] == 1, 'unexpected counts')
        print('5. Status counts: ' + json.dumps(counts, sort_keys=True))
        print('   Episode totals include 1 active and 1 archived; forgetting is not secure deletion.')
        print('UNSUPPORTED: authorized cross-agent sharing, quarantine, MCP/Grok integration.')
    print('PASS: demo completed; temporary database removed.')

if __name__ == '__main__':
    main()
