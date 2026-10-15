# Batch 12 — Cost & performance

**Topics:** #39 Prompt caching · #49 Model routing & cascades · #50 Semantic caching
**Phase:** P3 (small pieces fit P1, see §5) · **Written:** 2026-10-14 · **Builds on:** #11, #12, #14, #16, #19, #26–#29, #32, #38, #40–#43, #45, #47, #48
**Sketches:** `batch-12-sketches.zip` — 88 pytest, 7 experiment scripts with outputs (e0–e6)

> **How this batch was checked.** *Run:* a breakpoint-level cache simulator fed with real request bodies from the layout builder (E1), PYTHONHASHSEED processes (E2), a routing/cascade Monte-Carlo with a paired non-inferiority test (E3), 42 hand-labelled question pairs through a real (stand-in) embedding model (E4), Qdrant's engine via qdrant-edge-py 0.8.0 (E5, tests), mocked OpenRouter streams through the OpenInference instrumentor (E0), and a mutation check of the sketch controls (E6). *Read, not run:* the Anthropic, OpenAI and OpenRouter caching/routing docs (2026-10-14), RouteLLM, cascade routing, vCache and two cache side-channel papers. *Not run:* any real model, OpenRouter, Phoenix server, Qdrant server, the production embedding model (Hugging Face is blocked here). Simulated prices and per-item probabilities are labelled as such wherever they appear.

---

## 0. Why this batch, and in which order

You already pay attention to cost: #16 showed that model choice moves cost ~30×, and #28 estimated that agentic RAG multiplies input tokens by ×1.7 / ×3.3 / ×5.4 for 1 / 2 / 3 searches, because every step re-sends everything. This batch adds three more levers. They differ in *what they risk*:

| Lever | What it saves | What it risks | Who decides correctness |
|---|---|---|---|
| **#39 Prompt caching** | Re-processing an identical prefix (input price ×0.025–0.25, lower TTFT) | Nothing about the answer — output is identical. You can *lose money* with a bad layout. | The provider (exact byte match) |
| **#49 Routing & cascades** | Price per token (cheap model where it suffices) | Answer quality on the items routed wrong | Your router + your eval |
| **#50 Semantic caching** | The whole LLM call | Silent wrong answers to *different* questions, and leaks across users | Your similarity threshold, guard and ACL checks |

That ordering is also the adoption order: prompt caching first (pure plumbing, measurable from usage fields on day one), routing second (needs the P3 generation eval), semantic caching last and only as a flagged experiment — it is the only one of the three that can make kb-agent *wrong* and *leaky* at the same time.

```
question ──► [semantic cache?] ──hit──► replay (sources → token* → done, cost 0)
                 │ miss
                 ▼
       retrieval / prefetch (#28 L1) ──► router (#49, pre-generation) ──► answer profile
                                                                              │
                         prompt layout (#39): tools | system | history | last user turn
                                                                              │
                                     provider prompt cache (exact prefix) ◄───┘
                                                                              ▼
                                   stream ──► refusal holdback (#49) ──► done (+ cache usage, route)
                                                                              │
                                                     admission (#50) ──► cache insert
```

---

## 1. #39 Prompt caching

### 1.1 Why it exists

Before a model writes its first token it must compute key/value states for every input token. If the next request starts with the same tokens, the provider can keep those states and skip the work. You see it as a cheaper input price for the reused part and a shorter time to first token. OpenAI's guide states it plainly: the cache holds KV tensors, not text, and output is unchanged — identical requests are still not guaranteed identical outputs (#42's nondeterminism is untouched).

The catch: the reuse is **exact-prefix only**. One changed byte early in the prompt — a timestamp, a reordered tool, a trimmed tool result — and everything after it is processed (and often *written*) again. Prompt caching is therefore a layout discipline more than a feature.

### 1.2 What the providers actually do (read 2026-10-14)

| | Anthropic (Claude 5.5 family, also via OpenRouter) | OpenAI GPT-5.6+ | Gemini 2.5+ (via OpenRouter) | DeepSeek / Grok / Moonshot / Groq |
|---|---|---|---|---|
| Enable | `cache_control` on blocks (≤ 4) or top-level automatic | on by default (implicit); explicit `prompt_cache_breakpoint` optional | implicit; explicit `cache_control` — only the **last** marker is used | automatic |
| Minimum prefix | **512 tokens** (Fable 5.1, Mythos 5.1, Opus 5.5, Opus 5, Sonnet 5.5, Haiku 5.5); 1,024 Sonnet 4.6/5, Opus 4.8; 2,048 Opus 4.7; 4,096 Haiku 4.5 | 1,024 visible tokens | 1,024 (2.5 Flash) / 4,096 (2.5 Pro) | small / unspecified |
| Write price | 1.25× (5 min), 2× (1 h) | **1.25×, also for automatic caching** | none extra | none extra (DeepSeek: input price) |
| Read price | **0.05×** Opus/Sonnet 5.5, 0.025× Fable/Mythos 5.1, 0.1× others (Haiku 5.5: $0.01 vs $0.10) | 0.1× (0.05× GPT-6.1 Sol) | 0.25× | 0.1 / 0.25 / 0.25 / 0.5× |
| Lifetime | 5 min or 1 h, **counted from the start of the request** that wrote or read it, refreshed by reads | ≥ 30 min after last write/read (`ttl: "30m"` is the only value) | ~3–5 min, not refreshed | provider-defined |
| Isolation | per **workspace** (Claude API, Foundry), per organisation (Bedrock, Google Cloud) | per organisation and processing region; `prompt_cache_key` for per-customer accounting | — | — |
| Rate limits | cache hits don't count against Anthropic rate limits (1 h guidance) | cached tokens **do** count toward TPM | — | — |

Two things in that table change kb-agent decisions:

- **Writes cost extra on both of kb-agent's likely answer providers.** A prompt that is sent once and never again costs *more* with caching on (×1.25 on the whole cached part). OpenAI's guide shows how to turn it off on GPT-5.6+: explicit mode with no breakpoints. On Anthropic you simply don't mark anything.
- **Read prices are model-specific and the gateway docs lag.** OpenRouter's caching page lists one Anthropic read multiplier of 0.1×; Anthropic's own table says 0.05× for Opus/Sonnet 5.5. Use OpenRouter's billed `usage.cost` (#16) as the truth and the multipliers only for estimates.

### 1.3 The breakpoint model (what the simulator implements)

Anthropic documents the mechanics precisely, and OpenAI GPT-5.6+ now works the same way in all essentials:

1. **Writes happen only at breakpoints.** A breakpoint writes one entry: a hash of everything up to and including that block. Nothing is written at earlier positions.
2. **Reads look backwards for entries that earlier requests wrote** — at most 20 positions per breakpoint (consecutive `tool_use` / `tool_result` runs count as one position). It does *not* discover stable content behind the breakpoint by itself.
3. **Order is tools → system → messages.** A change at one level invalidates that level and everything after. Tool definitions changed → everything gone. On Anthropic, `tool_choice`, adding/removing images, thinking settings and `effort` invalidate the message level. On OpenAI, `tool_choice: "none"` and `allowed_tools` are the *recommended* way to change tool availability without touching the prefix — the same parameter is cache-neutral on one provider and cache-breaking on the other.
4. **Lifetime starts when the writing request starts.** A 4-minute generation leaves 1 minute for the follow-up on a 5-minute cache.
5. **An entry is readable only after the first response begins** — parallel requests with the same prefix don't help each other.
6. **Below the minimum, nothing happens and nothing errors.** `cache_creation_input_tokens = 0` and `cache_read_input_tokens = 0` is the only sign.

`cachesim.py` implements rules 1–6 (with the documented simplifications) so you can test layouts without paying for them. Its tests replay the docs' own examples, including the "common mistake" — a breakpoint on the block that carries a timestamp writes a fresh entry every time and never reads.

### 1.4 Measured on kb-agent's request shapes (E1)

Token sizes are `len // 3` estimates (#12); costs are input cost relative to "no caching" (1.00 = same; lower is cheaper).

**A — P1 single-turn RAG** (system 300, sources 900, question 30; 400 Poisson arrivals per rate)

| Requests/hour | Policy | Sonnet 5.5 (5 m) | GPT-5.6+ | DeepSeek |
|---|---|---|---|---|
| any | automatic (top-level) | **1.25** | **1.25** | 1.00 |
| any | explicit at system (300 tokens) | 1.00 | 1.00 | 0.96 → 0.78 |
| 2 | system padded to 560 + explicit | 1.22 | 1.21 | 1.13 |
| 12 | system padded to 560 + explicit | 0.97 | 1.21 | 0.94 |
| 60+ | system padded to 560 + explicit | 0.78 | 1.21 | 0.80 |

Reading it:
- **Automatic caching on single-turn RAG is a 25 % surcharge.** Every request writes its whole prompt (sources make it unique) and nobody reads it.
- **P1's system prompt is below the 512-token minimum**, so an explicit breakpoint there is a silent no-op.
- **Padding the system prompt to cross the minimum pays only with traffic.** Break-even for Sonnet 5.5 (5 min): the padded prefix costs 560 × 1.25 cold and 560 × 0.05 warm versus 300 uncached, so it needs P(warm) ≥ 0.60 — about **11 requests per hour** with Poisson arrivals. A portfolio demo is below that. On GPT-5.6+ 560 tokens doesn't reach the 1,024 minimum at all. (OpenAI's guide has the general formula: break-even length = M·(r + (w − r)/N).)

**B — P2 agent:** 3 conversations × 6 turns × 3 model calls (tools 1,320 · system 600 · prefetch 900 · two tool results × 1,000 · 8 s between steps · 90 s between turns · two conversations overlap)

| Variant | Tokens | Sonnet 5.5 (5 m) | GPT-5.6+ | DeepSeek |
|---|---|---|---|---|
| **Good:** explicit at system + at history end + automatic tail | 1.00 | **0.33** (hit 77 %) | 0.37 | 0.31 |
| Same without the history breakpoint | 1.00 | 0.38 | 0.41 | 0.34 |
| Automatic only | 1.00 | 0.54 | 0.57 | 0.46 |
| Keep history verbatim (old sources + tool loops) | **2.53** | 0.40 (hit 91 %) | 0.52 | 0.46 |
| Timestamp in the system prompt | 1.00 | **1.25** (hit 0 %) | 1.25 | 1.00 |
| Per-turn tool routing (#29) | 0.90 | 0.41 | 0.44 | 0.37 |
| Tool list built from a set, different worker per turn | 1.00 | 0.52 | 0.55 | 0.45 |
| Ledger trimming at the last step (#28) | 0.89 | 0.28 | 0.32 | 0.27 |
| `tool_choice: "none"` at the last step (#26) | 1.00 | 0.52 | **0.37** | 0.45* |
| Sliding history window | 0.93 | 0.34 | 0.38 | 0.31 |
| Chunked history trimming | 0.97 | 0.34 | 0.37 | 0.32 |

\* the DeepSeek column treats `tool_choice` as part of the prefix (not documented either way).

Reading it:
- **A good layout cuts agent input cost to about a third.** Agentic RAG is where caching earns its keep, because each step re-sends the previous step plus a little.
- **One timestamp in the system prompt turns a 3× saving into a 25 % surcharge.**
- **The history breakpoint matters** with text-only history (#12): turn *N+1* rewrites turn *N*'s user message (sources dropped, tool loop dropped), so reuse across turns ends at the previous history; without a marker there, no entry was ever written at that position.
- **Keeping history verbatim "for the cache" is a false economy:** 2.5× the tokens; even at 0.05× reads it costs more than dropping old sources, and #12's focus argument still holds.
- **Not every prefix change is bad.** Trimming tool results at the last step rewrites part of the prefix but removes more tokens than the rewrite costs (0.28 < 0.33). Rule of thumb: rewrite when saved tokens × remaining requests > rewritten tokens × (w − r).
- **`tool_choice: "none"` at the step limit costs Anthropic users the message cache on that step;** on OpenAI it is free. Turns that hit the limit are rare, so this is a note in the profile, not a reason to change #26.
- **Sliding vs. chunked history barely matters here** — history pairs (~340 tokens) are small next to 2,000 tokens of tool results per turn. It matters for long chat-only conversations; the stepped trim in `layout.py` is cheap insurance.

**C — Resuming after an approval pause (#32)** (Sonnet 5.5; input cost of the proposing and the resuming request together)

| Pause | 5-min TTL (write 1.25×) | 1-h TTL (write 2×) |
|---|---|---|
| 1 – 4.8 min | **0.66** | 1.04 |
| 5 – 58 min | 1.25 | **1.04** |
| > 1 h | 1.25 | 2.00 |

The 1-hour cache wins only if fewer than ~36 % of approvals arrive within ~5 minutes (0.66 p + 1.25 (1 − p) = 1.04). You have the data for that decision in the `approvals` table (`decided_at − created_at`) — default to 5 minutes and switch when the median approval takes longer.

### 1.5 Layout rules for kb-agent

`layout.py` encodes them; `audit.py` checks them:

1. **Stable before variable:** tools → system rules → history → last user turn. Already the #12 order — keep it.
2. **Tools canonical:** sorted by name, keys sorted recursively, built from a list, never from a set. E2: building the list by iterating a `set` gave **19 different tool prefixes in 20 processes** (`PYTHONHASHSEED` salts set order); sorted + `sort_keys` gave 1. The same applies to any dict you build from a set before serialising.
3. **System = versioned rules only** (#38 bundle). Date, memory (#51), user names, sources go in the **last user turn**. #51 already put memory there for safety; caching is a second reason.
4. **Three markers in agent mode:** end of system (shared by every conversation in the workspace — tools + system are identical for all users), end of history (turn-to-turn reuse), automatic tail (agent steps). That is 3 of Anthropic's 4 slots; the automatic marker uses one.
5. **Normalise every message to content-part form.** A marker is attached to a content part; if adding it turns `"content": "x"` into `[{"type": "text", "text": "x"}]`, next turn's unmarked copy has a different representation. The simulator caught exactly this bug in the first version of the experiment.
6. **Trim in steps, not one pair per turn.**
7. **Single-turn RAG (P1, L0/L1 first turns): no caching** unless the shared prefix exceeds the model minimum *and* traffic keeps it warm. On GPT-5.6+ send `prompt_cache_options: {"mode": "explicit"}` without breakpoints to avoid write charges.
8. **One marker style:** OpenRouter translates a block-level `cache_control` into OpenAI's `prompt_cache_breakpoint` and back (TTLs are not translated towards OpenAI), and Gemini uses only the last marker. Gemini also treats the first system message as immutable — dynamic content must go to a later user message, which rule 3 already does.

### 1.6 The gateway in between (OpenRouter)

- **Sticky routing** keeps a conversation on the provider that holds its cache: keyed per account, model and conversation (hash of the first system and first non-system message), or by an explicit `session_id` (≤ 256 characters, body or `x-session-id` header; `prompt_cache_key` is the fallback). Sticky sessions expire after 10 minutes of inactivity (the Pareto Router page says 5 — the docs disagree).
- **Sticky routing is off when you set `provider.order`.** kb-agent pins `order` + `allow_fallbacks: false` (#19, ADR-0005) with one provider, so every request reaches the same cache anyway. If you ever list two providers, stickiness won't help you — the order will.
- **`session_id` still groups requests in OpenRouter's Logs**, which is useful for debugging agent turns. Send an HMAC of the conversation id, not the id itself (#19: the gateway keeps metadata).
- **Model fallbacks (`models: [...]`) switch model on any error** — context length, moderation, rate limits, downtime — and bill the model that answered. A fallback model has a cold cache and its own data policy. If you use them, every listed model must pass the ADR-0005 filter (ZDR, cancellation, reasoning) and the `model` in the response must be logged.

### 1.7 Observability

- **Normalise usage.** OpenRouter/OpenAI Chat: `prompt_tokens` *includes* cached tokens, details in `prompt_tokens_details.{cached_tokens, cache_write_tokens}`. Anthropic native: `input_tokens` *excludes* reads and writes — total = input + cache_read + cache_creation. `usage.py` handles all three; summing raw `input_tokens` across providers under-counts.
- **The instrumentor already records it.** E0, mocked OpenRouter stream and non-stream through openinference-instrumentation-openai 0.1.65 with openai 3.31.0: both paths set `llm.token_count.prompt_details.cache_read` and `…cache_write` on the LLM span. Cost attributes (`llm.cost.prompt_details.cache_read` exists in semconv 0.1.41) are *not* set — Phoenix computes cost from its price table. Whether Phoenix prices cached tokens at the cache rate is unverified; keep `costUsd` from `usage.cost` as the number you report.
- **Add to `done.usage` and the log line:** `cachedInputTokens`, `cacheWriteTokens` (camelCase, §7.3 style). Dashboard metric: token hit ratio = cached ÷ total input, by route and day.
- **When the hit ratio drops,** `audit.first_divergence(prev, next)` names the first differing block and the likely cause (model / tools / system / params / conversation rewritten). Both Anthropic and OpenAI now also offer server-side cache diagnostics that compare consecutive requests; the offline audit runs in CI where no provider is called.

### 1.8 Privacy and the cache

- **Caches are shared within your workspace (Anthropic API) or organisation (OpenAI).** That is what makes the shared tools + system prefix work across users — and it means kb-agent's *own* users share one cache.
- **Cache hits are observable.** Gu et al. (ICML 2025) audited 17 LLM APIs, found prompt caching in 8 and global cache sharing across users in 7 (OpenAI among them); at least five providers mitigated after disclosure. Song et al. built prompt-stealing and "peeping neighbour" attacks on KV and semantic caches from timing alone. OpenAI's guide now suggests separate `prompt_cache_key`s per customer, partly because they help prevent cache-hit probing across users.
- **What this means for kb-agent:** the provider's cache is isolated from other organisations; inside your organisation, a kb-agent user could in principle time requests to learn whether another user recently sent the same *prefix* — but only prefixes the attacker can reproduce byte-for-byte (tools, system, the attacker's own guesses at a whole earlier conversation). With per-conversation history and sources in the last user turn, that is a weak channel. The same channel is much stronger in your **own semantic cache** (§3.7).
- **Retention:** Anthropic holds KV states and hashes in memory only and marks prompt caching ZDR-eligible; OpenAI GPT-5.6+ caches ≥ 30 minutes, and on earlier models ZDR organisations default to in-memory retention. OpenRouter's ZDR allows in-memory caching (Batch 4 finding). Nothing here changes D25.

### 1.9 Pitfalls

1. Automatic caching on single-turn prompts: +25 % on Anthropic and GPT-5.6+.
2. Prefix below the minimum: silent no-op. Check `cache_write_tokens` after the first request.
3. Timestamp, user name, memory or sources in the system prompt.
4. Tool list from a set or a dict built from a set; per-turn tool routing that changes the `tools` array.
5. A breakpoint on the block that changes every request.
6. Agent turn growing more than 20 blocks past the last write — add a breakpoint earlier.
7. Representation changes (string vs. content parts) when a marker moves.
8. Changing `tool_choice`, thinking or `effort` mid-turn on Anthropic; changing model mid-turn anywhere (caches are per model, §4).
9. Treating a 5-minute TTL as "5 minutes after the answer" — it counts from the request start.
10. Assuming parallel requests share a cache (the entry exists only after the first response starts).
11. Trusting one multiplier table. Use billed cost.
12. Summing Anthropic `input_tokens` as prompt size.
13. Keeping full history "because it's cached" — more tokens, worse focus.

### 1.10 Plan mapping

| Where | Change |
|---|---|
| P1 · M1.3 prompt builder | Keep date line out of the system prompt; canonical serialisation; **no caching** (mode `off`) |
| P1 · `done.usage`, log line | `cachedInputTokens`, `cacheWriteTokens` via `usage.normalise` |
| ADR-0005 / model profile | `cache: {mode, ttl, min_tokens, read_mult, write_mult, params_in_prefix, policy_checked}`; cache read price joins the model filter |
| P2 agent loop | `explicit+auto` with the history marker; append-only steps asserted by an audit test; tools fixed per conversation (§4) |
| P2 approvals (#32) | TTL policy from the approval-delay distribution |
| CI (D19) | `test_agent_steps_are_append_only`, canonical-tools test across `PYTHONHASHSEED`s — free, no provider |

---

## 2. #49 Model routing & cascades

### 2.1 Why, and the vocabulary

A strong model for everything is the quality ceiling and the cost ceiling. Most kb-agent questions ("Wie starte ich einen Pod neu?") don't need it; some ("compare the rollback runbook with ADR-0004's alias rules") do. Routing spends the expensive model where it changes the outcome. The terms get mixed up, so:

| Term | Decides | When | kb-agent example |
|---|---|---|---|
| **Role profiles** (static routing) | which model per *task type* | design time | `answer` / `agent` / `router` / `judge` profiles (#27) — you already have this |
| **Router** (dynamic) | which model per *request* | before generation | rules on prefetch scores, domains, multi-hop signals |
| **Cascade** | whether to *also* ask a bigger model | after generation, on a check | QueryPlan fails validation → retry on the strong model |
| **Cascade routing** | both, generalised | iteratively | Dekoninck et al. (ICML 2025): route, check, re-route; proves the optimal strategies and finds the **quality estimator** is what decides success |
| **Fallback** | another model when this one *errors* | on failure | OpenRouter `models: [...]` — availability, not quality |
| **Gateway routers** | a model chosen *for* you | per request | OpenRouter Auto Router, Pareto Router |

RouteLLM (ICLR 2025) is the reference for learned routers: classifiers trained on Chatbot Arena preferences (plus augmentation) that pick between one strong and one weak model, reporting more than 2× cost savings on public benchmarks without losing quality. It also gave the field its metrics: **PGR** (share of the strong–weak quality gap recovered), **APGR** (area under PGR over the share of calls sent to the strong model; random routing = 0.5) and **CPT** (strong-call share needed to reach a target PGR). `stats.py` implements PGR/APGR.

### 2.2 The constraint that shapes everything: the answer streams

A cascade judges the cheap answer *after* it is written. kb-agent streams answers token by token (#14). So a cascade on the answer must either:
- **buffer** the cheap answer until the check passes — TTFT becomes the whole cheap generation plus the check (E3: 0.6 s → 2.75 s with a deterministic check, 4.55 s with an LLM judge), or
- **show** the cheap tokens and then retract them — breaking the `sources → token* → done` contract (#14) and the user's trust.

Hence the split:
- **The streamed answer is *routed* before the first token** (`router.py`), on features that exist at that point: the L1 prefetch scores (#28), the router's domains (#29), the QueryPlan (#23), write intent.
- **Non-streamed structured calls are *cascaded*** (`cascade.py`): QueryPlan, RouteDecision, judge verdicts, memory extraction, synthetic questions. Nobody waits for their tokens, and their checks are machine-checkable (#27).
- **One exception streams fine: the refusal holdback** (`holdback.py`). Tokens are held back only while the text is still a prefix of the shared refusal sentence (#10, #40). The first diverging token flushes everything — normal answers lose at most a few characters of latency. If the stream ends as exactly the refusal, nothing has been shown, and when the prefetch evidence was strong (top-1 above a calibrated floor) the harness asks the strong model instead. That targets #45's `refused_wrongly` failure directly. Same mechanics as #48's redaction holdback; emitted text is always a prefix of the final text (tested at every split position).

### 2.3 A router for kb-agent

**Features available before the first token** (no extra LLM call): prefetch top-1 and top-2 dense scores, number of sources surviving the gate (#11), distinct source domains, multi-hop wording (EN/DE), follow-up flag, code sources (#25), write intent from the QueryPlan. Policy `route-rules@v1`: strong if any of *write intent, ≥ 2 domains, multi-hop wording, weak evidence (top-1 below a calibrated floor), ambiguous evidence (tiny top-1/top-2 margin with ≥ 3 sources), code, follow-up*; cheap otherwise. Every decision carries **reason codes** — on the DECISION span (#29), in `done.route`, and in eval reports, so you can see *why* items were routed.

**Rules first, learned later.** A learned router needs labels you don't have yet: for each item, "did the cheap model suffice?" — which means running **both** models with repeats on every item. When you have them, `calibrate_threshold()` picks the threshold that routes the most items cheap while the one-sided 95 % upper bound of "cheap wasn't good enough" among them stays under your loss budget (exact binomial bound — the same discipline as #11's 0/8 and #46's 0/45 lessons).

**Route once per turn, never per step.** Caches are per model (§1), so switching models mid-turn rewrites the whole prefix at write price. And on Anthropic models, reasoning blocks are tied to the model that produced them: a block the receiving model can't read is dropped and changes the cached prefix from there (Batch 5 already found Sonnet/Haiku 5.5 thinking is account-bound). A turn = one answer profile.

**What about the agent model?** The agent role (L2) chooses tools and writes queries — failures there show up as wrong tool calls, which #42's agent eval measures. Start with a fixed agent profile; route only the *answer* step's model once the generation eval (#40) exists.

### 2.4 Cascades for structured calls

`run_cascade(steps, check, is_unsure)`: cheapest profile first, escalate on **checkable** failures only:

| Signal | Escalate? | Why |
|---|---|---|
| invalid JSON, schema error, `extra="forbid"` violation | yes | #27: the check is exact |
| semantic check fails (empty query, unknown domain) | yes | cheap, deterministic |
| `finish_reason: "length"` | yes | truncated output never validates |
| the schema's own **"unsure" exit** (#27) | yes | the cheap model's honest abstention is your best free quality estimator |
| model/provider **refusal** | **no** | escalating a refusal shops for a model that complies |
| **402** budget exhausted / cancellation | **no** | stop the turn (#14, #16) |

The failed cheap attempt is part of the price (`CascadeResult.cost_usd` sums all attempts, and stays `None` if any cost is unknown — #16's rule). Record every attempt on the span: profile, outcome (`accepted`, `escalated:schema:json_invalid`, …), cost, seconds.

**#27's corrective retry vs. escalation:** a corrective retry on the *same* cheap model fixes formatting slips cheaply; escalation fixes capability gaps. Use one corrective retry for syntax errors, escalate on semantic failures and "unsure".

### 2.5 What the trade-off looks like (E3, synthetic)

Synthetic population: 45 items, 17 "hard"; strong pass rate 0.864, cheap 0.716. Prices are Anthropic list prices (Haiku 5.5 $0.10/$0.50, Sonnet 5.5 $2/$10 per MTok) for a 1,300-in / 300-out answer: cheap $0.00028, strong $0.0056 (20×). Latencies are placeholders.

| Strategy | Quality | Δ vs strong | Cost vs strong | Strong share | Mean TTFT |
|---|---|---|---|---|---|
| Strong only | 0.864 | — | 100 % | 100 % | 1.50 s |
| Cheap only | 0.716 | −14.8 pts | 5 % | 0 % | 0.60 s |
| Router (rules catch 75 % of hard, send 20 % of easy) | 0.819 | −4.6 pts | 44 % | 41 % | 0.97 s |
| Router + refusal holdback | 0.844 | −2.0 pts | 47 % | 44 % | 1.04 s |
| Cascade, deterministic check (catches 30 % of bad answers) | 0.786 | −7.8 pts | 15 % | 10 % | 2.75 s |
| Cascade, LLM judge (catches 70 %, 5 % false alarms) | 0.880 | +1.6 pts | 33 % | 23 % | 4.55 s |

What to take from it, independent of the made-up probabilities:
- **The check bounds the cascade.** A deterministic check that catches 30 % of bad answers (most wrong answers are well-formed) leaves most of the gap in place.
- **A judge-checked cascade can beat the strong model** because a rejected cheap answer gets a second, independent try. That depends on cheap and strong failures being independent; in reality hard items fail both, so treat the +1.6 as an upper bound.
- **The cascade's TTFT is the price** (4.55 s), which is why it doesn't belong on the streamed answer.
- **The refusal holdback recovers ~2.5 points for 3 % of the strong cost** — cheapest improvement in the table, because it only acts on a failure the user would otherwise see.

### 2.6 Evaluating a router: you can't show "as good", only "not worse by more than X"

The decision question is *non-inferiority*: is the routed system not worse than the strong model by more than a margin (say 5 points), and how much cheaper is it? `paired_noninferiority()` compares per-item means (items are the unit, repeats are not independent — #42) and returns `non_inferior` / `inferior` / `inconclusive`.

E3, 2,000 simulated campaigns per cell, both arms with the same number of repeats:

| Candidate (true Δ) | Repeats | Non-inferior | Inconclusive | Inferior |
|---|---|---|---|---|
| Strong vs. itself (0) | 1 / 3 / 5 | 19 / 34 / 48 % | 80 / 66 / 52 % | 1 / 0 / 0 % |
| Router (−4.6) | 1 / 3 / 5 | 7 / 6 / 6 % | 89 / 91 / 90 % | 5 / 3 / 4 % |
| Router + holdback (−2.0) | 1 / 3 / 5 | 11 / 17 / 22 % | 88 / 82 / 78 % | 1 / 1 / 0 % |
| Cascade + judge (+1.6) | 1 / 3 / 5 | 25 / 50 / 65 % | 75 / 50 / 35 % | 0 / 0 / 0 % |
| Cheap only (−14.8) | 1 / 3 / 5 | 0 / 0 / 0 % | 70 / 41 / 24 % | 30 / 60 / 76 % |

- **At 45 items, "inconclusive" is the normal outcome** — even a system compared with itself is confirmed non-inferior only a third of the time with 3 repeats. To confirm non-inferiority with 80 % power at a 5-point margin when the true difference is 0, this population needs **~190 items × 3 repeats** (~114 × 5, ~564 × 1).
- **So write the decision rule for the inconclusive case first** (#43): e.g. "adopt the router if non-inferior on the full set, *or* if inconclusive overall but no targeted slice (multi-hop, near-miss, code) is inferior and it saves ≥ 40 %". That is a cost decision under uncertainty, recorded in the ADR — not a proof.
- **Grow targeted slices rather than repeats** (#42): routing errors concentrate on hard items. A 12–16-item `multi_hop` slice detects large losses; a whole-set comparison can't see a 4-point average loss.
- **Report the cost–quality picture, not one number:** cheap-only, strong-only, the router at several thresholds (an APGR curve) and the Pareto front. A router that isn't on the front is dead weight.

**Labels cost money.** Building "cheap suffices" labels means both models × all items × repeats — at Haiku/Sonnet 5.5 prices for 190 items × 3 repeats × 2 models that is roughly 190 × 3 × ($0.00028 + $0.0056) ≈ $3.35 for the answers alone (estimate; judge cost extra). Cheap by kb-agent standards, but use the separate eval key (#42).

### 2.7 OpenRouter's own routers

- **Auto Router** (`openrouter/auto`): classifies the prompt into one of ~30 task types and picks models by the *market's* spend share over a trailing 7-day window, within a `cost_tier` band; it honours account restrictions, ZDR policies and `allowed_models`, adds no fee, reports the chosen `model` in the response and keeps a conversation on its model while it stays a top candidate. For kb-agent it is useful as a **baseline arm** in an eval, not as production routing: the choice changes week to week with other people's spending (not reproducible, #42), it optimises for what's popular rather than your golden set, and two gotchas apply — settings sent under the other slug's plugin id (`auto-router` vs `auto-beta-router`) are accepted and **silently ignored**, and `cost_tier` is a band, so it also excludes models *cheaper* than the band.
- **Pareto Router** (`openrouter/pareto-code`): coding only, picks the cheapest model above an Artificial Analysis coding percentile. Not for kb-agent's answers; possibly for a code-review skill later.
- **Model fallbacks** (`models`): availability failover (§1.6). Not a quality cascade.

### 2.8 Observability and contract

- DECISION span (`kb.route.profile`, `kb.route.reasons`, `kb.route.policy`; no question text — `span_attributes()` is tested for that). Cascade attempts on the span of the structured call.
- `done` gains `route: {profile, reasons, escalated}`; the per-request log line gets the same. Cost per route and escalation rate per day on the status page.
- The feedback loop (#45) gets a new triage dimension: thumbs-down rate by route. A route with a higher thumbs-down rate is a router bug candidate, not just a model one.

### 2.9 Pitfalls

1. Cascading the streamed answer: buffering kills TTFT, streaming-then-retracting breaks the contract.
2. Escalating on self-reported confidence without calibrating it — "unsure" is a *schema* signal you test like any classifier, not a probability.
3. Escalating refusals, 402s or cancellations.
4. Switching models mid-turn: cache rewrite at write price, reasoning blocks dropped or rejected.
5. Routing labels from one run per model (#42: repeats).
6. Comparing a router to the strong model with a "difference not significant" test and calling it equal. Non-inferiority, margin written first.
7. Forgetting the failed attempt's cost.
8. Using a gateway auto-router in an eval baseline without recording the resolved model per request.
9. Fallback models outside the ADR-0005 filter (data policy, cancellation).
10. A router whose thresholds are cosine scores from one embedding model (#4) — recalibrate on every embedding change (#9), like the abstention gate.

### 2.10 Plan mapping

| Where | Change |
|---|---|
| P1 | Static role profiles are routing level 0 — nothing to build |
| P2 | Cascade for QueryPlan/router/judge structured calls (profile chain in the model profile file) |
| P3 · ADR-0017 | Router policy (rules v1), features, profiles `answer.cheap` / `answer.strong`, escalation floor, margin, decision rule with an inconclusive branch |
| P3 · eval | `routing_v1`: both-model labels with repeats (separate eval key), non-inferiority + per-slice report + APGR curve |
| SSE `done`, log line | `route: {profile, reasons, escalated}` |

---

## 3. #50 Semantic caching

### 3.1 Why, and the honest expectation

A semantic cache answers a *new* question with an *old* answer when the questions are close enough in embedding space. Hit = no retrieval-to-generation round trip, no tokens. The appeal is obvious; the catch is that "close in embedding space" is not "has the same answer" (§3.3), and that a cache shared across users is a channel between them (§3.7).

How much would it save in kb-agent? It depends entirely on how often questions repeat *within the cache lifetime and scope*. A portfolio deployment with a handful of users repeats little. Measure before building: replay the per-request log (question hashes + scope) and count near-duplicates, or simulate on `retrieval_v1` + synthetic paraphrases (#44). If the projected hit rate is single-digit percent, the cheaper caches below deliver most of the benefit with none of the risk.

### 3.2 The cache ladder (cheapest and safest first)

| Cache | Key | Risk | Status |
|---|---|---|---|
| Embedding cache | exact normalised query text + model | none | trivial; saves CPU (#5) |
| Retrieval cache | exact query vector hash + filters + **principal set** + index build | ACL (#47) if the principal set is missing | small; saves Qdrant time only |
| QueryPlan / rewrite cache | already in #23 (bundle + history hash) | low | done |
| Judge verdict cache | already in #41 | none | done |
| Contextual-retrieval cache | already in #24 | none | done |
| Provider prompt cache | exact prefix (§1) | none for answers | §1 |
| **Semantic answer cache** | scope + similarity + guard + serve-time ACL | wrong answers, leaks, poisoning | experiment behind a flag |

### 3.3 Correctness: similarity is not "same answer" (E4)

42 hand-labelled kb-agent question pairs: 18 paraphrases (same answer) and 24 near misses (different answer: environment, version, number, negation, direction, platform, identifier, and 4 purely semantic ones). Embeddings from WordLlama `l2_supercat_256` — a *stand-in*: static token embeddings whose weights ship inside the PyPI wheel, English-only, not your production embedder. The pattern, not the exact scores, is the result; re-run E4 with multilingual-e5 on the Mac.

- Paraphrases: min 0.616, median 0.832. Different-answer pairs: **max 0.978**, median 0.846 — **13 of 24 different-answer pairs score above the median paraphrase.** "Upgrade Keycloak from 26.7 to 26.8" vs "from 26.6 to 26.7": 0.978. "Which documents can a viewer see?" vs "…not see?": 0.969. "Roll back in staging" vs "in production": 0.863. The true paraphrase "roll back a deployment" vs "revert a deployment to the previous version": 0.616.
- **No threshold separates them.** At 0.95 the cache still serves 8 of 24 wrong answers while hitting only 22 % of paraphrases.
- **A discriminator guard fixes the lexical cases:** require the same *literal tokens* (numbers, versions, identifiers, flags, camelCase, backticked spans — #21's exact-token family) and the same *contrast classes* from a small reviewed DE/EN lexicon (prod/production/live → `env:prod`; not/nicht/without → `neg`; enable/turn on → `dir:enable`; AKS vs EKS…). With the guard: **20 of 20 lexically detectable near misses blocked**, 0 false hits at threshold ≥ 0.85, 2 of 24 at 0.75 — both from the "semantic" category (approves vs executes; access vs refresh token lifetime), which no lexicon can see. Cost: 1 of 18 paraphrases falsely blocked ("stop" vs "cut off"). False misses are safe; false hits are not.
- **0 of 24 is not "zero risk":** the exact one-sided 95 % upper bound is 11.7 %. Calibrate on a labelled pair set as large as you can afford, report the bound, and set the threshold for a false-hit target, not for hit rate (§3.9).
- **Static thresholds can't give guarantees** — vCache (ICLR 2026) learns a separate threshold per cached entry online and reports up to 12.5× higher hit rates and 26× lower error rates than static-threshold baselines. Worth knowing; for kb-agent's volume, a static threshold + guard + conservative TTL is the proportionate version.
- **Language is part of the answer.** A multilingual embedder puts "Wie rolle ich zurück?" next to "How do I roll back?" — and serving the English answer breaks #10's "reply in the user's language". Language is in the scope key.

### 3.4 Scope: what must match exactly

`Scope` (keys.py) — similarity is only compared within one scope:

| Field | Why |
|---|---|
| `bundle` (#38) | different rules, refusal sentence or source layout → different answer |
| `answer_profile` | model + provider + sampling params; the router's choice (§2) |
| `index_build` (#9) | a re-index (new model, new chunking) starts a new scope; old entries age out |
| `lang` | §3.3 |
| `domains` | the user's convenience filter (#7) changes the candidate set |
| `mode` | L0 / L1 / L2 (#28) are different pipelines |

**Not in the key: the principal.** This answers the question parked in Batch 10. Two options:
- *Key on the principal set* (ancestor-expanded groups + user): correct, but fragments the cache into one partition per distinct group set — at kb-agent's volume, almost no hits.
- **Check at serve time** (recommended): an entry stores its source document ids and versions; a hit is served only if the asker can read **every** source document *now* (#47's reference predicate, against Postgres) and every source is still at the stored version. Revocation takes effect immediately, entries are shared, and a user who can read more simply gets the shared answer (a quality issue, not a leak). Start with `org_only` admission (only answers built entirely from `org` documents) and widen once the serve-time check has its own red-team items.

### 3.5 Admission: a cache amplifies whatever it admits

One admitted answer is replayed to everyone whose question lands near it — including a poisoned one. Admit only answers that passed everything kb-agent already checks (`admission.py`):

| Rejected | Reason |
|---|---|
| not standalone (follow-up without a #23 rewrite) | "and in staging?" means nothing without its history |
| refusal, partial, abstained | refusals go stale on the next upload; pipeline abstentions (#11) cost nothing to recompute |
| cancelled, `finish_reason ≠ stop` | incomplete |
| invalid citations or uncited segments (#10, #40) | unverified |
| any guard code (#48) | PII redacted, injection-flagged sources |
| memory used (#51) | personalised — another user's goals in the answer |
| any tool other than `search_kb` | web/SQL/GitHub results are live data; write tools have side effects |
| no sources; non-`org` sources (initially) | §3.4 |

Two further defences against cache poisoning (an attacker crafting a question whose bad answer then reaches others): a **TTL** (24 h is plenty for a docs assistant), and **feedback eviction** — a thumbs-down or a "regenerate" click on a cached answer evicts the entry (#45). A stricter option is "admit only after k distinct askers": it bounds poisoning and the timing channel but needs a pending state; not worth it until the cache proves useful.

### 3.6 Invalidation

| Event | Action | Note |
|---|---|---|
| Document re-ingested, deleted, ACL changed | `invalidate_docs(ids)` → `match.any` on `source_doc_ids` | plus the serve-time version check as a second line |
| New document ingested | `invalidate_domains(domains)` | doc-based invalidation can't see this: the new doc was never a source, yet it may answer cached questions better |
| Re-index / alias swap (#9) | nothing — new `index_build` = new scope | purge the old scope lazily |
| Bundle or answer-profile change | nothing — new scope | |
| TTL | `purge_expired()` nightly | |
| Thumbs-down / regenerate | `evict(entry_id)` | |

Two Qdrant facts, verified on the engine (E5):
- **A `should` list built from an empty input matches everything.** An invalidation helper written as `Filter(should=[MatchValue(d) for d in doc_ids])` with `doc_ids = []` deleted the *entire* cache (the same trap that leaked documents in #47; here it destroys). `invalidate_docs([])` is a no-op in the sketch, uses `match.any`, and a test keeps the engine fact visible. Never share such a helper with the knowledge-base collection.
- **Entries without sources are invisible to doc-based invalidation.** A cached "not in the knowledge base" survives every document invalidation — after you upload the missing runbook, the cache keeps refusing. That is why refusals are not admitted.

### 3.7 Confidentiality: the cache is a channel

- **Content:** covered by the serve-time ACL check and `org_only` admission — a user never receives an answer built from documents they can't read, even if the entry was written by someone who could.
- **Existence and timing:** a hit returns in milliseconds, a miss in seconds. With an org-wide scope, any user can probe "has someone recently asked something close to X?" — Song et al.'s *peeping neighbour* attack, with semantic search making the guesses cheap. In a DevOps knowledge base the questions are mostly harmless; "How do I revoke access for a leaving employee?" isn't. Options, in order of strength: per-user scope (safe, few hits), org scope with only `org` answers and a TTL (the default here — say so in the system card, #59), k-distinct-askers admission, padding hit latency (weak; streaming makes it hard).
- **Origin data:** the entry's original question and trace id belong to another user's request. `replay.py` sends the *current* request's trace id; the stored question never reaches the browser.

### 3.8 Replay and UX

`replay_events()` keeps the #14 contract: `sources` (fresh source cards for the stored refs, numbers unchanged — #10 never renumbers) → `token`* → `done`. In `done`: `usage.costUsd = 0.0` — *true* here, unlike a cancelled stream whose cost is unknown and must stay `null` (#16) — and `cache: {hit, entryId, similarity, createdAt}`. The UI labels the answer ("cached answer from 14 Oct") and offers **Regenerate**, which bypasses the cache; a thumbs-down on a cached answer evicts the entry. Rate limiting (D24): cache hits cost nothing but still count toward the per-user request throttle — otherwise probing is free.

### 3.9 Evaluating a semantic cache

- **Primary metric: false-hit rate** on labelled pairs, with an upper confidence bound; secondary: hit rate on paraphrases, cost saved, latency. A cache that is "right 95 % of the time" serves a confident wrong answer to one asker in twenty.
- **`semcache_pairs_v1`:** paraphrases (same answer) and near misses (different answer) for each discriminator category plus "semantic" ones, DE + EN + cross-language. Written by hand from `retrieval_v1` items and real feedback (#45), synthetic paraphrases allowed after review (#44). Labels are about *answers*, so write them against the source sections.
- **Replay evaluation:** run the per-request log (or a synthetic stream) through the cache offline with the production embedder; count hits, then *judge every hit* (#41) or check it against the pair labels. Decision rule first: e.g. "enable if false-hit upper bound ≤ 2 % and projected savings ≥ 15 % of answer cost".
- **Red-team items (#46):** poison-then-replay (an injection-flagged answer must never be admitted), revoke-then-ask (ACL change must miss immediately), cross-language serve (language mismatch must miss), probe timing (documented, not blocked, unless per-user scope).

### 3.10 Pitfalls

1. One global threshold tuned for hit rate.
2. No discriminator check: versions, environments, negation, direction, identifiers.
3. Principal in neither key nor serve-time check → cross-user leak; principal in the key → no hits.
4. Caching follow-ups, memory-personalised answers, tool-dependent answers, refusals.
5. Doc-based invalidation only — new documents never invalidate.
6. An invalidation filter built from an empty list.
7. Language not in the scope.
8. Replaying the origin trace id or question to another user.
9. `costUsd: null` on hits (it is truly 0) or `0` on cancels (it is unknown).
10. Hits not counted by the throttle.
11. Measuring a cache by hit rate alone.
12. Building it before measuring repetition in real traffic.

### 3.11 Plan mapping

| Where | Change |
|---|---|
| §13.4 | "Semantic cache" becomes: cache ladder; semantic answer cache as a flagged experiment (ADR-0018) with scope, guard, serve-time ACL, admission, invalidation, `done.cache` |
| Qdrant | collection `kb_semcache__{embedder}` (dim = query embedder), keyword indexes `scope`, `source_doc_ids`, `domains`, float index `expires_at` — created with the collection (#7) |
| Ingest/delete/ACL paths (Nest + AI service) | call `invalidate_docs` / `invalidate_domains` |
| UI | cached-answer label + Regenerate |
| Eval | `semcache_pairs_v1`, replay evaluation, red-team items |

---

## 4. How the three interact

- **Routing vs. prompt caching.** Caches are per model. Every routing decision that differs from the previous turn's model starts that turn cold, and the shared tools+system prefix is per model too — two answer profiles means two warm-ups. Route per turn (not per step), and prefer few profiles.
- **Tool routing (#29) vs. prompt caching.** A per-turn tool subset changes the `tools` array — the first level of the prefix (E1: 0.33 → 0.41). Alternatives: expose a stable superset for the whole conversation and enforce the routed subset at *execution* (ToolPolicy is authoritative anyway, #33 — a call to a non-routed tool becomes a tool error message); on OpenAI models, `allowed_tools` restricts calls without changing the prefix. Whether a smaller tool list helps the model choose better is an agent-eval question (#42) — test it, don't assume it.
- **Semantic cache vs. routing.** The answer profile is in the scope, so entries written by the cheap model are only served to questions routed cheap. That keeps quality honest but halves the effective cache. Fine.
- **Semantic cache vs. prompt cache.** A semantic hit skips the LLM call entirely, so it also skips warming the provider cache. Irrelevant at kb-agent's volume; worth knowing when reading hit-ratio dashboards.
- **Cost accounting.** One answer = possibly a held refusal + an escalated call, or a cache replay at $0, or a cascade with a failed attempt. `done.usage.costUsd` is the sum; `done.route` and `done.cache` explain it. Budgets (D24) see the sum.
- **Throttle and probing.** Cache hits and cheap routes still count as requests for the per-user throttle.

---

## 5. What fits Phase 1 now

All small, none needs a P3 component:

1. **Prompt layout as specified in §1.5** — mostly what #12 already says; add canonical tool serialisation (no tools in P1, but the builder is reused in P2) and keep the date in the last user turn. ~30 min.
2. **No prompt caching in P1** (mode `off`; on GPT-5.6+ models, explicit mode without breakpoints). E1-A: automatic caching would add 25 %.
3. **Model profile `cache` block** with `mode: off` and the multipliers, so P2 flips a setting instead of writing code.
4. **Cache usage in `done.usage` and the log line** (`cachedInputTokens`, `cacheWriteTokens`) via `usage.normalise()` — the instrumentor already puts them on spans (E0).
5. **Static role profiles** (`answer`, later `router`/`judge`) are routing level 0 — already planned (#27).

---

## 6. Plan change list (for plan v3 / the Phase 3 plan)

1. **Model profile:** `cache: {mode: off|explicit|explicit+auto, ttl: 5m|1h, history_breakpoint, min_tokens, read_mult, write_mult, params_in_prefix, policy_checked}`; ADR-0005 filter adds cache read price and minimum.
2. **Prompt builder:** layout rules §1.5; `audit` tests in CI (append-only agent steps, canonical tools across hash seeds).
3. **SSE contract (§7.3):** `done.usage` gains `cachedInputTokens`, `cacheWriteTokens`; `done.route` (`profile`, `reasons`, `escalated`); `done.cache` (`hit`, `entryId`, `similarity`, `createdAt`). Bump the contract version (Batch 5's change list already adds one).
4. **Approvals (#32):** cache TTL chosen from the approval-delay distribution; record `decided_at − created_at`.
5. **Tools (#29/#33):** stable tool set per conversation; per-turn routing enforced at execution — decide by agent eval.
6. **ADR-0017 Routing:** rules v1, features, profiles, escalation floor for the refusal holdback, non-inferiority margin and decision rule with an inconclusive branch; `routing_v1` labels (both models × repeats) on the eval key.
7. **Cascades for structured calls:** profile chains for QueryPlan, router, judge, memory extraction.
8. **ADR-0018 Semantic cache (flag, default off):** cache ladder; scope; serve-time ACL; `org_only` admission; guard lexicon versioned with the bundle; invalidation hooks on ingest/delete/ACL change; TTL; feedback eviction; UI label + Regenerate; scope decision (org vs. user) recorded with the timing-channel trade-off in the system card (#59).
9. **Eval sets:** `semcache_pairs_v1` (+ replay evaluation), red-team items from §3.9.
10. **Settings (Appendix A):** `LLM_CACHE_MODE`, `LLM_CACHE_TTL`, `ROUTER_POLICY`, `ANSWER_PROFILE_CHEAP`, `ANSWER_PROFILE_STRONG`, `REFUSAL_ESCALATION_FLOOR`, `SEMCACHE_ENABLED`, `SEMCACHE_SCOPE` (`org`|`user`), `SEMCACHE_THRESHOLD`, `SEMCACHE_TTL_S`, `SEMCACHE_ORG_ONLY`.
11. **Throttle (D24):** cache hits count as requests.
12. **Status page:** cost by route, escalation rate, token cache-hit ratio, semantic cache hit and eviction counts.

---

## 7. Self-check

Answer without the notes; then compare.

**Prompt caching**
1. Why does automatic caching make P1's single-turn RAG 25 % more expensive on Sonnet 5.5 and GPT-5.6+, but not on DeepSeek?
2. P1's system prompt is ~300 tokens. What happens when you put a breakpoint after it on Claude Sonnet 5.5, and what tells you so?
3. "Writes happen only at breakpoints; reads look backwards." Explain why a breakpoint on the block with the timestamp never produces a hit.
4. Why does text-only history (#12) need a breakpoint at the end of the history to get turn-to-turn reuse?
5. A tool list is built by iterating a set. Why do cache hits drop in production but not on your laptop?
6. `tool_choice: "none"` at the last agent step: what does it do to the cache on Anthropic and on OpenAI?
7. An approval comes back after 6 minutes. What did the 5-minute cache cost you, and when is the 1-hour cache the better default?
8. Which usage field means what on OpenRouter vs. Anthropic native, and which one under-counts if you sum it?
9. Why is `provider.order` relevant to OpenRouter's sticky routing — and why doesn't it hurt kb-agent?
10. Name two ways a prompt cache can leak information, and which one matters inside kb-agent.

**Routing & cascades**
11. Why can't kb-agent cascade its streamed answer, and which three things can it do instead?
12. What does the refusal holdback guarantee about emitted text, and when does it escalate?
13. Which failures should escalate a structured call, and which must never?
14. Why route once per turn and not per agent step?
15. In E3, why can a judge-checked cascade beat the strong model, and why is that number optimistic?
16. You compare router vs. strong on 45 items × 3 repeats and get "difference not significant". What can you conclude?
17. What does APGR measure, and what value does random routing get?
18. Why is OpenRouter's Auto Router a baseline arm and not a production router for kb-agent?

**Semantic caching**
19. Give three question pairs where cosine similarity is high but the cached answer would be wrong, and the guard rule that catches each.
20. Which near misses can no guard catch, and what limits the damage then?
21. Why is the principal not in the scope key, and what replaces it?
22. Why aren't refusals admitted? Name the Qdrant fact that makes them hard to invalidate.
23. An invalidation helper receives an empty list. What happened in E5, and how does the sketch prevent it?
24. A new runbook is uploaded. Which cached answers should go, and why can't doc-based invalidation find them?
25. What does `done.usage.costUsd` say on a cache hit vs. a cancelled stream, and why?
26. What is the timing side channel of an org-scoped semantic cache, and what are the options?

<details>
<summary>Answer key (short)</summary>

1. Every prompt is unique (sources), so automatic caching writes the whole prompt at 1.25× and nothing is ever read; DeepSeek charges writes at the normal input price.
2. Nothing — 300 < 512, silently not cached; `cache_creation_input_tokens` and `cache_read_input_tokens` are both 0.
3. The entry's hash includes the timestamp, so no later request computes the same hash, and the lookback only finds entries written by earlier requests — none were written at the stable position before it.
4. Turn N+1 rewrites turn N's user message (sources and tool loop dropped), so the longest reusable prefix ends at the previous history; an entry exists there only if a breakpoint wrote one.
5. Set order is salted per process (`PYTHONHASHSEED`); on one laptop process the order is constant, across workers/restarts it differs (E2: 19 of 20 orders different).
6. Anthropic: invalidates the message-level cache for that request (E1: 0.33 → 0.52 if done every turn). OpenAI: recommended way to disable tools, prefix unchanged.
7. The resume rewrote the prefix at 1.25× (0.66 → 1.25 relative cost). 1 h (2× writes) wins when fewer than ~36 % of approvals arrive within ~5 minutes.
8. OpenRouter/OpenAI: `prompt_tokens` includes cached; `prompt_tokens_details.cached_tokens`/`cache_write_tokens`. Anthropic native: `input_tokens` excludes reads and writes — summing it under-counts.
9. Sticky routing is disabled when `provider.order` is set; kb-agent pins a single provider, so every request reaches the same cache anyway.
10. Cross-user/organisation cache sharing (Gu et al.: global sharing at 7 providers) and timing probes of shared prefixes; inside kb-agent the workspace cache is shared by its users, but the stronger channel is its own semantic cache.
11. Buffering kills TTFT, streaming-then-retracting breaks the contract. Instead: route before generation, cascade only non-streamed structured calls, and hold back a refusal.
12. Emitted text is always a prefix of the final text; it escalates only when the whole stream is exactly the refusal *and* the prefetch top-1 is above the calibrated floor.
13. Escalate: invalid JSON, schema/semantic failure, `length`, "unsure". Never: refusals, 402, cancellation.
14. Caches are per model (a switch rewrites the prefix at write price) and reasoning blocks are tied to the producing model.
15. A rejected cheap answer gets a second, independent try from the strong model; real failures correlate on hard items, so independence overstates it.
16. Nothing about equality; at 45 items even identical systems are confirmed non-inferior only ~1/3 of the time. Use a non-inferiority test with a margin and a pre-written rule for "inconclusive".
17. The area under "performance gap recovered" vs. share of calls to the strong model; random routing gives 0.5.
18. Its choice follows a 7-day market spend window (not reproducible, not your golden set), and wrong plugin-id settings are silently ignored.
19. staging vs production (contrast class `env`), Qdrant 1.18 vs 1.19 (literal tokens), "see" vs "not see" (`neg`), enable vs disable (`dir`), AKS vs EKS (`cloud`), `--dry-run` vs `--force` (flag literals), `kb_current` vs `kb_previous` (identifier literals).
20. Purely semantic ones (approve vs execute; access vs refresh token). Threshold calibrated for a false-hit bound, TTL, feedback eviction, Regenerate, and measuring the false-hit rate.
21. A principal-set key fragments the cache into near-zero hits; instead every source document is checked against the asker's current ACL and version at serve time.
22. They go stale on the next upload; they have no `source_doc_ids`, so `match.any` invalidation can't reach them (E5).
23. A `should` list built from `[]` matched everything and deleted the whole cache; the sketch returns early on empty input and uses `match.any`.
24. Entries in the new document's domains — the new doc was never a source of those entries; `invalidate_domains` removes them.
25. 0.0 on a hit (truly no LLM call); `null` on a cancelled stream (cost unknown, #16).
26. Hits are fast, so anyone can probe whether a similar question was asked recently. Options: per-user scope, org scope limited to `org` answers + TTL (documented), k-distinct-askers admission, latency padding (weak).
</details>

---

## Appendix A — Sketch index (`batch-12-sketches.zip`)

| File | What it shows | Tests |
|---|---|---|
| `kbcost/prompt_cache/cachesim.py` | breakpoint simulator, profiles | 10 |
| `kbcost/prompt_cache/layout.py`, `audit.py` | cache-aware body builder, divergence audit | 9 |
| `kbcost/prompt_cache/usage.py` | usage normalisation, cost estimate | 4 |
| `kbcost/routing/router.py`, `stats.py` | rule router, threshold calibration, non-inferiority, APGR, Pareto | 7 |
| `kbcost/routing/cascade.py`, `holdback.py` | structured-call cascade, refusal holdback | 16 |
| `kbcost/semcache/*` | guard, admission, Qdrant store, replay | 42 |
| `experiments/e0` | instrumentor cache attributes (stream + non-stream) | — |
| `experiments/e1` | layouts × providers, approval pause | — |
| `experiments/e2` | set-ordered tool lists across processes | — |
| `experiments/e3` | routing/cascade trade-off, non-inferiority power, items needed | — |
| `experiments/e4` | 42 labelled pairs, thresholds, guard | — |
| `experiments/e5` | Qdrant invalidation facts | — |
| `experiments/e6` | 11 mutants (guard, ACL, version, expiry, scope, admission, canonical tools, representation, minimum, holdback, unsure) — all killed | — |

## Appendix B — Sources

Docs (read 2026-10-14):
- [OpenRouter — Prompt caching](https://openrouter.ai/docs/guides/best-practices/prompt-caching)
- [Anthropic — Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
- [OpenAI — Prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching)
- [OpenRouter — Auto Router](https://openrouter.ai/docs/guides/routing/routers/auto-router)
- [OpenRouter — Pareto Router](https://openrouter.ai/docs/guides/routing/routers/pareto-router)
- [OpenRouter — Model fallbacks](https://openrouter.ai/docs/guides/routing/model-fallbacks)

Papers:
- [Ong et al., RouteLLM: Learning to Route LLMs with Preference Data (ICLR 2025)](https://proceedings.iclr.cc/paper_files/paper/2025/hash/5503a7c69d48a2f86fc00b3dc09de686-Abstract-Conference.html)
- [Dekoninck, Baader, Vechev, A Unified Approach to Routing and Cascading for LLMs (ICML 2025)](https://proceedings.mlr.press/v267/dekoninck25a.html)
- [Schroeder et al., vCache: Verified Semantic Prompt Caching (ICLR 2026)](https://iclr.cc/virtual/2026/poster/10006471)
- [Gu et al., Auditing Prompt Caching in Language Model APIs (ICML 2025)](https://proceedings.mlr.press/v267/gu25b.html)
- [Song et al., The Early Bird Catches the Leak: Timing Side Channels in LLM Serving Systems (arXiv 2409.20002)](https://arxiv.org/abs/2409.20002)
