---
title: "Contacto"
lead: "La forma más rápida es un correo. Respondo yo, no hay formulario que vaya a un buzón que nadie mira."
description: "Contacta con Domain Security. Auditorías de seguridad y test de intrusión para pymes. Escribe un correo y respondo personalmente."
---

{{< contact-links >}}

## Qué contarme

No hace falta que sepas lo que necesitas, para eso estoy yo. Con esto me hago una idea bastante buena en el primer correo:

- A qué se dedica el negocio y cuánta gente trabaja con equipos informáticos.
- Qué tienes montado, aunque sea a grandes rasgos: si hay servidores propios, dominio Windows, varias sedes, TPV, cámaras, WiFi de invitados.
- Qué te preocupa en concreto, o si es más bien una revisión general porque nunca se ha hecho.
- Si hay alguna fecha o limitación, por ejemplo que no se pueda tocar nada en temporada alta.

Respondo en un par de días laborables. Si veo que lo que necesitas no es lo que yo hago, te lo digo y, si conozco a alguien más adecuado, te lo indico.

## Antes de contratar nada

Cualquier prueba de intrusión se ejecuta siempre bajo **autorización previa por escrito**, con el alcance cerrado antes de empezar. Puedes leer cómo trabajo en la [página de servicios]({{< relref "/services" >}}) y revisar mi trabajo publicado en el [portfolio]({{< relref "/portfolio" >}}).

<!--
  FORMULARIO DE CONTACTO, PENDIENTE Y NO IMPLEMENTADO.

  Si algún día se quiere un formulario en lugar del mailto, el sitio se despliega
  en Cloudflare Workers con static assets, así que el enganche natural es un
  script de Worker por delante de los archivos estáticos, sin backend propio ni
  servicios de terceros:

    1. Crear src/index.js y declararlo en wrangler.toml con
       main = "./src/index.js". El Worker atiende POST /api/contact y, para
       cualquier otra ruta, delega en los archivos con env.ASSETS.fetch(request).
    2. En ese handler: validar los campos, comprobar un token de Turnstile
       (el captcha de Cloudflare, que no usa cookies de terceros) y reenviar el
       mensaje por la API de un proveedor de correo, con la clave guardada como
       secreto mediante "npx wrangler secret put".
    3. Sustituir el bloque contact-links de arriba por un <form method="post"
       action="/api/contact">. Ojo: en GitHub Pages esa ruta no existe, así que
       hay que apuntar con action absoluta a domainsecurity.agency, o bien
       ocultar el formulario cuando el sitio no se sirva desde ese dominio.
    4. IMPORTANTE: actualizar /legal/ antes de publicarlo. Un formulario recoge
       datos personales de forma directa y obliga a añadir la base legal, la
       casilla de consentimiento y el plazo de conservación.

  Mientras tanto, el mailto no recoge ningún dato ni requiere JavaScript.
-->
