"""`pnpm contracts:generate`: writes the OpenAPI document, SSE event schemas included (D14)."""

import json
import sys
from pathlib import Path

from pydantic.json_schema import models_json_schema

from ai_service.agent import (
    AgentDoneEvent,
    ApprovalRequiredEvent,
    RouteEvent,
    StepEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from ai_service.main import app
from ai_service.rag import DoneEvent, ErrorEvent, SourcesEvent, TokenEvent

V1_EVENTS = (SourcesEvent, TokenEvent, DoneEvent, ErrorEvent)
# plan-phase-2 §7.3
V2_EVENTS = (
    RouteEvent,
    StepEvent,
    ToolCallEvent,
    ToolResultEvent,
    ApprovalRequiredEvent,
    AgentDoneEvent,
)


def main() -> None:
    openapi = app.openapi()
    # OpenAPI cannot describe SSE payloads, so they ride along as plain component schemas.
    _, events = models_json_schema(
        [(model, "serialization") for model in (*V1_EVENTS, *V2_EVENTS)],
        ref_template="#/components/schemas/{model}",
    )
    openapi["components"]["schemas"].update(events["$defs"])
    Path(sys.argv[1]).write_text(json.dumps(openapi, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
