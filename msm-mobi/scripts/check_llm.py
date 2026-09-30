#!/usr/bin/env python3
"""One-shot check that the real model path works before opening the study.

Sends a block-shaped request through the same code the task uses -- same
LiteLLM call, same system prompt construction, same Stance, same word cap --
and prints the reply plus the latency the participant would have waited.

It also reports how many replies ended on a question, and which prompt
version was used.

    python scripts/check_llm.py
    python scripts/check_llm.py --stance counterbalancing --turn 2 --repeat 5
    python scripts/check_llm.py --question no --repeat 5
    python scripts/check_llm.py --model openai/gpt-5

On the droplet:
    docker compose exec msm-mobi python scripts/check_llm.py --repeat 3
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.content import ContentLibrary  # noqa: E402
from app.llm import PROMPT_VERSION, LLMClient, LLMError, Turn, build_system_prompt  # noqa: E402


async def run(args: argparse.Namespace) -> int:
    lib = ContentLibrary()
    block = lib.practice
    stance = lib.stances[args.stance]
    block = type(block)(**{**block.__dict__, "stance": stance, "ends_with_question": args.question == "yes"})

    print(f"provider={args.provider}  model={config.LLM_MODEL}  effort={config.LLM_EFFORT or '(unset)'}  "
          f"prompt_version={PROMPT_VERSION}")
    if config.LLM_API_BASE:
        print(f"api_base={config.LLM_API_BASE}")
    print(f"stance={stance.name}  turn={args.turn}  ends_with_question={block.ends_with_question}\n")
    print("--- system prompt ---")
    print(build_system_prompt(block, args.turn))
    print("\n--- replies ---")

    turns = [Turn("user", "I think routines help most people because they remove a lot of small daily decisions.")]
    if args.turn == 2:
        turns += [
            Turn("assistant", "Removing small decisions does seem to free up attention for bigger "
                              "ones. Though some people find a fixed routine makes them less able to "
                              "adapt when the day goes sideways. Does that trade-off match your "
                              "experience?"),
            Turn("user", "Yes, that is fair, I have definitely had days where sticking to the plan "
                         "was clearly the wrong call for me."),
        ]

    client = LLMClient(args.provider)
    latencies, compliant, rewrites = [], 0, 0
    for i in range(args.repeat):
        try:
            result = await client.respond(block, answer_score_1=70, confidence_score_1=55,
                                          turns=list(turns), turn_number=args.turn)
        except LLMError as exc:
            # The vendor's own message is the useful part; the LiteLLM stack is not.
            print(f"FAILED: {str(exc).splitlines()[0][:300]}", file=sys.stderr)
            return 1
        latencies.append(result.latency_ms)
        compliant += not result.over_cap
        rewrites += result.rewrites
        print(f"[{i + 1}] {result.latency_ms} ms | {len(result.text.split())} words | "
              f"rewrites={result.rewrites} | over_cap={result.over_cap} | "
              f"ends_with_question={result.elicited} (wanted {result.ends_with_question}) | model={result.model}")
        if result.rewrites:
            print(f"    first draft ({len(result.raw_text.split())} words): {result.raw_text}")
        print(f"    {result.text}\n")

    if len(latencies) > 1:
        print(f"latency: min={min(latencies)}ms  max={max(latencies)}ms  mean={sum(latencies) // len(latencies)}ms")
    print(f"{compliant} of {args.repeat} replies complied (length and question rule); "
          f"{rewrites} rewrite round{'s' if rewrites != 1 else ''} in total.")
    print(f"\nThinking indicator switches to 'still thinking' after {config.THINKING_SLOW_AFTER_MS} ms.")
    return 0


def main() -> int:
    # Keep stdout and stderr in order when piped, so a failure prints after
    # the prompt it followed rather than before it.
    sys.stdout.reconfigure(line_buffering=True)
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stance", default="calibrated", choices=["aligning", "calibrated", "counterbalancing"])
    ap.add_argument("--provider", default="litellm", choices=["litellm", "fake"])
    ap.add_argument("--model", default=None, help=f"LiteLLM model id instead of {config.LLM_MODEL!r}")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--turn", type=int, default=1, choices=[1, 2])
    ap.add_argument("--question", default="yes", choices=["yes", "no"],
                    help="whether the reply must end on a question (the per-block flag)")
    args = ap.parse_args()
    if args.model:
        os.environ["MSM_LLM_MODEL"] = args.model
        config.LLM_MODEL = args.model
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
