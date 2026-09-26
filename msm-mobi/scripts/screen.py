#!/usr/bin/env python3
"""Screen downloaded study data for low-effort sessions.

Reads the quality export and applies the criteria from the README, so the
decision of whom to look at is a script rather than a spreadsheet. With the
blocks export as well, it prints the flagged participants' own replies, which
is what a rejection has to be justified from.

    python scripts/screen.py ~/Desktop/msm-quality-2026-09-27.csv
    python scripts/screen.py quality.csv --blocks blocks.csv --show
    curl -s "https://msm-mobi.study.childmind.org/admin/quality.csv?token=$TOKEN" | python scripts/screen.py -

Thresholds are flags with the README's defaults; tune them on the first
batches. Nothing here is a verdict: a flag means "read this one", and the
exit code is 1 when there is something to read.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path


def _num(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def signals(row: dict[str, str], args: argparse.Namespace) -> tuple[list[str], list[str]]:
    """(strong reasons, weaker notes) for one participant."""
    strong: list[str] = []
    notes: list[str] = []
    failed = _num(row.get("attention_failed")) or 0
    read = _num(row.get("min_read_seconds"))
    distinct = _num(row.get("distinct_reply_ratio"))
    words = _num(row.get("median_reply_words"))
    sd = _num(row.get("rating_sd"))
    unchanged = _num(row.get("unchanged_rating_share"))
    pastes = _num(row.get("paste_blocked")) or 0
    focus = _num(row.get("focus_lost_seconds")) or 0
    done = _num(row.get("blocks_completed")) or 0

    if failed >= 2:
        strong.append("failed both attention checks")
    elif failed == 1:
        notes.append("failed one attention check")
    if read is not None and read < args.min_read:
        strong.append(f"rated a scenario after {read:.0f}s")
    if distinct is not None and distinct < args.min_distinct:
        strong.append(f"reused replies (distinct ratio {distinct:.2f})")
    if words is not None and words <= args.max_short_words:
        strong.append(f"median reply {words:.0f} words")
    if sd is not None and sd == 0 and done >= 3:
        strong.append("identical first rating in every block")
    if unchanged is not None and unchanged == 1 and words is not None and words <= 5 and done >= 3:
        strong.append("never changed a rating, with very short replies")
    if pastes > 0:
        notes.append(f"{pastes:.0f} paste attempt{'s' if pastes > 1 else ''}")
    if focus > args.focus_minutes * 60:
        notes.append(f"tab hidden {focus / 60:.0f} min")
    return strong, notes


def load_blocks(path: Path) -> dict[str, list[dict[str, str]]]:
    out: dict[str, list[dict[str, str]]] = {}
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out.setdefault(row["participant_id"], []).append(row)
    for rows in out.values():
        rows.sort(key=lambda r: int(r["block_index"] or 0))
    return out


def show_replies(pid: str, blocks: dict[str, list[dict[str, str]]]) -> None:
    for b in blocks.get(pid, []):
        if b.get("is_practice") == "1":
            continue
        head = (f"    block {b['block_index']:>2}  {b['category_label']:<16} {b['stance_label']:<16} "
                f"rating {b['answer_score_1'] or '-':>3} -> {b['answer_score_2'] or '-':>3}")
        print(head)
        for n in (1, 2, 3):
            text = (b.get(f"user_text_{n}") or "").strip().replace("\n", " ")
            if text:
                print(f"      you {n}: {text[:160]}{'…' if len(text) > 160 else ''}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("quality", help="quality.csv, or - for stdin")
    ap.add_argument("--blocks", type=Path, help="blocks.csv, to print flagged participants' replies")
    ap.add_argument("--show", action="store_true", help="print the replies of every flagged participant")
    ap.add_argument("--all", action="store_true", help="list every participant, not only flagged ones")
    ap.add_argument("--keep-test", action="store_true", help="include SIM-* and walkthrough-* IDs")
    ap.add_argument("--min-read", type=float, default=5.0, help="seconds on a scenario before rating (default 5)")
    ap.add_argument("--min-distinct", type=float, default=0.7, help="distinct reply ratio (default 0.7)")
    ap.add_argument("--max-short-words", type=float, default=3, help="median reply words counted as short (default 3)")
    ap.add_argument("--focus-minutes", type=float, default=10, help="tab-hidden minutes worth a note (default 10)")
    ap.add_argument("--flag-on", type=int, default=2, help="strong signals needed to flag (default 2; both checks failed always flags)")
    args = ap.parse_args()

    source = sys.stdin if args.quality == "-" else open(args.quality, newline="", encoding="utf-8")
    rows = list(csv.DictReader(source))
    if not args.keep_test:
        rows = [r for r in rows if not r["pid"].startswith(("SIM-", "walkthrough-"))]
    blocks = load_blocks(args.blocks) if args.blocks else {}

    stages = Counter(r["stage"] for r in rows)
    print(f"{len(rows)} participants: " + ", ".join(f"{n} {s}" for s, n in sorted(stages.items())))
    print()

    flagged = 0
    for r in rows:
        strong, notes = signals(r, args)
        both = any(s.startswith("failed both") for s in strong)
        is_flag = both or len(strong) >= args.flag_on
        if not (is_flag or args.all):
            continue
        flagged += is_flag
        mark = "FLAG " if is_flag else "     "
        done = r.get("blocks_completed") or "0"
        mins = r.get("total_minutes") or "-"
        print(f"{mark}{r['pid']:<26} {r['stage']:<10} {done:>2} blocks  {mins:>5} min")
        for s in strong:
            print(f"      ! {s}")
        for n in notes:
            print(f"      · {n}")
        if is_flag and args.show and blocks:
            show_replies(r["pid"], blocks)
        print()

    print(f"{flagged} flagged of {len(rows)}. A flag means read the transcript, not reject.")
    if flagged and not (args.show and blocks):
        print("Add --blocks blocks.csv --show to print their replies here.")
    return 1 if flagged else 0


if __name__ == "__main__":
    raise SystemExit(main())
