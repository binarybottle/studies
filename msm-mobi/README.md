# MSM-MoBI — scenario conversations on Prolific

The online version of the MoBI-MSM scenario-response task: a Prolific
participant reads short imagined scenarios, rates a statement about each,
exchanges three messages with an AI assistant whose hidden conversational
stance is experimentally assigned, and rates the statement again. This
directory is the whole study: the application, its content, its
configuration template and this document. Hosting is described in the
[repository README](../README.md).

- [What the participant does](#what-the-participant-does)
- [Why a web app and not Retell](#why-a-web-app-and-not-retell)
- [How it fits together](#how-it-fits-together)
- [Assignment and counterbalancing](#assignment-and-counterbalancing)
- [The Prolific side](#the-prolific-side)
- [Configuration — `msm-mobi/.env`](#configuration--msm-mobienv)
- [Running locally](#running-locally)
- [Before opening the study](#before-opening-the-study)
- [Exporting data](#exporting-data)
- [Swapping in the real content](#swapping-in-the-real-content)
- [Capacity](#capacity)
- [Troubleshooting](#troubleshooting)

---

## What the participant does

```
Prolific  ->  /start  ->  /consent  ->  /task  ->  /finish  ->  Prolific
                          (agree)      practice + 12 blocks   (completion code)
```

Each block, practice included:

| # | Step | Data |
|---|---|---|
| 1 | Scenario and its Question, with 0/100 anchor labels | `scenario_shown_at` |
| 2 | Answer Score 1 (0–100) | `answer_score_1` |
| 3 | Confidence Score 1 (0–100) | `confidence_score_1` |
| 4 | "You rated that N out of 100. What made you give that score?" — ≥15 words | `user_text_1` |
| 5 | LLM reply 1 (≤75 words, ends by asking for a reply) | `llm_text_1`, latency, model |
| 6 | Reply — ≥15 words | `user_text_2` |
| 7 | LLM reply 2 | `llm_text_2` |
| 8 | Reply — ≥15 words | `user_text_3` |
| 9 | Answer Score 2 | `answer_score_2` |
| 10 | Confidence Score 2 | `confidence_score_2` |
| 11 | Activation score (0 calm – 100 activated) | `activation_score` |
| 12 | Continue gate (not after block 12) | `advanced_at` |

Every value is timestamped. The practice block always runs the Calibrated
stance and is flagged `is_practice`. Navigation is forward-only; the
transcript is cleared at each block boundary so no earlier block can be
re-read. Paste is blocked in the text fields.

**Resume.** Every submission is persisted before the response returns, and
the session's position is stored with it. A participant who refreshes, loses
their connection, or comes back the next day is put back at the exact step
they left, with the current block's transcript replayed — including a model
turn that was in flight, which simply runs again. A redeploy mid-session has
the same effect. There is no way to restart from the beginning.

## Why a web app and not Retell

The other study on this server (DASH) forwards every turn to a hosted Retell
agent. That was considered here and rejected for one reason: **each block's
model conversation must be independent**, and a Retell chat is a single
transcript that the model sees in full. A prompt asking the model to ignore
earlier blocks is a request, not a guarantee, and a stance manipulation that
can be contaminated by the previous block's stance is a confound you cannot
measure.

Here every model call is built from scratch: the block's Scenario, Question,
ratings and the turns exchanged so far in *this* block, and nothing else
(`app/llm.py`, `build_messages`). Isolation is structural. The other benefits
follow from owning the call: transcripts, prompts and the answering model land
in this study's own database rather than a vendor dashboard; numeric answers
come from a number field rather than a language-model extraction node; and
the model is a configuration value.

## How it fits together

| File | Role |
|---|---|
| `app/main.py` | The Prolific pages (`/start`, `/consent`, `/task`, `/finish`), the task API, admin exports |
| `app/session.py` | The per-block state machine; serializes itself for resume |
| `app/assign.py` | Counterbalanced assignment (Williams square, rolling scenario window) |
| `app/content.py` | Loads the content CSVs; resolves a participant's plan |
| `app/llm.py` | Stance system prompts, block-local context, the 75-word cap, LiteLLM and fake providers |
| `app/store.py` | SQLite: `participants`, `blocks`, `events`; CSV export |
| `app/prompts.py` | All participant-facing copy inside the task |
| `app/config.py` | Protocol constants and environment-driven settings |
| `app/static/` | The browser interface: no build step, no dependencies, no external requests |
| `content/` | The scenario bank, categories, stance prompts, practice scenario |
| `scripts/check_llm.py` | Sends one block-shaped request through the real model path and reports latency |
| `scripts/simulate.py` | Drives N simulated participants through the whole study at once |
| `scripts/import_retell_bank.py` | Produced the current `content/scenario_key.csv` from the Retell prototype |
| `tests/` | `pytest`: the full journey, resume, input rules, the stance-leak assertion, counterbalancing |

**The server owns the flow.** The browser is told only what to render next
and what single input to collect. It never receives the Stance, the
assignment, or anything about upcoming blocks;
`tests/test_flow.py::test_stance_never_reaches_the_client` asserts this.

**Every handler is asynchronous.** A model call is an awaited network wait,
so the single worker can hold hundreds of participants waiting on the model
at once. A per-participant lock stops a double-click or a refresh mid-turn
from submitting the same step twice; a repeated request for a model turn
that already ran returns the current state instead of running it again.

## Assignment and counterbalancing

There is no assignment file. At consent the participant is issued the next
**sequence number** (0, 1, 2, …, stored as `assignment_index`), and the
12 real blocks are a pure function of that number and the content bank:

- **Order.** The 12 Category × Stance conditions are laid out in a Williams
  Latin square. Across every run of 12 consecutive participants, each
  condition appears in each ordinal position exactly once and follows each
  other condition exactly once.
- **Scenarios.** Each category needs three scenarios per participant. They
  are taken from a window that advances through the category's bank by
  three per participant, so with 24 scenarios per category the whole bank is
  used before any scenario repeats (every 8 participants). Which of the
  three lands on which stance is shuffled by a generator seeded with the
  sequence number.

The resolved assignment is written to the participant row at consent, so a
later edit to the bank cannot change what someone already saw. Withdrawn
participants never receive a sequence number, so the cycle is not broken by
declines. Someone who consents and never starts *does* consume one; check
`participants.csv` for the gaps when the balance matters.

## The Prolific side

The study URL is `/start` with **no query string**:

```
https://msm-mobi.childmind.org/start
```

Prolific appends `?PROLIFIC_PID=…&STUDY_ID=…&SESSION_ID=…` itself. Do not
paste a URL with a `pid` in it, and do not point Prolific at `/consent`:
`/start` is the only route that registers a participant, and it is what
sends a returning participant to the right place.

Two completion codes, each needing the right action attached in Prolific.
Neither should be a rejection:

| `.env` variable | Reached when | Prolific action |
|---|---|---|
| `PROLIFIC_CC_COMPLETE` | block 12's activation score was submitted | approve automatically |
| `PROLIFIC_CC_NO_CONSENT` | the participant declined at the information sheet | custom screening, fixed reward |

A participant who stops part-way gets **no code**: `/finish` tells them to
return the study on Prolific, or to email for payment covering the part they
completed. Their data up to that point is in the database.

Set the Prolific study's estimated time from the pilot: twelve blocks with
two model turns each is roughly 30–45 minutes for a participant who writes
15-word replies. The instruction text says as much (`DURATION_TEXT`).

## Configuration — `msm-mobi/.env`

`.env` exists only on the droplet, is never committed, and is not touched by
`git pull`. Create it once:

```bash
cd ~/studies/msm-mobi
cp env.example .env && chmod 600 .env
openssl rand -hex 24    # ADMIN_TOKEN
nano .env
```

After editing: `docker compose up -d msm-mobi` — no build, but the container
has to be recreated to re-read the file.

| Variable | Notes |
|---|---|
| `ANTHROPIC_API_KEY` | The model vendor's credential. For another vendor, set that vendor's variable instead (`OPENAI_API_KEY`, …). |
| `MSM_LLM_MODEL` | LiteLLM model id, `vendor/model`. Default `anthropic/claude-opus-5`. Recorded per participant. |
| `MSM_LLM_PROVIDER` | `litellm` (real) or `fake` (canned replies, no key). |
| `MSM_LLM_MAX_CONCURRENCY` | Model calls in flight at once; 32 by default. Raise together with the vendor rate limit. |
| `MSM_LLM_EFFORT`, `MSM_LLM_FALLBACK_MODELS`, `MSM_LLM_API_BASE`, `MSM_LLM_API_KEY` | Optional; see `env.example`. |
| `PROLIFIC_CC_COMPLETE`, `PROLIFIC_CC_NO_CONSENT` | The two completion codes. |
| `ADMIN_TOKEN` | Guards `/admin/*`. Empty disables the exports. |
| `STUDY_NAME`, `ORG_NAME`, `CONTACT_EMAIL`, `DURATION_TEXT` | Shown to participants. |

**Do not put an inline comment after a value.**

Changing `MSM_LLM_MODEL` mid-study is allowed and visible: the model each
participant was assigned under is on their row, and the model that actually
answered each turn is on the block row (`llm_text_N_model`).

## Running locally

Python 3.11 or later.

```bash
cd msm-mobi
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest httpx
.venv/bin/python -m pytest
MSM_LLM_PROVIDER=fake PROLIFIC_CC_COMPLETE=X PROLIFIC_CC_NO_CONSENT=Y .venv/bin/python -m app
```

Then open `http://127.0.0.1:8000/start?PROLIFIC_PID=test1`. The database
lands in `msm-mobi/data/study.db`; delete it to start over. To rehearse the
thinking indicator's slow state, add `MSM_FAKE_LLM_DELAY_S=9`.

Copy `env.example` to `.env` with a real key and drop `MSM_LLM_PROVIDER=fake`
to talk to the model.

## Before opening the study

1. **Confirm the model path** from inside the container, both turns:

   ```bash
   docker compose exec msm-mobi python scripts/check_llm.py --repeat 5
   docker compose exec msm-mobi python scripts/check_llm.py --turn 2 --repeat 5
   ```

   Read the replies. Check `elicited=True` on every one (a reply that does
   not end on a question leaves the participant facing an unlabelled box)
   and that the latency spread sits clear of the 7 s threshold at which the
   indicator changes text.

2. **Walk the participant path** yourself:
   `https://msm-mobi.childmind.org/start?PROLIFIC_PID=walkthrough-1`. Refresh
   in the middle of a block and confirm you land on the same step. Then
   exclude that ID from the export.

3. **Check the exports work** (below) before there is anything in them.

4. **Set the Prolific completion codes** in `.env` and the matching actions
   in Prolific.

## Exporting data

Everything is in this study's database; nothing has to be joined against a
vendor. From your laptop, on the allow-listed IP:

```bash
TOKEN=$(ssh arno@167.71.248.46 \
    'cd ~/studies && docker compose exec -T msm-mobi printenv ADMIN_TOKEN' \
    | /usr/bin/tr -d ' \t\r\n')
curl -s "https://msm-mobi.childmind.org/admin/blocks.csv?token=$TOKEN" \
    -o ~/Desktop/msm-blocks-$(date +%F).csv
curl -s "https://msm-mobi.childmind.org/admin/participants.csv?token=$TOKEN" \
    -o ~/Desktop/msm-participants-$(date +%F).csv
```

`head -1` each file: the first line should be a column header. `{"detail":"Not
found"}` means a wrong or empty token **or** an IP that is not allow-listed
in `Caddyfile`; the endpoint deliberately does not say which.

| File | Contents |
|---|---|
| `blocks.csv` | One row per block per participant: category, scenario, stance, every score, every text, both model replies (as shown and as returned), latency, the answering model, timestamps. `is_practice` = 1 for the practice block. |
| `participants.csv` | One row per Prolific submission: stage, `assignment_index`, model, timestamps. |
| `events/<pid>.jsonl` | The full event log for one participant — steps, model calls, focus loss, blocked pastes, rejected submissions — for investigating a report. |

Join to Prolific's own export on `pid` = `Participant id` for demographics
and submission status. The assembled table is the most sensitive artifact the
study produces; keep it off shared drives and out of the repository.

The database itself (`/data/study.db` in the `msm_mobi_data` volume) is
backed up nightly by `backup.sh` alongside DASH's.

## Swapping in the real content

`content/scenario_key.csv` currently holds the 96 vignettes from the Retell
prototype (24 per category), with the Question phrased as agreement with the
prototype's appraisal statement. Replace it, keeping the columns:

```
scenario_label, category_label, scenario_text, question_text, scale_low_label, scale_high_label
```

`category_label` must match `content/category_key.csv`, and each category
needs at least three scenarios; the app refuses to start otherwise. The
stance prompts are `content/stance_key.csv` (currently the prototype's
Aligning / Calibrated / Counterbalancing definitions; the invariant framing
that controls length and the closing question is `RESPONSE_FRAMING` in
`app/llm.py`). The practice block is `content/practice_scenario.csv`.

Content is copied into the image, so a change needs
`docker compose up -d --build msm-mobi`. Participants already in progress
keep the plan they were issued at consent.

## Capacity

The deployment is one asynchronous worker and SQLite. A participant is not a
thread: while they wait on the model the process holds an open socket and
nothing else, so concurrency is bounded by the model vendor's rate limit
(`MSM_LLM_MAX_CONCURRENCY` queues turns beyond it) and by the droplet's
memory, not by the app. Measured locally with `scripts/simulate.py` against
the fake model at 2 s per turn, 300 participants running the full study at
once with 4 s of think time per step (a fast human): all 300 completed,
submissions answered in 3 ms median / 6 ms p95, and model turns took exactly
the model's 2 s with no queueing. With think time removed entirely — every
participant submitting the instant the server answers, ~300 requests per
second — latency climbs into seconds, which is CPU saturation of one Python
process and not a shape real participants can produce.

The droplet's 1 GB is the tighter constraint. LiteLLM alone costs the
container ~200 MB resident, and the DASH container and Caddy share the box.
Upgrade to 2 GB before releasing hundreds of Prolific slots at once.

## Troubleshooting

**Container restarts repeatedly.** `docker compose logs msm-mobi`. A
`ContentError` means a content CSV is malformed or a category is short of
scenarios; a `KeyError` means a missing environment variable.

**"The model did not return a response."** The vendor call failed after two
retries. The participant sees a retry button and their place is kept. Check
the key, the vendor's status page, and `events/<pid>.jsonl` for the error
text (`llm_request_failed`).

**A participant reports being stuck.** Their event log has every step with
timestamps. Their stage in `participants.csv` says where they are; `in_task`
with no recent events means they left. Sending them the study link from
Prolific again resumes them.

**Replies do not end on a question.** `llm_text_N_elicited` = 0 in
`blocks.csv`. Run `scripts/check_llm.py --repeat 10`; if it is frequent,
the model or the framing needs attention before more data is collected.
