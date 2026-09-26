"""Canonical version for Hungry Hippa.

One source of truth: the package version. ``pyproject.toml`` carries the same
string (a test asserts they agree), and ``mcp_server.server_version()`` reports it
to MCP clients. There is no plugin manifest and no separate metadata file to drift.
"""

from __future__ import annotations

__version__ = "1.1.0"
