# DASH — text-message screener pilot

What this study is, what a participant goes through, how it is wired to
Prolific and Retell, and the settings and data that belong to this study
alone.

Everything shared with any other study on the same server — creating the
droplet, TLS, deploying, backups, restoring — is in the
[repository README](../README.md). This document assumes the site is already
running.

`STATUS.md` in this directory is a different kind of document: a
point-in-time handoff briefing, written to be pasted to someone who cannot
see the repository. It goes stale on purpose. This file is the durable one.

---

## What this study is

The Child Mind Institute MATTER Lab is piloting an automated text-message
interviewer. Participants are recruited on Prolific, given a written persona
describing a fictional parent and child, and answer a standardized mental
health screening questionnaire **in character**. Nobody is asked about their
own child or their own mental health. It is a test of whether the software
works, not a research study; a research study may follow and has not yet been
submitted for Institutional Review Board review.

| Thing | Value |
|---|---|
| Study site | `https://study.arnoklein.info` |
| Prolific study URL | `https://study.arnoklein.info/start` |
| Study SMS number (DID) | +1 (507) 431-7807 |
| Opt-in page | `https://matter.childmind.org/studies/dash/opt-in/` |
| SMS terms / privacy notice | `matter.childmind.org/sms-terms/`, `/sms-privacy/` |
| SMS / agent provider | Retell |
| Study contact (participants) | olivia.fitzpatrick@childmind.org |
| Policy contact (legal) | lindsay.alexander@childmind.org |

The two policy pages and the opt-in page live in the **matter-website**
repository (Jekyll on GitHub Pages), not here. The study site redirects
`/sms-terms` and `/sms-privacy` to them rather than serving its own copies,
so there is one canonical wording. Note that matter.childmind.org sits behind
a Cloudflare bot challenge that returns 403 to anything that is not a real
browser — those pages cannot be checked with `curl`.

---

## The participant journey

1. Prolific sends the participant to `/start` with their identifiers.
2. `/consent` shows the information sheet. Agreeing records consent to take
   part; it sends no messages.
3. `/begin` offers the interview. What appears here depends on
   `SMS_ENABLED` — see [Two channels](#two-channels) below.
4. **By text:** the opt-in page on matter.childmind.org collects a mobile
   number and an **unchecked** checkbox carrying the SMS disclosure.
   Submitting posts to `POST /api/opt-in` on this site, which records the
   consent and asks Retell to send a confirmation text. The participant then
   texts their five-character code to the study number. Retell's function
   node calls `/api/verify-code`, which binds the conversation to the
   Prolific submission — the only point at which that link can be made.
5. **In the browser:** `/chat` runs the same Retell agent over
   `/api/chat/start` and `/api/chat/send`. No phone number is involved and
   the code is bound at chat creation.
6. At the end, a function node calls `/api/complete`, which releases the
   Prolific completion code. `/begin` polls `/status` every five seconds, so
   a participant who did the interview by text sees the return link appear on
   the page they left open.

Phone numbers are hashed on arrival and never stored in plaintext. The
database on the droplet is the only key connecting a transcript to a Prolific
submission.

Three separate things are easy to conflate, and keeping them apart is
load-bearing:

- **Consent to take part** is the agreement on `/consent`.
- **The SMS opt-in** is the checkbox on the opt-in page. It is not the same
  act, and separating the two is what fixed the first A2P campaign rejection.
- **The five-character code** is neither. It identifies a session so a
  conversation can be matched to a Prolific submission for payment. The
  campaign application says so explicitly, because a reviewer could otherwise
  read it as a second consent gate.

### Two channels

Both channels run the same interview. `SMS_ENABLED` decides what `/begin`
offers:

| `SMS_ENABLED` | `/begin` shows |
|---|---|
| unset or `0` | the browser interview only |
| `1` | both, with the device's likely channel first — a phone leads with SMS, a desktop leads with the browser. Both are always offered. |

It ships unset because carriers filter outbound A2P messages until the
campaign is approved, so the text channel cannot deliver anything yet. On the
day approval lands, set it to `1` and restart the container; nothing else
changes.

**The browser channel is a compliance requirement, not just a convenience.**
The A2P campaign filing tells TCR that consenting to receive text messages is
not a condition of taking part or of being paid, and that claim is true only
because `/chat` runs the same interview. The campaign was rejected on 26
August 2026 for the opposite reading. Do not remove the browser channel, and
do not reword the site to describe the study as text-message-only — see
[Configuration](#configuration--dashenv) and `optin/A2P_submission.md`.

The `channel` column in the export records which one each participant
actually used.

---

## The Prolific side

In Prolific, the study URL is `/start` with **no query string**:

```
https://study.arnoklein.info/start
```

Prolific appends `?PROLIFIC_PID=…&STUDY_ID=…&SESSION_ID=…` itself. Do not
paste a URL with a `pid` already in it, and do not point Prolific at
`/consent`: `/start` is the only route that registers a participant, and it
is what decides whether a returning participant resumes at consent, at the
code, or at their completion link. A participant who reaches `/start`
without Prolific's identifiers — a bookmark, or a link passed between
participants — gets a page telling them to reopen the study from Prolific.

Three completion codes exist, and each needs the right action attached in
Prolific. None of them should be a rejection:

| `.env` variable | Reached when |
|---|---|
| `PROLIFIC_CC_COMPLETE` | the interview finished, under the attention-failure threshold |
| `PROLIFIC_CC_ATTENTION` | the interview finished, at or over the threshold |
| `PROLIFIC_CC_NO_CONSENT` | the participant declined at the information sheet |

Non-consent gets the screen-out code because Prolific forbids rejecting a
participant who declined to take part. A single failed attention check never
reaches `PROLIFIC_CC_ATTENTION` on its own — see `ATTENTION_FAILURE_THRESHOLD`
and the docstring on `completion_code_for` in [study_site.py](study_site.py).

A participant whose chat closed without reaching the end — they texted STOP,
or stopped replying until the silence timer expired — lands at stage
`timed_out` and deliberately gets **no code**. The consent copy tells them to
email for payment covering the part they completed, and `/finish` sends them
there.

---

## Configuration — `dash/.env`

`.env` exists only on the droplet, is never committed, and is not touched by
`git pull`. Create it once:

```bash
cd ~/studies/dash
cp env.example .env && chmod 600 .env
openssl rand -hex 16    # PHONE_HASH_SALT
openssl rand -hex 24    # ADMIN_TOKEN
nano .env
```

After editing it: `docker compose up -d dash` — no build, but the container
has to be recreated to re-read the file.

| Variable | Notes |
|---|---|
| `STUDY_SMS_NUMBER` | The DID participants text. Also rendered on the site. |
| `ORG_NAME`, `CONTACT_EMAIL` | Shown to participants; `CONTACT_EMAIL` is the study contact, not the policy contact. |
| `PHONE_HASH_SALT` | See the warning below. |
| `ADMIN_TOKEN` | Guards `/admin/linkage.csv`. |
| `PROLIFIC_CC_*` | The three completion codes above. May stay as placeholders until the Prolific study exists. |
| `RETELL_API_KEY` | One key covers everything: the opt-in confirmation message and the browser chat. |
| `RETELL_AGENT_ID` | Only to point this container at a different agent; the study's own is the default in `study_site.py`. |
| `SMS_ENABLED` | `1` once the A2P campaign is approved. See [Two channels](#two-channels). |
| `SMS_SEND_URL`, `SMS_SEND_TOKEN` | Only to override the defaults — the endpoint already points at Retell and the token falls back to `RETELL_API_KEY`. Until a key is set, `/api/opt-in` records each consent and reports the confirmation as `unconfigured` rather than claiming it was sent. |
| `OPTIN_PAGE_URL`, `OPTIN_PAGE_ORIGIN` | Where the opt-in page is published. The origin is the only one allowed to POST to `/api/opt-in` from a browser; if the page moves and this does not, the submission is blocked by CORS. |

**`PHONE_HASH_SALT` must be set to its final value before any participant
texts you.** Rotating it later makes hashes from before and after mutually
incomparable, which silently breaks repeat-handset detection. This is also
the reason deployment pulls rather than copies files up: overwriting the
droplet's `.env` with the blank template destroys the salt with no way to
recover it.

**Do not put an inline comment after a value.** Compose strips them
correctly; every other way of reading the file does not, which is how a
73-character `ADMIN_TOKEN` once broke the export.

---

## Walking the participant path

After a deploy, with a fresh Prolific ID:

```
https://study.arnoklein.info/start?PROLIFIC_PID=test123456789012345678
```

Information sheet → consent → a five-character code, and either the browser
interview or the choice of both channels depending on `SMS_ENABLED`.

---

## Exporting data

`backup.sh` and the CSV export are unrelated operations, and it is easy to
reach for the wrong one:

| | `backup.sh` | `/admin/linkage.csv` |
|---|---|---|
| Produces | binary SQLite file | CSV text |
| Purpose | disaster recovery | analysis |
| Where | `~/studies/backups/` on the droplet | downloaded to your laptop |
| When | nightly from cron, unattended | whenever you want current data |
| Readable as a table | no | yes |

Backups are a droplet-level concern and are documented in the
[repository README](../README.md#backups). You do not need to run one before
exporting: the endpoint reads the live database, so the CSV is current as of
the moment you call it.

### Pulling the linkage table

From your laptop, on the allow-listed IP:

```bash
TOKEN=$(ssh arno@167.71.248.46 \
    'cd ~/studies && docker compose exec -T dash printenv ADMIN_TOKEN' \
    | /usr/bin/tr -d ' \t\r\n')
curl -s "https://study.arnoklein.info/admin/linkage.csv?token=$TOKEN" \
    -o ~/Desktop/linkage-$(date +%F).csv
```

`167.71.248.46` is the droplet; `dig +short study.arnoklein.info` confirms
it if that ever changes. The CSV lands wherever `-o` points — an absolute
path, because a relative one lands in whatever directory the terminal
happens to be in, and this file should not end up inside the repository.

Three details in that command are each load-bearing, and all three have
already gone wrong once:

- **The token is read from the container, not from `.env`.** Parsing the
  file with `cut -d= -f2` also captures the inline comment after the value
  (`# openssl rand -hex 24`), producing a 73-character string that makes
  `curl` fail with exit 3 on a malformed URL. Compose strips those comments
  when it loads the env file, so `printenv` inside the container returns
  the exact 48-character string the server compares against.
- **`/usr/bin/tr`, spelled absolutely.** A `tr` alias in your shell profile
  silently turns this step into something else entirely.
- **`ssh` must actually succeed.** If it fails, `TOKEN` is empty and the
  export returns 404 — the same 404 as a wrong token, with no clue that the
  real problem was ssh.

Sanity-check the result rather than trusting it, since `curl -s` reports
nothing on failure:

```bash
head -1 ~/Desktop/linkage-$(date +%F).csv
```

That should be the column header. If it is `{"detail":"Not found"}` the
request was rejected, which means either a wrong or empty token **or** an
IP that is not allow-listed. The endpoint returns 404 rather than 403
deliberately, so a prober cannot confirm it exists — which also means it
cannot tell you which of the two went wrong. Check `${#TOKEN}` is 48
first, then `curl ifconfig.me` against the `remote_ip` line in `Caddyfile`.
Note that a laptop reaching the site over IPv6 is matched by the `/64` in
that line, not by the IPv4 address.

Columns, from [`linkage_export`](study_site.py):

| Column | Meaning |
|---|---|
| `prolific_pid` | Prolific participant ID. Joins to Prolific's export. |
| `session_id` | Prolific session ID. |
| `channel` | `sms` or `web`, whichever the participant actually used. Empty if they never started one. |
| `code` | The one-time code issued at consent. |
| `chat_id` | Retell chat ID. Joins to the transcript. Empty until the participant texts in. |
| `stage` | `arrived`, `consented`, `texting`, `complete`, `timed_out`, or `withdrew`. |
| `attention_failures` | Count of checks recorded as failed. |
| `checks_seen` | Count of checks that ran at all. A failure count of 0 means something different when this is 0. |
| `consented_at` | Unix timestamp, or empty. |

`complete` and `timed_out` are both terminal and both reached from `texting`,
and they mean opposite things: `complete` is written only by `/api/complete`,
which the agent calls from the node before its End node, while `timed_out` is
written by the `chat_ended` webhook when the chat closed without that call.
Keeping them apart is what lets this export distinguish a finished interview
from an abandoned one.

`phone_hash` is stored but deliberately not exported. The plaintext number
is never stored at all.

### Assembling the complete table

The linkage CSV is a **key, not a dataset**. It carries no demographics and
no transcript text. A complete table is a join across three sources:

| Source | How to get it | Join column |
|---|---|---|
| Linkage | the `curl` above | — |
| Demographics, submission status, time taken | Prolific → your study → Data → export CSV | `prolific_pid` |
| Transcripts, chat analysis | Retell dashboard or API export | `chat_id` |

This split is the privacy design, not an inconvenience. The linkage lives
on this droplet precisely so that Retell never stores a direct identifier
next to a conversation; see the docstring on `linkage_export` in
[study_site.py](study_site.py). Joining the three files reverses that
separation, so the assembled table is the most sensitive artifact the study
produces. Keep it off shared drives and out of the repo.

```python
import pandas as pd

linkage = pd.read_csv("linkage-2026-08-21.csv")
prolific = pd.read_csv("prolific_export.csv")
retell = pd.read_csv("retell_chats.csv")

merged = (
    linkage
    .merge(prolific, left_on="prolific_pid", right_on="Participant id", how="left")
    .merge(retell, on="chat_id", how="left")
)
merged.to_csv("study-complete-2026-08-21.csv", index=False)
```

**Verify the header names against the actual files before trusting that
snippet.** Prolific's export has used `Participant id` with that exact
capitalisation, and Retell's export shape depends on how you pull it, but
both are outside this repository's control and neither is pinned by
anything here. `print(prolific.columns.tolist())` costs nothing.

Two checks worth running on the result, because both failures are silent:

```python
# Anyone who never texted in -- whether they dropped at the information
# sheet or after consenting -- has an empty chat_id, so their Retell columns
# are legitimately blank. Expected, not a join failure. Cross-tabulate
# against stage to see where they actually stopped.
print(linkage.groupby("stage")["chat_id"].apply(lambda c: c.isna().sum()))

# Rows that should have matched and did not. This one is a real problem.
matched = merged["Participant id"].notna().sum()
print(f"{matched} of {len(linkage)} matched Prolific")
```

A participant at stage `complete` with no Prolific match usually means the
export was pulled before they submitted; re-export rather than assuming the
linkage is wrong.

---

## `optin/` — A2P campaign paperwork

```
optin/
    A2P_submission.md         Campaign application field text
    build_optin_page.py       Generates the opt-in page from the app's constants
    add_web_branch.py         Adds the browser branch to the Retell flow export
    patch_retell_flow.py      Applies the flow fixes to a Retell export
    retell-flow-changes.md    The same changes, as dashboard steps
    hostname-switch.md        Runbook for moving to studies.childmind.org
    email-cmi-dns-followup.md Correspondence with CMI IT
```

Paperwork rather than code, but it quotes this study's number and
disclosures, so it belongs beside them and travels with the directory when
the study is copied.

The opt-in page itself is not a file in there. `build_optin_page.py`
generates it from the application's own constants, so the disclosure wording
on the page and in the consent record stored for each person cannot drift —
a previous hand-maintained duplicate is exactly how pre-rejection wording
stayed live after the canonical text was corrected.

The page the campaign cites is published on matter.childmind.org, not served
here. The site's own front page is rendered by `study_site.py`.

---

## Troubleshooting

**Container restarts repeatedly with a `KeyError`.** A missing environment
variable — `study_site.py` reads `PROLIFIC_CC_*` at import. Check
`docker compose logs dash`.

**`/api/verify-code` returns "not recognised" for a valid code.** The
container was rebuilt without the volume mounted, so it is reading a fresh
database. Confirm `docker compose config` still shows `dash_data:/data`.

**The opt-in form fails silently in the browser.** `OPTIN_PAGE_ORIGIN` does
not match where the page is actually served from, so the POST is blocked by
CORS. Check the browser console rather than the server log — the request
never arrives.

**`/api/opt-in` reports the confirmation as `unconfigured`.** No
`RETELL_API_KEY` is set. The consent is still recorded; only the text was
not attempted.

**A confirmation text is accepted but never arrives.** Expected until the
A2P campaign is approved: carriers filter outbound A2P messages, so a
successful API call means Retell accepted it, not that anyone received it.

**A participant's interview reads as if it never had a code.** The Retell
flow's verification nodes were unreachable in an earlier export. See
`optin/retell-flow-changes.md`, and confirm the flow version in the Retell
dashboard is actually **published** — a draft version leaves the live number
answering with the old flow.

For 502s, certificate loops, failed builds and admin-export 404s, see
[Troubleshooting](../README.md#troubleshooting) in the repository README.
