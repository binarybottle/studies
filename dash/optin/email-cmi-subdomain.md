# Email to Child Mind Institute web / IT — subdomain request

**Subject:** Request: a childmind.org subdomain for the DASH text-message pilot

Hi,

I am running a pilot of an automated text-message interviewer for the DASH
screener, and I need a Child Mind Institute hostname for it. Right now it runs
on a personal domain, study.arnoklein.info, and that has become a blocker: our
A2P messaging campaign — the carrier registration required before we can send
any SMS at all — was rejected in part because the participant-facing site is
not on an organization domain. Carrier reviewers open the URL directly and
judge whether the messaging program belongs to the organization it claims to.

**What I am asking for**

Either of these works, whichever is easier for you:

1. **A DNS A record** for a subdomain such as `dash.childmind.org` or
   `dash.matter.childmind.org`, pointing at `167.71.248.46`. That is a
   DigitalOcean droplet I administer. It already terminates TLS with
   automatically renewed Let's Encrypt certificates, so nothing needs to be
   installed or maintained on your side beyond the record itself. If the
   domain sits behind Cloudflare, the record needs to be DNS-only (grey cloud)
   for the first certificate issuance.

2. **A reverse proxy** from a path on an existing site, e.g.
   `matter.childmind.org/studies/dash/`, to that same address, if you would
   rather not delegate a subdomain.

**What runs there**

A small participant-facing web application: a study information page, a consent
form, and a page showing a one-time code that participants text to our study
number. No personal data beyond a Prolific participant ID is stored, phone
numbers are hashed on arrival and never kept in plaintext, and the site
publishes the SMS terms and privacy notices already hosted on
matter.childmind.org rather than duplicating them.

I maintain the server, the application, and its backups. The only thing I need
from you is the DNS record or the proxy rule.

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
