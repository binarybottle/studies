# Switching to the Child Mind Institute hostname

Do this when the DNS record for `dash.studies.childmind.org` exists and
resolves to 167.71.248.46. Check first, because Caddy cannot get a certificate
before it does:

```bash
dig +short dash.studies.childmind.org      # expect 167.71.248.46
```

Four places name the host, and missing one fails quietly rather than loudly.

## 1. Caddyfile — add the new hostname

Change the site block's first line to serve both names during the change:

```
study.arnoklein.info, dash.studies.childmind.org {
```

Keeping the old name is deliberate. Participants mid-study have the old URL
open, Prolific has it recorded against submissions in flight, and the opt-in
page posts to it. Retire it only once nothing points at it, which is at least
one full study later.

```bash
scp Caddyfile arno@167.71.248.46:~/studies/
ssh arno@167.71.248.46 'cd ~/studies && docker compose restart caddy'
docker compose logs caddy | tail -20     # watch the certificate issue
```

## 2. The study site — where the opt-in form posts

In `dash/.env` on the droplet:

```
OPTIN_API_URL=https://dash.studies.childmind.org/api/opt-in
```

Then `docker compose up -d dash`. No rebuild needed; it only re-reads the file.

## 3. The opt-in page — regenerate and republish

The page hard-codes the address it posts to, and it is generated, so
regenerate rather than editing it:

```bash
python dash/optin/build_optin_page.py ~/Software/matter-website/opt-in.html
```

Commit and push `matter-website`. Until this is done the published form still
posts to the old hostname, which keeps working only while the Caddyfile serves
both names.

## 4. Prolific — the study URL

Change it to:

```
https://dash.studies.childmind.org/start
```

No query string; Prolific appends the identifiers itself. Submissions already
in flight keep working because the old hostname still resolves.

## Afterwards

Walk the whole path once on the new hostname before letting participants near
it: `/start?PROLIFIC_PID=switchtest001`, through consent, opt-in, and the code
page. Then update the A2P campaign if any field cites the old host — as of
this writing none do, because the campaign cites the opt-in page on
matter.childmind.org rather than the study site.
