# Email to Child Mind Institute web / IT — subdomain request

**Subject:** Request: a wildcard DNS record for participant-facing study sites

Hi,

I run participant-facing web applications for research studies, and I need them
on a Child Mind Institute hostname rather than the personal domain they are on
today (study.arnoklein.info). This has become blocking: our A2P messaging
campaign — the carrier registration required before we can send any SMS at all
— was rejected in part because the participant-facing site is not on an
organization domain. Carrier reviewers open the URL directly and judge whether
the messaging program belongs to the organization it claims to. It is also
simply the right thing for participants to see.

**What I am asking for**

A single wildcard DNS A record:

    *.studies.childmind.org.    A    167.71.248.46

That is a DigitalOcean droplet I administer. One record covers every study,
now and in future — the current one would be `dash.studies.childmind.org`, and
later studies get their own names without anyone needing to email you again.

TLS needs nothing from you: the server obtains and renews Let's Encrypt
certificates per hostname automatically over HTTP validation, so a wildcard
certificate is not required. If the zone is behind Cloudflare, the record
should be DNS-only (grey cloud) so that validation can reach the server.

If a wildcard is against policy, individual A records work equally well and I
will send a request per study — starting with `dash.studies.childmind.org`.
Either way it is a DNS record and nothing to install, host, or maintain on your
side.

**What runs there**

A small participant-facing web application per study: an information page, a
consent form, and a page showing a one-time code that participants text to our
study number. No personal data beyond a Prolific participant ID is stored,
phone numbers are hashed on arrival and never kept in plaintext, and the sites
link to the SMS terms and privacy notices already hosted on
matter.childmind.org rather than keeping their own copies.

I maintain the server, the applications, and their backups.

**One related request, whether or not the subdomain happens**

matter.childmind.org is behind a Cloudflare managed challenge that returns 403
to any request that is not a full browser, including the site root. We have
just published the messaging opt-in page there, at
matter.childmind.org/studies/dash/opt-in/, and that page is cited in the
carrier registration. If the reviewer or their automated checker fetches it
with anything other than a browser they will get a challenge page instead of
the required disclosures, which is indistinguishable from the page being
broken — and a page that does not load is one of the things we were already
rejected for.

Could you exempt `/studies/dash/*` from the bot challenge, or allowlist the
checker if you would rather scope it tightly? It should be verifiable with:

    curl -s -o /dev/null -w '%{http_code}\n' https://matter.childmind.org/studies/dash/opt-in/

returning 200 rather than 403.

**Timing**

We cannot send a single message until the campaign is approved, and the
resubmission is otherwise ready, so this is currently the critical path. If
there is a review or approval process for subdomains, please point me at it and
I will follow it.

Happy to walk anyone through the setup or the application itself.

Thanks,

Arno Klein
Child Mind Institute
arno.klein@childmind.org
