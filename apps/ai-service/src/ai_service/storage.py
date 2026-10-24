"""The AI service's database `ai` (D52, ADR-0015): stored originals and job progress; Procrastinate
keeps its queue there too."""

import hashlib
from dataclasses import dataclass
from typing import Any, Literal, LiteralString, Protocol
from uuid import UUID

import psycopg
from procrastinate.schema import SchemaManager
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

JobState = Literal[
    "queued", "parsing", "embedding", "building", "evaluating", "ready", "failed", "cancelled"
]

# Applied once each, in order. Never edit an applied one; add the next.
# shortcut: Procrastinate's schema as of 3.10; a Procrastinate upgrade adds its migration SQL here.
MIGRATIONS: list[tuple[str, LiteralString]] = [
    ("0001_procrastinate", SchemaManager.get_schema()),
    (
        "0002_source_documents",
        """
        create table source_documents (
          doc_id uuid not null,
          version int not null,
          sha256 char(64) not null,
          mime text not null,
          size_bytes int not null,
          original bytea not null,
          created_at timestamptz not null default now(),
          primary key (doc_id, version)
        );
        create table job_progress (
          job_id bigint primary key references procrastinate_jobs (id) on delete cascade,
          state text not null,
          error text,
          result jsonb,
          updated_at timestamptz not null default now()
        );
        """,
    ),
]


@dataclass(frozen=True)
class Progress:
    state: JobState
    error: str | None = None
    result: dict[str, Any] | None = None


class Store(Protocol):
    async def put_original(self, doc_id: UUID, mime: str, data: bytes) -> int:
        """The version of these bytes: the latest one if it has them, else a new one."""
        ...

    async def original(self, doc_id: UUID, version: int) -> bytes | None: ...
    async def latest_versions(self) -> dict[UUID, int]: ...
    async def delete_originals(self, doc_id: UUID) -> None: ...
    async def set_progress(self, job_id: int, progress: Progress) -> None: ...
    async def progress(self, job_id: int) -> Progress | None: ...


class MemoryStore:
    """`AI_DATABASE_URL=:memory:` (tests): the same behaviour, gone with the process."""

    def __init__(self) -> None:
        self.originals: dict[tuple[UUID, int], bytes] = {}
        self.jobs: dict[int, Progress] = {}

    async def put_original(self, doc_id: UUID, mime: str, data: bytes) -> int:
        latest = (await self.latest_versions()).get(doc_id, 0)
        if latest and self.originals[doc_id, latest] == data:
            return latest
        self.originals[doc_id, latest + 1] = data
        return latest + 1

    async def original(self, doc_id: UUID, version: int) -> bytes | None:
        return self.originals.get((doc_id, version))

    async def latest_versions(self) -> dict[UUID, int]:
        latest: dict[UUID, int] = {}
        for doc_id, version in self.originals:
            latest[doc_id] = max(version, latest.get(doc_id, 0))
        return latest

    async def delete_originals(self, doc_id: UUID) -> None:
        for key in [key for key in self.originals if key[0] == doc_id]:
            del self.originals[key]

    async def set_progress(self, job_id: int, progress: Progress) -> None:
        self.jobs[job_id] = progress

    async def progress(self, job_id: int) -> Progress | None:
        return self.jobs.get(job_id)


class PgStore:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self.pool = pool

    async def put_original(self, doc_id: UUID, mime: str, data: bytes) -> int:
        sha256 = hashlib.sha256(data).hexdigest()
        async with self.pool.connection() as conn:
            cursor = await conn.execute(
                "select version, sha256 from source_documents where doc_id = %s"
                " order by version desc limit 1",
                [doc_id],
            )
            latest = await cursor.fetchone()
            if latest and latest[1] == sha256:
                return latest[0]
            version = latest[0] + 1 if latest else 1
            await conn.execute(
                "insert into source_documents (doc_id, version, sha256, mime, size_bytes, original)"
                " values (%s, %s, %s, %s, %s, %s)",
                [doc_id, version, sha256, mime, len(data), data],
            )
            return version

    async def original(self, doc_id: UUID, version: int) -> bytes | None:
        async with self.pool.connection() as conn:
            cursor = await conn.execute(
                "select original from source_documents where doc_id = %s and version = %s",
                [doc_id, version],
            )
            row = await cursor.fetchone()
        return row[0] if row else None

    async def latest_versions(self) -> dict[UUID, int]:
        async with self.pool.connection() as conn:
            cursor = await conn.execute(
                "select doc_id, max(version) from source_documents group by doc_id"
            )
            return dict(await cursor.fetchall())

    async def delete_originals(self, doc_id: UUID) -> None:
        async with self.pool.connection() as conn:
            await conn.execute("delete from source_documents where doc_id = %s", [doc_id])

    async def set_progress(self, job_id: int, progress: Progress) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                "insert into job_progress (job_id, state, error, result) values (%s, %s, %s, %s)"
                " on conflict (job_id) do update set state = excluded.state,"
                " error = excluded.error, result = excluded.result, updated_at = now()",
                [
                    job_id,
                    progress.state,
                    progress.error,
                    progress.result and Jsonb(progress.result),
                ],
            )

    async def progress(self, job_id: int) -> Progress | None:
        async with self.pool.connection() as conn:
            cursor = await conn.execute(
                "select state, error, result from job_progress where job_id = %s", [job_id]
            )
            row = await cursor.fetchone()
        return Progress(*row) if row else None


async def ensure_database(url: str) -> None:
    """Create the database if it is missing, so an existing Postgres volume needs no reset."""
    name = conninfo_to_dict(url)["dbname"]
    server = make_conninfo(url, dbname="postgres")
    async with await psycopg.AsyncConnection.connect(server, autocommit=True) as conn:
        cursor = await conn.execute("select 1 from pg_database where datname = %s", [name])
        if not await cursor.fetchone():
            await conn.execute(sql.SQL("create database {}").format(sql.Identifier(str(name))))


async def migrate(pool: AsyncConnectionPool) -> None:
    async with pool.connection() as conn:
        # One process at a time: the API and `kb-admin` may start together.
        await conn.execute("select pg_advisory_xact_lock(hashtext('ai-migrations'))")
        await conn.execute(
            "create table if not exists schema_migrations"
            " (name text primary key, applied_at timestamptz not null default now())"
        )
        cursor = await conn.execute("select name from schema_migrations")
        applied = {name for (name,) in await cursor.fetchall()}
        for name, statements in MIGRATIONS:
            if name not in applied:
                await conn.execute(statements)
                await conn.execute("insert into schema_migrations (name) values (%s)", [name])
