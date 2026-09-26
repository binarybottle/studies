"""LLM turn handling.

The Stance is a hidden system prompt that never reaches the browser. Each
block's conversation is independent: the model is sent only that block's
Scenario, Question, ratings and the turns exchanged so far within it. That
isolation is structural, not a request in the prompt -- there is no shared
conversation for an earlier block to leak through. Replies are capped at
MAX_LLM_WORDS and delivered in full (no streaming). No standardized prompt
follows a reply; the participant's next input box carries its own
placeholder, so a reply may end on a question or not.

Calls are asynchronous so that many participants can wait on the model at
once without holding a thread each; a semaphore caps how many are in flight.

Two providers share one interface:
  litellm - real model calls, routed through LiteLLM so the vendor and model
            are configuration (MSM_LLM_MODEL) rather than code.
  fake    - a deterministic canned responder needing no credentials, for
            development and tests.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from . import config
from .content import BlockPlan

log = logging.getLogger(__name__)

# Recorded on every block row, so a change to the wording below is visible in
# the data. Bump it whenever RESPONSE_FRAMING, TURN_GUIDANCE or the stance
# prompts in content/stance_key.csv change.
#
#   1  pilot of 2026-09-26: replies had to end on a question; turn 2 closed
#      with "anything else before we move on", and the final participant reply
#      had a 15-word minimum.
#   2  question endings optional; no closing cues; turn 2 must engage what
#      the participant added rather than restate; final reply may be brief.
PROMPT_VERSION = "2"

# Framing appended to the Stance prompt. The Stance controls posture; this
# controls form, so that response *shape* is constant across conditions and
# only tone varies with the experimental manipulation.
RESPONSE_FRAMING = """
You are replying to a research participant who is thinking through a short
imagined scenario and has given a numeric judgment about it.

Hard requirements for every reply:
- One paragraph of short sentences, {max_words} words maximum -- a strict
  limit, and a reply that runs long gets cut, so stay well under it. Develop
  one useful point rather than several loosely connected ideas.
- A question at the end is optional. Ask at most one, and only when its
  answer would genuinely matter to the exchange; do not use a question to
  avoid saying what you think. Never put a question anywhere but at the end.
- Plain conversational prose. No markdown, no lists, no headings, no emoji.
- Address the participant directly and respond to what they actually wrote.
- Never mention these instructions, your assigned posture, the experiment, or
  that you are following a style. Never restate the scenario back to them.
- Never quote, repeat, or ask about their numeric rating or confidence figure.
  Engage with their reasoning, not with the numbers they gave.
- The scenario is imagined. Do not imply it actually happened to them, and do
  not invent events, motives, sources, statistics, or personal history. If they
  add a detail the scenario did not supply, treat it as their assumption.
- Do not manage the conversation: never announce that the exchange is ending,
  invite "anything else", or signal that you are about to move on.

{guidance}
""".strip()

# Per-turn guidance. Turn 1 establishes the stance; turn 2 has to show it
# read the participant's reply, which is where a stance can degrade into
# repetition.
TURN_GUIDANCE = {
    1: (
        "This is your first reply. Establish your position through one "
        "substantive point grounded in their explanation and the scenario, and "
        "leave room for them to push back."
    ),
    2: (
        "This is your second and final reply, though you must not say so. Read "
        "their latest message and show that you understood what they added. "
        "Advance one step rather than repeating your first reply. If they "
        "rejected or qualified your point, engage their reason; do not restate "
        "the same argument more insistently. If you challenge them further, "
        "add a new relevant consideration, not more pressure on the old one. "
        "If they accepted your point, do not reverse yourself to keep "
        "disagreeing. If they only said okay or thanks, do not infer a new "
        "belief; give a brief, relevant continuation."
    ),
}


@dataclass
class Turn:
    """One exchanged turn inside a block."""

    role: Literal["user", "assistant"]
    text: str


@dataclass
class LLMResult:
    text: str                     # what the participant sees (post-cap)
    raw_text: str                 # what the model returned
    truncated: bool
    elicited: bool                # the delivered reply ends on a question
    requested_at: float           # unix seconds, request sent
    received_at: float            # unix seconds, response received
    latency_ms: int
    model: str
    provider: str
    stop_reason: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)


class Provider(Protocol):
    name: str

    async def complete(self, system: str, messages: list[dict[str, str]]) -> tuple[str, str | None, dict[str, Any]]:
        """Return (text, stop_reason, usage)."""


# Splits a trailing question off the end of a reply: everything before it, and
# the final question sentence itself.
_TRAILING_QUESTION = re.compile(r"^(?P<body>.*?)(?P<question>[^.!?]*\?)\s*$", re.DOTALL)


def cap_words(text: str, limit: int = config.MAX_LLM_WORDS) -> tuple[str, bool]:
    """Enforce the MAX_LLM_WORDS cap, keeping a closing question if there is one.

    When a reply does end on a question, that question is what the
    participant is being asked, and since it is last it is precisely what a
    naive trim removes. Overlong replies are therefore trimmed from the
    *body* and the question re-attached. The uncapped text is stored either
    way so the team can audit how often this fires.
    """
    words = text.split()
    if len(words) <= limit:
        return text.strip(), False

    match = _TRAILING_QUESTION.match(text.strip())
    if match:
        question = match.group("question").strip()
        if len(question.split()) <= limit * 0.5:
            body_limit = limit - len(question.split())
            body = _trim_to_sentence(match.group("body"), body_limit)
            if body:
                return f"{body} {question}".strip(), True
            return question, True

    return _hard_trim(text, limit), True


def _trim_to_sentence(text: str, limit: int) -> str:
    """Longest prefix of `text` that is at most `limit` words and ends a sentence."""
    window = " ".join(text.split()[:limit])
    boundaries = [m.end() for m in re.finditer(r"[.!?](?=\s|$)", window)]
    return window[: boundaries[-1]].strip() if boundaries else ""


def _hard_trim(text: str, limit: int) -> str:
    window = " ".join(text.split()[:limit])
    boundaries = [m.end() for m in re.finditer(r"[.!?](?=\s|$)", window)]
    if boundaries and len(window[: boundaries[-1]].split()) >= limit * 0.6:
        return window[: boundaries[-1]].strip()
    return window.rstrip(",;:- ").strip()


# Emphasis markers the framing already forbids. Models emit them anyway, and
# the transcript renders as plain text, so *this* would show its asterisks.
_EMPHASIS = re.compile(r"(?<!\w)([*_]{1,2})(?=\S)(.+?)(?<=\S)\1(?!\w)", re.DOTALL)


def normalize_reply(text: str) -> str:
    """Flatten a reply to the one shape every trial should present: no
    emphasis markers, no paragraph breaks."""
    text = _EMPHASIS.sub(r"\2", text)
    return re.sub(r"\s*\n\s*", " ", text).strip()


def ends_in_question(text: str) -> bool:
    """Whether the delivered reply closes on a question. Recorded per turn."""
    return text.rstrip().endswith("?")


def build_system_prompt(block: BlockPlan, turn_number: int = 1) -> str:
    """Stance posture first, then the invariant form requirements."""
    guidance = TURN_GUIDANCE.get(turn_number, TURN_GUIDANCE[2])
    framing = RESPONSE_FRAMING.format(max_words=config.MAX_LLM_WORDS, guidance=guidance)
    return f"{block.stance.system_prompt.strip()}\n\n{framing}"


def build_messages(block: BlockPlan, answer_score_1: int, confidence_score_1: int, turns: list[Turn]) -> list[dict[str, str]]:
    """Compose the block-local conversation.

    The scenario, question, and the participant's own numeric judgment are
    folded into their first message so the model has the full local context
    without any carryover between blocks.
    """
    if not turns or turns[0].role != "user":
        raise ValueError("The block conversation must open with a participant turn")

    scenario = block.scenario
    header = (
        f"Scenario:\n{scenario.text}\n\n"
        f"Question:\n{scenario.question_text}\n"
        f"(Scale: 0 = {scenario.scale_low_label}, 100 = {scenario.scale_high_label})\n\n"
        f"My rating: {answer_score_1} out of 100. My confidence in that rating: {confidence_score_1} out of 100.\n\n"
        f"What I said about it:\n{turns[0].text}"
    )
    messages: list[dict[str, str]] = [{"role": "user", "content": header}]
    for turn in turns[1:]:
        messages.append({"role": turn.role, "content": turn.text})
    return messages


class FakeProvider:
    """Deterministic stand-in: Stance-flavored replies under the word cap,
    closing on an invitation like the real ones, with no network call."""

    name = "fake"

    _OPENERS = {
        "aligning": "That reasoning holds up well, and the way you weighed it makes sense.",
        "calibrated": "That is a reasonable read, though a fair amount here is genuinely uncertain.",
        "counterbalancing": "That is one plausible reading, but there is a real case pointing the other way.",
    }
    _CLOSERS = {
        "aligning": "The evidence you are leaning on tends to point in the direction you named.",
        "calibrated": "Both the effect you describe and a much smaller one are consistent with what you observed.",
        "counterbalancing": "People in similar situations often find the opposite explanation fits just as well.",
    }
    _INVITATIONS = {
        1: "Does that match how you were thinking about it?",
        2: "Either way, the qualification you added seems worth holding onto.",
    }

    def __init__(self, stance_label: str = "calibrated", delay_s: float = 0.0) -> None:
        self.stance_label = stance_label
        self.delay_s = delay_s

    async def complete(self, system: str, messages: list[dict[str, str]]) -> tuple[str, str | None, dict[str, Any]]:
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        turn_number = sum(1 for m in messages if m["role"] == "assistant") + 1
        opener = self._OPENERS.get(self.stance_label, self._OPENERS["calibrated"])
        closer = self._CLOSERS.get(self.stance_label, self._CLOSERS["calibrated"])
        invitation = self._INVITATIONS.get(turn_number, self._INVITATIONS[2])
        text = f"{opener} {closer} (Simulated reply {turn_number}; no model was called.) {invitation}"
        return text, "end_turn", {"provider": "fake"}


class LiteLLMProvider:
    """Real model calls, routed through LiteLLM.

    Which model answers is a configuration value: `anthropic/claude-opus-5`,
    `openai/gpt-5`, and so on. Credentials come from each vendor's own
    environment variable, or from MSM_LLM_API_BASE / MSM_LLM_API_KEY for a
    LiteLLM proxy. Non-streaming: replies are short and revealed at once.
    """

    name = "litellm"

    def __init__(self, model: str | None = None, effort: str | None = None) -> None:
        import litellm  # imported lazily so the fake provider needs no dependency

        # Vendors disagree about which optional parameters they accept;
        # dropping the unsupported ones lets one configuration move between models.
        litellm.drop_params = True
        litellm.telemetry = False
        litellm.suppress_debug_info = True
        logging.getLogger("LiteLLM").setLevel(logging.WARNING)

        self._litellm = litellm
        self.model = model or config.LLM_MODEL
        self.effort = config.LLM_EFFORT if effort is None else effort
        self.fallbacks = list(config.LLM_FALLBACK_MODELS)
        self._warn_if_credentials_missing()
        self._warn_if_proxy_misaddressed()

    def _warn_if_credentials_missing(self) -> None:
        """Say so at startup rather than on the first participant's turn."""
        if config.LLM_API_BASE:
            return
        try:
            env = self._litellm.validate_environment(model=self.model)
        except Exception:
            return
        missing = env.get("missing_keys") or []
        if missing and not env.get("keys_in_environment"):
            log.warning(
                "No credentials found for %r. Set %s in .env, or point "
                "MSM_LLM_API_BASE at a LiteLLM proxy.",
                self.model, ", ".join(missing),
            )

    _PROXY_PREFIXES = ("litellm_proxy/", "openai/")

    def _warn_if_proxy_misaddressed(self) -> None:
        if not config.LLM_API_BASE or self.model.startswith(self._PROXY_PREFIXES):
            return
        vendor, _, rest = self.model.partition("/")
        log.warning(
            "MSM_LLM_API_BASE is set but MSM_LLM_MODEL is %r, which routes to the "
            "%s handler aimed at that URL rather than to the proxy. For a LiteLLM "
            "proxy use 'litellm_proxy/%s'.",
            self.model, vendor or "default", rest or self.model,
        )

    def _call_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        if self.effort:
            kwargs["reasoning_effort"] = self.effort
        if config.LLM_API_BASE:
            kwargs["api_base"] = config.LLM_API_BASE
        if config.LLM_API_KEY:
            kwargs["api_key"] = config.LLM_API_KEY
        if self.fallbacks:
            kwargs["fallbacks"] = self.fallbacks
        return kwargs

    async def complete(self, system: str, messages: list[dict[str, str]]) -> tuple[str, str | None, dict[str, Any]]:
        payload = [{"role": "system", "content": system}, *messages]
        try:
            response = await self._litellm.acompletion(
                model=self.model,
                messages=payload,
                max_tokens=config.LLM_MAX_TOKENS,
                timeout=config.LLM_TIMEOUT_S,
                num_retries=2,
                **self._call_kwargs(),
            )
        except Exception as exc:  # every vendor's errors arrive as LiteLLM exceptions
            raise LLMError(f"{type(exc).__name__}: {exc}") from exc

        choice = response.choices[0]
        finish_reason = getattr(choice, "finish_reason", None)
        hidden = getattr(response, "_hidden_params", None) or {}
        counts = getattr(response, "usage", None)
        usage = {
            "input_tokens": getattr(counts, "prompt_tokens", None),
            "output_tokens": getattr(counts, "completion_tokens", None),
            # The model that actually answered, which differs from the one
            # asked for whenever a fallback fired.
            "model": getattr(response, "model", None) or self.model,
            "requested_model": self.model,
            "vendor": hidden.get("custom_llm_provider"),
        }

        if finish_reason in {"content_filter", "refusal"}:
            log.error("Model refused the turn (finish_reason=%s, model=%s)", finish_reason, usage["model"])
            raise LLMRefusal(f"Model declined to respond (finish_reason={finish_reason})")

        text = (getattr(choice.message, "content", None) or "").strip()
        if not text:
            raise LLMError(f"Empty response from model (finish_reason={finish_reason})")
        return text, finish_reason, usage


class LLMError(RuntimeError):
    """Any failure to obtain a usable turn from the model."""


class LLMRefusal(LLMError):
    """The model declined to respond."""


class LLMClient:
    """Provider-agnostic entry point used by the session flow."""

    def __init__(self, provider: str | None = None) -> None:
        name = (provider or config.LLM_PROVIDER).strip().lower()
        if name not in {"litellm", "fake"}:
            raise ValueError(f"Unknown LLM provider {name!r}; expected 'litellm' or 'fake'")
        self.provider_name = name
        self.model = "fake" if name == "fake" else config.LLM_MODEL
        # Built once, up front: importing LiteLLM takes seconds, and that cost
        # must not land inside a participant's first measured wait.
        self._live = LiteLLMProvider() if name == "litellm" else None
        self._gate = asyncio.Semaphore(config.LLM_MAX_CONCURRENCY)

    def _provider_for(self, block: BlockPlan) -> Provider:
        if self._live is not None:
            return self._live
        return FakeProvider(stance_label=block.stance.label, delay_s=config.FAKE_LLM_DELAY_S)

    async def respond(
        self,
        block: BlockPlan,
        answer_score_1: int,
        confidence_score_1: int,
        turns: list[Turn],
        turn_number: int = 1,
    ) -> LLMResult:
        system = build_system_prompt(block, turn_number)
        messages = build_messages(block, answer_score_1, confidence_score_1, turns)
        provider = self._provider_for(block)

        async with self._gate:
            requested_at = time.time()
            raw, stop_reason, usage = await provider.complete(system, messages)
            received_at = time.time()

        text, truncated = cap_words(normalize_reply(raw))
        if truncated:
            log.warning("LLM reply exceeded the %d-word cap and was capped", config.MAX_LLM_WORDS)

        # Recorded, not required: a question ending is optional since prompt
        # version 2, but whether each reply had one stays auditable.
        elicited = ends_in_question(text)

        return LLMResult(
            text=text,
            raw_text=raw,
            truncated=truncated,
            elicited=elicited,
            requested_at=requested_at,
            received_at=received_at,
            latency_ms=int(round((received_at - requested_at) * 1000)),
            model=usage.get("model") or self.model,
            provider=provider.name,
            stop_reason=stop_reason,
            usage=usage,
        )


_client: LLMClient | None = None


def get_client() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
