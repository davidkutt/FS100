"""Summarize an SSE v2 capture of /v1/agent: one line per event, tokens joined into the answer."""

import json
import sys

answer: list[str] = []
for block in open(sys.argv[1]).read().split("\n\n"):
    if not block.strip() or block.startswith(":"):
        continue  # keepalive comments
    fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
    event, data = fields["event"], json.loads(fields["data"])
    if event == "token":
        answer.append(data["text"])
        continue
    if event == "tool_result":
        data = {k: data[k] for k in ("id", "status", "summary", "truncated", "durationMs")}
    if event == "sources":
        data = [(s["n"], s["title"], round(s["score"], 2)) for s in data["sources"]]
    print(event, data)
print("ANSWER:", "".join(answer))
