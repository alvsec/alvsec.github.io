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
