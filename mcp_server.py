"""Hungry Hippa — local MCP server (stdio, JSON-RPC 2.0).

Hungry Hippa is a local-first memory runtime for AI agents. This module exposes
the same :class:`~controller.MemoryController` that the Hermes ``cortex`` tool
uses, over a **local stdio** MCP transport, so other MCP-capable clients on the
same machine can read and write the same memory runtime.

Transport and scope (deliberately minimal):

  * stdio only — newline-delimited JSON-RPC 2.0 on stdin/stdout.
  * No network listener, no Unix socket, no HTTP. Nothing to bind, nothing to
    firewall; a client has to be able to start this process to talk to it.
  * No tool takes a SQL string, a filesystem path or a database path, and there
    is no raw-database or export tool. See ``docs/MCP.md``.

Run it:

    python mcp_server.py                 # serve on stdio
    python mcp_server.py --print-schemas # print the tool schemas as JSON
    python -m mcp_server                 # equivalent when cwd is the plugin dir

Caller identity: every tool accepts ``actor_id`` and defaults to
``mcp-untrusted``. An untrusted actor writes quarantined memories, reads only
its own unclassified non-quarantined rows, and can never purge. This is an
actor/policy check, not capability-based security — see ``policy.py``.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "TOOLS", "tool_schemas", "call_tool", "handle_message", "serve", "main",
    "SERVER_NAME", "PROTOCOL_VERSION", "DEFAULT_MCP_ACTOR",
]

SERVER_NAME = "hungry-hippa"
PROTOCOL_VERSION = "2024-11-05"
DEFAULT_MCP_ACTOR = "mcp-untrusted"

# The plugin registers itself with Hermes under the legacy provider name
# ("living-cortex"), and this directory is the import root. Reuse the same
# synthetic package so an in-process client and the Hermes plugin share one
# module identity (and therefore one MemoryController class).
PLUGIN_PACKAGE = "livingcortex"


def _load_plugin_package(name: str = PLUGIN_PACKAGE):
    """Import this directory as a package, like the Hermes plugin loader does."""
    here = Path(__file__).resolve().parent
    existing = sys.modules.get(name)
    if existing is not None and getattr(existing, "__file__", None):
        return existing
    init = here / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        name, str(init), submodule_search_locations=[str(here)])
    if spec is None or spec.loader is None:  # pragma: no cover - broken install
        raise ImportError(f"cannot load plugin package from {init}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


if __package__:
    # Imported as part of a real package (Hermes or `python -m` from the parent).
    from . import limits as _limits
    from . import policy as _policy
    from . import trust as _trust
    from .config import load_config, resolve_db_path
    from .controller import MemoryController
else:
    _PLUGIN = _load_plugin_package()
    from livingcortex import limits as _limits
    from livingcortex import policy as _policy
    from livingcortex import trust as _trust
    from livingcortex.config import load_config, resolve_db_path
    from livingcortex.controller import MemoryController


# Per-process call budget. A blunt resource guard against a runaway or hostile
# client loop; it does not identify callers and is not an authorisation
# mechanism. Override with HUNGRY_HIPPA_MAX_MCP_CALLS for a long-lived session.
CALL_BUDGET = _limits.CallBudget(_limits.max_calls_from_env())


def set_call_budget(max_calls: Optional[int] = None) -> None:
    """Reset the per-process call budget (tests and operator tuning).

    With no argument the configured/default budget is restored, so a test that
    shrinks the budget cannot leak that setting into later work.
    """
    CALL_BUDGET.reset(max_calls if max_calls is not None
                      else _limits.max_calls_from_env())


def call_budget_summary() -> Dict[str, Any]:
    return CALL_BUDGET.summary()


def server_version() -> str:
    """Read the version from plugin.yaml so there is one source of truth."""
    try:
        for line in (Path(__file__).resolve().parent / "plugin.yaml").read_text(
                encoding="utf-8").splitlines():
            if line.startswith("version:"):
                return line.split(":", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return "0.0.0"


# --------------------------------------------------------------------- args

_ACTOR = {
    "type": "string",
    "description": ("Caller label, NOT identity. It names the caller for its own "
                    "rows; it never grants owner rights. Owner identity requires "
                    "owner_token. Defaults to 'mcp-untrusted'."),
    "maxLength": 128,
}
_OWNER_TOKEN = {
    "type": "string",
    "description": ("Contents of the operator's owner-token file "
                    "($HERMES_HOME/hungry_hippa.owner.token, mode 0600). Present "
                    "it to act as the owner. Never logged; never echoed."),
    "maxLength": 128,
}
_OUTCOME = {"type": "string",
            "enum": ["success", "failure", "mixed", "unknown", "unexpected"]}
_SOURCE_CLASS = {
    "type": "string",
    "enum": ["user_explicit", "document", "tool_result", "visual_observation",
             "audio_observation", "external_source", "hermes_inference",
             "derived_pattern"],
}
_SENSITIVITY = {"type": "string",
                "enum": ["unclassified", "internal", "private", "restricted"]}


def _out(**props: Any) -> Dict[str, Any]:
    """Build an MCP ``outputSchema`` for a tool.

    Every handler returns exactly one JSON object inside a text content block.
    The shared envelope is ``{ok: bool, error?: str}``; each tool adds the fields
    listed here. ``additionalProperties`` stays true because the envelope may
    gain a ``truncated``/``original_chars`` note when a result hits the size cap,
    and claiming otherwise would advertise a guarantee the server does not keep.
    """
    shared = {
        "ok": {"type": "boolean",
               "description": "false when the call was denied or failed."},
        "error": {"type": "string",
                  "description": "Present when ok is false."},
    }
    return {
        "type": "object",
        "additionalProperties": True,
        "required": ["ok"],
        "properties": {**shared, **props},
    }


def tool_schemas() -> List[Dict[str, Any]]:
    """The advertised MCP tool list. Strict schemas, no path/SQL arguments."""
    return [
        {
            "name": "hippa_remember",
            "description": (
                "Store one memory. memory_type='episodic' records what happened "
                "(context/user_request/actions_taken/decisions/result/outcome); "
                "memory_type='semantic' records a fact or belief with a source "
                "class. Untrusted callers are stored quarantined."
            ),
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["memory_type", "content"],
                "properties": {
                    "memory_type": {"type": "string",
                                    "enum": ["episodic", "semantic"]},
                    "content": {"type": "string", "maxLength": 32000,
                                "description": "Episode context, or the belief claim."},
                    "user_request": {"type": "string", "maxLength": 8000},
                    "actions_taken": {"type": "string", "maxLength": 8000},
                    "decisions": {"type": "string", "maxLength": 8000},
                    "result": {"type": "string", "maxLength": 8000},
                    "outcome": _OUTCOME,
                    "project": {"type": "string", "maxLength": 256},
                    "claim": {"type": "string", "maxLength": 32000,
                              "description": "semantic: belief text (defaults to content)."},
                    "kind": {"type": "string",
                             "enum": ["fact", "belief", "hypothesis", "procedural_belief"]},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "source_class": _SOURCE_CLASS,
                    "sensitivity": _SENSITIVITY,
                    "related_entities": {"type": "array", "maxItems": 32,
                                         "items": {"type": "string", "maxLength": 256}},
                    "actor_id": _ACTOR,
                    "owner_token": _OWNER_TOKEN,
                },
            },
            "outputSchema": _out(
                belief_id={"type": "string"},
                episode_id={"type": "string"},
                quarantined={"type": "boolean"},
                importance={"type": "number"},
                outcome={"type": "string"},
                sensitivity={"type": "string"},
                actor_id={"type": "string"},
            ),
        },
        {
            "name": "hippa_recall",
            "description": (
                "Hybrid recall (keyword + graph + optional local vectors) under "
                "actor policy. Quarantined rows are excluded unless the owner "
                "explicitly asks for them. explain=true returns per-item score "
                "parts without memory contents."
            ),
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "maxLength": 8000},
                    "project": {"type": "string", "maxLength": 256},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                    "explain": {"type": "boolean", "default": False},
                    "include_quarantined": {
                        "type": "boolean", "default": False,
                        "description": "Owner-review only; ignored for untrusted actors."},
                    "actor_id": _ACTOR,
                    "owner_token": _OWNER_TOKEN,
                },
            },
            "outputSchema": _out(
                count={"type": "integer", "description": "Items recalled after policy."},
                context={"type": "string", "description": "Rendered recall text."},
                items={"type": "array", "items": {"type": "object"},
                       "description": "id/type/quarantined/sensitivity only, no contents."},
                entities={"type": "array", "items": {"type": "string"}},
                sources={"type": "array", "items": {"type": "string"}},
                excluded={"description": "Content-free exclusion reasons for the owner; "
                                         "a non-enumerating summary for anyone else."},
                token_estimate={"type": "integer"},
                explain={"type": "array", "items": {"type": "object"},
                         "description": "Score parts; never memory contents."},
            ),
        },
        {
            "name": "hippa_build_context",
            "description": (
                "Recall and compile the smallest useful context package inside an "
                "explicit character budget: {items, rendering, token_estimate, "
                "excluded}. token_estimate is characters/4, not a tokenizer count."
            ),
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "maxLength": 8000},
                    "project": {"type": "string", "maxLength": 256},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                    "max_chars": {"type": "integer", "minimum": 100, "maximum": 20000},
                    "actor_id": _ACTOR,
                    "owner_token": _OWNER_TOKEN,
                },
            },
            "outputSchema": _out(
                rendering={"type": "string"},
                item_ids={"type": "array", "items": {"type": "string"}},
                token_estimate={"type": "integer",
                                "description": "characters/4, not a tokenizer count."},
                chars_used={"type": "integer"},
                budget_chars={"type": "integer"},
                excluded={"type": "array", "items": {"type": "object"}},
                entities={"type": "array", "items": {"type": "string"}},
                sources={"type": "array", "items": {"type": "string"}},
            ),
        },
        {
            "name": "hippa_record_outcome",
            "description": (
                "Record whether a stored procedure worked. Updates the procedure's "
                "success/failure counters and re-evaluates its confidence."
            ),
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["procedure_id", "success"],
                "properties": {
                    "procedure_id": {"type": "string", "maxLength": 64},
                    "success": {"type": "boolean"},
                    "actor_id": _ACTOR,
                    "owner_token": _OWNER_TOKEN,
                },
            },
            "outputSchema": _out(
                procedure_id={"type": "string"},
                name={"type": "string"},
                status={"type": "string"},
                confidence={"type": "number"},
                success_count={"type": "integer"},
                failure_count={"type": "integer"},
            ),
        },
        {
            "name": "hippa_forget",
            "description": (
                "Forget a memory. Default mode 'archival' keeps the row and marks it "
                "archived (reversible). mode='purge' deletes permanently and is "
                "denied unless confirmation=true and the actor is an owner."
            ),
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["target_kind", "target_id"],
                "properties": {
                    "target_kind": {"type": "string", "enum": ["episode", "belief"]},
                    "target_id": {"type": "string", "maxLength": 64},
                    "mode": {"type": "string", "enum": ["archival", "purge"],
                             "default": "archival"},
                    "confirmation": {"type": "boolean", "default": False,
                                     "description": "Required for purge."},
                    "reason": {"type": "string", "maxLength": 512},
                    "actor_id": _ACTOR,
                    "owner_token": _OWNER_TOKEN,
                },
            },
            "outputSchema": _out(
                mode={"type": "string", "enum": ["archival", "purge"]},
                target={"type": "string"},
                archived={"type": "boolean"},
                purged={"type": "boolean"},
                reason={"type": "string",
                        "description": "Why a forget was denied, when ok is false."},
                actor_id={"type": "string"},
            ),
        },
        {
            "name": "hippa_status",
            "description": (
                "Memory-runtime health: table counts, quarantine counts, vector "
                "availability, active policy. Counts only — never row contents."
            ),
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"actor_id": _ACTOR, "owner_token": _OWNER_TOKEN},
            },
            "outputSchema": _out(
                product={"type": "string"},
                server_version={"type": "string"},
                actor_id={"type": "string"},
                identity={"type": "string", "enum": ["owner", "untrusted"],
                          "description": "Server-resolved identity, not the label."},
                provenance={"type": "string", "enum": ["user", "agent", "external"]},
                counts={"type": "object"},
                vectors={"type": "object"},
                failures={"type": "integer"},
                policy={"type": "object"},
                call_budget={"type": "object"},
                limits={"type": "object"},
                db_path={"type": "string",
                         "description": "Owner actors only; omitted for untrusted callers."},
            ),
        },
    ]


TOOLS: List[Dict[str, Any]] = tool_schemas()
TOOL_NAMES = tuple(t["name"] for t in TOOLS)


# ----------------------------------------------------------------- handlers

def _binding_of(args: Dict[str, Any]) -> "_trust.Binding":
    """Resolve the caller's binding for this request.

    ``actor_id`` is a *claim*, not identity. Owner identity requires the owner
    token; a claim that names an owner actor without it is remapped, so the
    label can never alias the owner's rows.
    """
    return _trust.external_binding(args.get("actor_id"), args.get("owner_token"))


def _actor_of(args: Dict[str, Any]) -> str:
    """The caller's label (kept for logging/echo; never a privilege decision)."""
    return _binding_of(args).actor_id


def _bind(controller, binding):
    """Bind the controller to this MCP call using the server-resolved binding.

    The MCP server runs the controller in a primary agent context so writes are
    permitted, but identity and provenance come from ``trust.py``: an MCP caller
    without the owner token is untrusted, and everything it writes is
    quarantined, whatever ``actor_id`` it sent.
    """
    controller.bind_session(session_id="mcp",
                            platform="mcp",
                            agent_context="primary",
                            trust=binding)
    return controller


def _ok(**payload: Any) -> Dict[str, Any]:
    return {"ok": True, **payload}


def _denied(reason: str, **extra: Any) -> Dict[str, Any]:
    return {"ok": False, "error": reason, **extra}


def _t_remember(controller, args: Dict[str, Any], actor_id: str) -> Dict[str, Any]:
    mtype = str(args.get("memory_type") or "").strip().lower()
    content = str(args.get("content") or "").strip()
    if mtype not in ("episodic", "semantic"):
        return _denied("memory_type must be 'episodic' or 'semantic'")
    if not content:
        return _denied("content is required")
    sensitivity = args.get("sensitivity") or "unclassified"
    # untrusted callers cannot label their own memory as trusted-only
    if not controller.is_owner and sensitivity != "unclassified":
        sensitivity = "unclassified"

    if mtype == "semantic":
        r = controller.semantic.add_belief(
            str(args.get("claim") or content),
            kind=args.get("kind") or "belief",
            confidence=args.get("confidence"),
            source_class=args.get("source_class") or "external_source",
            related_entities=args.get("related_entities"),
            sensitivity=sensitivity,
            actor_id=actor_id,
            identity=controller.identity,
            session_id="mcp",
        )
        if r.get("error"):
            return _denied(r["error"])
        return _ok(belief_id=r["belief_id"], quarantined=r.get("quarantined", False),
                   sensitivity=r.get("sensitivity"), actor_id=r.get("actor_id"))

    fields: Dict[str, Any] = {"context": content, "actor_id": actor_id,
                              "sensitivity": sensitivity, "embed": False}
    for src, dst in (("user_request", "user_request"), ("actions_taken", "actions_taken"),
                     ("decisions", "decisions"), ("result", "result"),
                     ("project", "project"), ("outcome", "outcome")):
        if args.get(src):
            fields[dst] = args[src]
    r = controller.remember_episode(**fields)
    if r.get("error"):
        return _denied(r["error"])
    return _ok(episode_id=r["episode_id"], importance=r.get("importance"),
               outcome=r.get("outcome"), quarantined=r.get("quarantined", False),
               sensitivity=r.get("sensitivity"), actor_id=r.get("actor_id"))


def _t_recall(controller, args: Dict[str, Any], actor_id: str) -> Dict[str, Any]:
    query = str(args.get("query") or "").strip()
    if not query:
        return _denied("query is required")
    out = controller.recall(
        query,
        project=args.get("project", ""),
        limit=args.get("limit"),
        actor_id=actor_id,
        explain=bool(args.get("explain")),
        include_quarantined=bool(args.get("include_quarantined")),
    )
    payload = _ok(
        count=out.get("count", 0),
        context=_limits.truncate(out.get("context", ""), _limits.MAX_RESULT_CHARS),
        items=[
            {"id": (i.get("episode_id") or i.get("belief_id") or i.get("rel_id")),
             "type": i.get("_kind") or i.get("kind"),
             "quarantined": bool(i.get("quarantined", 0)),
             "sensitivity": i.get("sensitivity", "unclassified")}
            for i in out.get("items", [])
        ],
        entities=out.get("entities", []),
        sources=out.get("sources", []),
        excluded=out.get("excluded", []),
        token_estimate=(out.get("context_package") or {}).get("token_estimate", 0),
    )
    if args.get("explain"):
        payload["explain"] = out.get("explain", [])
    if out.get("error"):
        payload["error"] = out["error"]
    return payload


def _t_build_context(controller, args: Dict[str, Any], actor_id: str) -> Dict[str, Any]:
    query = str(args.get("query") or "").strip()
    if not query:
        return _denied("query is required")
    pkg = controller.build_context(query, project=args.get("project", ""),
                                   limit=args.get("limit"), actor_id=actor_id,
                                   max_context_chars=args.get("max_chars"))
    return _ok(
        rendering=_limits.truncate(pkg.get("rendering", ""), _limits.MAX_RESULT_CHARS),
        item_ids=[(i.get("episode_id") or i.get("belief_id") or i.get("rel_id"))
                  for i in pkg.get("items", [])],
        token_estimate=pkg.get("token_estimate", 0),
        chars_used=pkg.get("chars_used", 0),
        budget_chars=pkg.get("budget_chars"),
        excluded=pkg.get("excluded", []),
        entities=pkg.get("entities", []),
        sources=pkg.get("sources", []),
    )


def _t_record_outcome(controller, args: Dict[str, Any], actor_id: str) -> Dict[str, Any]:
    pid = str(args.get("procedure_id") or "").strip()
    if not pid:
        return _denied("procedure_id is required")
    if "success" not in args:
        return _denied("success is required")
    r = controller.record_outcome(pid, bool(args.get("success")))
    if not r:
        return _denied(f"unknown procedure {pid}")
    return _ok(procedure_id=r["procedure_id"], name=r["name"], status=r["status"],
               confidence=r["confidence"], success_count=r["success_count"],
               failure_count=r["failure_count"])


def _t_forget(controller, args: Dict[str, Any], actor_id: str) -> Dict[str, Any]:
    kind = str(args.get("target_kind") or "").strip()
    target = str(args.get("target_id") or "").strip()
    mode = str(args.get("mode") or "archival").strip().lower()
    if kind not in ("episode", "belief"):
        return _denied("target_kind must be 'episode' or 'belief'")
    if not target:
        return _denied("target_id is required")
    if mode not in ("archival", "purge"):
        return _denied("mode must be 'archival' or 'purge'")
    if mode == "purge":
        # Default deny over MCP: an explicit confirmation flag AND an owner actor.
        if not bool(args.get("confirmation")):
            return _denied("purge requires confirmation=true; archival is the default")
        if not controller.is_owner:
            return _denied("purge denied for this actor", actor_id=actor_id)
    r = controller.forget(kind, target, mode=mode, reason=args.get("reason", ""))
    if r.get("error"):
        return _denied(r["error"], actor_id=actor_id, target=target,
                       policy_reason=r.get("reason", ""))
    return _ok(mode=mode, target=target,
               archived=bool(r.get("archived")), purged=bool(r.get("purged")))


def _t_status(controller, args: Dict[str, Any], actor_id: str) -> Dict[str, Any]:
    st = controller.status()
    payload = _ok(
        product="Hungry Hippa",
        server_version=server_version(),
        actor_id=actor_id,
        identity=controller.identity,
        provenance=controller.provenance,
        counts=st.get("counts", {}),
        vectors=st.get("vectors"),
        failures=st.get("failures", 0),
        policy=_policy.policy_summary(),
        call_budget=CALL_BUDGET.summary(),
        limits={"max_query_chars": _limits.MAX_QUERY_CHARS,
                "max_content_chars": _limits.MAX_CONTENT_CHARS,
                "max_result_chars": _limits.MAX_RESULT_CHARS},
    )
    # the database path is operator information, not for untrusted callers
    if controller.is_owner:
        payload["db_path"] = st.get("path")
    return payload


_HANDLERS = {
    "hippa_remember": _t_remember,
    "hippa_recall": _t_recall,
    "hippa_build_context": _t_build_context,
    "hippa_record_outcome": _t_record_outcome,
    "hippa_forget": _t_forget,
    "hippa_status": _t_status,
}


def call_tool(name: str, arguments: Optional[Dict[str, Any]], controller=None) -> Dict[str, Any]:
    """Dispatch one MCP tool call and return a plain result dict.

    ``{"ok": True, ...payload}`` on success, ``{"ok": False, "error": ...}`` when
    the call is rejected by schema or policy. The JSON-RPC layer wraps this into
    MCP content; tests call it directly, in-process.
    """
    if name not in _HANDLERS:
        return _denied(f"unknown tool {name}")
    args = dict(arguments or {})
    if not isinstance(args, dict):
        return _denied("arguments must be an object")
    binding = _binding_of(args)
    actor_id = binding.actor_id
    # The token is consumed by the boundary and never travels further: handlers
    # cannot echo it, store it as memory content, or write it to the audit log.
    args.pop("owner_token", None)
    schema = next((t for t in TOOLS if t["name"] == name), None)
    problems = validate_args(schema, args) if schema else []
    problems.extend(_limits.check_args(args))
    if problems:
        return _denied("; ".join(dict.fromkeys(problems))[:400])
    allowed, reason = CALL_BUDGET.check()
    if not allowed:
        return _denied(reason, budget=CALL_BUDGET.summary())
    CALL_BUDGET.record()
    if controller is None:
        return _denied("no memory runtime available")
    try:
        return _HANDLERS[name](_bind(controller, binding), args, actor_id)
    except Exception as e:  # never raise into the protocol loop
        return _denied(f"{type(e).__name__}: {e}"[:400])


# ------------------------------------------------------------ validation

def validate_args(schema: Optional[Dict[str, Any]],
                  args: Dict[str, Any]) -> List[str]:
    """Minimal strict check against a tool schema.

    Deliberately small and stdlib-only: types, required fields, enums, numeric
    bounds, string/array length caps and ``additionalProperties: false``. It is
    a request-shape guard, not a general JSON-Schema implementation.
    """
    if not schema:
        return []
    spec = schema.get("inputSchema") or {}
    problems: List[str] = []
    for key in spec.get("required", []):
        if args.get(key) in (None, ""):
            problems.append(f"missing required field '{key}'")
    props = spec.get("properties") or {}
    if spec.get("additionalProperties") is False:
        for key in args:
            if key not in props:
                problems.append(f"unknown field '{key}'")
    for key, value in args.items():
        rule = props.get(key)
        if not rule:
            continue
        if value is None:
            # An explicit null is not a valid value for any field we advertise:
            # every declared property is a concrete type, and a null actor_id
            # must not fall through to the default owner actor.
            problems.append(f"'{key}' must not be null")
            continue
        declared = rule.get("type")
        if declared == "string":
            if not isinstance(value, str):
                problems.append(f"'{key}' must be a string")
                continue
            if "maxLength" in rule and len(value) > rule["maxLength"]:
                problems.append(f"'{key}' exceeds {rule['maxLength']} characters")
            if rule.get("enum") and value not in rule["enum"]:
                problems.append(f"'{key}' must be one of {rule['enum']}")
        elif declared == "boolean":
            if not isinstance(value, bool):
                problems.append(f"'{key}' must be a boolean")
        elif declared == "integer":
            if isinstance(value, bool) or not isinstance(value, int):
                problems.append(f"'{key}' must be an integer")
                continue
            if "minimum" in rule and value < rule["minimum"]:
                problems.append(f"'{key}' must be >= {rule['minimum']}")
            if "maximum" in rule and value > rule["maximum"]:
                problems.append(f"'{key}' must be <= {rule['maximum']}")
        elif declared == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                problems.append(f"'{key}' must be a number")
                continue
            if "minimum" in rule and value < rule["minimum"]:
                problems.append(f"'{key}' must be >= {rule['minimum']}")
            if "maximum" in rule and value > rule["maximum"]:
                problems.append(f"'{key}' must be <= {rule['maximum']}")
        elif declared == "array":
            if not isinstance(value, list):
                problems.append(f"'{key}' must be an array")
                continue
            if "maxItems" in rule and len(value) > rule["maxItems"]:
                problems.append(f"'{key}' exceeds {rule['maxItems']} items")
            item = rule.get("items") or {}
            item_type = item.get("type")
            if item_type == "string" and any(
                    not isinstance(v, str) for v in value):
                problems.append(f"'{key}' items must be strings")
                continue
            if item_type == "string" and "maxLength" in item:
                bad = [v for v in value if len(v) > item["maxLength"]]
                if bad:
                    problems.append(
                        f"'{key}' items exceed {item['maxLength']} characters")
    return problems


# --------------------------------------------------------- JSON-RPC layer

def _result(msg_id: Any, payload: Dict[str, Any]) -> Dict[str, Any]:
    text = json.dumps(payload, ensure_ascii=False, default=str)
    if len(text) > _limits.MAX_RESULT_JSON_CHARS:
        # Backstop: a single frame never exceeds the configured cap, whatever a
        # handler produced. `ok` is preserved so a client can still act on it.
        text = json.dumps({
            "ok": payload.get("ok", True),
            "truncated": True,
            "original_chars": len(text),
            "note": "result exceeded the MCP result size cap",
            "preview": text[:2000],
        }, ensure_ascii=False)
    return {"jsonrpc": "2.0", "id": msg_id,
            "result": {"content": [{"type": "text", "text": text}],
                       "isError": not payload.get("ok", True)}}


def _error(msg_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id,
            "error": {"code": code, "message": message}}


def handle_message(msg: Dict[str, Any], controller) -> Optional[Dict[str, Any]]:
    """Handle one JSON-RPC message. Returns a response, or None for a notification."""
    if not isinstance(msg, dict):
        return _error(None, -32600, "invalid request")
    method = msg.get("method")
    msg_id = msg.get("id")
    params = msg.get("params") or {}
    if not isinstance(params, dict):
        params = {}

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": server_version()},
        }}
    if method in ("notifications/initialized", "initialized"):
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = params.get("name")
        if not isinstance(name, str) or not name:
            return _error(msg_id, -32602, "tools/call requires a tool name")
        payload = call_tool(name, params.get("arguments"), controller)
        return _result(msg_id, payload)
    if method == "shutdown":
        return {"jsonrpc": "2.0", "id": msg_id, "result": None}
    if msg_id is None:
        return None  # unknown notification: silently ignore, per JSON-RPC
    return _error(msg_id, -32601, f"method not found: {method}")


def serve(stdin=None, stdout=None, controller=None) -> int:
    """Serve newline-delimited JSON-RPC on stdio until EOF."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    # stdout is the protocol channel: any logging must go to stderr.
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    ctrl = controller if controller is not None else _default_controller()
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            stdout.write(json.dumps(_error(None, -32700, "parse error")) + "\n")
            stdout.flush()
            continue
        try:
            response = handle_message(msg, ctrl)
        except Exception as e:  # never take the server down on one bad call
            response = _error(msg.get("id") if isinstance(msg, dict) else None,
                              -32603, f"internal error: {type(e).__name__}")
        if response is not None:
            stdout.write(json.dumps(response, ensure_ascii=False, default=str) + "\n")
            stdout.flush()
    return 0


def _default_controller():
    cfg = load_config()
    ctrl = MemoryController(cfg, db_path=resolve_db_path(cfg))
    return _bind(ctrl, DEFAULT_MCP_ACTOR)


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--print-schemas" in argv:
        print(json.dumps({"server": SERVER_NAME, "version": server_version(),
                          "protocolVersion": PROTOCOL_VERSION,
                          "transport": "stdio",
                          "tools": TOOLS}, indent=2))
        return 0
    if "--help" in argv or "-h" in argv:
        print(__doc__)
        return 0
    if argv:
        print(f"unknown argument: {argv[0]}\nRun with --help or --print-schemas.",
              file=sys.stderr)
        return 2
    return serve()


if __name__ == "__main__":
    sys.exit(main())
