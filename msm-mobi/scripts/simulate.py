#!/usr/bin/env python3
"""Drive N simulated participants through the whole study at once.

A load check for the deployment shape (one asynchronous worker, SQLite): it
reports how long submissions and model turns took under concurrency. Point it
at a server running with MSM_LLM_PROVIDER=fake to test the app alone, or at a
real model to test the vendor's rate limit -- that costs real money.

    python scripts/simulate.py --base http://127.0.0.1:8000 --participants 50 --think 5

Each simulated participant gets its own Prolific-style ID prefixed SIM-, so
they are easy to exclude from an export.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import statistics
import time
import uuid

import httpx

WORDS = "I think this depends a great deal on the specific person and their particular circumstances here."


async def participant(base: str, client: httpx.AsyncClient, timings: dict[str, list[float]], think: float) -> None:
    pid = f"SIM-{uuid.uuid4().hex[:10]}"
    # Stagger arrivals over the first think interval, as real participants do.
    await asyncio.sleep(random.uniform(0, think))
    r = await client.get(f"{base}/start", params={"PROLIFIC_PID": pid})
    assert r.status_code == 303, r.text
    r = await client.post(f"{base}/consent", params={"pid": pid}, data={"decision": "consent"})
    assert r.status_code == 303, r.text
    r = await client.post(f"{base}/api/session", json={"pid": pid})
    r.raise_for_status()
    view = r.json()
    token = view["session"]
    while not view.get("done"):
        if think and not view.get("awaiting_llm"):
            await asyncio.sleep(random.uniform(0.5 * think, 1.5 * think))
        if view.get("awaiting_llm"):
            t0 = time.perf_counter()
            r = await client.post(f"{base}/api/session/{token}/llm")
            timings["llm"].append(time.perf_counter() - t0)
        else:
            spec = view["input"]
            value = 55 if spec["type"] == "numeric" else (WORDS if spec["type"] == "text" else True)
            t0 = time.perf_counter()
            r = await client.post(f"{base}/api/session/{token}/submit", json={"step": spec["step"], "value": value})
            timings["submit"].append(time.perf_counter() - t0)
        r.raise_for_status()
        view = r.json()
    r = await client.get(f"{base}/finish", params={"pid": pid})
    assert r.status_code == 303 and "cc=" in r.headers["location"], r.text


async def main_async(args: argparse.Namespace) -> int:
    timings: dict[str, list[float]] = {"submit": [], "llm": []}
    t0 = time.perf_counter()
    # One connection per participant, or the client's own pool would queue
    # behind the slow model turns and the numbers would measure the script.
    limits = httpx.Limits(max_connections=args.participants + 10, max_keepalive_connections=args.participants + 10)
    async with httpx.AsyncClient(timeout=120, follow_redirects=False, limits=limits) as client:
        results = await asyncio.gather(
            *(participant(args.base, client, timings, args.think) for _ in range(args.participants)),
            return_exceptions=True,
        )
    elapsed = time.perf_counter() - t0
    failures = [r for r in results if isinstance(r, Exception)]
    print(f"{args.participants} participants in {elapsed:.1f}s, {len(failures)} failed")
    for f in failures[:5]:
        print(f"  {type(f).__name__}: {f}")
    for name, values in timings.items():
        if values:
            values.sort()
            p95 = values[int(len(values) * 0.95) - 1]
            print(f"{name:7s} n={len(values):5d}  median={statistics.median(values) * 1000:6.0f}ms  "
                  f"p95={p95 * 1000:6.0f}ms  max={values[-1] * 1000:6.0f}ms")
    return 1 if failures else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--participants", type=int, default=20)
    ap.add_argument("--think", type=float, default=0.0,
                    help="Mean seconds a simulated participant spends on each step. 0 hammers the "
                         "server as fast as it answers; real people take 10-60 s.")
    return asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
