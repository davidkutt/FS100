#!/bin/bash
# SessionStart hook for Claude Code cloud sessions: provides the toolchain from
# docs/setup/installation.md (Node 24 + pnpm via Corepack, uv + Python 3.13) and installs
# all project dependencies, so lint and tests work right away. Idempotent; local sessions skip it.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
export COREPACK_ENABLE_DOWNLOAD_PROMPT=0
persist() { [ -n "${CLAUDE_ENV_FILE:-}" ] && echo "$1" >> "$CLAUDE_ENV_FILE"; return 0; }

# --- Node 24 (.nvmrc) ---------------------------------------------------------------------
want_node="$(cat .nvmrc)"
if [ "$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || true)" != "$want_node" ]; then
  export NVM_DIR="${NVM_DIR:-$([ -d /opt/nvm ] && echo /opt/nvm || echo "$HOME/.nvm")}"
  if [ ! -s "$NVM_DIR/nvm.sh" ]; then
    echo "session-start: Node $want_node is required, but neither it nor nvm is available" >&2
    exit 1
  fi
  set +u
  # shellcheck source=/dev/null
  . "$NVM_DIR/nvm.sh"
  nvm install "$want_node" >/dev/null
  node_bin="$(dirname "$(nvm which "$want_node")")"
  set -u
  export PATH="$node_bin:$PATH"
  persist "export PATH=\"$node_bin:\$PATH\""
fi
persist "export COREPACK_ENABLE_DOWNLOAD_PROMPT=0"

# --- pnpm (package.json#packageManager) + Node deps ----------------------------------------
corepack enable pnpm
pnpm install --frozen-lockfile

# --- uv + Python deps (Python 3.13 is fetched by uv if missing) ----------------------------
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
  persist "export PATH=\"\$HOME/.local/bin:\$PATH\""
fi
uv sync --locked --directory apps/ai-service
# pyright downloads its Node bundle on first use; do it now so the container cache keeps it.
uv run --directory apps/ai-service pyright --version >/dev/null

echo "session-start: node $(node --version), pnpm $(pnpm --version), $(uv --version)"
