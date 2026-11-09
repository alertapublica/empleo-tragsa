"""Lectura de la API de Empleo en Empresas Públicas (alertapublica.es), solo lo del Grupo Tragsa.

La web no calcula nada: los códigos INE, las áreas y el teletrabajo vienen ya en la API. Aquí solo se
comprueba que siguen estando las claves que se usan (si la API cambia, la generación falla y no se
publica una web rota) y se filtra el organismo.
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

ORGANISMO = "tragsa"
API_VERSION = 1
USER_AGENT = "empleo-tragsa (+https://github.com/alertapublica/empleo-tragsa)"
FICHEROS = ("ofertas.json", "procesos.json", "listas.json")

# Claves de la API v1 que usa la web. Dentro de la versión 1 solo se añaden claves, nunca se quitan.
CLAVES_OFERTA = {
    "id", "organismo", "codigo", "titulo", "empresa", "estado", "ubicacion", "localidad", "comunidad",
    "ccaa", "provincia", "plazas", "tipo_contrato", "contrato", "convocatoria", "tipo_puesto",
    "departamento", "plazo_inicio", "plazo_fin", "plazo_hora", "publicada", "detectada", "areas",
    "teletrabajo", "url", "url_inscripcion",
}
CLAVES_PROCESO = {
    "id", "organismo", "nombre", "tipo", "acceso", "tipo_contrato", "sistema", "estado", "plazo_fin",
    "plazo_hora", "url", "url_inscripcion", "comunicados",
}
CLAVES_COMUNICADO = {"fecha", "titulo", "url"}
CLAVES_LISTAS = {"comunidades", "provincias", "areas", "tipos_contrato", "tipos_proceso", "accesos",
                 "sistemas", "estados_proceso"}


class ApiError(Exception):
    """La API no tiene la forma esperada: mejor no publicar que publicar una web incompleta."""


def _leer(origen: str, nombre: str, sin_cache: bool = False) -> dict:
    """`origen` es una URL (https://…/api/) o una carpeta local con los tres ficheros."""
    if not origen.startswith(("http://", "https://")):
        return json.loads((Path(origen) / nombre).read_text(encoding="utf-8"))
    url = urllib.parse.urljoin(origen if origen.endswith("/") else origen + "/", nombre)
    if sin_cache:  # tras un aviso del portal, para no recibir la copia anterior de la caché
        url += f"?t={int(time.time())}"
    peticion = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(peticion, timeout=60) as respuesta:
        return json.loads(respuesta.read().decode("utf-8"))


def _comprobar(datos: dict, nombre: str, lista: str | None, claves: set[str]) -> None:
    if datos.get("version") != API_VERSION:
        raise ApiError(f"{nombre}: versión {datos.get('version')!r}, se esperaba {API_VERSION}")
    if not datos.get("generado"):
        raise ApiError(f"{nombre}: falta «generado»")
    if lista is None:
        faltan = claves - datos.keys()
        if faltan:
            raise ApiError(f"{nombre}: faltan {sorted(faltan)}")
        return
    for elemento in datos.get(lista) or []:
        faltan = claves - elemento.keys()
        if faltan:
            raise ApiError(f"{nombre}: a {elemento.get('id')!r} le faltan {sorted(faltan)}")


def comprobar(ofertas: dict, procesos: dict, listas: dict) -> None:
    _comprobar(ofertas, "ofertas.json", "ofertas", CLAVES_OFERTA)
    _comprobar(procesos, "procesos.json", "procesos", CLAVES_PROCESO)
    for proceso in procesos.get("procesos") or []:
        for comunicado in proceso["comunicados"]:
            faltan = CLAVES_COMUNICADO - comunicado.keys()
            if faltan:
                raise ApiError(f"procesos.json: un comunicado de {proceso['id']!r} no tiene {sorted(faltan)}")
    _comprobar(listas, "listas.json", None, CLAVES_LISTAS)
    if not any(o["id"] == ORGANISMO for o in listas.get("organismos") or []):
        raise ApiError(f"listas.json: no figura el organismo {ORGANISMO!r}")


def cargar(origen: str, esperar: str = "", intentos: int = 10, pausa: float = 60) -> dict:
    """Lee la API y devuelve lo del Grupo Tragsa.

    `esperar` es la hora `generado` que anunció el portal al publicar: si la API aún da una anterior
    (caché de GitHub Pages), se vuelve a pedir cada `pausa` segundos, como mucho `intentos` veces.
    """
    for intento in range(intentos):
        listas = _leer(origen, "listas.json", sin_cache=bool(esperar))
        if not esperar or listas.get("generado", "") >= esperar or intento == intentos - 1:
            break
        time.sleep(pausa)
    ofertas = _leer(origen, "ofertas.json", sin_cache=bool(esperar))
    procesos = _leer(origen, "procesos.json", sin_cache=bool(esperar))
    comprobar(ofertas, procesos, listas)
    return {
        "generado": ofertas["generado"],
        "ofertas": [o for o in ofertas["ofertas"] if o["organismo"] == ORGANISMO],
        "procesos": [p for p in procesos["procesos"] if p["organismo"] == ORGANISMO],
        "listas": listas,
    }
