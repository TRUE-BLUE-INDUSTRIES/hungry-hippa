# Hungry Hippa Red-Team Report

Adversarial review of a local-first memory runtime, run against the repository at
`d22f556` and fixed in eight commits (`cbf7d2c` → `18ba2f4`). Every finding below
was reproduced before it was fixed, on a throwaway database, with benign payloads;
every fix has a named regression test. Where a limitation remains, it is written
down here rather than left implied.

Full suite at the end: `python scripts/check_all.py` → **all 15 steps passed**.
Per-finding detail, commands and evidence: [SECURITY_AUDIT.md](SECURITY_AUDIT.md).

## What we tried

Attacking Hungry Hippa is not really attacking SQL injection or the CLI — those
have limits, caps and parameterized statements. The interesting target is the
thing the product *is*: a runtime that takes text from one session and puts it in
front of a model in the next one, while deciding who is allowed to do what.

So the attempts were:

1. **Become the owner.** Send `actor_id: "primary"` over MCP and see whether the
   server believes us.
2. **Store an instruction.** Write a benign "IGNORE PRIOR INSTRUCTIONS…" memory and
   see what the next session is handed.
3. **Ask about secrets we cannot read.** Recall a topic the operator has a private
   memory about, and compare the answer with a topic they do not.
4. **Read the files.** Check the mode of the database, its WAL, its migration
   backups and its exports.
5. **Wear a trusted label.** Write memory claiming `source_class: user_explicit`
   with confidence 0.99.
6. **Rewrite history.** Contradict a belief the operator had confirmed, at higher
   confidence, from a non-operator channel.
7. **Exhaust resources.** Write legal-size records in volume, restart the process
   to reset the budget, and watch the database grow.
8. **Act as a confused deputy.** Make the model, acting on text it read from
   somewhere else, use its owner-identity tool.

## What actually broke

All eight, to varying degrees — that is the honest summary.

- **Identity was a request field.** `actor_id: "primary"` read the owner's private
  belief, returned the database path, and purged an owner belief. Full owner
  takeover with one string.
- **Memory was replayed as instruction.** A stored instruction-shaped belief came
  back verbatim in the next session's context, indistinguishable from anything
  else, with no framing. Content could also forge the runtime's own
  `[BELIEF … user_explicit conf 0.95]` header and a `</recalled_memory>` close tag
  it had not opened.
- **Existence was answerable.** Recall as an unauthorized caller returned
  `excluded=[{"item": "belief:B-0002", "reason": "other-actor"}]` for a topic that
  matched a protected memory, and `[]` for one that did not — plus sequential row
  ids and unfiltered graph entity names.
- **The database was world-readable** (`0644`), and the earlier backup fix copied
  that mode through, so a world-readable database produced a world-readable copy of
  every memory. Exports were created with the process umask too.
- **Provenance was caller-declared.** `source_class` was stored verbatim, so any
  writer could mint `user_explicit` — the class with the highest contradiction
  weight — along with its own confidence number.
- **A contradiction could retire the operator's own statement.** An untrusted
  actor contradicted a `user_explicit` belief; the replacement became active and
  recall-visible at confidence 0.99.
- **Volume was effectively unbounded.** The only guard was a per-process call
  budget, reset by starting a new process; nothing reported database size.
- **The model's tool ran as the owner.** A belief written through the `cortex` tool
  was stored as `user_explicit`, `quarantined=0` — the same as something the
  operator said.

## What did not break

Worth recording, because it is the difference between a product with holes and a
product with no bottom:

- **Quarantine held at the write layer.** Untrusted writes were quarantined in both
  episodic and semantic memory, excluded from recall, from belief listing/search
  and from consolidation input. No code path cleared the flag, so poisoning could
  not be laundered by consolidation.
- **SQL injection was inert.** Six payloads (`DROP TABLE`, `ATTACH DATABASE`,
  `UNION SELECT`) stored and queried as text; the parameterization held.
- **No stored SQL was ever executed.** The old `down_sql` script is recorded but no
  down-migrator exists, so a crafted database did not buy code execution.
- **The MCP surface had no SQL, path, dump or export tool**, and no network
  transport: stdio only, nothing to bind, nothing to firewall.
- **Secrets never reached the audit log.** Credential-shaped strings were redacted
  and the memory content was preserved intact.
- **Size and shape limits held** on both the MCP and the `cortex` tool surfaces.
- **The test suite was honest.** No test passed for the wrong reason, and the two
  tests that had *encoded* the archival defect were corrected rather than weakened.

## What we changed

Eight commits, each with its own regression test (names in
[SECURITY_AUDIT.md](SECURITY_AUDIT.md)):

| Finding | Change |
|---|---|
| Caller-controlled owner identity | Trust is resolved from the channel: in-process code is owner; an MCP caller is owner only with a `0600` owner token; anything else is untrusted, writes quarantined, labels remapped. `actor_id` is a label, never privilege. |
| Prompt injection through memory | Every compiled context is framed as recalled data with no authority (plus a structured `trust` block), and every field from a memory row is neutralized so it cannot forge markup, a metadata header or a role turn. |
| Existence oracle | Non-owner callers get one uniform, non-enumerating answer; no ids, no counts, no entities. The owner keeps the diagnostics. |
| File permissions | New databases `0600`; backups never wider than `0600` and never wider than their source; exports `0600`; existing lax files reported, never silently changed, with `fix-permissions` as the explicit remedy. |
| Caller-declared provenance | Schema v5 splits `claimed_source_class` from `verified_source_class`, adds `source_actor` and `ingestion_channel`; the effective class is channel-derived and confidence is capped by it. `verify` is the operator-only promotion path. |
| History rewrite | Protected facts (operator-attested, or high-confidence canonical) can only be superseded/contradicted from the operator channel; a model's contradiction becomes a quarantined candidate and the fact stands. |
| Confused deputy | A capability ladder (read / write_candidate / approve / correct / forget / purge) is derived from the channel. The model may read and write candidates; it may not approve, correct or forget a protected fact, or purge anything. |
| Resource exhaustion | Write accounting in the database (per actor, per hour, survives restarts); database size reported with a warning threshold; configurable consolidation scan caps; graph hops clamped; backups refuse to run without room. |

## What remains risky

Stated plainly, because a red-team report that ends in "and now it is secure" is
not a red-team report:

- **Prompt injection is not solved.** The runtime guarantees that memory is
  labelled, framed and stripped of markup. It cannot guarantee that a model reading
  hostile prose ignores it. Long-form text can still argue.
- **Provenance is about origin, not truth.** The operator channel can assert a
  false `user_explicit`, and a model can write a confident, wrong memory. The
  runtime now says where a claim came from; it does not know whether it is so.
- **The token is a local capability, not authentication.** Anyone running as the
  operator can read the token file and the database. That is the boundary; it stops
  a *client* claiming ownership, not a same-user process.
- **Plaintext at rest, and no tamper-evident audit.** Permissions stop other local
  users. Someone with write access to the file can also clear the write-quota
  accounting the new resource guard relies on.
- **No per-caller read quotas or query timeouts.** Read volume is still cheap.
- **Prose-level trust weighting is coarse.** The protection rule for history
  rewrite is two named triggers (operator-attested, or 0.90+ confidence), and its
  threshold is a judgement call, not a measurement.
- **Blocked contradictions pile up in quarantine** until the operator reviews them,
  and the only review surface today is `recall --quarantined`.
- **Transport is local by design**, so none of this was tested against a network
  attacker — because there is no network transport to test.

## Why the architecture is safer now

Not because any single control is clever, but because the *shape* of the trust
decisions changed.

Before, trust was data the caller supplied: an identity string in the request, a
source class in the payload, a confidence that came with the claim. Any interface
that accepted a write was, by construction, an interface that could grant
privilege — and there were several such interfaces.

Now trust is derived from the channel the call arrived on, in one place
(`trust.py`), and the same resolution feeds every decision that matters:

- **Who is calling** → identity (owner / untrusted), which decides reads, archival
  and purge.
- **What a write earns** → provenance (user / agent / external), which decides the
  verified source class, the confidence ceiling, and whether the row is quarantined.
- **What the caller may do** → a capability ladder, so a model can do its job
  without being able to approve its own claims, rewrite what the operator relies
  on, or delete anything.

Two properties fall out of that which did not hold before. First, **a caller can no
longer promote itself**: claiming `primary` gets you nothing, claiming
`user_explicit` gets you `agent_reported`, and neither gets you a purge. Second,
**every high-impact mutation is attributable**: the audit row names the actor, the
provenance and the reason, and the original row is kept — history is rewritten only
by the operator, visibly.

And memory now arrives where it is used with a label that says what it is: recalled
data with no authority, provenance visible, markup neutralized. That does not make
a model immune to a persuasive memory. It does mean the boundary between "what the
operator said" and "what something wrote into the store" is preserved all the way
into the context window instead of dissolving at the render step.

The honest one-line summary: **the runtime no longer trusts anything it was told
about itself, and it can show what it does trust and why.**
