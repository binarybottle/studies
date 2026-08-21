# Deploying the study site to DigitalOcean

Runs the DASH text screener at `https://study.arnoklein.info` on a single
Ubuntu droplet: Caddy terminating TLS, one container per study, SQLite on a
named Docker volume.

For what the application *does* — the participant journey, Retell wiring,
Prolific completion codes, and the privacy design for IRB review — see the
main `README.md`. This document is only about getting it running.

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
        env.example      Template — copy to .env
        study_site.py    The application
        store.py         SQLite persistence
```

Only two files need editing: `Caddyfile` (two `EDIT:` markers) and
`dash/.env`. Everything else is used as-is.

---

## 1. Droplet

DigitalOcean → Create → Droplets.

- **Image:** Ubuntu 24.04 LTS
- **Region:** NYC3
- **Size:** Basic → Regular → 1 GB / 1 vCPU ($6/mo) is sufficient
- **Authentication:** SSH key
- **Backups:** enable ($1.20/mo — the droplet holds the linkage database)

---

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

The 1 GB droplet can run out of memory while building Python wheels.

```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

Reboot if the login banner asks for it; this also activates the `docker`
group membership.

---

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

---

## 4. Upload

From the directory containing this bundle:

```bash
ssh arno@DROPLET_IP 'mkdir -p ~/studies/dash'
scp compose.yml Caddyfile backup.sh arno@DROPLET_IP:~/studies/
scp dash/* arno@DROPLET_IP:~/studies/dash/
```

---

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

---

## 6. Start

```bash
cd ~/studies
docker compose up -d
docker compose logs -f caddy      # watch for certificate issuance
```

Verify:

```bash
curl -I https://study.arnoklein.info/sms-terms        # expect 200
curl -I https://study.arnoklein.info/admin/linkage.csv # expect 404 from the droplet
```

The second check confirms the IP restriction is active: requests from the
droplet itself are not your home address, so they are refused.

Walk the participant path in a browser:

```
https://study.arnoklein.info/start?PROLIFIC_PID=test123456789012345678
```

Information sheet → consent → a five-character code and the study phone
number.

---

## 7. Backups

`study.db` is the only key connecting Retell transcripts to Prolific
submissions. Losing it makes every transcript permanently unattributable.

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
are weekly, which is coarser than a study needs.

---

## Operating

| Task | Command |
|---|---|
| Redeploy after a code change | `docker compose up -d --build dash` |
| Follow logs | `docker compose logs -f dash` |
| Restart | `docker compose restart dash` |
| Shell in the container | `docker compose exec dash sh` |
| Stage counts | `docker compose exec dash python -c "import store; store.init_db(); print(store.summary())"` |
| Export linkage table | `curl "https://study.arnoklein.info/admin/linkage.csv?token=$ADMIN_TOKEN"` |

**Never run `docker compose down -v`.** The `-v` flag deletes named volumes,
including `dash_data` and therefore `study.db`. Plain `docker compose down`
is safe.

---

## Adding a second study

1. Copy `dash/` to a new directory, e.g. `screener2/`.
2. Add a service block in `compose.yml` pointing at it, with its own volume.
3. Add a site block in `Caddyfile` for the new hostname.
4. Add the DNS A record.
5. `docker compose up -d`

Studies stay isolated: separate containers, separate volumes, separate
databases.

---

## Troubleshooting

**Caddy loops requesting a certificate.** DNS has not propagated, or the name
resolves somewhere else. Check `dig +short study.arnoklein.info @1.1.1.1`.

**502 from Caddy.** The `dash` container is down or still starting.
`docker compose ps` and `docker compose logs dash`.

**Container restarts repeatedly.** Almost always a missing environment
variable — `study_site.py` reads `PROLIFIC_CC_*` at import. Check
`docker compose logs dash` for the `KeyError`.

**Build killed during `pip install`.** Out of memory. Confirm swap is active
with `free -h`.

**`/api/verify-code` returns "not recognised" for a valid code.** The
container was rebuilt without the volume mounted, so it is reading a fresh
database. Confirm `docker compose config` still shows `dash_data:/data`.
