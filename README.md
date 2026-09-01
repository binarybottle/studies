# studies — deployment and operations

Runs one or more study sites on a single Ubuntu droplet: Caddy terminating
TLS, one container per study, SQLite on a named Docker volume per study.

This document covers the droplet: creating it, deploying to it, operating it,
backing it up. It is study-agnostic. What a study *does* — the participant
journey, its vendor wiring, its Prolific setup, its environment variables and
its data export — is documented in that study's own directory. There is
currently one:

- **[dash/README.md](dash/README.md)** — the DASH text-message screener pilot.

Commands below name the `dash` service because that is the only one so far.
For a second study, substitute its service name; nothing else changes.

The live droplet is **167.71.248.46** (`ssh arno@167.71.248.46`). Part 1
writes `DROPLET_IP` because it describes building a droplet that does not
exist yet; Parts 2 and 3 use the real address.

- [Part 1 — First-time setup](#part-1--first-time-setup): once per droplet.
- [Part 2 — Rebuild and deploy](#part-2--rebuild-and-deploy): every code change.
- [Part 3 — Operating](#part-3--operating): backups, logs, troubleshooting.

---

## Files

```
studies/
    compose.yml          Caddy + one service per study
    Caddyfile            TLS, routing, admin IP restriction
    backup.sh            Nightly SQLite backup, 30-day retention
    dash/                One study. See dash/README.md.
        README.md        What the study is and how it is configured
        STATUS.md        Point-in-time handoff briefing
        Dockerfile       Pinned Python 3.12 runtime
        requirements.txt Pinned dependencies
        env.example      Template — copy to .env on the droplet
        study_site.py    The application
        store.py         SQLite persistence
        optin/           A2P campaign paperwork; not deployed
```

Everything a study needs lives in that study's directory, including material
that is never deployed with it, so that copying the directory copies the
whole study.

This repository is the source of truth for everything except `.env`, which
exists only on the droplet and is never committed. The droplet holds its own
checkout; deployment is `git pull` plus a rebuild.

Only two things need editing at setup: `Caddyfile` (two `EDIT:` markers) and
the study's `.env`. Everything else is used as-is.

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

One A record per study hostname. For a `childmind.org` host this is CMI IT's
to make; for a domain you control, your registrar's DNS panel.

| Field | Value |
|---|---|
| Host | the study's subdomain, e.g. `dash.study` |
| Points to | the droplet's IPv4 address |

Verify before continuing — Caddy's certificate request fails if the name does
not yet resolve:

```bash
dig +short dash.study.childmind.org @1.1.1.1
```

If a domain is ever moved behind Cloudflare, keep the record **DNS-only
(grey cloud)** until the certificate is issued. The proxy intercepts the
HTTP-01 challenge.

## 4. First upload

The droplet gets its own checkout of this repository. On the droplet:

```bash
git clone git@github.com:binarybottle/studies.git ~/studies
```

That needs a key the droplet can authenticate with. Either add its public key
as a deploy key on the repository, or use HTTPS if the repository is public.

Nothing is copied up by hand, then or later: deployment is `git pull` plus a
rebuild, described in [Part 2](#part-2--rebuild-and-deploy). `.env` is created
directly on the droplet in the next step and never leaves it — it is in
`.gitignore`, so no push or pull can carry it in either direction.

## 5. Configure

### `Caddyfile`

Two `EDIT:` markers:

- `email` — a real address; Let's Encrypt sends expiry warnings there.
- `remote_ip` in the `@blocked` line — your own address, from
  `curl ifconfig.me` **on your laptop**, not on the droplet. This restricts
  `/admin/*` to you. Space-separate multiple addresses.

If your home IP is dynamic, either update this occasionally or drop the
`@admin` block and rely on the study's `ADMIN_TOKEN` alone.

### The study's `.env`

Each study directory has an `env.example` to copy. What the variables mean,
and which of them are dangerous to change later, is documented with the study
— for DASH, see [Configuration](dash/README.md#configuration--dashenv).

## 6. Start

```bash
cd ~/studies
docker compose up -d
docker compose logs -f caddy      # watch for certificate issuance
```

Then run the [verification checks](#verify) below, and walk the study's own
participant path — for DASH, see
[Walking the participant path](dash/README.md#walking-the-participant-path).

## 7. Install backups

See [Backups](#backups) in Part 3. Do this before any study opens, not after.

---

# Part 2 — Rebuild and deploy

The everyday loop: edit on the laptop, push, pull on the droplet, rebuild the
study's service. Caddy and its certificates are never touched.

## Deploy

Commit and push from the laptop, then:

```bash
ssh arno@167.71.248.46 'cd ~/studies && git pull && docker compose up -d --build dash'
```

That is the whole deployment. The droplet is a checkout of this repository,
so `git pull` brings the application, `compose.yml`, `Caddyfile` and
`backup.sh` in one step, and `git rev-parse HEAD` there answers exactly what
is running.

**`.env` is never at risk.** It is listed in `.gitignore`, so it is not in
the repository and `git pull` cannot touch it. This is the reason to prefer
pulling over copying files up: a study's `.env` can hold values that cannot
be regenerated — DASH's `PHONE_HASH_SALT` is one — and overwriting it with
the blank template destroys them silently. A copy command needs an exclusion
to avoid that, and an exclusion can be forgotten.

**Only what you have pushed is deployed.** Uncommitted work on the laptop
does not reach the server. That is deliberate: it means the running code is
always a commit you can name, check out, and go back to.

**Do not edit files on the droplet.** The next pull will either refuse or
conflict, and a local commit made there diverges from this repository in a
way that is easy to create and annoying to unpick. Edit here, push, pull
there. The one exception is `.env`, which is not in the repository and can
only be edited there.

## Not every change needs a rebuild

| What changed | Command (on the droplet, in `~/studies`) |
|---|---|
| `study_site.py`, `store.py` | `docker compose up -d --build dash` |
| `requirements.txt`, `Dockerfile` | `docker compose up -d --build dash` (slow — reinstalls wheels) |
| `dash/.env` | `docker compose up -d dash` — no build; recreates the container so it re-reads the file. Edit it on the droplet: it is not in the repository |
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

If a study is live, run `./backup.sh` first when the change touches
`store.py` or anything schema-shaped. It is cheap insurance on the one file
that cannot be regenerated.

## Verify

```bash
docker compose ps    # dash should reach "healthy" within ~40s
```

Both `curl` checks below are run **on the droplet** — the expected `404` in
the second one depends on that:

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://dash.study.childmind.org/sms-terms
# expect 200

curl -s -o /dev/null -w '%{http_code}\n' https://dash.study.childmind.org/admin/linkage.csv
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
ssh arno@167.71.248.46 'cd ~/studies && git checkout <good-commit> && docker compose up -d --build dash'
# return to the tip with git checkout main, then rebuild again
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
| Export participant data | see [dash/README.md](dash/README.md#exporting-data) |
| Disk / memory | `df -h && free -h` |
| Stop everything | `docker compose down` |

**Never run `docker compose down -v`.** The `-v` flag deletes named volumes,
including `dash_data` and therefore `study.db`. Plain `docker compose down`
is safe. Likewise avoid `docker system prune --volumes`.

## Backups

A study's database is the only key connecting vendor transcripts to Prolific
submissions. Losing it makes every transcript permanently unattributable.

This is disaster recovery, not data export — for a CSV you can analyse, see
[Exporting data](dash/README.md#exporting-data).

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

1. Copy `dash/` to a new directory, e.g. `screener2/`. The copy brings
   `README.md` and `optin/` with it, which is the point: the new study's
   documentation and campaign text start from wording that already passed
   review, and are edited rather than written.
2. Add a service block in `compose.yml` pointing at it, with its own volume.
3. Add a site block in `Caddyfile` for the new hostname.
4. Add the DNS A record.
5. `docker compose up -d`

Studies stay isolated: separate containers, separate volumes, separate
databases.

## Troubleshooting

Symptoms below are droplet-level. For anything specific to a study's
application — its vendor wiring, its environment variables, its API routes —
see that study's README; for DASH,
[Troubleshooting](dash/README.md#troubleshooting).

**`405` from a `curl -I` check.** Not a fault. See
[Verify](#verify) above — use the `%{http_code}` GET form.

**Caddy loops requesting a certificate.** DNS has not propagated, or the name
resolves somewhere else. Check `dig +short dash.study.childmind.org @1.1.1.1`.

**502 from Caddy.** The study's container is down or still starting.
`docker compose ps` and `docker compose logs dash`.

**Container restarts repeatedly.** Almost always a missing environment
variable, read at import time. Check `docker compose logs dash` for a
`KeyError` and compare `.env` against the study's `env.example`.

**Build killed during `pip install`.** Out of memory. Confirm swap is active
with `free -h`; see [Swap](#swap) in Part 1.

**Changes deployed but the site looks unchanged.** The pull did not land, or
the rebuild ran in the wrong directory. On the droplet, check
`git -C ~/studies rev-parse HEAD` matches what you pushed, and confirm
`docker compose ps` shows the container created seconds ago, not hours.

**Admin export returns 404 from your own laptop.** Your home IP changed.
`curl ifconfig.me`, update the `remote_ip` line in `Caddyfile`, redeploy, and
reload Caddy.
