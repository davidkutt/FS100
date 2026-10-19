# Installation guide — local development toolchain

This guide installs everything you need to develop FS100 on your own machine. The primary target is a
**MacBook with Apple Silicon (M1)**; Linux and Windows (WSL2) are covered as well.

Once the toolchain is in place, continue with the **[startup guide](startup.md)**.

---

## 1. What you need — and what you don't

You install **five tools** on the host. Everything else is either a project dependency (installed by
`pnpm install` / `uv sync`) or runs in Docker.

| Tool | Version | Why | Pinned in |
|---|---|---|---|
| **Git** | ≥ 2.40 | Source control | — |
| **Node.js** | **24 LTS** (≥ 24.15) | Runtime for the Angular and NestJS apps and the root scripts | `.nvmrc`, `package.json#engines` |
| **pnpm** | **12.11.2** (via Corepack) | Workspace package manager for `apps/web` + `apps/api` | `package.json#packageManager` |
| **uv** | ≥ 0.11 | Python package/project manager; also installs Python itself | — |
| **Python** | **3.13** (installed by uv) | Runtime for the AI service | `.python-version`, `apps/ai-service/pyproject.toml` |
| **Docker** + Compose v2 | Engine ≥ 25, Compose ≥ 2.24 | Runs Postgres, Qdrant, Keycloak, Phoenix | `infra/compose/docker-compose.yml` |

**Do not install globally:** Angular CLI, Nest CLI, TypeScript, ESLint, Prettier, ruff, pyright, pytest.
They are project dev-dependencies, versioned in the lockfiles, and invoked through `pnpm` / `uv run`
(see [§6](#6-per-technology-notes)). **Do not install** Postgres, Keycloak, Qdrant or Phoenix natively —
they run as containers with a fixed port map.

**Optional, needed later:**

| Tool | Needed in | Purpose |
|---|---|---|
| OpenRouter account + API key **with a credit limit** | M1.3 | LLM calls (`LLM_API_KEY`); or use `LLM_PROVIDER=fake` |
| Hugging Face token | M1.3 (optional) | Alternative LLM router (`https://router.huggingface.co/v1`) |
| Azure CLI (`az`) | M1.7 | Azure readiness spike (budget, quota, ACR) |
| GitHub CLI (`gh`) | any | PRs, Actions runs from the terminal |
| `psql` client | any | Poke at the `app` / `keycloak` databases (or use `docker exec`) |
| lefthook | any | Optional lint-on-commit hooks |

---

## 2. macOS (Apple Silicon)

### 2.1 Base tools

```bash
# Apple command line tools (git, compilers) — skip if already installed
xcode-select --install

# Homebrew (https://brew.sh) — skip if already installed
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

brew install git
```

### 2.2 Node.js 24 LTS

Use a version manager so the repo's `.nvmrc` selects the right Node automatically. Pick **one**:

```bash
# Option A: fnm (fast, Rust) — recommended
brew install fnm
echo 'eval "$(fnm env --use-on-cd --shell zsh)"' >> ~/.zshrc && exec zsh
fnm install 24 && fnm default 24

# Option B: nvm
brew install nvm   # then follow the caveats printed by brew to add nvm to ~/.zshrc
nvm install 24 && nvm alias default 24
```

Inside the repo, `fnm use` / `nvm use` reads `.nvmrc` (`24`).

> Node 24 is the Active LTS line. Node 26 enters LTS on 28 Oct 2026 — the plan re-evaluates it then (D2).

### 2.3 pnpm via Corepack

Corepack ships with Node 24 and installs exactly the pnpm version pinned in `package.json#packageManager`:

```bash
corepack enable pnpm
cd FS100 && pnpm --version     # -> 12.11.2 (downloaded on first use)
```

If `corepack enable` fails with a permissions error (Node installed system-wide), use
`sudo corepack enable pnpm` or switch to fnm/nvm. Do **not** `npm install -g pnpm` — a global pnpm can
drift from the pinned version.

### 2.4 uv and Python 3.13

```bash
brew install uv                # or: curl -LsSf https://astral.sh/uv/install.sh | sh
uv python install 3.13         # uv-managed CPython, independent of the macOS system Python
```

You never activate a virtualenv by hand: `uv sync` creates `apps/ai-service/.venv`, and `uv run …` uses it.

### 2.5 Docker

Pick **one** container runtime. All images used by FS100 are multi-arch, so they run natively on arm64
(no Rosetta emulation).

| Option | Notes |
|---|---|
| **Docker Desktop** | Official, GUI. Free for personal use / small companies. Includes Compose v2. |
| **OrbStack** | Lightweight, fast, low RAM use — very good on M1 machines. Drop-in `docker` CLI. |
| **Colima** | Open source, CLI only: `brew install colima docker docker-compose && colima start --cpu 4 --memory 6` |

**Memory:** give the Docker VM **at least 4 GB, better 6 GB** (Docker Desktop → Settings → Resources).
Measured idle usage of the Phase 1 infra:

| Container | Idle RAM | Image size |
|---|---|---|
| Keycloak 26.x | ~700 MB | ~750 MB |
| Phoenix 20.x | ~450 MB | ~1.4 GB |
| Postgres 17 | ~60 MB | ~650 MB |
| Qdrant 1.x | ~25 MB (grows with vectors) | ~270 MB |

The native dev servers (Angular, Nest, FastAPI) need another ~1–1.5 GB, and the embedding model in the
AI service (M1.2) another 0.5–2.5 GB depending on the model. On a 16 GB Mac that fits comfortably; on 8 GB
see plan.md A1 (Mode A only, `e5-small`).

---

## 3. Linux (Ubuntu / Debian)

```bash
sudo apt-get update && sudo apt-get install -y git curl ca-certificates

# Node 24 via fnm
curl -fsSL https://fnm.vercel.app/install | bash
exec $SHELL
fnm install 24 && fnm default 24
corepack enable pnpm

# uv + Python 3.13
curl -LsSf https://astral.sh/uv/install.sh | sh
uv python install 3.13

# Docker Engine + Compose plugin: follow https://docs.docker.com/engine/install/ubuntu/
# then allow your user to talk to the daemon:
sudo usermod -aG docker "$USER" && newgrp docker
docker compose version
```

## 4. Windows

Use **WSL2** (Ubuntu) and follow the Linux steps *inside* WSL. Install **Docker Desktop for Windows** with
the WSL2 backend and enable integration for your distro. Clone the repo into the WSL filesystem
(`~/code/FS100`), **not** under `/mnt/c/…` — file watching and I/O are much slower across the boundary.

---

## 5. Verify the toolchain

Run inside the cloned repo:

```bash
git --version            # git version 2.40+
node --version           # v24.x
pnpm --version           # 12.11.2
uv --version             # uv 0.11+
uv python find 3.13      # path to a CPython 3.13 interpreter
docker --version         # Docker version 25+
docker compose version   # Docker Compose version v2.24+
docker info --format '{{.Architecture}} / {{.MemTotal}}'   # aarch64 on M1; memory in bytes
```

Then install the project dependencies (also part of the [startup guide](startup.md)):

```bash
pnpm install                              # web + api (one lockfile: pnpm-lock.yaml)
uv sync --directory apps/ai-service       # ai-service (lockfile: apps/ai-service/uv.lock)
```

---

## 6. Per-technology notes

How each technology is installed and used **in this repo**. Versions are the ones pinned at M1.0
(plan.md D2); Dependabot keeps them fresh from M1.6.

### Frontend — `apps/web`

| Technology | Version | Installed by | Notes |
|---|---|---|---|
| Angular | 22.2 | `pnpm install` | Standalone components, signals, zoneless. CLI: `pnpm --filter @fs100/web ng <cmd>` |
| Bootstrap | 5.3.8 | `pnpm install` | Compiled from SCSS in `src/styles.scss` with variable overrides; no jQuery, no Bootstrap JS yet |
| Vitest | 5.x | `pnpm install` | Angular's default unit-test runner (`ng test`), DOM via jsdom |
| ESLint + angular-eslint | 10.x / 22.x | `pnpm install` | `ng lint`, includes template accessibility rules |
| TypeScript | 6.0 | `pnpm install` (catalog) | Angular 22 requires `>=6.0 <6.1` |

### API — `apps/api`

| Technology | Version | Installed by | Notes |
|---|---|---|---|
| NestJS | 12.1 | `pnpm install` | ESM (`"type": "module"`, `.js` import suffixes). CLI: `pnpm --filter @fs100/api exec nest <cmd>` |
| Vitest + supertest | 5.x / 7.x | `pnpm install` | Unit tests in `src/**/*.spec.ts`, HTTP tests in `test/*.e2e-spec.ts` |
| oxlint | 1.x | `pnpm install` | Nest 12's default linter, type-aware via `oxlint-tsgolint` |
| Express | 5 | `pnpm install` | Via `@nestjs/platform-express` |

### AI service — `apps/ai-service`

| Technology | Version | Installed by | Notes |
|---|---|---|---|
| Python | 3.13 | `uv python install` | `requires-python = ">=3.13,<3.14"` |
| FastAPI + Uvicorn | 0.143 / 0.54 | `uv sync` | `uvicorn ai_service.main:app --reload` (started by `pnpm dev`) |
| pydantic-settings | 2.15 | `uv sync` | Settings from the process environment (`core/settings.py`) |
| ruff | 0.17 | `uv sync` (dev group) | Lint + format: `uv run ruff check .`, `uv run ruff format .` |
| pyright | 1.1.414 | `uv sync` (dev group) | Strict mode. **First run downloads a Node-based pyright bundle** (needs network once) |
| pytest + httpx2 | 9.1 / 2.13 | `uv sync` (dev group) | `fastapi.testclient.TestClient` uses `httpx2` (Starlette deprecated plain `httpx` for it) |

Coming with later milestones (not installed yet): `qdrant-client` 1.18 + `fastembed` (M1.2), `openai`
SDK + OpenInference/OpenTelemetry (M1.1/M1.3), `pypdf` (M1.2), Drizzle + `jose` + Zod in the API (M1.1/M1.4),
`keycloak-js` + `keycloak-angular` in the web app (M1.1).

### Infrastructure — Docker images (`infra/compose/docker-compose.yml`)

| Service | Image | Ports (localhost only) | Notes |
|---|---|---|---|
| Postgres | `postgres:17.11` | 5432 | `infra/postgres/init.sql` creates the `keycloak` and `app` databases on first start |
| Keycloak | `quay.io/keycloak/keycloak:26.8.1` | 8080 | `start-dev --import-realm` with `infra/keycloak/realm-kb.json`; state lives in Postgres |
| Qdrant | `qdrant/qdrant:v1.19.2` | 6333 (REST, dashboard), 6334 (gRPC) | Telemetry disabled |
| Phoenix | `arizephoenix/phoenix:version-20.23.0` | 6006 (UI, OTLP/HTTP), 4317 (OTLP/gRPC) | SQLite in a named volume |

Pinned in M2.0 (`plan-phase-2.md` D47). Bump minor lines deliberately; Qdrant always together with
`qdrant-client`. Existing volumes migrate in place on the next `pnpm stack:up` (there is no downgrade).

---

## 7. pnpm 12 specifics worth knowing

- **Build scripts are opt-in.** Dependency `postinstall` scripts only run for packages listed as `true`
  under `allowBuilds` in `pnpm-workspace.yaml` (pnpm ≥ 11 replaced `onlyBuiltDependencies` with this
  map). Today only `esbuild` is allowed. If an install fails with `ERR_PNPM_IGNORED_BUILDS`, run
  `pnpm approve-builds` and commit the reviewed change.
- **Fresh releases are held back.** pnpm 12 applies a minimum release age to newly published versions. If
  you pin a version that is only hours old, pnpm adds it to `minimumReleaseAgeExclude` in
  `pnpm-workspace.yaml`. Prefer a slightly older version over committing such an exclusion.
- **Catalogs.** Shared versions (`typescript`, `vitest`, `prettier`, `@types/node`) are defined once under
  `catalog:` in `pnpm-workspace.yaml` and referenced as `"catalog:"` in the apps.

## 8. Editor setup (VS Code)

Open the repo root and accept the recommended extensions (`.vscode/extensions.json`): Angular Language
Service, ESLint, oxc, Prettier, Vitest, Python, Ruff, Container Tools, EditorConfig. For Python, select the
interpreter at `apps/ai-service/.venv` (*Python: Select Interpreter*).

## 9. Troubleshooting the installation

| Symptom | Fix |
|---|---|
| `Unsupported engine` / Angular refuses to run | Node is not 24.x — run `fnm use` / `nvm use` in the repo |
| `pnpm: command not found` after `corepack enable` | Open a new shell; with nvm, re-run `corepack enable pnpm` after every `nvm install` |
| Corepack: `Cannot find matching keyid` | Outdated Corepack: `npm install -g corepack@latest`, then `corepack enable pnpm` |
| `ERR_PNPM_IGNORED_BUILDS` | See [§7](#7-pnpm-12-specifics-worth-knowing) — approve the package with `pnpm approve-builds` |
| `uv: command not found` | Restart the shell (the installer adds `~/.local/bin` to `PATH`) |
| pyright hangs on first run | It downloads its Node bundle once; check network/proxy, or run `uv run pyright --version` to warm it up |
| `Cannot connect to the Docker daemon` | Start Docker Desktop / OrbStack / `colima start` |
| Containers get OOM-killed, Keycloak restarts | Give the Docker VM more memory (≥ 6 GB) |
