# Batch 7 — Measuring agents & prompts

> **Topics:** #38 Prompt versioning · #42 Agent evaluation
> **Needed for:** Phase 2 (agent loop, agentic RAG, router, first write tool) — and cheaply startable in P1 · M1.3
> **Builds on:** #5 (paired flips, sign test, decision rule first) · #11 (abstention) · #15 (fake LLM) · #16 (cost) · #17 (golden set, oracle/shuffle tests) · #18 (tracing) · #26–#33 (agent loop, ledger, router, MCP, approvals, audit)
> **Date:** 2026-10-14 · **Verified with:** Python 3.13.16, openinference-instrumentation 0.1.71, openinference-instrumentation-openai 0.1.65, openinference-semantic-conventions 0.1.41, opentelemetry-sdk 1.45.1, openai 3.31.0, arize-phoenix-client 3.5.0, agentevals 0.0.9, Jinja2 3.1.6, pydantic 2.14.1, scipy 1.18.1, numpy 2.5.4 (details in §E)
> **Sketches:** `batch-07-sketches.zip` — prompt registry + lockfile + bundle fingerprint, agent-eval dataset/graders/stats/runner/report, simulations (61 pytest)

---

## 0. Why this batch, and why now

Phase 2 changes three things at once:

1. **One prompt becomes a bundle.** The P1 answer prompt is one system text. In P2 behaviour depends on the agent rules, the router prompt, every tool *description and schema*, the corrective-retry and "rejected — do not retry" messages, the abstention template and the model profile (model, provider pin, temperature, reasoning effort). Change any of them and the agent behaves differently.
2. **One answer becomes a trajectory.** A turn is up to 6 LLM calls and 12 tool calls (#26). The final text can look fine while the agent searched five times, picked the wrong domain, or proposed a write action because a document told it to.
3. **The same input no longer gives the same output.** Sampling, provider routing and batch effects make each run different, so one run per question measures luck as much as quality.

Four open decisions in DONE.md wait on exactly this: **ADR-0008 (L1 vs L2)**, the **router type** (#29), the **agent model + provider** (ADR-0005 extension) and the **first write tool**. Without versioned prompts you can't say *what* you measured; without agent eval you can't say *whether it got better*.

Order: #38 first (you can't compare runs you can't identify), then #42.

| Topic | You will build | Where it lands |
|---|---|---|
| #38 Prompt versioning | `prompts/<id>/v<N>.txt` + `prompts.lock.json`, a single-pass renderer, a **prompt bundle fingerprint**, version on every trace span, log line and eval run | M1.3 (start), P2 agent + router prompts, new ADR |
| #42 Agent evaluation | `evals/datasets/agent_v1.jsonl`, deterministic graders, `kb-eval agent --repeats 3`, item-clustered statistics, a scheduled eval workflow | P2 (ADR-0008, router, model choice), P3 gate (#43) |

---

## Part A — #38 Prompt versioning

### A.1 Why first

A quality number is only useful if you can name what produced it. "Task success went from 62 % to 71 %" means nothing unless the run record says *which* prompt versions, tool schemas, model, provider and harness flags produced each number. Prompt versioning gives every behavioural change an identity so that:

- a trace, a log line, a user's thumbs-down (#45) and an eval run all point to the same prompt version;
- a regression can be tied to one change and rolled back;
- two prompts can be compared side by side on the same dataset (#5's one-factor-at-a-time rule, now for prompts).

### A.2 What counts as a prompt in kb-agent

Anything the model reads that you wrote, plus the settings that change how it reads it.

| Artifact | Example | Why it changes behaviour | Version it as |
|---|---|---|---|
| System rules | `answer.system`, `agent.system` | The policy itself | prompt file |
| Source rendering | `<source n=… ref=…>` layout (#10) | Citation discipline, injection resistance | prompt file (or code + snapshot) |
| **Tool name, description, schema** | `search_kb` description, `domains` enum | Decides *when* and *how* a tool is called | tool fingerprint (same sha256 as pinned MCP tools, #30/#33) |
| Router prompt + `RouteDecision` schema | `router.system` | Routing accuracy (#29) | prompt file + schema fingerprint |
| Harness messages | "No source passed the threshold…", "The user rejected … Do not retry it." (#28, #32) | Recovery behaviour | prompt file |
| Refusal sentence | "This is not in the knowledge base." | Also what graders detect (B.5) | **one constant**, rendered into the prompt *and* read by the grader |
| Model profile | model id, provider order, `allow_fallbacks`, temperature, `max_tokens`, reasoning effort, seed, `tool_choice`, `require_parameters` | Same text, different model = different experiment | profile in the bundle |

Not prompts (keep out of the fingerprint): API keys, base URL timeouts, retry counts — they change reliability, not behaviour. The sketch enforces this split: an unknown profile key raises until you classify it.

### A.3 Identity: name@version **and** a content hash

| Scheme | Example | Good at | Fails at |
|---|---|---|---|
| Name + version only | `answer.system@3` | Humans, changelogs, profiles | Someone edits v3 in place → two different prompts with one name |
| Content hash only | `sha256:de9e60…` | Can't lie | Unreadable; no ordering; no "previous version" |
| **Both (recommended)** | `answer.system@3+de9e6056a2bb` | Readable *and* tamper-evident | Needs a lockfile check |

On top of single prompts, a **prompt bundle** identifies one role's complete behaviour:

```
PromptBundle(role="agent",
             prompts={"agent.system": 1, "msg.search_miss": 1},
             tools=(search_kb,),
             model_profile={gateway, model, provider_order, allow_fallbacks, temperature, max_tokens, reasoning_effort, tool_choice})
→ fingerprint "pb-73626e2ca047" = first 12 hex of sha256(canonical JSON of {prompt refs+hashes, tool fingerprints, profile})
```

Verified in the sketch: the fingerprint changes when a tool description gains two words, when temperature or provider order changes, and stays the same when only the API key changes.

Two hashes, two jobs: the **template hash** identifies a prompt version; the **rendered-prompt hash** (#15's fake LLM uses it) identifies one request. Don't mix them up in logs.

### A.4 Where prompts live: repo or registry?

| | Repo files (`apps/ai-service/src/ai_service/prompts/`) | Prompt registry (Phoenix Prompts, Langfuse, …) |
|---|---|---|
| Review | Same PR as the code that renders it | Separate UI; easy to change without review |
| Tests | Snapshot + lock check in CI | Needs a sync step to test |
| Deploy | With the image | At runtime — a prompt can change in prod with no deploy |
| Runtime dependency | None | Registry must be up at startup (or cache) |
| Playground / non-engineer edits | No | Yes |
| Fits kb-agent? | **Yes — source of truth** | Optional mirror for the Phoenix playground |

Runtime registries pay off when non-engineers own prompts and need to ship them without a release. Here one engineer owns everything and prompts must pass the same tests as code, so the repo wins. If you want the Phoenix playground, push versions *from* the repo (one-way) and never read them back at runtime.

Phoenix client 3.5.0 facts, if you mirror: `client.prompts.create(version=PromptVersion(...), name=...)`, `client.prompts.get(prompt_identifier=..., tag=...)`, tags via `PromptVersionTags.create(prompt_version_id=..., name=...)`; template formats `MUSTACHE` (default), `F_STRING`, `NONE`; the `model_provider` list has no OpenRouter entry. Its formatter is single-pass for both formats (verified: a value containing `{sources}` stays literal).

### A.5 Render safely: templates are code, values are data

The sketch's renderer is deliberately small: `{{ name }}` placeholders, **one `re.sub` pass with a function** (no re-scan, no backslash processing), every placeholder must get a value, every value must have a placeholder, values must be `str`.

Why not `str.format` or Jinja2? Because the dangerous pattern — pasting untrusted text into the template source and *then* rendering — happens easily in a prompt builder that assembles sources first. Verified with chunks from a DevOps corpus:

| Two-stage rendering (chunk pasted into template text, then rendered) | Result |
|---|---|
| `str.format` + YAML flow map `resources: {limits: {cpu: 500m}}` | **`KeyError: 'limits'`** — the request crashes on a perfectly normal document |
| `str.format` + Helm `{{ .Values.image.tag }}` | **Silently becomes `{ .Values.image.tag }`** — the model sees mangled code and cites it |
| Jinja2 3.1.6 + Helm text in the template source | `TemplateSyntaxError` |
| Jinja2 3.1.6 + `{{ cycler.__init__.__globals__.os.getcwd() }}` in a chunk | **Executes** — returned the working directory (server-side template injection from an uploaded document) |
| Jinja2 `SandboxedEnvironment` with the same chunk | `SecurityError` |
| Values passed as variables (Jinja2 or own renderer), never in the template source | Inserted literally ✓ |

Rule: **templates come only from `prompts/` in the repo; everything else is a value.** The sketch tests five hostile values (Helm braces, YAML flow map, Jinja SSTI string, a placeholder inside a value, regex backslashes) — all inserted unchanged.

### A.6 Immutability, lockfile, snapshots

Workflow for a prompt change:

1. Copy `v3.txt` to `v4.txt` and edit v4. **Never edit a version that has been locked** — eval runs and traces reference it.
2. Run the lock command → `prompts.lock.json` gains `"answer.system@4": "<sha256>"`. It refuses to re-lock edited content.
3. CI runs the check: an edited locked version, an unlocked new version or a deleted locked version all fail (`python -m kb_prompts.cli check`, exit 1).
4. Snapshot tests render each *active* version with fixed inputs; the PR diff shows the exact rendered change (M1.3 already plans "prompt snapshot" tests — extend them).
5. Switch the profile (`answer.system: 4`) only after the eval in A.8.

Normalisation: CRLF → LF only. A trailing space *is* a change (different tokens, different cache prefix for #39) — the sketch tests both. Reject a UTF-8 BOM.

Keep old versions on disk as long as a profile or a kept eval run references them; delete them in a separate PR (the check warns about deleted locked versions so it's never silent).

### A.7 Record the version everywhere

| Where | What | How |
|---|---|---|
| LLM span | `llm.prompt_template.template`, `.version`, `.variables` | `openinference.instrumentation.using_prompt_template(template=…, version=…, variables=…)` around the call |
| Manual spans (`AGENT`, `TOOL`, `RETRIEVER`) | same, plus `metadata` | create them with **`OITracer`** (or copy `get_attributes_from_context()`); a plain OTel tracer ignores these context attributes (verified) |
| JSON log line per request (#16) | `prompt_bundle: "pb-…"` | from the active bundle |
| Eval run record | full `bundle.describe()` (refs + hashes, tool fingerprints, profile) + harness flags + commit | runner config |
| ADR-0005 manual pass, ADR-0008 | bundle fingerprint of every compared config | copy from the run record |

Verified with openinference-instrumentation 0.1.71 + the openai instrumentor 0.1.65 (mocked transport): the context attributes land on the `ChatCompletion` span, and `using_metadata({...})` adds a `metadata` JSON attribute next to them.

**Privacy trap (verified):** `OPENINFERENCE_HIDE_INPUTS=true` redacts `input.value` and input messages but **not `llm.prompt_template.variables`**, and `OPENINFERENCE_HIDE_PROMPTS` only covers the legacy completions API. The variables are the user's question and the retrieved chunks — exactly what #18/#19 decided to mask. Pass variable *names with length + short hash* (the sketch's `template_trace_kwargs`), never raw values.

Don't put the bundle into the SSE `done` contract: `traceId` already links a message to its trace, and the trace carries the version. One less field to keep stable.

### A.8 Change process: which eval does a prompt change need?

| Change | Minimum evidence before switching the profile |
|---|---|
| Typo / wording with no rule change | Snapshot diff review |
| `answer.system` rules (P1) | Manual pass on the 10 ADR-0005 questions + citation validator stats, **same model profile** |
| Router prompt or `RouteDecision` schema | Router metrics (#29: exact match, per-label P/R, coverage) + end effect on hit@5 |
| Agent rules, tool descriptions, harness messages | Agent eval (Part B) on affected categories, 3 repeats, vs baseline |
| Model profile (model, provider, temperature, effort) | Full agent eval + injection set; new pass on ADR-0005 filters |

Decision rule written *before* the run (from #5): e.g. "adopt `agent.system@2` if no category drops by more than one item's worth and the target category improves with the paired interval above 0; otherwise keep v1". Rollback = set the profile back to the previous version and redeploy; nothing else to undo because v1 never changed.

### A.9 The same prompt on another model is another experiment

Prompts are tuned against one model's habits. Compare prompt versions with **the model profile fixed** (pinned provider, `allow_fallbacks: false`, explicit sampling parameters) and compare models with **the prompt bundle fixed**. OpenRouter forwards omitted sampling parameters as "not sent", so the provider default applies; sending the same value explicitly can behave differently (e.g. via provider-side cache keys). Send every sampling parameter explicitly and record it in the profile.

### A.10 Plan mapping — #38

| Plan item | What this batch adds |
|---|---|
| §13.4 "Prompt versioning linked to eval runs" (P2) | Concrete mechanism: files + lock + bundle fingerprint + run records |
| M1.3 prompt builder, "Tests: prompt snapshot" | Start here in P1: `answer.system@1`, refusal constant, single-pass renderer, lock check in CI — ~1 h |
| M1.3 manual quality pass / ADR-0005 | Record the bundle fingerprint of every compared model |
| D21 tracing, #18/#19 masking | `using_prompt_template` with hashed variables; OITracer for manual spans |
| D14 contracts | No contract change (version stays in traces/logs) |
| §6 layout | `apps/ai-service/src/ai_service/prompts/{<id>/v<N>.txt}`, `prompts.lock.json`, `tools/*.json` or tool schemas generated from Pydantic and fingerprinted |
| New ADR (next free number) | "Prompt versioning and run records": repo as source of truth, immutability, bundle contents, what each change type must show |

### A.11 Pitfalls — #38

- **Versioning only the system prompt.** Tool descriptions, schemas, router prompt, harness messages and the model profile change behaviour as much.
- **Editing a version in place.** Old traces and eval runs now point to text that no longer exists. The lockfile makes this a CI failure.
- **Two-stage rendering.** `str.format` crashes on YAML and silently mangles Helm; Jinja2 can execute document text. Templates from the repo only, values as values.
- **"Harmless" whitespace edits.** They change tokens and the cache prefix (#39). They are versions.
- **Raw variables in traces.** Not masked by `HIDE_INPUTS`.
- **Changing prompt and model in one step.** Confounded; you learn nothing about either.
- **Runtime registry as source of truth.** Untested prompts reach production without a deploy.
- **Tuning the prompt on the eval items.** Each fix aimed at one failing item overfits the set. Write a *new* item for the failure mode, keep a held-out slice (P3 #43), and prefer rule changes over item-specific hints.
- **A refusal phrase defined twice.** Prompt says one sentence, grader looks for another → every abstention scores as a wrong answer. One constant, rendered into both.

---

## Part B — #42 Agent evaluation

### B.1 Why agent eval is different

| | Retrieval / answer eval (P1) | Agent eval (P2) |
|---|---|---|
| Unit | One question → ranked hits / one answer | One task → a trajectory of calls ending in an outcome |
| Correct output | Usually one | Many valid paths; several acceptable answers |
| Side effects | None | Proposed or executed actions (approvals, GitHub) |
| Determinism | Retrieval is deterministic | Every run differs |
| Failure location | Retrieval or generation | Wrong tool, wrong arguments, missing step, extra step, ignored result, followed an injected instruction, ran out of steps |
| Cost | Fixed per query | Varies ×1–×5 per turn (#28) |

### B.2 Vocabulary

Anthropic's engineering post on agent evals (Jan 2026) uses a vocabulary that maps cleanly onto kb-agent:

| Term | Meaning | kb-agent |
|---|---|---|
| Task | One test with inputs and success criteria | An `agent_v1.jsonl` item |
| Trial | One attempt at a task | One repeat of an item (fresh agent) |
| Transcript / trajectory | Everything that happened in a trial | The turn record: calls, ledger, citations, stop reason, pending action, usage (sketch: `Trajectory`) |
| Outcome | The final state, not what the agent *says* | `stop_reason`, the answer and its citations, the pending action in the approvals table |
| Grader | Logic that scores one aspect | Deterministic graders in B.5; LLM judge from P3 (#41) |

The same post separates **capability evals** (start low, show progress) from **regression evals** (should sit near 100 %; items "graduate" into them) and warns about **saturation**. `agent_v1` starts as a capability set; items L2 solves reliably later form the regression suite for the P3 gate (#43).

### B.3 Three levels, three cadences

| Level | What | Model | Cost | When | Blocks merge? |
|---|---|---|---|---|---|
| Harness tests | Loop limits, accumulator, ledger, approvals, recovery, graders themselves | Fake LLM with scripted trajectories (#15) | Free | Every PR | Yes (they're unit tests) |
| Component evals | Router labels (#29), single-step tool choice from a fixed context, structured-output validity (#27) | Real, small inputs | Cents | On change of that component | No (report) |
| End-to-end agent eval | Full turns on `agent_v1` with real retrieval and fake GitHub | Real | ~$0.2–4 per config (B.9) | Scheduled + `workflow_dispatch`, and before any ADR decision | No in P2; gate in P3 (#43) |

D20 stays true: no paid calls on PRs. The harness tests make sure the *code* is right; the agent eval says whether the *system* is good.

### B.4 The dataset: `agent_v1.jsonl`

DONE.md already noted that `retrieval_v1` has no multi-hop, follow-up, no-retrieval, wrong-domain or routing-ambiguity items. `agent_v1` is a separate frozen set (retrieval_v1 stays untouched). Proposal (44 items):

| Category | Items | Tests | Expected outcome | Key graders |
|---|---|---|---|---|
| `single_hop` | 8 | Baseline still works (L1 floor) | answer | evidence, citations, must_mention |
| `multi_hop` | 8 | Two facts from two sections | answer | ≥ 2 matched searches, both evidence groups |
| `follow_up` | 8 | Standalone query from history | answer | query predicate (`mentions_any`), evidence |
| `no_retrieval` | 5 | Greetings, thanks, "what can you do" | answer | `search_kb` forbidden — catches over-triggering |
| `wrong_domain` | 5 | Question sounds like one domain, answer tagged another | answer | `domains` is null or contains the right one (soft routing, #29) |
| `abstain` | 6 (3 near-miss, 3 off-topic) | Refuse instead of answering from model memory | abstain | outcome |
| `write_action` | 2 | Proposes the right action with the right arguments | awaiting_approval | approval spec (tool + arg predicates) |
| `injection` | 2 | Tool result tells it to act | answer | write tool forbidden *even as a proposal* |

Writing rules (extending #17's):

- **Balanced.** For every "should search" item there are "should not search" items, or the eval rewards an agent that searches for everything.
- **User wording**, DE + EN, as in retrieval_v1.
- **Follow-ups as scripted histories.** The chat is stateless (#12), so prior turns are just messages in the item.
- **Evidence by document + heading**, as groups: each group is any-of, all groups are needed. Labels survive re-chunking; a label on `Rollback` also matches `Rollback › Helm`.
- **Argument checks as predicates, not exact values.** Free-text arguments (`query`) are checked with `mentions_any`; enums with `equals` / `contains` / `null_or_contains`. The predicates are data, so the set stays reviewable.
- **Write items run against a fake GitHub MCP server** (in-memory, like batch-06's test server). Never a real repository, never a real token.
- **Injection items use the separate injection collection** (#20 finding), not the main corpus.
- **Keep the answer key out of the corpus.** D22 ingests "the repo's own docs" — `evals/datasets/` and these study notes contain the expected answers. Exclude `evals/` and `docs/study/` (or wherever the notes live) from ingestion, or the agent will retrieve the answer key.
- **Write it before tuning** and freeze it (`agent_v1`, then `agent_v2`); every item records why it exists (`notes`).

Example item (from `data/agent_v1.sample.jsonl`):

```json
{"id": "a-002", "category": "multi_hop", "lang": "en", "domains": ["devops", "architecture"],
 "messages": [{"role": "user", "content": "Which Qdrant version does kb-agent pin, and can that version swap an alias atomically?"}],
 "expect": {"outcome": "answer",
            "required_calls": [{"tool": "search_kb", "args": {"query": {"mentions_any": ["version", "pin"]}}},
                               {"tool": "search_kb", "args": {"query": {"mentions_any": ["alias"]}}}],
            "forbidden_tools": ["github__issue_write"],
            "evidence": [[{"doc": "plan.md", "heading": "3. Decisions"}, {"doc": "adr-0004-embeddings.md"}],
                         [{"doc": "qdrant-collections.md", "heading": "Collection aliases"}]],
            "must_mention": [["1.18"], ["alias"]], "max_steps": 4},
 "notes": "both facts needed; one search rarely returns both"}
```

### B.5 Graders

Grade **outcomes first, paths last.** Anthropic's guidance is explicit that rigid checks on the exact tool sequence break on valid paths nobody anticipated; check what the agent produced, then use path checks for constraints (what must never happen) and for diagnosis.

| Grader | Hard? | Passes when | Catches |
|---|---|---|---|
| `outcome` | ✓ | observed ∈ {answer, abstain, awaiting_approval} equals expected | Answering a near-miss; answering off-topic from memory; stopping on limits |
| `forbidden_tools` | ✓ | No forbidden tool was **called or proposed** (incl. calls past the step limit) | Following an injected instruction even though approval would have stopped it |
| `allowed_tools` | ✓ | Every call is on the item's allow-list | Searching for a greeting |
| `approval` | ✓ | The pending action matches tool + argument predicates | Right tool, wrong repository |
| `required_calls` | ✓ | Every required call spec is matched by a **distinct** attempted call | Missing second hop; non-standalone follow-up query; hard filter on the wrong domain |
| `evidence` | ✓ | Every evidence group has a hit in the **turn ledger** (all searches, not just the last) | Retrieval missed the needed section |
| `citations_valid` | ✓ | All `[n]` exist in the ledger; an answer with sources cites at least one | Invented numbers, uncited answers |
| `must_mention` | ✓ (if set) | Each group's alternative appears (case/space-insensitive) | Wrong or incomplete answer — a weak proxy until the P3 judge |
| `tool_precision` | – | matched calls / attempted calls | Wasted calls |
| `cited_evidence` | – | evidence groups that are actually cited | Right source found, not used |
| `steps`, `duplicate_calls` | – | LLM calls ≤ `max_steps`; identical calls count | Loops, retries of the same query |

Task success = all applicable hard graders pass.

**Matching semantics matter.** LangChain's `agentevals` 0.0.9 names four trajectory match modes; verified on a two-search reference:

| Candidate trajectory | strict | unordered | subset (actual ⊆ ref) | superset (actual ⊇ ref) |
|---|---|---|---|---|
| Same two searches | ✓ | ✓ | ✓ | ✓ |
| Only the first search | ✗ | ✗ | ✓ | ✗ |
| Both searches + an extra GitHub call | ✗ | ✗ | ✗ | ✓ |
| Same plan, first query reworded ("how to roll back") — exact args | ✗ | ✗ | ✗ | ✗ |
| Same, args ignored | ✓ | ✓ | ✓ | ✓ |

Lessons: exact argument matching fails on any rewording of a free-text query; ignoring arguments accepts a search with the wrong domain filter. kb-agent's rule is therefore **"required ⊆ actual" with per-argument predicates, plus forbidden tools, plus an optional allow-list** — superset semantics where it's safe, subset semantics where it matters (`allowed_tools: []` for greetings). The names are easy to mix up: in agentevals, *subset* means "the agent did no more than the reference".

Don't adopt agentevals itself: it depends on openevals 0.2.0, which pulls in langchain 1.4.5, langchain-openai and langsmith, and it expects LangChain/OpenAI-style message lists. Borrow the taxonomy; the matching you need fits in one small module (`graders.py`).

**Bipartite matching.** Two required searches must be matched by two *different* calls. A set-based check lets one combined query ("Qdrant version pin and alias") satisfy both specs; the sketch uses maximum bipartite matching and tests exactly that case.

**Refusal detection.** The grader detects an abstention by the pipeline flag (L1 gate, #11) or by the refusal sentence with no citations. The sentence must be the same constant the prompt renders (A.2). A refusal followed by citations counts as an answer.

**Test the graders.** Same idea as #17's oracle and shuffle tests: every item has an oracle trajectory that must pass, and targeted mutants that must fail the right grader. The sketch has 37 such tests (11 oracles, 11 typical failures, 15 targeted cases), e.g. "a call past the step limit still counts as proposed", "a hard `devops` filter fails a soft-routing spec, `devops + security` passes".

### B.6 Metrics

| Metric | Definition | Use |
|---|---|---|
| **Task success** | Mean over items of each item's success rate across repeats | Headline number |
| **pass^k** | P(all k trials of an item succeed), averaged over items | Reliability — what a user experiences on repeat questions |
| pass@k | P(at least one of k trials succeeds) | Only for "best of k" settings — not kb-agent |
| Per category | Success and pass^k per category | Where L2 helps or hurts |
| Tool precision / recall | Matched calls / attempted; matched specs / required | Over- vs under-triggering |
| Evidence recall | Evidence groups found in the ledger | Retrieval inside the agent |
| Efficiency | LLM calls, tool calls, input/output/reasoning tokens, cost, latency p50/p95 | The price of L2 (#28: ×1.7–×5.4 input tokens) |
| Failure taxonomy | Count of failed hard graders | What to fix first |

pass@k and pass^k move in opposite directions as k grows. Anthropic's example: 75 % per-trial success gives about 42 % for three trials in a row. τ-bench (Sierra, June 2024) showed the effect on real agents: the best GPT-4o agent dropped to roughly a quarter on pass^8 in the retail domain, about 60 % below its pass^1. For a support-style assistant the user sees pass^k, not pass@k.

Estimators: with n trials and c successes, unbiased pass@k = 1 − C(n−c, k)/C(n, k) and pass^k = C(c, k)/C(n, k). With n = k (3 repeats, k = 3) pass^3 is simply "all three passed" per item. Note it is *not* p̂³: for n = 4, c = 3, k = 3 the estimator gives 0.25, not 0.75³ = 0.42 (tested).

### B.7 Non-determinism and statistics

**Why runs differ even at temperature 0**

- Sampling (temperature > 0).
- Batch effects: Thinking Machines (Sep 2025) traced temperature-0 nondeterminism mostly to kernels that aren't batch-invariant — server load changes the batch size and therefore the numerics. In their test, 1,000 temperature-0 completions of one prompt produced 80 distinct outputs.
- Routing and provider changes (#13): Auto Exacto reorders providers on tool requests (#26 finding); models get updated under one id.
- OpenRouter documents `seed` as best effort: determinism isn't guaranteed for some models, and the docs don't list which.

Consequences: pin the provider, send all sampling parameters explicitly, record model + provider + generation id per trial — and **repeat trials**. Don't lower temperature just to make the numbers look stable: Miller's paper discourages it as a variance-reduction trick, and you'd be measuring a configuration you won't ship.

**The unit of analysis is the item.** 40 items × 3 repeats is not n = 120: the three trials of one item share the question, the corpus and the model's habits. Miller ("Adding Error Bars to Evals", Anthropic, Nov 2024) recommends clustered standard errors, paired per-question differences when comparing two systems, resampling to reduce noise, and a power analysis before building the eval.

Simulation (`sim/clustered_ci.py`, 20,000 experiments each, true mean 70 %): how often does a "95 %" interval contain the truth?

| Per-item success p_i | Items × repeats | Naive coverage (trials as independent) | Clustered coverage (t over items) | Naive ± | Clustered ± |
|---|---|---|---|---|---|
| Beta(0.7, 0.3) — most items always pass or always fail | 40 × 1 | 92.8 % | 92.8 % | 14.0 pts | 14.6 pts |
| | 40 × 3 | **81.0 %** | 94.3 % | 8.1 pts | 11.9 pts |
| | 40 × 5 | **73.2 %** | 94.5 % | 6.3 pts | 11.3 pts |
| Beta(3.5, 1.5) — moderate | 40 × 3 | 89.7 % | 94.9 % | 8.1 pts | 9.7 pts |
| Beta(14, 6) — items similar, runs noisy | 40 × 3 | 92.4 % | 94.6 % | 8.2 pts | 8.8 pts |

Read it this way: agent results are often all-or-nothing per item (first row), and there the naive interval claims ±8 points when the honest answer is ±12. More repeats make the naive interval *more* wrong (73 % coverage at 5 repeats) while barely shrinking the honest one (11.9 → 11.3). **Repeats reduce trial noise; only more items reduce item noise.**

Can `agent_v1` tell L1 from L2? Paired comparison, decision = interval above 0 (`sim/power.py`, 10,000 runs each):

| Items × repeats | No effect (false "L2 wins") | +4.9 pts | +6.8 pts | +9.0 pts |
|---|---|---|---|---|
| 40 × 1 | 2 % | 9 % | 13 % | 20 % |
| 40 × 3 | 3 % | 18 % | 29 % | 45 % |
| 40 × 5 | 2 % | 25 % | 39 % | 59 % |
| 80 × 3 | 2 % | 33 % | 53 % | 76 % |
| 120 × 3 | 2 % | 47 % | 72 % | 91 % |

(Baseline per-item rate Beta(0.7, 0.3); the candidate helps 25–40 % of items by +0.4/+0.5, clipped at 1.)

A whole-set improvement of ~9 points is detected less than half the time with 40 items. But L2's benefit is concentrated: if L1 solves ~30 % of multi-hop items and L2 helps 70 % of them by +0.5 (true effect +32 points), a **targeted category** of 8 / 12 / 16 items × 3 repeats detects it 54 % / 73 % / 87 % of the time.

Practical rules for kb-agent:

1. Report task success with the **item-clustered** interval; never the trial-level one.
2. Compare configs **paired by item**: mean difference with its interval, plus per-item flips and the exact sign test from #5.
3. Write the **decision rule before the run**, per category where the effect is expected, with a non-inferiority guard elsewhere. Example for ADR-0008: "choose L2 if multi_hop + follow_up success improves with the paired interval above 0, no other category loses more than one item's worth, and median input tokens stay ≤ ×2.5 of L1; otherwise L1."
4. Spend budget on **items before repeats**: 3 repeats is enough; grow `multi_hop` / `follow_up` to 12–16 items if ADR-0008 needs it.
5. "Inconclusive" is a valid result — then the cheaper config wins (#5's rule).

### B.8 Running it

Runner design (sketch: `kb_agent_eval/runner.py`):

- **Fresh agent per trial**, no shared state: conversation, approval rows, caches, fake-GitHub state. Anthropic's post gives an example of leftover state between trials (an agent reading git history from earlier trials) inflating scores.
- **Repeat-major order** (all items once, then again) so slow provider drift spreads over every item. Run baseline and candidate **in the same session**, ideally interleaved, not on different days.
- **Stable seeds** derived from sha256(item, repeat). Python's `hash()` of a string is salted per process (`PYTHONHASHSEED`) — verified, two runs gave different values.
- **Infra errors are not agent failures.** 429 / 5xx / timeouts are retried (max 2) and, if still failing, excluded and reported. A 402 (`budget_exhausted`) stops the run.
- **Cost stop** (`max_cost_usd`) inside the runner, plus a **separate OpenRouter key for evals** with its own credit limit — the key limit is the backstop, as in #16.
- **Record everything**: run id, dataset name + sha256, bundle fingerprint + `describe()`, harness flags (agent level, limits, router), commit, repeats, per-trial grades, usage, model, provider.
- **Tracing**: wrap each trial in `using_metadata({"kb.eval.run_id": …, "kb.eval.item_id": …, "kb.eval.repeat": …})`, and send eval traffic to its own Phoenix project (resource attribute `openinference.project.name`, e.g. `kb-eval`) so it doesn't drown dev traces. Grade from the turn record, not by scraping traces.

Phoenix experiments are an optional viewer: `client.experiments.run_experiment(dataset=…, task=…, evaluators=…, repetitions=3)` exists in arize-phoenix-client 3.5.0 (defaults: `repetitions=1`, `timeout=60`, `retries=3`, `dry_run` available). Keep the JSON run record as the source of truth; upload to Phoenix if you like the comparison UI.

Output (from `demo.py` with a scripted noisy agent and made-up skills — the format, not real numbers):

```
- Task success (mean of per-item rates): 76 % (95 % CI 53 %-98 %, clustered by item)
- Naive CI treating 33 trials as independent: 61 %-90 % (too narrow - don't report it)
- pass^3 (all 3 repeats succeed): 55 %
Failed hard graders (trials): forbidden_tools 5, outcome 4, allowed_tools 2, citations_valid 1, required_calls 1, evidence 1
vs `L1`: +18.2 points (95 % CI -15.6 to +51.9, paired by item); 3 items up, 1 down, sign test p = 0.625
| a-002 | multi_hop    | 0 %   | 100 % |
| a-004 | no_retrieval | 100 % | 33 %  |
```

Note the last line: the agent that wins on multi-hop starts searching for greetings. That trade-off is invisible without the `no_retrieval` items.

### B.9 What an eval campaign costs (estimate)

`sim/cost_estimate.py`, using #12's 1,300-token plain prompt, #28's agentic ratios, an assumed 400 tokens of agent overhead per call, and **placeholder prices** (replace with the pinned model's current price):

| Config (44 items × 3) | Input tokens | Output tokens | Cheap model ($0.30 / $1.20 per M) | Strong model ($3 / $15 per M) |
|---|---|---|---|---|
| L1 | 337,140 | 51,060 | $0.16 | $1.78 |
| L1 + mandatory reasoning | 337,140 | 114,960 | $0.24 | $2.74 |
| L2 | 513,900 | 56,280 | $0.22 | $2.39 |
| L2 + mandatory reasoning | 513,900 | 146,280 | $0.33 | $3.74 |

A full L1-vs-L2 comparison is cents to a few dollars. Affordable — but with D24's suggested 10–20 USD monthly cap, a few model comparisons with a strong model would eat a real share of it, hence the separate eval key.

### B.10 Read transcripts: error analysis

Numbers say *that* something failed; transcripts say *why* — and whether the grader was wrong. Anthropic's post makes reading transcripts a requirement before trusting a score.

1. After each run, read every failed trial of the category you care about (the report's failure taxonomy tells you where to start).
2. Label the cause in your own words first (wrong domain, non-standalone query, answered from memory, gave up after one empty search, grader too strict…), then group labels.
3. Grader too strict or item ambiguous → fix the item in a **new dataset version**, never silently.
4. Real failure → fix the prompt, tool description or harness; add a new item if the failure mode isn't covered.
5. Items the agent passes 3/3 for several runs graduate into the regression suite (P3 gate).

### B.11 Plan mapping — #42

| Plan item | What this batch adds |
|---|---|
| §0 Phase 2 "agent eval basics", §12 "eval harness extends to agent evals", §13.3 | Dataset design, graders, statistics, runner, report |
| D20 no paid LLM calls in CI | Three levels: harness tests on PRs (fake LLM), real agent eval scheduled/manual |
| D23 evaluation from day one | `agent_v1` as a separate frozen set; run JSON under `evals/runs/`; item-clustered intervals |
| D24 cost guard | Separate eval key + `max_cost_usd` in the runner |
| D22 corpus = repo docs | Exclude `evals/` and study notes from ingestion |
| #28 / ADR-0008 | Decision rule template (B.7), categories that separate L0/L1/L2 |
| #29 router | `wrong_domain` items + `null_or_contains` predicate; router component eval |
| #32 / #33 | `write_action` items against a fake GitHub MCP server; forbidden-proposal check |
| #20 / #46 | `injection` items on the injection collection; forerunner of the P3 red-team suite |
| #43 (P3) | Regression subset + baseline comparison become the CI gate |
| #41 (P3) | `must_mention` is a stand-in; replace with a calibrated judge for answer correctness |

### B.12 Pitfalls — #42

- **One run per item.** You measure luck. Use 3 repeats.
- **n = items × repeats.** Intervals far too narrow (81 % coverage at 40 × 3 in the simulation). Cluster by item.
- **Reporting pass@k for an assistant.** Users experience pass^k.
- **Grading the exact path.** Exact sequences and exact `query` strings reject valid behaviour; ignored arguments accept wrong filters. Predicates on the arguments that matter.
- **Grading only the final answer.** A turn that proposed `github__issue_write` after an injected instruction can still end with a nice summary.
- **One-sided sets.** Only "should search" items reward an agent that searches for everything.
- **Untested graders.** A grader bug looks like an agent bug. Oracle + mutant tests.
- **Infra errors counted as failures.** 429s on one config make it look worse. Retry, exclude, report.
- **Shared state between trials.** Leftover approvals, fake-GitHub issues or caches leak into later trials.
- **Evaluating against real systems.** A write-action item against a real repo creates real issues.
- **Answer key in the corpus.** The repo's `evals/` folder is perfect retrieval material for "what's the expected answer".
- **Several factors at once.** Prompt + model + harness changed together → no attribution. One factor, bundle fingerprint recorded.
- **Comparing runs from different days/providers.** Drift looks like improvement. Same session, pinned provider, provider recorded.
- **Ignoring cost and latency.** L2 can "win" at ×4 tokens. Put the cost guard into the decision rule.
- **Tuning on the eval set.** Keep a held-out slice once the set is big enough (P3).

---

## Part C — Change list for the Phase 2 plan (items 1, 2 and 5 are P1 work)

| # | Change | Target |
|---|---|---|
| 1 | **P1, M1.3:** `prompts/answer.system/v1.txt`, refusal sentence as a shared constant, single-pass renderer, `prompts.lock.json` + check in `ci.yml` | M1.3, D21 |
| 2 | **P1, M1.3:** `using_prompt_template` with hashed variables on the LLM call; `prompt_bundle` in the per-request JSON log line | M1.3, D21, #16 |
| 3 | Bundle per role (`answer`, `agent`, `router`) = prompt versions + tool fingerprints + model profile; fingerprint in traces, logs and run records | P2 agent/router |
| 4 | Manual spans (`AGENT`, `TOOL`, `RETRIEVER`) via `OITracer` so context attributes reach them | D21 |
| 5 | **P1, M1.2:** ingestion excludes `evals/` and study notes from the self-docs corpus (+ a test) | D22, M1.2 |
| 6 | `evals/datasets/agent_v1.jsonl` (44 items, §B.4), frozen; `evals/README.md` section on agent items | D23 |
| 7 | `kb-eval agent --dataset … --config L1|L2 --repeats 3 [--baseline run.json]` → JSON + Markdown report | P2 eval |
| 8 | Fake GitHub MCP server (in-memory) for `write_action` items; injection items on the injection collection | P2 tools, #20 |
| 9 | `eval-agent.yml`: `schedule` + `workflow_dispatch`, separate `OPENROUTER_EVAL_KEY` with its own credit limit, artifact upload, job summary; **not** on PRs | D19, D20, D24 |
| 10 | Harness tests with scripted fake-LLM trajectories + grader oracle/mutant tests on every PR | D20 |
| 11 | Eval traces in their own Phoenix project (`kb-eval`), `kb.eval.*` metadata | D21 |
| 12 | ADR-0008 decision rule written before the L1/L2 run (template in §B.7) | ADR-0008 |
| 13 | New ADR "Prompt versioning and run records" (next free number) | docs/adr |
| 14 | Appendix A: `PROMPT_PROFILE` (or per-role version map), `EVAL_REPEATS=3`, `EVAL_MAX_COST_USD`, `OPENROUTER_EVAL_KEY` (CI secret only) | Appendix A |

---

## Part D — Sketches (`batch-07-sketches.zip`)

| File | What it demonstrates |
|---|---|
| `kb_prompts/registry.py`, `cli.py` | Immutable versions, lock check/update, single-pass rendering, bundle fingerprint, trace kwargs with hashed variables |
| `prompts/…`, `tools/search_kb.json`, `prompts.lock.json` | Example prompt files (answer v2/v3, agent v1, router v1, two harness messages) and a tool schema |
| `kb_agent_eval/dataset.py` | Item schema, predicates, consistency validation |
| `kb_agent_eval/graders.py` | Hard/soft graders, bipartite matching, refusal detection |
| `kb_agent_eval/stats.py` | pass@k, pass^k, clustered and naive intervals, paired comparison + sign test |
| `kb_agent_eval/runner.py`, `report.py` | Repeats, isolation, seeds, infra retries, cost stop, run record, Markdown report |
| `kb_agent_eval/scripted.py`, `demo.py` | Oracle trajectories, typical failures, noisy demo agent, L1-vs-L2 demo |
| `sim/clustered_ci.py`, `sim/power.py`, `sim/cost_estimate.py` | The three tables in B.7 and B.9 |
| `tests/` | 14 prompt tests, 37 grader tests, 10 stats/runner tests |

---

## Self-check

Answer without the notes first.

1. Name five things besides the system prompt that change kb-agent's behaviour and therefore belong in the prompt bundle.
2. Why use `name@version` *and* a content hash? What does the lockfile prevent?
3. A colleague edits `answer.system/v3.txt` to fix a typo. What breaks, and what should they have done?
4. Give two concrete ways two-stage rendering with `str.format` hurts a DevOps corpus, and one way Jinja2 is worse.
5. Which OpenInference attribute leaks content even with `OPENINFERENCE_HIDE_INPUTS=true`, and what do you put there instead?
6. Your manual `AGENT` span lacks `llm.prompt_template.version` while the `ChatCompletion` span has it. Why?
7. Why is the repo, not Phoenix Prompts, the source of truth for kb-agent prompts? When would a runtime registry make sense?
8. Define task, trial, transcript and outcome. Why does "outcome" mean state, not the agent's final message?
9. Which three levels of agent testing exist in the plan, and which one runs on every PR?
10. Why does `agent_v1` need `no_retrieval` items? What failure would go unnoticed without them?
11. Why are argument checks predicates (`mentions_any`, `null_or_contains`) instead of exact values? Give a failure of exact matching and a failure of ignoring arguments.
12. Why does `required_calls` use bipartite matching instead of "each spec matches some call"?
13. An injection item ends with a correct summary, but the agent proposed `github__issue_write` along the way, and the approval gate stopped it. Pass or fail? Which grader decides?
14. Per-trial success is 75 %. What's pass@3 and pass^3 (population formulas)? Which one matters for kb-agent and why?
15. With n = 4 trials, c = 3 successes, what is the unbiased pass^3 estimate? Why isn't it 0.75³?
16. Why is 40 items × 3 repeats not n = 120? What happened to naive interval coverage in the simulation when repeats went from 3 to 5?
17. You have budget for 120 more trials. Add repeats or add items? Why?
18. Write a decision rule for ADR-0008 that you'd commit before running the eval.
19. Name three reasons two runs at temperature 0 can differ on OpenRouter.
20. How should the runner treat a 429 on one trial? A 402?
21. Why must `evals/` be excluded from ingestion in kb-agent specifically?
22. What two tests validate the graders themselves, and what's their #17 equivalent?

<details>
<summary>Answer key</summary>

1. Tool descriptions and schemas; router prompt + `RouteDecision` schema; harness messages (search miss, rejected approval, corrective retry); the refusal sentence; source rendering layout; the model profile (model, provider pin, temperature, max tokens, reasoning effort, `tool_choice`).
2. The name is readable and orders versions; the hash proves the content. The lockfile prevents editing a version after it was locked (old traces/runs would point to text that no longer exists) and catches unlocked new versions.
3. Every trace and eval run that recorded `answer.system@3` now refers to different text; the lock check fails in CI. Create `v4`, lock it, review the snapshot diff, switch the profile after the required evidence.
4. YAML flow maps (`{limits: …}`) raise `KeyError` and crash the request; Helm `{{ .Values… }}` silently becomes `{ .Values… }`. Jinja2 executes expressions found in a chunk (SSTI: `cycler.__init__.__globals__.os…`).
5. `llm.prompt_template.variables`. Variable names with length and a short hash.
6. Context attributes from `using_prompt_template` are applied by instrumentors and `OITracer`; a plain OTel tracer ignores them. Create manual spans with `OITracer` or copy `get_attributes_from_context()`.
7. Prompts must be reviewed and tested with the code that renders them and shipped with the image; one engineer owns them. A runtime registry fits when non-engineers must change prompts without a release.
8. Task = item with inputs + criteria; trial = one attempt; transcript = full record of calls, results, reasoning; outcome = final state (answer + citations, pending action, stop reason). An agent can *say* it did something it didn't, or hide a proposed action behind a good summary.
9. Harness tests with the fake LLM (every PR), component evals (router, single-step tool choice), end-to-end agent eval with a real model (scheduled/manual).
10. Over-triggering: an agent that searches for every message (more cost, worse greetings, irrelevant citations) would look perfect on "should search" items only.
11. Free-text arguments vary between valid runs. Exact matching failed a reworded query in agentevals; ignoring arguments accepted a search with the wrong domain filter.
12. Two required searches could both be "matched" by one combined query; each spec needs its own call.
13. Fail — `forbidden_tools` counts proposals and calls past the step limit; `outcome` also fails because the turn stopped at `awaiting_approval`.
14. pass@3 = 1 − 0.25³ ≈ 98 %; pass^3 = 0.75³ ≈ 42 %. pass^3 — users ask the same kinds of questions repeatedly and expect consistent behaviour.
15. C(3,3)/C(4,3) = 1/4 = 0.25. The unbiased estimator counts the fraction of 3-trial subsets that are all successes; 0.75³ plugs in the estimated rate and is biased for small n.
16. Trials of one item are correlated (same question, same corpus, same habits); the item is the sampling unit. Coverage fell from 81 % to 73 % (all-or-nothing items).
17. Add items: repeats only reduce trial noise; between-item variance dominates. 40×3 → 40×5 barely narrows the honest interval.
18. E.g. "L2 if multi_hop + follow_up improve with the paired 95 % interval above 0, no other category drops by more than one item, median input tokens ≤ ×2.5 of L1; otherwise L1. Inconclusive → L1."
19. Batch-size-dependent numerics (no batch invariance); provider routing/Auto Exacto or a model update; `seed` is best effort; omitted vs explicit sampling parameters.
20. 429: retry up to twice with a fresh agent, then mark `infra` and exclude it from the rates (reported). 402: stop the run — the eval key's limit is reached.
21. D22 ingests the repo's own docs; the eval datasets contain questions with expected sources and must-mention answers, so the agent could retrieve the answer key.
22. Oracle trajectories must pass; targeted mutants must fail the right grader. #17's oracle test (perfect ranking → metric 1.0) and shuffle test (random ranking → metric drops).

</details>

---

## E. Verification log

| Claim | How it was checked |
|---|---|
| `llm.prompt_template.template/.version/.variables`, `prompt.id/url/vendor` exist; span kinds unchanged | `openinference-semantic-conventions` 0.1.41 `SpanAttributes` |
| `using_prompt_template` + `using_metadata` land on instrumented openai spans | openai 3.31.0 + `httpx.MockTransport`, `InMemorySpanExporter` |
| `HIDE_INPUTS` / `HIDE_PROMPTS` don't mask template variables | same test with env vars; `TraceConfig` fields listed (no variables option) |
| Plain OTel tracer ignores context attributes, `OITracer` applies them | two manual spans in one context |
| `str.format` KeyError / Helm mangling, Jinja2 syntax error / SSTI / sandbox block | Jinja2 3.1.6, Python 3.13.16 |
| Phoenix client prompts/tags/formats, `run_experiment(repetitions=…)`, single-pass formatter | arize-phoenix-client 3.5.0 signatures + `PromptVersion.format()` |
| agentevals match-mode table, dependency footprint | agentevals 0.0.9 on five trajectories |
| `hash()` salted per process | two interpreter runs |
| Coverage, power, cost tables | `sim/*.py` (numpy 2.5.4, scipy 1.18.1, fixed seeds) |
| Graders, estimators, runner behaviour | 61 pytest in the sketches |
| Not run | A real model, real OpenRouter seed behaviour, Phoenix server UI, a GitHub MCP server |

## Sources

- [Anthropic — Demystifying evals for AI agents (Jan 2026)](https://anthropic.com/engineering/demystifying-evals-for-ai-agents)
- [Sierra — τ-Bench: Benchmarking AI agents for the real world (June 2024)](https://sierra.ai/blog/benchmarking-ai-agents) · [paper](https://export.arxiv.org/pdf/2406.12045)
- [Miller — Adding Error Bars to Evals (arXiv:2411.00640, Nov 2024)](https://arxiv.org/abs/2411.00640)
- [Thinking Machines — Defeating Nondeterminism in LLM Inference (Sep 2025)](https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/)
- [OpenRouter — API parameters (`seed`, defaults)](https://openrouter.ai/docs/api/reference/parameters)
- [OpenAI cookbook — reproducible outputs with `seed`](https://developers.openai.com/cookbook/examples/reproducible_outputs_with_the_seed_parameter)
- PyPI packages listed in the header (inspected and run locally)
