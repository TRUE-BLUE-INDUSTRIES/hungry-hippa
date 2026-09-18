"""Vector memory (§3/§5) — local embeddings, fail-open.

Privacy rule (§19.8): embeddings are computed by a LOCAL server only
(OpenAI-compatible LM Studio by default, or Ollama). Memory text is never
POSTed to a non-loopback URL, and HTTP proxies are ignored so a proxy env
cannot exfiltrate it. If the embed server is unreachable, disabled, or the
URL is not loopback, vector operations degrade to no-ops and retrieval
falls back to FTS5/graph (fail safely, §19.15).
"""

from __future__ import annotations

import ipaddress
import json
import math
import struct
import threading
import urllib.request
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from . import db as _db

_NOMIC_DIM = 768
_BACKENDS = ("openai-compat", "ollama")
_LOOPBACK_HOSTS = {"localhost"}

# Never send memory text through an HTTP(S) proxy, even if the environment
# has HTTP_PROXY/HTTPS_PROXY/ALL_PROXY set.
_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _is_loopback_url(url: str) -> bool:
    """True only for http(s) URLs whose host is loopback, without DNS."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return False
    if host in _LOOPBACK_HOSTS:
        return True
    try:
        return bool(ipaddress.ip_address(host).is_loopback)
    except ValueError:
        return False


def _http_post_json(url: str, payload: Dict[str, Any],
                    headers: Dict[str, str], timeout: float) -> Dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    hdrs = {"Content-Type": "application/json"}
    hdrs.update(headers)
    req = urllib.request.Request(url, data=body, headers=hdrs, method="POST")
    with _NO_PROXY.open(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data if isinstance(data, dict) else {}


class VectorStore:
    def __init__(self, database: _db.Database, config: Dict):
        self.db = database
        self.cfg = config
        self.ret = config.get("retrieval", {})
        self.backend = str(self.ret.get("embedding_backend", "openai-compat")).strip().lower()
        self.model = self.ret.get(
            "embedding_model", "text-embedding-nomic-embed-text-v1.5")
        if self.backend == "ollama":
            self.url = (self.ret.get("ollama_url")
                        or "http://127.0.0.1:11434").rstrip("/")
        else:
            self.url = (self.ret.get("embed_url")
                        or "http://127.0.0.1:1234/v1").rstrip("/")
        self.api_key = str(self.ret.get("embed_api_key", "lm-studio") or "")
        self.timeout = float(self.ret.get("embed_timeout_s", 10))
        self.enabled = bool(self.ret.get("vectors_enabled", True))
        self._health: Optional[bool] = None
        self._health_lock = threading.Lock()
        self._loopback = _is_loopback_url(self.url)
        if self.enabled and not self._loopback:
            self._health = False

    # ------------------------------------------------------------ embedding

    def embed(self, text: str) -> Optional[List[float]]:
        """Compute a local embedding, or None when unavailable."""
        if not self.enabled or not text or not text.strip():
            return None
        if self._health is False:
            return None
        if self.backend not in _BACKENDS or not self._loopback:
            self._set_health(False)
            return None
        try:
            vec = self._embed_request(text[:4000])
        except Exception:
            self._set_health(False)
            return None
        if not isinstance(vec, list) or not vec:
            return None
        self._set_health(True)
        return [float(x) for x in vec]

    def _embed_request(self, text: str) -> Optional[List[float]]:
        if self.backend == "ollama":
            endpoint = f"{self.url}/api/embeddings"
            payload: Dict[str, Any] = {"model": self.model, "prompt": text}
            headers: Dict[str, str] = {}
        else:
            endpoint = f"{self.url}/embeddings"
            payload = {"model": self.model, "input": text}
            headers = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
        data = _http_post_json(endpoint, payload, headers, self.timeout)
        if self.backend == "ollama":
            vec = data.get("embedding")
        else:
            rows = data.get("data")
            vec = None
            if isinstance(rows, list) and rows and isinstance(rows[0], dict):
                vec = rows[0].get("embedding")
        return vec if isinstance(vec, list) else None

    def _set_health(self, ok: bool) -> None:
        with self._health_lock:
            self._health = ok

    def health(self) -> Dict[str, Any]:
        return {"enabled": self.enabled, "backend": self.backend,
                "model": self.model, "url": self.url,
                "reachable": self._health}

    # -------------------------------------------------------------- storage

    def store(self, kind: str, target_id: str, text: str) -> bool:
        """Embed and store text for a target. Idempotent per (kind, target)."""
        vec = self.embed(text)
        if not vec:
            return False
        vector_id = self.db.next_id("vector")
        blob = struct.pack(f"<{len(vec)}f", *vec)

        def _store(conn) -> None:
            conn.execute("DELETE FROM vectors WHERE kind = ? AND target_id = ?",
                         (kind, target_id))
            conn.execute(
                "INSERT INTO vectors(vector_id, kind, target_id, dim, vec, model, created_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (vector_id, kind, target_id, len(vec), blob, self.model, _db.now_iso()),
            )

        return self.db._run(_store, write=True) is not None

    def remove(self, kind: str, target_id: str) -> None:
        def _rm(conn) -> None:
            conn.execute("DELETE FROM vectors WHERE kind = ? AND target_id = ?",
                         (kind, target_id))

        self.db._run(_rm, write=True)

    # ------------------------------------------------------------ similarity

    def search(self, query: str, kinds: Optional[List[str]] = None,
               top_k: Optional[int] = None) -> List[Dict[str, Any]]:
        """Vector search over stored embeddings, ranked by cosine similarity."""
        qvec = self.embed(query)
        if not qvec:
            return []
        top_k = top_k or int(self.ret.get("vector_top_k", 8))

        def _search(conn) -> List[Dict[str, Any]]:
            sql = "SELECT * FROM vectors"
            params: List[Any] = []
            if kinds:
                sql += " WHERE kind IN (%s)" % ",".join("?" for _ in kinds)
                params.extend(kinds)
            rows = conn.execute(sql, params).fetchall()
            scored = []
            for r in rows:
                try:
                    vec = list(struct.unpack(f"<{r['dim']}f", bytes(r["vec"])))
                except Exception:
                    continue
                scored.append({
                    "kind": r["kind"], "target_id": r["target_id"],
                    "score": _cosine(qvec, vec),
                })
            scored.sort(key=lambda x: -x["score"])
            return scored[:top_k]

        return self.db._run(_search) or []
