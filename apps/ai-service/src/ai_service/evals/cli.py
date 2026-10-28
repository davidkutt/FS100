"""`kb-eval retrieval | agent | redteam | routing`.

Run from `apps/ai-service` (as the `pnpm eval:*` scripts do); default paths are relative to it.
"""

import argparse
import logging
import warnings

from ai_service.core.settings import Settings
from ai_service.evals import agent, retrieval, routing


def main() -> None:
    settings = Settings()
    parser = argparse.ArgumentParser(prog="kb-eval", description="Grove evaluation harness")
    commands = parser.add_subparsers(dest="command", required=True)
    retrieval.add_command(commands, settings)
    agent.add_commands(commands, settings)
    routing.add_command(commands, settings)
    args = parser.parse_args()
    warnings.filterwarnings("ignore", "Payload indexes have no effect in the local Qdrant")
    logging.getLogger("httpx2").setLevel(logging.WARNING)  # one line per request drowns the report
    args.run(args)
