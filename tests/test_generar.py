"""Pruebas del generador con datos de ejemplo de la API (tests/fixtures, recortados de la real)."""
from __future__ import annotations

import copy
import json
import re
import shutil
import tempfile
import unittest
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

from web import datos, generar

FIXTURES = Path(__file__).parent / "fixtures"
# Fecha fija: los plazos de los datos de ejemplo caen después.
NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
BASE = "https://ejemplo.es/"


def load() -> dict:
    return datos.cargar(str(FIXTURES))


class Paginas(HTMLParser):
    """Enlaces, ids y etiquetas de una página."""

    def __init__(self):
        super().__init__()
        self.hrefs: list[str] = []
        self.ids: list[str] = []
        self.label_for: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id"):
            self.ids.append(attrs["id"])
        if tag in ("a", "link") and "href" in attrs:
            self.hrefs.append(attrs["href"])
        if tag == "script" and "src" in attrs:
            self.hrefs.append(attrs["src"])
        if tag == "label" and attrs.get("for"):
            self.label_for.append(attrs["for"])


class Datos(unittest.TestCase):
    def test_solo_tragsa(self):
        data = load()
        self.assertTrue(data["ofertas"])
        self.assertEqual({o["organismo"] for o in data["ofertas"]}, {"tragsa"})
        self.assertEqual({p["organismo"] for p in data["procesos"]}, {"tragsa"})

    def test_falta_una_clave(self):
        ofertas = json.loads((FIXTURES / "ofertas.json").read_text())
        procesos = json.loads((FIXTURES / "procesos.json").read_text())
        listas = json.loads((FIXTURES / "listas.json").read_text())
        rota = copy.deepcopy(ofertas)
        del rota["ofertas"][0]["plazo_fin"]
        with self.assertRaisesRegex(datos.ApiError, "plazo_fin"):
            datos.comprobar(rota, procesos, listas)
        rota = copy.deepcopy(listas)
        del rota["provincias"]
        with self.assertRaisesRegex(datos.ApiError, "provincias"):
            datos.comprobar(ofertas, procesos, rota)

    def test_version_distinta(self):
        ofertas = json.loads((FIXTURES / "ofertas.json").read_text())
        ofertas["version"] = 2
        procesos = json.loads((FIXTURES / "procesos.json").read_text())
        listas = json.loads((FIXTURES / "listas.json").read_text())
        with self.assertRaisesRegex(datos.ApiError, "versión"):
            datos.comprobar(ofertas, procesos, listas)

    def test_espera_la_hora_anunciada(self):
        """Si la API aún da una versión anterior a la anunciada, reintenta y al final sigue con lo que hay."""
        llamadas = []
        original = datos._leer

        def leer(origen, nombre, sin_cache=False):
            llamadas.append((nombre, sin_cache))
            return original(origen, nombre)

        datos._leer = leer
        try:
            data = datos.cargar(str(FIXTURES), esperar="2999-01-01T00:00:00+00:00", intentos=3, pausa=0)
        finally:
            datos._leer = original
        self.assertEqual([n for n, _ in llamadas].count("listas.json"), 3)
        self.assertTrue(all(sin_cache for _, sin_cache in llamadas))
        self.assertTrue(data["ofertas"])


class Textos(unittest.TestCase):
    def test_plazos(self):
        hoy = date(2026, 11, 9)
        texto = generar.deadline_text
        self.assertIn("Finaliza hoy", texto({"plazo_fin": "2026-11-09", "plazo_hora": "23:59"}, hoy))
        self.assertIn("a las 23:59", texto({"plazo_fin": "2026-11-09", "plazo_hora": "23:59"}, hoy))
        self.assertIn("Finaliza mañana", texto({"plazo_fin": "2026-11-10"}, hoy))
        self.assertIn("Quedan 3 días", texto({"plazo_fin": "2026-11-12"}, hoy))
        self.assertNotIn("urgente", texto({"plazo_fin": "2026-11-20"}, hoy))
        self.assertEqual(texto({"plazo_fin": None}, hoy), "Plazo: no consta")
        self.assertIn("aún no iniciado", texto({"plazo_inicio": "2026-11-12", "plazo_fin": "2026-11-20"}, hoy))

    def test_ubicacion(self):
        donde = generar.where
        self.assertEqual(donde({"ubicacion": "Sede Madrid Tragsa", "localidad": "Madrid",
                                "comunidad": "Comunidad de Madrid"}), "Madrid")
        self.assertEqual(donde({"ubicacion": "Comunidad de Valencia", "localidad": "Moncada",
                                "comunidad": "Comunitat Valenciana"}), "Moncada, Comunitat Valenciana")
        self.assertEqual(donde({"ubicacion": "Sevilla", "localidad": "Sevilla", "comunidad": "Andalucía"}), "Sevilla")
        self.assertEqual(donde({"ubicacion": "Varios", "localidad": None, "comunidad": "Varias comunidades"}), "Varios")

    def test_mayusculas(self):
        self.assertEqual(generar.humane_caps("SE PUBLICA LA LISTA DE TRAGSATEC"), "Se publica la lista de Tragsatec")
        self.assertEqual(generar.humane_caps("Bases generales"), "Bases generales")

    def test_articulo(self):
        self.assertEqual(generar.with_article("Comunidad de Madrid"), "la Comunidad de Madrid")
        self.assertEqual(generar.with_article("País Vasco"), "el País Vasco")
        self.assertEqual(generar.with_article("Andalucía"), "Andalucía")


class Web(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.out = cls.tmp / "_site"
        cls.data = load()
        cls.state = generar.build(cls.data, cls.out, BASE, NOW, bot="bot_de_prueba")
        cls.pages = sorted(cls.out.rglob("*.html"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def read(self, path: str) -> str:
        return (self.out / path).read_text(encoding="utf-8")

    def test_paginas_principales(self):
        for path in ("index.html", "tragsa/index.html", "tragsatec/index.html", "tasas-de-reposicion/index.html",
                     "como-funciona/index.html", "avisos/index.html", "aviso-legal/index.html", "404.html",
                     "comunidad/andalucia/index.html", "provincia/sevilla/index.html", "provincia/madrid/index.html",
                     "sitemap.xml", "robots.txt", "estado.json", "assets/estilos.css", "assets/filtros.js"):
            self.assertTrue((self.out / path).is_file(), path)

    def test_solo_ofertas_abiertas(self):
        portada = self.read("index.html")
        abiertas = [o for o in self.data["ofertas"] if o["estado"] == "abierta"]
        cerradas = [o for o in self.data["ofertas"] if o["estado"] != "abierta"]
        self.assertTrue(cerradas)
        self.assertEqual(portada.count('<li data-texto="'), len(abiertas))
        for oferta in cerradas:
            self.assertNotIn(oferta["url"].replace("&", "&amp;"), portada)
        self.assertEqual(self.state["ofertas"], len(abiertas))

    def test_titulo_abre_la_ficha_oficial(self):
        portada = self.read("index.html")
        oferta = next(o for o in self.data["ofertas"] if o["estado"] == "abierta")
        # Los dos enlaces a Tragsa abren en una pestaña nueva, para no perder la lista.
        self.assertIn(f'<a href="{oferta["url"].replace("&", "&amp;")}" target="_blank" rel="noopener">', portada)
        self.assertIn(f'<a href="{oferta["url_inscripcion"].replace("&", "&amp;")}" target="_blank" rel="noopener">',
                      portada)

    def test_grupo_tragsa_en_las_dos_empresas(self):
        grupo = next(o for o in self.data["ofertas"] if o["empresa"] == "Grupo Tragsa")
        for empresa in ("tragsa", "tragsatec"):
            self.assertIn(grupo["titulo"].replace("&", "&amp;"), self.read(f"{empresa}/index.html"))
        tragsa = self.read("tragsa/index.html")
        for oferta in self.data["ofertas"]:
            if oferta["empresa"] == "Tragsatec":
                self.assertNotIn(f'href="{oferta["url"]}"', tragsa)

    def test_paginas_solo_con_ofertas(self):
        """Comunidades y provincias sin ofertas abiertas no tienen página (la cerrada es de Valencia)."""
        self.assertFalse((self.out / "provincia/valencia").exists())
        self.assertFalse((self.out / "comunidad/comunitat-valenciana").exists())
        self.assertFalse((self.out / "provincia/zaragoza").exists())

    def test_sitemap_igual_a_las_paginas(self):
        sitemap = self.read("sitemap.xml")
        urls = re.findall(r"<loc>([^<]+)</loc>", sitemap)
        on_disk = {BASE + str(p.relative_to(self.out)).removesuffix("index.html")
                   for p in self.pages if p.name == "index.html"}
        self.assertEqual(set(urls), on_disk)
        self.assertEqual(len(urls), self.state["paginas"])
        self.assertIn(f"Sitemap: {BASE}sitemap.xml", self.read("robots.txt"))

    def test_enlaces_internos(self):
        """Todo enlace relativo (y los absolutos a la propia web) lleva a un fichero que existe."""
        for page in self.pages:
            parser = Paginas()
            parser.feed(page.read_text(encoding="utf-8"))
            for href in parser.hrefs:
                if href.startswith(BASE):
                    target = self.out / href.removeprefix(BASE).split("#")[0]
                elif urlparse(href).scheme or href.startswith(("#", "mailto:")):
                    continue
                else:
                    target = (page.parent / href.split("#")[0].split("?")[0]).resolve()
                if target.is_dir() or str(target).endswith("/"):
                    target = target / "index.html"
                self.assertTrue(target.exists(), f"{page.relative_to(self.out)}: {href}")

    def test_accesibilidad_basica(self):
        for page in self.pages:
            html = page.read_text(encoding="utf-8")
            parser = Paginas()
            parser.feed(html)
            name = page.relative_to(self.out)
            self.assertEqual(len(parser.ids), len(set(parser.ids)), f"{name}: ids repetidos")
            for target in parser.label_for:
                self.assertIn(target, parser.ids, f"{name}: label for={target} sin campo")
            self.assertEqual(html.count("<h1"), 1, f"{name}: debe tener un h1")
            self.assertIn('<html lang="es">', html)
            self.assertIn('class="salto" href="#contenido"', html)

    def test_aviso_de_web_no_oficial_en_todas(self):
        for page in self.pages:
            html = page.read_text(encoding="utf-8")
            self.assertIn("no pertenece a Tragsa ni al Grupo Tragsa", html, page)
            self.assertIn(generar.TRAGSA_EMPLEO, html, page)

    def test_canonical(self):
        self.assertIn(f'<link rel="canonical" href="{BASE}provincia/sevilla/">', self.read("provincia/sevilla/index.html"))
        self.assertIn('<meta name="robots" content="noindex">', self.read("404.html"))
        self.assertNotIn('rel="canonical"', self.read("404.html"))

    def test_procesos(self):
        tasas = self.read("tasas-de-reposicion/index.html")
        for proceso in self.data["procesos"]:
            path = f"tasas-de-reposicion/{generar.Sitio(self.data, BASE, NOW.date(), '').proceso_slug[proceso['id']]}/index.html"
            html = self.read(path)
            self.assertIn(f"feeds/proceso-{proceso['id']}.xml", html)
            for comunicado in proceso["comunicados"]:
                self.assertIn(comunicado["url"].replace("&", "&amp;"), html)
            self.assertIn(generar.humane_caps(proceso["nombre"]), tasas)
        abierto = next(p for p in self.data["procesos"] if p["estado"] == "abierto")
        self.assertIn("Puestos indefinidos con inscripción abierta", self.read("index.html"))
        self.assertIn(abierto["url_inscripcion"], self.read("index.html") + tasas + "".join(
            p.read_text() for p in (self.out / "tasas-de-reposicion").rglob("index.html")))

    def test_avisos(self):
        avisos = self.read("avisos/index.html")
        self.assertIn("https://t.me/bot_de_prueba?start=tragsa", avisos)
        self.assertIn(f"{generar.PORTAL}avisos/?organismo=tragsa", avisos)
        self.assertIn(f"{generar.PORTAL}feeds/organismo-tragsa.xml", avisos)

    def test_estado(self):
        state = json.loads(self.read("estado.json"))
        self.assertEqual(state["generado"], self.data["generado"])
        self.assertEqual(state["fecha"], "2026-11-09")


class SinOfertas(unittest.TestCase):
    def test_web_vacia(self):
        data = load()
        data["ofertas"] = []
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "_site"
            generar.build(data, out, BASE, NOW, bot="")
            portada = (out / "index.html").read_text(encoding="utf-8")
            self.assertIn("En este momento no hay ofertas abiertas", portada)
            self.assertNotIn('id="filtros"', portada)
            self.assertFalse((out / "comunidad").exists())
            self.assertFalse((out / "provincia").exists())
            self.assertNotIn("t.me/", (out / "avisos/index.html").read_text(encoding="utf-8"))


def luminance(hex_color: str) -> float:
    channels = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


class Colores(unittest.TestCase):
    def test_contraste_de_la_paleta(self):
        css = (generar.ASSETS / "estilos.css").read_text(encoding="utf-8")
        blocks = re.findall(r"\{([^{}]*--ink:[^{}]*)\}", css)
        self.assertEqual(len(blocks), 5)  # sistema oscuro, claro (base), oscuro, sepia y contraste alto
        for block in blocks:
            v = dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})", block))
            pairs = [("ink", "bg"), ("ink", "surface"), ("muted", "bg"), ("muted", "surface"),
                     ("accent", "bg"), ("accent", "surface"), ("accent-ink", "accent"),
                     ("alert", "alert-bg")]
            for fg, bg in pairs:
                self.assertGreaterEqual(contrast(v[fg], v[bg]), 4.5, f"{fg} sobre {bg}: {v[fg]} / {v[bg]}")


if __name__ == "__main__":
    unittest.main()
