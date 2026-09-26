"""Counterbalanced block assignment.

The lab protocol reads a pre-generated assignment CSV. Online, participants
arrive at any hour and nobody hands out IDs, so the app generates each
participant's 12 blocks itself, from a sequence number issued at consent.

Two things are balanced across the sample:

* **Ordinal position.** The 12 Category x Stance conditions are laid out in a
  Williams Latin square. Across every run of 12 consecutive participants each
  condition appears in each position exactly once, and every condition is
  immediately preceded by every other condition exactly once, so first-order
  carryover is balanced too.
* **Scenario use.** Each category's three scenarios are drawn from the bank at
  a rolling offset, so consecutive participants step through the whole bank
  before any scenario repeats. Which of the three lands on which stance is
  shuffled by a generator seeded with the sequence number, so it is fixed for
  a given participant but not systematically tied to position.

Everything is a pure function of ``(assignment_index, bank)``: the plan can
be regenerated, and it is also stored on the participant row at consent so a
later edit to the bank cannot change what someone already saw.
"""

from __future__ import annotations

import random
from itertools import product
from typing import Sequence

from . import config


def williams_square(n: int) -> list[list[int]]:
    """Williams design for ``n`` treatments.

    Row 0 is the standard interleaving 0, 1, n-1, 2, n-2, ...; each later row
    adds 1 modulo n. For even n one square is balanced for first-order
    carryover, which is all 12 needs.
    """
    first: list[int] = []
    lo, hi = 0, n - 1
    for k in range(n):
        first.append(lo if k % 2 == 0 else hi)
        if k % 2 == 0:
            lo += 1
        else:
            hi -= 1
    return [[(v + r) % n for v in first] for r in range(n)]


def condition_order(assignment_index: int, categories: Sequence[str], stances: Sequence[str]) -> list[tuple[str, str]]:
    """The (category, stance) sequence for one participant."""
    conditions = list(product(categories, stances))
    square = williams_square(len(conditions))
    row = square[assignment_index % len(square)]
    return [conditions[c] for c in row]


def scenario_picks(
    assignment_index: int,
    per_category: dict[str, Sequence[str]],
    count: int,
) -> dict[str, list[str]]:
    """``count`` distinct scenario labels per category for one participant.

    The window into each category's bank advances by ``count`` per
    participant, so a bank of 24 is exhausted every eight participants before
    it wraps. A bank smaller than ``count`` is a content error, not something
    to paper over.
    """
    rng = random.Random(assignment_index)
    picks: dict[str, list[str]] = {}
    for category, labels in per_category.items():
        labels = list(labels)
        if len(labels) < count:
            raise ValueError(f"Category {category!r} has {len(labels)} scenarios; need at least {count}")
        start = (assignment_index * count) % len(labels)
        window = [labels[(start + k) % len(labels)] for k in range(count)]
        rng.shuffle(window)
        picks[category] = window
    return picks


def build_assignment(
    assignment_index: int,
    categories: Sequence[str],
    stances: Sequence[str],
    per_category: dict[str, Sequence[str]],
) -> list[dict[str, str]]:
    """One participant's real blocks, in presentation order.

    Returns ``[{"category": ..., "scenario": ..., "stance": ...}, ...]`` with
    ``config.REAL_BLOCK_COUNT`` entries.
    """
    order = condition_order(assignment_index, categories, stances)
    if len(order) != config.REAL_BLOCK_COUNT:
        raise ValueError(f"{len(categories)} categories x {len(stances)} stances != {config.REAL_BLOCK_COUNT} blocks")
    picks = scenario_picks(assignment_index, per_category, len(stances))
    cursor = {c: 0 for c in categories}
    blocks: list[dict[str, str]] = []
    for category, stance in order:
        blocks.append({
            "category": category,
            "scenario": picks[category][cursor[category]],
            "stance": stance,
        })
        cursor[category] += 1
    return blocks
