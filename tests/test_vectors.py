"""Local embedding tests: LM Studio OpenAI-compat, Ollama, fail-open.

Always-on checks never need a live embed server. Live 768-d checks skip
(report SKIP, still pass the suite) when nothing is listening.

Throwaway temp databases only.

run_all() -> list of {name, passed, detail}.
"""

from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import patch

REPO_DIR = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _package import import_package  # noqa: E402

_PLUGIN = import_package()


def _cfg(**retrieval_over: Any) -> Dict[str, Any]:
    from hungry_hippa.config import DEFAULTS

    cfg = copy.deepcopy(DEFAULTS)
    cfg["retrieval"].update(retrieval_over)
    return cfg


def _store(**retrieval_over: Any):
    from hungry_hippa.db import Database
    from hungry_hippa.vectors import VectorStore

    tmp = tempfile.mkdtemp(prefix="hh_vec_")
    db = Database(os.path.join(tmp, "hungry_hippa.db"))
    return VectorStore(db, _cfg(**retrieval_over))


def _openai_body(dim: int = 8) -> bytes:
    return json.dumps({"data": [{"embedding": [0.1] * dim}]}).encode("utf-8")


def _ollama_body(dim: int = 8) -> bytes:
    return json.dumps({"embedding": [0.2] * dim}).encode("utf-8")


class _EmbedServer(ThreadingHTTPServer):
    hits: List[Dict[str, Any]]
    response_body: bytes


def _serve(response_body: bytes) -> _EmbedServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            return

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length)
            self.server.hits.append({
                "path": self.path,
                "body": body,
                "headers": {k.lower(): v for k, v in self.headers.items()},
            })
            payload = self.server.response_body
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    srv = _EmbedServer(("127.0.0.1", 0), Handler)
    srv.hits = []
    srv.response_body = response_body
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    return srv


# ---------------------------------------------------------------- always-on

def check_defaults_target_lm_studio():
    from hungry_hippa.config import DEFAULTS
    from hungry_hippa.vectors import VectorStore

    ret = DEFAULTS["retrieval"]
    assert ret["embedding_backend"] == "openai-compat", ret["embedding_backend"]
    assert ret["embed_url"] == "http://127.0.0.1:1234/v1", ret["embed_url"]
    assert ret["embedding_model"] == "text-embedding-nomic-embed-text-v1.5"
    assert ret["ollama_url"] == "http://127.0.0.1:11434"
    vs = _store()
    assert vs.backend == "openai-compat"
    assert vs.url == "http://127.0.0.1:1234/v1"
    assert vs.model == "text-embedding-nomic-embed-text-v1.5"
    health = vs.health()
    assert health["backend"] == "openai-compat"
    assert health["url"] == "http://127.0.0.1:1234/v1"
    assert VectorStore is not None
    return "default backend openai-compat at 127.0.0.1:1234/v1"


def check_embed_empty_or_disabled_is_none():
    vs = _store()
    assert vs.embed("") is None
    assert vs.embed("   ") is None
    off = _store(vectors_enabled=False)
    assert off.embed("bracket cracked") is None
    assert off.search("bracket") == []
    return "empty text and vectors_enabled=false are no-ops"


def check_fail_open_when_server_down():
    vs = _store(embed_url="http://127.0.0.1:1/v1", embed_timeout_s=0.3)
    assert vs.embed("anything at all") is None
    assert vs.search("anything") == []
    assert vs.store("episode", "E-1", "anything") is False
    assert vs.health()["reachable"] is False
    # cached miss does not retry
    with patch("hungry_hippa.vectors._http_post_json",
               side_effect=AssertionError("retry after fail-open")):
        assert vs.embed("second call") is None
    return "unreachable loopback server fail-opens and caches the miss"


def check_fail_open_recall_uses_fts():
    from hungry_hippa.controller import MemoryController

    cfg = _cfg(embed_url="http://127.0.0.1:1/v1", embed_timeout_s=0.3,
               vectors_enabled=True)
    tmp = tempfile.mkdtemp(prefix="hh_vec_fts_")
    c = MemoryController(cfg, db_path=os.path.join(tmp, "hungry_hippa.db"))
    c.bind_session(session_id="vec-fts", platform="cli")
    marker = "brass-sprocket-quaternion-hippa"
    r = c.remember_episode(
        context=f"{marker} cracked near the bolt interface",
        outcome="success", project="vec_fts", embed=True)
    assert r.get("episode_id", "").startswith("E-"), r
    out = c.recall(marker)
    ids = [it.get("episode_id") for it in out.get("items", [])]
    assert r["episode_id"] in ids, (ids, out.get("excluded"))
    assert c.vectors.health()["reachable"] is False
    return f"FTS recall found {r['episode_id']} with embed server down"


def check_non_loopback_url_is_refused():
    from hungry_hippa.vectors import _is_loopback_url

    assert _is_loopback_url("http://127.0.0.1:1234/v1")
    assert _is_loopback_url("http://127.0.0.2:9/v1")
    assert _is_loopback_url("http://localhost:11434")
    assert _is_loopback_url("http://[::1]:1234/v1")
    assert not _is_loopback_url("https://api.openai.com/v1")
    assert not _is_loopback_url("http://203.0.113.1:1234/v1")
    assert not _is_loopback_url("http://10.0.0.1:11434")
    assert not _is_loopback_url("http://127.0.0.1.evil.example/v1")
    assert not _is_loopback_url("file:///tmp/x")

    vs = _store(embed_url="https://api.openai.com/v1",
                embedding_backend="openai-compat")
    with patch("hungry_hippa.vectors._http_post_json",
               side_effect=AssertionError("non-loopback must not POST")):
        assert vs.embed("secret memory text") is None
    assert vs.health()["reachable"] is False
    return "non-loopback URLs are refused without a network call"


def check_openai_compat_request_shape():
    srv = _serve(_openai_body(dim=8))
    try:
        host, port = srv.server_address
        vs = _store(embedding_backend="openai-compat",
                    embed_url=f"http://{host}:{port}/v1",
                    embedding_model="text-embedding-nomic-embed-text-v1.5",
                    embed_api_key="lm-studio",
                    embed_timeout_s=2)
        vec = vs.embed("hello local embed")
        assert vec is not None and len(vec) == 8, vec
        assert len(srv.hits) == 1, srv.hits
        hit = srv.hits[0]
        assert hit["path"] == "/v1/embeddings", hit["path"]
        payload = json.loads(hit["body"].decode("utf-8"))
        assert payload["model"] == "text-embedding-nomic-embed-text-v1.5"
        assert payload["input"] == "hello local embed"
        assert "prompt" not in payload
        assert hit["headers"].get("authorization") == "Bearer lm-studio"
    finally:
        srv.shutdown()
    return "openai-compat POSTs /v1/embeddings with input + Bearer"


def check_ollama_request_shape():
    srv = _serve(_ollama_body(dim=8))
    try:
        host, port = srv.server_address
        vs = _store(embedding_backend="ollama",
                    ollama_url=f"http://{host}:{port}",
                    embedding_model="nomic-embed-text",
                    embed_timeout_s=2)
        vec = vs.embed("hello ollama embed")
        assert vec is not None and len(vec) == 8, vec
        assert len(srv.hits) == 1, srv.hits
        hit = srv.hits[0]
        assert hit["path"] == "/api/embeddings", hit["path"]
        payload = json.loads(hit["body"].decode("utf-8"))
        assert payload["model"] == "nomic-embed-text"
        assert payload["prompt"] == "hello ollama embed"
        assert "input" not in payload
        assert "authorization" not in hit["headers"]
    finally:
        srv.shutdown()
    return "ollama POSTs /api/embeddings with prompt, no Bearer"


def check_proxy_env_does_not_escape_loopback():
    srv = _serve(_openai_body(dim=4))
    saved = {k: os.environ.get(k) for k in
             ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy",
              "https_proxy", "all_proxy")}
    try:
        for key in saved:
            os.environ[key] = "http://203.0.113.1:9"
        host, port = srv.server_address
        vs = _store(embedding_backend="openai-compat",
                    embed_url=f"http://{host}:{port}/v1",
                    embed_timeout_s=2)
        vec = vs.embed("must not leave the box")
        assert vec is not None and len(vec) == 4, vec
        assert len(srv.hits) == 1, srv.hits
    finally:
        srv.shutdown()
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    return "HTTP_PROXY does not intercept loopback embed POST"


def check_unknown_backend_fail_open():
    vs = _store(embedding_backend="openai",
                embed_url="http://127.0.0.1:1234/v1")
    with patch("hungry_hippa.vectors._http_post_json",
               side_effect=AssertionError("unknown backend must not POST")):
        assert vs.embed("do not ship this") is None
    return "backend other than ollama|openai-compat fail-opens"


def check_vector_only_eligible_recall():
    """Unreadable top-k vectors must not hide a durable permitted memory."""
    import subprocess
    from hungry_hippa import trust
    from hungry_hippa.controller import MemoryController

    child = '''
import copy, json, sys
from hungry_hippa.config import DEFAULTS
from hungry_hippa.controller import MemoryController
from hungry_hippa import trust
cfg = copy.deepcopy(DEFAULTS)
cfg['manager'] = {'enabled': False}
c = MemoryController(cfg, db_path=sys.argv[1])
c.bind_session(session_id='second-process', platform='mcp',
               trust=trust.external_binding('fixture-client'))
calls = []
def embed(text):
    calls.append(text)
    return [1.0, 0.0]
c.vectors.embed = embed
out = c.recall('semanticquestion', limit=1, explain=True)
print(json.dumps({'recall': out, 'calls': calls}))
'''
    for kind in ('belief', 'episode'):
        for crowd in ('other_actor', 'private', 'quarantined', 'archived'):
            with tempfile.TemporaryDirectory(prefix='hh_vec_eligible_') as root:
                path = str(Path(root) / 'fixture.db')
                cfg = _cfg(vectors_enabled=True)
                cfg['manager'] = {'enabled': False}
                c = MemoryController(cfg, db_path=path)
                c.vectors.embed = lambda text: [0.8, 0.6] if text == 'allowed' else [1.0, 0.0]
                key = kind + '_id'

                def add(text, **kwargs):
                    kwargs.setdefault('actor_id', 'fixture-client')
                    kwargs['identity'] = trust.OWNER
                    if kind == 'belief':
                        return c.semantic.add_belief(text, source_class='document', **kwargs)
                    return c.episodic.remember_episode(context=text, **kwargs)

                hidden = []
                for n in range(c.vectors.ret.get('vector_top_k', 8)):
                    kw = {}
                    if crowd == 'private': kw['sensitivity'] = 'private'
                    if crowd == 'quarantined': kw['quarantined'] = True
                    if crowd == 'other_actor': kw['actor_id'] = 'other-client'
                    row = add(f'invented concealed workshop record {n}', **kw)
                    rid = row[key]
                    if crowd == 'archived':
                        table = 'beliefs' if kind == 'belief' else 'episodes'
                        c.db._run(lambda conn: conn.execute(
                            f'UPDATE {table} SET status=? WHERE {key}=?',
                            ('archived', rid)), write=True)
                    assert c.vectors.store(kind, rid, 'hidden')
                    hidden.append(rid)
                evidence = c.db.add_evidence('invented durable vector evidence',
                                             'document', 'fixture:vector', '')
                own = add('assigned workshop detail', evidence_ids=[evidence])
                assert c.vectors.store(kind, own[key], 'allowed')
                assert c.db.fts_search('semanticquestion') == []
                raw = c.vectors.search('semanticquestion')
                assert {h['target_id'] for h in raw} == set(hidden), raw
                assert own[key] in {h['target_id'] for h in c.vectors.search('semanticquestion', top_k=100)}
                proc = subprocess.run([sys.executable, '-c', child, path],
                                      capture_output=True, text=True, check=True)
                result = json.loads(proc.stdout)
                out = result['recall']
                assert 'error' not in out, out
                assert [r.get(key) for r in out['items']] == [own[key]], (kind, crowd, out)
                assert evidence in out['sources'], out
                assert 'assigned workshop detail' in out['context'], out
                assert result['calls'] == ['semanticquestion'], result
    return 'eight vector-only second-process recall cases retain evidence; one embedding each; raw search unchanged'


def check_vector_window_boundaries():
    from hungry_hippa import trust
    from hungry_hippa.controller import MemoryController

    with tempfile.TemporaryDirectory(prefix='hh_vec_boundary_') as root:
        c = MemoryController(_cfg(vector_top_k=1), db_path=str(Path(root) / 'fixture.db'))
        calls = []
        def embed(text):
            calls.append(text)
            return [0.8, 0.6] if text == 'allowed' else [1.0, 0.0]
        c.vectors.embed = embed
        # An orphan always wins the historical window but is never supplemented.
        assert c.vectors.store('belief', 'B-orphan', 'hidden')
        targets = []
        for kind in ('belief', 'episode'):
            kwargs: Dict[str, Any] = dict(actor_id='fixture-client', identity=trust.OWNER)
            row = (c.semantic.add_belief('invented boundary belief', **kwargs)
                   if kind == 'belief' else
                   c.episodic.remember_episode(context='invented boundary episode', **kwargs))
            rid = row[kind + '_id']
            assert c.vectors.store(kind, rid, 'allowed')
            targets.append((kind, rid))
        for k in (1, 2, 5):
            raw = c.vectors.search('semanticquestion', top_k=k)
            for predicate in (lambda row: True, lambda row: False):
                calls.clear()
                hits = c.vectors.search('semanticquestion', top_k=k,
                                         supplement_eligible=predicate)
                keys = [(h['kind'], h['target_id']) for h in hits]
                assert len(keys) == len(set(keys)) <= 2 * k, hits
                assert hits[:len(raw)] == raw, (raw, hits)
                assert calls == ['semanticquestion'], calls
            assert c.vectors.search('semanticquestion', top_k=k) == raw
        hits = c.vectors.search('semanticquestion', top_k=1,
                                 supplement_eligible=lambda row: True)
        assert [(h['kind'], h['target_id']) for h in hits] == [('belief', 'B-orphan'), targets[0]]
        episode_hits = c.vectors.search('semanticquestion', kinds=['episode'], top_k=1,
                                         supplement_eligible=lambda row: True)
        assert [(h['kind'], h['target_id']) for h in episode_hits] == [targets[1]]

        # Run every identity/review case with only that kind and the orphan indexed.
        for kind, rid in targets:
            other_kind, other_id = next(pair for pair in targets if pair[0] != kind)
            c.vectors.remove(other_kind, other_id)
            table = 'beliefs' if kind == 'belief' else 'episodes'
            key = kind + '_id'
            cases = [
                ('elsewhere', 'private', 0, 'active', 'viewer', trust.OWNER, False, True),
                ('elsewhere', 'restricted', 0, 'active', 'viewer', trust.SYSTEM, False, True),
                ('primary', 'unclassified', 0, 'active', 'primary', trust.UNTRUSTED, True, False),
                ('owner', 'unclassified', 0, 'active', 'owner', trust.UNTRUSTED, True, False),
                ('fixture-client', 'unclassified', 1, 'active', 'fixture-client', trust.UNTRUSTED, False, False),
                ('fixture-client', 'unclassified', 1, 'active', 'fixture-client', trust.UNTRUSTED, True, True),
                ('elsewhere', 'unclassified', 1, 'active', 'fixture-client', trust.UNTRUSTED, True, False),
                ('fixture-client', 'unclassified', 1, 'archived', 'fixture-client', trust.OWNER, True, False),
                ("  fixture'client  ", ' UNCLASSIFIED ', 0, 'active', " fixture'client ", trust.UNTRUSTED, False, True),
                ('fixture-client', 'private', 0, 'active', 'fixture-client', trust.UNTRUSTED, True, False),
            ]
            for actor, sensitivity, quarantined, status, caller, identity, review, expected in cases:
                c.db._run(lambda conn: conn.execute(
                    f'UPDATE {table} SET actor_id=?, sensitivity=?, quarantined=?, status=? WHERE {key}=?',
                    (actor, sensitivity, quarantined, status, rid)), write=True)
                out = c.retrieval.recall('semanticquestion', actor_id=caller,
                                          identity=identity, include_quarantined=review,
                                          limit=1, explain=True)
                assert 'error' not in out, out
                assert bool(out['items']) == expected, (kind, cases, out)
                if expected:
                    assert out['items'][0][key] == rid, out
                else:
                    assert not out['sources'] and not out.get('explain'), out
                    if identity == trust.UNTRUSTED:
                        assert out['excluded']['unauthorized'] is True, out
            # Selection is not authorization: change the record after search returns.
            c.db._run(lambda conn: conn.execute(
                f'UPDATE {table} SET actor_id=?, sensitivity=?, quarantined=0, status=? WHERE {key}=?',
                ('fixture-client', 'unclassified', 'active', rid)), write=True)
            original = c.vectors.search
            selected = []
            def search_then_restrict(*args, **kwargs):
                hits = original(*args, **kwargs)
                assert rid in [h['target_id'] for h in hits], hits
                selected.append(rid)
                c.db._run(lambda conn: conn.execute(
                    f'UPDATE {table} SET sensitivity=? WHERE {key}=?', ('private', rid)), write=True)
                return hits
            with patch.object(c.vectors, 'search', side_effect=search_then_restrict):
                out = c.retrieval.recall('semanticquestion', actor_id='fixture-client',
                                          identity=trust.UNTRUSTED, explain=True)
            assert selected == [rid] and out['items'] == [] and out['sources'] == [], out
            assert out['explain'] == [] and out['excluded']['unauthorized'], out
            assert c.vectors.store(other_kind, other_id, 'allowed')
    return 'bounded deduplicated windows, orphan/kind/tie compatibility, identity/review matrix and post-selection denial'


# ---------------------------------------------------------------- live (skip)

def _live_probe() -> Optional[List[float]]:
    vs = _store()
    return vs.embed("hungry hippa embed probe")


def check_live_embed_returns_768():
    vec = _live_probe()
    if vec is None:
        return "SKIP: no local embed server at default openai-compat URL"
    assert len(vec) == 768, f"expected 768-d nomic vector, got {len(vec)}"
    assert all(isinstance(x, float) for x in vec[:4])
    return f"live embed dim={len(vec)} url=http://127.0.0.1:1234/v1"


def check_live_store_and_search():
    vs = _store()
    probe = vs.embed("hungry hippa search probe")
    if probe is None:
        return "SKIP: no local embed server at default openai-compat URL"
    assert vs.store("episode", "E-live", "the brass sprocket sheared at the hub")
    hits = vs.search("broken sprocket at the hub", kinds=["episode"], top_k=3)
    assert hits and hits[0]["target_id"] == "E-live", hits
    assert hits[0]["score"] > 0.0
    return f"live vector search score={hits[0]['score']:.3f}"


# --------------------------------------------------------------------------- runner

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

    check("defaults_target_lm_studio", check_defaults_target_lm_studio)
    check("embed_empty_or_disabled_is_none", check_embed_empty_or_disabled_is_none)
    check("fail_open_when_server_down", check_fail_open_when_server_down)
    check("fail_open_recall_uses_fts", check_fail_open_recall_uses_fts)
    check("non_loopback_url_is_refused", check_non_loopback_url_is_refused)
    check("openai_compat_request_shape", check_openai_compat_request_shape)
    check("ollama_request_shape", check_ollama_request_shape)
    check("proxy_env_does_not_escape_loopback", check_proxy_env_does_not_escape_loopback)
    check("unknown_backend_fail_open", check_unknown_backend_fail_open)
    check("vector_window_boundaries", check_vector_window_boundaries)
    check("vector_only_eligible_recall", check_vector_only_eligible_recall)
    check("live_embed_returns_768", check_live_embed_returns_768)
    check("live_store_and_search", check_live_store_and_search)
    return results


if __name__ == "__main__":
    results = run_all()
    passed = sum(1 for r in results if r["passed"])
    for r in results:
        print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['name']}: {r['detail']}")
    print(f"\n{passed}/{len(results)} passed")
    sys.exit(0 if passed == len(results) else 1)
