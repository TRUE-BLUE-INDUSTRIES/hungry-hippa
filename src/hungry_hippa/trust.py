"""Identity, provenance and trust binding for Hungry Hippa.

The problem this module exists to solve: ``actor_id`` arrives in the request
payload, so treating it as identity means any caller becomes the owner by typing
``"primary"``. Claimed identity and trusted identity are different things and must
be resolved by the *server*, not by the caller.

Three independent ideas, deliberately separate:

``identity``    may this caller read protected rows, forget them, purge them?
                ``owner`` / ``system`` / ``untrusted``. Derived from the channel:
                in-process operator code is owner; the runtime's own background
                work is system; an MCP process whose launch context presented the
                owner token is owner; anything else is untrusted.

``provenance``  how much trust does a memory *written* through this binding earn?
                ``user`` (a human channel), ``agent`` (the model, which may have
                been reading hostile text), ``agent_consolidation`` (the runtime's
                own sleep pass), ``external`` (an untrusted caller). Independent of
                identity: the operator's own agent has owner identity and only
                ``agent`` provenance, because the agent is not the user.

``channel``     where the call came in from, recorded on every row.

Trust anchors, in order of strength:

1. **In-process** — code running inside the operator's own process (the CLI, the
   local agent adapter, tests). Not forgeable by a request.
2. **Owner token** — 32 random bytes in a ``0600`` file under the XDG state
   directory that only the operator's OS user can read. The MCP server reads
   ``HUNGRY_HIPPA_OWNER_TOKEN`` from its *launch environment* and verifies it
   against that file, so the authenticated thing is the launch context the operator
   configured — never an argument a model can invent.
3. **Everything else** — untrusted.

This is a local capability, not authentication, and it is not presented as
authentication: the transport is stdio, so "can read the token file" is exactly
"who is the operator or running as them". It stops a *client* from naming itself
owner. It does not and cannot stop a process that already holds the operator's uid.
"""

from __future__ import annotations

import hmac
import os
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from . import policy as _policy

# ---------------------------------------------------------------- identities

OWNER = "owner"
SYSTEM = "system"
UNTRUSTED = "untrusted"

IDENTITIES = (OWNER, SYSTEM, UNTRUSTED)

PROVENANCE_USER = "user"
PROVENANCE_AGENT = "agent"
PROVENANCE_AGENT_CONSOLIDATION = "agent_consolidation"
PROVENANCE_EXTERNAL = "external"

PROVENANCES = (PROVENANCE_USER, PROVENANCE_AGENT, PROVENANCE_AGENT_CONSOLIDATION,
               PROVENANCE_EXTERNAL)

CHANNEL_MCP = "mcp"
CHANNEL_LOCAL = "local"
CHANNEL_CLI = "cli"
CHANNEL_AGENT_TOOL = "agent_tool"
CHANNEL_CONSOLIDATION = "consolidation"
CHANNEL_IMPORT = "import"

# Source classes the runtime assigns itself, rather than believing a caller:
# the model's own report of where something came from, and anything an
# unauthorized caller wrote.
AGENT_SOURCE_CLASS = "agent_reported"
CONSOLIDATION_SOURCE_CLASS = "derived_pattern"
EXTERNAL_SOURCE_CLASS = "external_source"
TRUSTED_SOURCE_CLASSES = frozenset({"user_explicit"})

APP_DIR_NAME = "hungry-hippa"
TOKEN_FILENAME = "owner.token"
TOKEN_BYTES = 32
TOKEN_MAX_CHARS = 128
OWNER_TOKEN_ENV = "HUNGRY_HIPPA_OWNER_TOKEN"
TOKEN_FILE_ENV = "HUNGRY_HIPPA_OWNER_TOKEN_FILE"


@dataclass(frozen=True)
class Binding:
    """The server's decision about who is calling and how much to trust them."""

    actor_id: str
    identity: str = UNTRUSTED
    provenance: str = PROVENANCE_EXTERNAL
    channel: str = CHANNEL_MCP

    @property
    def is_owner(self) -> bool:
        return self.identity == OWNER

    def as_dict(self) -> dict:
        return {"actor_id": self.actor_id, "identity": self.identity,
                "provenance": self.provenance, "channel": self.channel}


def normalize_identity(value: Any) -> str:
    v = str(value or "").strip().lower()
    return v if v in IDENTITIES else UNTRUSTED


def normalize_provenance(value: Any) -> str:
    v = str(value or "").strip().lower()
    return v if v in PROVENANCES else PROVENANCE_EXTERNAL


def resolve_provenance(value: Any, identity: Any = None) -> str:
    """Provenance for a write, with the in-process default spelled out.

    ``None``/``""`` means "the caller did not declare a channel" — which happens
    only for code already running inside the operator's process (the write paths in
    the controller and the MCP server always pass one explicitly). Such a call
    inherits the identity's default rather than being read as external: an
    untrusted identity still resolves to ``external``. ``normalize_provenance``
    keeps its stricter default for constructing bindings.
    """
    if value is None or str(value).strip() == "":
        resolved_identity = normalize_identity(identity) if identity is not None else OWNER
        if resolved_identity == UNTRUSTED:
            return PROVENANCE_EXTERNAL
        if resolved_identity == SYSTEM:
            return PROVENANCE_AGENT_CONSOLIDATION
        return PROVENANCE_USER
    return normalize_provenance(value)


# ------------------------------------------------------------ the owner token

def state_dir() -> Path:
    """The Hungry Hippa state directory: ``$XDG_STATE_HOME/hungry-hippa``.

    Falls back to ``~/.local/state/hungry-hippa`` when ``XDG_STATE_HOME`` is unset.
    No Hermes, no ``~/.hermes``: Hungry Hippa owns its own state location.
    """
    base = os.environ.get("XDG_STATE_HOME", "").strip()
    root = Path(base) if base else Path(os.path.expanduser("~")) / ".local" / "state"
    return root / APP_DIR_NAME


def token_path() -> Path:
    override = os.environ.get(TOKEN_FILE_ENV, "").strip()
    if override:
        return Path(override)
    return state_dir() / TOKEN_FILENAME


def _create_token_file(path: Path, token: str) -> None:
    """Create the token file ``0600`` in one step and write it as bytes.

    The descriptor is closed exactly once, in a ``finally``: an earlier version
    could double-close through ``os.fdopen``'s error path. The file is created
    with the restrictive mode from the start, never briefly wider.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(fd, (token + "\n").encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        os.chmod(str(path), 0o600)
    except OSError:
        pass


def ensure_owner_token(path: Optional[Path] = None) -> str:
    """Return the owner token, creating the ``0600`` file if it does not exist.

    An existing but empty or blank file is not a reason to fail: the file is
    rewritten in place (its descriptor is closed properly first), so an empty file
    never turns into an ``O_EXCL`` error.
    """
    p = Path(path) if path else token_path()
    try:
        existing = p.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        existing = ""
    except OSError:
        existing = ""
    if existing:
        return existing
    token = secrets.token_urlsafe(TOKEN_BYTES)
    if p.exists():
        # present but empty/corrupt: reuse the path, keep the mode tight
        tmp = p.parent / (p.name + ".new")
        _create_token_file(tmp, token)
        os.replace(str(tmp), str(p))
        return token
    _create_token_file(p, token)
    return token


def read_owner_token(path: Optional[Path] = None) -> Optional[str]:
    p = Path(path) if path else token_path()
    try:
        token = p.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return token or None


def token_file_mode(path: Optional[Path] = None) -> Optional[int]:
    p = Path(path) if path else token_path()
    try:
        return stat.S_IMODE(os.stat(p).st_mode)
    except OSError:
        return None


def token_matches(supplied: Any, path: Optional[Path] = None) -> bool:
    """Constant-time check of a caller-supplied token against the token file.

    ``hmac.compare_digest`` is used, so the comparison leaks no timing information
    about how much of the token matched.
    """
    if not supplied or not isinstance(supplied, str):
        return False
    if len(supplied) > TOKEN_MAX_CHARS:
        return False
    expected = read_owner_token(path)
    if not expected:
        return False
    return hmac.compare_digest(supplied.strip(), expected)


# ------------------------------------------------------------- the bindings

def local_binding(actor_id: str = "", *, channel: str = CHANNEL_LOCAL,
                  provenance: str = PROVENANCE_USER) -> Binding:
    """A binding for code already running inside the operator's own process."""
    return Binding(actor_id=_policy.normalize_actor(actor_id or None),
                   identity=OWNER, provenance=normalize_provenance(provenance),
                   channel=channel)


def agent_binding(actor_id: str = "") -> Binding:
    """The operator's own agent: owner identity, but only agent provenance.

    The model may have been reading a web page, a dependency README or a tool
    result; it is not the user, so a memory it writes does not inherit the user's
    authority (see docs/SECURITY.md).
    """
    return local_binding(actor_id, channel=CHANNEL_AGENT_TOOL,
                         provenance=PROVENANCE_AGENT)


def system_binding(actor_id: str = "system") -> Binding:
    """The runtime's own background work (consolidation, sleep passes).

    System identity may read everything and write derived rows normally, but it is
    **not** the operator: it cannot approve, correct a protected fact, forget a
    protected fact, or purge, and everything it writes is marked
    ``agent_consolidation`` provenance so it can never be mistaken for human input.
    """
    return Binding(actor_id=actor_id, identity=SYSTEM,
                   provenance=PROVENANCE_AGENT_CONSOLIDATION,
                   channel=CHANNEL_CONSOLIDATION)


def external_binding(claimed_actor: Any = "", token: Any = "") -> Binding:
    """Resolve an MCP caller from the *server's* launch context.

    Owner identity requires a token that matches the operator's ``0600`` token
    file. The claimed ``actor_id`` is kept only as a *label*, and a claim that
    collides with an owner label is remapped so an untrusted caller can never
    alias the owner's rows.
    """
    if token_matches(token):
        return Binding(actor_id=_policy.normalize_actor(claimed_actor or None),
                       identity=OWNER, provenance=PROVENANCE_USER,
                       channel=CHANNEL_MCP)
    label = _policy.normalize_actor(claimed_actor)
    if label in _policy.OWNER_ACTORS:
        label = _policy.UNTRUSTED_ACTOR
    return Binding(actor_id=label, identity=UNTRUSTED,
                   provenance=PROVENANCE_EXTERNAL, channel=CHANNEL_MCP)


def server_binding(claimed_actor: Any = "",
                   env_token: Optional[str] = None) -> Binding:
    """The binding for an MCP *server instance*, from its launch environment.

    ``HUNGRY_HIPPA_OWNER_TOKEN`` is read once at start-up and verified against the
    operator's token file here. A server launched without it — or with a token that
    does not match — is an untrusted instance, and no argument a model can send
    changes that.
    """
    token = env_token if env_token is not None else os.environ.get(OWNER_TOKEN_ENV, "")
    return external_binding(claimed_actor, token)


def verified_source_class(claimed: Any, provenance: Any) -> str:
    """The source class the runtime is willing to believe for a write.

    ``source_class`` is caller-supplied metadata, so it is a *claim*. What gets
    stored as the effective class — and therefore what the trust weighting in
    contradiction resolution uses — is decided here from the channel:

      * ``user`` provenance (the operator's CLI, or an owner-authorized MCP
        process) may assert the origin; the claim becomes the verified class.
      * ``agent`` provenance (the model) is recorded as ``agent_reported``: the
        model may describe where something came from, but it does not get to
        promote its own text to ``user_explicit``.
      * ``agent_consolidation`` provenance (the runtime's sleep pass) is recorded
        as ``derived_pattern``.
      * ``external`` provenance (any other caller) is always ``external_source``,
        and its writes are quarantined anyway.

    The claim is preserved next to it in ``claimed_source_class``, so provenance
    stays inspectable rather than silently rewritten.
    """
    claim = str(claimed or "").strip() or "agent_inference"
    prov = normalize_provenance(provenance)
    if prov == PROVENANCE_EXTERNAL:
        return EXTERNAL_SOURCE_CLASS
    if prov == PROVENANCE_AGENT:
        return AGENT_SOURCE_CLASS
    if prov == PROVENANCE_AGENT_CONSOLIDATION:
        return CONSOLIDATION_SOURCE_CLASS
    return claim


def binding_summary() -> dict:
    """Content-free description of the binding model, for status output."""
    mode = token_file_mode()
    token = os.environ.get(OWNER_TOKEN_ENV, "")
    return {
        "model": ("channel-derived: in-process operator code is owner; the runtime's "
                  "own background work is system; an MCP server instance is owner "
                  "only when its launch environment carried the verified owner "
                  "token, regardless of any actor_id the caller sends"),
        "identity_axis": "who may read protected rows / forget / purge",
        "provenance_axis": "how much trust a written memory earns (user > agent > agent_consolidation > external)",
        "identities": list(IDENTITIES),
        "provenances": list(PROVENANCES),
        "token_file": str(token_path()),
        "token_file_present": read_owner_token() is not None,
        "token_file_mode": oct(mode) if mode is not None else None,
        "token_file_lax": bool(mode is not None and (mode & 0o077)),
        "server_token_env": OWNER_TOKEN_ENV,
        "server_token_supplied": bool(token),
        "server_token_verified": token_matches(token) if token else False,
        "not_authentication": ("stdio transport: the token proves the launcher could "
                               "read an operator-only file, not who they are over a "
                               "network"),
    }
