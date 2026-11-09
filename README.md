# Empleo en Tragsa y Tragsatec

[![Tests](https://github.com/alertapublica/empleo-tragsa/actions/workflows/ci.yml/badge.svg)](https://github.com/alertapublica/empleo-tragsa/actions/workflows/ci.yml)
[![Publicar](https://github.com/alertapublica/empleo-tragsa/actions/workflows/publicar.yml/badge.svg)](https://github.com/alertapublica/empleo-tragsa/actions/workflows/publicar.yml)
[![Código: EUPL 1.2](https://img.shields.io/badge/código-EUPL%201.2-blue)](LICENSE)

Web independiente y **no oficial** con las ofertas de empleo del Grupo Tragsa (Tragsa y Tragsatec). Ofrece un buscador, páginas por comunidad, provincia y área, las tasas de reposición con todos sus comunicados y avisos por Telegram, correo y RSS. La web de Tragsa no permite suscribirse a sus ofertas.

> No pertenece a Tragsa, a Tragsatec ni al Grupo Tragsa. Las ofertas oficiales están en la [web de empleo de Tragsa](https://www.tragsa.es/es/equipo-humano/unete-a-nuestro-equipo/Paginas/default.aspx).

## Cómo funciona

```text
alertapublica.es/api/ (ofertas, procesos, listas)  →  python -m web  →  _site/  →  GitHub Pages
```

- **Los datos no se calculan aquí.** Salen de la [API de Empleo en Empresas Públicas](https://alertapublica.es/datos/) ([repo](https://github.com/alertapublica/empleo-publico-abierto)), que ya trae los códigos INE, las áreas y la mención del teletrabajo. Se filtra `organismo == "tragsa"` y se genera HTML estático, para que los buscadores lo indexen.
- **Sin fichas propias.** El título de cada oferta abre su ficha en tragsa.es e «Inscribirse» lleva al Portal de Empleo de Tragsa. Así no se duplica contenido.
- **Páginas que aparecen y desaparecen.** Cada comunidad, provincia y área tiene página solo mientras haya ofertas abiertas. Al vaciarse, la página desaparece (404) y sale del `sitemap.xml`.
- **Avisos.** No se gestionan aquí. Se enlaza al portal: `alertapublica.es/avisos/?organismo=tragsa` para el correo y `t.me/<bot>?start=tragsa` para Telegram, los dos con Tragsa ya elegido.
- **Sin dependencias.** Solo la biblioteca estándar de Python, sin cookies, sin analítica y sin recursos externos (CSP estricta).

### Páginas

| Ruta | Contenido |
|---|---|
| `/` | Todas las ofertas abiertas, con buscador, filtros y enlaces por comunidad, provincia y área |
| `/tragsa/`, `/tragsatec/` | Ofertas de cada empresa (las de «Grupo Tragsa» salen en las dos) |
| `/comunidad/<slug>/`, `/provincia/<slug>/`, `/area/<slug>/` | Solo mientras tengan ofertas abiertas |
| `/tasas-de-reposicion/` y una página por proceso | Situación, plazo y comunicados por fecha |
| `/como-funciona/` | Guía para presentar una candidatura, con enlaces a las fuentes ([`web/textos/como-funciona.html`](web/textos/como-funciona.html)) |
| `/avisos/` | Telegram, correo y RSS del portal |
| `/aviso-legal/` | Web no oficial, reclamaciones, titular y privacidad ([`web/textos/aviso-legal.html`](web/textos/aviso-legal.html)) |
| `sitemap.xml`, `robots.txt`, `404.html`, `estado.json` | `estado.json` guarda la hora `generado` de la API publicada |

## Cuándo se publica

[`publicar.yml`](.github/workflows/publicar.yml) se lanza en tres casos:

1. **Aviso del portal.** Al terminar de publicar, `actualizar.yml` de empleo-publico-abierto lanza este workflow con la hora `generado` de su API. El generador espera, como mucho 10 minutos, a que la API sirva esa versión y no la de la caché.
2. **Cron de respaldo**, cada 3 horas.
3. **`push` a `main`**: al cambiar el código se publica siempre.

En los dos primeros casos no se vuelve a publicar si la web publicada ya tiene el mismo `generado` y es del mismo día. La fecha cuenta porque textos como «Finaliza hoy» dependen de ella.

## Puesta en marcha

1. **Pages:** en *Settings → Pages*, la fuente tiene que ser «GitHub Actions».
2. **Dominio propio**, cuando exista:
   - el dominio en *Settings → Pages → Custom domain*, con su DNS en Cloudflare y sin proxy. Para un dominio raíz, los registros `A` de GitHub Pages (185.199.108.153 a 185.199.111.153). Para un subdominio, un `CNAME` a `alertapublica.github.io`;
   - activar «Enforce HTTPS»;
   - la variable del repo `BASE_URL` con `https://<dominio>/`, que usan las direcciones canónicas, el sitemap y `robots.txt`.
3. **Aviso desde el portal:**
   - crear un token de grano fino con acceso **solo** a `alertapublica/empleo-tragsa` y el permiso «Actions: lectura y escritura»;
   - guardarlo como secreto `TOKEN_WEB_TRAGSA` en `alertapublica/empleo-publico-abierto`.

   Sin él, la web solo se actualiza con el cron.
4. **Buzón de reclamaciones:** de momento es el correo del titular (`CONTACTO` en [`web/generar.py`](web/generar.py)). Con el dominio se puede crear `reclamaciones@<dominio>` con el reenvío de correo de Cloudflare y cambiarlo ahí.

Otras variables opcionales del generador: `API_URL` (otra API o una carpeta local) y `TELEGRAM_BOT` (usuario del bot, sin @).

## Desarrollo

Necesita Python 3.13 y nada más.

```bash
python -m unittest                                   # tests, con los datos de tests/fixtures
python -m web --api tests/fixtures --salida _site    # genera la web con los datos de ejemplo
python -m web                                        # genera la web con la API real
python -m http.server -d _site                       # y se ve en http://localhost:8000/
```

| Fichero | Qué hay |
|---|---|
| [`web/datos.py`](web/datos.py) | Lectura de la API, comprobación de las claves que se usan y filtro de Tragsa |
| [`web/generar.py`](web/generar.py) | Páginas, sitemap y `estado.json`; nombre de la web, enlaces a Tragsa y titular |
| [`web/textos/`](web/textos/) | Textos largos en HTML, editables sin tocar el código (`{{raiz}}`, `{{portal}}`… se sustituyen al generar) |
| [`web/assets/`](web/assets/) | Estilos (paleta propia, claro y oscuro) y `filtros.js` (mejora progresiva: sin JavaScript se ve la lista completa) |
| [`tests/`](tests/) | Pruebas: enlaces internos, sitemap, accesibilidad básica, contraste, plazos y API |

Si la API cambia de forma (otra `version` o una clave que falta), la generación falla y no se publica nada. Las claves que se usan están en `CLAVES_*` de [`web/datos.py`](web/datos.py).

## Licencia

- **Código:** [Licencia Pública de la Unión Europea (EUPL) 1.2](LICENSE).
- **Datos:** de [Empleo en Empresas Públicas](https://alertapublica.es/datos/), con licencia [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.es).
- **Textos, documentos y enlaces de cada oferta y comunicado:** pertenecen al Grupo Tragsa, que es la fuente oficial y la que prevalece. «Tragsa» y «Tragsatec» son marcas de sus titulares; aquí solo se usan para identificar las ofertas.
