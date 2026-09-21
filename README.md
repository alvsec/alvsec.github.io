# Domain Security

Sitio de Domain Security, la consultoría de seguridad de Álvaro Irún (alvsec),
más el blog de writeups de pentesting. Hugo sin tema externo (layouts propios en
`layouts/`), bilingüe EN/ES.

## Despliegue en dos dominios

El mismo repositorio se publica en dos sitios:

- **GitHub Pages**, en `alvsec.github.io`, vía GitHub Actions en cada push a `main`.
  El workflow sobreescribe `baseURL` con la URL de Pages.
- **Cloudflare Pages**, en `domainsecurity.agency`. Build command recomendado:
  `hugo --minify --baseURL https://domainsecurity.agency/`

La etiqueta `rel="canonical"` y los `hreflang` NO se construyen desde `baseURL`,
sino desde `params.canonicalBase` en `hugo.toml`, así que ambas copias declaran
`domainsecurity.agency` como versión canónica y no compiten entre sí como
contenido duplicado. Si cambias de dominio, ese es el único sitio que tocar.

## Estructura

    content/{en,es}/         una carpeta por idioma
      _index.md              copy de la portada, en el front matter
      services.md            servicios
      about.md               sobre mí
      portfolio.md           portfolio técnico
      contact.md             contacto
      legal.md               aviso legal y privacidad
      posts/                 writeups del blog
    layouts/
      index.html             portada
      partials/head-seo.html SEO, Open Graph y canonical
      shortcodes/            recent-posts, contact-links
    static/css/style.css     hoja de estilos única
    static/img/              favicon e imágenes de vista previa Open Graph
    static/reports/          informes de pentest en PDF

**No uses `url:` en el front matter de una página bilingüe.** Una `url` absoluta
se salta el prefijo de idioma y hace que la versión en español sobreescriba a la
inglesa en la misma ruta. Deja que Hugo derive la ruta del nombre del archivo.

Para los enlaces internos entre páginas, usa `{{< relref "/pagina" >}}` en lugar
de rutas absolutas, que resuelve al idioma correcto automáticamente.

## Desarrollo

    hugo server

El CI usa Hugo **0.140.2**. Las claves `languageCode` y `languageName` de
`hugo.toml` están deprecadas en Hugo 0.158 o superior, pero sus sustitutas
(`locale` y `label`) no existen en 0.140.2, así que se mantienen a propósito.
Localmente verás avisos de deprecación; no son un error.

## Ritmo del blog

Objetivo: ~2 posts al mes. Un writeup por cada máquina HTB **retirada** que
resuelva, y un post por cada cosa relevante que monte en el laboratorio.

## La página /webs/

Página aparte para vender páginas web a negocios locales. Vive en el mismo
repositorio pero está **deliberadamente aislada** del resto del sitio: no sale
en ningún menú, no tiene la cabecera de Domain Security y solo está en
castellano. Quien llega por un enlace de WhatsApp no debe aterrizar en una
consultora de ciberseguridad.

    content/es/webs.md          todos los textos, en el front matter
    layouts/webs/baseof.html    armazón propio, por eso no hereda nada
    layouts/webs/single.html    estructura de la página
    static/css/webs.css         hoja propia, no carga style.css
    static/img/webs/            capturas en WebP y la imagen Open Graph

**No la muevas a `/portfolio/`**, que ya es el portfolio técnico de
ciberseguridad y está en el menú de los dos idiomas.

### Cambiar los textos

Todo está en el front matter de `content/es/webs.md`, en bloques con nombre
(`hero`, `incluye`, `trabajos`, `precios`, `proceso`, `cierre`, `pie`). Se
editan ahí y no hace falta tocar HTML. El número de WhatsApp y el correo están
arriba del todo, en `whatsapp` y `email`.

### Añadir un trabajo nuevo

1. Guarda la captura en `static/img/webs/` en **WebP a 1280x800**. Si tienes
   un PNG, conviértelo con `python3 -c "from PIL import Image;
   Image.open('x.png').convert('RGB').save('static/img/webs/x.webp','WEBP',quality=82)"`.
2. Añade un bloque a `trabajos.items` en `content/es/webs.md` copiando uno
   existente. Los campos son: `nombre`, `url` (vacío si no hay web pública),
   `enlace_texto`, `etiqueta`, `tipo` (`cliente` o `propio`, controla el color
   de la etiqueta), `imagen`, `alt`, `hice` y `sirve`.
3. El `alt` es obligatorio: describe lo que se ve, no repitas el nombre.

La primera imagen de la lista se carga de inmediato y el resto en diferido.
Si cambias el orden, no hace falta tocar nada: el layout lo resuelve solo.

### Cambiar el tamaño de las capturas

Si usas una proporción distinta a 1280x800, actualiza los atributos `width` y
`height` en `layouts/webs/single.html` y el `aspect-ratio` de `.trabajo img`
en `static/css/webs.css`. Deben coincidir, o la página dará saltos al cargar.

### Colores y tipografía

`static/css/webs.css` repite los mismos valores que `static/css/style.css` en
lugar de importarlos, para cargar una sola hoja pequeña. **Si cambias la
paleta en uno, cámbiala también en el otro.**

### Desplegar

Igual que el resto del sitio: `git add -A`, `git commit` y `git push`. GitHub
Actions y Cloudflare compilan cada uno por su cuenta. No se sube nada a mano.
