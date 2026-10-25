"""One reranker per process, fastembed only (runs in the service venv): load, peak RSS, median latency
for 10/20/30 real 1000-char chunks, logit range. Args: MODEL|jina-int8|mminilm|mminilm-int8 CORPUS CACHE [THREADS|-] [PROVIDER]."""

import glob
import statistics
import sys
import time

import resource
from fastembed.common.model_description import ModelSource
from fastembed.rerank.cross_encoder import TextCrossEncoder

name, corpus, cache = sys.argv[1], sys.argv[2], sys.argv[3]
threads = int(sys.argv[4]) if len(sys.argv) > 4 and sys.argv[4] != "-" else None
providers = [sys.argv[5]] if len(sys.argv) > 5 else None
CUSTOM = {
    "jina-int8": ("jinaai/jina-reranker-v2-base-multilingual", "onnx/model_int8.onnx"),
    "mminilm": ("cross-encoder/mmarco-mMiniLMv2-L12-H384-v1", "onnx/model.onnx"),
    "mminilm-int8": ("cross-encoder/mmarco-mMiniLMv2-L12-H384-v1", "onnx/model_qint8_arm64.onnx"),
}
if name in CUSTOM:
    repo, file = CUSTOM[name]
    TextCrossEncoder.add_custom_model(name, ModelSource(hf=repo), model_file=file)
texts: list[str] = []
for f in sorted(glob.glob(f"{corpus}/*.md")):
    t = open(f).read()
    texts += [t[i : i + 1000] for i in range(0, len(t), 850)]
query = "Wie setze ich ein fehlerhaftes Deployment auf die vorherige Version zurück?"
rss0 = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss  # bytes on macOS
t0 = time.perf_counter()
m = TextCrossEncoder(name, cache_dir=cache, threads=threads, providers=providers)
load_s = time.perf_counter() - t0
list(m.rerank(query, texts[:4]))
lat = {}
for n in (10, 20, 30):
    runs = []
    for r in range(3):
        t = time.perf_counter()
        scores = list(m.rerank(query, texts[r * 30 : r * 30 + n], batch_size=16))
        runs.append(time.perf_counter() - t)
    lat[n] = statistics.median(runs)
print(
    f"{name} threads={threads} {providers or ''}: load {load_s:.1f} s, "
    f"peak RSS +{(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - rss0) / 1e9:.2f} GB, "
    + ", ".join(f"{n} pairs {s * 1000:.0f} ms" for n, s in lat.items())
    + f", scores {min(scores):.2f}…{max(scores):.2f}"
)
