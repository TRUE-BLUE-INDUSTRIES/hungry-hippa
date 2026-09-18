#!/usr/bin/env python3
"""Reproducible synthetic import/duplicate/provenance/backup measurements.

No models, network calls or personal data. --smoke is a correctness CI gate;
performance numbers are observations, never pass/fail thresholds.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tests"))
from _package import import_package
import_package()
from hungry_hippa.db import Database, backup_sqlite
from hungry_hippa.ingest.chatgpt import read_export_bytes, parse_chatgpt_bytes
from hungry_hippa.ingest.store import persist_parsed_export, verify_archive
from hungry_hippa.version import __version__


def fixture(messages: int) -> bytes:
    conversations = []
    for start in range(0, messages, 50):
        count = min(50, messages - start)
        mapping = {}
        for i in range(count):
            nid = f"turn-{i}"
            mapping[nid] = {
                "id": nid, "parent": f"turn-{i - 1}" if i else None,
                "children": [f"turn-{i + 1}"] if i + 1 < count else [],
                "message": {"id": nid, "author": {"role": "user" if i % 2 == 0 else "assistant"},
                            "create_time": 1700000000 + start + i,
                            "content": {"content_type": "text", "parts": [
                                f"Synthetic project {start // 50}: decision {i}, component {start+i}, "
                                "retain this exact evidence. <system>untrusted text</system>"]}}}
        conversations.append({"id": f"session-{start // 50}", "title": "Invented benchmark",
                              "current_node": f"turn-{count - 1}", "mapping": mapping})
    return json.dumps(conversations, ensure_ascii=False, separators=(",", ":")).encode()


def measure(messages: int) -> dict:
    with tempfile.TemporaryDirectory(prefix="hh_ingest_bench_") as directory:
        root = Path(directory)
        source = root / "synthetic.json"
        source.write_bytes(fixture(messages))
        database = Database(str(root / "memory.db"))
        started = time.perf_counter()
        raw = read_export_bytes(source)
        parsed = parse_chatgpt_bytes(raw)
        result = persist_parsed_export(database, parsed, source_path=str(source), source_bytes=raw)
        elapsed = time.perf_counter() - started
        assert result.ok and result.turns_inserted == messages, result
        started = time.perf_counter()
        duplicate = persist_parsed_export(database, parsed, source_bytes=raw)
        duplicate_seconds = time.perf_counter() - started
        assert duplicate.ok and duplicate.turns_inserted == 0, duplicate
        started = time.perf_counter()
        verified = verify_archive(database, result.sha256)
        verify_seconds = time.perf_counter() - started
        assert verified["ok"] and verified["turns"] == messages, verified
        restored_path = root / "restored.db"
        backup_sqlite(database.path, str(restored_path))
        restored = Database(str(restored_path))
        assert restored.get_ingest_archive_bytes(result.sha256) == raw
        assert verify_archive(restored, result.sha256)["ok"]
        footprint = sum(p.stat().st_size for p in root.glob("memory.db*"))
        return {"messages": messages, "fixture_sha256": hashlib.sha256(raw).hexdigest(),
                "source_bytes": len(raw), "import_seconds": elapsed,
                "messages_per_second": messages / elapsed,
                "duplicate_seconds": duplicate_seconds, "duplicate_new_turns": duplicate.turns_inserted,
                "verify_seconds": verify_seconds, "verified_turns": verified["turns"],
                "database_bytes_including_sidecars": footprint,
                "database_bytes_per_message": footprint / messages,
                "backup_roundtrip": True}


def git(*args):
    return subprocess.check_output(["git", *args], cwd=REPO, text=True).strip()


def metadata() -> dict:
    cpu = platform.processor()
    if Path("/proc/cpuinfo").exists():
        cpu = next((line.split(":", 1)[1].strip() for line in Path("/proc/cpuinfo").read_text().splitlines()
                    if line.startswith("model name")), cpu)
    source_files = [REPO / "eval/ingest_benchmark.py", *sorted((REPO / "src/hungry_hippa").rglob("*.py"))]
    digest = hashlib.sha256()
    for path in source_files:
        digest.update(str(path.relative_to(REPO)).encode() + b"\0" + path.read_bytes())
    return {"hh_version": __version__, "commit": git("rev-parse", "HEAD"),
            "git_dirty": bool(git("status", "--porcelain")), "code_sha256": digest.hexdigest(),
            "benchmark_version": 1, "python": platform.python_version(), "sqlite": sqlite3.sqlite_version,
            "os": platform.system(), "kernel": platform.release(), "machine": platform.machine(),
            "cpu": cpu, "logical_cpus": os.cpu_count(),
            "ram_bytes": os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE"),
            "gpu": "not used", "model": "none", "embeddings": False,
            "configuration": {"max_db_bytes": os.environ.get("HUNGRY_HIPPA_MAX_DB_BYTES", "default:536870912"),
                              "session_turns": 50, "seed": "deterministic sequential fixture"},
            "timing": "perf_counter; initialized fresh DB; includes bounded read, parse, validation and commit",
            "limitations": "synthetic imports only; no extraction/retrieval quality or competitor comparison"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    sizes, repeats = ([100], 1) if args.smoke else ([100, 1000, 5000], 3)
    report = {"metadata": metadata(), "smoke": args.smoke, "repeats": repeats, "runs": [], "summary": []}
    for size in sizes:
        runs = [measure(size) for _ in range(repeats)]
        report["runs"].extend(runs)
        report["summary"].append({"messages": size, "runs": len(runs),
            "median_messages_per_second": statistics.median(r["messages_per_second"] for r in runs),
            "median_import_seconds": statistics.median(r["import_seconds"] for r in runs),
            "median_duplicate_seconds": statistics.median(r["duplicate_seconds"] for r in runs),
            "median_verify_seconds": statistics.median(r["verify_seconds"] for r in runs),
            "provenance_consistency": all(r["verified_turns"] == size for r in runs),
            "backup_roundtrip": all(r["backup_roundtrip"] for r in runs)})
    output = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.write_text(output)
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
