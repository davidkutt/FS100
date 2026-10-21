from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ai_service.agent import Agent
from ai_service.api.agent import get_agent, get_models
from ai_service.catalog import ModelInfo
from ai_service.core.auth import Caller, get_caller
from ai_service.tools import Risk, Role, ToolKind

router = APIRouter(prefix="/v1", tags=["catalog"])


class ToolInfo(BaseModel):
    name: str
    description: str
    kind: ToolKind
    risk: Risk
    min_role: Role


@router.get("/models")
def models(models: Annotated[dict[str, ModelInfo], Depends(get_models)]) -> list[ModelInfo]:
    """The model registry (D40); the API filters it by the caller's role."""
    return list(models.values())


@router.get("/tools")
def tools(
    agent: Annotated[Agent, Depends(get_agent)], caller: Annotated[Caller, Depends(get_caller)]
) -> list[ToolInfo]:
    """The tool registry (D30); the API filters it by the caller's role."""
    return [
        ToolInfo.model_validate(tool, from_attributes=True)
        for tool in sorted(agent.tools(None, caller), key=lambda tool: tool.name)
    ]
