"""Identity and trust binding for Hungry Hippa.

The problem this module exists to solve: ``actor_id`` arrives in the request
payload, so treating it as identity means any caller becomes the owner by
typing ``"primary"``. Claimed identity and trusted identity are different
things and must be resolved by the *server*, not by the caller.

Two independent axes, deliberately separate:

``identity``   may this caller read protected rows, forget them, purge them?
               ``owner`` or ``untrusted``. Derived from the channel:
               in-process code (the operator's own agent, the CLI) is owner;
               an MCP request is owner only if it presents the owner token.

``provenance`` how much trust does a memory *written* through this binding
               earn? ``user`` (a human channel), ``agent`` (the model, which
               may have been reading hostile text), ``external`` (an untrusted
               caller). Independent of identity: the operator's own agent has
               owner identity and only ``agent`` provenance, because the agent
               is not the user.

Trust anchors, in order of strength:

1. **In-process** — code running inside the operator's own process (the Hermes
   plugin, the CLI, tests). Not forgeable by a request.
2. **Owner token** — a 32-byte random token in a ``0600`` file
   (``$HERMES_HOME/hungry_hippa.owner.token``, override with
   ``HUNGRY_HIPPA_OWNER_TOKEN_FILE``) that only the operator's OS user can
   read. A client that can read it is running as the operator and already has
   the database anyway; a client that cannot is refused.
3. **Everything else** — untrusted.

This is a local capability, not authentication, and it is not presented as
authentication: the transport is stdio, so "who can read the token file" is
exactly "who is the operator or running as them". It stops a *client* from
naming itself owner. It does not and cannot stop a process that already holds
the operator's uid.
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
UNTRUSTED = "untrusted"

PROVENANCE_USER = "user"
PROVENANCE_AGENT = "agent"
PROVENANCE_EXTERNAL = "external"

CHANNEL_MCP = "mcp"
CHANNEL_LOCAL = "local"
CHANNEL_CLI = "cli"
CHANNEL_AGENT_TOOL = "agent_tool"

TOKEN_FILENAME = "hungry_hippa.owner.token"
TOKEN_BYTES = 32
TOKEN_MAX_CHARS = 128

# Source classes the runtime assigns itself, rather than believing a caller:
# the model's own report of where something came from, and anything an
# unauthorized caller wrote.
AGENT_SOURCE_CLASS = "agent_reported"
EXTERNAL_SOURCE_CLASS = "external_source"
TRUSTED_SOURCE_CLASSES = frozenset({"user_explicit"})


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
    return OWNER if v == OWNER else UNTRUSTED


def normalize_provenance(value: Any) -> str:
    v = str(value or "").strip().lower()
    return v if v in (PROVENANCE_USER, PROVENANCE_AGENT, PROVENANCE_EXTERNAL) \
        else PROVENANCE_EXTERNAL


def resolve_provenance(value: Any, identity: Any = None) -> str:
    """Provenance for a write, with the in-process default spelled out.

    ``None``/``""`` means "the caller did not declare a channel" — which happens
    only for code already running inside the operator's process (the write paths
    in the controller and the MCP server always pass one explicitly). Such a call
    inherits the identity's default rather than being read as external: an
    untrusted identity still resolves to ``external``. ``normalize_provenance``
    keeps its stricter default for constructing bindings.
    """
    if value is None or str(value).strip() == "":
        if identity is not None and not _policy.is_owner_identity(identity):
            return PROVENANCE_EXTERNAL
        return PROVENANCE_USER
    return normalize_provenance(value)


# ------------------------------------------------------------ the owner token

def token_path() -> Path:
    override = os.environ.get("HUNGRY_HIPPA_OWNER_TOKEN_FILE", "")
    if override:
        return Path(override)
    home = os.environ.get("HERMES_HOME") or os.path.join(
        os.path.expanduser("~"), ".hermes")
    return Path(home) / TOKEN_FILENAME


def _write_token_file(path: Path) -> str:
    token = secrets.token_urlsafe(TOKEN_BYTES)
    path.parent.mkdir(parents=True, exist_ok=True)
    # create with 0600 from the start: never briefly world-readable
    fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(token + "\n")
    except Exception:
        os.close(fd) if not fd < 0 else None
        raise
    return token


def ensure_owner_token(path: Optional[Path] = None) -> str:
    """Return the owner token, creating the 0600 file if it does not exist."""
    p = Path(path) if path else token_path()
    try:
        if p.exists():
            token = p.read_text(encoding="utf-8").strip()
            if token:
                return token
            return _write_token_file(p)
    except FileNotFoundError:
        pass
    return _write_token_file(p)


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
    """Constant-time check of a caller-supplied token against the token file."""
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
    result; it is not the user, so a memory it writes does not inherit the
    user's authority (see ``docs/SECURITY.md``).
    """
    return local_binding(actor_id, channel=CHANNEL_AGENT_TOOL,
                         provenance=PROVENANCE_AGENT)


def external_binding(claimed_actor: Any = "", token: Any = "") -> Binding:
    """Resolve an external (MCP) caller.

    Owner identity requires a valid owner token. The claimed ``actor_id`` is
    kept only as a *label*, and a claim that collides with an owner label is
    remapped so an untrusted caller can never alias the owner's rows.
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


def verified_source_class(claimed: Any, provenance: Any) -> str:
    """The source class the runtime is willing to believe for a write.

    ``source_class`` is caller-supplied metadata, so it is a *claim*. What gets
    stored as the effective class — and therefore what the trust weighting in
    contradiction resolution uses — is decided here from the channel:

      * ``user`` provenance (the operator's CLI, or an MCP caller holding the
        owner token) may assert the origin; the claim becomes the verified class.
      * ``agent`` provenance (the model) is recorded as ``agent_reported``: the
        model may describe where something came from, but it does not get to
        promote its own text to ``user_explicit``.
      * ``external`` provenance (any other caller) is always
        ``external_source``, and its writes are quarantined anyway.

    The claim is preserved next to it in ``claimed_source_class``, so provenance
    stays inspectable rather than silently rewritten.
    """
    claim = str(claimed or "").strip() or "hermes_inference"
    prov = normalize_provenance(provenance)
    if prov == PROVENANCE_EXTERNAL:
        return EXTERNAL_SOURCE_CLASS
    if prov == PROVENANCE_AGENT:
        return AGENT_SOURCE_CLASS
    return claim


def binding_summary() -> dict:
    """Content-free description of the binding model, for status output."""
    mode = token_file_mode()
    return {
        "model": ("channel-derived: in-process code is owner; an MCP caller is "
                  "owner only with the owner token, regardless of any actor_id it sends"),
        "identity_axis": "who may read protected rows / forget / purge",
        "provenance_axis": "how much trust a written memory earns (user > agent > external)",
        "token_file": str(token_path()),
        "token_file_present": read_owner_token() is not None,
        "token_file_mode": oct(mode) if mode is not None else None,
        "token_file_lax": bool(mode is not None and (mode & 0o077)),
        "not_authentication": ("stdio transport: the token proves the caller can read "
                              "an operator-only file, not who they are over a network"),
    }
