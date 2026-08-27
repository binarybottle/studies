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

try:
    import study_site as site  # noqa: E402
except ModuleNotFoundError as error:  # pragma: no cover - operator guidance
    raise SystemExit(
        f"Cannot import the study site ({error.name} is missing).\n"
        "\n"
        "This script runs on your own machine, not on the droplet. The server\n"
        "installs the application's dependencies inside the container, and it\n"
        "has no checkout of the website repository to write the page into.\n"
        "\n"
        "If the prompt says arno@ubuntu-..., type exit first, then:\n"
        "    cd ~/Software/studies\n"
        "    python3 dash/optin/build_optin_page.py \\\n"
        "        ~/Software/matter-website/opt-in.html"
    ) from error

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

  The form posts cross-origin to the study host. That endpoint allows
  exactly one origin: {origin}. If this page moves to another host, set
  OPTIN_PAGE_ORIGIN in the study site's .env to match, or the browser
  will block every submission.
-->

<h1>{program}</h1>
<p>{org} is a nonprofit children's mental health organization. This page is
where participants in our research studies opt in to receive text messages
from us.</p>

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

  <p>Privacy: <a href="{sms_privacy}">{sms_privacy}</a><br>
  Terms: <a href="{sms_terms}">{sms_terms}</a></p>

  <p><button type="submit"
             style="font-size:1em; padding:0.6em 1.2em;">Opt in</button></p>
  <p id="result" role="status" aria-live="polite" style="font-weight:bold;"></p>
</form>

<p>The box above is not ticked for you, and nothing is sent unless you tick it.
When you opt in we send one confirmation text. The conversation itself begins
when you text {number} yourself.</p>

<h2>Text messages are optional</h2>
<p><strong>Consenting to receive text messages is not a condition of any
purchase, of taking part in our research studies, of completing one, or of
being paid for one.</strong> Every study in this program is also offered in a
web browser. A participant who never opts in to text messages takes part,
completes the study, and receives identical compensation. Opting in is not
required to read this page.</p>

<h2>What the program is</h2>
<p>An automated interviewer conducts a standardized questionnaire by text
message. Messages consist of questionnaire items and replies to what you send.
No marketing or promotional messages are ever sent from this number.</p>
<p>The current program is a pilot test of that messaging system, run in
preparation for a research study that has not yet begun and for which {org}
will apply for review by an Institutional Review Board. Each participant is
given a short written persona describing a fictional parent and child, and
answers the questionnaire in character. No participant is asked about their
own child or their own mental health.</p>

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
  <li>Opting in is optional: it is not a condition of taking part in any
      study, of completing one, or of being paid. The same study is offered
      in a web browser.</li>
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
<a href="{sms_privacy}">SMS privacy notice</a> &middot;
<a href="{sms_terms}">SMS terms and conditions</a> &middot;
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
        org=html.escape(site.ORG_NAME),
        number=html.escape(site.STUDY_SMS_NUMBER),
        sms_privacy=site.SMS_PRIVACY_URL,
        sms_terms=site.SMS_TERMS_URL,
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
