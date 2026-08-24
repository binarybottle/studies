# Email to Child Mind Institute web / IT — DNS request

**Subject:** One DNS record needed: *.studies.childmind.org (blocking our SMS campaign)

Hi,

**The ask, up front:** could you add one DNS record?

    *.studies.childmind.org.    A    167.71.248.46

That is the only thing I need. Everything below is why, and what to do if a
wildcard is against policy.

**Why it is blocking**

Mike, Laura, Lauren, Olivia and I are running a pilot of an automated
text-message interviewer for the DASH screener. Before we can send a single
SMS we need an A2P campaign approved — the carrier registration that every
organization sending text messages has to pass. Ours was rejected, in part
because the participant-facing site is on a personal domain,
study.arnoklein.info. Carrier reviewers open the URL directly and judge
whether the messaging program plausibly belongs to the organization it claims
to. On a personal domain it does not, and no amount of correct wording on the
page fixes that.

**Why a wildcard rather than a single name**

This is not a one-off. Each study we run needs its own participant-facing
hostname, and each one otherwise means another request to you. One wildcard
record means you are asked once: I create `dash.studies.childmind.org` now,
and future studies get their own names under `studies.childmind.org` without
anyone opening another ticket.

If wildcards are against policy, in order of preference:

1. Delegate the `studies.childmind.org` zone to me with NS records, which has
   the same effect and keeps the wildcard out of the main zone.
2. Individual A records on request, starting with
   `dash.studies.childmind.org` → 167.71.248.46. This works fine; it just
   means we do this again per study.

Either way it is a DNS change and nothing to install, host, patch, or monitor
on your side.

**On the security question, since a wildcard usually raises one**

The record points at a single DigitalOcean droplet I administer. Nothing under
that name is hosted anywhere else, no CMI systems, credentials, or data live on
it, and it holds no personal data beyond a Prolific participant ID and hashed
phone numbers. TLS is handled on the box: it obtains and renews Let's Encrypt
certificates per hostname over HTTP validation, so no wildcard certificate is
involved. I am happy to have the setup reviewed, and to have the record removed
if anything about it stops being acceptable.

**One thing I am specifically not asking for**

I had considered asking for a reverse proxy from a path on
matter.childmind.org instead, and I want to save you the trouble of
considering it: matter.childmind.org is a GitHub Pages site, which cannot
proxy to another server. It would take a Cloudflare Worker or origin rule —
much more work for you than a DNS record, and one more thing to maintain. It
would also put the application behind the bot challenge described below, which
is the opposite of what the campaign needs.

**What runs there**

A small participant-facing web application per study: a study information page,
a consent form, and a page showing a one-time code that participants text to
our study number. Phone numbers are hashed on arrival and never kept in
plaintext. The sites link to the SMS terms and privacy notices already hosted
on matter.childmind.org rather than keeping their own copies. I maintain the
server, the applications, and their backups.

**A second, separate request**

This one applies regardless of the DNS record. matter.childmind.org sits behind
a Cloudflare managed challenge that returns 403 to any request that is not a
full browser, including the site root. We have just published the messaging
opt-in page there, at matter.childmind.org/studies/dash/opt-in/, and that page
is cited in the carrier registration. If the reviewer or their automated
checker fetches it with anything other than a browser, they get a challenge
page instead of the required disclosures — indistinguishable from the page
being broken, and "the page does not load" is already one of the things we were
rejected for.

Could you exempt `/studies/dash/*` from the bot challenge, or allowlist the
checker if you would rather scope it tightly? Verifiable with:

    curl -s -o /dev/null -w '%{http_code}\n' https://matter.childmind.org/studies/dash/opt-in/

returning 200 rather than 403.

**Timing**

We cannot send a single message until the campaign is approved, and the
resubmission is otherwise ready, so these two changes are the critical path. If
there is a review or approval process for either, please point me at it and I
will follow it.

Happy to walk anyone through the setup.

Thank you!

Arno Klein
Child Mind Institute
arno.klein@childmind.org
