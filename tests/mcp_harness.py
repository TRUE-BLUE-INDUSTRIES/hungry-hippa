"""Shared test harness for driving Hungry Hippa through the official MCP SDK.

Everything MCP-shaped in the test suite goes through here, so no test ever
re-implements the protocol. The client is the SDK's ``ClientSession`` over the
SDK's stdio transport, talking to ``mcp_server.py`` in a real subprocess.

Trust model under test (see ``trust.py``): the *server launch environment*
authenticates. ``mcp_server.py`` reads ``HUNGRY_HIPPA_OWNER_TOKEN`` from its own
environment and verifies it against the operator's ``0600`` token file, so:

  * an owner session launches the server with the token in its environment;
  * an untrusted session launches it without one.

No test ever writes a token into a committed file, and no assertion ever prints it.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

REPO = Path(__file__).resolve().parent.parent
PACKAGE_DIR = REPO / "src" / "hungry_hippa"   # src layout
MCP_SERVER = PACKAGE_DIR / "mcp_server.py"
PACKAGE = "hungry_hippa"


sys.path.insert(0, str(Path(__file__).resolve().parent))   # tests/ (shared helpers)
from _package import import_package  # noqa: E402

_PACKAGE = import_package()


def import_mcp_server():
    """Return the ``hungry_hippa.mcp_server`` module (in-process server checks).

    Imported normally from the package: it is an ordinary module now, so there is
    no need to load the file by path and no second copy of it in ``sys.modules``.
    """
    from hungry_hippa import mcp_server
    return mcp_server

from hungry_hippa import trust                      # noqa: E402
from hungry_hippa.config import load_config         # noqa: E402
from hungry_hippa.controller import MemoryController  # noqa: E402

SDK_AVAILABLE = True
try:                                                # the official SDK
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
except Exception:                                   # pragma: no cover
    SDK_AVAILABLE = False


# --------------------------------------------------------------------- tokens

def make_token_file(tmp: Optional[str] = None) -> Tuple[str, str]:
    """Create a throwaway token file; return ``(path, token)``.

    Never touches the operator's real token: the path is always inside a temporary
    directory that the caller owns.
    """
    base = tmp or tempfile.mkdtemp(prefix="hh_token_")
    path = os.path.join(base, "owner.token")
    token = trust.ensure_owner_token(Path(path))
    return path, token


def session_env(db_path: str, token_file: Optional[str] = None,
                token: Optional[str] = None, **extra: str) -> Dict[str, str]:
    """Environment for a server subprocess.

    Without ``token`` the server starts with no owner token at all — the honest
    "untrusted instance" configuration.
    """
    env = dict(os.environ)
    env["HUNGRY_HIPPA_DB"] = db_path
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("LIVING_CORTEX_DB", None)
    env.pop(trust.OWNER_TOKEN_ENV, None)
    if token_file:
        env[trust.TOKEN_FILE_ENV] = token_file
    else:
        env.pop(trust.TOKEN_FILE_ENV, None)
    if token is not None:
        env[trust.OWNER_TOKEN_ENV] = token
    env.update(extra)
    return env


# ------------------------------------------------------------------- sessions

async def _run_calls_async(db_path: str, calls: Iterable[Tuple[str, Dict[str, Any]]],
                           *, token_file: Optional[str] = None,
                           token: Optional[str] = None,
                           cwd: Optional[str] = None,
                           read_timeout: float = 30.0) -> Dict[str, Any]:
    """Start the server, initialise, run each call, and return everything seen."""
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(MCP_SERVER)],
        env=session_env(db_path, token_file, token),
        cwd=str(cwd or REPO),
    )
    results: List[Dict[str, Any]] = []
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=read_timeout) as session:
            init = await session.initialize()
            tools = await session.list_tools()
            for name, args in calls:
                r = await session.call_tool(name, args)
                text = ""
                for block in getattr(r, "content", []) or []:
                    text += getattr(block, "text", "") or ""
                parsed: Any
                try:
                    parsed = json.loads(text) if text else None
                except json.JSONDecodeError:
                    parsed = None
                results.append({"name": name, "is_error": bool(getattr(r, "is_error", False)),
                                "text": text, "json": parsed,
                                "structured": getattr(r, "structured_content", None)})
    server_info = getattr(init, "serverInfo", None) or getattr(init, "server_info", None)
    protocol = getattr(init, "protocolVersion", None) or getattr(init, "protocol_version", None)
    return {
        "initialize": {"server": server_info, "protocol": protocol},
        "tools": [{"name": t.name, "description": t.description,
                   "input_schema": getattr(t, "input_schema", None)} for t in tools.tools],
        "results": results,
    }


def run_calls(db_path: str, calls: Iterable[Tuple[str, Dict[str, Any]]], **kwargs) -> Dict[str, Any]:
    """Synchronous wrapper: one server process, one initialised session."""
    return asyncio.run(_run_calls_async(db_path, list(calls), **kwargs))


def one_call(db_path: str, name: str, args: Optional[Dict[str, Any]] = None,
             **kwargs) -> Dict[str, Any]:
    """One tool call against a fresh server process; returns the parsed payload."""
    out = run_calls(db_path, [(name, args or {})], **kwargs)
    return out["results"][0]["json"] or {}


def expect_tool_error(db_path: str, name: str, args: Dict[str, Any], **kwargs) -> str:
    """Run a call expected to fail; return the error text (never raises for us)."""
    out = run_calls(db_path, [(name, args)], **kwargs)
    r = out["results"][0]
    return (r["text"] or "") + (" (is_error)" if r["is_error"] else "")


# ------------------------------------------------------- in-process surfaces

def fresh_db(prefix: str = "hh_mcp_") -> str:
    base = tempfile.mkdtemp(prefix=prefix)
    return os.path.join(base, "hungry_hippa.db")


def controller(db_path: str, *, binding: Optional[trust.Binding] = None) -> MemoryController:
    cfg = load_config()
    cfg["retrieval"]["vectors_enabled"] = False
    ctrl = MemoryController(cfg, db_path=db_path)
    ctrl.bind_session(session_id="harness", platform="cli",
                      trust=binding or trust.local_binding("primary"))
    return ctrl


def in_process_call(db_path: str, name: str, args: Optional[Dict[str, Any]] = None,
                    *, token: str = "", binding: Optional[trust.Binding] = None
                    ) -> Dict[str, Any]:
    """Call a tool through the server object without a subprocess.

    Used for server-side assertions (limits, policy) where a full session would
    only add noise. The SDK still owns schema validation and dispatch here.
    """
    server_mod = import_mcp_server()
    ctrl = controller(db_path, binding=binding)
    app = server_mod.build_server(controller=ctrl, owner_token=token)
    result = asyncio.run(app.call_tool(name, args or {}))
    text = ""
    for block in getattr(result, "content", []) or []:
        text += getattr(block, "text", "") or ""
    try:
        return json.loads(text) if text else {}
    except json.JSONDecodeError:
        return {"_raw": text}
