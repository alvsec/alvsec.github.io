---
title: "Services"
lead: "Audits, penetration testing and hardening for small businesses. No fixed packages and no shop window pricing, because the scope depends on what you actually have running."
description: "Security audits, penetration testing and hardening for small businesses and local shops. A two front methodology, with an executive report and a CVSS scored technical report."
---

## Security audit for small businesses

The most complete engagement, and the natural starting point if you have never had a security review. It combines real offensive testing with a defensive configuration review, because each one finds things the other cannot.

### A methodology on two fronts

**Offensive, black box.** I start with no prior information about your infrastructure and simulate specific attacker positions rather than generic ones: someone connected to the guest WiFi, an office machine that has been compromised, or someone on the internet who can only see what you expose. From each of those positions I get as far as I can and document the exact path.

**Defensive, review based.** With access to the systems I review the configuration from the inside out: permissions and access control, password policy, the state of your backups and whether they can genuinely be restored, missing updates, network segmentation and exposed services.

Crossing the two fronts is what makes the result useful. The offensive side proves a weakness is genuinely exploitable rather than theoretical; the defensive side explains why it exists and what else is configured just as badly but has not blown up yet.

### What it includes

- An opening meeting to agree scope, systems in and out, and the testing window.
- Reconnaissance and mapping of what you expose, inside and out.
- Controlled exploitation of the weaknesses found, as far as the agreed scope allows.
- A configuration review of network, systems, access control and backups.
- A closing meeting to walk through the findings and answer questions.

### What you get

- **Executive report.** Written for whoever makes the decisions and is not technical. What the risks are, what could realistically happen, what it costs to fix, and where to start.
- **Technical report.** Every finding with its description, reproduction steps, evidence, CVSS score and recommended fix.

<div class="audience"><strong>Who it is for:</strong> small businesses, local shops and small offices that depend on their systems to work and have never checked whether those systems hold up.</div>

## Penetration test

Narrower than a full audit. Here the goal is not to review everything, but to answer one specific question: how far can someone get if they try.

### Typical scope

- **Internal network.** Lateral movement, privilege escalation and, where there is a Windows domain, everything reachable against Active Directory from an unprivileged account.
- **WiFi.** Whether the guest network is genuinely separated from the working network, how strong the authentication is, and what can be reached from a guest position.
- **External perimeter.** What you look like from the internet: published services, reachable admin panels, default credentials and information leaks.

<div class="note">
<p><strong>Always under prior written authorisation.</strong> Before a single test is launched we sign a document setting out the scope, the systems included and excluded, the time window and the contact details to stop the test at any moment. Without that signed document, nothing starts. It is not a formality, it is what separates a penetration test from a crime.</p>
</div>

<div class="audience"><strong>Who it is for:</strong> businesses with their own infrastructure, a Windows domain or several sites, that already have a sense of their risks and want it verified.</div>

## Maintenance and hardening for small businesses

Not everyone needs an audit. Sometimes what you need is for someone to leave the systems properly configured and explain how to keep them that way. This is configuration work rather than audit work, and it is usually the logical next step after one.

- **Networks.** Segmentation between the working network, the guest network and the devices that should not be talking to anyone, such as cameras, point of sale terminals or screens.
- **Backups.** That they exist, that they are out of reach of a ransomware encryption, and above all that someone has actually tested restoring them.
- **Access control.** One user per person, least privilege, a clear out of accounts belonging to people who left, and a second factor wherever it can be used.
- **WiFi.** Proper authentication, a guest network that is genuinely isolated, and passwords that have not been written on a note by the counter for the last three years.

<div class="audience"><strong>Who it is for:</strong> local shops, hospitality, clinics and small offices with no technical staff, running their own equipment as best they can.</div>

## Pricing

There are no published rates because scope drives everything: reviewing an office with five machines and a router is not the same job as three sites with a Windows domain and their own servers. Write to me describing what you have and I will send a fixed quote, with no commitment, before anything starts.
