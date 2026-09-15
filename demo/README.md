# Hungry Hippa demo

Eight scripted steps showing what a memory runtime actually changes between two
sessions. No LLM, no network, no live model, and **no access to your production
database**.

```bash
python demo/demo.py --reset    # recreate the demo database from demo/seed.json
python demo/demo.py            # play the demo
python demo/demo.py --check    # play it and diff against expected_output.txt
python demo/demo.py --tmp      # use a throwaway temp database and clean up after
```

Runs in about two seconds. `--check` resets first, so a comparison run always
starts from the same seed. When comparing, the database path, dates/timestamps
and the closing cleanup note are normalised, so `--tmp --check` matches the same
expected output as a default run.

## Files

| File | What it is |
|---|---|
| `demo.py` | The scripted demo. Prints a transcript; `--check` compares it to the expected output. |
| `seed.json` | Generic fixture: `Operator`, `Project A`/`Project B`, `fixture housing`, `solvent X`, `method B`. **No personal information** — every value is invented. |
| `expected_output.txt` | The transcript captured from a real run. Dates and database paths are normalised before comparison. |
| `.demo_db/` | The throwaway demo database, created by `--reset`. Gitignored. Never `$HERMES_HOME`. |

The demo database path is `demo/.demo_db/hungry_hippa.db` unless you set
`HUNGRY_HIPPA_DEMO_DB` or pass `--tmp`.

## What each step proves

| Step | What happens | What it demonstrates |
|---|---|---|
| 1 | An agent starts work on `Project A` | Baseline: a normal agent turn |
| 2 | It records a decision, an attempted fix and the failure outcome | Ingestion: episode + belief with provenance and outcome |
| 3 | Session A ends | The context window is gone; the audit trail is not |
| 4 | Session B starts with no conversation history | A genuinely cold start |
| 5 | Hungry Hippa restores the relevant context | Hybrid recall + the context compiler, inside a character budget |
| 6 | The agent does not repeat the failed fix | The point of the whole exercise: remembered failure changes the next decision |
| 7 | A second MCP client process asks the same question | Cross-agent access, and the actor policy: `mcp-untrusted` gets nothing, the owner client gets the history |
| 8 | The operator inspects, corrects and forgets a memory | Reversible forgetting (archival) plus supersession, with the audit trail printed at the end |

Step 7 is a real second process: the demo starts `mcp_server.py` with
`HUNGRY_HIPPA_DB` pointing at the demo database and drives it over stdio
JSON-RPC. Nothing is bound to a network port.

## Expected output

`expected_output.txt` is the full transcript from a real run. The lines that
carry the demonstration:

```
STEP 5 — Hungry Hippa restores the relevant context
    [EPISODE E-0003 ...] attempted to free the seized housing with solvent X on Project A — outcome: failure | result: the housing cracked ...
    [BELIEF B-0002 fact/user_explicit conf 0.90] Project A chose method B over method A

STEP 6 — the agent avoids repeating the failed fix
  the restored context contains the failed attempt ... -> the housing cracked.

STEP 7 — a second compatible agent gets only what it is authorized to read
  untrusted client   -> count=0 items=0 denied=6 by={'other-actor': 6}
  owner-authorized   -> count=6 items=[('E-0003', 'episode'), ...]

STEP 8 — the operator can inspect, correct and forget a memory
  correct : B-0002 is now status=superseded
            B-0003 = "Project A chose method B over method A, and the housing is now freed with a warm soak"
  forget  : archived=True (reversible; the row is retained as status='archived')
            the corrected claim is now recalled: False
```

If `--check` reports a diff, the demo output has drifted from the captured run.
Read the diff, decide whether the change was intended, and only then refresh the
file with `python demo/demo.py > demo/expected_output.txt`.

## Recording a two-minute video

Total screen time: about two minutes. Everything below runs offline.

1. **0:00–0:15 — setup.** Terminal open in the repository root. Run
   `python demo/demo.py --reset`. Say: this is a throwaway database, no personal
   data, nothing leaves the machine.
2. **0:15–0:45 — the failure.** Run `python demo/demo.py`. Let steps 1–3 scroll:
   the agent records the decision, the failed attempt with `solvent X`, and the
   outcome `the housing cracked`. Then the session ends.
3. **0:45–1:10 — the cold start.** Steps 4–5. Point at the restored context:
   the failed attempt and the decision come back in a new session with no
   conversation history.
4. **1:10–1:30 — the payoff.** Step 6. The agent refuses to repeat the failed
   approach, because the failure is in front of it.
5. **1:30–1:50 — the second agent.** Step 7. The untrusted MCP client gets
   `count=0` and a list of denials; the owner client gets the history. Mention
   that this is a separate local process, stdio only, no network port.
6. **1:50–2:00 — inspection and forgetting.** Step 8. The operator corrects the
   belief (the old one becomes `superseded`) and archives it (`archived=True`,
   reversible). Close on the audit trail at the end.

Recording tips: terminal font size large enough to read the context lines; no
need to edit, the transcript is already in order; if you want a shorter cut, drop
steps 1 and 3 narration and keep 5, 6 and 7.

## Limits of this demo (stated, not implied)

- The "agent" is a deterministic script, not an LLM. It demonstrates what the
  runtime stores, restores and refuses to hand out — not how a model would
  phrase an answer.
- Recall here runs without embeddings (offline, repeatable). With local Ollama
  embeddings enabled, retrieval also matches paraphrases; that is not exercised
  by this demo.
- Step 7's trusted/untrusted split is the actor policy from `policy.py`. It is
  policy checking, not capability-based security, and a caller that can start the
  server can claim any `actor_id`. See `docs/SECURITY.md`.
- The audit-trail timestamps change on every run; `--check` normalises them.
