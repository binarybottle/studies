# Reply to Child Mind Institute IT — the record is not resolving

**Subject:** Re: DNS record — not resolving yet, and one thing to check

Hi, and thank you for turning this around quickly.

It is not resolving yet, and I do not think it is propagation: the zone's own
authoritative nameservers do not have the record. Asking them directly, with
no caching in between:

    $ dig +norecurse @deb.ns.cloudflare.com dash.studies.childmind.org A
    status: NXDOMAIN

    $ dig +norecurse @deb.ns.cloudflare.com '*.studies.childmind.org' A
    status: NXDOMAIN

    $ dig +norecurse @deb.ns.cloudflare.com studies.childmind.org A
    status: NXDOMAIN

A control on the same server, in the same zone, answers normally:

    $ dig +norecurse @deb.ns.cloudflare.com matter.childmind.org A
    status: NOERROR    104.26.7.10

childmind.org is served by deb.ns.cloudflare.com and julian.ns.cloudflare.com,
and both return NXDOMAIN for all three names. Could you check that the record
landed in that Cloudflare zone specifically? The usual causes are a record
saved in a different zone or account, or a `studies.childmind.org` zone
created without NS records delegating it from `childmind.org`.

**One thing worth confirming while you are in there.** The control above shows
matter.childmind.org resolving to a Cloudflare address rather than to its
origin, so records in this zone are proxied by default. The wildcard needs to
be **DNS-only, grey cloud**, resolving to 167.71.248.46 itself. Proxied, two
things break: our server cannot complete the HTTP validation that issues its
TLS certificate, so the hostname would have no working certificate at all; and
the participant-facing site ends up behind the same bot challenge that
currently makes matter.childmind.org return 403 to anything that is not a
browser — which is the other request in my earlier email.

Once it is in, this confirms it from anywhere:

    dig +short dash.studies.childmind.org          # expect 167.71.248.46
    dig +short anything.studies.childmind.org      # same, proving the wildcard

Thanks again,

Arno Klein
Child Mind Institute
arno.klein@childmind.org
