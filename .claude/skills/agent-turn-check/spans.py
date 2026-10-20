"""Print the Phoenix span tree of one trace (parent links, not start order)."""

from __future__ import annotations  # system python3 may predate 3.10

import json
import sys
import urllib.request

url = f"http://localhost:6006/v1/projects/default/spans?trace_id={sys.argv[1]}&limit=200"
spans = json.load(urllib.request.urlopen(url))["data"]
children: dict[str | None, list[dict]] = {}
ids = {s["context"]["span_id"] for s in spans}
for span in sorted(spans, key=lambda s: s["start_time"]):
    children.setdefault(span["parent_id"] if span["parent_id"] in ids else None, []).append(span)


def show(parent: str | None, depth: int) -> None:
    for span in children.get(parent, []):
        attrs = span.get("attributes", {})
        extra = " ".join(
            str(attrs[k]) for k in ("llm.prompt_template.version", "llm.model_name") if k in attrs
        )
        print("  " * depth + f"{span['name']} [{span.get('span_kind')}] {extra}".rstrip())
        show(span["context"]["span_id"], depth + 1)


show(None, 0)
