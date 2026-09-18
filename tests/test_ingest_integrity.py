"""Hostile-input and exact-source regression tests using synthetic history only."""
from __future__ import annotations

import copy
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _package import import_package
import_package()
from hungry_hippa.db import Database, backup_sqlite
from hungry_hippa.ingest import chatgpt
from hungry_hippa.ingest.store import persist_parsed_export, verify_archive
from test_chatgpt_ingest import _linear_export, _regenerated_reply_export, _cli_env, _run_cli


class ImportIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="hh_integrity_")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / "memory.db"
        self.db = Database(str(self.path))

    def put(self, payload, *, raw=None):
        raw = raw if raw is not None else json.dumps(payload).encode()
        parsed = chatgpt.parse_chatgpt_bytes(raw)
        result = persist_parsed_export(self.db, parsed, source_bytes=raw)
        return result, raw

    def test_exact_snapshot_survives_source_change_and_backup(self):
        raw = json.dumps(_linear_export()).encode()
        source = self.root / "export.json"
        source.write_bytes(raw)
        parsed = chatgpt.parse_chatgpt_bytes(chatgpt.read_export_bytes(source))
        source.write_bytes(b'[]')
        failed = persist_parsed_export(self.db, parsed, source_path=str(source))
        self.assertFalse(failed.ok)
        saved = persist_parsed_export(self.db, parsed, source_path=str(source), source_bytes=raw)
        self.assertTrue(saved.ok, saved.error)
        source.unlink()
        backup = self.root / "restored.db"
        backup_sqlite(str(self.path), str(backup))
        restored = Database(str(backup))
        self.assertEqual(restored.get_ingest_archive_bytes(saved.sha256), raw)
        self.assertTrue(verify_archive(restored, saved.sha256)["ok"])
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)

    def test_reimports_keep_each_archive_and_latest_branch(self):
        payload = _regenerated_reply_export()
        first, raw = self.put(payload)
        changed = copy.deepcopy(payload)
        changed[0]["current_node"] = "n-b1"
        changed[0]["mapping"].pop("n-c")
        changed[0]["mapping"].pop("n-b2")
        changed[0]["mapping"]["n-a"]["children"] = ["n-b1"]
        second, _ = self.put(changed)
        self.assertTrue(second.ok, second.error)
        old_turn = self.db.get_ingest_turn_sources("chatgpt", "conv-regen", "n-c")
        self.assertEqual([a["sha256"] for a in old_turn], [first.sha256])
        self.assertTrue(verify_archive(self.db, first.sha256)["ok"])
        self.assertTrue(verify_archive(self.db, second.sha256)["ok"])
        again, _ = self.put(payload, raw=raw)
        self.assertTrue(again.ok, again.error)
        self.assertEqual(again.turns_inserted, 0)
        latest = self.db.get_ingest_conversation("chatgpt", "conv-regen")
        self.assertEqual(latest["current_node"], "n-b1")
        turns = self.db.get_ingest_turns("chatgpt", "conv-regen")
        self.assertFalse(next(t for t in turns if t["turn_id"] == "n-c")["on_current_path"])

    def test_conflicting_turn_rolls_back_whole_import(self):
        first, _ = self.put(_linear_export())
        payload = _linear_export()
        payload[0]["mapping"]["n-a"]["message"]["content"]["parts"] = ["Poison replacement"]
        extra = copy.deepcopy(payload[0])
        extra["id"] = "new-session"
        payload.insert(0, extra)
        refused, _ = self.put(payload)
        self.assertFalse(refused.ok)
        self.assertEqual(self.db.ingest_counts(), {
            "ingest_archives": 1, "ingest_conversations": 1, "ingest_turns": 2})
        self.assertTrue(verify_archive(self.db, first.sha256)["ok"])

    def test_byte_and_canonical_tampering_are_detected(self):
        saved, raw = self.put(_linear_export())
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("UPDATE ingest_turns SET content = 'tampered' WHERE turn_id = 'n-a'")
        self.assertFalse(verify_archive(self.db, saved.sha256)["ok"])
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("UPDATE ingest_archive_bytes SET raw_bytes = ?", (raw + b' ',))
        self.assertIn("integrity", verify_archive(self.db, saved.sha256)["error"])

    def test_v6_pointer_requires_reimport_for_verified_evidence(self):
        from hungry_hippa.schema import MIGRATIONS
        saved, raw = self.put(_linear_export())
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.executescript(MIGRATIONS[7]["down"])
            conn.execute("DELETE FROM schema_migrations WHERE version = 7")
        self.db = Database(str(self.path))
        self.assertIsNotNone(self.db.last_backup)
        self.assertFalse(verify_archive(self.db, saved.sha256)["ok"])
        again, _ = self.put(_linear_export(), raw=raw)
        self.assertTrue(again.ok, again.error)
        self.assertTrue(verify_archive(self.db, saved.sha256)["ok"])

    def test_persistent_growth_budget_refuses_atomically(self):
        with patch.dict(os.environ, {"HUNGRY_HIPPA_MAX_DB_BYTES": "1"}):
            result, _ = self.put(_linear_export())
        self.assertFalse(result.ok)
        self.assertEqual(self.db.ingest_counts()["ingest_archives"], 0)
        with closing(sqlite3.connect(self.path)) as conn, conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM ingest_archive_bytes").fetchone()[0], 0)

    def test_ambiguous_and_nonfinite_json_is_refused(self):
        bad = [b'{"error":"unknown"}', b'{"mapping":{},"mapping":{}}',
               b'[{"mapping":{},"create_time":NaN}]',
               b'[{"mapping":{},"create_time":1e9999}]',
               b'[{"mapping":{},"title":"\\ud800"}]',
               json.dumps(_linear_export() * 2).encode(),
               b'[' * 80 + b']' * 80]
        for raw in bad:
            with self.subTest(raw=raw[:40]), self.assertRaises(ValueError):
                chatgpt.parse_chatgpt_bytes(raw)

    def test_size_and_lineage_limits_refuse_before_persistence(self):
        file = self.root / "too-big.json"
        file.write_bytes(b' ' * 1025)
        with patch.object(chatgpt, "MAX_EXPORT_BYTES", 1024), self.assertRaises(ValueError):
            chatgpt.read_export_bytes(file)
        with patch.object(chatgpt, "MAX_TOTAL_PATH_ENTRIES", 2), self.assertRaises(ValueError):
            chatgpt.parse_chatgpt_bytes(json.dumps(_linear_export()).encode())
        self.assertEqual(self.db.ingest_counts()["ingest_turns"], 0)

    def test_deep_valid_conversation_is_never_silently_lost(self):
        nodes = {}
        for i in range(1100):
            nodes[str(i)] = {"parent": str(i-1) if i else None,
                            "children": [str(i+1)] if i < 1099 else [],
                            "message": {"author": {"role": "user"},
                                        "content": {"parts": [f"Synthetic turn {i}"]}}}
        convo = chatgpt.parse_chatgpt_payload({"id": "long-session", "mapping": nodes,
                                              "current_node": "1099"})[0]
        self.assertEqual(convo.turn_count, 1100)
        self.assertEqual(len(convo.current_path_turn_ids), 1100)

    def test_idless_exports_do_not_collide(self):
        first = _linear_export()
        del first[0]["id"]
        second = copy.deepcopy(first)
        second[0]["mapping"]["n-a"]["message"]["content"]["parts"] = ["Unrelated conversation"]
        a, _ = self.put(first)
        b, _ = self.put(second)
        self.assertTrue(a.ok and b.ok, (a.error, b.error))
        self.assertEqual(self.db.ingest_counts()["ingest_conversations"], 2)

    def test_fifo_symlink_and_untrusted_paths_never_opened(self):
        fifo = self.root / "fifo"
        os.mkfifo(fifo)
        with self.assertRaises(OSError):
            chatgpt.read_export_bytes(fifo)
        source = self.root / "source.json"
        source.write_text('[]')
        link = self.root / "linked.json"
        link.symlink_to(source)
        with self.assertRaises(OSError):
            chatgpt.read_export_bytes(link)
        payload = _linear_export()
        payload[0]["mapping"]["n-a"]["message"]["metadata"] = {
            "path": "../../private", "command": "touch NEVER_EXECUTE"}
        saved, _ = self.put(payload)
        self.assertTrue(saved.ok)
        self.assertFalse((self.root / "NEVER_EXECUTE").exists())

    def test_cli_requires_destination_and_can_verify_and_show(self):
        file = self.root / "input.json"
        file.write_text(json.dumps(_linear_export()))
        env = _cli_env(str(self.path))
        env.pop("HUNGRY_HIPPA_DB")
        refused = _run_cli(["ingest", "chatgpt", str(file), "--apply"], env=env, cwd=self.tmp.name)
        self.assertEqual(refused.returncode, 1)
        self.assertIn("choose an import database", refused.stdout)
        applied = _run_cli(["ingest", "chatgpt", str(file), "--apply", "--db", str(self.path)],
                           env=env, cwd=self.tmp.name)
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        digest = hashlib.sha256(file.read_bytes()).hexdigest()
        verified = _run_cli(["ingest", "verify", digest, "--db", str(self.path)], env=env, cwd=self.tmp.name)
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        self.assertTrue(json.loads(verified.stdout)["ok"])
        shown = _run_cli(["ingest", "show", "conv-linear", "--db", str(self.path)], env=env, cwd=self.tmp.name)
        self.assertEqual(shown.returncode, 0, shown.stdout + shown.stderr)
        self.assertEqual(json.loads(shown.stdout)["turns"][0]["archives"][0]["sha256"], digest)


if __name__ == "__main__":
    unittest.main(verbosity=2)
