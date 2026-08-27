# Switching to the Child Mind Institute hostname

Do this when the DNS record for `dash.studies.childmind.org` exists and
resolves to 167.71.248.46. Check first, because Caddy cannot get a certificate
before it does — and ask the zone's own nameservers, not a cached resolver:

```bash
dig +short dash.studies.childmind.org                      # expect 167.71.248.46
dig +short @deb.ns.cloudflare.com dash.studies.childmind.org
dig +short @deb.ns.cloudflare.com anything.studies.childmind.org   # proves the wildcard
```

**The answer must be 167.71.248.46 itself.** If it comes back as a Cloudflare
address — 104.x or 172.67.x, which is what `matter.childmind.org` returns —
the record is proxied, and two things follow: Caddy's HTTP validation cannot
reach the server, so no certificate is issued, and the study site ends up
behind the same bot challenge that hides the opt-in page from non-browsers.
The record has to be DNS-only, grey cloud.

Five places name the host, and missing one fails quietly rather than loudly.

## 1. Caddyfile — add the new hostname

Already done in the repository; the site block serves both names:

```
study.arnoklein.info, dash.studies.childmind.org {
```

Keeping the old name was deliberate while a study might have been running:
participants mid-study would have had the old URL open and Prolific would have
had it recorded against submissions in flight. Neither is true — no study has
begun — and the opt-in page now posts to the new host, so the old name can be
retired as soon as steps 4 and 5 are done. The documentation no longer refers
to it.

```bash
ssh arno@167.71.248.46 'cd ~/studies && git pull && \
    docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile'
ssh arno@167.71.248.46 'cd ~/studies && docker compose logs caddy | tail -20'
```

Commit and push first: the droplet is a checkout, and copying files up is the
thing the repository README warns against.

## 2. The study site — where the opt-in form posts

`OPTIN_API_URL` in `dash/study_site.py`. Nothing to do on the droplet: the
constant is read only by the page generator, which runs on a laptop, so a
value set in the server's `.env` would never be seen. Already changed in the
repository to `https://dash.studies.childmind.org/api/opt-in`.

## 3. The opt-in page — regenerate and republish

The page hard-codes the address it posts to, and it is generated, so
regenerate rather than editing it:

```bash
python dash/optin/build_optin_page.py ~/Software/matter-website/opt-in.html
```

Commit and push `matter-website`. Until this is done the published form still
posts to the old hostname, which keeps working only while the Caddyfile serves
both names.

## 4. Retell — the two tool URLs

Both custom tools post to the study host and are configured in the Retell
dashboard, not in either repository:

- `verify_code` -> `https://dash.studies.childmind.org/api/verify-code`
- `complete_study` -> `https://dash.studies.childmind.org/api/complete`

These live in the flow itself, not only in the dashboard, so an import
overwrites a correction made by hand. `patch_retell_flow.py` rewrites them
too; if you edit them in the dashboard instead, remember that the next import
undoes it.

They keep working on the old hostname while the Caddyfile serves both, so
this is not urgent on the day — but a chat that cannot reach `verify_code`
refuses to start the interview, by design, so leaving it undone eventually
stops every session.

## 5. Prolific — the study URL

Change it to:

```
https://dash.studies.childmind.org/start
```

No query string; Prolific appends the identifiers itself. Submissions already
in flight keep working because the old hostname still resolves.

## Doing this while a campaign is under review

Only one of the five steps touches anything the carrier can see. The
application cites three URLs, all on matter.childmind.org — the opt-in page,
the SMS terms, and the privacy notice — and no study-host URL at all. So
steps 1, 2, 4 and 5 are invisible to a reviewer and can be done at any time.

Step 3, republishing the opt-in page, edits a page that is cited and under
review. Nothing a reviewer reads changes — the disclosure, the number, the
unchecked box and the policy links are identical — the only difference is the
address the form posts to. The argument for doing it anyway is that the
address is currently a personal domain, and "the participant-facing site is
not on an organization domain" is one of the reasons the campaign was
rejected the first time. A reviewer who opens the page source sees it.

Sequence it so the page is only ever republished against a hostname already
proven to work: do 1, 2, 4 and 5, confirm the new host end to end, and
republish the page last.

## Afterwards

Walk the whole path once on the new hostname before letting participants near
it: `/start?PROLIFIC_PID=switchtest001`, through consent, opt-in, and the code
page. Then update the A2P campaign if any field cites the old host — as of
this writing none do, because the campaign cites the opt-in page on
matter.childmind.org rather than the study site.
