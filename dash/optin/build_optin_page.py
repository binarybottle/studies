"""Generate the opt-in page published on the organization's website.

The page lives in the matter-website repository and is served at
``matter.childmind.org/studies/dash/opt-in``, but the disclosure it shows, the
number it advertises and the confirmation it promises are all defined in
``study_site.py``. Retyping them into a second repository is how they drift,
and a disclosure that differs from the one stored with each recorded consent
is worthless as evidence of consent. So the page is generated.

Regenerate whenever the disclosure, the number, or the contact address
changes, writing straight into the website checkout::

    $ python dash/optin/build_optin_page.py ~/Software/matter-website/opt-in.html
    wrote /Users/you/Software/matter-website/opt-in.html

then commit and push that repository. With no argument it writes
``opt-in.html`` beside this script, for review before copying.

The output is a Jekyll page: front matter, then body markup that the site's
``page`` layout wraps. It follows the conventions of the neighbouring
``text-study.html`` rather than carrying its own document shell.
"""

from __future__ import annotations

import html
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import study_site as site  # noqa: E402

TEMPLATE = """---
layout: page
contact: "{email_display}"
title: "{program} - opt in"
permalink: /studies/dash/opt-in/
redirect_from:
  - /opt-in/
---

<!--
  GENERATED FILE - do not edit here.
  Regenerate from the study repository:
    python dash/optin/build_optin_page.py ~/Software/matter-website/opt-in.html

  The form posts to {api}, which is a different origin. That endpoint
  allows exactly one origin: {origin}. If this page moves to another
  host, set OPTIN_PAGE_ORIGIN in the study site's .env to match, or the
  browser will block every submission.
-->

<h1>{program}</h1>
<p>A messaging program of {lab}. {org} is a nonprofit children's mental health
organization.</p>

<h2>Messages in this program come from</h2>
<p style="font-size:1.5em; font-weight:bold; margin:0.5em 0;">
{number}</p>
<p>This number is published here for anyone to see, without agreeing to
anything first.</p>

<h2>Opt in to receive messages</h2>
<form id="optin">
  <p>
    <label for="phone">Your mobile number</label><br>
    <input type="tel" id="phone" name="phone" autocomplete="tel"
           placeholder="(555) 123-4567" required
           style="font-size:1em; padding:0.5em; width:100%; max-width:18em;">
  </p>

  <p style="display:flex; gap:0.6em; align-items:flex-start;">
    <input type="checkbox" id="consent" name="consent" value="yes"
           style="margin-top:0.35em;">
    <label for="consent">{disclosure}</label>
  </p>

  <p><button type="submit"
             style="font-size:1em; padding:0.6em 1.2em;">Opt in</button></p>
  <p id="result" role="status" aria-live="polite" style="font-weight:bold;"></p>
</form>

<p>The box above is not ticked for you, and nothing is sent unless you tick it.
When you opt in we send one confirmation text. The interview itself begins when
you text {number} yourself. Opting in is not required to read this page, and
consenting to receive text messages is not a condition of any purchase or of
taking part in any other {org} activity.</p>

<h2>What the program is</h2>
<p>{org} is testing an automated text-message interviewer. This is a pilot test
of the software rather than a research study: its purpose is to confirm that
the system works reliably before any research data is collected. It is
preparation for a research study that has not yet begun, and for which {org}
will apply for review by an Institutional Review Board.</p>
<p>Testers are recruited through the Prolific research platform. Each tester is
given a short written persona describing a fictional parent and a fictional
child, and answers a standardized mental health screening questionnaire in
character as that fictional parent. No tester is asked about their own child,
their own family, or their own mental health.</p>

<h2>Messaging terms</h2>
<ul>
  <li>Program: a standardized questionnaire conducted by an automated
      interviewer. No marketing or promotional messages are ever sent from
      this number.</li>
  <li>Message frequency varies: 100 to 200 messages in a single session of
      {duration}.</li>
  <li>Message and data rates may apply. We do not charge for
      participation.</li>
  <li>Reply STOP at any time to opt out. Reply HELP for help.</li>
  <li>Phone numbers are used only to conduct the conversation. They are not
      sold, rented, or shared with third parties, and are not used for
      marketing.</li>
  <li>Carriers are not liable for delayed or undelivered messages.</li>
</ul>

<h2>Your phone number</h2>
<p>Your number is used to send the confirmation message and is then converted
to an irreversible cryptographic hash; the number itself is not kept. To
request deletion of your records, email {email_display}.</p>

<p class="text-muted">Questions: {email_display} &middot;
<a href="/sms-privacy/">SMS privacy notice</a> &middot;
<a href="/sms-terms/">SMS terms and conditions</a> &middot;
<a href="https://childmind.org/privacy/">Organization privacy policy</a> &middot;
<a href="https://childmind.org/terms/">Organization terms of use</a></p>

<script>
document.getElementById("optin").addEventListener("submit", async (event) => {{
  event.preventDefault();
  const result = document.getElementById("result");
  result.textContent = "Sending...";
  try {{
    const response = await fetch("{api}", {{
      method: "POST",
      headers: {{ "content-type": "application/json" }},
      body: JSON.stringify({{
        phone: document.getElementById("phone").value,
        consent: document.getElementById("consent").checked,
        pid: new URLSearchParams(location.search).get("pid")
      }})
    }});
    const body = await response.json();
    result.textContent = body.ok ? body.message : body.error;
  }} catch (error) {{
    result.textContent =
      "Something went wrong. Please email {email_display} and we will help.";
  }}
}});
</script>
"""


def build() -> str:
    """Render the page from the study site's own constants.

    Returns:
        The complete Jekyll page.
    """
    return TEMPLATE.format(
        program=html.escape(site.PROGRAM_NAME),
        lab=html.escape(site.LAB_NAME),
        org=html.escape(site.ORG_NAME),
        number=html.escape(site.STUDY_SMS_NUMBER),
        duration=html.escape(site.DURATION_TEXT),
        disclosure=html.escape(site.OPTIN_DISCLOSURE),
        # The site writes addresses this way to keep them out of scrapers.
        email_display=html.escape(site.CONTACT_EMAIL.replace("@", " [at] ")),
        origin=site.OPTIN_PAGE_ORIGIN,
        api=site.OPTIN_API_URL,
    )


if __name__ == "__main__":
    if len(sys.argv) > 1:
        out = pathlib.Path(sys.argv[1]).expanduser()
    else:
        out = pathlib.Path(__file__).with_name("opt-in.html")
    out.write_text(build(), encoding="utf-8")
    print(f"wrote {out}")
