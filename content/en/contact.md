---
title: "Contact"
lead: "The fastest way is an email. I answer it personally, there is no form feeding an inbox nobody reads."
description: "Get in touch with Domain Security. Security audits and penetration testing for small businesses. Send an email and I answer personally."
---

{{< contact-links >}}

## What to tell me

You do not need to know what you need, that is my job. This gives me a good picture from the first email:

- What the business does and how many people work with computers.
- What you have running, even roughly: your own servers, a Windows domain, several sites, point of sale, cameras, guest WiFi.
- What specifically worries you, or whether it is a general review because nobody has ever done one.
- Any dates or constraints, for example that nothing can be touched during peak season.

I reply within a couple of working days. If what you need is not what I do, I will say so, and if I know someone better suited I will point you to them.

## Before commissioning anything

Any intrusion testing is always carried out under **prior written authorisation**, with the scope agreed before anything starts. You can read how I work on the [services page]({{< relref "/services" >}}) and review my published work in the [portfolio]({{< relref "/portfolio" >}}).

<!--
  CONTACT FORM, PENDING AND NOT IMPLEMENTED.

  If a form is ever wanted instead of the mailto, the site deploys to Cloudflare
  Workers with static assets, so the natural hook is a Worker script sitting in
  front of the static files, with no backend of our own and no third party
  service:

    1. Create src/index.js and declare it in wrangler.toml with
       main = "./src/index.js". The Worker handles POST /api/contact and, for
       any other route, falls through to the files via env.ASSETS.fetch(request).
    2. In that handler: validate the fields, verify a Turnstile token
       (Cloudflare's captcha, which sets no third party cookies) and forward the
       message through a mail provider API, with the key stored as a secret
       using "npx wrangler secret put".
    3. Replace the contact-links block above with a <form method="post"
       action="/api/contact">. Note: that route does not exist on GitHub Pages,
       so either use an absolute action to domainsecurity.agency, or hide the
       form when the site is not served from that domain.
    4. IMPORTANT: update /legal/ before shipping it. A form collects personal
       data directly and requires adding the legal basis, a consent checkbox and
       a retention period.

  For now, the mailto collects no data and needs no JavaScript.
-->
