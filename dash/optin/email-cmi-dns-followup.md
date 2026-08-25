# Reply to Child Mind Institute IT (David) — DNS confirmed, rule still blocking

The DNS record is live and correct. The skip rule matches but skips the wrong
components, and its expression does not cover two of the three URLs filed with
the carrier. Both are one-line fixes in the same rule.

**Subject:** Re: DNS confirmed working — one fix left on the Cloudflare rule

Hi David,

**DNS is confirmed working, thank you.** From the authoritative server and
from a public resolver, and the wildcard resolves for arbitrary names:

    $ dig +short @deb.ns.cloudflare.com dash.studies.childmind.org A
    167.71.248.46
    $ dig +short @1.1.1.1 anything.studies.childmind.org A
    167.71.248.46

Grey cloud confirmed too — it answers with the droplet address rather than a
Cloudflare one, which is what our certificate issuance needs. That side is
done, and I can take it from here.

**The challenge is still firing, including on the path your rule matches.**
Just now, from a residential connection:

    /studies/dash/opt-in/    403  cf-mitigated: challenge   (cf-ray a30cfc633e55dd82-EWR)
    /sms-terms/              403  cf-mitigated: challenge
    /sms-privacy/            403  cf-mitigated: challenge

Your description points at two causes, and I think both are real.

**1. The skip list does not include Super Bot Fight Mode.** You have the
action as "Skip WAF features (including Super Bot Fight Mode)", but the
components listed are "All managed rules, All rate limiting rules". In the
Skip action, Super Bot Fight Mode is its own checkbox — skipping managed rules
and rate limiting does not skip it. Since the challenge is coming from SBFM's
"Definitely automated traffic" setting, the rule can match all 93 requests and
still let the challenge through, which is exactly what we are seeing. Ticking
that box should be the whole fix.

**2. The expression misses two of the three URLs that matter.**
`(http.request.uri.path contains "/studies/")` does not match `/sms-terms/` or
`/sms-privacy/`, and those two are the privacy policy and terms URLs filed in
our carrier registration. Something like:

    (starts_with(http.request.uri.path, "/studies/")) or
    (starts_with(http.request.uri.path, "/sms-terms")) or
    (starts_with(http.request.uri.path, "/sms-privacy"))

If it is easy, `/text-study/` as well — the terms page links to it, so a
reviewer following the trail lands there.

I can verify from outside the moment you have made the change; these are the
checks:

    curl -s -o /dev/null -w '%{http_code}\n' https://matter.childmind.org/studies/dash/opt-in/
    curl -s -o /dev/null -w '%{http_code}\n' https://matter.childmind.org/sms-terms/
    curl -s -o /dev/null -w '%{http_code}\n' https://matter.childmind.org/sms-privacy/

All three should return 200 rather than 403.

Thanks again — this has moved quickly.

Arno
