# Batch 9 — Generation quality & evaluation at scale

> **Topics:** #40 Generation evaluation · #41 LLM-as-judge & judge calibration · #43 Evaluation as a CI gate ·
> #44 Synthetic data generation · #45 Online feedback loop
> **Needed for:** Phase 3 ("LLM-judge eval gate"), with four small pieces worth doing already in Phase 1 (§6)
> **Builds on:** #1 (five failure stages), #10 (citations, refusals), #11 (abstention), #17 (golden set, statistics),
> #18 (tracing), #20 (injection), #27 (structured outputs), #38 (prompt bundles), #42 (agent eval, clustered intervals)
> **Sketches:** `batch-09-sketches.zip` — 64 pytest (6 against PostgreSQL 16.15), workflow passes actionlint + shellcheck,
> 6 experiment scripts with outputs
> **Date:** 2026-10-14

---

## 0. Why this batch, and how the pieces fit

Phase 1 measures **retrieval** (`retrieval_v1`, hit@k, MRR, nDCG). That covers stages 1–3 of the five failure stages
from #1. Stages 4–5 — context assembly and generation — are only covered by the M1.3 "manual quality pass" of
10 questions. Batches 3 and 7 added structural checks (citation validator, refusal constant) and agent graders,
but nothing yet answers the questions a user actually cares about:

- Is every statement in the answer backed by the sources it shows?
- Do the `[n]` chips point at the right source?
- Does the answer contain the facts that matter, or just plausible filler?
- Does it refuse when it should, and only then?

Those questions need a grader that reads language, which means an LLM judge. A judge is a model, so it has an error
rate, and an unmeasured error rate turns every number it produces into an opinion. This batch therefore comes as a chain:

```
 question ─► retrieval ─► context ─► generation ─► answer
   │            │                        │            │
   │       retrieval_v1 (P1)        oracle-context   generation_v1: deterministic checks (#40)
   │       hit@k / MRR / nDCG        run (#40)        + judge verdicts per segment (#40/#41)
   │                                                   │
   │                         judge calibrated on YOUR labels (#41) ◄── confusion matrix, PPI
   │                                                   │
   └───────── CI gate: base vs head, same job, three outcomes (#43)
                                                       │
   synthetic items ──► filters ──► human review ──► next dataset version (#44)
   user feedback ───► triage ────► human review ──► next dataset version (#45)
```

Three ideas carry the whole batch:

1. **Code first, judge second.** Everything that can be checked exactly (invalid `[n]`, images, refusal sentence,
   literal ports and flags, language) is checked by code. The judge only gets the questions code can't answer.
2. **A judge is an instrument; calibrate it like one.** Agreement percentages hide the one error that matters
   (missed failures). With an imperfect judge, real differences look smaller and you need more items to see them.
3. **Gates must respect noise.** At 45 items, a naive "fail if the score drops by 2 points" rule fails almost half of
   unchanged PRs when the metric comes from an LLM. Deterministic and stochastic metrics need different rules.

---

## 1. #40 Generation evaluation

### 1.1 Why

Retrieval metrics can be perfect while answers are bad: the model ignores the right chunk, merges two runbooks,
invents a flag, cites `[2]` for a fact from `[1]`, or answers in English to a German question. The reverse also happens:
retrieval misses a section, the model refuses correctly, and the user is well served. You need metrics on the
**answer**, and you need them split so that a number tells you which stage to fix.

### 1.2 What to measure

| Metric | Question it answers | Checked by | Unit | Notes |
|---|---|---|---|---|
| structural pass | Did the answer break a hard rule? | code | answer | invalid `[n]`, images, URLs not in sources, `[1]: url` definitions (batch-04 exfil list) |
| answer kind | answered / refused / partial / empty | code | answer | shared refusal constant per language (batch-07) |
| abstention correctness | refused exactly when it should | code | answer | confusion matrix answerable × kind (§1.7) |
| language match | same language as the question | code | answer | stop-word vote; *unknown* when too short or mixed |
| `must_mention` | exact literals present (ports, flags, commands) | code | answer | `5432` must not match `54321` |
| uncited claim rate | claims without any `[n]` | code | segment | cheap proxy, no judge needed |
| **faithfulness** | is each claim backed by *some* source? | judge | segment | grounding, not truth (§1.5) |
| **citation recall** | does each claim cite a source that backs it? | judge | segment | ALCE-style |
| **citation precision** | does each citation back its claim? | judge | citation | |
| miscited | true claim, wrong chip | judge | segment | misleads users who check |
| **nugget recall (vital strict)** | are the key facts there? | judge (+ code for literals) | nugget | completeness and relevance in one (§1.6) |

Two common metrics are left out on purpose. RAGAS-style **context precision/recall** grade retrieval with an LLM;
you already have labelled retrieval metrics that are exact and free. RAGAS-style **answer relevance** (generate
questions from the answer and compare embeddings) is indirect and hard to interpret; nuggets answer the same question
in a way you can read.

### 1.3 Segment the answer first

Graders work much better on small units than on whole answers. The sketch (`geneval/segments.py`) splits an answer into
**segments** — one sentence or one list item — and attaches the `[n]` citations that belong to each:

- citations are read outside inline code and fences, so `items[0]` or `arr[1]` never count (the batch-03 traps);
- `[1, 2]` and `[1][2]` are two citations; `[x](url)` and `[^1]` are none;
- a citation right after the full stop belongs to the sentence before it (`… 5432. [1] Next …`);
- German and English abbreviations don't end a sentence (`z. B.`, `d. h.`, `e.g.`, `bzw.`), single digits do (`Set replicas to 3.`);
- a fenced code block is glued to the sentence that introduces it (a command is part of its claim);
- headings are structure, not claims.

The judge then grades segment by segment, and every metric in §1.2 is computed from those verdicts.

### 1.4 Deterministic checks before any judge

`geneval/checks.py` runs on every answer in milliseconds:

- **answer kind** from the shared refusal constants (`"This isn't in the knowledge base."` /
  `"Das steht nicht in der Wissensbasis."`), normalised for case, apostrophes and punctuation. A refusal sentence
  plus at least four more words is **partial** ("The KB doesn't cover OpenShift. For Helm it says … [1]").
- **structural pass** = valid citations, no images, no foreign URLs, no reference definitions. These are hard
  failures no judge can overrule.
- **`must_mention`** for literals: anything that looks like an identifier must match as a whole token.

Because they are code, they run in CI on fake-LLM output (batch-03 #15) and on recorded answers, at no cost.

### 1.5 Faithfulness vs citation quality: four metrics from one verdict

The judge returns, per segment, a support label (`supported` / `partial` / `unsupported` / `no_claim`) and the list of
sources that contain the support. That single verdict gives four metrics that can't contradict each other:

```
faithfulness       = claim segments supported by some source / claim segments
citation recall    = claim segments supported AND citing ≥ 1 supporting source / claim segments
citation precision = citations (segment, n) with n among the supporting sources / all citations
miscited           = supported claims whose citations all point at non-supporting sources
```

Worked example (sketch test `test_score_answer_four_metrics`): "A is 1 [1]. B is 2 [2]. C is 3 [1]. Hello there."
with verdicts *supported by 1*, *supported by 1*, *unsupported*, *no claim* gives faithfulness 2/3, citation recall
1/3, citation precision 1/3 and one miscited segment. The chip for "B is 2" is wrong although the statement is
grounded — exactly the case a user notices when they click it.

**Grounding is not truth.** The rubric says: correct general knowledge that is *not* in the sources is
**unsupported**. Otherwise a model that ignores the sources and answers from memory scores well, and you lose the
property that makes RAG trustworthy. Truth relative to the world is a different metric (and in this project the
sources are the world).

### 1.6 Completeness: nuggets instead of reference answers

Comparing the answer to a reference answer (BLEU, ROUGE, embedding similarity) rewards copying the reference's wording
and punishes correct answers phrased differently. The TREC 2024 RAG track uses **nuggets** instead: short atomic
facts a good answer must contain, each marked **vital** or **okay**, and a judge labels each one *support*,
*partial support* or *not support*. The main score is **vital strict**: fully supported vital nuggets divided by all
vital nuggets.

For kb-agent: write 1–4 nuggets per answerable `generation_v1` item from the **source section**, not from a model
answer (writing them from an answer anchors you on its phrasing). Literals inside nuggets (`5432`, `--force`) are also
listed in `must_mention`, so code checks them exactly.

The same TREC study has the caveat that shapes how you use any judge: fully automatic nugget scores agreed with manual
ones very well **when ranking whole systems** (Kendall's τ ≈ 0.9) but only weakly **per question** (τ ≈ 0.36–0.54).
Use judge scores to compare configurations, not to diagnose one answer. For one answer, read it.

### 1.7 Abstention as a confusion matrix

From #11: a false abstention (refusing an answerable question) is unrecoverable for the user, a false acceptance is
recoverable. Report both cells, never one "refusal accuracy":

| | answered | refused | partial |
|---|---|---|---|
| **answerable** | good | false abstention | read it |
| **unanswerable (near-miss)** | false acceptance | good | read it |
| **unanswerable (off-topic)** | false acceptance | good (usually the pipeline gate, #11) | read it |

Faithfulness and citation metrics are **undefined** for refusals (no claims). The sketch returns `None`, and the
aggregate prints how many items each number is based on. A mean that silently counts refusals as 0 or 1 lets a
model "improve" faithfulness by refusing more.

### 1.8 Isolate generation from retrieval: the oracle-context run

Run `generation_v1` twice: once with normal retrieval, once with **oracle context** — the chunks of the labelled
section(s) (`relevant: doc + heading` from #17), padded with retrieved non-relevant chunks up to `top_k` so the prompt
looks normal. Then each item falls into a cell:

| | good with oracle | bad with oracle |
|---|---|---|
| **good with retrieval** | fine | lucky (retrieval found something better than your label — check the label) |
| **bad with retrieval** | **retrieval/ranking problem** (#21–#24 territory) | **generation problem** (prompt, model, context layout) |

This is the cheapest way to stop arguing whether the prompt or the retriever is at fault, and it tells you whether a
better model would help at all.

### 1.9 The dataset: `generation_v1`

Reuse the questions from `retrieval_v1`; don't fork them. A new file references item ids and adds what generation
needs:

```json
{"id": "r-017", "expect": "answer", "nuggets": [
   {"text": "kubectl rollout undo deployment/<name> rolls back to the previous revision", "vital": true},
   {"text": "kubectl rollout status confirms the rollback finished", "vital": false}],
 "must_mention": ["kubectl rollout undo"], "lang": "de"}
{"id": "r-041", "expect": "refuse", "kind": "near_miss", "notes": "OpenShift not in corpus; Helm rollback is"}
```

Size: the 35-ish answerable items plus ~8 near-miss and ~10 off-topic unanswerables (the batch-02 recommendation).
With 45 items, the item-clustered intervals from #42 apply: whole-set differences under ~10 points are not
detectable with a few repeats, so decisions focus on targeted slices (§3.5).

### 1.10 Plan mapping

| Plan element | What changes |
|---|---|
| M1.3 manual quality pass (P1) | Use `segments` + `checks` on the 10 answers; record pass/fail **and failure stage** per answer in `evals/labels/manual_pass_v1.jsonl`. These are your first calibration labels (§2.4). |
| M1.3 refusal sentence | Already planned as a shared constant (batch-07); `answer_kind` reads it. |
| D23 golden set | P3: `generation_v1.jsonl` next to `retrieval_v1` (ids shared, nuggets added). |
| §13.3 "Generation eval" (P3) | Metrics of §1.2, oracle-context run, results per slice (answerable / near-miss / off-topic, DE / EN, domain). |
| D22 ingestion exclusions | Also exclude `evals/labels/` and `evals/synth/` (extends the batch-07 finding about `evals/`). |

### 1.11 Pitfalls

- **Scoring the whole answer at once.** One bad sentence hides in a long good answer; per-segment verdicts don't.
- **Counting refusals as faithful (or unfaithful).** Undefined is undefined; report `n`.
- **Rewarding world knowledge.** "Correct but not in the sources" must be unsupported.
- **Reference-answer similarity as completeness.** Use nuggets; check literals with code.
- **Diagnosing single answers with judge scores.** Per-item agreement with humans is weak even when system-level
  agreement is strong.
- **Blaming the prompt for a retrieval miss.** Run the oracle-context arm before changing prompts.

---

## 2. #41 LLM-as-judge & judge calibration

### 2.1 Why

A judge turns hundreds of answers into numbers you can compare. It is also a model with biases, a version, a provider,
sampling noise and an error rate. Two consequences are easy to underestimate:

- an imperfect judge **shrinks real differences**, so you need more items to see them (§2.6);
- a judge that is lenient (passes bad answers) gives a **confident wrong number**: in the simulation below, the
  judge-only 95 % interval contained the true pass rate only about 19 % of the time (§2.7).

Calibration is how you find out how wrong the instrument is, and the correction tells you what the real number is.

### 2.2 Judge design rules

| Rule | Why | Sketch |
|---|---|---|
| Pointwise grading per segment, one call per answer | cheaper than per-claim calls; no position bias; coverage is checkable | `judge_answer` |
| Labels with definitions, including `partial` and `no_claim` | leniency hides in vague scales; binary-plus-partial is easy to calibrate | `SYSTEM` rubric |
| Short rationale **before** the label | reasoning first, then decision (batch-05 #27) | schema field order |
| Strict JSON schema + Pydantic + semantic checks | every segment once, sources in range, no contradictions | `_semantic_check` |
| One corrective retry, then `JudgeError` | an invalid verdict is never a pass or a fail; it's excluded and counted | `test_invalid_twice…` |
| Answer and sources are data inside tags; reserved tags neutralised | answers and chunks can contain instructions to the judge (#20) | `neutralise`, `test_injection_stays_data` |
| Single-pass rendering | chunk text with `{{ }}` stays literal (batch-07 #38) | `render` |
| Verdict cache keyed by bundle + model profile + rendered prompt | re-scoring an unchanged answer is free and identical | `VerdictCache` |
| Explicit sampling parameters, pinned provider | provider defaults differ; `seed` is best effort (batch-07) | `model_profile` |
| Judge from a **different model family** than the answer model | self-preference bias (§2.3) | ADR-0012 |
| Judge prompt is a versioned bundle (`judge-support@v1`) | a prompt edit is a new instrument; recalibrate | #38 |

### 2.3 Known biases and what kb-agent does about each

| Bias | What happens | Mitigation |
|---|---|---|
| Position | in pairwise comparisons, the judge prefers the first (or second) answer | grade pointwise; for pairwise A/B, ask both orders and count only consistent preferences (`pairwise`) |
| Verbosity | longer answers score better | grade per segment and per nugget, not "overall quality"; check the judge on a long-answer slice |
| Self-preference | judges favour outputs of their own model family; the preference tracks how well they recognise their own text | judge from another family; recalibrate when either model changes |
| Leniency | plausible but under-specified answers pass | explicit `partial`; measure **fail recall**; include mutants (§2.4) |
| Authority of citations | a `[n]` makes a claim look supported | the judge sees the cited text and grades each segment against it |
| Instructions in the content | an answer or chunk tells the judge what to output | data tags, neutralised tags, injection items in the calibration set |
| Prompt sensitivity | rewording the rubric moves scores | bundle versioning; recalibrate on change |
| Nondeterminism | same input, different verdict | explicit parameters, pinned provider, cache; measure the judge's self-agreement on repeats |

Position, verbosity and self-enhancement biases were documented for GPT-4-class judges in the MT-Bench work; position
bias was studied in depth in "Large Language Models are not Fair Evaluators"; self-preference and its link to
self-recognition were shown at NeurIPS 2024. "Judging the Judges" (2024) adds that judges tend to be lenient,
struggle most with under-specified answers, and that percent agreement alone allowed score deviations of up to
20 points where Cohen's kappa separated judges better.

### 2.4 The calibration procedure

1. **Label before you write the rubric's final version.** Grade ~20 answers yourself, then revise the rubric. Grading
   changes what you think the criteria are ("criteria drift", Shankar et al., UIST 2024). Freeze a label guide v1.
2. **Build a calibration pool of ~120 answers** with enough failures in it:
   - answers from 2–3 configurations (dev model, demo model, and a deliberately weak one, e.g. a tiny model or a
     prompt without the citation rule);
   - all item types (answerable, near-miss, off-topic; DE and EN; code-heavy answers);
   - **~20 mutants**: take supported answers and change one thing — a port, a flag, a version; move a citation to the
     wrong source; add one sentence from outside the sources. Mutants have known labels and test exactly the judge's
     sensitivity to small, important errors (the batch-07 grader-mutant idea applied to judges).
3. **Label blind to the judge**, at segment level for faithfulness/citations and nugget level for completeness. Record
   labeller, date, guide version. Answer-level pass = all claim segments supported and structural pass.
4. **Split by item, not by answer** (stable sha256 split, `dev_test_split`). Answers to the same question in both
   halves leak.
5. **Iterate the rubric and the judge model on dev only.** Then run test **once** and record the report (§2.5) in
   ADR-0012 together with a decision rule written beforehand, for example: fail-recall lower 95 % bound ≥ 0.60,
   pass-recall ≥ 0.85, kappa ≥ 0.6 (your numbers; the point is writing them first).
6. **Measure yourself.** Re-label 20 answers a week later. Your self-agreement is the ceiling for the judge.
7. **Recalibrate** when the judge model, provider or bundle changes, when the answer model's family changes, or when
   answer style changes visibly (length, format). Keep the calibration pool as the **judge regression suite**; mutants
   make it cheap to rerun.

Enriching the pool with weak configurations and mutants is legitimate for **per-class recall** (the recall of failures
doesn't depend on how many failures there are) but not for agreement or kappa, which move with prevalence. Report
kappa on a sample that looks like real traffic, or don't report it at all.

### 2.5 Which numbers to look at: confusion matrix first

Treat **fail** as the positive class: the judge's job is to find bad answers.

| | judge: fail | judge: pass |
|---|---|---|
| **you: fail** | caught (tp) | **missed** (fn) |
| **you: pass** | false alarm (fp) | ok (tn) |

The kappa paradox, reproduced (`experiments/judge_stats.out`, 100 items, 90 % raw agreement in every row):

| Judge | agreement | kappa | Gwet AC1 | PABAK | fail recall | pass recall |
|---|---:|---:|---:|---:|---:|---:|
| says "pass" to everything (10 % real failures) | 0.90 | **0.00** | 0.89 | 0.80 | **0.00** | 1.00 |
| catches 5 of 10 failures | 0.90 | 0.44 | 0.88 | 0.80 | 0.50 | 0.94 |
| balanced set, 10 errors | 0.90 | 0.80 | 0.80 | 0.80 | 0.90 | 0.90 |

Agreement can't tell a useless judge from a good one. Kappa can, but its value depends on prevalence. The
"paradox-resistant" alternatives (AC1, PABAK) look great for the judge that never fails anything. **Report the
confusion matrix and both per-class recalls with Wilson intervals** (`calibration.report`), and add kappa as a
secondary number.

### 2.6 Attenuation: an imperfect judge shrinks the differences you're looking for

If the judge passes good answers with probability *p* (pass recall) and fails bad ones with probability *f*
(fail recall), the pass rate it reports is `p·true + (1 − f)·(1 − true)`. The difference between two systems shrinks
by Youden's `J = p + f − 1`:

| pass recall | fail recall | J | a true +10 pts reads as | items needed for the same power |
|---:|---:|---:|---:|---:|
| 1.00 | 1.00 | 1.00 | +10.0 | ×1.0 |
| 0.95 | 0.90 | 0.85 | +8.5 | ×1.4 |
| 0.95 | 0.70 | 0.65 | +6.5 | ×2.4 |
| 0.90 | 0.60 | 0.50 | +5.0 | ×4.0 |

Simulated on 45 paired items, one judging per answer, sign test: the power to detect a real +10-point improvement
drops from **0.46** with a perfect judge to **0.14** with the lenient judge (J = 0.65). A weak judge doesn't just add
noise; it hides improvements you actually made.

### 2.7 Correcting aggregate numbers: PPI (and why not Rogan–Gladen)

**Prediction-powered inference** (Angelopoulos et al., *Science* 2023) combines a small **random** human-labelled
sample with a larger judge-labelled set:

```
estimate = mean(judge on the large set) + mean(human − judge on the labelled sample)
SE²      = var(judge on large set)/N + var(human − judge)/n
```

The second term measures and removes the judge's bias; the interval stays valid however good or bad the judge is.
ARES (NAACL 2024) uses exactly this for RAG evaluation and needs roughly 150+ annotated data points.

Simulation (true pass rate 0.70, 60 human labels + 500 judged answers, 2,000 runs):

| Judge | Method | 95 % CI contains the truth | mean width |
|---|---|---:|---:|
| lenient (pass 0.95, fail 0.70) | judge only | **19 %** | 7.5 pts |
| | human only (60) | 95 % | 23.0 pts |
| | Rogan–Gladen (sens/spec from the 60) | 93 % | 34.3 pts |
| | **PPI** | **95 %** | **19.1 pts** |
| good (pass 0.95, fail 0.90) | judge only | 94 % *(errors happen to cancel at this prevalence)* | 8.1 pts |
| | human only | 95 % | 23.0 pts |
| | **PPI** | **95 %** | **15.0 pts** |
| good, 150 labels (ARES size) | **PPI** | 96 % | 11.4 pts |

Own 10-line PPI matched `ppi_py` (0.2.3, `lam=1`) to three decimals. Three practical notes:

- `ppi_py.ppi_mean_ci` defaults to **`alpha=0.1`** (a 90 % interval) and power-tuned PPI++; pass `alpha=0.05`.
- The labelled sample must be a **uniform random sample** of the same pool. Labelling only what the judge flagged
  measures its precision and tells you nothing about its misses (`labelling_sample` exists for this).
- In kb-agent the judged pool is small (45 items × 3 repeats per config). PPI pays off for **absolute claims** in an
  ADR or the README ("faithfulness of the demo config is 0.91, 95 % CI …") and for larger pools (synthetic items,
  sampled production traces). For **paired A/B decisions** on the same items, use the paired rules in §3 and keep
  attenuation in mind.

Rogan–Gladen (the classic prevalence correction from sensitivity and specificity) is unbiased in theory, but with
60 labels its interval was wider than simply using the 60 human labels. Skip it.

### 2.8 How many labels?

Precision of the fail recall you measure, if the judge catches 80 % of failures (Wilson 95 %):

| real failures labelled | interval | random answers needed at 15 % failure rate |
|---:|---|---:|
| 10 | 0.49–0.94 (±23 pts) | ~67 |
| 20 | 0.58–0.92 (±17 pts) | ~134 |
| 40 | 0.65–0.90 (±12 pts) | ~267 |
| 80 | 0.70–0.87 (±9 pts) | ~534 |

That is why §2.4 enriches the pool with weak configs and mutants: 120 answers with ~40 failures among them give a
fail-recall interval of about ±12 points for a few hours of labelling. Segment-level labels give more data points, but
segments of one answer are correlated, so cluster by answer when you compute intervals (the batch-07 lesson).

### 2.9 Frameworks: what's in the box (verified)

| Library | Version | Findings | Use in kb-agent |
|---|---|---|---|
| arize-phoenix-evals | 3.9.2 | 20 packages; `create_classifier` / `ClassificationEvaluator`; built-in Faithfulness, Correctness, Refusal, ToolSelection … evaluators. **List or score choices → strict `json_schema`; choices with descriptions → forced named `tool_choice`**, which Claude Opus/Sonnet 5.5 reject (batch-05). No temperature unless you pass one. Mustache values aren't HTML-escaped (`&&`, `<source>`, `{{ }}` stay literal). | optional: borrow templates, run benchmarks; pass parameters explicitly; avoid described choices with Claude 5.5 judges |
| ragas | 0.4.3 | 91 packages / 772 MB (LangChain stack, datasets, instructor). **Can't share an environment with openai 3.x**: instructor and langchain-openai pin openai < 2 / < 3. Usage tracking on by default (metadata + persistent user id; `RAGAS_DO_NOT_TRACK=true`). | no; if ever, a separate tool environment |
| deepeval | 4.2.8 | 67 packages, installs with openai 3.31; PostHog telemetry on by default (`DEEPEVAL_TELEMETRY_OPT_OUT=1`). | no (own judge is ~200 lines and fits D11's "no framework") |
| ppi-python | 0.2.3 | pulls numba, statsmodels, gdown; default 90 % interval | test oracle only; own `ppi_mean` in the eval package |

Recommendation: **own judge** in `ai_service/evals/judge/` on the existing `LlmProvider` (non-streaming JSON call),
with the schema, validation and cache from the sketch. It costs about the same code as wiring a framework and keeps
D11, the provider pins (#19) and tracing (#18) intact. Judge calls get their own Phoenix project (batch-07).

### 2.10 Cost (estimate, placeholder prices)

Per answer: segment judge ≈ 1,700 input + 400 output tokens, nugget judge ≈ 600 + 150. For one PR's LLM eval
(45 items × 3 repeats × base and head = 270 answers), judging ≈ 0.62 M input + 0.15 M output tokens:
≈ **$0.12** with a cheap judge ($0.10 / $0.40 per M), ≈ **$4** with a strong one ($3 / $15 per M); generating the
answers adds ≈ $0.07 / $2.3. The verdict cache makes re-scoring free. A full calibration round (120 answers, a few
judge variants on dev) is cents to a few dollars. Use the separate eval key with its own limit (batch-07).

### 2.11 Plan mapping

| Plan element | What changes |
|---|---|
| D11 "no agent framework" | extend to eval: no ragas/deepeval in the service env; own judge |
| ADR-0005 filter order (#19) | judge model goes through the same filter (data policy, provider pin, structured outputs, no forced tool choice) plus **different family than the answer model** |
| New ADR-0012 "Generation eval & judge" | metrics, judge model + provider + bundle, label guide version, calibration report (confusion matrix on test, per-class recalls with CIs, kappa), acceptance rule, recalibration triggers |
| `evals/labels/` | human labels with labeller, date, guide version; never ingested |
| D21 tracing | judge spans as `EVALUATOR` kind in an own Phoenix project; judge prompt variables follow the batch-07 masking rule |

### 2.12 Pitfalls

- **"Our judge agrees 90 % with humans."** Ask for fail recall. A never-fail judge agrees 90 % on a 90 %-pass set.
- **Iterating the rubric on the test labels.** That's tuning on the test set; split by item, test once.
- **Labelling judge-flagged answers only.** You learn its precision, never its misses.
- **Same family as judge and answerer.** Self-preference inflates scores of the configuration you're likely to ship.
- **Judge prompt edits without recalibration.** A new bundle is a new instrument.
- **Trusting a judge on a new answer style.** Errors can correlate with the change you test (longer answers,
  different format), so the bias no longer cancels in A/B comparisons. Spot-check 20 labels of the new style.
- **Treating `JudgeError` as pass or fail.** Exclude, count, and alert when the error rate rises.
- **phoenix-evals with label descriptions on Claude 5.5.** Forced tool choice → 400.

---

## 3. #43 Evaluation as a CI gate

### 3.1 Why

An eval that only runs when you remember to run it catches regressions late. A gate turns the eval into a check on
every relevant change. The difficulty is noise: a gate that fails unchanged PRs gets ignored or disabled, and a gate
that never fails is decoration. The rules have to match the kind of metric.

### 3.2 Tiers

| Tier | What | When | Cost | Blocks? |
|---|---|---|---|---|
| T0 unit / harness | pytest, fake LLM (pipeline, SSE, citations, refusal path, agent loop), scripted judge tests, prompt lock, contract drift | every PR | free | yes |
| T1 deterministic eval | `retrieval_v1` base vs head; structural generation checks on fake-LLM output | PRs touching retrieval/ingest/eval/dataset paths | CPU minutes | yes |
| T2 LLM eval | `generation_v1` × 3 repeats, base vs head, judged | same-repo PRs touching prompts/model profiles/RAG code **with the `llm-eval` label** | cents–dollars | yes when it runs; *inconclusive* doesn't block |
| T3 nightly | T2 on `main` (history, trend, protected-item list); `agent_v1` weekly (batch-07) | schedule | dollars/month | no (alerts) |
| T4 decision campaign | ADR-grade runs with written decision rules (batch-07) | manual | as needed | n/a |

### 3.3 Two kinds of metric, two kinds of rule

**Deterministic** metrics (retrieval on a fixed index, structural checks on fake output) have no run-to-run noise.
Every per-item flip is real. Rule: **protected items must not lose**, and the aggregate drop must stay within a small
tolerance (0 to one item's worth). The noise that remains is *item sampling* — whether 45 items represent your
users — and that is a reason to grow the set, not to loosen the gate.

**Stochastic** metrics (LLM answers, LLM judge) vary between runs even when nothing changed. Rule: compare per-item
rates **paired by item**, require **statistical evidence and a minimum effect**, and allow a third outcome.

### 3.4 Measure base and head in the same job

A stored baseline from last week was produced on a different runner, maybe a different architecture, maybe with a
different provider routing. Two observations from this batch:

- ONNX Runtime 1.31 on CPU (`experiments/onnx_determinism.out`, a base-size FFN with mean pooling and L2 norm):
  bit-identical across repeated runs and across 1 vs 2 threads, but **batch size 1 vs 32 changed every vector**
  (max |Δ| = 6.7 × 10⁻⁸). Ingest batches documents, queries run one at a time, and an arm64 Mac runs different CPU kernels
  than an amd64 runner (not measured here). Tiny differences only flip near-ties, but near-ties exist (duplicated boilerplate, identical
  chunks), and Qdrant doesn't break ties (batch-08).
- OpenRouter routing, provider quantization and model updates drift over days (batch-03, batch-07).

So: **check out the PR's base commit into a worktree and evaluate base and head in the same job**, interleaved for LLM
runs. Stored results are for dashboards and history, not for the gate. Cost control: cache the base index by
(corpus hash, ingest fingerprint), cache judge verdicts, and reuse a nightly base result only if its fingerprint is
identical and it's less than a day old. For retrieval gates you can also run Qdrant with `exact=True` to take ANN
approximation out of the comparison (measure ANN recall separately when HNSW starts mattering).

One more consequence: the CI eval must use the **production embedding model profile**. The plan's risk table proposes
`e5-small` in CI to save cold-start time; a gate on e5-small measures a different system. Cache the model instead
(`actions/cache` on the fastembed directory).

### 3.5 The numbers: what a gate rule can and can't do at 45 items

Simulation (`experiments/gate_sim.out`): 45 items with realistic spread of difficulty (mean pass 0.74), baseline and
candidate each one campaign of *r* repeats; regression = 12 items each lose 0.37 pass probability (≈ −10 pts overall).

| Rule | r | false fail on unchanged PRs | catches the −10 pt regression |
|---|---:|---:|---:|
| drop > 2 pts | 1 | **44 %** | 85 % |
| drop > 5 pts | 1 | 25 % | 69 % |
| paired t p < .05 **and** drop > 3 pts | 1 | 4.5 % | 28 % |
| paired t p < .05 and drop > 3 pts | 3 | 4.8 % | 54 % |
| paired t p < .05 and drop > 3 pts | 5 | 5.3 % | 71 % |
| exact sign test p < .05 and drop > 3 pts | 3 | 3.1 % | 38 % |
| protected = 10/10 in history, candidate ≤ 1/3, then 5 re-runs ≤ 2/5 | 3 | 2.0 % | 41 % |
| protected = 3/3 in one baseline, candidate ≤ 1/3 | 3 | 88 % | 99.7 % |

What this means:

- Naive thresholds on LLM metrics are coin flips. Don't ship them.
- A statistically controlled whole-set gate at 45 items × 3 repeats catches a 10-point regression about half the
  time. That's useful, not sufficient. Pair it with **targeted slices**: when a PR changes the refusal wording, gate
  on the abstention slice; when it changes citation instructions, gate on citation metrics (batch-07 found targeted
  categories of 12–16 items detect large effects 73–87 % of the time).
- "Protected items" only work for items that are **effectively deterministic** — established over a long history
  (e.g. 10/10 across recent nightlies), and confirmed by re-running just the flagged items. "Passed 3/3 once" is not
  protection.

### 3.6 Three outcomes

The gate returns **pass**, **fail** or **inconclusive** (`gate/compare.py`):

- **fail**: deterministic rule broken, or a stochastic drop that is both significant and large enough;
- **inconclusive**: a drop above the minimum effect without significance, or a protected item flipped and needs
  confirmation re-runs; posts a warning and the summary, doesn't block; you decide (more repeats, read the answers,
  or accept and write down why);
- **pass**: everything else.

Runs are compared only if dataset id and content hash match (`IncompatibleRuns` otherwise). Everything else in the
fingerprint may differ — that's what the PR changed — and the summary lists it.

### 3.7 GitHub Actions mechanics (verified against the docs)

- **Path filters and required checks don't mix.** A workflow skipped by `on.pull_request.paths` leaves its required
  check *pending* ("waiting for status") and blocks the merge. A **job** skipped by `if:` reports *success*. So filter
  inside the workflow (`dorny/paths-filter@v4`) and make one always-running **fan-in job** the only required check.
- **Skipped means success, also after a failure.** If a job in `needs` fails, dependents are skipped, and a skipped
  required job is green. The fan-in job therefore runs with `if: ${{ !cancelled() }}` and fails itself when any
  dependency result is `failure` or `cancelled` (pattern from Jake Wharton's "fan-in" article; logic tested in this
  batch).
- **Secrets:** workflows triggered by PRs from forks get no Actions secrets; Dependabot-triggered workflows get only
  Dependabot secrets. The LLM eval must skip (not fail) in both cases — the `if:` in the sketch does that — and it
  never uses `pull_request_target` with a checkout of PR code.
- **Labels as triggers:** add `labeled` to `pull_request.types`, otherwise adding `llm-eval` does nothing.
- **Environment `eval`** holds `OPENROUTER_EVAL_KEY`; add `concurrency` with `cancel-in-progress` so pushes don't
  stack paid runs; set `timeout-minutes` and the batch-07 cost stop (`EVAL_MAX_COST_USD`).
- **Job summary:** `$GITHUB_STEP_SUMMARY`, at most **1 MiB per step** and 20 step summaries per job; the sketch caps
  at 900 KiB and puts the full report in an artifact.
- **Current major versions** (git tags, 2026-10-14): `actions/checkout@v7`, `actions/upload-artifact@v7`,
  `actions/download-artifact@v8`, `actions/cache@v6`, `astral-sh/setup-uv@v10`, `dorny/paths-filter@v4`.

The sketch `.github/workflows/eval.yml` puts it together and passes actionlint 1.7.12 with shellcheck.

### 3.8 Plan mapping

| Plan element | What changes |
|---|---|
| D19 retrieval eval "report only" (P1) | keep report-only, but already in P1: path filter **inside** the workflow, base vs head **in the same job**, deltas and lost/gained items in the job summary |
| D20 "No paid LLM calls in CI" | P3 amendment (your call): none on default PR runs; label-triggered T2 and nightly T3 with the separate eval key and cost cap |
| Risk table "e5-small in CI" | conflicts with gate validity; cache the production model instead |
| §13.3 "Eval as CI gate (blocking on regressions)" (P3) | tiers T0–T3, one required fan-in check `eval-gate`, three outcomes, rules per metric kind in `evals/gate/*.json` |
| New ADR-0013 "Eval gate policy" | metric kinds, rules, tolerances, protected-item policy, who may accept an inconclusive result and how it's recorded |

### 3.9 Pitfalls

- **`on.pull_request.paths` on a required workflow** → PRs that don't touch those paths can never merge.
- **A required job behind `needs`** → green when its dependency failed.
- **Stored baselines from another machine** → phantom regressions.
- **Thresholds without noise model** → 44 % false fails, then someone disables the gate.
- **Gating the whole set when the change targets a slice** → the effect drowns in 45 items.
- **CI on a smaller embedding model than production** → the gate tests the wrong system.
- **Secrets in fork/Dependabot runs** → they don't exist; a "required" LLM eval would block every dependency bump.
- **Updating the baseline in the same PR that regresses it** → the gate compares against itself. Baselines come from
  the base commit, not from files the PR can edit.

---

## 4. #44 Synthetic data generation

### 4.1 Why

Writing 45 good items by hand already takes hours, and the categories that matter most for Phase 3 decisions —
paraphrase without keyword overlap, cross-language, near-miss unanswerables, multi-hop, follow-up — are the hardest to
write and the thinnest in `retrieval_v1`. An LLM can propose many candidates per chunk. The catch is that synthetic
questions look like the text they were generated from, so they flatter retrieval, and a model can't tell which
"unanswerable" questions are actually answered somewhere else in your corpus.

### 4.2 Where synthetic data helps and where it doesn't

| Use | Verdict |
|---|---|
| Growing thin slices (paraphrase, cross-language, near-miss) for **tuning and development** | good, after review |
| Growing a **frozen test set** | only reviewed, labelled `origin: synthetic`, reported as its own slice |
| Mutants for judge calibration (§2.4) | very good: known labels by construction |
| Query–passage pairs and hard negatives for fine-tuning (P6, #55) | good, with false-negative filtering and no overlap with eval items |
| Replacing real questions | no: style, mistakes, code-switching ("Wie kann ich den Pod restarten?") and real intents come from people |

### 4.3 Pipeline

```
chunks ─► stratified sample (domain × language) ─► generate per type + style ─► filters ─► review queue (JSONL)
                                                                                              │ accept / edit / reject
                                                                                              ▼
                                                     next dataset version (origin, generator, reviewer kept)
```

- **Sample by stratum** (`stratified_sample`): otherwise the biggest DevOps runbooks dominate and the two German docs
  disappear.
- **Generate by type**: `lookup`, `paraphrase` (no shared content words), `cross_language` (question in the other
  language), `near_miss_unanswerable` (same topic, perturbed version/tool/environment), `multi_hop` (two chunks that
  share an entity, e.g. a service name).
- **Generate with styles**: terse, a typo, German–English mix, an error message pasted in. Clean textbook questions are
  the easiest kind.
- Use a generator from a **different family than the answer model** where you can, and a cheap model; the corpus is
  public, so D25 holds.

### 4.4 Filters, and the circularity trap

Cheap deterministic filters (`synth/generate.py`, tested):

| Filter | Catches |
|---|---|
| copied share (content words of the question found verbatim in the chunk) > 0.6 for paraphrase / cross-language | questions that reuse the chunk's terms; they are easy for BM25 and dense search alike and inflate hit@k |
| context-bound wording (`this document`, `the above`, `dieser Abschnitt`, `laut dem Text`) | questions that only make sense next to the chunk |
| language mismatch; cross-language item in the source language | wrong-language generations |
| near-duplicate (character 4-gram Jaccard ≥ 0.7) against each other and the existing set | paraphrase farms |
| length bounds | one-word and essay questions |

What filters can't catch, and review must: wrong labels, near-miss items that are actually answered in another
document (search the corpus in the retrieval inspector before accepting), and questions nobody would ask.

**Don't filter by "the current retriever finds the source".** That round-trip filter is a known technique for
**training** data (Promptagator), but applied to an eval set it keeps exactly the questions today's system already
answers, and the set turns into a regression test of itself. The same goes for "the current model answers it
correctly".

To check whether synthetic items are easier than real ones, compare the distribution of `copied_share` (and hit@k)
between the real and the synthetic slice. A large gap means the generator is still copying.

### 4.5 Provenance and versioning

Every candidate keeps `origin: "synthetic"`, `generator: {bundle, model_profile}`, the filter values, `status` and
`reviewed_by`. Only `accepted`/`edited` items with a reviewer are promoted (`promote`), and only into the **next**
version (`retrieval_v2`, `generation_v2`). Frozen v1 sets never change (#17). Reports show real and synthetic slices
side by side. Labels stay at doc + heading level so they survive re-chunking (#17), and the review queue lives in
`evals/synth/`, excluded from ingestion.

### 4.6 Preview for P6: hard negatives

For fine-tuning (#55) you'll mine **hard negatives** — highly ranked chunks that don't answer the question. Many of
them are actually relevant but unlabelled (false negatives); filter with a cross-encoder or judge before training.
And keep training data away from evaluation: no eval questions, and ideally no eval **sections**, in the training
pairs, split by doc + heading. A tuned model that "beats" the base model on leaked items proves nothing.

### 4.7 Plan mapping

| Plan element | What changes |
|---|---|
| §13.3 "Synthetic data generation" (P3) | `kb-eval synth` CLI: sample → generate → filter → `evals/synth/queue-*.jsonl`; review by editing the JSONL; `promote` into v2 |
| D23 dataset versioning | v2 sets carry `origin`; summaries split real vs synthetic |
| Batch 8's `retrieval_v2` slices (`exact_term`, `paraphrase`, `cross_language`, `follow_up`, `context_dependent`) | synthetic candidates fill the thin ones; `follow_up` needs multi-turn generation (conversation + standalone label) |
| P6 #55 | hard-negative mining + false-negative filter + leakage split |

### 4.8 Pitfalls

- **Unreviewed synthetic items in a frozen set.** Labels are wrong more often than you'd think, especially near-misses.
- **Questions that copy the chunk.** Measure `copied_share`; compare real vs synthetic.
- **Round-trip filtering an eval set.** Circular.
- **Mixing synthetic and real numbers.** Always two slices.
- **Generating from the chunk only.** "It", "the service above" — check context-bound wording, or generate from the
  section with its heading path.
- **Training on eval sections in P6.** Leakage.

---

## 5. #45 Online feedback loop

### 5.1 Why

The golden set covers the questions you thought of. Real use finds the others: unexpected phrasings, missing
documents, refusals that annoyed someone, citations that pointed nowhere useful. Feedback is the cheapest way to find
those cases — **as candidates**. It is not a quality metric, and it must never write into an eval set or a training
set by itself.

Honest framing for a portfolio project: real traffic will be you and the seed users. That's fine. The loop's value
is the mechanism and dogfooding — you use the assistant daily, thumbs-down its failures, and each one has a defined
path to becoming a regression item.

### 5.2 What to capture

- **Explicit:** thumbs up/down on an answer, optional reason chips (`wrong`, `incomplete`, `not_grounded`,
  `bad_citation`, `should_refuse`, `refused_wrongly`, `wrong_language`, `outdated`, `other`), optional comment
  (≤ 1,000 characters). `refused_wrongly` matters: false abstentions are otherwise invisible (#11).
- **Implicit (later, optional):** citation clicks, copy, stop, regenerate, rephrasing within a minute. Useful as
  weak signals for sampling traces to review, never as labels.

### 5.3 Where it lives (verified pieces)

**Nest owns feedback.** It's product data, tied to a user, and Nest is the service that knows the user (D3).

1. The Nest relay passes SSE events through unchanged (D12) but taps the `done` event and records
   `chat_turns(trace_id, sub, prompt_bundle, model, index_build, abstained)` — no question or answer text.
   This requires `done.traceId` in **every** mode; §7.3 currently describes it as dev-only (that's only the UI link).
2. `POST /api/feedback {traceId, rating, reasons, comment}` inserts **only if the turn belongs to the caller and is
   less than 7 days old**. Unknown turn, someone else's turn and expired turn all return the same 404 — no probing
   of other users' trace ids (same idea as approvals in batch-06). Voting again updates the row; changing the rating
   resets triage. Reasons are an allow-list, enforced by a `CHECK` constraint.
3. A small **triage job** (`kb-feedback sync`, Python, scheduled) reads new rows and mirrors them into Phoenix as
   **trace annotations**, so a reviewer sees the vote next to the trace. Nest never talks to Phoenix.

Phoenix behaviour that shapes this design (Phoenix 20.21.3 + phoenix-client 3.5.0, run locally):

- Annotations are **upserted by (name, trace, identifier)**. Without an identifier, a second user's vote
  **overwrote** the first. With a per-user identifier (HMAC of `sub`, never the raw `sub`), both votes stayed.
- **Deleting a trace deletes its annotations** (`ON DELETE CASCADE` in the schema). Retention (14 days, batch-04) will
  delete feedback-linked traces with their annotations — so Postgres is the system of record, Phoenix the view.
- `POST /v1/traces/transfer` moves traces to another project **with their annotations** (verified). At triage, move
  flagged traces to a `kb-feedback` project with a longer retention policy, or copy what the reviewer needs into
  `feedback.snapshot`.

### 5.4 Triage

Every thumbs-down gets a **failure stage** from #1 plus two outcomes that aren't failures:

`ingestion` · `retrieval` · `ranking` · `context` · `generation` · `abstention` · `out_of_scope` · `corpus_gap` · `not_a_failure`

State machine (conditional `UPDATE … WHERE triage_status = $from RETURNING`, exactly-once under 8 concurrent
reviewers, verified on PostgreSQL 16.15):

```
new ──► triaged ──► eval_candidate ──► fixed
  │        ├──────► fixed
  ├──► duplicate / wont_fix
```

The oracle-context run (§1.8) is the fastest triage tool: rerun the question with the right section forced in and you
know whether it's a retrieval or a generation problem.

### 5.5 From feedback to an eval item

`eval_candidates()` exports triaged items as **review candidates**, never as dataset rows. The reviewer:

1. rewrites the question in their own words (no user wording or personal data copied blindly);
2. labels doc + heading (or `answerable: false` with a note);
3. adds nuggets / `must_mention` for generation items;
4. promotes it into the **next** dataset version with `origin: "feedback"`.

Feedback-derived items are the most valuable regression items you'll have — they are failures that actually happened.

### 5.6 What feedback is not

- **Not a quality metric.** Votes are sparse and selection-biased (people vote when annoyed or delighted), and a
  thumbs-up doesn't mean the answer is grounded — users rarely check sources. Report volume and coverage
  (`feedback_stats`), not "satisfaction".
- **Not ground truth.** A thumbs-down can be wrong, or adversarial. Triage decides.
- **Not training data by itself.** Feedback can be poisoned; only reviewed items move on.

### 5.7 Privacy

Comments are free text and may contain secrets or personal data: run the batch-04 secret scan on submit, cap the
length, delete comments some time after triage (e.g. 90 days), and keep only the HMAC identifier in Phoenix. The
snapshot holds what the reviewer needs (question, answer hash, source refs), not the whole trace.

### 5.8 Plan mapping

| Plan element | What changes |
|---|---|
| §7.3 `done.traceId` | always present (the Phoenix link in the UI stays dev-only) |
| §7.2 NestJS API (P3) | `POST /api/feedback` (viewer+, own turns only, 204/404); `GET/POST /api/admin/feedback` triage (admin) |
| §7.4 app DB (P3) | `chat_turns` + `feedback` tables (sketch `feedback/schema.sql`), Drizzle migration |
| Chat relay (M1.4) | passive tap on `done` → `chat_turns` insert; relay output stays byte-identical (test) |
| Phoenix (D21) | `kb-feedback` project with longer retention; annotation identifiers = HMAC(sub) |
| Angular chat (P3) | thumbs + reason chips + comment under each answer; keyboard-operable; `aria-live` confirmation |
| §13.3 "Online feedback loop" (P3) | triage CLI/page, export of candidates, promotion into v2 sets |

### 5.9 Pitfalls

- **Feedback keyed only by trace id.** Anyone who sees a trace id could vote on it; bind to `sub` via `chat_turns`.
- **Phoenix annotations without identifier.** Users overwrite each other.
- **Phoenix as the system of record.** Retention deletes annotations with their traces.
- **Copying user questions into the eval set.** Rewrite and review.
- **Thumbs-down rate as a KPI.** It measures who bothered to click.
- **Auto-adding feedback to eval or training data.** Poisoning and mislabels.

---

## 6. Putting it together, and what to do already in Phase 1

The flywheel: the golden sets measure; the judge scales measurement to language-level questions; calibration keeps the
judge honest; the gate turns measurement into protection; synthetic data and feedback grow the sets where they are
thin or wrong. Each arrow needs a human at the right spot: rubric and labels (judge), review (synthetic, feedback),
inconclusive gate results (you).

Four cheap things fit into Phase 1 without changing its scope:

1. **M1.3 manual pass with structure (≈ 30 min extra):** run `segments` + `checks` on the 10 answers; save
   pass/fail + failure stage per answer to `evals/labels/manual_pass_v1.jsonl`. These become the first calibration
   labels.
2. **M1.6 `eval.yml` shape:** path filter inside the workflow, base vs head in one job, lost/gained items in the job
   summary, one fan-in job — still report-only (D19), but the structure P3 needs.
3. **§7.3 `done.traceId` always**, so feedback and traces can be joined later.
4. **CI uses the production embedding model**, cached — not e5-small.

Everything else is Phase 3.

---

## 7. Change list for the plan

| # | Where | Change |
|---|---|---|
| 1 | M1.3 | manual pass records labels + failure stage in `evals/labels/manual_pass_v1.jsonl` |
| 2 | D19, M1.6 | eval workflow: in-workflow path filter, same-job base vs head, fan-in required check; report-only in P1 |
| 3 | §11 risks | replace "`e5-small` in CI" with "cache the production model; gate must test the production profile" |
| 4 | §7.3 | `done.traceId` in all modes; only the UI trace link is dev-only |
| 5 | D22 | exclude `evals/labels/` and `evals/synth/` from ingestion (with `evals/` and the notes path, batch-07) |
| 6 | D23 (P3) | `generation_v1.jsonl` (nuggets vital/okay, `must_mention`, `expect` answer/refuse) referencing `retrieval_v1` ids |
| 7 | D20 (P3, your call) | "no paid LLM calls on default PR runs"; label-triggered and nightly LLM eval with the separate eval key + cost cap |
| 8 | D11 (P3) | own judge on `LlmProvider`; no ragas/deepeval in the service env; any framework only in a separate tool env with telemetry off |
| 9 | ADR-0012 (new) | generation eval & judge: metrics, judge model/provider/bundle (different family), label guide, calibration report, acceptance rule, recalibration triggers |
| 10 | ADR-0013 (new) | eval gate policy: tiers, rules per metric kind, tolerances, protected-item policy, handling of *inconclusive* |
| 11 | §7.2 / §7.4 (P3) | `POST /api/feedback`, admin triage endpoints; `chat_turns` + `feedback` tables |
| 12 | M1.4 relay (P3) | passive `done` tap writes `chat_turns`; byte-identical relay test |
| 13 | D21 (P3) | `kb-feedback` Phoenix project + retention; HMAC annotation identifiers; judge spans in an eval project |
| 14 | §13.3 (P3) | `kb-eval generation`, `kb-eval synth`, `kb-feedback sync` CLIs; real vs synthetic vs feedback slices in every report |
| 15 | Appendix A (P3) | `JUDGE_MODEL`, `JUDGE_PROVIDER_ORDER`, `JUDGE_CACHE_DIR`, `EVAL_MAX_COST_USD`, `FEEDBACK_WINDOW_DAYS=7`, `FEEDBACK_ID_HMAC_KEY`, `PHOENIX_FEEDBACK_PROJECT=kb-feedback` |

---

## 8. Self-check

Answer without the notes; the key is below.

1. A config scores 0.95 faithfulness but users complain the answers are wrong. Name two ways that can happen.
2. Define faithfulness, citation recall, citation precision and *miscited* from one per-segment verdict.
3. Why are refusals excluded from faithfulness, and what must the aggregate report alongside the mean?
4. Why nuggets instead of similarity to a reference answer? What does the TREC 2024 RAG study say about per-question use?
5. What does the oracle-context run tell you that a normal run can't? Which cell means "fix retrieval"?
6. A vendor says its judge agrees with humans 90 % of the time. Which numbers do you ask for, and why?
7. Which judge numbers stay valid when you enrich the calibration pool with mutants and a weak config, and which don't?
8. Judge pass recall 0.95, fail recall 0.70. A change truly adds 10 points. What does the judge show, and how many more items do you need?
9. In the lenient-judge simulation, why did the judge-only interval contain the truth only ~19 % of the time? How does PPI fix it, and what does it assume?
10. Why label a random sample, not the answers the judge flagged?
11. Name three judge biases and the kb-agent mitigation for each.
12. Why does phoenix-evals' built-in faithfulness evaluator work with a Claude Sonnet 5.5 judge via OpenRouter, while a classifier whose choices have descriptions fails?
13. Deterministic vs stochastic metric: how do the gate rules differ, and why?
14. What happens with "fail if the score drops by more than 2 points" on 45 LLM-judged items × 1 repeat?
15. Give two reasons to evaluate base and head in the same CI job.
16. What happens to a required check if its workflow uses `on.pull_request.paths`? What does a job skipped by `if:` report, and how does the fan-in job handle a failed dependency?
17. Why does the LLM eval skip Dependabot and fork PRs, and why is that acceptable?
18. Why must you not filter synthetic eval questions by "the current retriever finds the source"?
19. Name two cheap filters for synthetic questions and what each catches.
20. Who may vote on a turn, how is it enforced, and why do three different failure cases return the same 404?
21. What happens to Phoenix feedback annotations when trace retention runs, and what do you do about it?
22. Why is the thumbs-down rate not a quality metric?

<details>
<summary>Answer key</summary>

1. Retrieval returned the wrong (but plausible) section and the model faithfully summarised it; or the sources are
   outdated/wrong. Faithfulness measures grounding, not correctness against the user's need — check retrieval metrics,
   nuggets and the oracle run.
2. Faithfulness: supported claim segments / claim segments. Citation recall: supported and citing ≥ 1 supporting
   source / claim segments. Citation precision: citations whose source supports their segment / all citations.
   Miscited: supported claims whose citations all point elsewhere.
3. A refusal has no claims, so the metric is undefined; counting it as 0 or 1 lets refusing more change the score.
   Report `n` (items where the metric is defined) and the abstention confusion matrix.
4. Similarity rewards wording, not facts; nuggets are atomic facts judged for support. Automatic nugget scores rank
   systems well (τ ≈ 0.9) but agree only weakly per question (τ ≈ 0.36–0.54) — use for comparing configs, not
   diagnosing single answers.
5. Whether generation works when retrieval is perfect. "Bad with retrieval, good with oracle" = retrieval/ranking
   problem; "bad with both" = generation problem.
6. The confusion matrix, fail recall and pass recall with intervals, the failure prevalence of the sample, then kappa.
   A judge that never fails anything agrees 90 % on a set with 10 % failures (kappa 0, fail recall 0).
7. Per-class recalls (fail recall, pass recall) are conditional on the true class and stay valid; agreement and kappa
   depend on prevalence and don't.
8. +6.5 points (J = 0.65); about 2.4× the items for the same power (1/J²).
9. The judge passes 30 % of bad answers, so its pass rate centres at 0.755, not 0.70; with 500 items its interval is
   narrow around the wrong value. PPI adds the mean human−judge difference from a random labelled sample, removing
   the bias. Assumption: the labelled items are a uniform random sample of the same pool.
10. Judge-flagged answers only show how often a "fail" is right (precision). Misses — failures the judge passed — are
    only visible in a random sample.
11. E.g. position (pointwise grading; both orders for pairwise), verbosity (segment/nugget grading; long-answer
    slice), self-preference (different family), leniency (`partial`, mutants, fail recall), injection (data tags,
    neutralised tags), nondeterminism (explicit params, pinned provider, cache).
12. Its choices are a plain list/score map, so it sends a strict `json_schema` response format. Choices with
    descriptions switch to tool calling with a forced named `tool_choice`, which Claude Opus/Sonnet 5.5 reject (400).
13. Deterministic: no noise, every flip is real → protected items must not lose, aggregate within tolerance.
    Stochastic: run-to-run noise → paired per-item test plus minimum drop, a third outcome (inconclusive),
    confirmation re-runs for protected items.
14. About 44 % of unchanged PRs fail (simulated); the rule is noise.
15. No drift between machines/architectures/batching (ONNX outputs change with batch size) and no provider/model drift
    between baseline time and PR time; also no baseline the PR itself can edit.
16. The check stays pending and blocks merging. A job skipped by `if:` reports success. The fan-in job runs with
    `if: !cancelled()` and fails when any `needs` result is failure or cancelled.
17. They get no Actions secrets (forks: none; Dependabot: only Dependabot secrets), so they can't call the LLM; the
    deterministic tiers still run, and LLM evals run on same-repo labelled PRs and nightly.
18. It keeps only questions the current system already answers, so the set measures itself and hides exactly the
    failures you want to find (round-trip filtering is for training data).
19. Copied share (catches questions reusing the chunk's terms → inflated hit@k); context-bound wording (catches
    "according to this document"); also language mismatch and near-duplicate.
20. Only the user who asked (`chat_turns.sub` = caller's `sub`), enforced in the `INSERT … SELECT … WHERE`. Unknown,
    foreign and expired turns look the same so nobody can probe whether a trace id exists.
21. They're deleted with the trace (`ON DELETE CASCADE`). Keep feedback in Postgres as the system of record; at triage
    transfer flagged traces to a `kb-feedback` project with longer retention or copy a snapshot.
22. It's sparse and selection-biased, and users rarely verify grounding; it measures who clicked, not answer quality.

</details>

---

## Appendix A — Verification log

**Ran (Python 3.13.16, 2 vCPU sandbox):**

- arize-phoenix-evals 3.9.2 with openai 3.31.0 (httpx 0.28.1 / httpx2 2.13.1) on a mock transport: request shapes per
  choice format, template rendering of hostile values (`experiments/phoenix_evals_request_shapes.*`)
- ragas 0.4.3, deepeval 4.2.8, arize-phoenix-evals 3.9.2 in fresh venvs: package counts, sizes, the openai 3.x
  conflict (`pip` resolver), telemetry defaults from source (`experiments/deps_footprint.out`)
- arize-phoenix 20.21.3 (`phoenix serve`, SQLite) + arize-phoenix-client 3.5.0 + OTLP/HTTP from opentelemetry-sdk
  1.45.1: trace annotations with/without identifier, `POST /v1/traces/transfer`, trace delete, schema inspection
  (`experiments/phx_feedback_exp.*`); REST surface from `/openapi.json`
- onnxruntime 1.31.0 + onnx 1.23.2: determinism across repeats, threads, batch sizes (`experiments/onnx_determinism.*`)
- numpy 2.5.4 + scipy 1.18.1 + ppi-python 0.2.3: judge statistics and gate simulations
  (`experiments/judge_stats.*`, `experiments/gate_sim.*`); own PPI cross-checked against `ppi_py`
- scikit-learn 1.9.1 (kappa cross-check), pydantic 2.14.1, psycopg 3.3.6 against PostgreSQL 16.15
- actionlint 1.7.12 + shellcheck (shellcheck-py) on the workflow sketch; git tags of the GitHub actions used

**Read (docs and papers):** GitHub Docs (troubleshooting required status checks; secret types; job summary limits via a
mirror of the docs repository), Jake Wharton's fan-in article (May 2025), Phoenix data-retention docs and the
trace-transfer release note, ARES, "Judging the Judges", "Who Validates the Validators?", "The Great Nugget Recall",
NeurIPS 2024 self-preference paper (abstract page).

**Not run:** any real LLM (judge or answer model), OpenRouter, GitHub Actions itself, Qdrant, a real embedding model
(Hugging Face downloads blocked; the ONNX test uses random weights with base-size shapes).

## Appendix B — Sketch index (`batch-09-sketches.zip`)

| File | Tests |
|---|---:|
| `kb_eval9/geneval/{segments,checks,metrics}.py` | 20 |
| `kb_eval9/judge/judge.py` | 14 |
| `kb_eval9/judge/calibration.py` | 7 |
| `kb_eval9/gate/compare.py` | 9 |
| `kb_eval9/pipeline.py` (end to end with fakes) | 1 |
| `kb_eval9/synth/generate.py` | 7 |
| `kb_eval9/feedback/{schema.sql,store.py}` (PostgreSQL) | 6 |
| `.github/workflows/eval.yml` | actionlint + shellcheck clean |
| `experiments/*` | 6 scripts + outputs |

## Sources

- Gao et al., *Enabling Large Language Models to Generate Text with Citations* (ALCE), EMNLP 2023 — https://arxiv.org/abs/2305.14627
- Es et al., *RAGAS: Automated Evaluation of Retrieval Augmented Generation*, 2023 — https://arxiv.org/abs/2309.15217
- Saad-Falcon et al., *ARES: An Automated Evaluation Framework for RAG Systems*, NAACL 2024 — https://arxiv.org/html/2311.09476v2
- Angelopoulos et al., *Prediction-Powered Inference*, Science 2023 — https://arxiv.org/abs/2301.09633 · `ppi_py` — https://pypi.org/project/ppi-python/
- Zheng et al., *Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena*, NeurIPS 2023 — https://arxiv.org/abs/2306.05685
- Wang et al., *Large Language Models are not Fair Evaluators* — https://arxiv.org/abs/2305.17926
- Panickssery et al., *LLM Evaluators Recognize and Favor Their Own Generations*, NeurIPS 2024 — https://papers.nips.cc/paper_files/paper/2024/hash/7f1f0218e45f5414c79c0679633e47bc-Abstract-Conference.html
- Thakur et al., *Judging the Judges: Evaluating Alignment and Vulnerabilities in LLMs-as-Judges* — https://arxiv.org/html/2406.12624v2
- Shankar et al., *Who Validates the Validators?*, UIST 2024 — https://arxiv.org/pdf/2404.12272
- Pradeep et al., *The Great Nugget Recall* (TREC 2024 RAG) — https://arxiv.org/html/2504.15068v1
- Dai et al., *Promptagator: Few-shot Dense Retrieval From 8 Examples*, ICLR 2023 — https://arxiv.org/abs/2209.11755
- Feinstein & Cicchetti, *High agreement but low kappa*, J Clin Epidemiol 1990; Rogan & Gladen, *Estimating prevalence from the results of a screening test*, Am J Epidemiol 1978
- GitHub Docs: troubleshooting required status checks — https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks
- GitHub Docs: secret types — https://docs.github.com/en/code-security/reference/secret-security/secret-types
- GitHub Docs (job summary limits, mirror of the docs repository) — https://source-hub.etos-pro.ru/github/docs/commit/b312c93a9be97e039e58c5f7bf95be3769c1545f
- Jake Wharton, *Fan-in to a single required GitHub Action* (2025) — https://jakewharton.com/fan-in-to-a-single-required-github-action/
- Phoenix: data retention — https://www.arize.com/docs/phoenix/settings/data-retention.md · trace transfer — https://www.arize.com/docs/phoenix/release-notes/08-2025/08-14-2025-trace-transfer-for-long-term-storage
