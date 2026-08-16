"""Vector memory (§3/§5) — local embeddings via Ollama.

Privacy rule (§19.8): embeddings are computed by the LOCAL Ollama instance
only; nothing is uploaded. If Ollama is unreachable or disabled, vector
operations degrade to no-ops and retrieval falls back to FTS5/graph
(fail safely, §19.15).
"""

from __future__ import annotations

import json
import math
import struct
import threading
import urllib.request
from typing import Any, Dict, List, Optional

from . import db as _db

_NOMIC_DIM = 768


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class VectorStore:
    def __init__(self, database: _db.Database, config: Dict):
        self.db = database
        self.cfg = config
        self.ret = config.get("retrieval", {})
        self.model = self.ret.get("embedding_model", "nomic-embed-text")
        self.url = (self.ret.get("ollama_url", "http://127.0.0.1:11434")).rstrip("/")
        self.timeout = float(self.ret.get("embed_timeout_s", 10))
        self.enabled = bool(self.ret.get("vectors_enabled", True))
        self._health: Optional[bool] = None
        self._health_lock = threading.Lock()

    # ------------------------------------------------------------ embedding

    def embed(self, text: str) -> Optional[List[float]]:
        """Compute a local embedding, or None when unavailable."""
        if not self.enabled or not text or not text.strip():
            return None
        if self._health is False:
            return None
        payload = json.dumps({"model": self.model, "prompt": text[:4000]}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.url}/api/embeddings", data=payload,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            vec = data.get("embedding")
            if not isinstance(vec, list) or not vec:
                return None
            self._set_health(True)
            return [float(x) for x in vec]
        except Exception:
            self._set_health(False)
            return None

    def _set_health(self, ok: bool) -> None:
        with self._health_lock:
            self._health = ok

    def health(self) -> Dict[str, Any]:
        return {"enabled": self.enabled, "model": self.model,
                "url": self.url, "reachable": self._health}

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
