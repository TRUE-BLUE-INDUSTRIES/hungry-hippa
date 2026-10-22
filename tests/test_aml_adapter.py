"""AML adapter contract checks: official Add/Search wire shapes on throwaway
databases.

Verifies the adapter against the AML API Guide contract (request/response
schemas, id echoes, user_id isolation, idempotent Add, evidence-only Search).

Nothing here touches a production database. The adapter itself refuses to
start with a base dir equal to the live default store; these checks use temp
directories only and invented payload data.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_DIR = Path(__file__).resolve().parent.parent


sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests/ (shared helpers)

from _package import import_package  # noqa: E402

import_package()

from hungry_hippa import aml_adapter as aml  # noqa: E402
from hungry_hippa import config as _config  # noqa: E402

API_KEY = "test-key-only"


def _serve(api_key: str = API_KEY, env: Optional[Dict[str, str]] = None):
    base_dir = tempfile.mkdtemp(prefix="hh_aml_")
    old = {}
    for key, value in (env or {}).items():
        old[key] = os.environ.get(key)
        os.environ[key] = value
    try:
        server = aml.make_server("127.0.0.1", 0, base_dir=base_dir,
                                 api_key=api_key)
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    url = f"http://{host}:{port}"
    for _ in range(100):
        try:
            urllib.request.urlopen(url + "/health", timeout=2).read()
            break
        except Exception:
            time.sleep(0.05)
    return server, url


def _request(base: str, method: str, path: str, body: Any = None,
             auth: str = f"Bearer {API_KEY}",
             extra_headers: Optional[Dict[str, str]] = None
             ) -> Tuple[int, Dict[str, Any]]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    if auth == "X-Api-Key":
        req.add_header("X-Api-Key", API_KEY)
    elif auth:
        req.add_header("Authorization", auth)
    for key, value in (extra_headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode())
        except Exception:
            payload = {}
        return exc.code, payload


def _add_payload(request_id="req-1", user_id="user-1", session_id="sess-1",
                 texts: Optional[List[str]] = None):
    texts = texts if texts is not None else [
        "The lighthouse keeper drinks black coffee at dawn.",
        "Brass telescopes are polished every second Tuesday.",
    ]
    return {
        "request_id": request_id,
        "user_id": user_id,
        "session_id": session_id,
        "messages": [
            {"role": "user" if i % 2 == 0 else "assistant",
             "content": text,
             "timestamp": 1704067200000 + i * 1000}
            for i, text in enumerate(texts)
        ],
    }


# ---------------------------------------------------------------- checks

def check_health_open_without_auth():
    server, base = _serve()
    try:
        status, payload = _request(base, "GET", "/health", auth="")
        assert status == 200, f"health status {status}"
        assert payload.get("status") == "ok", payload
        return "ok"
    finally:
        server.shutdown()


def check_auth_required_and_schemes():
    server, base = _serve()
    try:
        for bad in ("", "Bearer wrong-key"):
            status, _ = _request(base, "POST", "/search",
                                 {"query": "x", "user_id": "u", "top_k": 1},
                                 auth=bad)
            assert status == 401, f"expected 401, got {status}"
        for good in (f"Bearer {API_KEY}", f"Token {API_KEY}", "X-Api-Key"):
            status, payload = _request(base, "POST", "/search",
                                       {"query": "x", "user_id": "nope",
                                        "top_k": 1}, auth=good)
            assert status == 200, f"scheme {good}: got {status}"
            assert payload.get("data") == [], payload
        return "ok"
    finally:
        server.shutdown()


def check_add_search_official_roundtrip():
    server, base = _serve()
    try:
        payload = _add_payload()
        status, added = _request(base, "POST", "/add", payload)
        assert status == 200, f"add status {status}: {added}"
        # official echo contract: success + byte-for-byte id echoes
        assert added.get("success") is True, added
        assert added.get("request_id") == "req-1", added
        assert added.get("user_id") == "user-1", added
        assert added.get("session_id") == "sess-1", added

        status, found = _request(base, "POST", "/search",
                                 {"query": "black coffee lighthouse",
                                  "user_id": "user-1", "top_k": 5})
        assert status == 200, f"search status {status}: {found}"
        data = found.get("data")
        assert isinstance(data, list) and data, "no evidence returned"
        assert len(data) <= 5, "must not exceed top_k"
        texts = " ".join(r.get("content", "") for r in data)
        assert "lighthouse" in texts or "coffee" in texts, texts[:200]
        # evidence records only: required fields, never a generated answer
        assert "answer" not in found, "search must not synthesize an answer"
        for record in data:
            assert isinstance(record.get("id"), str) and record["id"], record
            assert isinstance(record.get("content"), str) and \
                record["content"], record
            assert "answer" not in record, record
        return f"{len(data)} evidence records"
    finally:
        server.shutdown()


def check_add_idempotent_retry():
    server, base = _serve()
    try:
        payload = _add_payload(request_id="req-dup",
                               texts=["The harbor master dislikes black coffee."])
        for attempt in (1, 2):
            status, added = _request(base, "POST", "/add", payload)
            assert status == 200, f"attempt {attempt}: {status} {added}"
            assert added.get("success") is True, added
            assert added.get("request_id") == "req-dup", added
        status, found = _request(base, "POST", "/search",
                                 {"query": "harbor master coffee",
                                  "user_id": "user-1", "top_k": 100})
        assert status == 200, found
        data = found.get("data", [])
        assert data, "nothing stored"
        # one logical write -> each fragment stored exactly once
        assert len(data) == 1, f"retry duplicated rows: {len(data)}"
        return "replay echoed without rewrite"
    finally:
        server.shutdown()


def check_request_id_conflict_is_409():
    server, base = _serve()
    try:
        status, _ = _request(base, "POST", "/add", _add_payload(
            request_id="req-conflict", texts=["original fact"]))
        assert status == 200, status
        status, payload = _request(base, "POST", "/add", _add_payload(
            request_id="req-conflict", texts=["different fact"]))
        assert status == 409, f"expected 409, got {status}: {payload}"
        # original data intact
        status, found = _request(base, "POST", "/search",
                                 {"query": "original fact",
                                  "user_id": "user-1", "top_k": 10})
        assert any("original fact" in r.get("content", "")
                   for r in found.get("data", [])), found
        return "ok"
    finally:
        server.shutdown()


def check_user_id_isolation():
    server, base = _serve()
    try:
        status, _ = _request(base, "POST", "/add", _add_payload(
            user_id="alice", texts=["Alice keeps bees on the roof."]))
        assert status == 200, status
        # same query, different user -> nothing leaks across
        status, found = _request(base, "POST", "/search",
                                 {"query": "bees roof",
                                  "user_id": "bob", "top_k": 10})
        assert status == 200, found
        assert found.get("data") == [], f"cross-user leak: {found}"
        # unknown user -> empty data, still 200
        status, found = _request(base, "POST", "/search",
                                 {"query": "bees roof",
                                  "user_id": "nobody", "top_k": 10})
        assert status == 200 and found.get("data") == [], found
        # owner user finds it
        status, found = _request(base, "POST", "/search",
                                 {"query": "bees roof",
                                  "user_id": "alice", "top_k": 10})
        assert any("bees" in r.get("content", "")
                   for r in found.get("data", [])), found
        return "ok"
    finally:
        server.shutdown()


def check_top_k_never_exceeded():
    server, base = _serve()
    try:
        texts = [f"synthetic fact number {i} about copper wiring"
                 for i in range(6)]
        status, _ = _request(base, "POST", "/add",
                             _add_payload(request_id="req-k", texts=texts))
        assert status == 200, status
        status, found = _request(base, "POST", "/search",
                                 {"query": "copper wiring",
                                  "user_id": "user-1", "top_k": 2})
        assert status == 200, found
        assert len(found.get("data", [])) == 2, found
        return "ok"
    finally:
        server.shutdown()


def check_contract_errors_are_400():
    server, base = _serve()
    try:
        cases = [
            ({"user_id": "u", "session_id": "s", "messages": []},
             "/add", "empty messages"),
            ({"request_id": "r", "session_id": "s", "messages": []},
             "/add", "missing user_id"),
            ({"request_id": "r", "user_id": "u", "session_id": "s",
              "messages": [{"role": "user"}]}, "/add", "missing content"),
            ({"user_id": "u", "top_k": 5}, "/search", "missing query"),
            ({"query": "x", "top_k": 5}, "/search", "missing user_id"),
        ]
        for body, path, label in cases:
            status, _ = _request(base, "POST", path, body)
            assert status == 400, f"{label}: expected 400, got {status}"
        return "ok"
    finally:
        server.shutdown()


def check_content_parts_coerced():
    server, base = _serve()
    try:
        payload = _add_payload(request_id="req-parts")
        payload["messages"] = [
            {"role": "user",
             "content": [{"type": "text", "text": "The cellar door sticks "
                                                  "in winter."}],
             "timestamp": 1704067200000},
        ]
        status, added = _request(base, "POST", "/add", payload)
        assert status == 200, f"{status}: {added}"
        assert added.get("success") is True, added
        status, found = _request(base, "POST", "/search",
                                 {"query": "cellar door winter",
                                  "user_id": "user-1", "top_k": 5})
        assert any("cellar door" in r.get("content", "")
                   for r in found.get("data", [])), found
        return "ok"
    finally:
        server.shutdown()


def check_options_accepted():
    server, base = _serve()
    try:
        status, _ = _request(base, "POST", "/add", _add_payload(
            request_id="req-opt", texts=["The user lives in Seattle."]))
        assert status == 200, status
        status, found = _request(base, "POST", "/search",
                                 {"query": "Where does the user live?",
                                  "options": ["A. Seattle", "B. Boston"],
                                  "user_id": "user-1", "top_k": 5})
        assert status == 200, f"{status}: {found}"
        assert any("Seattle" in r.get("content", "")
                   for r in found.get("data", [])), found
        return "ok"
    finally:
        server.shutdown()


def check_refuses_live_store():
    live = str(_config.discover_default_db_path())
    for candidate in (live, str(Path(live).parent)):
        try:
            aml.resolve_base_dir(candidate)
        except RuntimeError:
            continue
        if candidate == live:
            raise AssertionError(
                f"adapter accepted the live store path: {candidate}")
    # the default base dir must not be the live store
    default = aml.resolve_base_dir(None)
    assert default != Path(live).resolve(), "default base == live store"
    return str(default)


def run_all() -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []

    def check(name: str, fn) -> None:
        try:
            detail = fn() or "ok"
            results.append({"name": name, "passed": True,
                            "detail": str(detail)[:300]})
        except AssertionError as e:
            results.append({"name": name, "passed": False,
                            "detail": f"assert: {e}"})
        except Exception as e:
            results.append({"name": name, "passed": False,
                            "detail": f"{type(e).__name__}: {e}"})

    check("health_open_without_auth", check_health_open_without_auth)
    check("auth_required_and_schemes", check_auth_required_and_schemes)
    check("add_search_official_roundtrip", check_add_search_official_roundtrip)
    check("add_idempotent_retry", check_add_idempotent_retry)
    check("request_id_conflict_is_409", check_request_id_conflict_is_409)
    check("user_id_isolation", check_user_id_isolation)
    check("top_k_never_exceeded", check_top_k_never_exceeded)
    check("contract_errors_are_400", check_contract_errors_are_400)
    check("content_parts_coerced", check_content_parts_coerced)
    check("options_accepted", check_options_accepted)
    check("refuses_live_store", check_refuses_live_store)
    return results


if __name__ == "__main__":
    results = run_all()
    passed = sum(1 for r in results if r["passed"])
    for r in results:
        print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['name']}: {r['detail']}")
    print(f"\n{passed}/{len(results)} passed")
    sys.exit(0 if passed == len(results) else 1)
