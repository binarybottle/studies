"""Runtime configuration and protocol constants.

Values the protocol calls tunable live here so the research team can change
them in one place without touching flow logic. Everything environment-driven
comes from the study's ``.env`` (loaded by compose on the droplet, or by
``_load_dotenv`` for a local run).
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Minimal .env support for local runs; real environment variables win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(PROJECT_ROOT / ".env")


def _path_env(name: str, default: str) -> Path:
    raw = os.environ.get(name, default)
    p = Path(raw)
    return p if p.is_absolute() else PROJECT_ROOT / p


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes"}


# --- Protocol constants (from the MoBI-MSM participant UX spec) ---

REAL_BLOCK_COUNT = 12
"""Blocks 1-12, one per Category x Stance combination."""

PRACTICE_BLOCK_INDEX = 0
"""Practice block is block 0; real blocks are 1-12."""

MIN_RESPONSE_WORDS = 1
"""Free-text replies only have to be non-empty. The lab protocol's 15-word
floor was dropped after the first online pilot: it produced padded, repeated
sentences rather than engagement. Low-effort entries are flagged after the
fact instead (the quality export), not blocked at entry."""

MIN_FINAL_RESPONSE_WORDS = 1
"""User Text Response 3, kept separate so the two can differ again if the
team wants a floor on the first replies only."""

MAX_LLM_WORDS = 75
"""Hard cap on each LLM Text Response. Each reply both responds and invites
the next response in the same message, which is why it is above the spec's
original 50."""

SCORE_MIN = 0
SCORE_MAX = 100
"""Numeric score fields are whole numbers in [0, 100]."""

THINKING_SLOW_AFTER_MS = 7000
"""When the thinking indicator switches to its 'still thinking' text. A soft
threshold, not a cutoff."""

ATTENTION_CHECKS = {
    # block index -> (check id, instruction, expected answer). Asked at the
    # top of that block, before its Scenario. Block 1 follows the practice
    # round, a few minutes in; block 7 is the halfway point of the twelve.
    # Both are plain instructed responses in the same numeric box the
    # participant has been using, so a failure means the instruction was
    # not read, not that it was hard.
    1: ("ac1", "A quick check that you are reading: for this box only, please enter the number 37.", 37),
    7: ("ac2", "Another quick check that you are reading: for this box only, please enter the number 72.", 72),
}

ATTENTION_FAILURE_THRESHOLD = 2
"""Failed checks needed before a finished session gets the attention code
rather than the completion code. Both, never one: a single miss in an hour
is not evidence of anything."""

FIXATION_CROSS_MS = 500
"""Blank hold with a central cross before every block's Scenario. Kept from
the lab protocol so the online and in-lab experiences match; it costs the
participant half a second per block."""


# --- Study identity, shown to participants ---

STUDY_NAME = os.environ.get("STUDY_NAME", "Scenario conversations pilot")
ORG_NAME = os.environ.get("ORG_NAME", "Child Mind Institute")
CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "olivia.fitzpatrick@childmind.org")
DURATION_TEXT = os.environ.get("DURATION_TEXT", "45 to 60 minutes")
PRIVACY_URL = "https://childmind.org/privacy/"
TERMS_URL = "https://childmind.org/terms/"


# --- Prolific ---

PROLIFIC_COMPLETE_URL = "https://app.prolific.com/submissions/complete?cc={code}"

# One code per outcome. In Prolific, attach "approve automatically" to
# CC_COMPLETE and "custom screening with a fixed reward" to CC_NO_CONSENT.
# Never attach a rejection action to either.
CC_COMPLETE = os.environ.get("PROLIFIC_CC_COMPLETE", "REPLACE_ME")
CC_NO_CONSENT = os.environ.get("PROLIFIC_CC_NO_CONSENT", "REPLACE_ME_TOO")
CC_ATTENTION = os.environ.get("PROLIFIC_CC_ATTENTION", "")
"""Optional. A finished session that failed both attention checks returns
with this code, so Prolific can hold it for review (attach "manually
review", never a rejection). Unset, such sessions get CC_COMPLETE and the
failures are only in the export."""

ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
"""Guards the /admin exports. Empty disables them entirely."""


# --- Paths ---

CONTENT_DIR = _path_env("MSM_CONTENT_DIR", "content")
"""Holds the category, scenario, stance and practice CSVs."""

DATA_DIR = _path_env("MSM_DATA_DIR", "data")
DB_PATH = Path(os.environ.get("STUDY_DB_PATH") or DATA_DIR / "study.db")
"""STUDY_DB_PATH is what compose.yml sets, pointing into the study's volume,
so the same variable name works for every study on the droplet."""


# --- LLM ---

LLM_PROVIDER = os.environ.get("MSM_LLM_PROVIDER", "litellm").strip().lower()
"""``litellm`` for real runs, ``fake`` for development and tests."""

LLM_MODEL = os.environ.get("MSM_LLM_MODEL", "anthropic/claude-opus-5").strip()
"""A LiteLLM model identifier, ``vendor/model``. The model every session ran
against is recorded on its row, so a change mid-study is visible in the data."""

LLM_FALLBACK_MODELS = [
    m.strip() for m in os.environ.get("MSM_LLM_FALLBACK_MODELS", "").split(",") if m.strip()
]
"""Optional models tried in order if the primary fails. Leave unset for a
study that must not silently change models."""

LLM_EFFORT = os.environ.get("MSM_LLM_EFFORT", "").strip().lower()
"""Reasoning effort, sent only when set. Unset by default: on the lab gateway
it moved mean latency from ~2.5 s to ~6.7 s, straddling THINKING_SLOW_AFTER_MS."""

LLM_API_BASE = os.environ.get("MSM_LLM_API_BASE", "").strip()
LLM_API_KEY = os.environ.get("MSM_LLM_API_KEY", "").strip()
"""Set both to route through a LiteLLM proxy. Left empty, LiteLLM reads the
vendor's own credential (ANTHROPIC_API_KEY, ...) from the environment."""

LLM_MAX_TOKENS = int(os.environ.get("MSM_LLM_MAX_TOKENS", "4000"))
LLM_TIMEOUT_S = float(os.environ.get("MSM_LLM_TIMEOUT_S", "60"))
FAKE_LLM_DELAY_S = float(os.environ.get("MSM_FAKE_LLM_DELAY_S", "0"))

LLM_MAX_CONCURRENCY = int(os.environ.get("MSM_LLM_MAX_CONCURRENCY", "32"))
"""How many model calls may be in flight at once. Beyond this, turns queue
rather than tripping the vendor's rate limit and failing the participant."""
