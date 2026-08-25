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

Four things that would help, none of which I asked last time:

1. **Which Cloudflare feature is issuing the challenge — a WAF custom rule,
   Bot Fight Mode, or Super Bot Fight Mode?** This may be the whole answer. As
   I understand it, a custom rule with a Skip action can bypass Super Bot
   Fight Mode but *not* plain Bot Fight Mode, which is a zone-level toggle
   that runs on every request regardless of custom rules. If Bot Fight Mode is
   what is on, no path-based exemption can work and it has to be switched off
   for the zone.

2. **Is the rule saved and deployed, rather than sitting as a draft?** Worth
   thirty seconds to rule out.

3. **Could you paste the DNS record exactly as it appears** — name, type,
   content, proxy status? If there is a typo in the name field, that would
   explain the NXDOMAIN better than anything I can see from outside.

4. **When do you think you can get to this?** Not chasing — I ask because our
   carrier registration is being reviewed now, and if the challenge cannot be
   lifted quickly I would rather know, so we can decide whether to withdraw
   and resubmit later rather than have it rejected a third time.

If a path exemption turns out not to be possible, would setting the challenge
to log-only for this zone until the review completes be an option?

Thank you again for the quick turnaround on this.

Arno
