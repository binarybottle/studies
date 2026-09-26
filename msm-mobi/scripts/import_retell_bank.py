#!/usr/bin/env python3
"""Turn the Retell prototype's scenario bank into content/scenario_key.csv.

The Retell conversation flow carried the 96 vignettes inside four "picker"
code nodes, one per goal, as JavaScript array literals. This pulls them out
and writes them in the schema the app reads, so the same bank can be piloted
here while the team finalises the real battery.

    scripts/import_retell_bank.py "~/Downloads/Retell MoBI-MSM All-12 Randomized Prototype v3.json"

Each vignette becomes one row. The Retell design asked for agreement with an
appraisal statement, so the Question is that agreement question and the scale
anchors are "Not at all" / "Completely agree". Replace the file outright when
the real battery exists; nothing else in the app refers to it by content.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

# Retell goal -> this app's category label (content/category_key.csv).
CATEGORY = {
    "Information": "know_understand",
    "Decision": "decide_advice",
    "Reflection": "reflect_meaning",
    "Support": "seek_support",
}

SCALE_LOW = "Do not agree at all"
SCALE_HIGH = "Completely agree"


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    flow = json.loads(Path(sys.argv[1]).expanduser().read_text(encoding="utf-8"))
    nodes = flow["conversationFlow"]["nodes"]

    rows: list[dict[str, str]] = []
    for node in nodes:
        code = node.get("code") or ""
        goal = re.search(r'goal:\s*"(\w+)"', code)
        bank = re.search(r"const scenarios = (\[.*?\]);", code, re.DOTALL)
        if not (goal and bank):
            continue
        category = CATEGORY[goal.group(1)]
        for item in json.loads(bank.group(1)):
            rows.append({
                "scenario_label": item["id"].lower().replace("-", "_"),
                "category_label": category,
                "scenario_text": item["vignette"],
                "question_text": f"How much do you agree with this statement? “{item['appraisal']}”",
                "scale_low_label": SCALE_LOW,
                "scale_high_label": SCALE_HIGH,
            })

    out = Path(__file__).resolve().parent.parent / "content" / "scenario_key.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    by_cat = {c: sum(r["category_label"] == c for r in rows) for c in CATEGORY.values()}
    print(f"wrote {len(rows)} scenarios to {out}: {by_cat}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
