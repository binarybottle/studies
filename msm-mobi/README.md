# MSM-MoBI — scenario conversations on Prolific

The online version of the MoBI-MSM scenario-response task: a Prolific
participant reads short imagined scenarios, rates a statement about each,
exchanges three messages with an AI assistant whose hidden conversational
stance is experimentally assigned, and rates the statement again. This
directory is the whole study: the application, its content, its
configuration template and this document. Hosting is described in the
[repository README](../README.md).

- [What the participant does](#what-the-participant-does)
- [How it fits together](#how-it-fits-together)
- [Assignment and counterbalancing](#assignment-and-counterbalancing)
- [The Prolific side](#the-prolific-side)
- [Configuration — `msm-mobi/.env`](#configuration--msm-mobienv)
- [Running locally](#running-locally)
- [Before opening the study](#before-opening-the-study)
- [Downloading and assessing the data](#downloading-and-assessing-the-data)
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
| 0 | Blocks 1 and 7 only: an attention check ("enter the number 37") in the numeric box | `attention_checks` table |
| 1 | Scenario and its Question, with 0/100 anchor labels | `scenario_shown_at` |
| 2 | Answer Score 1 (0–100) | `answer_score_1` |
| 3 | Confidence Score 1 (0–100) | `confidence_score_1` |
| 4 | "You rated that N out of 100. What made you give that score?" — any length, not empty | `user_text_1` |
| 5 | LLM reply 1 (≤75 words; ends on a question or not, per the block's flag) | `llm_text_1`, rewrites, latency, model |
| 6 | Reply — any length, not empty | `user_text_2` |
| 7 | LLM reply 2 (same flag; must engage what the participant added; no "moving on" cues) | `llm_text_2` |
| 8 | Final reply — any length, not empty | `user_text_3` |
| 9 | Answer Score 2 | `answer_score_2` |
| 10 | Confidence Score 2 | `confidence_score_2` |
| 11 | Activation score (0 calm – 100 activated) | `activation_score` |
| 12 | Continue gate (not after block 12) | `advanced_at` |

Every value is timestamped. The practice block always runs the Calibrated
stance and is flagged `is_practice`. Free-text replies have no word minimum:
the lab protocol's 15-word floor produced padded, repeated sentences in the
first online pilot rather than engagement, and participants said so.
Low-effort sessions are flagged afterwards instead (`quality.csv`), not
blocked at entry. Navigation is forward-only; the
transcript is cleared at each block boundary so no earlier block can be
re-read. Paste is blocked in the text fields.

**Reply length and the question ending are enforced by a loop, not by
cutting.** After every model call the code checks two things: at most 75
words, and ends on a question exactly when the block's flag says so. A
reply that misses either is handed back to the model with the problem named
("your reply was 96 words; the limit is 75") and a request to rewrite it
complete, summarizing rather than cutting; the code checks again and
repeats. Each round is one more model call (~2.5 s). After `MAX_REWRITES`
rounds (5) the shortest attempt is delivered as is and the row flags it
(`llm_text_N_over_cap`). Every block row records the first draft, the
number of rounds, and whether the delivered reply ended on a question.

**Resume.** Every submission is persisted before the response returns, and
the session's position is stored with it. A participant who refreshes, loses
their connection, or comes back the next day is put back at the exact step
they left, with the current block's transcript replayed — including a model
turn that was in flight, which simply runs again. A redeploy mid-session has
the same effect. There is no way to restart from the beginning.

## How it fits together

| File | Role |
|---|---|
| `app/main.py` | The Prolific pages (`/start`, `/consent`, `/task`, `/finish`), the task API, admin exports |
| `app/session.py` | The per-block state machine; serializes itself for resume |
| `app/assign.py` | Counterbalanced assignment (Williams square, rolling scenario window, question-ending flags) |
| `app/content.py` | Loads the content CSVs; resolves a participant's plan |
| `app/llm.py` | Stance system prompts, block-local context, the rewrite loop for length and question ending, LiteLLM and fake providers |
| `app/store.py` | SQLite: `participants`, `blocks`, `attention_checks`, `events`; the CSV exports |
| `app/prompts.py` | All participant-facing copy inside the task |
| `app/config.py` | Protocol constants and environment-driven settings |
| `app/static/` | The browser interface: no build step, no dependencies, no external requests |
| `content/` | The scenario bank, categories, stance prompts, practice scenario |
| `scripts/check_llm.py` | Sends one block-shaped request through the real model path and reports latency |
| `scripts/simulate.py` | Drives N simulated participants through the whole study at once |
| `scripts/download.sh` | Fetches the three exports from the server into a dated folder on your laptop |
| `scripts/screen.py` | Applies the low-effort criteria to the exports (or the database) and prints flagged participants with their replies |
| `scripts/import_retell_bank.py` | Produced the current `content/scenario_key.csv` from the Retell prototype |
| `tests/` | `pytest`: the full journey, resume, input rules, attention checks, the stance-leak assertion, counterbalancing, the exports |

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
- **Question ending.** Each stance has four blocks (one per category); in
  two of them the chatbot's replies end on a question and in two they do
  not. Which two categories is chosen from the six possible pairs by the
  sequence number, offset per stance, so over every six consecutive
  participants each category is the question-ending one in each stance
  equally often. The practice block always ends on a question. The flag is
  `ends_with_question` on the block row; the observed outcome per turn is
  `llm_text_N_elicited`.

The resolved assignment is written to the participant row at consent, so a
later edit to the bank cannot change what someone already saw. Withdrawn
participants never receive a sequence number, so the cycle is not broken by
declines. Someone who consents and never starts *does* consume one; check
`participants.csv` for the gaps when the balance matters.

## The Prolific side

The study URL is `/start` with **no query string**:

```
https://msm-mobi.study.childmind.org/start
```

Prolific appends `?PROLIFIC_PID=…&STUDY_ID=…&SESSION_ID=…` itself. Do not
paste a URL with a `pid` in it, and do not point Prolific at `/consent`:
`/start` is the only route that registers a participant, and it is what
sends a returning participant to the right place.

Three completion codes, each needing the right action attached in Prolific.
None should be a rejection:

| `.env` variable | Reached when | Prolific action |
|---|---|---|
| `PROLIFIC_CC_COMPLETE` | block 12's activation score was submitted | approve automatically |
| `PROLIFIC_CC_ATTENTION` | finished, but both attention checks failed (optional; see below) | manually review |
| `PROLIFIC_CC_NO_CONSENT` | the participant declined at the information sheet | custom screening, fixed reward |

A participant who stops part-way gets **no code**: `/finish` tells them to
return the study on Prolific, or to email for payment covering the part they
completed. Their data up to that point is in the database.

Set the Prolific study's estimated time from the pilot: the first three
completed sessions took 33–60 minutes, so the consent page says 45 to 60
(`DURATION_TEXT` in `.env`). Revise both together if the batches say
otherwise.

### Attention checks

Two instructed responses, in the same numeric box as every rating: "for
this box only, please enter the number 37" at the top of block 1 (a few
minutes in, right after the practice round) and "…72" at the top of block 7
(halfway). They are defined in `ATTENTION_CHECKS` in `app/config.py`, never
block progress, and are recorded per participant (`attention_seen`,
`attention_failed` in `participants.csv`; `attention_failed` in
`quality.csv`; an `attention_check` event with the answer).

A finished session that failed **both** returns to Prolific with
`PROLIFIC_CC_ATTENTION` when that is set, so the submission can be held for
review; attach "manually review" to that code in Prolific, never a rejection.
One failure never changes the code. With the variable unset, every finished
session gets the completion code and the failures are only in the exports.
The consent page tells participants the checks exist.

### Screening for low effort

Beyond the two checks, the design is flag afterwards, not block at entry.
How to download the data and run that screening is in
[Downloading and assessing the data](#downloading-and-assessing-the-data).
Prolific-side filters (approval rate ≥ 98%, a minimum number of previous
submissions, fluent English) remove most low-effort participants before
they arrive.

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
| `PROLIFIC_CC_COMPLETE`, `PROLIFIC_CC_NO_CONSENT` | The completion codes, from the Prolific study's completion-code section. |
| `PROLIFIC_CC_ATTENTION` | Optional third code for a finished session that failed both attention checks; attach "manually review" in Prolific. |
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

1. **Confirm the model path** from inside the container, both turns and
   both question flags:

   ```bash
   docker compose exec msm-mobi python scripts/check_llm.py --repeat 5
   docker compose exec msm-mobi python scripts/check_llm.py --turn 2 --repeat 5
   docker compose exec msm-mobi python scripts/check_llm.py --question no --repeat 5
   docker compose exec msm-mobi python scripts/check_llm.py --question no --turn 2 --repeat 5
   ```

   Read the replies. Each line reports how many rewrite rounds it took and
   whether the delivered reply ended on a question against what was wanted;
   a rewrite adds ~2.5 s, so a model that needs one on most replies will
   cross the 7 s threshold at which the thinking indicator changes text.
   The output names the `prompt_version` in force; that value is written to
   every block row.

2. **Walk the participant path** yourself:
   `https://msm-mobi.study.childmind.org/start?PROLIFIC_PID=walkthrough-1`. Refresh
   in the middle of a block and confirm you land on the same step. Then
   exclude that ID from the export.

3. **Check the exports work** (below) before there is anything in them.

4. **Set the Prolific completion codes** in `.env` and the matching actions
   in Prolific; see [The Prolific side](#the-prolific-side) for which action
   goes with which.

5. **Deploy between batches, not during one.** A rebuild keeps every session
   resumable, but a participant mid-session would see new prompt wording
   from their next turn.

## Downloading and assessing the data

Everything is in this study's own database on the droplet; nothing has to
be joined against a vendor. The server exports it as CSV files behind an
admin token and an IP allow-list, and a script screens those files for
low-effort sessions. The routine after each batch is: download, screen,
read the flagged transcripts, decide in Prolific.

### 1. What the exports contain

| File | Contents |
|---|---|
| `blocks.csv` | One row per block per participant: category, scenario, stance, `ends_with_question` (the flag), every score, every text the participant typed, both model replies (as shown, and the first draft as `_raw`), rewrite rounds and `_over_cap`, `_elicited` (did it end on a question), latency, the answering model, `prompt_version`, timestamps. `is_practice` = 1 for the practice block. This is the analysis file. |
| `participants.csv` | One row per Prolific submission: `stage` (`consented`, `in_task`, `complete`, `withdrew`), `assignment_index`, `attention_seen`, `attention_failed`, model, timestamps. |
| `quality.csv` | One row per participant with the signals of a low-effort session, computed from the two files above and the event log. Columns are explained in step 3. |
| `events/<pid>.jsonl` | The full event log for one participant: steps, model calls, focus loss, blocked pastes, rejected submissions. For investigating a report; not part of the routine. |

### 2. Download

**Requirements:** ssh access to the droplet, and an IP address on the
`/admin/*` allow-list in the repository's `Caddyfile` (`curl ifconfig.me`
tells you yours; a change there is a Caddy recreate, see the repository
README). Both are needed because the export is the study's most sensitive
artifact.

From your laptop, in a checkout of this repository:

```bash
msm-mobi/scripts/download.sh
```

That reads the admin token from the running container, fetches the three
CSVs into `~/Desktop/msm-mobi/<today's date>/`, checks that each one is a
CSV rather than an error page, and prints the row counts. Give it a
directory to put the dated folder somewhere else:

```bash
msm-mobi/scripts/download.sh ~/data/msm-mobi
```

The same by hand, if the script is not available:

```bash
TOKEN=$(ssh arno@167.71.248.46 \
    'cd ~/studies && docker compose exec -T msm-mobi printenv ADMIN_TOKEN' \
    | /usr/bin/tr -d ' \t\r\n')
for f in blocks participants quality; do
  curl -s "https://msm-mobi.study.childmind.org/admin/$f.csv?token=$TOKEN" -o ~/Desktop/msm-$f.csv
done
head -1 ~/Desktop/msm-quality.csv      # must be a column header
```

`{"detail":"Not found"}` in a file means a wrong or empty token **or** an
IP that is not on the allow-list; the endpoint deliberately does not say
which. Check `${#TOKEN}` is about 32 first, then your IP against
`Caddyfile`.

One participant's event log, when a report needs investigating:

```bash
curl -s "https://msm-mobi.study.childmind.org/admin/events/<PROLIFIC_PID>.jsonl?token=$TOKEN"
```

### 3. Screen for low-effort sessions

`quality.csv` carries these per-participant signals:

| Column | Suspicious when | What it usually means |
|---|---|---|
| `attention_failed` | 2 | did not read either instruction; the strongest single signal |
| `min_read_seconds` | under ~5 s | rated a scenario without reading it |
| `distinct_reply_ratio` | under ~0.7 | the same sentence pasted into several boxes |
| `median_reply_words` | 1–3 | "ok" / "yes" throughout |
| `rating_sd` | 0 or near it | straight-lining the first rating |
| `unchanged_rating_share` | 1.0 *and* short replies | never engaged; on its own it is a legitimate result |
| `focus_lost_seconds` | many minutes | left the tab; not disqualifying by itself |
| `paste_blocked` | > 0 | tried to paste replies in; read their text |

`scripts/screen.py` applies those criteria and prints who to look at and
why. It flags a participant who failed both attention checks, or who trips
two or more of the other signals; anything weaker is listed as a note.
Plain Python 3, no dependencies.

**Locally, on the downloaded files** (the normal way). `--show` prints each
flagged participant's own replies, block by block, which is what any
decision has to rest on:

```bash
python3 msm-mobi/scripts/screen.py ~/Desktop/msm-mobi/2026-09-27/quality.csv \
    --blocks ~/Desktop/msm-mobi/2026-09-27/blocks.csv --show
```

**Remotely, with nothing downloaded.** Either pipe the export from the
server:

```bash
curl -s "https://msm-mobi.study.childmind.org/admin/quality.csv?token=$TOKEN" \
    | python3 msm-mobi/scripts/screen.py -
```

or run it on the droplet straight from the database, transcripts included:

```bash
ssh arno@167.71.248.46
cd ~/studies && docker compose exec msm-mobi python scripts/screen.py --db /data/study.db --show
```

Options: `--all` lists every participant with their signals, not only the
flagged; `--keep-test` includes `SIM-*` and `walkthrough-*` IDs, which are
skipped otherwise; the thresholds are flags (`--help`). Exit code 1 means
something was flagged. Output looks like:

```
23 participants: 19 complete, 3 in_task, 1 withdrew

FLAG 5f3a9c…                   complete   12 blocks   38.5 min
      ! failed both attention checks
      ! reused replies (distinct ratio 0.31)
      · tab hidden 14 min
    block  1  know_understand  aligning         rating  55 ->  55
      you 1: I think this depends on the person...
      ...

1 flagged of 23. A flag means read the transcript, not reject.
```

### 4. Read, then decide

A flag is a reason to read, not a verdict: a short reply can be a
considered one, and a participant can fail one check in an hour without
being inattentive. Read the printed replies. Under Prolific's rules a
submission can be rejected only for demonstrable non-engagement, and the
transcript is what justifies it; failing both attention checks is the
clearest case. The thresholds above are starting points to tune on the
first batches, not rules.

Sessions that never finished (`stage` = `in_task` or `consented`) have no
completion code and no submission to approve; Prolific times them out.
Their data up to the point they stopped is in `blocks.csv`.

### 5. Joining with Prolific

Prolific's own export (the study → Data → export) joins to any of these
files on `pid` = `Participant id` for demographics, submission status and
Prolific's own time-taken. Verify that column name against the actual file
before trusting a join. The assembled table is the most sensitive artifact
the study produces; keep it off shared drives and out of the repository.

### Backups

The database itself (`/data/study.db` in the `msm_mobi_data` volume) is
backed up nightly by `backup.sh` alongside DASH's. That is disaster
recovery; the exports above are how data leaves the server.

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
that controls length and form, the question rule for each flag, the
per-turn guidance and the rewrite request are `RESPONSE_FRAMING`,
`QUESTION_RULES`, `TURN_GUIDANCE` and `REWRITE_INSTRUCTION` in
`app/llm.py`). The practice block is `content/practice_scenario.csv`.

**Bump `PROMPT_VERSION` in `app/llm.py` whenever any of those change.** It
is recorded on every block row (`prompt_version` in `blocks.csv`) and in the
`session_started` event, so sessions run under different wording can be told
apart; its history is in the comment above it.

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

The droplet's memory is the tighter constraint: LiteLLM alone costs the
container ~200 MB resident, and the DASH container and Caddy share the box.
It was upgraded to 2 GB / 1 vCPU before the first pilot, which leaves
headroom for both studies at hundreds of concurrent participants; `free -h`
on the droplet says how much is left.

This container is capped at 768 MB by `mem_limit` in `compose.yml`, so a leak
here cannot take DASH down with it — and, equally, this study dies rather
than degrades if it ever reaches that ceiling. The cap is a ceiling, not a
reservation: it costs nothing while unused. `../capacity.sh` on the droplet
reports this container against it; raise the cap before a larger batch if a
live one sits above about half. The reasoning is in [Isolation between
studies](../README.md#isolation-between-studies).

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

**Telling starts, completions and partial sessions apart.** In
`participants.csv`, `stage` is `consented` for someone who agreed but never
opened the task, `in_task` for a partial session, `complete` for a finished
one, `withdrew` for a decline; `started_at` and `completed_at` give the
times. `blocks.csv` shows how far a partial session got: the last row with
any value filled in. Timing within a block comes from the per-step
timestamps there (`scenario_shown_at` to `answer_score_1_at` is reading;
`llm_text_N_requested_at` to `_received_at` is model latency; the gap from a
reply's `_received_at` to the next `user_text_N_at` is reading plus typing).
