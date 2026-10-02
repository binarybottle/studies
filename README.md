# studies — deployment and operations

Runs one or more study sites on a single Ubuntu droplet: Caddy terminating
TLS, one container per study, SQLite on a named Docker volume per study.

This document covers the droplet: creating it, deploying to it, operating it,
backing it up. It is study-agnostic. What a study *does* — the participant
journey, its vendor wiring, its Prolific setup, its environment variables and
its data export — is documented in that study's own directory. There are
two:

- **[dash/README.md](dash/README.md)** — the DASH text-message screener
  pilot, whose interview runs on a hosted Retell agent.
- **[msm-mobi/README.md](msm-mobi/README.md)** — the MSM-MoBI scenario
  conversations, a self-contained web app that calls the model directly.

Commands below name the `dash` service as the example. For the other study
substitute `msm-mobi`; nothing else changes.

The live droplet is **167.71.248.46** (`ssh arno@167.71.248.46`). Part 1
writes `DROPLET_IP` because it describes building a droplet that does not
exist yet; Parts 2 and 3 use the real address.

- [Part 1 — First-time setup](#part-1--first-time-setup): once per droplet.
- [Part 2 — Rebuild and deploy](#part-2--rebuild-and-deploy): every code change.
- [Part 3 — Operating](#part-3--operating): backups, logs, isolation, access,
  troubleshooting.

---

## Files

```
studies/
    compose.yml          Caddy + one service per study
    Caddyfile            TLS, routing, admin IP restriction
    backup.sh            Nightly SQLite backup of every study, 30-day retention
    capacity.sh          Each study's memory against its own cap, and the
                         droplet's headroom; run it during a live batch
    grant-access.sh      Give (or revoke) one person deploy access to named
                         studies; see Access
    retell.md            Retell agents and flows: setup, publishing, secrets
    dash/                The DASH study. See dash/README.md.
        README.md        What the study is and how it is configured
        STATUS.md        Point-in-time handoff briefing
        Dockerfile       Pinned Python 3.12 runtime
        requirements.txt Pinned dependencies
        env.example      Template — copy to .env on the droplet
        study_site.py    The application
        store.py         SQLite persistence
        optin/           A2P campaign paperwork; not deployed
    msm-mobi/            The MSM-MoBI study. See msm-mobi/README.md.
        README.md        What the study is and how it is configured
        Dockerfile, requirements.txt, env.example   As above
        app/             The application (FastAPI + a static browser UI)
        content/         Scenario bank, categories, stance prompts
        scripts/         Model check, load simulation, content import
        tests/           pytest suite
```

Everything a study needs lives in that study's directory, including material
that is never deployed with it, so that copying the directory copies the
whole study. `retell.md` is the exception, and deliberately: it describes the
Retell platform rather than any one study, so a second study running its
interview there inherits it rather than rediscovering it.

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
| `msm-mobi/app/`, `msm-mobi/content/` | `docker compose up -d --build msm-mobi` |
| `requirements.txt`, `Dockerfile` | `docker compose up -d --build <service>` (slow — reinstalls wheels; msm-mobi's LiteLLM takes a minute or more) |
| a study's `.env` | `docker compose up -d <service>` — no build; recreates the container so it re-reads the file. Edit it on the droplet: it is not in the repository |
| `Caddyfile` | `docker compose up -d --force-recreate caddy` — **not** `caddy reload`, see below |
| `compose.yml` | `docker compose up -d` |
| Nothing; just wedged | `docker compose restart dash` |

**Why the Caddyfile needs a recreate and not a reload.** `compose.yml` mounts
it as a single file, `./Caddyfile:/etc/caddy/Caddyfile`, and a single-file bind
mount binds the *inode*, not the path. `git pull` does not write the file in
place — it writes a replacement and renames it over the old one, which gives
the file a new inode. The container goes on reading the old inode, which is
still on disk because the mount holds it open. So after a pull the running
Caddy sees the previous contents, and `caddy reload` answers `config is
unchanged` and exits 0. It looks like it worked. It did nothing. Recreating the
container re-resolves the path and picks up the new file. Editing the Caddyfile
in place on the droplet keeps the inode and *does* work with `reload`, which is
why this is easy to miss.

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
| Memory per study, against its cap | `./capacity.sh` |
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
~/studies/backup.sh          # run once manually — an untested backup is not a backup
crontab -e
```

```
0 3 * * * /home/arno/studies/backup.sh >> /home/arno/studies/backup.log 2>&1
```

`backup.sh` and `capacity.sh` are committed executable, so a `git pull` keeps
them runnable. That matters more than it sounds: cron invokes `backup.sh` by
path, so if the executable bit is ever lost the nightly backup fails silently
except for a line in `backup.log`. If you add a script here, commit it with
`git update-index --chmod=+x` rather than relying on a local `chmod`, which a
pull that rebases will undo.

Uses SQLite's backup API rather than `cp`, since the database runs in WAL mode
and a plain copy taken mid-write can be unrestorable. Verifies the copy opens
and counts rows before keeping it. Prunes past 30 days. One file per study
per night, `dash-<date>.db` and `msm-mobi-<date>.db`; a study whose container
is not running is skipped rather than failing the job. The list of studies is
`SERVICES` at the top of the script.

Copy backups off the droplet periodically — DigitalOcean's droplet backups
are weekly, which is coarser than a study needs:

```bash
rsync -av arno@167.71.248.46:~/studies/backups/ ./backups/
```

### Restoring

```bash
docker compose stop dash
docker run --rm -v studies_dash_data:/data -v ~/studies/backups:/b \
    alpine cp /b/dash-2026-08-20.db /data/study.db
docker compose start dash
```

The volume is `studies_dash_data` (`studies_msm_mobi_data` for the other
study) — Compose prefixes the volume name from `compose.yml` with the project
directory name. Confirm with `docker volume ls` before typing it.

## Adding a study

1. Copy the closest existing study directory. `dash/` is the template for
   a Retell-hosted interview and brings its `optin/` campaign text; `msm-mobi/`
   is the template for a self-contained web task that calls a model directly.
   Either way the new study's documentation and consent text start from
   wording that already passed review, and are edited rather than written.
2. Add a service block in `compose.yml` pointing at it, with its own volume,
   its own network, and a `mem_limit` (start generous, then set it from
   `./capacity.sh` during the first real batch); add the network to Caddy's
   `networks` and the service to Caddy's `depends_on`.
3. Add a site block in `Caddyfile` for the new hostname.
4. Add the service name to `SERVICES` in `backup.sh`.
5. Add the DNS A record.
6. Create the study's `.env` on the droplet, then `docker compose up -d`.

Studies stay isolated: separate containers, separate volumes, separate
databases, separate networks. See [Isolation between
studies](#isolation-between-studies) for what that does and does not
guarantee, and [Retiring a study](#retiring-a-study) for the other end of the
lifecycle — the droplet fills up with finished studies left running, not with
new ones.

### Bringing up msm-mobi the first time

Everything above is in place in the repository. What remains is on the
droplet and at the DNS provider:

```bash
# DNS: A record msm-mobi.study.childmind.org -> 167.71.248.46, then confirm:
dig +short msm-mobi.study.childmind.org @1.1.1.1

ssh arno@167.71.248.46
cd ~/studies && git pull
cp msm-mobi/env.example msm-mobi/.env && chmod 600 msm-mobi/.env
nano msm-mobi/.env            # ANTHROPIC_API_KEY, ADMIN_TOKEN, the two Prolific codes
docker compose up -d --build msm-mobi
docker compose up -d --force-recreate caddy   # new site block
docker compose logs -f caddy                  # watch for certificate issuance
docker compose exec msm-mobi python scripts/check_llm.py --repeat 3
```

Then walk `https://msm-mobi.study.childmind.org/start?PROLIFIC_PID=walkthrough-1`
end to end. The droplet was resized to 2 GB / 1 vCPU for the second study:
LiteLLM alone is ~200 MB resident, on top of DASH and Caddy, and 1 GB was
tight for both. Both apps are I/O-bound, so one vCPU is enough.

## Isolation between studies

Each study gets its own container, its own named volume, its own SQLite
database, its own `.env`, its own `ADMIN_TOKEN`, its own Docker network, and
its own memory ceiling. Two of those are worth explaining, because what they
protect against is narrower than it looks.

### A network per study

Compose's default is a single bridge network on which every container
resolves and reaches every other by name. On that default, the `msm-mobi`
container can open a socket to `dash:8000` — and the `Caddyfile`'s IP
restriction on `/admin/*` does nothing about it, because that rule lives at
the edge and such a request never reaches the edge.

`compose.yml` therefore declares one network per study and joins Caddy to all
of them, since Caddy is the one thing that must reach everything.

**Be clear about what this buys.** The export that matters, DASH's
`/admin/linkage.csv`, needs DASH's `ADMIN_TOKEN`, which lives in a different
container's environment — so it was never reachable this way. The rest of
each study's surface is public endpoints that anything on the internet can
already reach. The one real gain is that a compromised study can no longer
forge `X-Forwarded-For` against its neighbour to evade the per-address rate
limit on DASH's opt-in endpoint.

The reason to keep it is not that it closes a live hole. It is that "a
study's port is reachable only by Caddy" becomes a property of the
configuration rather than a coincidence, and the `--forwarded-allow-ips *` in
each `Dockerfile` is justified by a premise that is now actually true. A
third study added by someone else inherits the segmentation instead of
inheriting a flat network.

It protects against nothing a person with `docker` group access does; see
[Access](#access).

### A memory ceiling per study

`mem_limit` on each service, with `memswap_limit` pinned to the same value.
Currently 768 MB for `msm-mobi` (LiteLLM alone is ~200 MB resident), 384 MB
for `dash`, 96 MB for Caddy.

These are circuit breakers, not budgets. Without them the kernel's OOM killer
scores by size and may kill a bystander study; today it would most likely
pick `msm-mobi` as the largest process, which protects DASH by luck rather
than by rule, and would not protect `msm-mobi` from a leak in DASH. With
them, a runaway container is the one that dies.

**A limit is a ceiling, not a reservation.** Docker sets nothing aside: a
container capped at 768 MB that is using 250 MB is using 250 MB, and the other
1.7 GB is available to everything else. Nothing is lost by setting a limit
generously, and the limits are *expected* to sum to more than the droplet has.
That is what makes this scale — see
[Sizing them as studies come and go](#sizing-them-as-studies-come-and-go).

`memswap_limit` matters because Docker otherwise allows a container twice its
`mem_limit` in swap, and this droplet has a 2 GB swapfile for builds. A
container that swapped instead of dying would keep running at disk speed on
one vCPU and drag every other study down with it, which is worse than the
clean kill. Build-time memory is unaffected by either setting, so [Swap](#swap)
still does its job for `pip install`.

The cost is that hitting a limit is a `SIGKILL` and a restart, not
backpressure: participants resume at the same step, but a model turn in
flight is lost. So set these generously, and check them against reality with
`./capacity.sh` during a live batch.

### Sizing them as studies come and go

Do not divide the droplet's memory among the studies. Because a limit is a
ceiling and not a reservation, a study's cap is a property of **that study**
and nothing else:

> **cap ≈ 3× the study's own measured peak, rounded up.**

Set it from one observation of that study under load and leave it alone.
Adding a fourth study does not require re-deriving the other three, and
retiring one does not free a number that someone has to redistribute. That is
the whole reason this scales: there is no shared budget to rebalance, and no
arithmetic that goes stale when the roster changes.

The caps will sum to more than the droplet has. That is correct and not worth
computing. Two separate numbers matter, and `./capacity.sh` prints both:

```bash
./capacity.sh            # during a live batch -- idle numbers mean nothing
./capacity.sh --watch    # every 10s
```

- **Each study against its own cap.** Answers "is this cap still right". Above
  ~50% during a real batch, raise it. This is per study and independent of the
  others.
- **`available` on the host.** Answers "can this droplet take another study".
  This is the only number that is actually shared, and it is a capacity
  question, not a limits question — limits cannot create memory. When
  `available` runs low the answer is a bigger droplet or a retired study, not
  smaller caps.

The script derives its service list from `docker compose config --services`,
so a study added or retired needs no edit to it. It exits non-zero when
something wants attention, including a service with no `mem_limit` at all and
one whose `memswap_limit` does not match — both are easy to forget when
copying a service block for a new study.

Swap in use is called out separately: containers are pinned so they cannot
swap, so swap activity means the host itself, usually a build. Investigate
that before adding a study rather than after.

### Retiring a study

Studies end at different times, and a finished study left running is the way
this droplet fills up — five idle studies holding a few hundred MB each, with
nobody recruiting. Memory is reclaimed by **stopping the container**, which
costs nothing and keeps everything:

```bash
./backup.sh                          # before touching a finished study
docker compose stop msm-mobi         # frees all of its memory
```

The volume, the database, and the image all survive. `restart:
unless-stopped` is what makes this stick across a droplet reboot — a stopped
container stays stopped, which is exactly what a finished study should do.
`./capacity.sh` then reports it as `stopped (no memory held)`.

To read the data again, start it, export, stop it again:

```bash
docker compose start msm-mobi
docker compose exec msm-mobi python scripts/screen.py --db /data/study.db --show
docker compose stop msm-mobi
```

**One trap.** Caddy's `depends_on` lists every study, and `docker compose up
-d caddy` starts a service's dependencies — so recreating Caddy after a
`Caddyfile` edit silently restarts every study you had stopped. Use
`--no-deps` once a study is retired:

```bash
docker compose up -d --force-recreate --no-deps caddy
```

Or remove the retired study from `depends_on`, which is tidier and worth doing
at the point the study is finished for good. While its container is stopped,
its hostname answers `502`; if the study is public and people may still visit,
replace the site block's `reverse_proxy` with a `respond` serving a short
closed-study notice, which also stops Let's Encrypt renewing a certificate for
a backend that is not there.

Full teardown, once the data is archived off the droplet and the paper is out:
remove the service block, its network, and its `depends_on` entry from
`compose.yml`, the site block from `Caddyfile`, the service from `SERVICES` in
`backup.sh`, and the DNS record. Keep the study directory in Git — it is the
record of what participants saw. Remove the volume last and deliberately
(`docker volume rm studies_msm_mobi_data`), never with `down -v`, and only
once you have verified a backup restores.

### Applying a change to either

Both are container-level settings, so they take effect on recreate:

```bash
./backup.sh                 # first, if a study is live
docker compose up -d        # recreates every container whose config changed
docker compose ps
```

This is the one case where the bare `docker compose up -d` is correct rather
than dangerous — the networks change for every service at once. It restarts
every study on the droplet, so do it between recruitment batches, not during
one.

### Narrowing further than this script can

Nothing above constrains a person in the `docker` group, and
`grant-access.sh` cannot change that. If the requirement is that a
collaborator genuinely cannot reach another study's data, there are two
honest options:

- **`sudo` wrappers instead of the `docker` group.** Write root-owned,
  argument-free scripts — `/usr/local/bin/msm-deploy`, `msm-logs`,
  `msm-screen` — each doing one fixed thing, and grant exactly those in
  `sudoers`. The person is then not in `docker` at all: no mounting volumes,
  no `compose exec`, no reading another study's `.env`. Fixed command lines
  with no arguments are what makes this hold; the moment arguments pass
  through to `docker`, it is root again. The cost is that anything you did
  not anticipate comes back to you.
- **A separate droplet per study.** $6–12/month, and the only option with no
  caveats attached.

## Access

Decide what the person actually needs before granting anything, because the
three levels differ enormously in what they expose:

| They need to | Give them |
|---|---|
| Read a study's data | That study's `ADMIN_TOKEN` and their IP address in `Caddyfile` — no droplet account at all. See the study's own README. |
| Deploy code | A user account, the `docker` group, and the shared checkout — below. |
| Administer the host | Their own account plus `sudo`. Not covered here. |

**What deploy access grants, unavoidably.** Membership of the `docker` group
is root-equivalent: a member can mount any volume, so they can read every
study's database and therefore all participant data, not only the study they
came for. `docker run -v dash_data:/d alpine cat /d/study.db` is the whole
attack, and `docker compose exec dash printenv` gets the secrets. There is no
way to grant "may rebuild a container" without that. It is a data-access
decision before it is a technical one; check it against the protocol that
governs the data.

`grant-access.sh` takes a list of studies and makes only those studies'
`.env` files readable to the person, leaving the rest at `600`. That is worth
doing, but be precise about what it is: it closes the **accidental** path — a
`grep -r` across the checkout, a `cat */.env`, a tab-completion into the
wrong directory — which is the disclosure that actually happens between
colleagues. It does not close the deliberate one, because file modes do not
constrain a `docker` group member. If you need the deliberate path closed
too, see [Narrowing further than this script
can](#narrowing-further-than-this-script-can).

The checkout itself is shared whole and cannot be split per study: one Git
working tree needs write access across all of it to `git pull`. That is
acceptable because the source is public on GitHub — the `.env` files are the
secrets, and those are what the study list governs.

Note also that a DigitalOcean **team** invitation is a different thing
entirely, and not what this section is about: it grants the control panel —
snapshots, resizing, the console, destroying the droplet — but no shell, and
it cannot be scoped to one project, because a DigitalOcean project is a
folder rather than a permission boundary.

### Granting deploy access

Ask them for their SSH **public** key: one line from
`cat ~/.ssh/id_ed25519.pub` on their own machine, or `ssh-keygen -t ed25519`
if they have none. Then, on the droplet:

```bash
cd ~/studies && git pull
sudo ./grant-access.sh dan 'ssh-ed25519 AAAAC3Nza... dan@example.org' msm-mobi
```

Quote the key. The trailing arguments are the studies they need; `all` grants
every study on the box. **The list is required** — which studies' secrets a
person can read is a decision, and a default would make it silently. A name
that is not a study directory aborts before anything changes, so a typo
cannot grant nothing and look like success.

`grant-access.sh` creates the account, grants the `docker` group and a share
of this checkout, sets the named studies' `.env` to `640` and forces every
other study's to `600`, then **verifies the result by running the real
commands as that person** — reach the checkout, write to it, fetch from
GitHub, run `docker compose`, read the granted `.env` files, and *fail* if an
ungranted one turns out to be readable — and prints the exact instructions to
send them. It validates the public key before touching anything, because a
key pasted through a chat client arrives wrapped across lines more often than
not.

It is idempotent, and re-running it with a **different** list moves the modes
to match, in both directions:

```bash
sudo ./grant-access.sh dan 'ssh-ed25519 AAAA...' msm-mobi dash   # widen
sudo ./grant-access.sh dan 'ssh-ed25519 AAAA...' msm-mobi        # narrow again
```

That matters because the script's recursive `chmod g+rwX` over the checkout
loosens every `.env` on the way past; the per-study pass runs afterwards and
puts the ungranted ones back to `600`. Re-running is the supported way to
change someone's scope — there is no separate subcommand.

Each grant is recorded in `.access/<user>` (git-ignored) so that "who can read
what" is answerable later without reading file modes, and so `--revoke` can
name what the person actually had.

**Log out and back in afterwards.** Group membership applies to new sessions
only, so your own `studies` membership is not active in the session that ran
the script, and new files you create there will carry the wrong group until
you reconnect.

Four things worth knowing about what it does:

- **The checkout stays in `/home/arno`.** Moving it to `/srv/studies` would
  be conventionally tidier, but it means updating the `backup.sh` crontab
  entry, every path in these READMEs, and re-verifying that Compose still
  derives the same volume names from the directory. Not worth it for a
  second person. The script derives every path from its own location, so a
  move would not need it edited.
- **The owner's home becomes traversable, not listable** (`chmod g=x`): they
  can reach a path they know inside it but cannot list the directory, and
  `~/.ssh` stays `700` regardless.
- **The setgid bit** on directories is what makes files created later
  inherit the `studies` group; without it the sharing decays as soon as
  either of you adds a file.
- **Re-check a `.env` after editing it.** `nano` edits in place and keeps
  the mode, but an editor that writes a replacement file and renames it over
  the original gives the new file your umask instead, which silently drops
  the group's read access and breaks their next deploy. Re-running
  `grant-access.sh` repairs it.

### What they do

The script prints this with the real values filled in:

> ```bash
> ssh dan@167.71.248.46
> cd /home/arno/studies
> git pull
> docker compose up -d --build msm-mobi
> docker compose ps                        # should reach "healthy" within ~40s
> docker compose logs -f msm-mobi          # Ctrl-C stops following
> ```
>
> **Always name your own service.** A bare `docker compose up -d` restarts
> every study on the droplet, including other people's live ones. And never
> `docker compose down -v`, which deletes the data volumes.
>
> Participants mid-session survive a rebuild — they resume at the same step —
> but would meet new wording from their next turn, so deploy between
> recruitment batches rather than during one.
>
> Changes go through GitHub, not this checkout: edit on your own machine,
> push, then `git pull` here.

The service names in that block are the ones you granted, not every service on
the box, so the person is told to name their own. The last paragraph is there
because the checkout is shared: edits made in place collide with yours and
leave it ambiguous what is deployed.

That is the [deploy loop](#part-2--rebuild-and-deploy) above with an absolute
path in place of `~/studies`, and nothing else: the script sets Git's
`safe.directory` system-wide, so no one has to configure anything on their
first login.

### Revoking

```bash
sudo ./grant-access.sh --revoke dan
```

That removes them from the `docker` and `studies` groups, which is what
actually ends deploy access, and leaves the account in place — it can do
nothing without those groups. To remove the account and its home as well,
the script prints the `deluser` command.

The script prints the studies they were granted, from `.access/<user>`, and
then clears that record. Rotate `ADMIN_TOKEN` and the vendor API keys for
those studies if the parting is not amicable.

Judge the other studies by how the parting went. The granted list is what
they could read without trying; the `docker` group they just lost was
root-equivalent the whole time they had it, so a deliberate reader could have
taken anything on the box. If that possibility matters here, treat every
secret as exposed rather than only the listed ones. `PHONE_HASH_SALT` is the
one that cannot be rotated either way — see the warning in
[dash/README.md](dash/README.md#configuration--dashenv).

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
