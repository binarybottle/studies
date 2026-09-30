"""Loading the content CSVs and resolving a participant's plan.

Three key files plus the practice record, in ``config.CONTENT_DIR``:

``category_key.csv``     category_label, category_name
``scenario_key.csv``     scenario_label, category_label, scenario_text,
                         question_text, scale_low_label, scale_high_label
``stance_key.csv``       stance_label, stance_name, system_prompt
``practice_scenario.csv`` one row: the fixed practice block

There is no assignment file. Block order and content come from
``assign.build_assignment`` and the sequence number issued at consent; the
resolved plan is stored on the participant row so it survives content edits.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import assign, config


class ContentError(RuntimeError):
    """The content files cannot be loaded or a plan cannot be resolved."""


@dataclass(frozen=True)
class Scenario:
    label: str
    category_label: str
    text: str
    question_text: str
    scale_low_label: str
    scale_high_label: str


@dataclass(frozen=True)
class Stance:
    label: str
    name: str
    system_prompt: str


@dataclass(frozen=True)
class BlockPlan:
    """One resolved block: what to show, and which hidden Stance drives the LLM."""

    block_index: int          # 0 = practice, 1..12 = real blocks
    is_practice: bool
    category_label: str
    category_name: str
    scenario: Scenario
    stance: Stance
    ends_with_question: bool = True   # whether the chatbot's replies end on a question


@dataclass(frozen=True)
class ParticipantPlan:
    participant_id: str
    assignment_index: int
    blocks: tuple[BlockPlan, ...]   # practice first, then blocks 1..12


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise ContentError(f"Required content file not found: {path}")
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in csv.DictReader(f)]
    if not rows:
        raise ContentError(f"Content file is empty: {path}")
    return rows


class ContentLibrary:
    """The content files, loaded once at startup."""

    def __init__(self, content_dir: Path | None = None) -> None:
        self.dir = Path(content_dir or config.CONTENT_DIR)
        self.categories = self._load_categories()
        self.scenarios = self._load_scenarios()
        self.stances = self._load_stances()
        self.practice = self._load_practice()
        self._check_bank()

    # --- loaders ---

    def _load_categories(self) -> dict[str, str]:
        return {r["category_label"]: r["category_name"] for r in _read_csv(self.dir / "category_key.csv")}

    def _load_scenarios(self) -> dict[str, Scenario]:
        out: dict[str, Scenario] = {}
        for r in _read_csv(self.dir / "scenario_key.csv"):
            out[r["scenario_label"]] = Scenario(
                label=r["scenario_label"],
                category_label=r["category_label"],
                text=r["scenario_text"],
                question_text=r["question_text"],
                scale_low_label=r["scale_low_label"],
                scale_high_label=r["scale_high_label"],
            )
        return out

    def _load_stances(self) -> dict[str, Stance]:
        return {
            r["stance_label"]: Stance(
                label=r["stance_label"], name=r["stance_name"], system_prompt=r["system_prompt"]
            )
            for r in _read_csv(self.dir / "stance_key.csv")
        }

    def _load_practice(self) -> BlockPlan:
        row = _read_csv(self.dir / "practice_scenario.csv")[0]
        stance_label = row.get("stance_label") or "calibrated"
        stance = self.stances.get(stance_label)
        if stance is None:
            raise ContentError(f"Practice scenario references unknown stance {stance_label!r}")
        scenario = Scenario(
            label=row["scenario_label"],
            category_label="practice",
            text=row["scenario_text"],
            question_text=row["question_text"],
            scale_low_label=row["scale_low_label"],
            scale_high_label=row["scale_high_label"],
        )
        return BlockPlan(
            block_index=config.PRACTICE_BLOCK_INDEX,
            is_practice=True,
            category_label="practice",
            category_name="Practice",
            scenario=scenario,
            stance=stance,
        )

    def _check_bank(self) -> None:
        """Fail at startup, not at a participant's consent, if the bank cannot
        supply every category."""
        for scenario in self.scenarios.values():
            if scenario.category_label not in self.categories:
                raise ContentError(
                    f"Scenario {scenario.label!r} has unknown category {scenario.category_label!r}"
                )
        for category in self.categories:
            n = len(self.scenarios_for(category))
            if n < len(self.stances):
                raise ContentError(f"Category {category!r} has {n} scenarios; need {len(self.stances)}")

    # --- queries ---

    def scenarios_for(self, category_label: str) -> list[str]:
        """Scenario labels in one category, in file order."""
        return [s.label for s in self.scenarios.values() if s.category_label == category_label]

    # --- assignment ---

    def assignment(self, assignment_index: int) -> list[dict[str, str]]:
        """The real blocks for a sequence number, as label triplets."""
        categories = list(self.categories)
        stances = list(self.stances)
        per_category = {c: self.scenarios_for(c) for c in categories}
        return assign.build_assignment(assignment_index, categories, stances, per_category)

    def resolve(self, participant_id: str, assignment_index: int, blocks: list[dict[str, Any]] | None = None) -> ParticipantPlan:
        """Turn label triplets into a full plan: practice first, then 1..12.

        ``blocks`` is the stored assignment when resuming; omitted, it is
        generated from the sequence number.
        """
        if blocks is None:
            blocks = self.assignment(assignment_index)
        if len(blocks) != config.REAL_BLOCK_COUNT:
            raise ContentError(f"{participant_id}: assignment has {len(blocks)} blocks, expected {config.REAL_BLOCK_COUNT}")
        if any("question" not in b for b in blocks):
            # Stored before the question flag existed; it is a pure function
            # of the sequence number, so the same flags are reconstructed.
            blocks = assign.add_question_flags(assignment_index, [dict(b) for b in blocks])

        resolved: list[BlockPlan] = [self.practice]
        for n, b in enumerate(blocks, start=1):
            category_name = self.categories.get(b["category"])
            if category_name is None:
                raise ContentError(f"{participant_id} block {n}: unknown category label {b['category']!r}")
            scenario = self.scenarios.get(b["scenario"])
            if scenario is None:
                raise ContentError(f"{participant_id} block {n}: unknown scenario label {b['scenario']!r}")
            stance = self.stances.get(b["stance"])
            if stance is None:
                raise ContentError(f"{participant_id} block {n}: unknown stance label {b['stance']!r}")
            resolved.append(
                BlockPlan(
                    block_index=n,
                    is_practice=False,
                    category_label=b["category"],
                    category_name=category_name,
                    scenario=scenario,
                    stance=stance,
                    ends_with_question=bool(b["question"]),
                )
            )
        return ParticipantPlan(participant_id=participant_id, assignment_index=assignment_index, blocks=tuple(resolved))
