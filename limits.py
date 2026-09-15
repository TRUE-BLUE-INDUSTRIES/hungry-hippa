"""Request limits and log redaction for Hungry Hippa (§ security phase).

Small, standard-library guards applied at the two boundaries (the Hermes
``cortex`` tool and the MCP server):

  * argument length caps — a query, a claim or an episode body cannot be
    arbitrarily large;
  * result caps — retrieved context text handed back to a caller is bounded;
  * a per-process call budget — a runaway or hostile client loop cannot hammer
    the runtime forever;
  * redaction of likely credentials before anything is written to an **audit**
    log (``mutation_log``, ``retrieval_log``).

What this module is not: a security guarantee. These are resource and abuse
guards. They do not make the system "unhackable", they do not encrypt anything,
and they are not capability-based access control. See ``docs/SECURITY.md``.

Redaction is deliberately narrow: it only touches the audit copies. Stored
memory content and immutable ``evidence`` rows keep exactly what they were
given, because silently rewriting a memory would corrupt the record it exists
to preserve.
"""

from __future__ import annotations

import os
import re
import shutil
import time
import threading
from typing import Any, Dict, List, Optional, Tuple

# --------------------------------------------------------------- size caps

MAX_QUERY_CHARS = 8000
MAX_CONTENT_CHARS = 32000
MAX_RESULT_CHARS = 20000
MAX_RESULT_JSON_CHARS = 40000
DEFAULT_MAX_CALLS = 1000

# Per-argument caps for the `cortex` tool and the MCP tools. Anything not
# listed falls back to MAX_CONTENT_CHARS.
FIELD_LIMITS: Dict[str, int] = {
    "query": MAX_QUERY_CHARS,
    "user_request": MAX_QUERY_CHARS,
    "claim": MAX_CONTENT_CHARS,
    "new_claim": MAX_CONTENT_CHARS,
    "counter_claim": MAX_CONTENT_CHARS,
    "content": MAX_CONTENT_CHARS,
    "context": MAX_CONTENT_CHARS,
    "actions_taken": MAX_CONTENT_CHARS,
    "decisions": MAX_CONTENT_CHARS,
    "result": MAX_CONTENT_CHARS,
    "description": MAX_CONTENT_CHARS,
    "reason": 512,
    "source_ref": 512,
    "project": 256,
    "name": 256,
    "src": 256,
    "dst": 256,
    "rel": 64,
    "kind": 64,
    "mode": 32,
    "target_kind": 64,
    "target_id": 64,
    "belief_id": 64,
    "episode_id": 64,
    "procedure_id": 64,
    "session_id": 128,
    "actor_id": 128,
    "path": 4096,          # local CLI export only; never exposed over MCP
}

MAX_ARRAY_ITEMS = 256


def field_limit(field: str) -> int:
    return int(FIELD_LIMITS.get(field, MAX_CONTENT_CHARS))


def check_args(args: Dict[str, Any], *, skip: Tuple[str, ...] = ("path",)) -> List[str]:
    """Return a list of human-readable violations for one tool/tool-call dict."""
    problems: List[str] = []
    for key, value in (args or {}).items():
        if key in skip:
            continue
        if isinstance(value, str):
            limit = field_limit(key)
            if len(value) > limit:
                problems.append(f"'{key}' exceeds {limit} characters")
        elif isinstance(value, (list, tuple)):
            if len(value) > MAX_ARRAY_ITEMS:
                problems.append(f"'{key}' exceeds {MAX_ARRAY_ITEMS} items")
            for item in value:
                if isinstance(item, str) and len(item) > field_limit(key):
                    problems.append(f"'{key}' items exceed {field_limit(key)} characters")
                    break
    return problems


def truncate(text: Any, limit: int, marker: str = "…[truncated]") -> str:
    """Hard-cap a string, leaving a visible marker rather than silent loss."""
    s = "" if text is None else str(text)
    if limit <= 0 or len(s) <= limit:
        return s
    keep = max(0, limit - len(marker))
    return s[:keep] + marker


# --------------------------------------------------------------- redaction

# Patterns for credentials that should never reach an audit log. Intentionally
# conservative: each one needs a recognisable provider shape or an explicit
# "key = value" assignment, so ordinary prose is not mangled.
_SECRET_PATTERNS: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    ("private_key", re.compile(
        r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}\b")),
    ("github_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("github_token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b")),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b")),
    ("bearer_token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9\-._~+/]{20,}=*")),
    ("assigned_secret", re.compile(
        r"(?i)\b(?:api[_-]?key|apikey|secret[_-]?key|secret|password|passwd|token|"
        r"access[_-]?key)\b\s*[:=]\s*['\"]?([A-Za-z0-9\-._~+/]{12,})")),
)


def redact(text: Any) -> str:
    """Replace likely credentials in *text* with ``[REDACTED:<kind>]`` markers."""
    if text in (None, ""):
        return "" if text is None else str(text)
    out = str(text)
    for name, pattern in _SECRET_PATTERNS:
        out = pattern.sub(f"[REDACTED:{name}]", out)
    return out


def looks_like_secret(text: Any) -> bool:
    """True when redaction would change *text* (used by tests and diagnostics)."""
    if not text:
        return False
    return redact(text) != str(text)


# ------------------------------------------------------------ call budget

class CallBudget:
    """A per-process call counter.

    A blunt resource guard: it stops a runaway client loop, it does not
    identify or authorise callers. Thread-safe because the MCP server and the
    Hermes tool can both hit it from different threads in one process.
    """

    def __init__(self, max_calls: int = DEFAULT_MAX_CALLS):
        self._lock = threading.Lock()
        self.max_calls = max(1, int(max_calls))
        self._used = 0

    def reset(self, max_calls: Optional[int] = None) -> None:
        with self._lock:
            if max_calls is not None:
                self.max_calls = max(1, int(max_calls))
            self._used = 0

    def check(self) -> Tuple[bool, str]:
        with self._lock:
            if self._used >= self.max_calls:
                return False, (f"call budget exhausted ({self.max_calls} calls "
                               f"in this process)")
            return True, ""

    def record(self) -> int:
        with self._lock:
            self._used += 1
            return self._used

    @property
    def used(self) -> int:
        with self._lock:
            return self._used

    def remaining(self) -> int:
        with self._lock:
            return max(0, self.max_calls - self._used)

    def summary(self) -> Dict[str, Any]:
        with self._lock:
            return {"used": self._used, "max_calls": self.max_calls,
                    "remaining": max(0, self.max_calls - self._used)}


def max_calls_from_env(default: int = DEFAULT_MAX_CALLS) -> int:
    """``HUNGRY_HIPPA_MAX_MCP_CALLS`` overrides the MCP call budget."""
    raw = os.environ.get("HUNGRY_HIPPA_MAX_MCP_CALLS", "")
    try:
        value = int(str(raw).strip())
    except Exception:
        return default
    return value if value > 0 else default


# ---------------------------------------------------------------- resources

# These are local-first guards, not a security boundary: they make runaway or
# abusive *volume* visible and bounded, and they survive process restarts because
# the accounting lives in the database rather than in the process.
DEFAULT_MAX_WRITES_PER_HOUR = 20000     # generous: normal use is far below this
DEFAULT_MAX_DB_BYTES = 512 * 1024 * 1024  # 512 MiB: a warning, not a hard stop


def max_writes_per_hour() -> int:
    raw = os.environ.get("HUNGRY_HIPPA_MAX_WRITES_PER_HOUR", "")
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_WRITES_PER_HOUR
    return value if value > 0 else DEFAULT_MAX_WRITES_PER_HOUR


def max_db_bytes() -> int:
    raw = os.environ.get("HUNGRY_HIPPA_MAX_DB_BYTES", "")
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_DB_BYTES
    return value if value > 0 else DEFAULT_MAX_DB_BYTES


def db_size_report(path: str) -> Dict[str, Any]:
    """Database size and whether it has passed the warning threshold."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return {"path": path, "bytes": 0, "limit_bytes": max_db_bytes(),
                "over_limit": False, "note": "database not found"}
    limit = max_db_bytes()
    return {
        "path": path,
        "bytes": size,
        "limit_bytes": limit,
        "over_limit": size > limit,
        "warning": (f"database is {size / 1048576:.0f} MiB, over the "
                    f"{limit / 1048576:.0f} MiB warning threshold; consider "
                    f"'hermes living-cortex consolidate' and a fresh export"
                    if size > limit else ""),
        "note": "a warning, not a quota: nothing is deleted and nothing is refused",
    }


def check_write_quota(db, actor_id: str, *, limit: Optional[int] = None,
                      now: Optional[float] = None) -> Tuple[bool, Dict[str, Any]]:
    """Cross-process write accounting, stored in the database.

    A per-process counter resets when the client starts a new process, which is
    trivial for a caller to do. The window is therefore kept in the database, so
    the count survives restarts, and it is keyed by actor as well as window.
    """
    limit = limit if limit is not None else max_writes_per_hour()
    window = int((now if now is not None else time.time()) // 3600)

    def _check(conn) -> Dict[str, Any]:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS write_quota ("
            "window_start INTEGER NOT NULL, actor TEXT NOT NULL, count INTEGER NOT NULL,"
            " PRIMARY KEY (window_start, actor))")
        row = conn.execute(
            "SELECT count FROM write_quota WHERE window_start = ? AND actor = ?",
            (window, actor_id)).fetchone()
        used = int(row[0]) if row else 0
        allowed = used < limit
        if allowed:
            conn.execute(
                "INSERT INTO write_quota(window_start, actor, count) VALUES (?,?,1)"
                " ON CONFLICT(window_start, actor) DO UPDATE SET count = count + 1",
                (window, actor_id))
        return {"allowed": allowed, "used": used, "limit": limit,
                "window_start": window, "actor_id": actor_id}

    try:
        report = db._run(_check, write=True) or {"allowed": True, "used": 0,
                                                 "limit": limit}
    except Exception as e:  # never let accounting break a write path
        logger.warning("write quota check failed: %s", e)
        return True, {"allowed": True, "used": -1, "limit": limit,
                      "error": str(e)[:120]}
    if not report["allowed"]:
        return False, report
    return True, report


def backup_space_multiplier() -> float:
    raw = os.environ.get("HUNGRY_HIPPA_BACKUP_SPACE_MULTIPLIER", "")
    try:
        value = float(raw)
    except ValueError:
        return 2.0
    return value if value > 0 else 2.0


def backup_space_ok(src: str, *, need_multiplier: Optional[float] = None) -> Tuple[bool, str]:
    """Is there room for a full copy of *src* next to it?

    A migration backup in a full filesystem is how a routine upgrade turns into
    data loss, so the caller refuses rather than half-writing a copy.
    """
    try:
        size = os.path.getsize(src)
        probe_dir = os.path.dirname(os.path.abspath(src)) or "."
        free = shutil.disk_usage(probe_dir).free
    except OSError as e:
        return True, f"could not measure free space ({e}); proceeding"
    need = int(size * (need_multiplier if need_multiplier is not None
                       else backup_space_multiplier()))
    if free < need:
        return False, (f"need about {need / 1048576:.0f} MiB free for the backup, "
                       f"{free / 1048576:.0f} MiB available in {probe_dir}")
    return True, f"{free / 1048576:.0f} MiB free, need {need / 1048576:.0f} MiB"
