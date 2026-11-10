// Mejora progresiva: sin JavaScript la página muestra la lista completa y el formulario sigue oculto.
// Basado en el de Empleo en Empresas Públicas: cada página declara solo los campos que usa.
(function () {
  "use strict";
  var form = document.getElementById("filtros");
  var list = document.getElementById("lista-ofertas");
  if (!form || !list) return;
  var status = document.getElementById("estado-filtros");
  var sinResultados = document.getElementById("sin-resultados");
  var items = Array.prototype.slice.call(list.children);
  var selects = ["empresa", "comunidad", "provincia", "area", "puesto", "tipo"].filter(function (n) { return form[n]; });
  var VARIOS = { area: true }; // una oferta puede tener dos áreas, separadas por espacios
  var casillas = ["pronto", "teletrabajo", "guardadas"].filter(function (n) { return form[n]; });
  var mas = document.getElementById("mas-filtros");
  var botonMas = document.getElementById("btn-filtros");
  var names = ["q"].concat(selects, form.orden ? ["orden"] : []);
  var timer = null;

  function plain(text) {
    return text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  }

  // Campo y sentido de cada orden. A igualdad, lo más reciente primero.
  var ORDEN = { reciente: ["publicada", -1], plazo: ["plazo", 1] };
  function comparar(clave) {
    var campo = ORDEN[clave][0], sentido = ORDEN[clave][1];
    return function (a, b) {
      var r = sentido * a.dataset[campo].localeCompare(b.dataset[campo]);
      return r || b.dataset.publicada.localeCompare(a.dataset.publicada);
    };
  }

  function apply(announce) {
    var words = plain(form.q.value).split(/\s+/).filter(Boolean);
    var marcadas = casillas.filter(function (n) { return form[n].checked; });
    var shown = 0, seats = 0;
    items.forEach(function (item) {
      var d = item.dataset;
      var match =
        words.every(function (word) { return d.texto.indexOf(word) !== -1; }) &&
        selects.every(function (n) {
          var v = form[n].value;
          return !v || (VARIOS[n] ? (d[n] || "").split(" ").indexOf(v) !== -1 : d[n] === v);
        }) &&
        marcadas.every(function (n) { return d[n] === "1"; });
      item.hidden = !match;
      if (match) {
        shown += 1;
        seats += Number(d.plazas) || 0;
      }
    });
    var activos = selects.filter(function (n) { return form[n].value; }).length;
    var contador = document.getElementById("n-filtros");
    if (contador) contador.textContent = activos ? " (" + activos + (activos === 1 ? " activo)" : " activos)") : "";
    // «Quitar filtros» va fuera del formulario (atributo form): se busca en form.elements.
    var quitar = Array.prototype.filter.call(form.elements, function (el) { return el.type === "reset"; })[0];
    if (quitar) quitar.hidden = !(words.length || marcadas.length || activos);
    if (sinResultados) sinResultados.hidden = shown !== 0;
    if (form.orden && ORDEN[form.orden.value]) {
      items.slice().sort(comparar(form.orden.value)).forEach(function (item) { list.appendChild(item); });
    }
    if (announce && status) {
      status.textContent = shown === 1
        ? "1 oferta encontrada, con " + seats + (seats === 1 ? " plaza." : " plazas.")
        : shown + " ofertas encontradas, con " + seats + (seats === 1 ? " plaza." : " plazas.");
    }
    // La dirección conserva la búsqueda: se puede guardar o compartir.
    var params = new URLSearchParams();
    names.forEach(function (name) {
      if (form[name].value && !(name === "orden" && form.orden.value === "reciente")) params.set(name, form[name].value);
    });
    marcadas.forEach(function (n) { params.set(n, "1"); });
    var query = params.toString();
    history.replaceState(null, "", query ? "?" + query : location.pathname);
  }

  function abrirPanel(abierto) {
    mas.hidden = !abierto;
    botonMas.setAttribute("aria-expanded", String(abierto));
  }

  var initial = new URLSearchParams(location.search);
  names.forEach(function (name) {
    if (initial.has(name)) form[name].value = initial.get(name);
  });
  casillas.forEach(function (n) { form[n].checked = initial.get(n) === "1"; });
  if (mas && botonMas) {
    botonMas.addEventListener("click", function () { abrirPanel(mas.hidden); });
    if (selects.some(function (n) { return initial.has(n); })) abrirPanel(true);
  }
  form.hidden = false;
  apply(initial.toString() !== "");

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    apply(true);
  });
  form.addEventListener("change", function () { apply(true); });
  form.q.addEventListener("input", function () {
    clearTimeout(timer);
    timer = setTimeout(function () { apply(true); }, 500);
  });
  form.addEventListener("reset", function () {
    // El botón se oculta al no quedar filtros: el foco pasa a la barra de búsqueda.
    setTimeout(function () { apply(true); form.q.focus(); }, 0);
  });
})();
