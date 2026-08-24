# Email to Child Mind Institute web / IT — DNS request

**Subject:** One DNS record needed: *.studies.childmind.org (blocking our SMS campaign)

Hi,

Mike, Laura, Lauren, Olivia and I are running a pilot of an automated
text-message interviewer for the DASH screener, and I need a CMI hostname for
it. Right now it runs on a personal domain, study.arnoklein.info, and that has
become a blocker: our A2P messaging campaign — the carrier registration
required before we can send any SMS at all — was rejected in part because the
participant-facing site is not on an organization domain. Carrier reviewers
open the URL directly and judge whether the messaging program belongs to the
organization it claims to.

**What I'm asking for: one DNS record.**

    *.studies.childmind.org.    A    167.71.248.46

That is a DigitalOcean droplet I administer. It terminates TLS with
automatically renewed Let's Encrypt certificates, obtained per hostname over
HTTP validation, so no wildcard certificate is involved and nothing needs to be
installed or maintained on your side beyond the record. If the zone is behind
Cloudflare, the record should be DNS-only so validation can reach the server.
No CMI systems, credentials, or data live on that machine, and I am happy to
have it reviewed or the record removed if that changes.

A wildcard rather than a single name because each study we run needs its own
hostname: one record means you are asked once rather than every time we start a
study. Separate hostnames also keep studies isolated from each other, which
matters when they have different participants, different consent, and different
review-board status.

If wildcards are against policy, in order of preference:

1. Delegate the `studies.childmind.org` zone to me with NS records. This has
   the same effect, and it keeps the wildcard out of the main zone.
2. Individual A records on request, starting with
   `dash.studies.childmind.org` → 167.71.248.46. This works fine; it just means
   we do this again for every study.

A path-based proxy on matter.childmind.org isn't an option, in case it comes
up: it's a GitHub Pages site and can't proxy to another server.

**Related request**

matter.childmind.org is behind a Cloudflare managed challenge that returns 403
to any request that is not a full browser, including the site root. We have
just published the messaging opt-in page there, at
matter.childmind.org/studies/dash/opt-in/, and that page is cited in the
carrier registration. If the reviewer or their automated checker fetches it
with anything other than a browser, they will get a challenge page instead of
the required disclosures, which is indistinguishable from the page being
broken, and a page that does not load is one of the things we were already
rejected for.

Could you exempt `/studies/*` from the bot challenge? That prefix covers this
page and the equivalent page for every study after it, rather than us asking
again each time; `/studies/dash/*` alone would do for now if you would rather
scope it tightly. It should be verifiable with:

    curl -s -o /dev/null -w '%{http_code}\n' https://matter.childmind.org/studies/dash/opt-in/

returning 200 rather than 403.

We cannot send a single message until the campaign is approved, and the
resubmission is otherwise ready, so this is critical. If there is a review or
approval process for either request, please point me to it and I will follow
it.

Thank you!

Arno Klein, <title>
Child Mind Institute
arno.klein@childmind.org · <Slack or phone>
