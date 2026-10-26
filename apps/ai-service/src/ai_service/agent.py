import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import aclosing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi.sse import ServerSentEvent
from opentelemetry import trace
from opentelemetry.trace import StatusCode
from pydantic import BaseModel, Field, ValidationError

from ai_service import approvals, prompts, rag, routing
from ai_service.approvals import Action, ApprovalError
from ai_service.core.auth import Caller
from ai_service.core.logging import request_id
from ai_service.core.settings import Settings
from ai_service.knowledge_base import SPAN_KIND, Domain, Hit
from ai_service.llm import LlmError, LlmProvider, Message, Token, ToolCall, Usage
from ai_service.rag import (
    AnswerStatus,
    ChatPipeline,
    ChatTurn,
    DoneEvent,
    ErrorEvent,
    EventModel,
    Source,
    SourcesEvent,
    TokenEvent,
    UsageInfo,
    answer_status,
    history_messages,
    invalid_citations,
    render_source,
)
from ai_service.routing import Route, Router, RouterName
from ai_service.tools import (
    Risk,
    ToolKind,
    ToolOutput,
    ToolSpec,
    TransientToolError,
    approval_id,
    permitted,
    untrusted,
    wrap,
)

StopReason = Literal["end", "max_steps", "budget", "awaiting_approval", "cancelled", "error"]
ToolStatus = Literal["ok", "error", "denied", "rejected"]
Tools = Callable[[list[Domain] | None, Caller], Awaitable[list[ToolSpec[Any]]]]
PROMPT = prompts.load("agent-system")
TOOL_RETRIES = 2
RETRY_BACKOFF_S = 0.5
logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class RouteEvent(EventModel):
    domains: list[Domain]  # the turn's default search filter; [] = none
    tool_groups: list[str]  # namespaces of the offered tools, e.g. kb, github
    router: RouterName
    confidence: float


class StepEvent(EventModel):
    n: int


class ToolCallEvent(EventModel):
    id: str
    name: str
    kind: ToolKind
    risk: Risk
    args: Any  # as the model sent them, parsed when valid JSON
    service_identity: str | None  # the credential it runs with, unless the user's own (D37)


class ToolResultEvent(EventModel):
    id: str
    status: ToolStatus
    summary: str
    content: str  # exactly what the model saw
    truncated: bool
    duration_ms: int


class ApprovalRequiredEvent(EventModel):
    approval_id: UUID
    call_id: str
    tool: str
    args: dict[str, Any]  # validated, exactly what runs once approved
    risk: Risk
    expires_at: datetime
    signed_action: str  # NestJS stores it and strips it before the browser (D29)


class Resume(BaseModel):
    """The user's decision on an `approval_required` action (D28)."""

    signed_action: str
    decision: Literal["approve", "reject"]
    note: str | None = Field(None, max_length=2000)
    args: dict[str, Any]  # as shown to the user; must match the signed hash


@dataclass(frozen=True)
class Resumed:
    action: Action
    spec: ToolSpec[Any]
    args: BaseModel
    decision: Literal["approve", "reject"]
    note: str | None


class AgentUsage(EventModel):
    input_tokens: int
    cached_tokens: int
    output_tokens: int
    cost_usd: float | None
    steps: int
    tool_calls: int


class AgentDoneEvent(EventModel):
    stop_reason: StopReason
    answer_status: AnswerStatus
    top_score: float | None
    usage: AgentUsage
    model: str | None
    prompt_version: str
    prompt_hash: str
    trace_id: str | None
    protocol_version: Literal[2] = 2


@dataclass
class _Outcome:
    status: ToolStatus
    output: ToolOutput
    duration_ms: int = 0


class _Sources:
    """Numbers stay stable for the whole turn, so `[n]` stays valid across searches; a section
    found through another of its chunks keeps its number (D59)."""

    def __init__(self) -> None:
        self.by_section: dict[str, Source] = {}
        self.top_score: float | None = None
        self.searched = False

    def render(self, hits: list[Hit]) -> str:
        self.searched = True
        rendered: list[str] = []
        for hit in hits:
            self.top_score = max(hit.score, self.top_score or hit.score)
            key = hit.parent_id or hit.chunk_id
            if key not in self.by_section:
                n = len(self.by_section) + 1
                self.by_section[key] = Source.model_validate({"n": n, **hit.model_dump()})
            rendered.append(render_source(self.by_section[key].n, hit))
        return "".join(rendered) or "No matching sources."


def _sse(event: str, data: BaseModel) -> ServerSentEvent:
    return ServerSentEvent(event=event, data=data)


def _error(type_: str, title: str, detail: str) -> ServerSentEvent:
    return _sse("error", ErrorEvent(type=type_, title=title, detail=detail))


def _failed(status: ToolStatus, message: str) -> _Outcome:
    return _Outcome(status, ToolOutput(f"Error: {message}", message))


def _parsed(arguments: str) -> Any:
    try:
        return json.loads(arguments)
    except ValueError:
        return arguments


def _assistant(text: str | None, calls: list[ToolCall]) -> Message:
    return {
        "role": "assistant",
        "content": text,
        "tool_calls": [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.arguments},
            }
            for call in calls
        ],
    }


def _routed(tool: ToolSpec[Any], route: Route) -> bool:
    """Low confidence offers every tool (D33)."""
    if not route.confident:
        return True
    return route.needs_tools and (not tool.domains or bool(set(tool.domains) & set(route.domains)))


def _call_event(call: ToolCall, spec: ToolSpec[Any]) -> ServerSentEvent:
    return _sse(
        "tool_call",
        ToolCallEvent(
            id=call.id,
            name=spec.name,
            kind=spec.kind,
            risk=spec.risk,
            args=_parsed(call.arguments),
            service_identity=spec.service_identity,
        ),
    )


def _observe(
    call: ToolCall,
    spec: ToolSpec[Any] | None,
    outcome: _Outcome,
    sources: _Sources,
    messages: list[Message],
) -> ServerSentEvent | None:
    """Appends the observation for the model; a `tool_result` event for registered tools."""
    if outcome.output.hits is not None:
        content = sources.render(outcome.output.hits)
    else:
        content = untrusted(outcome.output.content)
    budget = spec.result_budget_tokens if spec else 100
    name = spec.name if spec else "unknown"  # call.name is model-controlled
    block, truncated = wrap(name, outcome.status, content, budget)
    messages.append({"role": "tool", "tool_call_id": call.id, "content": block})
    if spec is None:
        return None
    return _sse(
        "tool_result",
        ToolResultEvent(
            id=call.id,
            status=outcome.status,
            summary=outcome.output.summary,
            content=block,
            truncated=truncated,
            duration_ms=outcome.duration_ms,
        ),
    )


async def _attempts(spec: ToolSpec[Any], args: BaseModel) -> ToolOutput:
    for attempt in range(TOOL_RETRIES):
        try:
            return await spec.run(args)
        except (TransientToolError, ConnectionError) as error:
            logger.warning("tool %s: %s, retry %d", spec.name, error, attempt + 1)
            await asyncio.sleep(RETRY_BACKOFF_S * 2**attempt)
    return await spec.run(args)


class Agent:
    """Own tool loop on the LlmProvider (D27); every limit ends the run with a `stopReason`."""

    def __init__(self, llm: LlmProvider, settings: Settings, tools: Tools, router: Router) -> None:
        self.llm = llm
        self.settings = settings
        self.tools = tools
        self.router = router
        self.system_prompt = PROMPT.text.format(
            repo=settings.github_repo or "(none)", sandbox=settings.github_sandbox_repo or "(none)"
        )

    async def stream(
        self,
        turns: list[ChatTurn],
        domains: list[Domain] | None,
        caller: Caller,
        conversation_id: UUID,
        model_id: str | None = None,
        resume: Resumed | None = None,
    ) -> AsyncGenerator[ServerSentEvent]:
        settings = self.settings
        *history, question = turns
        # Stable prefix first (system, sorted tools), so providers can cache it (D41).
        messages: list[Message] = [
            {"role": "system", "content": self.system_prompt},
            *history_messages(history),
            {"role": "user", "content": question.content},
        ]
        deadline = time.monotonic() + settings.agent_run_timeout_s
        semaphore = asyncio.Semaphore(settings.agent_max_parallel_tools)
        usage = AgentUsage(
            input_tokens=0, cached_tokens=0, output_tokens=0, cost_usd=None, steps=0, tool_calls=0
        )
        sources = _Sources()
        answer: list[str] = []
        model: str | None = None
        stop: StopReason = "end"
        limit: str | None = None
        attributes = {
            SPAN_KIND: "AGENT",
            "gen_ai.operation.name": "invoke_agent",
            "input.value": question.content,
            "user.id": caller.sub,
            "session.id": str(conversation_id),
            "llm.prompt_template.version": PROMPT.ref,
            "prompt.hash": PROMPT.hash,
        }
        with tracer.start_as_current_span("agent.run", attributes=attributes) as span:
            try:
                route = await self._route(question.content, domains)
                if route.usage:
                    usage.input_tokens += route.usage.input_tokens
                    usage.output_tokens += route.usage.output_tokens
                    usage.cost_usd = route.usage.cost_usd
                default = (route.domains or None) if route.confident else None
                tools = sorted(await self.tools(default, caller), key=lambda tool: tool.name)
                by_name = {tool.wire_name: tool for tool in tools if tool.available}
                routed = [
                    tool
                    for tool in by_name.values()
                    if permitted(tool.min_role, caller.roles) and _routed(tool, route)
                ]
                offered = [tool.definition() for tool in routed]
                yield _sse(
                    "route",
                    RouteEvent(
                        domains=default or [],
                        tool_groups=sorted({tool.group for tool in routed}),
                        router=route.router,
                        confidence=round(route.confidence, 3),
                    ),
                )
                if resume:
                    # The approved call continues the turn that proposed it (ADR-0008).
                    call = ToolCall(
                        resume.action.call_id, resume.spec.wire_name, resume.args.model_dump_json()
                    )
                    messages.append(_assistant(None, [call]))
                    usage.tool_calls += 1
                    yield _call_event(call, resume.spec)
                    outcome = await self._decided(call, resume, caller.roles, deadline, semaphore)
                    if event := _observe(call, resume.spec, outcome, sources, messages):
                        yield event
                for n in range(1, settings.agent_max_steps + 1):
                    if limit := self._exceeded(usage, deadline):
                        stop = "budget"
                        break
                    usage.steps = n
                    yield _sse("step", StepEvent(n=n))
                    text: list[str] = []
                    calls: list[ToolCall] = []
                    error: str | None = None
                    llm_attributes = {
                        SPAN_KIND: "LLM",
                        "llm.prompt_template.version": PROMPT.ref,
                        "prompt.hash": PROMPT.hash,
                    }
                    with tracer.start_as_current_span("llm", attributes=llm_attributes) as llm_span:
                        events = self.llm.stream_chat(
                            messages, offered, str(conversation_id), model_id
                        )
                        # aclosing: a client disconnect closes the provider stream (D27).
                        async with aclosing(events) as events:
                            async for event in events:
                                match event:
                                    case Token(text=token):
                                        text.append(token)
                                        yield _sse("token", TokenEvent(text=token))
                                    case ToolCall():
                                        calls.append(event)
                                    case Usage():
                                        model = event.model
                                        llm_span.set_attribute("llm.model_name", event.model)
                                        usage.input_tokens += event.input_tokens
                                        usage.cached_tokens += event.cached_tokens
                                        usage.output_tokens += event.output_tokens
                                        if event.cost_usd is not None:
                                            usage.cost_usd = (usage.cost_usd or 0) + event.cost_usd
                                    case LlmError(detail=detail):
                                        error = detail
                                if time.monotonic() > deadline:
                                    limit = "wall_clock"
                                    break
                    answer.extend(text)
                    if error is not None:
                        span.set_status(StatusCode.ERROR, error)
                        yield _error("llm", "LLM request failed", error)
                        stop = "error"
                        break
                    if limit:
                        stop = "budget"
                        break
                    if not calls:
                        stop = "end"
                        break
                    if n == settings.agent_max_steps:
                        stop = "max_steps"
                        break
                    messages.append(_assistant("".join(text) or None, calls))
                    for call in calls:
                        if spec := by_name.get(call.name):
                            usage.tool_calls += 1
                            yield _call_event(call, spec)
                    async with asyncio.TaskGroup() as group:
                        tasks = [
                            group.create_task(
                                self._execute(
                                    call, by_name.get(call.name), caller.roles, deadline, semaphore
                                )
                            )
                            for call in calls
                        ]
                    known_sources = len(sources.by_section)
                    proposal: ApprovalRequiredEvent | None = None
                    for call, task in zip(calls, tasks, strict=True):
                        spec = by_name.get(call.name)
                        outcome = task.result()
                        if not isinstance(outcome, _Outcome):
                            if proposal is None and spec:
                                proposal = self._propose(
                                    call, spec, outcome, caller.sub, conversation_id
                                )
                                continue
                            # shortcut: one write per step, queue approvals if models batch writes
                            outcome = _failed("error", "One write action at a time; retry later")
                        if event := _observe(call, spec, outcome, sources, messages):
                            yield event
                    if len(sources.by_section) > known_sources:
                        yield _sse("sources", SourcesEvent(sources=[*sources.by_section.values()]))
                    if proposal:
                        yield _sse("approval_required", proposal)
                        stop = "awaiting_approval"
                        break
            except (asyncio.CancelledError, GeneratorExit):
                span.set_attribute("agent.stop_reason", "cancelled")
                raise
            except Exception:
                logger.exception("agent run failed")
                span.set_status(StatusCode.ERROR)
                detail = f"See the AI service log ({request_id.get()})"
                yield _error("internal", "Agent run failed", detail)
                stop = "error"
            reply = "".join(answer)
            status = answer_status(reply, len(sources.by_section), sources.searched)
            invalid = invalid_citations(reply, len(sources.by_section))
            span.set_attributes(
                {
                    "output.value": reply,
                    "agent.stop_reason": stop,
                    "agent.limit": limit or "",
                    "agent.answer_status": status,
                    "agent.invalid_citations": invalid,
                }
            )
            logger.info(
                "agent stop=%s steps=%d tool_calls=%d input_tokens=%d cost_usd=%s",
                stop,
                usage.steps,
                usage.tool_calls,
                usage.input_tokens,
                usage.cost_usd,
            )
            context = span.get_span_context()
            done = AgentDoneEvent(
                stop_reason=stop,
                answer_status=status,
                top_score=sources.top_score,
                usage=usage,
                model=model,
                prompt_version=PROMPT.ref,
                prompt_hash=PROMPT.hash,
                trace_id=format(context.trace_id, "032x") if context.is_valid else None,
            )
            yield _sse("done", done)

    async def resume(
        self, resume: Resume, caller: Caller, conversation_id: UUID, domains: list[Domain] | None
    ) -> Resumed:
        """Raises ApprovalError unless the action is signed, current and this user's, as shown."""
        action = approvals.verify(resume.signed_action, self.settings.approval_signing_key)
        tools = await self.tools(domains, caller)
        spec = next((tool for tool in tools if tool.name == action.tool), None)
        if spec is None or not spec.requires_approval:
            raise ApprovalError(f"{action.tool} is no write tool")
        try:
            args = spec.args.model_validate(resume.args)
        except ValidationError as error:
            raise ApprovalError(f"invalid arguments: {error}") from error
        approvals.check(action, caller.sub, str(conversation_id), args)
        return Resumed(action, spec, args, resume.decision, resume.note)

    def _propose(
        self,
        call: ToolCall,
        spec: ToolSpec[Any],
        args: BaseModel,
        user_id: str,
        conversation_id: UUID,
    ) -> ApprovalRequiredEvent:
        approval_id = uuid4()
        # Whole seconds: the signed `exp` has no fractions.
        expires_at = datetime.now(UTC).replace(microsecond=0) + timedelta(
            minutes=self.settings.approval_ttl_min
        )
        action = Action(
            str(approval_id),
            user_id,
            str(conversation_id),
            spec.name,
            call.id,
            approvals.args_hash(args),
        )
        return ApprovalRequiredEvent(
            approval_id=approval_id,
            call_id=call.id,
            tool=spec.name,
            args=args.model_dump(mode="json"),
            risk=spec.risk,
            expires_at=expires_at,
            signed_action=approvals.sign(action, self.settings.approval_signing_key, expires_at),
        )

    async def _decided(
        self,
        call: ToolCall,
        resume: Resumed,
        roles: list[str],
        deadline: float,
        semaphore: asyncio.Semaphore,
    ) -> _Outcome:
        if resume.decision == "reject":
            note = f" Their note: {resume.note}" if resume.note else ""
            output = ToolOutput(f"The user rejected this action.{note}", "rejected by the user")
            return _Outcome("rejected", output)
        # The role may have changed since the proposal.
        if not permitted(resume.spec.min_role, roles):
            return _failed("denied", f"{resume.spec.name} is not permitted for your role")
        key = approval_id.set(resume.action.approval_id)
        try:
            return await self._run(call, resume.spec, resume.args, deadline, semaphore)
        finally:
            approval_id.reset(key)

    async def _route(self, question: str, domains: list[Domain] | None) -> Route:
        """The user's domain pick wins; a router failure means no routing."""
        if domains:
            return Route(domains, True, 1.0, "user")
        with tracer.start_as_current_span("route", attributes={SPAN_KIND: "CHAIN"}) as span:
            try:
                route = await self.router.route(question)
            except Exception as error:
                logger.warning("router %s failed: %r", self.settings.router, error)
                return Route([], True, 0.0, self.settings.router)
            span.set_attributes(
                {
                    "output.value": ",".join(route.domains),
                    "route.confidence": route.confidence,
                    "route.needs_tools": route.needs_tools,
                }
            )
            if route.router == "llm":
                span.set_attributes(
                    {
                        "llm.prompt_template.version": routing.PROMPT.ref,
                        "prompt.hash": routing.PROMPT.hash,
                    }
                )
            return route

    def _exceeded(self, usage: AgentUsage, deadline: float) -> str | None:
        if time.monotonic() > deadline:
            return "wall_clock"
        if usage.input_tokens >= self.settings.agent_run_input_token_budget:
            return "input_tokens"
        if usage.cost_usd is not None and usage.cost_usd >= self.settings.agent_run_cost_cap_usd:
            return "cost"
        return None

    async def _execute(
        self,
        call: ToolCall,
        spec: ToolSpec[Any] | None,
        roles: list[str],
        deadline: float,
        semaphore: asyncio.Semaphore,
    ) -> _Outcome | BaseModel:
        """One call → an observation for the model (errors included), or its validated args
        when it needs approval."""
        if spec is None:
            return _failed("error", f"Unknown tool {call.name}")
        if not permitted(spec.min_role, roles):
            return _failed("denied", f"{spec.name} is not permitted for your role")
        try:
            args = spec.args.model_validate_json(call.arguments or "{}")
        except ValidationError as error:
            return _failed("error", f"Invalid arguments: {error}")
        if spec.requires_approval:
            return args
        return await self._run(call, spec, args, deadline, semaphore)

    async def _run(
        self,
        call: ToolCall,
        spec: ToolSpec[Any],
        args: BaseModel,
        deadline: float,
        semaphore: asyncio.Semaphore,
    ) -> _Outcome:
        attributes = {
            SPAN_KIND: "TOOL",
            "gen_ai.operation.name": "execute_tool",
            "tool.name": spec.name,
            "input.value": call.arguments,
        }
        async with semaphore:
            timeout = min(
                spec.timeout_s or self.settings.agent_tool_timeout_s, deadline - time.monotonic()
            )
            started = time.perf_counter()
            with tracer.start_as_current_span("tool", attributes=attributes) as span:
                try:
                    async with asyncio.timeout(timeout):
                        outcome = _Outcome("ok", await _attempts(spec, args))
                except TimeoutError:
                    outcome = _failed("error", f"Timed out after {max(timeout, 0):.1f} s")
                except Exception as error:
                    logger.exception("tool %s failed", spec.name)
                    outcome = _failed("error", str(error) or type(error).__name__)
                span.set_attribute("output.value", outcome.output.summary)
                if outcome.status != "ok":
                    span.set_status(StatusCode.ERROR, outcome.output.summary)
            outcome.duration_ms = round((time.perf_counter() - started) * 1000)
            return outcome


async def rag_turn(
    pipeline: ChatPipeline,
    turns: list[ChatTurn],
    domains: list[Domain] | None,
    user_id: str,
    model_id: str | None = None,
) -> AsyncGenerator[ServerSentEvent]:
    """`mode=rag`: the Phase 1 pipeline as measured baseline (D32), ending with a v2 `done`."""
    sources: list[Source] = []
    answer: list[str] = []
    done: DoneEvent | None = None
    async with aclosing(pipeline.stream(turns, domains, user_id, model_id)) as events:
        async for event in events:
            match event.data:
                case SourcesEvent() as data:
                    sources = data.sources
                case TokenEvent() as data:
                    answer.append(data.text)
                case DoneEvent() as data:
                    done = data
                    continue
                case _:
                    pass
            yield event
    usage = (done and done.usage) or UsageInfo(input_tokens=0, output_tokens=0, cost_usd=None)
    result = AgentDoneEvent(
        stop_reason="end" if done else "error",
        answer_status=answer_status("".join(answer), len(sources), searched=True),
        top_score=max((source.score for source in sources), default=None),
        usage=AgentUsage(
            input_tokens=usage.input_tokens,
            cached_tokens=0,
            output_tokens=usage.output_tokens,
            cost_usd=usage.cost_usd,
            steps=1,
            tool_calls=0,
        ),
        model=done and done.model,
        prompt_version=rag.PROMPT.ref,
        prompt_hash=rag.PROMPT.hash,
        trace_id=done and done.trace_id,
    )
    yield _sse("done", result)
