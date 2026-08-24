# Deploying the study site to DigitalOcean

Runs the DASH text screener at `https://study.arnoklein.info` on a single
Ubuntu droplet: Caddy terminating TLS, one container per study, SQLite on a
named Docker volume.

For what the application *does* — the participant journey, Retell wiring,
Prolific completion codes, and the privacy design for IRB review — see the
main `README.md`. This document is only about getting it running.

The live droplet is **167.71.248.46** (`ssh arno@167.71.248.46`). Part 1
writes `DROPLET_IP` because it describes building a droplet that does not
exist yet; Parts 2 and 3 use the real address.

- [Part 1 — First-time setup](#part-1--first-time-setup): once per droplet.
- [Part 2 — Rebuild and deploy](#part-2--rebuild-and-deploy): every code change.
- [Part 3 — Operating](#part-3--operating): data export, backups, logs, troubleshooting.

---

## Files

```
studies/
    compose.yml          Caddy + one service per study
    Caddyfile            TLS, routing, admin IP restriction
    backup.sh            Nightly SQLite backup, 30-day retention
    dash/
        Dockerfile       Pinned Python 3.12 runtime
        requirements.txt Pinned dependencies
        env.example      Template — copy to .env on the droplet
        study_site.py    The application
        store.py         SQLite persistence
```

This laptop directory is the source of truth for everything except `.env`,
which exists only on the droplet and is never committed. Deployment is
`scp` + `docker compose up --build`; the droplet does not pull from git.

Only two files need editing at setup: `Caddyfile` (two `EDIT:` markers) and
`dash/.env`. Everything else is used as-is.

---

# Part 1 — First-time setup

Do this once, when creating the droplet. If the site is already running, skip
to [Part 2](#part-2--rebuild-and-deploy).

## 1. Droplet

DigitalOcean → Create → Droplets.

- **Image:** Ubuntu 24.04 LTS
- **Region:** NYC3
- **Size:** Basic → Regular → 1 GB / 1 vCPU ($6/mo) is sufficient
- **Authentication:** SSH key
- **Backups:** enable ($1.20/mo — the droplet holds the linkage database)

## 2. Harden and install Docker

As `root` on first login:

```bash
adduser arno && usermod -aG sudo arno
rsync --archive --chown=arno:arno ~/.ssh /home/arno
ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw --force enable
apt update && apt upgrade -y && apt install -y unattended-upgrades fail2ban
curl -fsSL https://get.docker.com | sh
usermod -aG docker arno
```

Then disable root and password SSH in `/etc/ssh/sshd_config`:

```
PermitRootLogin no
PasswordAuthentication no
```

```bash
systemctl restart ssh
```

**Open a second terminal and confirm `ssh arno@IP` works before closing the
first.** Locking yourself out here means rebuilding the droplet.

### Swap

The 1 GB droplet can run out of memory while building Python wheels. Without
swap, `pip install` is killed partway through every rebuild, not just this
first one.

```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

Reboot if the login banner asks for it; this also activates the `docker`
group membership.

## 3. DNS

DreamHost panel → `arnoklein.info` → DNS → **A** → ADD.

| Field | Value |
|---|---|
| Host | `study` |
| Points to | the droplet's IPv4 address |

Verify before continuing — Caddy's certificate request fails if the name does
not yet resolve:

```bash
dig +short study.arnoklein.info @1.1.1.1
```

If this domain is ever moved behind Cloudflare, keep the record **DNS-only
(grey cloud)** until the certificate is issued. The proxy intercepts the
HTTP-01 challenge.

## 4. First upload

From this directory on your laptop:

```bash
ssh arno@DROPLET_IP 'mkdir -p ~/studies/dash'
scp compose.yml Caddyfile backup.sh arno@DROPLET_IP:~/studies/
scp dash/* arno@DROPLET_IP:~/studies/dash/
```

`scp dash/*` is safe **only here**, before `.env` exists on the droplet. For
every later upload use the deploy command in
[Part 2](#part-2--rebuild-and-deploy), which excludes `.env`.

## 5. Configure

### `Caddyfile`

Two `EDIT:` markers:

- `email` — a real address; Let's Encrypt sends expiry warnings there.
- `remote_ip` in the `@blocked` line — your own address, from
  `curl ifconfig.me` **on your laptop**, not on the droplet. This restricts
  `/admin/*` to you. Space-separate multiple addresses.

If your home IP is dynamic, either update this occasionally or drop the
`@admin` block and rely on `ADMIN_TOKEN` alone.

### `dash/.env`

```bash
cd ~/studies/dash
cp env.example .env && chmod 600 .env
openssl rand -hex 16    # PHONE_HASH_SALT
openssl rand -hex 24    # ADMIN_TOKEN
nano .env
```

`PHONE_HASH_SALT` must be set to its final value **before any participant
texts you**. Rotating it later makes hashes from before and after mutually
incomparable, which silently breaks repeat-handset detection.

The three `PROLIFIC_CC_*` values can stay as placeholders until the Prolific
study exists; update them later and run `docker compose up -d dash`.

## 6. Start

```bash
cd ~/studies
docker compose up -d
docker compose logs -f caddy      # watch for certificate issuance
```

Then run the [verification checks](#verify) below, and walk the participant
path in a browser:

```
https://study.arnoklein.info/start?PROLIFIC_PID=test123456789012345678
```

Information sheet → consent → a five-character code and the study phone
number.

In Prolific, the study URL is `/start` with no query string:

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

## 7. Install backups

See [Backups](#backups) in Part 3. Do this before the study opens, not after.

---

# Part 2 — Rebuild and deploy

The everyday loop: edit on the laptop, upload, rebuild the `dash` service.
Caddy and its certificates are never touched.

## Deploy

From this directory on your laptop:

```bash
DROPLET=arno@167.71.248.46

rsync -av --exclude '.env' --exclude '__pycache__' dash/ "$DROPLET":~/studies/dash/
scp compose.yml Caddyfile backup.sh "$DROPLET":~/studies/
ssh "$DROPLET" 'cd ~/studies && docker compose up -d --build dash'
```

The `--exclude '.env'` is the part that matters. The droplet's `.env` holds
the real `PHONE_HASH_SALT`; overwriting it with the template silently breaks
repeat-handset detection for every participant after that point, and the
original salt is not recoverable. `rsync` also skips unchanged files, so a
one-line edit uploads one file.

Save the block as `deploy.sh` if you prefer, but keep the exclude.

## Not every change needs a rebuild

| What changed | Command (on the droplet, in `~/studies`) |
|---|---|
| `study_site.py`, `store.py` | `docker compose up -d --build dash` |
| `requirements.txt`, `Dockerfile` | `docker compose up -d --build dash` (slow — reinstalls wheels) |
| `dash/.env` | `docker compose up -d dash` — no build; recreates the container so it re-reads the file |
| `Caddyfile` | `docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile` — it is mounted read-only, so no rebuild at all |
| `compose.yml` | `docker compose up -d` |
| Nothing; just wedged | `docker compose restart dash` |

`--build dash` rebuilds only the dash image and recreates that one container.
The `dash_data` volume carries `study.db` across the rebuild, so participant
records survive. Expect about 20 seconds on the 1 GB droplet.

`Dockerfile` installs dependencies before copying the source, so when
`requirements.txt` is unchanged the `pip install` layer should come back
`CACHED` and a source-only edit costs a few seconds. If the build log shows
that step running for real (~14 s), its cache was invalidated — usually
because `requirements.txt` genuinely changed, or the build cache was pruned.
Harmless either way, just slower.

If the study is live, run `./backup.sh` first when the change touches
`store.py` or anything schema-shaped. It is cheap insurance on the one file
that cannot be regenerated.

## Verify

```bash
docker compose ps    # dash should reach "healthy" within ~40s
```

Both `curl` checks below are run **on the droplet** — the expected `404` in
the second one depends on that:

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://study.arnoklein.info/sms-terms
# expect 200

curl -s -o /dev/null -w '%{http_code}\n' https://study.arnoklein.info/admin/linkage.csv
# expect 404 -- from the droplet, which is not your home address
```

The second check confirms the IP restriction is active: requests originating
on the droplet itself are refused.

**Do not use `curl -I` for these.** `-I` sends a HEAD request, every route is
declared `@app.get`, and FastAPI does not auto-register HEAD — so a perfectly
healthy site answers `405` with `allow: GET`. That 405 arriving with both
`server: Caddy` and `server: uvicorn` headers actually proves the whole path
works, but it reads like a failure. The `%{http_code}` form above sends a real
GET.

## Rolling back

Images are not tagged per deploy, so the way back is the source:

```bash
git checkout <good-commit> -- dash/
# redeploy, then git checkout main -- dash/ when done
```

Which is the argument for committing before deploying, so that "the version
participants saw last Tuesday" is a thing that exists.

---

# Part 3 — Operating

## Quick reference

Run these on the droplet, from `~/studies`.

| Task | Command |
|---|---|
| Follow logs | `docker compose logs -f dash` |
| Last 100 log lines | `docker compose logs --tail 100 dash` |
| Container status | `docker compose ps` |
| Restart | `docker compose restart dash` |
| Shell in the container | `docker compose exec dash sh` |
| Stage counts | `docker compose exec dash python -c "import store; store.init_db(); print(store.summary())"` |
| Export linkage table | see [Exporting data](#exporting-data) |
| Disk / memory | `df -h && free -h` |
| Stop everything | `docker compose down` |

**Never run `docker compose down -v`.** The `-v` flag deletes named volumes,
including `dash_data` and therefore `study.db`. Plain `docker compose down`
is safe. Likewise avoid `docker system prune --volumes`.

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

You do not need to run a backup before exporting. The endpoint reads the
live database, so the CSV is current as of the moment you call it.

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

Columns, from [`linkage_export`](dash/study_site.py):

| Column | Meaning |
|---|---|
| `prolific_pid` | Prolific participant ID. Joins to Prolific's export. |
| `session_id` | Prolific session ID. |
| `code` | The one-time code issued at consent. |
| `chat_id` | Retell chat ID. Joins to the transcript. Empty until the participant texts in. |
| `stage` | `arrived`, `consented`, `texting`, `complete`, or `withdrew`. |
| `attention_failures` | Count of checks recorded as failed. |
| `checks_seen` | Count of checks that ran at all. A failure count of 0 means something different when this is 0. |
| `consented_at` | Unix timestamp, or empty. |

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
`dash/study_site.py`. Joining the three files reverses that separation, so
the assembled table is the most sensitive artifact the study produces.
Keep it off shared drives and out of the repo.

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

## Backups

`study.db` is the only key connecting Retell transcripts to Prolific
submissions. Losing it makes every transcript permanently unattributable.

This is disaster recovery, not data export — for a CSV you can analyse, see
[Exporting data](#exporting-data) above.

```bash
chmod +x ~/studies/backup.sh
~/studies/backup.sh          # run once manually — an untested backup is not a backup
crontab -e
```

```
0 3 * * * /home/arno/studies/backup.sh >> /home/arno/studies/backup.log 2>&1
```

Uses SQLite's backup API rather than `cp`, since the database runs in WAL mode
and a plain copy taken mid-write can be unrestorable. Verifies the copy opens
and counts rows before keeping it. Prunes past 30 days.

Copy backups off the droplet periodically — DigitalOcean's droplet backups
are weekly, which is coarser than a study needs:

```bash
rsync -av arno@167.71.248.46:~/studies/backups/ ./backups/
```

### Restoring

```bash
docker compose stop dash
docker run --rm -v studies_dash_data:/data -v ~/studies/backups:/b \
    alpine cp /b/study-2026-08-20.db /data/study.db
docker compose start dash
```

The volume is `studies_dash_data` — Compose prefixes the volume name from
`compose.yml` with the project directory name. Confirm with `docker volume ls`
before typing it.

## Adding a second study

1. Copy `dash/` to a new directory, e.g. `screener2/`.
2. Add a service block in `compose.yml` pointing at it, with its own volume.
3. Add a site block in `Caddyfile` for the new hostname.
4. Add the DNS A record.
5. `docker compose up -d`

Studies stay isolated: separate containers, separate volumes, separate
databases.

## Troubleshooting

**`405` from a `curl -I` check.** Not a fault. See
[Verify](#verify) above — use the `%{http_code}` GET form.

**Caddy loops requesting a certificate.** DNS has not propagated, or the name
resolves somewhere else. Check `dig +short study.arnoklein.info @1.1.1.1`.

**502 from Caddy.** The `dash` container is down or still starting.
`docker compose ps` and `docker compose logs dash`.

**Container restarts repeatedly.** Almost always a missing environment
variable — `study_site.py` reads `PROLIFIC_CC_*` at import. Check
`docker compose logs dash` for the `KeyError`.

**Build killed during `pip install`.** Out of memory. Confirm swap is active
with `free -h`; see [Swap](#swap) in Part 1.

**Changes deployed but the site looks unchanged.** The upload landed somewhere
other than `~/studies/dash/`, or the rebuild ran in the wrong directory. Check
the file's timestamp on the droplet with `ls -l ~/studies/dash/` and confirm
`docker compose ps` shows the container created seconds ago, not hours.

**`/api/verify-code` returns "not recognised" for a valid code.** The
container was rebuilt without the volume mounted, so it is reading a fresh
database. Confirm `docker compose config` still shows `dash_data:/data`.

**Admin export returns 404 from your own laptop.** Your home IP changed.
`curl ifconfig.me`, update the `remote_ip` line in `Caddyfile`, redeploy, and
reload Caddy.
