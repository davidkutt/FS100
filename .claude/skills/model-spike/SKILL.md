---
name: model-spike
description: Benchmarks a candidate model (reranker, Docling, Prompt Guard, spaCy, sparse encoder) for load time, latency and peak memory on the 16 GB M1 in a throwaway uv venv outside the repo, so apps/ai-service's environment and model cache stay untouched. Use when sizing or choosing a model against the D50 memory budget ("does X fit in 16 GB", "reranker latency for 20/50 pairs", "Docling peak memory", "spike a model", M3a.3 / M3a.5 / M3b.5).
---

# Model spike on the 16 GB M1

1. Throwaway venv in the scratchpad (`$S`), never `uv add` in the repo:
   ```bash
   uv venv -q --python 3.13 $S/spike/.venv
   VIRTUAL_ENV=$S/spike/.venv uv pip install "docling==…" "sentence-transformers==…" fastembed psutil
   ```
   Pick versions at least two weeks old. Keep scripts in `$S/scripts`, downloads in `$S/dl`, and run with
   `python -I`.
2. Model caches in the scratchpad too: `HF_HOME=$S/hf`, fastembed `cache_dir=$S/models`.
3. One model per process, nothing else CPU-heavy running (no `pnpm dev`, no second benchmark):
   - peak memory: `/usr/bin/time -l .venv/bin/python -I script.py` → `maximum resident set size` (bytes)
   - load memory: psutil RSS before/after; latency: median of 3 after a warm-up
   - rerankers (fastembed ONNX, no throwaway venv needed): `apps/ai-service/.venv/bin/python -I
     rerank_latency.py <model> <repo>/data/sample-docs $S/models` (in this folder); torch/MPS candidates:
     `rerank_bench.py {minilm|jina|bge}` in the throwaway venv
4. Reranker quality on the golden set, without touching the service cache: clone it (APFS, no disk cost)
   `cp -cR apps/ai-service/.cache/fastembed $S/models`, then from `apps/ai-service`
   `EMBEDDING_CACHE_DIR=$S/models uv run kb-eval retrieval --split dev --out $S/runs --rerank none
   --rerank <model>:<candidates> …` — one ingest (~160 s), every reranker on top; `run_in_background`.
5. Apple GPU (MPS) memory is not in RSS (nor in `pnpm mem`): print `torch.mps.current_allocated_memory()`
   and `driver_allocated_memory()` and add it to the D50 numbers by hand.
6. Does the dependency fit the service? Resolve without installing:
   `uv pip compile -q --python-version 3.13 apps/ai-service/pyproject.toml $S/pins.txt -o $S/pins.lock`;
   an unsatisfiable `numpy==<current>` reveals caps (Presidio 2.2.364 caps numpy < 2.5).
7. Licence and gating: `curl -s https://huggingface.co/api/models/<id>` → `cardData.license`, `gated`.
8. Qdrant features: a throwaway container, never the dev Qdrant:
   `docker run -d --rm --name grove-spike-qdrant -p 6343:6333 qdrant/qdrant:v1.19.2` → `docker stop` after.

## Pitfalls

- transformers 5: fp16 needs `model_kwargs={"dtype": torch.float16}`; `torch_dtype` is ignored silently
  (fp32, twice the memory). Check `model.dtype`.
- onnxruntime refuses fastembed's `snapshots/…/model.onnx` ("External data path escapes model directory");
  open `.cache/fastembed/models--…/onnx_snapshots/*/onnx/model.onnx`.
- First runs include downloads: report the warm run.
- onnxruntime's CoreML provider is much slower for cross-encoders (23 s for 10 pairs, +9.5 GB) or fails;
  4 threads instead of the default changes nothing on the M1.
- fastembed's `TextCrossEncoder.rerank` returns raw logits; `psutil` is not in the service venv (use
  `resource.getrusage`). The eval's top 10 means fewer than 10 candidates still rerank 10.
- `dev` near its ceiling hides failures: check `test` once, per item (exact-term items, ADR-0017).

## Done when

Each candidate has one line (load, memory, latency, licence), the numbers are in the ADR draft and the D50
table in `plan-phase-3.md`, and `$S/spike`, `$S/models`, `$S/hf` and the spike container are gone.
