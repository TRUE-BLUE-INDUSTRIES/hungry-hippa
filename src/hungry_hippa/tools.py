"""The ``cortex`` model tool — schema and dispatch.

One tool, action enum, mirrors the accepted fact_store pattern. The model is
instructed (system prompt block + skill) to RECALL before answering questions
about the past and to REMEMBER after significant tasks — that is what makes
the Cortex part of the normal cognitive loop (§16, Test 10).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from . import limits as _limits
from . import policy as _policy

CORTEX_SCHEMA = {
    "name": "cortex",
    "description": (
        "Hungry Hippa (formerly Living Cortex) persistent memory: episodic "
        "history, temporal knowledge graph, semantic beliefs with provenance, "
        "and procedural learning. "
        "Use recall() BEFORE answering questions about past work/projects/people "
        "or when the user asks 'do you remember'; use remember_episode() after "
        "significant tasks (problems found, decisions made, things that worked). "
        "Use relate() to connect people/projects/devices/problems/solutions. "
        "Use add_belief() for durable facts with a source; contradict() when "
        "evidence conflicts. why() traces a belief to its evidence. "
        "recall(..., explain=true) returns the score parts behind each result "
        "(relevance, recency, salience, confidence, provenance class) without "
        "echoing memory contents."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "recall", "remember_episode", "relate", "graph",
                    "episodes", "add_belief", "update_belief", "contradict",
                    "procedures", "record_outcome", "reinforce", "forget",
                    "consolidate", "why", "changed", "forgotten", "status",
                    "export",
                ],
                "description": "What to do.",
            },
            "query": {"type": "string",
                      "description": "recall: what to remember about."},
            "project": {"type": "string",
                        "description": "Optional project scope for recall/episodes."},
            "context": {"type": "string",
                        "description": "remember_episode: what happened."},
            "user_request": {"type": "string",
                             "description": "remember_episode: the user's request."},
            "actions_taken": {"type": "string",
                              "description": "remember_episode: what was done."},
            "tools_used": {"type": "string",
                           "description": "remember_episode: tools used."},
            "decisions": {"type": "string",
                          "description": "remember_episode: decisions made."},
            "result": {"type": "string",
                       "description": "remember_episode: the observed result."},
            "outcome": {"type": "string",
                        "enum": ["success", "failure", "mixed", "unknown", "unexpected"],
                        "description": "remember_episode: outcome."},
            "importance_signals": {
                "type": "array", "items": {"type": "string"},
                "description": "remember_episode: novel_object, user_asked, problem_discovered, decision_made, physical_action, unexpected_result, project_relevance.",
            },
            "src": {"type": "string", "description": "relate/graph: source entity."},
            "rel": {"type": "string",
                    "description": "relate/graph: OWNS USES WORKS_ON CREATED DEPENDS_ON PART_OF CAUSED FAILED_BECAUSE SOLVED_BY REPLACED_BY SUPERSEDES REQUIRES PRODUCED LEARNED_FROM APPLIES_TO ..."},
            "dst": {"type": "string", "description": "relate/graph: destination entity."},
            "include_history": {"type": "boolean",
                                "description": "graph: include superseded/contradicted edges."},
            "claim": {"type": "string", "description": "add_belief: the belief/fact text."},
            "kind": {"type": "string",
                     "enum": ["fact", "belief", "hypothesis", "procedural_belief"],
                     "description": "add_belief: belief kind."},
            "confidence": {"type": "number", "description": "add_belief: 0..1."},
            "source_class": {"type": "string",
                             "enum": ["user_explicit", "document", "tool_result",
                                      "visual_observation", "audio_observation",
                                      "external_source", "agent_inference",
                                      "derived_pattern"],
                             "description": "add_belief: where this came from."},
            "belief_id": {"type": "string",
                          "description": "update_belief/contradict/why/reinforce/forget target."},
            "new_claim": {"type": "string", "description": "update_belief: replacement claim."},
            "confidence_delta": {"type": "number",
                                 "description": "update_belief: nudge confidence."},
            "counter_claim": {"type": "string",
                              "description": "contradict: the conflicting claim."},
            "episode_id": {"type": "string", "description": "episodes/reinforce/forget target."},
            "procedure_id": {"type": "string",
                             "description": "procedures/reinforce/record_outcome target."},
            "success": {"type": "boolean",
                        "description": "record_outcome: did the procedure work?"},
            "explain": {"type": "boolean",
                        "description": "recall: include per-item score parts (no contents)."},
            "name": {"type": "string", "description": "procedures: create — procedure name."},
            "description": {"type": "string", "description": "procedures: create — what it does."},
            "steps": {"type": "array", "items": {"type": "string"},
                      "description": "procedures: create — ordered steps."},
            "target_kind": {"type": "string",
                            "description": "reinforce/forget: episode|belief|relationship|procedure."},
            "mode": {"type": "string", "enum": ["archival", "purge"],
                     "description": "forget: archival (default, reversible) or purge (deletes)."},
            "reason": {"type": "string", "description": "forget/consolidate: why."},
            "limit": {"type": "integer", "description": "Max results (default 6)."},
            "path": {"type": "string", "description": "export: destination JSON path."},
            "export_kind": {"type": "string", "enum": ["all", "episodes", "beliefs", "graph"],
                            "description": "export: what to export."},
        },
        "required": ["action"],
    },
}


def handle(cortex_controller, observability, action: str, args: Dict[str, Any]) -> str:
    """Dispatch a cortex tool call. Returns a JSON string (tool result)."""
    try:
        c = cortex_controller
        problems = _limits.check_args(args or {})
        if problems:
            return json.dumps({"error": "rejected: " + "; ".join(problems)[:300],
                               "limits": {"max_query_chars": _limits.MAX_QUERY_CHARS,
                                          "max_content_chars": _limits.MAX_CONTENT_CHARS}},
                              ensure_ascii=False)
        if action == "recall":
            out = c.recall(args.get("query", ""), project=args.get("project", ""),
                           limit=args.get("limit"),
                           explain=bool(args.get("explain")))
            payload = {
                "count": out.get("count", 0),
                "context": _limits.truncate(out.get("context", ""),
                                            _limits.MAX_RESULT_CHARS),
                "entities": out.get("entities", []),
                "sources": out.get("sources", []),
                "excluded": out.get("excluded", []),
            }
            if args.get("explain"):
                payload["explain"] = out.get("explain", [])
            return json.dumps(payload, ensure_ascii=False)

        if action == "remember_episode":
            fields = {k: args.get(k, "") for k in
                      ("context", "user_request", "actions_taken", "tools_used",
                       "decisions", "result")}
            fields = {k: v for k, v in fields.items() if v}
            if args.get("outcome"):
                fields["outcome"] = args["outcome"]
            if args.get("project"):
                fields["project"] = args["project"]
            if args.get("importance_signals"):
                fields["importance_signals"] = args["importance_signals"]
            r = c.remember_episode(**fields)
            return json.dumps(r, ensure_ascii=False)

        if action == "relate":
            r = c.relate(args.get("src", ""), args.get("rel", ""), args.get("dst", ""),
                         confidence=args.get("confidence", 0.7),
                         source_type=args.get("source_class", "agent_inference"))
            return json.dumps(r, ensure_ascii=False)

        if action == "graph":
            src = args.get("src", "")
            dst = args.get("dst", "")
            rel = args.get("rel", "")
            if not src and not dst and not rel:
                return json.dumps({"error": "graph query needs src/rel/dst"},
                                  ensure_ascii=False)
            rows = c.retrieve_graph(src=src, rel=rel, dst=dst,
                                    include_history=bool(args.get("include_history")),
                                    limit=args.get("limit") or 30)
            return json.dumps({"edges": rows}, ensure_ascii=False, default=str)

        if action == "episodes":
            if args.get("episode_id"):
                e = c.episodic.get_episode(args["episode_id"])
                return json.dumps(e or {"error": "not found"}, ensure_ascii=False, default=str)
            rows = c.episodic.list_episodes(project=args.get("project", ""),
                                            limit=args.get("limit") or 20)
            return json.dumps({"episodes": rows}, ensure_ascii=False, default=str)

        if action == "add_belief":
            # The source_class in the arguments is a claim; the controller passes
            # its channel-resolved provenance so the model cannot promote its own
            # text to user_explicit (see trust.verified_source_class).
            r = c.semantic.add_belief(
                args.get("claim", ""), kind=args.get("kind") or "belief",
                confidence=args.get("confidence"),
                source_class=args.get("source_class", "agent_inference"),
                identity=c.identity, provenance=c.provenance, channel=c.channel,
                actor_id=c.actor_id,
                session_id=c.session_id)
            return json.dumps(r, ensure_ascii=False)

        if action == "update_belief":
            r = c.update_belief(
                args.get("belief_id", ""), new_claim=args.get("new_claim", ""),
                confidence_delta=args.get("confidence_delta"),
                confidence=args.get("confidence"), reason=args.get("reason", ""))
            return json.dumps(r, ensure_ascii=False, default=str)

        if action == "contradict":
            r = c.contradict(args.get("belief_id", ""), args.get("counter_claim", ""),
                             confidence=args.get("confidence"),
                             source_class=args.get("source_class", "agent_inference"),
                             identity=c.identity, provenance=c.provenance,
                             channel=c.channel, actor_id=c.actor_id)
            return json.dumps(r, ensure_ascii=False, default=str)

        if action == "procedures":
            if args.get("name"):
                r = c.create_procedure(
                    args.get("name", ""), description=args.get("description", ""),
                    steps=args.get("steps"), confidence=args.get("confidence", 0.5))
                return json.dumps(r, ensure_ascii=False)
            rows = c.procedural.list_procedures(limit=args.get("limit") or 30)
            return json.dumps({"procedures": rows}, ensure_ascii=False, default=str)

        if action == "record_outcome":
            pid = args.get("procedure_id", "")
            if not pid:
                return json.dumps({"error": "record_outcome needs procedure_id"},
                                  ensure_ascii=False)
            r = c.record_outcome(pid, bool(args.get("success")))
            if not r:
                return json.dumps({"error": f"unknown procedure {pid}"},
                                  ensure_ascii=False)
            return json.dumps({
                "procedure_id": r["procedure_id"], "name": r["name"],
                "status": r["status"], "confidence": r["confidence"],
                "success_count": r["success_count"],
                "failure_count": r["failure_count"],
            }, ensure_ascii=False)

        if action == "reinforce":
            ok = c.reinforce(args.get("target_kind", ""), args.get("belief_id") or
                             args.get("episode_id") or args.get("procedure_id") or "")
            return json.dumps({"reinforced": ok}, ensure_ascii=False)

        if action == "forget":
            target = args.get("belief_id") or args.get("episode_id") or ""
            r = c.forget(args.get("target_kind", ""), target,
                         mode=args.get("mode", "archival"),
                         reason=args.get("reason", ""))
            return json.dumps(r, ensure_ascii=False)

        if action == "consolidate":
            r = c.consolidate(args.get("reason", "manual"))
            return json.dumps(r, ensure_ascii=False, default=str)

        if action == "why":
            r = observability.why(args.get("belief_id", ""))
            return json.dumps(r, ensure_ascii=False, default=str)

        if action == "changed":
            rows = observability.recent_changes(args.get("limit") or 20)
            return json.dumps({"changes": rows}, ensure_ascii=False, default=str)

        if action == "forgotten":
            rows = observability.forgotten(args.get("limit") or 20)
            return json.dumps({"forgotten": rows}, ensure_ascii=False, default=str)

        if action == "status":
            return json.dumps(c.status(), ensure_ascii=False, default=str)

        if action == "export":
            # DoD: "No interface exposes arbitrary SQL or raw database extraction."
            # Export is an operator-side maintenance action: it is owner-only and
            # every run is written to the audit log. It is not reachable over MCP
            # (the MCP tool surface deliberately has no export tool).
            if not c.is_owner:
                c.db.log_mutation("export_denied", "database", "",
                                  f"actor={c.actor_id} reason=owner-only",
                                  c.session_id)
                return json.dumps(
                    {"error": "export is operator-only; unavailable to this actor",
                     "actor_id": c.actor_id}, ensure_ascii=False)
            out_path = args.get("path", "hungry_hippa_export.json")
            kind = args.get("export_kind", "all")
            r = observability.export(out_path, kind)
            c.db.log_mutation("export", "database", "",
                              f"kind={kind} path={out_path} actor={c.actor_id}",
                              c.session_id)
            return json.dumps(r, ensure_ascii=False, default=str)

        return json.dumps({"error": f"unknown action {action}"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"[:400]}, ensure_ascii=False)
