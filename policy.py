"""Actor policy checks for Hungry Hippa.

This module implements **identity + policy checks**, not capability-based
security. Callers pass an ``actor_id`` string; the runtime applies a fixed,
documented read/write policy. There are no unforgeable, revocable,
time-limited capability tokens here, and the code and docs must not claim
otherwise.

Policy (v1, deterministic, no ML):

  * The operator-facing agent runs as the owner actor (``primary``/``owner``).
    Owner reads everything except quarantined rows unless it explicitly asks
    for them while reviewing.
  * Every other actor is untrusted. Untrusted actors may read only rows they
    wrote themselves, only when the row is ``unclassified`` and not
    quarantined. They may never read another actor's quarantined row.
  * Writes from an untrusted actor are stored quarantined (see
    ``write_quarantine``), so a poisoned memory does not enter normal recall.
  * Purge (irreversible delete) is owner-only.

Sensitivity labels are a coarse ordering used for read policy only. They are
not an encryption boundary; encryption at rest is the operating system's job
(see ``docs/SECURITY.md``).
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

DEFAULT_ACTOR = "primary"
OWNER_ACTORS = frozenset({"primary", "owner"})
UNTRUSTED_ACTOR = "mcp-untrusted"

# Identity axis. This is decided by the channel (see ``trust.py``), never by a
# request field: ``identity=None`` keeps the historical name-based behaviour for
# in-process callers, while an external caller is always resolved to an explicit
# identity before it reaches these functions.
IDENTITY_OWNER = "owner"
IDENTITY_UNTRUSTED = "untrusted"

# Coarse ordering: unclassified < internal < private < restricted.
SENSITIVITIES = ("unclassified", "internal", "private", "restricted")

# Reasons returned by may_read(); used in explain/excluded payloads. They are
# content-free by construction.
REASON_QUARANTINED = "quarantined"
REASON_QUARANTINED_OTHER_ACTOR = "quarantined-other-actor"
REASON_OTHER_ACTOR = "other-actor"
REASON_SENSITIVITY = "sensitivity"
REASON_INACTIVE = "inactive"

VALID_STATUSES = ("active", "archived", "compressed", "purged",
                  "superseded", "contradicted")


def normalize_actor(actor_id: Any) -> str:
    """Return a usable actor id.

    ``None`` or the empty string means "no actor supplied" and falls back to the
    local owner actor (the operator-facing agent). A **whitespace-only** string
    is a supplied-but-invalid identity and must never be elevated to owner: it is
    treated as the untrusted actor instead. Otherwise the trimmed value is used
    verbatim.
    """
    if actor_id is None:
        return DEFAULT_ACTOR
    raw = str(actor_id)
    if raw == "":
        return DEFAULT_ACTOR
    trimmed = raw.strip()
    if not trimmed:
        # supplied, non-empty, but not a usable identity: do not grant owner.
        return UNTRUSTED_ACTOR
    return trimmed


def is_owner_identity(identity: Any) -> bool:
    """True only for an explicitly owner identity."""
    return str(identity or "").strip().lower() == IDENTITY_OWNER


def is_owner(actor_id: Any, identity: Any = None) -> bool:
    """Is this caller the owner?

    With ``identity`` given (the external path) the identity decides, and the
    ``actor_id`` label is irrelevant — a caller that names itself ``primary``
    without the owner token is not the owner. Without ``identity`` the historical
    name-based check applies, which is only reachable from in-process code.
    """
    if identity is not None:
        return is_owner_identity(identity)
    return normalize_actor(actor_id) in OWNER_ACTORS


def normalize_sensitivity(value: Any) -> str:
    v = str(value or "").strip().lower()
    return v if v in SENSITIVITIES else "unclassified"


def write_quarantine(actor_id: Any, requested: bool = False,
                     identity: Any = None) -> bool:
    """Whether a write should be stored quarantined.

    Untrusted callers always write quarantined; the owner may request quarantine
    explicitly (e.g. reviewing a suspect memory). With ``identity`` given, the
    identity decides and the ``actor_id`` label is ignored — naming yourself
    ``primary`` does not lift quarantine.
    """
    if identity is not None:
        return bool(requested) or not is_owner_identity(identity)
    return bool(requested) or not is_owner(actor_id)


def may_read(item: Dict[str, Any], actor_id: Any, *,
             include_quarantined: bool = False,
             identity: Any = None) -> Tuple[bool, str]:
    """Return ``(allowed, reason)`` for reading one memory row.

    ``item`` is a row dict (episode, belief or relationship). Missing columns
    are treated as their migration-v4 defaults, so this is safe to call on
    rows fetched before the columns existed.
    """
    actor = normalize_actor(actor_id)
    owner = is_owner(actor, identity)
    row_actor = normalize_actor(item.get("actor_id"))
    quarantined = bool(item.get("quarantined", 0))
    sensitivity = normalize_sensitivity(item.get("sensitivity"))

    # An untrusted caller whose label collides with an owner label must not be
    # able to read the owner's rows as if they were its own. ``trust.py`` remaps
    # such labels, and this is the second line of defence for any other caller.
    if not owner and row_actor in OWNER_ACTORS and actor in OWNER_ACTORS:
        return False, REASON_OTHER_ACTOR

    if quarantined:
        if not include_quarantined:
            return False, REASON_QUARANTINED
        # Reviewing quarantined rows is allowed for the owner, or for the
        # actor that wrote the row. Never for third parties.
        if not owner and row_actor != actor:
            return False, REASON_QUARANTINED_OTHER_ACTOR

    if not owner:
        if row_actor != actor:
            return False, REASON_OTHER_ACTOR
        if sensitivity != "unclassified":
            return False, REASON_SENSITIVITY
    return True, ""


def may_purge(actor_id: Any, identity: Any = None) -> bool:
    """Irreversible deletion is owner-only. Over MCP it is denied by default."""
    return is_owner(actor_id, identity)


# ---------------------------------------------------------------- capabilities

# Operations, cheapest to most dangerous. The mapping to channels is deliberately
# narrow: memory a model wrote must never gain the authority of memory the
# operator confirmed, and a model's tool call must not be able to rewrite or
# remove something the operator relies on. See docs/SECURITY.md.
CAP_READ = "read"
CAP_WRITE_CANDIDATE = "write_candidate"
CAP_APPROVE = "approve"
CAP_CORRECT = "correct"
CAP_FORGET = "forget"
CAP_PURGE = "purge"

CAPABILITY_ORDER = (CAP_READ, CAP_WRITE_CANDIDATE, CAP_APPROVE, CAP_CORRECT,
                    CAP_FORGET, CAP_PURGE)


def may_capability(capability: str, *, provenance: Any = None,
                   identity: Any = None, protected: bool = False) -> bool:
    """Whether a channel may perform an operation.

    ``provenance`` is the channel (``user`` = the human's own terminal or an MCP
    caller holding the owner token; ``agent`` = the model; ``external`` = anyone
    else). ``protected`` marks the target as operator-attested or high-confidence
    canonical.

      * read              — any owner-identity channel (untrusted callers read
                            only their own rows, enforced by ``may_read``)
      * write_candidate   — anything; an agent write is recorded as
                            ``agent_reported`` and an external write is
                            quarantined
      * approve           — operator only: only a human channel may attest what
                            the operator said
      * correct           — operator only when the target is protected, else any
                            owner-identity channel
      * forget            — same rule as correct: reversible, but it still takes
                            a memory out of recall
      * purge             — operator only, always
    """
    prov = str(provenance if provenance is not None else "").strip().lower()
    user = prov == "user"
    agent = prov == "agent"
    owner_identity = is_owner_identity(identity) if identity is not None else True

    if capability == CAP_READ:
        return owner_identity or prov == "external"  # untrusted reads own rows
    if capability == CAP_WRITE_CANDIDATE:
        return True
    if capability == CAP_APPROVE:
        return user
    if capability in (CAP_CORRECT, CAP_FORGET):
        if protected:
            return user
        return (user or agent) and owner_identity
    if capability == CAP_PURGE:
        return user and owner_identity
    return False


def capability_summary() -> Dict[str, Any]:
    """Content-free capability table for status output and tests."""
    return {
        "model": "capabilities are channel-derived, not requested",
        "caps": list(CAPABILITY_ORDER),
        "table": {
            CAP_READ: "owner identity: everything; untrusted: own rows only",
            CAP_WRITE_CANDIDATE: "any channel; agent -> agent_reported, external -> quarantined",
            CAP_APPROVE: "operator channel only",
            CAP_CORRECT: "operator only for protected targets, else owner identity",
            CAP_FORGET: "operator only for protected targets, else owner identity",
            CAP_PURGE: "operator channel + owner identity only",
        },
    }


def policy_summary() -> Dict[str, Any]:
    """Content-free description of the active policy, for status output."""
    if normalize_actor(None) not in OWNER_ACTORS:  # pragma: no cover - invariant
        raise AssertionError("default actor must be an owner actor")
    return {
        "model": "actor + policy checks (not capability-based security)",
        "identity_model": ("caller-supplied actor_id; a policy selector, not "
                           "authentication - a caller that claims an owner "
                           "actor is treated as the owner"),
        "owner_actors": sorted(OWNER_ACTORS),
        "untrusted_actor_default": UNTRUSTED_ACTOR,
        "sensitivities": list(SENSITIVITIES),
        "quarantine_on_untrusted_write": True,
        "purge_owner_only": True,
        "untrusted_can_read": "own rows only, unclassified, not quarantined",
    }
