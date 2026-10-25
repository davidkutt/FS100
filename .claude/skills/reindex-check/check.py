"""Upload → job states → re-index gate → rollback on throwaway state: API :3001 + AI :8001, databases
app_reindex_check / ai_reindex_check, Qdrant alias kb_reindex_check. Removes only what it created.

uv run --directory apps/ai-service python ../../.claude/skills/reindex-check/check.py [OUT_DIR]

LIVE_SPARSE_MODEL=none: the uploads build a collection with that sparse side, then the AI service
restarts with SPARSE_MODEL from .env, so the re-index gate compares the two (an upgrade, M3a.2).
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx2
import psycopg
from qdrant_client import QdrantClient

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp())
CORPUS = ROOT / "data/sample-docs"
ALIAS = "kb_reindex_check"


def dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = re.split(r"\s+#", value, maxsplit=1)[0].strip()
    return values


env_file = dotenv(ROOT / ".env")
PW = env_file.get("POSTGRES_PASSWORD", "dev-only-change-me")
USER = env_file.get("POSTGRES_USER", "postgres")
PG = f"postgresql://{USER}:{PW}@localhost:5432"
overrides = {
    "QDRANT_ALIAS": ALIAS,
    "AI_DATABASE_URL": f"{PG}/ai_reindex_check",
    "API_DATABASE_URL": f"{PG}/app_reindex_check",
    "AI_SERVICE_URL": "http://localhost:8001",
    "AI_API_URL": "http://localhost:3001",
    "API_PORT": "3001",
    "LLM_PROVIDER": "fake",
    "OTEL_EXPORTER_OTLP_ENDPOINT": "",
    "LOG_LEVEL": "warn",
}
env = {**os.environ, **env_file, **overrides}
qdrant = QdrantClient("http://localhost:6333")
before = {c.name for c in qdrant.get_collections().collections}
assert not qdrant.collection_exists(ALIAS), "check alias exists already"


def sql(statement: str, db: str = "postgres") -> list[tuple[object, ...]]:
    with psycopg.connect(f"{PG}/{db}", autocommit=True) as conn:
        cursor = conn.execute(statement)  # type: ignore[arg-type]
        return cursor.fetchall() if cursor.description else []


def login(user: str) -> dict[str, str]:
    token = subprocess.check_output([".claude/skills/user-token/login.sh", user], cwd=ROOT, text=True)
    return {"authorization": f"Bearer {token.strip()}"}


def wait(url: str, seconds: float = 300) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if httpx2.get(url, timeout=2).status_code == 200:
                return
        except httpx2.HTTPError:
            pass
        time.sleep(1)
    raise TimeoutError(url)


peak = {"rss_kb": 0}


def sample(pid: int, stop: threading.Event) -> None:
    while not stop.is_set():
        out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True)
        if out.stdout.strip():
            peak["rss_kb"] = max(peak["rss_kb"], int(out.stdout.strip()))
        time.sleep(0.25)


def start_ai(extra: dict[str, str]) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [str(ROOT / "apps/ai-service/.venv/bin/uvicorn"), "ai_service.main:app", "--port", "8001"],
        cwd=ROOT / "apps/ai-service",
        env={**env, **extra},
        stdout=open(OUT / "ai.log", "a"),
        stderr=subprocess.STDOUT,
    )


live_sparse = os.environ.get("LIVE_SPARSE_MODEL")
sql("create database app_reindex_check")
ai = api = None
stop = threading.Event()
try:
    ai = start_ai({"SPARSE_MODEL": live_sparse} if live_sparse else {})
    api = subprocess.Popen(
        ["node", "dist/main.js"],
        cwd=ROOT / "apps/api",
        env=env,
        stdout=open(OUT / "api.log", "w"),
        stderr=subprocess.STDOUT,
    )
    wait("http://localhost:8001/readyz")
    wait("http://localhost:3001/readyz")
    sampler = threading.Thread(target=sample, args=(ai.pid, stop), daemon=True)
    sampler.start()
    idle_kb = int(subprocess.check_output(["ps", "-o", "rss=", "-p", str(ai.pid)], text=True))
    print(f"AI idle RSS {idle_kb / 1e6:.2f} GB")

    bob = login("bob")
    manifest: dict[str, list[str]] = json.loads((CORPUS / "domains.json").read_text())
    ids: dict[str, str] = {}
    started = time.monotonic()
    for name, domains in manifest.items():
        response = httpx2.post(
            "http://localhost:3001/api/documents",
            headers=bob,
            files={"file": (name, (CORPUS / name).read_bytes())},
            data={"domains": domains},
            timeout=60,
        )
        assert response.status_code == 202, response.text
        ids[response.json()["id"]] = name
    pdf_states: list[str] = []
    while True:
        docs = [d for d in httpx2.get("http://localhost:3001/api/documents", headers=bob).json() if d["id"] in ids]
        pdf = next(d for d in docs if d["filename"] == "slo-handbook.pdf")
        if not pdf_states or pdf_states[-1] != pdf["status"]:
            pdf_states.append(pdf["status"])
        if all(d["status"] in ("ready", "failed") for d in docs):
            break
        time.sleep(0.2)
    failed = [(d["filename"], d["error"]) for d in docs if d["status"] == "failed"]
    print(f"ingest of {len(docs)} docs via the queue: {time.monotonic() - started:.0f} s; failed: {failed}")
    print(f"PDF states seen: {' → '.join(pdf_states)}; chunks {sum(d['chunkCount'] or 0 for d in docs)}")
    print(f"AI peak RSS during ingest {peak['rss_kb'] / 1e6:.2f} GB")
    if live_sparse:
        ai.terminate()
        ai.wait(30)
        ai = start_ai({})
        wait("http://localhost:8001/readyz")
        sampler = threading.Thread(target=sample, args=(ai.pid, stop), daemon=True)
        sampler.start()
        print(f"AI restarted with SPARSE_MODEL={env.get('SPARSE_MODEL', 'the default')}")

    started = time.monotonic()
    cli = subprocess.run(
        ["uv", "run", "kb-admin", "reindex", "--reason", "reindex-check (CLI)"],
        cwd=ROOT / "apps/ai-service",
        env=env,
        capture_output=True,
        text=True,
    )
    print(f"--- kb-admin reindex (exit {cli.returncode}, {time.monotonic() - started:.0f} s)")
    print("\n".join(line for line in cli.stdout.splitlines()))
    print(f"AI peak RSS so far {peak['rss_kb'] / 1e6:.2f} GB")

    alice = login("alice")  # tokens live 5 minutes: log in right before each phase
    started_api = httpx2.post(
        "http://localhost:3001/api/admin/reindex", headers=alice, json={"reason": "reindex-check (API)"}
    )
    print("admin POST /api/admin/reindex:", started_api.status_code, started_api.text)
    editor = httpx2.post("http://localhost:3001/api/admin/reindex", headers=login("bob"), json={})
    print("editor POST /api/admin/reindex (expect 403):", editor.status_code)
    while True:  # a build takes under the token's 5 minutes
        status = httpx2.get("http://localhost:3001/api/admin/reindex", headers=alice, timeout=30).json()
        run = status["runs"][0]
        if run["state"] in ("ready", "failed", "cancelled"):
            break
        time.sleep(1)
    report = run["report"] or {}
    print(f"API run {run['id']}: {run['state']} by {run['requested_by']} → {report.get('decision')}, "
          f"blockers {report.get('blockers')}, alias → {status['collection']}")

    alice = login("alice")
    started = time.monotonic()
    rolled = httpx2.post("http://localhost:3001/api/admin/reindex/rollback", headers=alice, timeout=60)
    print(f"rollback via API: {rolled.status_code} {rolled.text} in {time.monotonic() - started:.2f} s")
    started = time.monotonic()
    cli_rollback = subprocess.run(
        ["uv", "run", "kb-admin", "reindex", "--rollback"],
        cwd=ROOT / "apps/ai-service", env=env, capture_output=True, text=True,
    )
    print(f"rollback via CLI: {cli_rollback.stdout.strip()} in {time.monotonic() - started:.2f} s")
    audit = sql("select actor_id, tool, args_redacted::text from audit_log where tool like 'kb.%' order by id", "app_reindex_check")
    print("audit:", audit)
    print(f"AI peak RSS overall {peak['rss_kb'] / 1e6:.2f} GB")
finally:
    stop.set()
    for proc in (api, ai):
        if proc:
            proc.terminate()
            try:
                proc.wait(30)
            except subprocess.TimeoutExpired:
                proc.kill()
    if qdrant.collection_exists(ALIAS):
        from qdrant_client import models

        qdrant.update_collection_aliases(
            change_aliases_operations=[models.DeleteAliasOperation(delete_alias=models.DeleteAlias(alias_name=ALIAS))]
        )
    created = {c.name for c in qdrant.get_collections().collections} - before
    for name in created:
        qdrant.delete_collection(name)
    sql("drop database if exists app_reindex_check with (force)")
    sql("drop database if exists ai_reindex_check with (force)")
    print(f"cleaned up: alias {ALIAS}, collections {sorted(created)}, both databases; logs in {OUT}")
