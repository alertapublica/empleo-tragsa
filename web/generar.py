"""Genera la web estática con las ofertas y los procesos del Grupo Tragsa.

Todo sale de la API de Empleo en Empresas Públicas (ver datos.py). No hay fichas propias: el título de
cada oferta abre su ficha en tragsa.es. Las páginas de comunidad, provincia y área solo existen
mientras tengan ofertas abiertas; al vaciarse desaparecen (404) y salen del sitemap.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import unicodedata
from datetime import date, datetime, timezone
from html import escape as e
from pathlib import Path
from urllib.parse import quote
from urllib.parse import quote
from zoneinfo import ZoneInfo

from . import datos

AQUI = Path(__file__).parent
ASSETS = AQUI / "assets"
TEXTOS = AQUI / "textos"
MADRID = ZoneInfo("Europe/Madrid")

SITE_NAME = "Empleo en Tragsa y Tragsatec"
TAGLINE = "Buscador independiente de las ofertas de empleo del Grupo Tragsa (Tragsa y Tragsatec)"
NO_OFICIAL = "Web independiente y no oficial: no pertenece a Tragsa, a Tragsatec ni al Grupo Tragsa."
REPO = "https://github.com/alertapublica/empleo-tragsa"
PORTAL = "https://alertapublica.es/"
PORTAL_NOMBRE = "Empleo en Empresas Públicas"
# Mismo titular que el portal (LSSI art. 10).
TITULAR = "Voceiro - JJAA"
CONTACTO = "info@voceiro.eu"
DEFAULT_BASE_URL = "https://alertapublica.github.io/empleo-tragsa/"
DEFAULT_API = "https://alertapublica.es/api/"
DEFAULT_BOT = "empleo_aapp_bot"
# Web oficial de empleo del Grupo Tragsa y acceso a su Portal de Empleo (candidaturas).
TRAGSA_EMPLEO = "https://www.tragsa.es/es/equipo-humano/unete-a-nuestro-equipo/Paginas/default.aspx"
TRAGSA_PORTAL = "https://www.tragsa.es/_layouts/15/GrupoTragsa/portal-empleo-acceso.aspx"
CSP = "default-src 'none'; style-src 'self'; script-src 'self'; img-src 'self'; base-uri 'none'; form-action 'self'"

MONTHS = "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split()
WEEKDAYS = "lunes martes miércoles jueves viernes sábado domingo".split()
SOON_DAYS = 7
URGENT_DAYS = 3
# Las de «Grupo Tragsa» son de las dos empresas: salen en las dos páginas de empresa.
EMPRESAS = {
    "tragsa": ("Tragsa", "Empresa de Transformación Agraria, S.A., S.M.E., M.P."),
    "tragsatec": ("Tragsatec", "Tecnologías y Servicios Agrarios, S.A., S.M.E., M.P."),
}
GRUPO = "Grupo Tragsa"
SIN_COMUNIDAD = "otras"
SIN_AREA = "sin-area"
GENERIC_PLACES = ("Comunidad de", "Sede", "Varios", "Nacional")
NAV = [
    ("index", "", "Ofertas"),
    ("tragsa", "tragsa/", "Tragsa"),
    ("tragsatec", "tragsatec/", "Tragsatec"),
    ("tasas", "tasas-de-reposicion/", "Tasas de reposición"),
    ("como", "como-funciona/", "Cómo funciona"),
    ("avisos", "avisos/", "Avisos"),
]


# ---------------------------------------------------------------- utilidades de texto y fechas

def slug(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text)
    plain = "".join(c for c in plain if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "-", plain).strip("-")


def plain(text: str) -> str:
    """Sin tildes y en minúsculas, como lo compara filtros.js."""
    text = unicodedata.normalize("NFD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


INITIALS = re.compile(r"\b([a-zñ])\.([a-zñ])\.")


def humane_caps(text: str) -> str:
    """Los lectores de pantalla deletrean las mayúsculas sostenidas: las pasa a frase (como el portal)."""
    match = re.fullmatch(r"(.*?)(\s*\([^()]*\))?", text, re.S)
    body, code = match.group(1), match.group(2) or ""
    letters = [c for c in body if c.isalpha()]
    if not letters or sum(c.isupper() for c in letters) / len(letters) < 0.7:
        return text
    lowered = body.lower()
    for word in ("tragsatec", "tragsa"):
        lowered = lowered.replace(word, word.capitalize())
    lowered = INITIALS.sub(lambda m: f"{m.group(1).upper()}.{m.group(2).upper()}.", lowered)
    return lowered[0].upper() + lowered[1:] + code


def long_date(value: str | None, weekday: bool = False) -> str:
    if not value:
        return "sin indicar"
    day = date.fromisoformat(value[:10])
    text = f"{day.day} de {MONTHS[day.month - 1]} de {day.year}"
    return f"{WEEKDAYS[day.weekday()]}, {text}" if weekday else text


def time_tag(value: str | None, weekday: bool = False) -> str:
    if not value:
        return "sin indicar"
    return f'<time datetime="{e(value[:10])}">{e(long_date(value, weekday))}</time>'


def stamp(generado: str) -> str:
    """«9 de noviembre de 2026, a las 22:05» en hora de Madrid."""
    moment = datetime.fromisoformat(generado).astimezone(MADRID)
    return f"{long_date(moment.date().isoformat())}, a las {moment:%H:%M}"


def count(n: int, one: str, many: str) -> str:
    return f"1 {one}" if n == 1 else f"{n} {many}"


def seats(n: int | None) -> str:
    return "Plazas: no consta" if n is None else count(n, "plaza", "plazas")


def with_article(region: str) -> str:
    """«en la Comunidad de Madrid», «en el País Vasco», «en Andalucía»."""
    if region.startswith(("Comunidad ", "Comunitat ", "Región ", "Ciudad ")):
        return f"la {region}"
    if region.startswith("País "):
        return f"el {region}"
    return region


# ---------------------------------------------------------------- contexto común

class Sitio:
    """Datos ya leídos y nombres legibles de las listas de la API."""

    def __init__(self, data: dict, base_url: str, today: date, bot: str):
        self.base_url = base_url if base_url.endswith("/") else base_url + "/"
        self.today = today
        self.bot = bot
        self.generado = data["generado"]
        listas = data["listas"]
        self.comunidades = {c["ccaa"]: c["nombre"] for c in listas["comunidades"]}
        self.provincias = {p["provincia"]: (p["nombre"], p["ccaa"]) for p in listas["provincias"]}
        self.areas = {a["id"]: a["nombre"] for a in listas["areas"]}
        self.contratos = {t["id"]: t["nombre"] for t in listas["tipos_contrato"]}
        self.tipos_proceso = {t["id"]: t["nombre"] for t in listas["tipos_proceso"]}
        self.accesos = {t["id"]: t["nombre"] for t in listas["accesos"]}
        self.sistemas = {t["id"]: t["nombre"] for t in listas["sistemas"]}
        self.estados = {t["id"]: t["nombre"] for t in listas["estados_proceso"]}
        self.ofertas = sorted(
            (o for o in data["ofertas"] if o["estado"] == "abierta"),
            key=lambda o: (o.get("publicada") or o["detectada"][:10], o["id"]),
            reverse=True,
        )
        self.procesos = sorted(
            data["procesos"],
            key=lambda p: (p["estado"] == "abierto", max((c["fecha"] or "" for c in p["comunicados"]), default="")),
            reverse=True,
        )
        self.proceso_slug = unique_slugs(self.procesos)

    def provincia(self, code: str | None) -> str:
        return self.provincias[code][0] if code in self.provincias else ""


def unique_slugs(processes: list[dict]) -> dict[str, str]:
    """Ruta de cada proceso a partir de su nombre; si dos coinciden, se añade el id."""
    names = [slug(humane_caps(p["nombre"])) or p["id"] for p in processes]
    return {p["id"]: name if names.count(name) == 1 else f"{name}-{p['id']}" for p, name in zip(processes, names)}


# ---------------------------------------------------------------- plantilla

def radios(name: str, options: list[tuple[str, str]]) -> str:
    return "".join(
        f'<div class="opcion"><input type="radio" id="{name}-{value}" name="{name}" value="{value}">'
        f'<label for="{name}-{value}">{label}</label></div>'
        for value, label in options
    )


def color_row(key: str, label: str, contrast: bool = True) -> str:
    check = f'<output id="contraste-{key}" for="color-{key}"></output>' if contrast else ""
    return (f'<div class="color-fila"><input type="color" id="color-{key}" value="#000000">'
            f'<label for="color-{key}">{label}</label>{check}</div>')


# Mismo panel «Aa» que Empleo en Empresas Públicas (tema.js y ajustes.js son copias de los suyos).
SETTINGS_DIALOG = f"""<dialog id="ajustes" class="ajustes" aria-labelledby="ajustes-titulo">
<div class="aj-cab"><h2 id="ajustes-titulo">Apariencia</h2>
<button type="button" id="ajustes-cerrar">Cerrar</button></div>
<div class="aj-cuerpo">
<fieldset><legend>Tema</legend>
<div class="opciones">{radios("tema", [("auto", "Automático"), ("light", "Claro"), ("sepia", "Sepia"),
                                       ("dark", "Oscuro"), ("contrast", "Contraste alto"), ("custom", "Personalizado")])}</div>
<p class="aj-nota">La opción Automático aplica el tema configurado en su dispositivo.</p>
<div class="colores" id="colores" hidden>
{color_row("fondo", "Fondo", False)}{color_row("texto", "Texto")}{color_row("enlaces", "Enlaces")}{color_row("titulos", "Títulos")}
<p class="aj-nota">Seleccione cuatro colores; el resto se calcula de forma automática. Se indica si alguno no alcanza un contraste de 4,5:1 con el fondo.</p>
</div></fieldset>
<fieldset><legend>Letra</legend>
<div class="opciones">{radios("fuente", [("sans", "Sans"), ("serif", "Serif"), ("dyslexic", "Dislexia")])}</div>
</fieldset>
<fieldset><legend>Tamaño de letra</legend>
<div class="paso"><button type="button" id="fs-menos" aria-label="A menos: reducir el tamaño de letra">A−</button>
<output id="fs-val" for="fs-menos fs-mas"></output>
<button type="button" id="fs-mas" aria-label="A más: aumentar el tamaño de letra">A+</button></div>
<p class="aj-nota">Porcentaje sobre el tamaño de letra configurado en su navegador.</p>
</fieldset>
<fieldset><legend>Ancho del contenido</legend>
<div class="paso"><button type="button" id="ancho-menos" aria-label="Reducir el ancho del contenido">−</button>
<output id="ancho-val" for="ancho-menos ancho-mas"></output>
<button type="button" id="ancho-mas" aria-label="Aumentar el ancho del contenido">+</button></div>
</fieldset>
<fieldset><legend>Ayudas de lectura</legend>
<label class="casilla-ajuste"><input type="checkbox" name="extra" value="just"><span>Justificar el texto</span></label>
<label class="casilla-ajuste"><input type="checkbox" name="extra" value="bionic"><span>Negrita en el inicio de cada palabra<span>Algunos lectores de pantalla pueden leer peor el texto con esta opción.</span></span></label>
<label class="casilla-ajuste"><input type="checkbox" name="extra" value="focus"><span>Foco: atenuar las ofertas que no se están leyendo<span>Las ofertas atenuadas tienen menos contraste de forma intencionada.</span></span></label>
</fieldset>
<p class="aj-nota">Sus ajustes se guardan únicamente en este navegador y no se envían a ningún servidor.</p>
</div>
<div class="aj-pie"><button type="button" id="ajustes-reset">Restablecer apariencia</button></div>
</dialog>"""

SETTINGS_BUTTON = ('<button type="button" id="btn-aa" class="btn-cab" aria-haspopup="dialog" hidden>'
                   '<span class="aa" aria-hidden="true">Aa</span> <span class="aa-texto">Apariencia</span></button>')


def page(site: Sitio, title: str, body: str, path: str, current: str = "", description: str = TAGLINE,
         crumbs: list[tuple[str, str]] | None = None, here: str = "", root: str | None = None) -> str:
    """`path` es la ruta de la página («», «tragsa/», «provincia/sevilla/»); los enlaces son relativos.

    `crumbs` son los pasos de la ruta de migas antes de esta página, que se llama `here` (o `title`)."""
    if root is None:
        root = "../" * path.count("/")
    links = "".join(
        f'<li><a href="{(root + href) or "./"}"{" aria-current=\"page\"" if key == current else ""}>{label}</a></li>'
        for key, href, label in NAV
    )
    full_title = title if title == SITE_NAME else f"{title} · {SITE_NAME}"
    trail = ""
    if crumbs:
        items = "".join(f'<li><a href="{(root + href) or "./"}">{e(label)}</a></li>' for href, label in crumbs)
        trail = (f'<nav class="migas" aria-label="Ruta de navegación"><ol>{items}'
                 f'<li aria-current="page">{e(here or title)}</li></ol></nav>\n')
    # La 404 no tiene dirección propia: ni canonical ni índice.
    meta = (f'<meta name="robots" content="noindex">' if path.endswith(".html")
            else f'<link rel="canonical" href="{e(site.base_url + path)}">')
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{CSP}">
<title>{e(full_title)}</title>
<meta name="description" content="{e(description)}">
{meta}
<link rel="stylesheet" href="{root}assets/estilos.css">
<script src="{root}assets/tema.js"></script>
<link rel="icon" href="{root}assets/icono.svg" type="image/svg+xml">
<link rel="alternate" type="application/rss+xml" title="Ofertas del Grupo Tragsa (RSS)" href="{PORTAL}feeds/organismo-tragsa.xml">
</head>
<body id="arriba">
<a class="salto" href="#contenido">Saltar al contenido</a>
<div class="franja"><div class="ancho"><p><strong>Web independiente:</strong> no pertenece a Tragsa ni al Grupo Tragsa. Ofertas oficiales: <a href="{TRAGSA_EMPLEO}">web de empleo</a> · inscripción en su <a href="{TRAGSA_PORTAL}">Portal de Empleo</a>.</p></div></div>
<header class="sitio">
<div class="ancho cab">
<a class="marca" href="{root or "./"}">{SITE_NAME}</a>
<div class="cab-acciones">
{SETTINGS_BUTTON}
<button type="button" id="btn-menu" class="btn-cab" hidden aria-expanded="false" aria-controls="nav-principal">Menú</button>
</div>
<nav id="nav-principal" class="principal" aria-label="Principal"><ul>{links}</ul></nav>
</div></header>
<main id="contenido" class="ancho" tabindex="-1">
{trail}{body}
</main>
<footer class="sitio"><div class="ancho">
<p class="subir"><a href="#arriba">Volver arriba</a></p>
<p>{NO_OFICIAL} Los datos proceden de <a href="{PORTAL}">{PORTAL_NOMBRE}</a> (licencia CC BY 4.0); los textos y enlaces de cada oferta son del Grupo Tragsa, que es la fuente oficial y la que prevalece.</p>
<p>Datos actualizados el {e(stamp(site.generado))}.</p>
<p><a href="{root}aviso-legal/">Aviso legal y privacidad</a> · <a href="{root}aviso-legal/#reclamaciones">Reclamaciones</a> · <a href="{REPO}">Código fuente</a></p>
</div></footer>
<a class="subir-flotante" id="subir-flotante" href="#arriba" hidden><span aria-hidden="true">↑</span> Arriba</a>
{SETTINGS_DIALOG}
<script src="{root}assets/guardadas.js" defer></script>
<script src="{root}assets/filtros.js" defer></script>
<script src="{root}assets/subir.js" defer></script>
<script src="{root}assets/ajustes.js" defer></script>
<script src="{root}assets/compartir.js" defer></script>
</body>
</html>
"""


# ---------------------------------------------------------------- ofertas

def where(offer: dict) -> str:
    """Ubicación para mostrar: la localidad cuando la ubicación solo dice la comunidad o la sede."""
    location = offer.get("ubicacion") or "Sin indicar"
    place = offer.get("localidad")
    if not place or not location.startswith(GENERIC_PLACES):
        return location
    region = offer.get("comunidad") or ""
    if not region or region in ("Sin ubicación", "Varias comunidades", "Ámbito nacional"):
        return place
    if plain(place) in plain(region) or plain(region) in plain(place):
        return place
    return f"{place}, {region}"


def until(offer: dict) -> str:
    hour = f", a las {e(offer['plazo_hora'])}" if offer.get("plazo_hora") else ""
    return f"{time_tag(offer['plazo_fin'], weekday=True)}{hour}"


def deadline_text(offer: dict, today: date) -> str:
    opens = offer.get("plazo_inicio")
    if opens and date.fromisoformat(opens) > today:
        end = f" hasta el {until(offer)}" if offer.get("plazo_fin") else ""
        return f"<strong>Plazo aún no iniciado.</strong> Inscripción desde el {time_tag(opens, weekday=True)}{end}"
    if not offer.get("plazo_fin"):
        return "Plazo: no consta"
    days = (date.fromisoformat(offer["plazo_fin"]) - today).days
    label = f"Plazo: hasta el {until(offer)}"
    if days == 0:
        return f'<span class="urgente">Finaliza hoy.</span> {label}'
    if days == 1:
        return f'<span class="urgente">Finaliza mañana.</span> {label}'
    if 1 < days <= URGENT_DAYS:
        return f'<span class="urgente">Quedan {days} días.</span> {label}'
    return label


def contract(site: Sitio, offer: dict) -> str:
    return site.contratos.get(offer.get("tipo_contrato") or "") or offer.get("contrato") or ""


def search_text(site: Sitio, offer: dict) -> str:
    parts = [offer.get(k) or "" for k in ("titulo", "codigo", "empresa", "ubicacion", "localidad", "comunidad",
                                          "departamento", "tipo_puesto", "convocatoria")]
    parts += [site.provincia(offer.get("provincia")), contract(site, offer)]
    parts += [site.areas.get(a, "") for a in offer.get("areas") or []]
    return plain(" ".join(str(p) for p in parts if p))


def saved_id(offer: dict) -> str:
    """Clave de la oferta en «Guardadas» (guardadas.js); solo letras, cifras y guiones."""
    return f"o:{slug(offer['id'])}"


def saved_filter() -> str:
    """Pastilla «Guardadas»: oculta hasta que guardadas.js sabe que hay alguna en este navegador."""
    return ('<label class="pastilla" id="pastilla-guardadas" data-tipo="o" hidden>'
            '<input type="checkbox" name="guardadas" value="1"> Guardadas<span id="n-guardadas"></span></label>\n')


def share_link(offer: dict) -> str:
    """«Compartir» la ficha oficial. Sin JavaScript, o donde no hay menú nativo, abre el correo (mailto:);
    con él, compartir.js abre el menú de compartir del sistema."""
    url = offer.get("url") or TRAGSA_EMPLEO
    mailto = f"mailto:?subject={quote(offer['titulo'])}&body={quote(offer['titulo'] + chr(10) + url)}"
    return (f'<a class="compartir" href="{e(mailto)}" data-url="{e(url)}" data-titulo="{e(offer["titulo"])}">'
            f'Compartir<span class="sr-only">: {e(offer["titulo"])}</span></a>')


def offer_card(site: Sitio, offer: dict) -> str:
    today = site.today
    days = (date.fromisoformat(offer["plazo_fin"]) - today).days if offer.get("plazo_fin") else 9999
    remote = offer.get("teletrabajo")
    facts = " · ".join(f for f in (offer.get("empresa"), where(offer), seats(offer.get("plazas"))) if f)
    extra = [offer.get("tipo_puesto"), offer.get("departamento"), contract(site, offer),
             "Menciona teletrabajo" if isinstance(remote, str) else None]
    extra = " · ".join(f for f in extra if f)
    extra = f' <span class="dato">· {e(extra)}</span>' if extra else ""
    published = (f' <span class="dato">· Publicada el {time_tag(offer["publicada"])}</span>'
                 if offer.get("publicada") else "")
    areas = " ".join(offer.get("areas") or []) or SIN_AREA
    code = f'<span class="dato">Código {e(offer["codigo"])}</span>' if offer.get("codigo") else ""
    apply = (f'<a href="{e(offer["url_inscripcion"])}">Inscribirse<span class="sr-only">: {e(offer["titulo"])}</span></a>'
             if offer.get("url_inscripcion") else "")
    actions = " · ".join(x for x in (apply, code, share_link(offer)) if x)
    actions = f'<p class="acciones-oferta">{actions}</p>' if actions else ""
    return f"""<li data-texto="{e(search_text(site, offer))}" data-empresa="{e(slug(offer.get('empresa') or ''))}" data-comunidad="{e(offer.get('ccaa') or SIN_COMUNIDAD)}" data-provincia="{e(offer.get('provincia') or '')}" data-area="{e(areas)}" data-puesto="{e(slug(offer.get('tipo_puesto') or ''))}" data-tipo="{e(offer.get('tipo_contrato') or '')}" data-teletrabajo="{1 if isinstance(remote, str) else 0}" data-plazas="{offer.get('plazas') or 0}" data-plazo="{e(offer.get('plazo_fin') or '9999')}" data-publicada="{e(offer.get('publicada') or offer['detectada'][:10])}" data-pronto="{1 if days <= SOON_DAYS else 0}" data-guardar="{e(saved_id(offer))}">
<h2><a href="{e(offer.get('url') or TRAGSA_EMPLEO)}">{e(offer['titulo'])}</a></h2>
<p>{e(facts)}{extra}</p>
<p class="plazo">{deadline_text(offer, today)}{published}</p>
{actions}
<div class="tarjeta-acciones"></div>
</li>"""


def select(name: str, label: str, choices: list[tuple[str, str]], everything: str = "Todas") -> str:
    """Desplegable con los valores que existen de verdad; con menos de dos, no se ofrece."""
    if len(choices) < 2:
        return ""
    opts = "".join(f'<option value="{e(v)}">{e(t)}</option>' for v, t in choices)
    return (f'<div class="campo"><label for="{name}">{label}</label>\n'
            f'<select id="{name}" name="{name}"><option value="">{everything}</option>{opts}</select></div>\n')


def by_name(pairs) -> list[tuple[str, str]]:
    return sorted(set(pairs), key=lambda p: plain(p[1]))


def listing(site: Sitio, offers: list[dict], fixed: set[str] = frozenset()) -> str:
    """Buscador, filtros y lista. `fixed` son los filtros que la página ya aplica (no se ofrecen)."""
    fields = ""
    if "empresa" not in fixed:
        fields += select("empresa", "Empresa", by_name((slug(o["empresa"]), o["empresa"]) for o in offers if o.get("empresa")))
    if "comunidad" not in fixed:
        regions = by_name((o["ccaa"], site.comunidades.get(o["ccaa"], o["ccaa"])) for o in offers if o.get("ccaa"))
        if any(not o.get("ccaa") for o in offers):
            regions.append((SIN_COMUNIDAD, "Varias o sin concretar"))
        fields += select("comunidad", "Comunidad autónoma", regions)
    if "provincia" not in fixed:
        fields += select("provincia", "Provincia", by_name((o["provincia"], site.provincia(o["provincia"]))
                                                           for o in offers if o.get("provincia") in site.provincias))
    if "area" not in fixed:
        present = {a for o in offers for a in (o.get("areas") or [SIN_AREA])}
        areas = [(k, v) for k, v in site.areas.items() if k in present]
        if SIN_AREA in present:
            areas.append((SIN_AREA, "Sin área"))
        fields += select("area", "Área (orientativa)", areas)
    fields += select("puesto", "Tipo de puesto", by_name((slug(o["tipo_puesto"]), o["tipo_puesto"])
                                                         for o in offers if o.get("tipo_puesto")), "Todos")
    fields += select("tipo", "Contrato", by_name((o["tipo_contrato"], contract(site, o))
                                                 for o in offers if o.get("tipo_contrato")), "Todos")
    remote = ""
    if any(isinstance(o.get("teletrabajo"), str) for o in offers):
        remote = ('<label class="pastilla"><input type="checkbox" name="teletrabajo" value="1"> '
                  'Menciona teletrabajo</label>\n')
    panel = button = ""
    if fields:
        button = ('<button type="button" class="pastilla" id="btn-filtros" aria-expanded="false" '
                  'aria-controls="mas-filtros">Filtros<span id="n-filtros"></span></button>\n')
        panel = f'<div class="panel rejilla" id="mas-filtros" hidden>\n{fields}</div>\n'
    total = sum(o.get("plazas") or 0 for o in offers)
    status = f"{count(len(offers), 'oferta abierta', 'ofertas abiertas')}, con {seats(total)}."
    cards = "\n".join(offer_card(site, o) for o in offers)
    form = ""
    if len(offers) > 1:
        form = f"""<form id="filtros" class="filtros" role="search" aria-label="Buscar ofertas" hidden>
<div class="buscador"><label for="q" class="sr-only">Buscar ofertas por palabra</label>
<input id="q" name="q" type="search" autocomplete="off" placeholder="Puesto, localidad o código">
<button type="submit">Buscar</button></div>
<div class="pastillas">
{button}<label class="pastilla"><input type="checkbox" name="pronto" value="1"> Cierran en {SOON_DAYS} días</label>
{remote}{saved_filter()}<div class="orden"><label for="orden">Ordenar por</label>
<select id="orden" name="orden"><option value="reciente">Más recientes</option><option value="plazo">Plazo más próximo</option></select></div>
</div>
{panel}</form>
"""
    reset = '<button type="reset" form="filtros" class="quitar" hidden>Quitar filtros</button>' if form else ""
    return f"""{form}<div class="resultados"><p id="estado-filtros" role="status">{status}</p>{reset}</div>
<p class="nota" id="sin-resultados" hidden>Ninguna oferta coincide con la búsqueda. Pruebe a quitar algún filtro.</p>
<ol class="ofertas" id="lista-ofertas">
{cards}
</ol>"""


def empty_note(site: Sitio, root: str) -> str:
    return (f'<p class="nota">En este momento no hay ofertas abiertas. Puede consultar las '
            f'<a href="{root}tasas-de-reposicion/">tasas de reposición</a> o recibir un '
            f'<a href="{root}avisos/">aviso</a> cuando se publique la próxima.</p>')


def alerts_hint(root: str) -> str:
    return (f'<p class="aviso-corto"><a href="{root}avisos/">Recibir un aviso</a> cuando se publique una oferta '
            'nueva: Telegram, correo o RSS, sin registrarse en ninguna web.</p>')


# ---------------------------------------------------------------- agrupaciones

def groups(site: Sitio) -> dict[str, list[tuple[str, str, list[dict]]]]:
    """Comunidades, provincias y áreas con alguna oferta abierta: (ruta, nombre, ofertas)."""
    regions: dict[str, list] = {}
    provinces: dict[str, list] = {}
    areas: dict[str, list] = {}
    for offer in site.ofertas:
        if offer.get("ccaa") in site.comunidades:
            regions.setdefault(offer["ccaa"], []).append(offer)
        if offer.get("provincia") in site.provincias:
            provinces.setdefault(offer["provincia"], []).append(offer)
        for area in offer.get("areas") or []:
            if area in site.areas:
                areas.setdefault(area, []).append(offer)
    return {
        "comunidad": sorted(((f"comunidad/{slug(site.comunidades[c])}/", site.comunidades[c], o, c)
                             for c, o in regions.items()), key=lambda g: plain(g[1])),
        "provincia": sorted(((f"provincia/{slug(site.provincia(p))}/", site.provincia(p), o, p)
                             for p, o in provinces.items()), key=lambda g: plain(g[1])),
        "area": [(f"area/{slug(site.areas[a])}/", site.areas[a], areas[a], a) for a in site.areas if a in areas],
    }


def link_list(items, root: str) -> str:
    rows = "".join(f'<li><a href="{root}{path}">{e(name)}</a> <span class="dato">({len(offers)})</span></li>'
                   for path, name, offers, _ in items)
    return f'<ul class="enlaces">{rows}</ul>'


def explore(site: Sitio, grouped: dict, root: str) -> str:
    if not site.ofertas:
        return ""
    return f"""<section class="explorar" aria-labelledby="explorar">
<h2 id="explorar">Ofertas por comunidad, provincia y área</h2>
<h3 id="por-comunidad">Por comunidad autónoma</h3>
{link_list(grouped["comunidad"], root)}
<h3 id="por-provincia">Por provincia</h3>
{link_list(grouped["provincia"], root)}
<h3 id="por-area">Por área</h3>
<p class="dato">El área la asigna {PORTAL_NOMBRE} a partir del título de la oferta: es orientativa.</p>
{link_list(grouped["area"], root)}
</section>"""


# ---------------------------------------------------------------- páginas

def open_processes_note(site: Sitio, root: str) -> str:
    rows = []
    for p in site.procesos:
        if p["estado"] != "abierto":
            continue
        hour = f", a las {e(p['plazo_hora'])}" if p.get("plazo_hora") and p.get("plazo_fin") else ""
        until_text = f" hasta el {time_tag(p['plazo_fin'], weekday=True)}{hour}" if p.get("plazo_fin") else ""
        rows.append(f'<li><a href="{root}tasas-de-reposicion/{site.proceso_slug[p["id"]]}/">'
                    f'{e(humane_caps(p["nombre"]))}</a>: inscripción abierta{until_text}.</li>')
    if not rows:
        return ""
    if len(rows) == 1:  # un solo proceso: una línea, para no empujar la primera oferta
        return (f'<p class="nota"><strong>Puestos indefinidos con inscripción abierta:</strong> '
                f'{rows[0][4:-5].replace(": inscripción abierta", ",", 1)}</p>')
    return (f'<div class="nota"><p><strong>Puestos indefinidos con inscripción abierta</strong></p>'
            f'<ul>{"".join(rows)}</ul></div>')


def index_page(site: Sitio, grouped: dict) -> str:
    offers = site.ofertas
    total = sum(o.get("plazas") or 0 for o in offers)
    intro = ("<p class=\"resumen\">Todas las ofertas abiertas de Tragsa y Tragsatec, con plazo, ubicación y enlace "
             "a la ficha oficial. Se actualiza cada hora.</p>")
    jump = ('<p class="aviso-corto"><a href="avisos/">Recibir un aviso</a> de ofertas nuevas · Ver por '
            '<a href="#por-comunidad">comunidad</a>, <a href="#por-provincia">provincia</a> o '
            '<a href="#por-area">área</a>.</p>') if offers else alerts_hint("")
    body = f"""<h1>Ofertas de empleo de Tragsa y Tragsatec</h1>
{intro}
{jump}
{open_processes_note(site, "")}
{listing(site, offers) if offers else empty_note(site, "")}
{explore(site, grouped, "")}"""
    description = (f"{count(len(offers), 'oferta de empleo abierta', 'ofertas de empleo abiertas')} en Tragsa y "
                   f"Tragsatec, con {seats(total)}: buscador por provincia, área y plazo, y avisos. Web independiente.")
    return page(site, SITE_NAME, body, "", "index", description)


COMPANY_TEXT = {
    "tragsa": ("La Dirección de Tragsa se compone de tres subdirecciones: Actuaciones Medioambientales, "
               "Control de Producción e Infraestructuras y Edificación."),
    "tragsatec": ("La Dirección de Tragsatec se estructura en las subdirecciones de Agricultura, Ganadería y "
                  "Seguridad Alimentaria; Medio Ambiente, Pesca e Ingeniería; Sistemas de Información, y "
                  "Coordinación y Apoyo."),
}
QUIENES_SOMOS = "https://www.tragsa.es/es/grupo-tragsa/quienes-somos/Paginas/default.aspx"


def company_page(site: Sitio, key: str) -> str:
    name, legal = EMPRESAS[key]
    offers = [o for o in site.ofertas if slug(o.get("empresa") or "") == key or o.get("empresa") == GRUPO]
    other = "tragsatec" if key == "tragsa" else "tragsa"
    body = f"""<h1>Ofertas de empleo de {name}</h1>
<p class="resumen">{name} ({legal}) forma parte del Grupo Tragsa junto con {EMPRESAS[other][0]}. {COMPANY_TEXT[key]} <span class="dato">(Fuente: <a href="{QUIENES_SOMOS}">«Quiénes somos», tragsa.es</a>.)</span></p>
<p>Aquí figuran las ofertas abiertas de {name} y las que el Grupo Tragsa publica para las dos empresas. Las de {EMPRESAS[other][0]} están en <a href="../{other}/">su página</a>.</p>
{alerts_hint("../")}
{listing(site, offers, {"empresa"}) if offers else empty_note(site, "../")}"""
    description = (f"{count(len(offers), 'oferta de empleo abierta', 'ofertas de empleo abiertas')} en {name}, "
                   "con plazo, ubicación y enlace a la ficha oficial. Web independiente.")
    return page(site, f"Ofertas de empleo de {name}", body, f"{key}/", key, description)


def region_page(site: Sitio, path: str, name: str, offers: list[dict], code: str, grouped: dict) -> str:
    total = sum(o.get("plazas") or 0 for o in offers)
    provinces = [g for g in grouped["provincia"] if site.provincias[g[3]][1] == code]
    inside = ""
    if len(provinces) > 1:
        inside = f"<h2>Por provincia</h2>\n{link_list(provinces, '../../')}"
    place = with_article(name)
    body = f"""<h1>Ofertas de empleo de Tragsa y Tragsatec en {e(place)}</h1>
<p class="resumen">{count(len(offers), "oferta abierta", "ofertas abiertas")} del Grupo Tragsa en {e(place)}, con {seats(total)}. No incluye las ofertas para varias comunidades, que están en la <a href="../../">portada</a>.</p>
{alerts_hint("../../")}
{listing(site, offers, {"comunidad"})}
{inside}"""
    description = (f"{count(len(offers), 'oferta de empleo abierta', 'ofertas de empleo abiertas')} de Tragsa y "
                   f"Tragsatec en {place}, con plazo y enlace a la ficha oficial. Web independiente.")
    return page(site, f"Empleo en Tragsa en {place}", body, path, description=description,
                crumbs=[("", "Ofertas")], here=name)


def province_page(site: Sitio, path: str, name: str, offers: list[dict], code: str, grouped: dict) -> str:
    total = sum(o.get("plazas") or 0 for o in offers)
    region_code = site.provincias[code][1]
    crumbs = [("", "Ofertas")]
    region = next((g for g in grouped["comunidad"] if g[3] == region_code), None)
    if region:
        crumbs.append((region[0], region[1]))
    body = f"""<h1>Ofertas de empleo de Tragsa y Tragsatec en la provincia de {e(name)}</h1>
<p class="resumen">{count(len(offers), "oferta abierta", "ofertas abiertas")} del Grupo Tragsa en la provincia de {e(name)}, con {seats(total)}.</p>
{alerts_hint("../../")}
{listing(site, offers, {"comunidad", "provincia"})}"""
    description = (f"{count(len(offers), 'oferta de empleo abierta', 'ofertas de empleo abiertas')} de Tragsa y "
                   f"Tragsatec en la provincia de {name}, con plazo y enlace a la ficha oficial. Web independiente.")
    return page(site, f"Empleo en Tragsa en la provincia de {name}", body, path, description=description,
                crumbs=crumbs, here=f"Provincia de {name}")


def area_page(site: Sitio, path: str, name: str, offers: list[dict]) -> str:
    total = sum(o.get("plazas") or 0 for o in offers)
    body = f"""<h1>Ofertas de empleo de Tragsa y Tragsatec: {e(name)}</h1>
<p class="resumen">{count(len(offers), "oferta abierta", "ofertas abiertas")}, con {seats(total)}. El área no la publica Tragsa: la asigna {PORTAL_NOMBRE} a partir del título de cada oferta y es orientativa. Una oferta puede tener dos áreas.</p>
{alerts_hint("../../")}
{listing(site, offers, {"area"})}"""
    description = (f"{count(len(offers), 'oferta de empleo abierta', 'ofertas de empleo abiertas')} de Tragsa y "
                   f"Tragsatec del área «{name}», con plazo y enlace a la ficha oficial. Web independiente.")
    return page(site, f"Empleo en Tragsa: {name}", body, path, description=description,
                crumbs=[("", "Ofertas")], here=name)


# ---------------------------------------------------------------- procesos (tasas de reposición)

def is_pdf(url: str) -> bool:
    return url.lower().split("?")[0].endswith(".pdf")


def notice(n: dict) -> str:
    when = f"{time_tag(n['fecha'])}: " if n.get("fecha") else ""
    if not n.get("url"):
        return f"{when}{e(humane_caps(n['titulo']))}"
    pdf = " (PDF)" if is_pdf(n["url"]) else ""
    return f'{when}<a href="{e(n["url"])}">{e(humane_caps(n["titulo"]))}{pdf}</a>'


def process_facts(site: Sitio, p: dict) -> list[tuple[str, str]]:
    facts = [
        ("Tipo", site.tipos_proceso.get(p.get("tipo") or "", "")),
        ("Acceso", site.accesos.get(p.get("acceso") or "", "")),
        ("Contrato", site.contratos.get(p.get("tipo_contrato") or "", "")),
        ("Sistema de selección", site.sistemas.get(p.get("sistema") or "", "")),
        ("Situación", site.estados.get(p.get("estado") or "", "")),
    ]
    return [(k, v) for k, v in facts if v]


def process_status(site: Sitio, p: dict) -> str:
    if p["estado"] != "abierto":
        return f"Situación: {e(site.estados.get(p['estado'], p['estado']))}."
    if not p.get("plazo_fin"):
        return "<strong>Inscripción abierta.</strong>"
    fake = {"plazo_fin": p["plazo_fin"], "plazo_hora": p.get("plazo_hora")}
    return f"<strong>Inscripción abierta.</strong> {deadline_text(fake, site.today)}"


def processes_page(site: Sitio) -> str:
    cards = []
    for p in site.procesos:
        last = max(p["comunicados"], key=lambda n: n.get("fecha") or "", default=None)
        facts = [v for k, v in process_facts(site, p) if k != "Situación"]
        facts.append(count(len(p["comunicados"]), "comunicado", "comunicados"))
        latest = f"<p>Último comunicado: {notice(last)}</p>" if last else ""
        cards.append(f"""<li>
<h2><a href="{site.proceso_slug[p['id']]}/">{e(humane_caps(p['nombre']))}</a></h2>
<p class="dato">{e(" · ".join(facts))}</p>
<p class="plazo">{process_status(site, p)}</p>
{latest}
</li>""")
    items = "\n".join(cards) or '<li>En este momento no hay procesos en la API.</li>'
    body = f"""<h1>Tasas de reposición del Grupo Tragsa</h1>
<p class="resumen">Procesos selectivos para puestos indefinidos de Tragsa y Tragsatec. Cada proceso se publica en tragsa.es con unas bases y una serie de comunicados por fases (admisión, méritos, pruebas, resultados). Aquí están reunidos y ordenados por fecha, con enlace a cada documento oficial.</p>
<p>Qué es una tasa de reposición y cómo se participa: <a href="../como-funciona/#tasas">Cómo funciona</a>.</p>
<ol class="ofertas procesos">
{items}
</ol>"""
    description = ("Tasas de reposición de Tragsa y Tragsatec: situación, plazo de inscripción y todos los "
                   "comunicados por fecha, con enlace a tragsa.es. Web independiente.")
    return page(site, "Tasas de reposición", body, "tasas-de-reposicion/", "tasas", description)


def process_page(site: Sitio, p: dict) -> str:
    name = humane_caps(p["nombre"])
    rows = "".join(f"<dt>{e(k)}</dt><dd>{e(v)}</dd>" for k, v in process_facts(site, p))
    if p["estado"] == "abierto" and p.get("plazo_fin"):
        hour = f", a las {e(p['plazo_hora'])}" if p.get("plazo_hora") else ""
        rows += f"<dt>Plazo de inscripción</dt><dd>Hasta el {time_tag(p['plazo_fin'], weekday=True)}{hour}</dd>"
    links = [f'<a class="boton" href="{e(p.get("url") or TRAGSA_EMPLEO)}">Página oficial del proceso</a>']
    if p.get("url_inscripcion"):
        label = "Inscribirse en la plataforma oficial" if p["estado"] == "abierto" else "Plataforma del proceso"
        links.append(f'<a href="{e(p["url_inscripcion"])}">{label}</a>')
    notices = sorted(p["comunicados"], key=lambda n: n.get("fecha") or "", reverse=True)
    items = "".join(f"<li>{notice(n)}</li>" for n in notices)
    body = f"""<h1>{e(name)}</h1>
<p class="plazo">{process_status(site, p)}</p>
<dl class="ficha">{rows}</dl>
<p class="acciones">{" ".join(links)}</p>
<h2>Comunicados</h2>
<p class="dato">{count(len(notices), "comunicado", "comunicados")}, del más reciente al más antiguo. Los títulos son los de tragsa.es; las relaciones de personas candidatas y las notas solo se publican allí.</p>
<ol class="comunicados-lista">{items}</ol>
<h2>Seguir este proceso</h2>
<p>Para recibir los comunicados nuevos sin entrar cada día en tragsa.es, suscríbase a la <a href="{PORTAL}feeds/proceso-{e(p['id'])}.xml">lista RSS de este proceso</a> o cree un <a href="../../avisos/">aviso</a>.</p>"""
    description = (f"{name}: situación, plazo y todos los comunicados por fecha, con enlace a los documentos "
                   "oficiales de tragsa.es. Web independiente.")
    return page(site, name, body, f"tasas-de-reposicion/{site.proceso_slug[p['id']]}/", "tasas", description,
                crumbs=[("", "Ofertas"), ("tasas-de-reposicion/", "Tasas de reposición")])


# ---------------------------------------------------------------- textos

def text_page(site: Sitio, name: str, title: str, path: str, current: str, description: str) -> str:
    body = (TEXTOS / f"{name}.html").read_text(encoding="utf-8")
    replacements = {
        "{{raiz}}": "../" * path.count("/"), "{{portal}}": PORTAL, "{{portal_nombre}}": PORTAL_NOMBRE,
        "{{titular}}": TITULAR, "{{contacto}}": CONTACTO, "{{repo}}": REPO, "{{sitio}}": SITE_NAME,
        "{{tragsa_empleo}}": TRAGSA_EMPLEO, "{{tragsa_portal}}": TRAGSA_PORTAL,
        "{{reclamaciones}}": reclamaciones_mailto(),
    }
    for key, value in replacements.items():
        body = body.replace(key, value)
    leftover = re.search(r"\{\{\w+\}\}", body)
    if leftover:
        raise ValueError(f"textos/{name}.html: {leftover.group()} sin sustituir")
    return page(site, title, body, path, current, description)


def reclamaciones_mailto() -> str:
    subject = quote(f"Reclamación sobre {SITE_NAME}")
    return f'<a href="mailto:{CONTACTO}?subject={subject}">{CONTACTO}</a>'


def alerts_page(site: Sitio) -> str:
    telegram = ""
    if site.bot:
        telegram = (f'<li><a href="https://t.me/{e(site.bot)}?start=tragsa"><strong>Telegram</strong>'
                    '<span>Abre el bot con Tragsa ya elegido. Puede añadir palabras del título, áreas o '
                    'comunidades.</span></a></li>')
    body = f"""<h1>Avisos de ofertas de Tragsa</h1>
<p class="resumen">La web de Tragsa no permite suscribirse a sus ofertas. Estos avisos los envía <a href="{PORTAL}">{PORTAL_NOMBRE}</a>, el portal del que salen los datos de esta web, del mismo titular: son gratuitos y no llevan publicidad.</p>
<ul class="vias">
{telegram}<li><a href="{PORTAL}avisos/?organismo=tragsa"><strong>Correo electrónico y más opciones</strong><span>En {PORTAL_NOMBRE}, con Tragsa ya marcado en el formulario de correo. Allí también puede añadir otras empresas públicas.</span></a></li>
</ul>
<h2 id="rss">Por RSS, sin datos personales</h2>
<p>Un lector de RSS (como Feedly, Inoreader o el de su navegador) muestra las ofertas nuevas en cuanto se publican. No hace falta registrarse en ninguna web: basta con copiar la dirección de la lista en el lector.</p>
<ul>
<li><a href="{PORTAL}feeds/organismo-tragsa.xml">Todas las ofertas del Grupo Tragsa</a></li>
<li><a href="{PORTAL}feeds/empresa-tragsa.xml">Solo las de Tragsa</a></li>
<li><a href="{PORTAL}feeds/empresa-tragsatec.xml">Solo las de Tragsatec</a></li>
<li>Los comunicados de cada tasa de reposición: en la página de cada proceso, en <a href="../tasas-de-reposicion/">Tasas de reposición</a>.</li>
</ul>
<p>Los datos personales de los avisos por Telegram y correo los trata {PORTAL_NOMBRE} conforme a su <a href="{PORTAL}acerca/#datos-personales">información de privacidad</a>.</p>"""
    description = "Avisos gratuitos de las ofertas de empleo de Tragsa y Tragsatec por Telegram, correo y RSS."
    return page(site, "Avisos de ofertas de Tragsa", body, "avisos/", "avisos", description)


def not_found_page(site: Sitio) -> str:
    root = site.base_url
    body = f"""<h1>Página no encontrada</h1>
<p>Puede que la página ya no exista: las páginas de cada comunidad, provincia o área solo están mientras tienen ofertas abiertas.</p>
<ul>
<li><a href="{root}">Todas las ofertas abiertas</a></li>
<li><a href="{root}tasas-de-reposicion/">Tasas de reposición</a></li>
<li><a href="{root}avisos/">Recibir avisos</a></li>
</ul>"""
    return page(site, "Página no encontrada", body, "404.html", root=root)


# ---------------------------------------------------------------- escritura

def sitemap(site: Sitio, entries: list[tuple[str, str | None]]) -> str:
    rows = []
    for path, lastmod in entries:
        mod = f"<lastmod>{lastmod}</lastmod>" if lastmod else ""
        rows.append(f"<url><loc>{e(site.base_url + path)}</loc>{mod}</url>")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + "\n".join(rows) + "\n</urlset>\n")


def write(out: Path, path: str, text: str) -> None:
    target = out / (path + "index.html" if path.endswith("/") or not path else path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def build(data: dict, out: Path, base_url: str = DEFAULT_BASE_URL, now: datetime | None = None,
          bot: str = DEFAULT_BOT) -> dict:
    """Genera la web en `out` (la vacía antes). Devuelve el contenido de estado.json."""
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(MADRID).date()
    site = Sitio(data, base_url, today, bot)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    shutil.copytree(ASSETS, out / "assets")
    updated = site.generado[:10]
    grouped = groups(site)
    entries: list[tuple[str, str | None]] = []

    def emit(path: str, html: str, lastmod: str | None = updated) -> None:
        write(out, path, html)
        entries.append((path, lastmod))

    emit("", index_page(site, grouped))
    for key in EMPRESAS:
        emit(f"{key}/", company_page(site, key))
    for path, name, offers, code in grouped["comunidad"]:
        emit(path, region_page(site, path, name, offers, code, grouped))
    for path, name, offers, code in grouped["provincia"]:
        emit(path, province_page(site, path, name, offers, code, grouped))
    for path, name, offers, _ in grouped["area"]:
        emit(path, area_page(site, path, name, offers))
    emit("tasas-de-reposicion/", processes_page(site))
    for p in site.procesos:
        last = max((n.get("fecha") or "" for n in p["comunicados"]), default="") or None
        emit(f"tasas-de-reposicion/{site.proceso_slug[p['id']]}/", process_page(site, p), last)
    emit("como-funciona/", text_page(site, "como-funciona", "Cómo funciona el empleo en el Grupo Tragsa",
                                     "como-funciona/", "como",
                                     "Cómo se presenta una candidatura a Tragsa y Tragsatec: tipos de ofertas, "
                                     "Portal de Empleo, plazos y tasas de reposición. Web independiente."), None)
    emit("avisos/", alerts_page(site), None)
    emit("aviso-legal/", text_page(site, "aviso-legal", "Aviso legal y privacidad", "aviso-legal/", "",
                                   f"Aviso legal de {SITE_NAME}: web independiente, sin relación con el Grupo Tragsa."),
         None)
    write(out, "404.html", not_found_page(site))
    (out / "sitemap.xml").write_text(sitemap(site, entries), encoding="utf-8")
    (out / "robots.txt").write_text(f"User-agent: *\nAllow: /\n\nSitemap: {site.base_url}sitemap.xml\n",
                                    encoding="utf-8")
    state = {"generado": site.generado, "fecha": today.isoformat(), "ofertas": len(site.ofertas),
             "procesos": len(site.procesos), "paginas": len(entries)}
    (out / "estado.json").write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return state


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default=os.environ.get("API_URL") or DEFAULT_API,
                        help="URL de la API o carpeta con ofertas.json, procesos.json y listas.json")
    parser.add_argument("--salida", default="_site", type=Path, help="carpeta de la web generada")
    parser.add_argument("--esperar", default="",
                        help="hora «generado» anunciada por el portal: espera a que la API la sirva")
    args = parser.parse_args()
    data = datos.cargar(args.api, esperar=args.esperar)
    state = build(data, args.salida, os.environ.get("BASE_URL") or DEFAULT_BASE_URL,
                  bot=(os.environ.get("TELEGRAM_BOT") or DEFAULT_BOT).lstrip("@"))
    print(json.dumps(state, ensure_ascii=False))
