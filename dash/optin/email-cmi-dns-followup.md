# Reply to Child Mind Institute IT (David) — closer, but not from the address that matters

DNS is done. The Cloudflare rule now passes from a residential connection but
still challenges datacenter traffic, which is what a carrier's checker uses.
The path his expression matches is among the ones still blocked from there,
which points at the component list rather than the expression.

**Subject:** Re: DNS confirmed — Cloudflare passing from home, still blocked from datacenter IPs

Hi David,

**DNS is confirmed working, thank you.** The wildcard resolves at the
authoritative server and at public resolvers, grey cloud, answering with the
droplet address:

    $ dig +short @deb.ns.cloudflare.com dash.studies.childmind.org A
    167.71.248.46

Our certificate issued off the back of it and the hostname is serving. That
one is closed, and I appreciate you tracking down the internal-DNS-versus-
Cloudflare split.

**Cloudflare has moved, but not far enough.** From my home connection all four
paths now return 200 with the real page — I can see the disclosure text and
the phone number in the body, so it is genuinely serving rather than a
challenge page with a 200:

    /studies/dash/opt-in/    200
    /sms-terms/              200
    /sms-privacy/            200
    /                        200

From our droplet, 167.71.248.46, at the same moment:

    /studies/dash/opt-in/    403
    /sms-terms/              403
    /sms-privacy/            403

Same result with a browser user agent, so it is not user-agent sniffing. The
difference is the source address: residential passes, datacenter does not.

**That distinction is the whole problem for us.** A carrier reviewer's
automated checker runs from their own infrastructure, which is a datacenter
address like the droplet, not a home connection like mine. So from the point
of view of the people the exemption exists for, nothing has changed yet.

**And I think your own notes explain why.** You listed:

    Action:  Skip WAF features (including Super Bot Fight Mode)
    Components skipped:  All managed rules, All rate limiting rules

In the Skip action, Super Bot Fight Mode is a separate checkbox from managed
rules and rate limiting. The two components listed do not include it. Since
SBFM's "definitely automated traffic" setting is what classifies datacenter
traffic as a bot, the rule can match and still leave the challenge in place —
which is exactly what we are seeing. The clearest evidence is that
`/studies/dash/opt-in/`, the one path your expression definitely matches,
is still 403 from the droplet. The rule is matching; it is just not skipping
the thing doing the challenging.

Two asks, then:

1. **Add Super Bot Fight Mode to the components the rule skips.**
2. **Extend the expression to `/sms-terms` and `/sms-privacy`.** They pass from
   my connection but not from the droplet, and both are filed in our carrier
   registration alongside the opt-in page.

I can verify from both vantage points as soon as you have made the change —
the datacenter one is the test that counts:

    curl -s -o /dev/null -w '%{http_code}\n' https://matter.childmind.org/studies/dash/opt-in/
    curl -s -o /dev/null -w '%{http_code}\n' https://matter.childmind.org/sms-terms/
    curl -s -o /dev/null -w '%{http_code}\n' https://matter.childmind.org/sms-privacy/

Thanks again — this has moved quickly.

Arno
