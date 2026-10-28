"""`kb-admin backfill-originals | reindex`, run from `apps/ai-service` with the repo's `.env` (as
the `pnpm kb:*` scripts do). A re-index is queued for the AI service's worker: it has the model."""

import argparse
import asyncio
import getpass
import hashlib
import mimetypes
from pathlib import Path

from qdrant_client import QdrantClient

from ai_service.core.settings import Settings
from ai_service.jobs import REINDEX, defer, job_status, open_jobs, rollback
from ai_service.knowledge_base import first_chunks
from ai_service.reindex import ReindexReport, summary
from ai_service.storage import Store


async def backfill(client: QdrantClient, alias: str, store: Store, corpus: Path) -> list[str]:
    """Stores the original of each indexed document that has none, found in `corpus` by its
    SHA-256; returns the documents left without one."""
    files = _by_sha256(corpus)
    stored = await store.latest_versions()
    missing: list[str] = []
    for doc_id, payload in first_chunks(client, alias).items():
        if doc_id in stored:
            continue
        found = files.get(payload.get("sha256", ""))
        if found is None:
            missing.append(f"{payload['filename']} ({doc_id})")
            continue
        mime = mimetypes.guess_type(found[0])[0] or "application/octet-stream"
        await store.put_original(doc_id, mime, found[1])
        print(f"stored {payload['filename']} ({doc_id})")
    return missing


def _by_sha256(corpus: Path) -> dict[str, tuple[str, bytes]]:
    files = (path for path in corpus.rglob("*") if path.is_file())
    return {hashlib.sha256(data := f.read_bytes()).hexdigest(): (f.name, data) for f in files}


async def _run(args: argparse.Namespace, settings: Settings) -> int:
    client = QdrantClient(settings.qdrant_url, api_key=settings.qdrant_api_key)
    async with open_jobs(settings.ai_database_url) as (jobs, store):
        if args.command == "backfill-originals":
            for line in await backfill(client, settings.qdrant_alias, store, args.corpus):
                print(f"no local source: {line}; upload it again or re-fetch its URL")
            return 0
        if args.rollback:
            try:
                collection = await rollback(jobs, store, client, settings.qdrant_alias)
            except LookupError as error:
                print(error)
                return 1
            print(f"{settings.qdrant_alias} → {collection}")
            return 0
        requested_by = f"cli:{getpass.getuser()}"
        job_id = await defer(
            jobs, REINDEX, reason=args.reason, force=args.force, requested_by=requested_by
        )
        print(f"Re-index job {job_id} queued; the AI service's worker runs it (`pnpm dev ai`).")
        state = None
        while (status := await job_status(jobs, store, job_id)) and status.state != "ready":
            if status.state != state:
                state = status.state
                print(state, flush=True)
            if state in ("failed", "cancelled"):
                print(status.error or "")
                return 1
            await asyncio.sleep(2)
        report = status.result if status else None
        if not isinstance(report, ReindexReport):
            return 1
        print(summary(report))
        return int(report.decision == "kept")


def main() -> None:
    parser = argparse.ArgumentParser(prog="kb-admin", description="Grove knowledge base admin")
    commands = parser.add_subparsers(dest="command", required=True)
    backfill_cmd = commands.add_parser(
        "backfill-originals", help="store originals of documents indexed before Phase 3 (D52)"
    )
    backfill_cmd.add_argument("--corpus", type=Path, default=Path("../../data/sample-docs"))
    reindex_cmd = commands.add_parser(
        "reindex", help="build from the originals, gate on the golden set, swap the alias (D55)"
    )
    reindex_cmd.add_argument("--reason", default="")
    reindex_cmd.add_argument("--force", action="store_true", help="swap despite the gate")
    reindex_cmd.add_argument("--rollback", action="store_true", help="re-point the alias back")
    args = parser.parse_args()
    if args.command == "reindex" and args.force and not args.reason.strip():
        parser.error("--force needs --reason")
    raise SystemExit(asyncio.run(_run(args, Settings())))
