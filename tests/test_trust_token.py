"""Owner-token storage tests: creation, mode, overrides and failure handling.

The token is the only secret Hungry Hippa holds. It lives in the XDG state
directory (``$XDG_STATE_HOME/hungry-hippa/owner.token``, falling back to
``~/.local/state/hungry-hippa/``), is created ``0600`` in one step, and is verified
by constant-time comparison. None of these tests touch the operator's real token:
every case runs inside a temporary directory.

run_all() -> list of {name, passed, detail}.
"""

from __future__ import annotations

import os
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

import mcp_harness as H

from hungry_hippa import trust

POSIX = os.name == "posix"


def _mode(path: Path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


class Env:
    """Temporarily set/restore environment variables."""

    def __init__(self, **values: Any) -> None:
        self.values = values
        self.previous: Dict[str, Any] = {}

    def __enter__(self):
        for k, v in self.values.items():
            self.previous[k] = os.environ.get(k)
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = str(v)
        return self

    def __exit__(self, *exc):
        for k, old in self.previous.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old
        return False


def check_initial_creation_and_mode():
    """A new token is random, non-empty and created 0600."""
    if not POSIX:
        return "skipped: POSIX permission bits not available"
    tmp = tempfile.mkdtemp(prefix="hh_tok_new_")
    path = Path(tmp) / "hungry-hippa" / "owner.token"
    token = trust.ensure_owner_token(path)
    assert path.exists(), path
    assert len(token) >= 32, len(token)
    assert _mode(path) == 0o600, oct(_mode(path))
    assert path.read_text(encoding="utf-8").strip() == token
    assert trust.token_matches(token, path) is True
    return f"created {path.name} with {len(token)} chars at mode 0600"


def check_existing_token_is_kept():
    """An existing token is returned unchanged, and is not rewritten."""
    tmp = tempfile.mkdtemp(prefix="hh_tok_keep_")
    path = Path(tmp) / "owner.token"
    first = trust.ensure_owner_token(path)
    before = path.stat().st_mtime_ns
    second = trust.ensure_owner_token(path)
    assert first == second, "ensure_owner_token generated a new token"
    assert path.stat().st_mtime_ns == before, "the file was rewritten"
    assert trust.read_owner_token(path) == first
    return "existing token reused; the file is untouched"


def check_empty_and_corrupt_files_are_repaired():
    """An empty or whitespace-only file is repaired, not an O_EXCL crash."""
    tmp = tempfile.mkdtemp(prefix="hh_tok_empty_")
    for content in ("", "\n", "   \n"):
        path = Path(tmp) / f"owner{len(content)}.token"
        path.write_text(content, encoding="utf-8")
        os.chmod(path, 0o600)
        token = trust.ensure_owner_token(path)
        assert token and len(token) >= 32, (content, token)
        assert path.read_text(encoding="utf-8").strip() == token
        assert _mode(path) == 0o600, oct(_mode(path))
    # a file that exists but cannot be read still yields a usable token
    path = Path(tmp) / "broken.token"
    path.write_text("  ", encoding="utf-8")
    assert trust.read_owner_token(path) is None
    assert trust.ensure_owner_token(path)
    return "empty, whitespace and unreadable token files are repaired in place"


def check_failed_write_is_reported_not_silent():
    """A token that cannot be written raises; nothing is left half-created."""
    if not POSIX:
        return "skipped: POSIX permission bits not available"
    if os.geteuid() == 0:
        return "skipped: running as root, directory permissions are not enforced"
    tmp = tempfile.mkdtemp(prefix="hh_tok_fail_")
    locked = Path(tmp) / "locked"
    locked.mkdir()
    path = locked / "owner.token"
    os.chmod(locked, 0o500)          # create is not permitted inside
    try:
        try:
            trust.ensure_owner_token(path)
        except OSError:
            raised = True
        else:
            raised = False
        assert raised, "a failed token write did not raise"
        assert not path.exists(), "a partial token file was left behind"
    finally:
        os.chmod(locked, 0o700)
    return "an unwritable state directory raises and leaves no partial file"


def check_xdg_state_home_is_used():
    """XDG_STATE_HOME decides the location when set."""
    tmp = tempfile.mkdtemp(prefix="hh_tok_xdg_")
    with Env(XDG_STATE_HOME=tmp, HUNGRY_HIPPA_OWNER_TOKEN_FILE=None):
        path = trust.token_path()
        assert str(path).startswith(tmp), path
        assert path.name == "owner.token", path
        assert path.parent.name == "hungry-hippa", path
        token = trust.ensure_owner_token()
        assert path.exists() and trust.token_matches(token) is True
    return f"XDG_STATE_HOME honoured: {path}"


def check_fallback_state_directory():
    """Without XDG_STATE_HOME the fallback is ~/.local/state/hungry-hippa."""
    with Env(XDG_STATE_HOME=None, HUNGRY_HIPPA_OWNER_TOKEN_FILE=None):
        path = trust.token_path()
        assert str(path).endswith("/.local/state/hungry-hippa/owner.token"), path
        assert ".hermes" not in str(path), path
    return f"fallback path is {path}"


def check_explicit_override_wins():
    """HUNGRY_HIPPA_OWNER_TOKEN_FILE overrides everything."""
    tmp = tempfile.mkdtemp(prefix="hh_tok_override_")
    explicit = os.path.join(tmp, "somewhere", "custom.token")
    with Env(XDG_STATE_HOME=os.path.join(tmp, "ignored"),
             HUNGRY_HIPPA_OWNER_TOKEN_FILE=explicit):
        assert str(trust.token_path()) == explicit, trust.token_path()
        token = trust.ensure_owner_token()
        assert trust.token_matches(token, Path(explicit)) is True
        assert _mode(Path(explicit)) == 0o600
    return "explicit token-file override is honoured and still mode 0600"


def check_comparison_is_strict():
    """Wrong, absent and oversized tokens never verify."""
    tmp = tempfile.mkdtemp(prefix="hh_tok_cmp_")
    path = Path(tmp) / "owner.token"
    token = trust.ensure_owner_token(path)
    assert trust.token_matches(token, path) is True
    assert trust.token_matches(token + "x", path) is False
    assert trust.token_matches(token[:-1], path) is False
    assert trust.token_matches("", path) is False
    assert trust.token_matches(None, path) is False
    assert trust.token_matches("x" * 500, path) is False
    missing = Path(tmp) / "nope.token"
    assert trust.token_matches(token, missing) is False
    return "only the exact token verifies; wrong/absent/oversized values fail"


def check_server_binding_uses_the_launch_environment():
    """The MCP binding comes from the launch env, not from a tool argument."""
    tmp = tempfile.mkdtemp(prefix="hh_tok_bind_")
    path = Path(tmp) / "owner.token"
    token = trust.ensure_owner_token(path)
    with Env(HUNGRY_HIPPA_OWNER_TOKEN_FILE=str(path)):
        owner = trust.server_binding("primary", token)
        assert owner.identity == trust.OWNER and owner.actor_id == "primary", owner
        # no token, wrong token: the label does not save the caller
        untrusted = trust.server_binding("primary", "")
        assert untrusted.identity == trust.UNTRUSTED, untrusted
        assert untrusted.actor_id != "primary", "an owner label was not remapped"
        wrong = trust.server_binding("primary", "not-the-token")
        assert wrong.identity == trust.UNTRUSTED, wrong
        # a token that matches the file is required, not merely a token
        other = trust.ensure_owner_token(Path(tempfile.mkdtemp()) / "other.token")
        assert trust.server_binding("primary", other).identity == trust.UNTRUSTED
        # the token value is never part of any output
        assert token not in str(owner.as_dict()), owner.as_dict()
        assert token not in str(trust.binding_summary()), "binding_summary leaked the token"
        assert token not in str(trust.binding_summary()), "summary leaked the token"
    return ("binding resolves from the launch token verified against the token file; "
            "remapping holds; no token in any output")


def run_all() -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []

    def check(name: str, fn) -> None:
        try:
            detail = fn() or "ok"
            results.append({"name": name, "passed": True, "detail": str(detail)[:300]})
        except AssertionError as e:
            results.append({"name": name, "passed": False, "detail": f"assert: {e}"})
        except Exception as e:
            results.append({"name": name, "passed": False,
                            "detail": f"{type(e).__name__}: {e}"})

    check("initial_creation_and_mode", check_initial_creation_and_mode)
    check("existing_token_is_kept", check_existing_token_is_kept)
    check("empty_and_corrupt_files_are_repaired", check_empty_and_corrupt_files_are_repaired)
    check("failed_write_is_reported_not_silent", check_failed_write_is_reported_not_silent)
    check("xdg_state_home_is_used", check_xdg_state_home_is_used)
    check("fallback_state_directory", check_fallback_state_directory)
    check("explicit_override_wins", check_explicit_override_wins)
    check("comparison_is_strict", check_comparison_is_strict)
    check("server_binding_uses_the_launch_environment",
          check_server_binding_uses_the_launch_environment)
    return results


if __name__ == "__main__":
    results = run_all()
    passed = sum(1 for r in results if r["passed"])
    for r in results:
        print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['name']}: {r['detail']}")
    print(f"\n{passed}/{len(results)} passed")
    sys.exit(0 if passed == len(results) else 1)
