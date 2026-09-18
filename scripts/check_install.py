#!/usr/bin/env python3
"""Build and smoke-test a wheel in a fresh, disposable virtual environment.

Run with ``python scripts/check_install.py`` (also part of ``check_all.py``).
Building/installing dependencies needs package-index access or a configured pip
cache. The installed runtime checks are offline: temporary XDG directories,
database and token paths, vectors disabled, no inherited owner authorization.
No project environment, user configuration or existing store is modified.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import venv


REPO = Path(__file__).resolve().parent.parent
EXPECTED_TOOLS = sorted((
    "hippa_build_context", "hippa_forget", "hippa_recall",
    "hippa_record_outcome", "hippa_remember", "hippa_status",
))


def isolated_environment(root: Path) -> dict[str, str]:
    """Keep interpreter, pip and runtime overrides out of the disposable check."""
    env = {
        key: value for key, value in os.environ.items()
        if not key.startswith("HUNGRY_HIPPA_")
        and key not in {
            "LIVING_CORTEX_DB", "PYTHONPATH", "PYTHONHOME", "PYTHONUSERBASE",
            "VIRTUAL_ENV", "PIP_TARGET", "PIP_PREFIX", "PIP_USER",
        }
    }
    for name in ("CONFIG", "DATA", "STATE", "CACHE"):
        directory = root / name.lower()
        directory.mkdir()
        env[f"XDG_{name}_HOME"] = str(directory)
    env.update({
        "HUNGRY_HIPPA_DB": str(root / "data" / "smoke.db"),
        "HUNGRY_HIPPA_OWNER_TOKEN_FILE": str(root / "state" / "owner.token"),
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PIP_CONFIG_FILE": os.devnull,
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_NO_INPUT": "1",
    })
    config_dir = root / "config" / "hungry-hippa"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(json.dumps({
        "retrieval": {"vectors_enabled": False},
        "manager": {"enabled": False},
    }), encoding="utf-8")
    return env


def run(command: list[str], *, cwd: Path, env: dict[str, str],
        timeout: int = 180) -> str:
    result = subprocess.run(command, cwd=cwd, env=env, text=True,
                            capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(
            f"{Path(command[0]).name} exited {result.returncode}:\n"
            + (result.stdout + result.stderr)[-6000:])
    return result.stdout


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="hh_install_") as directory:
        root = Path(directory)
        env = isolated_environment(root)
        source = root / "source"
        source.mkdir()
        # Copy only build inputs: setuptools must not leave build/egg-info
        # artifacts in the checkout, or accidentally package a developer's data.
        for name in ("pyproject.toml", "README.md", "LICENSE"):
            shutil.copy2(REPO / name, source / name)
        shutil.copytree(REPO / "src", source / "src",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info"))
        wheels = root / "wheels"
        wheels.mkdir()
        print("Building the distribution wheel in a temporary source copy", flush=True)
        run([sys.executable, "-m", "pip", "wheel", "--quiet", "--no-deps",
             "--wheel-dir", str(wheels), str(source)], cwd=root, env=env)
        artifacts = list(wheels.glob("hungry_hippa-*.whl"))
        if len(artifacts) != 1:
            raise RuntimeError("expected exactly one Hungry Hippa wheel")

        virtualenv = root / "venv"
        venv.EnvBuilder(with_pip=True).create(virtualenv)
        binaries = virtualenv / ("Scripts" if os.name == "nt" else "bin")
        python = str(binaries / ("python.exe" if os.name == "nt" else "python"))
        console_suffix = ".exe" if os.name == "nt" else ""
        cli = str(binaries / ("hungry-hippa" + console_suffix))
        server = str(binaries / ("hungry-hippa-mcp" + console_suffix))
        print("Installing the wheel and declared dependencies in a fresh venv", flush=True)
        run([python, "-m", "pip", "install", "--quiet", str(artifacts[0])],
            cwd=root, env=env)
        run([python, "-m", "pip", "check"], cwd=root, env=env)
        work = root / "outside-checkout"
        work.mkdir()
        version = run([python, "-c", """
import importlib.metadata as metadata
from pathlib import Path
import sys
import hungry_hippa
from hungry_hippa.version import __version__
from hungry_hippa.mcp_server import server_version
assert Path(hungry_hippa.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
assert __version__ == metadata.version('hungry-hippa') == server_version()
print(__version__)
"""], cwd=work, env=env, timeout=60).strip()
        help_text = run([cli, "--help"], cwd=work, env=env, timeout=60)
        assert "ingest" in help_text and "quarantine" in help_text
        status = json.loads(run([cli, "status"], cwd=work, env=env, timeout=60))
        assert status["path"] == env["HUNGRY_HIPPA_DB"], status
        assert status["failures"] == 0, status
        assert status["counts"] and all(value == 0 for value in status["counts"].values()), status

        schemas = json.loads(run([server, "--print-schemas"], cwd=work, env=env, timeout=60))
        assert schemas["version"] == version, schemas
        assert sorted(tool["name"] for tool in schemas["tools"]) == EXPECTED_TOOLS
        public_schema = json.dumps(schemas).lower()
        assert "owner_token" not in public_schema and "export" not in public_schema

        # Exercise the installed console script through the official SDK, from
        # outside both the real checkout and the temporary build source.
        run([python, "-c", """
import asyncio
import json
import os
import sys
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

async def check():
    params = StdioServerParameters(command=sys.argv[1], env=dict(os.environ))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=30) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert sorted(tool.name for tool in tools.tools) == json.loads(sys.argv[2])
            result = await session.call_tool('hippa_status', {})
            assert not result.is_error, result
            payload = json.loads(''.join(getattr(block, 'text', '') for block in result.content))
            assert payload.get('ok') is True, payload

asyncio.run(check())
""", server, json.dumps(EXPECTED_TOOLS)], cwd=work, env=env, timeout=60)
        print(f"PASS wheel {version}: isolated import, CLI health, six MCP tools and stdio call")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (AssertionError, OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"FAIL clean wheel installation: {error}", file=sys.stderr)
        sys.exit(1)
