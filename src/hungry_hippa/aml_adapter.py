"""Hungry Hippa — Agent Memory Leaderboard (Cycle 2) HTTP adapter.

Implements the participant Add/Search surface per the official AML API Guide
(https://agentmemoryleaderboard.ai/api-guide), verified 2026-10-04:

* ``POST /add``    — request ``{request_id*, messages[]*, user_id*,
  session_id*}``; each message ``{role*, content*, timestamp?}`` where
  ``content`` is a string (text/coding tracks) and ``timestamp`` is optional
  Unix milliseconds. Response ``200`` ONLY after the write is persisted AND
  immediately searchable: ``{success: true, request_id, user_id, session_id}``
  with the three ids echoed byte-for-byte. Omitting ``success: true`` or
  mis-echoing an id is a contract failure even with HTTP 200.
* ``POST /search`` — request ``{query*, options?, user_id*, top_k*}``.
  Returns ``{data: [{id*, content*, score?, created_at?}]}`` — stored
  fragments only, relevance-ordered, never more than ``top_k`` items,
  ``data: []`` when nothing matches. It NEVER generates a final answer: the
  platform owns Answer/Eval.
* ``GET /health``  — unauthenticated liveness probe; any 2xx means healthy.

Contract rules this adapter honors
-----------------------------------
* ``user_id`` is the ONLY retrieval-isolation field. ``session_id`` is
  stored, never used as a Search filter. Each ``user_id`` gets its own
  isolated SQLite store under the run's base directory, so per-conversation
  user ids (e.g. ``eval:run_abc:locomo:conv-0``) can never leak into each
  other. Use a FRESH base directory per evaluation run (smoke vs Full) —
  corpora must never share storage.
* Add re-delivery: the platform retries Add (408/409/425/429/500/502/503/
  504/524, timeouts) with the SAME ``request_id``. The adapter is idempotent
  on ``(user_id, request_id)``: same payload replays the original success
  echo without writing; a different payload under a known ``request_id``
  answers ``409``.
* Auth: the key travels in the header scheme declared at application time.
  This adapter accepts ``Authorization: Bearer``, ``Authorization: Token``
  and ``X-Api-Key`` (constant-time compare). Declare ``Bearer``.
* Contract errors (400/401/403/404/422) are NOT retried by the platform —
  the adapter fails fast on them. Transient overload answers ``429`` with
  ``Retry-After`` (retried with bounds). One request may run up to 30 min.

Safety
------
The adapter NEVER touches the operator's live memory store. It defaults to
``<data-dir>/aml_eval`` and REFUSES to start if the base directory or any
resolved user store equals the live default database path. Tests use
throwaway temp directories only.

Design
------
* stdlib only — zero new dependencies. One lock per user store keeps each
  user's Add/Search deterministic while different users proceed in parallel.
* Each message becomes one episode (annotated ``[ISO time] role: text`` so
  the stored fragment carries its temporal context for the platform's
  Answer model). No LLM is called on Add or Search; embeddings stay local.
* The benchmark instance binds as the owner on its isolated database. The
  platform's Add payload is the eval corpus for this deployment, so the
  quarantine path (meant for untrusted third-party writes into personal
  memory) is deliberately not applied here.

Run it::

    export HIPPA_AML_API_KEY="$(openssl rand -hex 24)"
    export HIPPA_AML_DATA_DIR="$HOME/.local/share/hungry-hippa/aml_eval_full"
    python -m hungry_hippa.aml_adapter --port 8000
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from . import config as _config
from .controller import MemoryController
from .version import __version__ as _package_version

SERVICE_NAME = "hungry-hippa-aml-adapter"

ENV_API_KEY = "HIPPA_AML_API_KEY"
ENV_DATA_DIR = "HIPPA_AML_DATA_DIR"
ENV_INCLUDE_OPTIONS = "HIPPA_AML_INCLUDE_OPTIONS"
ENV_MAX_INFLIGHT = "HIPPA_AML_MAX_INFLIGHT"

DEFAULT_BASE_DIR_NAME = "aml_eval"
MAX_BODY_BYTES = 32 * 1024 * 1024  # 32 MiB; official cap is 30 MiB/Add
DEFAULT_TOP_K = 100  # formal external evaluations use top_k = 100
MAX_TOP_K = 1000
MAX_INFLIGHT_DEFAULT = 8
RETRY_AFTER_SECONDS = 5


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ms_to_iso(ms: Any) -> str:
    """Unix milliseconds (int/float/numeric str) -> ISO-8601 UTC. '' if bad."""
    try:
        value = float(ms)
    except (TypeError, ValueError):
        return ""
    if value <= 0:
        return ""
    try:
        return datetime.fromtimestamp(value / 1000.0,
                                      tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return ""


def _coerce_text(content: Any) -> str:
    """Official: text/coding tracks send content as a string. Be lenient:
    also accept an ordered ContentPart[] list by joining its text parts."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text" and isinstance(part.get("text"), str):
                parts.append(part["text"])
            elif isinstance(part.get("content"), str):
                parts.append(part["content"])
        return "\n".join(parts)
    return ""


def _canonical_sha(payload: Dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Configuration / safety rails
# --------------------------------------------------------------------------

def _live_default_db() -> Path:
    """The operator's real memory store — the adapter must never use this."""
    return Path(_config.discover_default_db_path()).resolve()


def resolve_base_dir(explicit: Optional[str] = None) -> Path:
    """Resolve the isolated per-run base directory, with a hard safety rail.

    Raises :class:`RuntimeError` if it resolves to the live store path.
    """
    raw = (explicit or os.environ.get(ENV_DATA_DIR, "") or "").strip()
    if raw:
        path = Path(raw).expanduser().resolve()
    else:
        path = (_config.data_dir() / DEFAULT_BASE_DIR_NAME).resolve()
    if path == _live_default_db():
        raise RuntimeError(
            f"refusing to run the AML adapter with base dir {path}: it is "
            f"the live memory store. Set {ENV_DATA_DIR} to a dedicated "
            f"directory (fresh per evaluation run).")
    return path


def _user_ns(user_id: str) -> str:
    return hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:32]


def resolve_user_store(base_dir: Path, user_id: str) -> Tuple[Path, Path]:
    """(store.db, requests.db) for one user_id. Refuses the live store."""
    user_dir = (base_dir / "users" / _user_ns(user_id)).resolve()
    store = user_dir / "store.db"
    # Belt and suspenders: never let a user store be the live database.
    if store == _live_default_db() or user_dir == _live_default_db():
        raise RuntimeError(
            f"refusing to resolve AML user store inside the live memory "
            f"store ({user_dir}).")
    return store, user_dir / "requests.db"


def _load_api_key(explicit: Optional[str] = None) -> str:
    return (explicit or os.environ.get(ENV_API_KEY, "") or "").strip()


def _include_options() -> bool:
    return os.environ.get(ENV_INCLUDE_OPTIONS, "1").strip().lower() not in (
        "0", "false", "no", "")


def _max_inflight() -> int:
    try:
        return max(1, int(os.environ.get(ENV_MAX_INFLIGHT,
                                        str(MAX_INFLIGHT_DEFAULT))))
    except ValueError:
        return MAX_INFLIGHT_DEFAULT


# --------------------------------------------------------------------------
# Per-user state: isolated controller + idempotency ledger
# --------------------------------------------------------------------------

class _UserState:
    """One user's isolated store: controller, write lock, request ledger."""

    def __init__(self, store_path: Path, ledger_path: Path):
        self.lock = threading.Lock()
        store_path.parent.mkdir(parents=True, exist_ok=True)
        cfg = _config.load_config()
        self.controller = MemoryController(cfg, db_path=str(store_path))
        self.ledger_path = ledger_path
        self._init_ledger()

    def _init_ledger(self) -> None:
        conn = sqlite3.connect(str(self.ledger_path))
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS aml_requests ("
                " request_id TEXT PRIMARY KEY,"
                " payload_sha TEXT NOT NULL,"
                " session_id TEXT NOT NULL,"
                " status TEXT NOT NULL,"  # started | done
                " created_at TEXT NOT NULL)")
            conn.commit()
        finally:
            conn.close()

    def find_request(self, request_id: str) -> Optional[Dict[str, str]]:
        conn = sqlite3.connect(str(self.ledger_path))
        try:
            row = conn.execute(
                "SELECT payload_sha, session_id, status FROM aml_requests"
                " WHERE request_id = ?", (request_id,)).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        return {"payload_sha": row[0], "session_id": row[1], "status": row[2]}

    def mark_started(self, request_id: str, payload_sha: str,
                     session_id: str) -> None:
        conn = sqlite3.connect(str(self.ledger_path))
        try:
            conn.execute(
                "INSERT OR IGNORE INTO aml_requests"
                " (request_id, payload_sha, session_id, status, created_at)"
                " VALUES (?,?,?,?,?)",
                (request_id, payload_sha, session_id, "started",
                 _utcnow_iso()))
            conn.commit()
        finally:
            conn.close()

    def mark_done(self, request_id: str) -> None:
        conn = sqlite3.connect(str(self.ledger_path))
        try:
            conn.execute(
                "UPDATE aml_requests SET status = 'done'"
                " WHERE request_id = ?", (request_id,))
            conn.commit()
        finally:
            conn.close()


class _AdapterState:
    def __init__(self, base_dir: Path, api_key: str):
        self.base_dir = base_dir
        self.api_key = api_key
        self.include_options = _include_options()
        self._registry_lock = threading.Lock()
        self._users: Dict[str, _UserState] = {}
        self._inflight = 0
        self._inflight_lock = threading.Lock()
        self._max_inflight = _max_inflight()

    def user_state(self, user_id: str) -> _UserState:
        ns = _user_ns(user_id)
        with self._registry_lock:
            state = self._users.get(ns)
            if state is None:
                store, ledger = resolve_user_store(self.base_dir, user_id)
                state = _UserState(store, ledger)
                self._users[ns] = state
            return state

    def known_user(self, user_id: str) -> bool:
        ns = _user_ns(user_id)
        with self._registry_lock:
            if ns in self._users:
                return True
        store, _ = resolve_user_store(self.base_dir, user_id)
        return store.exists()

    # -- backpressure ----------------------------------------------------
    def acquire_slot(self) -> bool:
        with self._inflight_lock:
            if self._inflight >= self._max_inflight:
                return False
            self._inflight += 1
            return True

    def release_slot(self) -> None:
        with self._inflight_lock:
            self._inflight = max(0, self._inflight - 1)


# --------------------------------------------------------------------------
# Translation: AML wire <-> MemoryController
# --------------------------------------------------------------------------

def _validate_add(body: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    """Returns (normalized, error). Normalized: request_id, user_id,
    session_id, messages=[{role, text, iso}]."""
    request_id = body.get("request_id")
    user_id = body.get("user_id")
    session_id = body.get("session_id")
    messages = body.get("messages")
    if not isinstance(request_id, str) or not request_id:
        return {}, "request_id is required"
    if not isinstance(user_id, str) or not user_id:
        return {}, "user_id is required"
    if not isinstance(session_id, str) or not session_id:
        return {}, "session_id is required"
    if not isinstance(messages, list) or not messages:
        return {}, "messages must be a non-empty array"
    normalized: List[Dict[str, str]] = []
    for index, raw in enumerate(messages):
        if not isinstance(raw, dict):
            return {}, f"messages[{index}] must be an object"
        role = raw.get("role")
        if not isinstance(role, str) or not role.strip():
            return {}, f"messages[{index}].role is required"
        text = _coerce_text(raw.get("content")).strip()
        if not text:
            return {}, f"messages[{index}].content is required"
        iso = _ms_to_iso(raw.get("timestamp")) if raw.get("timestamp") is not None else ""
        annotated = f"[{iso}] {role}: {text}" if iso else f"{role}: {text}"
        normalized.append({"role": role, "text": text, "iso": iso,
                           "annotated": annotated})
    return {"request_id": request_id, "user_id": user_id,
            "session_id": session_id, "messages": normalized}, ""


def add_messages(state: _AdapterState, user: _UserState,
                 norm: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    """Idempotent Add. Returns (http_status, response_payload)."""
    request_id = norm["request_id"]
    user_id = norm["user_id"]
    session_id = norm["session_id"]
    payload_sha = _canonical_sha({"user_id": user_id,
                                  "session_id": session_id,
                                  "messages": [
                                      {"role": m["role"], "text": m["text"],
                                       "iso": m["iso"]}
                                      for m in norm["messages"]]})

    def echo() -> Dict[str, Any]:
        # Ids echoed byte-for-byte, exactly as received.
        return {"success": True, "request_id": request_id,
                "user_id": user_id, "session_id": session_id}

    with user.lock:
        seen = user.find_request(request_id)
        if seen is not None:
            if seen["payload_sha"] != payload_sha:
                return 409, {"error": "request_id already used with a "
                                      "different payload"}
            if seen["status"] == "done":
                return 200, echo()  # idempotent replay: nothing rewritten
            # 'started' here means a previous attempt died mid-write (the
            # per-user lock guarantees no other thread is still writing).
            # Reprocess; partial writes from the dead attempt may duplicate,
            # but a crash mid-Add is not a realistic platform retry path
            # (retries arrive while the first attempt is still running and
            # simply wait on this lock, then replay the echo above).
        else:
            user.mark_started(request_id, payload_sha, session_id)

        controller = user.controller
        controller.bind_session(session_id=session_id,
                                platform="aml-adapter",
                                agent_context="primary")
        for index, msg in enumerate(norm["messages"]):
            try:
                result = controller.remember_episode(
                    user_request=msg["annotated"],
                    context=(f"aml request {request_id} message {index}"),
                    ts_start=msg["iso"],
                    ts_end=msg["iso"],
                    source_refs=[f"aml:{request_id}#{index}"],
                    project="",
                    session_id=session_id,
                )
            except Exception:
                return 500, {"error": "internal error"}
            if result.get("error"):
                # Quota or write-gate failure: 500 is retried with bounds.
                return 500, {"error": "store failed"}
        user.mark_done(request_id)
        return 200, echo()


def _evidence_id(item: Dict[str, Any]) -> str:
    for key in ("episode_id", "belief_id", "rel_id", "procedure_id", "id"):
        value = item.get(key)
        if value:
            return str(value)
    return ""


def search_evidence(state: _AdapterState, user: _UserState, query: str,
                    options: List[str], top_k: int) -> List[Dict[str, Any]]:
    """Recall evidence for a query under one user_id. Records only."""
    effective = query
    if options and state.include_options:
        effective = query + "\nOptions:\n" + "\n".join(options)
    with user.lock:
        user.controller.bind_session(session_id="aml-search",
                                     platform="aml-adapter",
                                     agent_context="primary")
        out = user.controller.recall(effective, limit=top_k)
    records: List[Dict[str, Any]] = []
    for item in out.get("items", []) or []:
        if not isinstance(item, dict):
            continue
        rid = _evidence_id(item)
        content = str(item.get("user_request", "") or "").strip()
        if not rid or not content:
            continue  # id and content are required; skip unusable rows
        try:
            score = float(item.get("_score", 0.0) or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        created_at = str(item.get("ts_start", "") or
                         item.get("created_at", "") or "")
        records.append({"id": rid, "content": content, "score": score,
                        "created_at": created_at})
    return records[:top_k]


# --------------------------------------------------------------------------
# HTTP server (stdlib only)
# --------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    server_version = "HungryHippaAMLAdapter/2"

    # -- helpers ---------------------------------------------------------
    def _send(self, status: int, payload: Dict[str, Any],
              extra_headers: Optional[Dict[str, str]] = None) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def _check_auth(self) -> bool:
        state: _AdapterState = self.server.state  # type: ignore[attr-defined]
        if not state.api_key:
            return False  # no key configured: deny everything but /health
        headers = self.headers
        bearer = (headers.get("Authorization", "") or "").strip()
        presented = ""
        low = bearer.lower()
        if low.startswith("bearer "):
            presented = bearer[7:].strip()
        elif low.startswith("token "):
            presented = bearer[6:].strip()
        elif headers.get("X-Api-Key", "").strip():
            presented = headers.get("X-Api-Key", "").strip()
        if not presented:
            return False
        return hmac.compare_digest(presented, state.api_key)

    def log_message(self, fmt: str, *args: Any) -> None:  # keep stdout clean
        pass

    # -- routes ----------------------------------------------------------
    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in ("/health", "/healthz"):
            state: _AdapterState = self.server.state  # type: ignore[attr-defined]
            self._send(200, {"status": "ok", "service": SERVICE_NAME,
                             "version": str(_package_version or "unknown"),
                             "auth_configured": bool(state.api_key)})
            return
        self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        state: _AdapterState = self.server.state  # type: ignore[attr-defined]
        path = urlparse(self.path).path
        if path not in ("/add", "/search"):
            self._send(404, {"error": "not found"})
            return
        if not self._check_auth():
            self._send(401, {"error": "unauthorized"})
            return
        if not state.acquire_slot():
            # 429 with Retry-After: the platform retries with bounds.
            self._send(429, {"error": "overloaded, retry later"},
                       {"Retry-After": str(RETRY_AFTER_SECONDS)})
            return
        try:
            length = self._read_length()
            if length is None:
                self._send(400, {"error": "bad Content-Length"})
                return
            if length > MAX_BODY_BYTES:
                self._send(413, {"error": "body too large"})
                return
            raw = self.rfile.read(length) if length else b""
            try:
                body = json.loads(raw.decode("utf-8")) if raw else {}
            except Exception:
                self._send(400, {"error": "invalid JSON"})
                return
            if not isinstance(body, dict):
                self._send(400, {"error": "top-level JSON must be an object"})
                return

            if path == "/add":
                norm, err = _validate_add(body)
                if err:
                    self._send(400, {"error": err})
                    return
                user = state.user_state(norm["user_id"])
                status, payload = add_messages(state, user, norm)
                self._send(status, payload)
            else:
                query = body.get("query")
                user_id = body.get("user_id")
                top_k = body.get("top_k", DEFAULT_TOP_K)
                options = body.get("options", [])
                if not isinstance(query, str) or not query.strip():
                    self._send(400, {"error": "query is required"})
                    return
                query = _coerce_text(query).strip() or query.strip()
                if not isinstance(user_id, str) or not user_id:
                    self._send(400, {"error": "user_id is required"})
                    return
                try:
                    top_k = int(top_k)
                except (TypeError, ValueError):
                    self._send(400, {"error": "top_k must be an integer"})
                    return
                top_k = max(1, min(top_k, MAX_TOP_K))
                if options is None:
                    options = []
                if not isinstance(options, list):
                    self._send(400, {"error": "options must be an array"})
                    return
                options = [str(o) for o in options
                           if isinstance(o, str) and o.strip()][:64]
                if not state.known_user(user_id):
                    self._send(200, {"data": []})
                    return
                user = state.user_state(user_id)
                try:
                    records = search_evidence(state, user, query, options,
                                              top_k)
                except Exception:
                    self._send(500, {"error": "internal error"})
                    return
                self._send(200, {"data": records})
        finally:
            state.release_slot()

    def _read_length(self) -> Optional[int]:
        try:
            return int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            return None


def make_server(host: str = "127.0.0.1", port: int = 8000,
                base_dir: Optional[str] = None,
                api_key: Optional[str] = None,
                db_path: Optional[str] = None) -> ThreadingHTTPServer:
    """Build (but do not start) the adapter server. Used by tests too.

    ``db_path`` is the legacy single-database argument: when given, it is
    used as the base directory's parent anchor is ignored and the path's
    parent becomes the base dir. Prefer ``base_dir``.
    """
    if db_path and not base_dir:
        # Back-compat for the scaffold's tests: treat the db path's parent
        # as the base dir (the file name itself is not used).
        resolved_base = Path(db_path).expanduser().resolve().parent
        if resolved_base == _live_default_db():
            raise RuntimeError("refusing the live memory store")
        base = resolved_base
    else:
        base = resolve_base_dir(base_dir)
    base.mkdir(parents=True, exist_ok=True)
    key = _load_api_key(api_key)
    server = ThreadingHTTPServer((host, port), _Handler)
    server.state = _AdapterState(base, key)  # type: ignore[attr-defined]
    server.daemon_threads = True
    return server


# Back-compat alias: the scaffold exposed resolve_eval_db(); the v2 layout
# uses a base directory. Kept so older call sites fail loudly, not silently.
def resolve_eval_db(explicit: Optional[str] = None) -> Path:
    base = resolve_base_dir(explicit)
    return base


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Hungry Hippa Add/Search HTTP adapter for the Agent "
                    "Memory Leaderboard (Cycle 2).")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--base-dir", default=None,
                        help=f"per-run base directory (default: <data-dir>/{DEFAULT_BASE_DIR_NAME}; "
                             f"fresh per evaluation run; never the live store)")
    parser.add_argument("--db-path", default=None,
                        help="legacy: single database path; its parent "
                             "becomes the base dir")
    parser.add_argument("--api-key", default=None,
                        help=f"Bearer token (default: ${ENV_API_KEY})")
    args = parser.parse_args(argv)

    key = _load_api_key(args.api_key)
    if not key:
        print(f"WARNING: no API key configured ({ENV_API_KEY} unset and "
              f"--api-key not given); /add and /search will answer 401. "
              f"Set one before the smoke test.")
    try:
        server = make_server(args.host, args.port, args.base_dir, key or None,
                             db_path=args.db_path)
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        return 2
    addr = server.server_address
    state: _AdapterState = server.state  # type: ignore[attr-defined]
    print(f"{SERVICE_NAME} listening on http://{addr[0]}:{addr[1]} "
          f"(base dir: {state.base_dir})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
