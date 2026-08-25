# Follow-up to Child Mind Institute IT

Short, and deliberately so: the email already sent covers the DNS record and
the grey-cloud requirement. This adds only what was learned afterwards. Send
it as a reply on the same thread.

**Subject:** Re: DNS and Cloudflare — two more data points

Two things I found after writing, both of which narrow it down.

**The challenge fires from the droplet too.** You suggested testing from
167.71.248.46, so I did, over SSH:

    /studies/dash/opt-in/    403
    /sms-terms/              403
    /                        403

Same 403 as from a home connection. So this is not our network and not an
address that could be allowlisted around — whatever rule was added does not
appear to be matching these paths at all. If it helps locate it in the
security log, a blocked request from a moment ago is `cf-ray a30c71a03d66ae12-EWR`.

**It is not only the opt-in page.** Every path we depend on is challenged:

    /studies/dash/opt-in/    403  cf-mitigated: challenge
    /sms-terms/              403  cf-mitigated: challenge
    /sms-privacy/            403  cf-mitigated: challenge
    /                        403  cf-mitigated: challenge

That matters more than it might look. `matter.childmind.org/sms-privacy/` and
`/sms-terms/` are the two URLs filed in our carrier registration, which is
under review right now, and the opt-in page is cited in the consent field. All
three answer 403 to anything that is not a browser while a reviewer may be
checking them.

**And one thing you can take off your list.** I checked the certificate from
outside CMI: matter.childmind.org presents `CN=childmind.org` with a
`*.childmind.org` SAN, issued by Google Trust Services, valid into October,
and the chain verifies with no override. No GitHub-domain certificate reaches
visitors and there is no browser warning we can reproduce. Cloudflare is
already proxying the site, which is what makes the managed challenge possible
in the first place, so the reverse proxy in your note is in place rather than
missing. I would rather leave it untouched while the carrier review is open.

Thanks,

Arno Klein
Child Mind Institute
arno.klein@childmind.org
