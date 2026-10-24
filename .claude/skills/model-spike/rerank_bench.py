"""One model per process: load time, RSS, latency for 20/50 pairs, sanity ranking."""
import glob, os, statistics, sys, time
import psutil
which, corpus, cache = sys.argv[1], sys.argv[2], sys.argv[3]
proc = psutil.Process()
texts = []
for f in sorted(glob.glob(f"{corpus}/*.md")):
    t = open(f).read()
    texts += [t[i:i + 1000] for i in range(0, len(t), 850)]
passages = texts[:50]
rollback = next(p for p in texts if "kubectl rollout undo" in p)
queries = ["Wie setze ich ein fehlerhaftes Deployment auf die vorherige Version zurück?",
           "How do I roll back a Kubernetes deployment?"]
rss0 = proc.memory_info().rss
t0 = time.perf_counter()
if which == "bge":
    import torch
    from sentence_transformers import CrossEncoder
    dev = "mps" if torch.backends.mps.is_available() else "cpu"
    m = CrossEncoder("BAAI/bge-reranker-v2-m3", device=dev, cache_folder=cache,
                     model_kwargs={"dtype": torch.float16})
    score = lambda q, ps: list(m.predict([(q, p) for p in ps], batch_size=16))
else:
    from fastembed.rerank.cross_encoder import TextCrossEncoder
    name = {"jina": "jinaai/jina-reranker-v2-base-multilingual",
            "minilm": "Xenova/ms-marco-MiniLM-L-6-v2"}[which]
    m = TextCrossEncoder(name, cache_dir=cache)
    score = lambda q, ps: list(m.rerank(q, ps, batch_size=16))
load_s = time.perf_counter() - t0
score(queries[1], passages[:4])  # warm-up
lat = {}
for n in (20, 50):
    runs = []
    for _ in range(3):
        t = time.perf_counter(); score(queries[0], passages[:n]); runs.append(time.perf_counter() - t)
    lat[n] = statistics.median(runs)
ranks = []
for q in queries:
    cand = passages[:29] + [rollback]
    s = score(q, cand)
    ranks.append(sorted(range(30), key=lambda i: -s[i]).index(29) + 1)
extra = ""
if which == "bge":
    extra = f", mps driver {torch.mps.driver_allocated_memory()/1e9:.2f} GB"
print(f"{which}: load {load_s:.1f} s, RSS +{(proc.memory_info().rss-rss0)/1e9:.2f} GB "
      f"(peak {psutil.Process().memory_info().rss/1e9:.2f} GB){extra}, "
      f"20 pairs {lat[20]*1000:.0f} ms, 50 pairs {lat[50]*1000:.0f} ms, "
      f"rank of the rollback chunk DE/EN: {ranks}")
