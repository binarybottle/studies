# Follow-up to Child Mind Institute IT (David)

A reply on the same thread. The email already sent covers the DNS record, the
grey-cloud requirement, the rule expression, and the certificate, so none of
that is repeated here. Two things only, both learned afterwards, and the first
answers the question that email ended on.

**Subject:** Re: DNS and Cloudflare — verified from outside CMI, still blocked

Hi David,

I asked in my last note whether the Cloudflare rule could be verified from a
non-CMI network. I have now done that, and it is still blocked.

From the droplet itself, 167.71.248.46, over SSH:

    /studies/dash/opt-in/    403
    /sms-terms/              403
    /                        403

Same result as from my home connection, so it is not our office network and
not an address that could be allowlisted around — the rule does not appear to
be matching these paths at all.

It is also not only the opt-in page. Every path is challenged:

    /studies/dash/opt-in/    403  cf-mitigated: challenge
    /sms-terms/              403  cf-mitigated: challenge
    /sms-privacy/            403  cf-mitigated: challenge
    /                        403  cf-mitigated: challenge

That last part is the reason I am following up so quickly rather than waiting.
`matter.childmind.org/sms-terms/` and `/sms-privacy/` are the two URLs filed
in our carrier registration, and that registration is under review right now.
A reviewer checking them today gets a 403. A blocked request against
/sms-terms/ from a moment ago is `cf-ray a30c77636dee6e2f-EWR`, if a second example
helps locate the rule.

Thank you again for the quick turnaround on this.

Arno
