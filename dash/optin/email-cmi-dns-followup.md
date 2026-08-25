# Reply to Child Mind Institute IT — neither change is visible yet

**Subject:** Re: DNS and Cloudflare — neither is visible from outside, and the certificate is fine

Hi, and thank you for turning these around.

Neither change is reaching us yet. Details below, including one check run from
the droplet itself, since that is where you suggested testing.

**DNS: the record is not in the published zone**

Not a caching problem. Both the authoritative server and a public resolver
return nothing:

    $ dig +short @deb.ns.cloudflare.com dash.studies.childmind.org A
    (no answer)

    $ dig +short @1.1.1.1 dash.studies.childmind.org A
    (no answer)

    $ dig dash.studies.childmind.org
    status: NXDOMAIN

A control in the same zone on the same server answers normally, so the zone
itself is fine:

    $ dig +short @deb.ns.cloudflare.com matter.childmind.org A
    104.26.7.10

Could you confirm the record is saved in the childmind.org Cloudflare zone as
`*.studies` A `167.71.248.46`, **DNS-only, grey cloud**? It has to be
unproxied: the droplet obtains its own TLS certificates by HTTP validation,
and a proxied record prevents that, leaving the hostname with no working
certificate at all.

**Cloudflare: the challenge still fires, including from the droplet**

From a residential connection every path we depend on returns 403 with
`cf-mitigated: challenge`:

    /studies/dash/opt-in/    403  challenge
    /sms-terms/              403  challenge
    /sms-privacy/            403  challenge
    /                        403  challenge

And the same three from the droplet you suggested testing from
(167.71.248.46), over SSH:

    /studies/dash/opt-in/    403
    /sms-terms/              403
    /                        403

So this is not our network, and not an address you could allowlist your way
around — the rule does not appear to be matching these paths at all. Could you
share the rule expression? A recent blocked request is `cf-ray a30c6d230c962142-EWR`,
which should locate it in the security log.

What we need is a match on **URI path** — starting with `/studies/`,
`/sms-terms/`, `/sms-privacy/` — with **no source-IP condition**, since the
carrier's reviewer fetches from an address nobody can predict.

This one is time-sensitive in a way the DNS record is not. Our A2P campaign is
under review now, and `matter.childmind.org/sms-privacy/` and
`/sms-terms/` are the two URLs filed in the application, with
`/studies/dash/opt-in/` cited in the consent field. All three currently
return 403 to anything that is not a browser.

**Certificate: nothing to change, please leave it as it is**

The certificate served for matter.childmind.org is valid from outside CMI:

    subject  CN=childmind.org
    SAN      childmind.org, *.childmind.org
    issuer   Google Trust Services WE1
    valid    12 Jul 2026 - 10 Oct 2026

`*.childmind.org` covers matter.childmind.org, and the chain verifies without
overrides — `curl` completes the handshake with no certificate error and no
`-k`. There is no GitHub-domain certificate being presented to visitors and no
browser warning that we can reproduce.

Cloudflare is also already proxying the site — that is what makes the managed
challenge possible in the first place — so the reverse proxy in your note is
in place rather than something to add. I would rather not change anything
there while a carrier review is open.

Thanks again,

Arno Klein
Child Mind Institute
arno.klein@childmind.org
