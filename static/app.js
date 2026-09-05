// Utilidades compartidas por todas las pantallas.

// ---- Modo oscuro ----
function temaEsOscuro() { return document.documentElement.dataset.theme === 'dark'; }
function setTema(oscuro) {
  document.documentElement.dataset.theme = oscuro ? 'dark' : '';
  try { localStorage.setItem('kdym_tema', oscuro ? 'oscuro' : 'claro'); } catch (e) {}
}
function toggleTema() { setTema(!temaEsOscuro()); }

// ---- Animación de inicio ----
// Se muestra solo en una apertura "fresca" (no al navegar entre pestañas de la app
// ni al volver de otra app). El #splash está oculto por CSS y sólo se muestra si acá
// le agregamos la clase 'on'.
(function () {
  const splash = document.getElementById('splash');
  if (!splash) return;
  const ahora = Date.now();
  const ult = +(localStorage.getItem('kdym_splash_ts') || 0);
  if (ahora - ult < 30 * 60 * 1000) { splash.remove(); return; }  // < 30 min: no repetir
  localStorage.setItem('kdym_splash_ts', String(ahora));
  splash.classList.add('on');
  document.body.classList.add('splashing');

  let cerrado = false;
  function cerrar() {
    if (cerrado) return;
    cerrado = true;
    splash.classList.add('hide');
    setTimeout(() => { splash.remove(); document.body.classList.remove('splashing'); }, 650);
  }
  splash.addEventListener('click', cerrar);   // tocar para saltear la intro

  const vid = document.getElementById('splash-video');
  if (!vid) { setTimeout(cerrar, 3300); return; }

  // Arranca con el video; si falla, vuelve a la animación de CSS.
  splash.classList.add('con-video');
  function sinVideo() {
    splash.classList.remove('con-video');
    setTimeout(cerrar, 3300);
  }
  vid.addEventListener('ended', cerrar);
  vid.addEventListener('error', sinVideo);

  let seguridad = setTimeout(cerrar, 10000);   // por si nunca arranca
  vid.addEventListener('playing', () => {
    clearTimeout(seguridad);
    seguridad = setTimeout(cerrar, ((vid.duration || 7) * 1000) + 1500);
  });

  function intentarPlay() {
    const p = vid.play();
    if (!p || !p.catch) return;
    p.catch(() => {
      // Si la pestaña está en segundo plano el navegador no deja reproducir;
      // en ese caso reintento cuando el usuario vuelve a la app.
      if (document.hidden) {
        document.addEventListener('visibilitychange', function volvio() {
          if (document.hidden) return;
          document.removeEventListener('visibilitychange', volvio);
          clearTimeout(seguridad);
          seguridad = setTimeout(cerrar, 10000);
          intentarPlay();
        });
      } else {
        sinVideo();
      }
    });
  }
  intentarPlay();
})();

function toast(msg, tipo) {
  const cont = document.getElementById('toasts');
  if (!cont) return;
  const el = document.createElement('div');
  el.className = 'toast ' + (tipo || '');
  el.textContent = msg;
  cont.appendChild(el);
  setTimeout(() => {
    el.style.transition = 'opacity .3s';
    el.style.opacity = '0';
    setTimeout(() => el.remove(), 300);
  }, tipo === 'alert' ? 6000 : 2600);
}

async function api(url, body) {
  const opt = { method: 'POST', headers: { 'Content-Type': 'application/json' } };
  if (body !== undefined) opt.body = JSON.stringify(body);
  const r = await fetch(url, body !== undefined ? opt : { method: 'POST' });
  let data = {};
  try { data = await r.json(); } catch (e) {}
  if (!r.ok || data.ok === false) {
    toast(data.error || 'Ocurrió un error', 'alert');
    throw new Error(data.error || 'error');
  }
  return data;
}

async function apiGet(url) {
  const r = await fetch(url);
  return r.json();
}

function iniciales(nombre) {
  return (nombre || '')
    .split(' ').filter(Boolean).slice(0, 2)
    .map(s => s[0].toUpperCase()).join('');
}

function cerrarModal(id) {
  const el = document.getElementById(id);
  if (el) { el.classList.remove('show'); el.style.zIndex = ''; }
}
function abrirModal(id) {
  const el = document.getElementById(id);
  if (!el) return;
  // Si ya hay otro modal abierto, este va por encima (modales apilados).
  const abiertos = [...document.querySelectorAll('.modal-bg.show')].filter(m => m !== el);
  if (abiertos.length) {
    const maxZ = Math.max(...abiertos.map(m => parseInt(getComputedStyle(m).zIndex, 10) || 100));
    el.style.zIndex = (maxZ + 10);
  }
  el.classList.add('show');
}

document.addEventListener('click', e => {
  if (e.target.classList && e.target.classList.contains('modal-bg')) {
    e.target.classList.remove('show');
  }
});

function escapeHtml(s) {
  return (s || '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}
function escapeJs(s) { return (s || '').replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/"/g, '\\"'); }

// ---- Días de la semana ----
const DIAS_ABBR = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom'];

// ---- Selector reutilizable de "días que viene" con horario por día ----
// Devuelve { getData() -> {dias:[...], horarios:{wd:"HH:MM"}}, setData(dias,horarios) }
function crearDiasPicker(pickerId, rowsId) {
  const state = { dias: new Set(), horarios: {} };
  function render() {
    const picker = document.getElementById(pickerId);
    const rows = document.getElementById(rowsId);
    if (!picker) return;
    picker.innerHTML = DIAS_ABBR.slice(0, 6).map((d, i) =>
      `<div class="dia-btn ${state.dias.has(i) ? 'on' : ''}" data-i="${i}">${d}</div>`
    ).join('');
    picker.querySelectorAll('.dia-btn').forEach(b => b.onclick = () => {
      const i = +b.dataset.i;
      if (state.dias.has(i)) { state.dias.delete(i); delete state.horarios[i]; }
      else state.dias.add(i);
      render();
    });
    if (rows) {
      rows.innerHTML = [...state.dias].sort((a, b) => a - b).map(i =>
        `<div class="dia-hora-row">
           <span class="dia-hora-lbl">${DIAS_ABBR[i]}</span>
           <input type="time" step="900" class="input" data-dia="${i}" value="${state.horarios[i] || ''}">
         </div>`).join('');
      rows.querySelectorAll('input[type=time]').forEach(inp =>
        inp.oninput = () => { state.horarios[+inp.dataset.dia] = inp.value; });
    }
  }
  render();
  return {
    getData() {
      const h = {};
      Object.keys(state.horarios).forEach(k => { if (state.horarios[k]) h[k] = state.horarios[k]; });
      return { dias: [...state.dias].sort((a, b) => a - b), horarios: h };
    },
    setData(dias, horarios) {
      state.dias = new Set((dias || []).filter(i => i < 6));
      state.horarios = {};
      Object.keys(horarios || {}).forEach(k => { if (+k < 6) state.horarios[+k] = horarios[k]; });
      render();
    },
  };
}

// ---- Modal de paciente compartido ----
let NP_CB = null;
function abrirNuevoPaciente(onSaved) {
  if (!document.getElementById('modal-paciente')) return;
  ['np-nombre', 'np-apellido', 'np-dni', 'np-telefono', 'np-obra',
   'np-diagnostico', 'np-notas'].forEach(id => {
    const el = document.getElementById(id); if (el) el.value = '';
  });
  document.getElementById('np-tot').value = '0';
  document.getElementById('np-usadas').value = '0';
  NP_CB = onSaved || null;
  abrirModal('modal-paciente');
  setTimeout(() => document.getElementById('np-nombre').focus(), 100);
}

async function guardarNuevoPaciente() {
  const v = id => (document.getElementById(id) || {}).value || '';
  const body = {
    nombre: v('np-nombre'), apellido: v('np-apellido'), dni: v('np-dni'),
    telefono: v('np-telefono'), obra_social: v('np-obra'),
    diagnostico: v('np-diagnostico'), sesiones_totales: v('np-tot'),
    sesiones_usadas: v('np-usadas'), notas: v('np-notas'),
  };
  if (!body.nombre.trim() || !body.apellido.trim()) {
    toast('Nombre y apellido son obligatorios', 'alert'); return;
  }
  const r = await api('/api/paciente', body);
  const nombre = (body.nombre + ' ' + body.apellido).trim();
  toast('Paciente guardado ✓', 'ok');
  cerrarModal('modal-paciente');
  // Al guardar, se abre "Agregar turnos" para configurar días y horarios.
  if (document.getElementById('modal-agturnos')) {
    abrirAgregarTurnos(r.id, nombre, () => { if (NP_CB) NP_CB(r.id, nombre); });
  } else if (NP_CB) {
    NP_CB(r.id, nombre);
  }
}

(function () {
  const b = document.getElementById('np-guardar');
  if (b) b.addEventListener('click', guardarNuevoPaciente);
})();

// ---- Contador de notificaciones (sidebar + nav inferior) ----
async function actualizarBadgeNotif() {
  const badges = [document.getElementById('nav-notif-badge'), document.getElementById('nav-notif-badge-m')];
  if (!badges.some(Boolean)) return;
  try {
    const r = await apiGet('/api/notificaciones/count');
    badges.forEach(b => {
      if (!b) return;
      if (r.count > 0) { b.textContent = r.count; b.style.display = 'inline-flex'; }
      else { b.style.display = 'none'; }
    });
  } catch (e) {}
}
actualizarBadgeNotif();
setInterval(actualizarBadgeNotif, 15000);

// ---- Menú "Más" (celular) ----
function toggleMas() {
  const s = document.getElementById('mas-sheet');
  if (s) s.classList.toggle('show');
}

// ---- Reloj/fecha del header (celular) + contador de sesiones (sidebar) ----
function _cabeceraReloj() {
  const rel = document.getElementById('m-reloj');
  const fec = document.getElementById('m-fecha');
  const d = new Date();
  if (rel) rel.textContent = d.toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' });
  if (fec) {
    let t = d.toLocaleDateString('es-AR', { weekday: 'long', day: 'numeric', month: 'long' });
    fec.textContent = t.charAt(0).toUpperCase() + t.slice(1);
  }
}
async function _sidebarSesiones() {
  const enc = document.getElementById('side-encurso');
  if (!enc) return;
  try {
    const e = await apiGet('/api/estado');
    enc.textContent = e.stats.en_curso;
    const bx = document.getElementById('side-boxes');
    if (bx) bx.textContent = (e.boxes || []).length;
  } catch (err) {}
}
_cabeceraReloj();
_sidebarSesiones();
setInterval(_cabeceraReloj, 30000);
setInterval(_sidebarSesiones, 15000);

// ============ Motor de alarma (sonido elegido, en bucle) ============
// La config del sonido vive en localStorage para que sea instantánea por dispositivo.
function cfgAlarma() { return localStorage.getItem('kdym_alarma') || 'campana'; }
function cfgAlarmaOn() { return localStorage.getItem('kdym_alarma_on') !== '0'; }  // default: on
function alarmaSeleccionada() { return cfgAlarma(); }
function alarmaEncendida() { return cfgAlarmaOn(); }

function _sampleAlarma(tipo, t) {
  const sq = f => Math.sign(Math.sin(2 * Math.PI * f * t));
  const sn = f => Math.sin(2 * Math.PI * f * t);
  switch (tipo) {
    case 'triple': return (t < 0.66 && (t % 0.22) < 0.14) ? sq(880) * 0.6 : 0;
    case 'suave': { const seg = Math.floor(t / 0.5) % 2; return ((t % 0.5) < 0.4 ? 1 : 0.2) * sn(seg ? 659 : 523) * 0.5; }
    case 'sirena': { const f = 600 + 400 * (0.5 + 0.5 * Math.sin(2 * Math.PI * (t / 2))); return sn(f) * 0.5; }
    case 'fuerte': return ((t % 0.19) < 0.12) ? sq(1000) * 0.7 : 0;
    case 'sirena_intensa': { const f = 500 + 700 * (0.5 + 0.5 * Math.sin(2 * Math.PI * (t / 0.9))); return sq(f) * 0.6; }
    case 'timbre': return sq(480) * 0.5 + sq(620) * 0.3;
    case 'alarma': { const seg = Math.floor(t / 0.14) % 2; return ((t % 0.14) < 0.1) ? sq(seg ? 1200 : 900) * 0.6 : 0; }
    default: { const env = Math.exp(-(t % 1.0) * 4); return (sn(988) + 0.5 * sn(1319)) * 0.5 * env; } // campana
  }
}
function makeAlarmDataUri(tipo) {
  const sr = 8000, dur = 2.0, n = Math.floor(sr * dur);
  const buf = new ArrayBuffer(44 + n * 2), dv = new DataView(buf);
  const wr = (o, s) => { for (let i = 0; i < s.length; i++) dv.setUint8(o + i, s.charCodeAt(i)); };
  wr(0, 'RIFF'); dv.setUint32(4, 36 + n * 2, true); wr(8, 'WAVE'); wr(12, 'fmt ');
  dv.setUint32(16, 16, true); dv.setUint16(20, 1, true); dv.setUint16(22, 1, true);
  dv.setUint32(24, sr, true); dv.setUint32(28, sr * 2, true); dv.setUint16(32, 2, true); dv.setUint16(34, 16, true);
  wr(36, 'data'); dv.setUint32(40, n * 2, true);
  for (let i = 0; i < n; i++) { let s = _sampleAlarma(tipo, i / sr); s = Math.max(-1, Math.min(1, s)); dv.setInt16(44 + i * 2, s * 32767, true); }
  let bin = ''; const by = new Uint8Array(buf);
  for (let i = 0; i < by.length; i++) bin += String.fromCharCode(by[i]);
  return 'data:audio/wav;base64,' + btoa(bin);
}
let _ALARM_AUDIO = null, _ALARM_TIPO = null;
function alarmAudio() {
  const tipo = cfgAlarma();
  if (!_ALARM_AUDIO || _ALARM_TIPO !== tipo) {
    if (_ALARM_AUDIO) { try { _ALARM_AUDIO.pause(); } catch (e) {} }
    _ALARM_AUDIO = new Audio(makeAlarmDataUri(tipo));
    _ALARM_AUDIO.loop = true;
    _ALARM_AUDIO.volume = 0;   // arranca en silencio: keep-alive (ver abajo)
    _ALARM_TIPO = tipo;
  }
  return _ALARM_AUDIO;
}

// ---- Clave para que suene aunque el celular esté en segundo plano / pantalla apagada ----
// Los navegadores móviles BLOQUEAN audio.play() cuando la pestaña no está visible,
// pero SÍ permiten cambiar el volumen de un audio que ya se está reproduciendo.
// Por eso mantenemos el audio de la alarma reproduciéndose SIEMPRE en silencio
// (volumen 0) desde el primer toque; cuando toca la alarma sólo subimos el volumen.
function mantenerAudioVivo() {
  const a = alarmAudio();
  if (a.paused) { a.play().catch(() => {}); }
}
function sonarContinuo() {
  const a = alarmAudio();
  a.volume = 1;
  if (a.paused) a.play().catch(() => {});   // por si el navegador lo pausó
}
function pararSonido() {
  // No lo pausamos: lo dejamos vivo en silencio para que la próxima alarma
  // pueda sonar aunque estemos en segundo plano.
  if (_ALARM_AUDIO) { _ALARM_AUDIO.volume = 0; }
}
function probarAlarma() { sonarContinuo(); setTimeout(pararSonido, 3000); toast('Así suena la alarma elegida', 'ok'); }

// ---- Navegación más fluida entre pestañas ----
// La app es multipágina (cada pestaña recarga). Para que el cambio se sienta
// instantáneo: barra de progreso al tocar, resaltado inmediato del ítem tocado
// y prefetch del destino al pasar/tocar (así el navegador ya lo tiene listo).
(function () {
  const bar = document.createElement('div');
  bar.id = 'nav-progress';
  document.addEventListener('DOMContentLoaded', () => document.body.appendChild(bar));
  if (document.body) document.body.appendChild(bar);

  function esInterno(a) {
    const href = a.getAttribute('href') || '';
    if (!href || href.startsWith('#') || href.startsWith('http') ||
        href.startsWith('/api/') || href.startsWith('mailto:') ||
        href.startsWith('tel:') || a.target === '_blank' ||
        a.hasAttribute('download')) return false;
    return true;
  }

  // Click en un link interno: barra + resaltado inmediato en la nav.
  document.addEventListener('click', (e) => {
    const a = e.target.closest && e.target.closest('a[href]');
    if (!a || !esInterno(a)) return;
    bar.classList.remove('done');
    // reinicia la animación
    void bar.offsetWidth;
    bar.classList.add('go');
    const grupo = a.closest('.side-nav') ? '.side-nav a' : (a.closest('.mbot') ? '.mbot a' : null);
    if (grupo) {
      document.querySelectorAll(grupo).forEach(x => x.classList.remove('on'));
      a.classList.add('on');
    }
  }, true);

  // Prefetch al pasar el mouse o tocar los ítems de navegación.
  const yaVisto = {};
  function prefetch(href) {
    if (!href || yaVisto[href]) return;
    yaVisto[href] = 1;
    const l = document.createElement('link');
    l.rel = 'prefetch'; l.href = href;
    document.head.appendChild(l);
  }
  function armarPrefetch() {
    document.querySelectorAll('.side-nav a, .mbot a').forEach(a => {
      if (!esInterno(a)) return;
      const href = a.getAttribute('href');
      a.addEventListener('mouseenter', () => prefetch(href));
      a.addEventListener('touchstart', () => prefetch(href), { passive: true });
    });
  }
  if (document.readyState !== 'loading') armarPrefetch();
  else document.addEventListener('DOMContentLoaded', armarPrefetch);

  // Al terminar de cargar la página nueva, completa la barra.
  window.addEventListener('pageshow', () => { bar.classList.add('done'); bar.classList.remove('go'); });
})();

// ---- Agregar turnos (modal compartido: ficha + agenda) ----
// abrirAgregarTurnos(pid, nombre, onDone):
//  - con pid: modo ficha (paciente ya elegido, precarga sus días/horarios)
//  - sin pid: modo agenda (aparece buscador de paciente)
let AT_PID = null, AT_PICKER = null, AT_MODO = 'auto', AT_ONDONE = null;
let AT_DIAS = new Set();          // días de la semana elegidos (0=Lun)
let AT_HORAS = {};                // hora por día de la semana {wd: "HH:MM"}
let AT_ESTRATEGIA = 'hora';       // 'hora' (elijo el horario) | 'recomendado'
let AT_PLAN_MODO = 'nuevo';       // 'nuevo' | 'extender'
let AT_PROP = null;               // última propuesta mostrada (filas)
let AT_PROP_ABIERTA = false;      // si el panel de propuesta está desplegado
let AT_PROP_VISTA = 'lista';      // 'lista' | 'calendario'
let AT_QUEDAN = 0;                // sesiones que le quedan al paciente
const AT_DUR = 30;                // duración fija (siempre 30 min)

// Llena un <select> con las sedes disponibles y marca la sede activa.
function poblarSelectSede(selId, sedeElegida) {
  const sel = document.getElementById(selId);
  if (!sel) return;
  const sedes = window.SEDES || [];
  const actual = sedeElegida != null ? sedeElegida : window.SEDE_ACTUAL;
  sel.innerHTML = sedes.map(s =>
    `<option value="${s.id}" ${s.id == actual ? 'selected' : ''}>${escapeHtml(s.nombre)}</option>`
  ).join('');
  // Si hay una sola sede, no tiene sentido mostrar el selector.
  const wrap = sel.closest('.field');
  if (wrap) wrap.style.display = sedes.length > 1 ? '' : 'none';
}

function abrirAgregarTurnos(pid, nombre, onDone) {
  if (!document.getElementById('modal-agturnos')) return;
  AT_PID = pid || null; AT_ONDONE = onDone || null;
  const buscarWrap = document.getElementById('at-buscar-wrap');
  if (AT_PID) {
    buscarWrap.style.display = 'none';
    document.getElementById('at-titulo').textContent = 'Agregar turnos' + (nombre ? ' — ' + nombre : '');
  } else {
    buscarWrap.style.display = '';
    document.getElementById('at-titulo').textContent = 'Agregar turnos';
    document.getElementById('at-buscar').value = '';
    document.getElementById('at-resultados').innerHTML = '';
    document.getElementById('at-elegido').textContent = '';
  }
  document.getElementById('at-cantidad').value = '';
  document.getElementById('at-desde').value = new Date().toISOString().slice(0, 10);
  atError('');
  document.getElementById('at-propuesta').innerHTML = '';
  document.getElementById('at-manual-rows').innerHTML = '';
  AT_DIAS = new Set(); AT_HORAS = {}; AT_PROP = null; AT_PROP_ABIERTA = false;
  AT_PROP_VISTA = 'lista'; AT_QUEDAN = 0;
  atPlanModo('nuevo');
  atRenderDiasChips();
  atEstrategia('hora');
  atRenderHorasRows();
  document.getElementById('at-plan-info').textContent = '';
  poblarSelectSede('at-sede');
  atModo('auto');
  atAgregarFila();
  abrirModal('modal-agturnos');
  if (AT_PID) atCargarPlanPaciente(AT_PID);
}

async function atCargarPlanPaciente(pid) {
  try {
    const p = await apiGet('/api/paciente/' + pid + '/resumen');
    atAplicarPlanPaciente(p);
  } catch (e) {}
}

// Precarga los días/horas/cantidad del paciente en el flujo de plan.
function atAplicarPlanPaciente(p) {
  AT_QUEDAN = p.sesiones_quedan > 0 ? p.sesiones_quedan : 0;
  // En "recomendados" los días los elige la app: no precargo los del paciente.
  if (AT_ESTRATEGIA !== 'recomendado') {
    AT_DIAS = new Set(p.dias_idx || []);
    // Hora por cada día que ya tenía cargada.
    AT_HORAS = {};
    const hs = p.horarios || {};
    (p.dias_idx || []).forEach(i => {
      const h = hs[i] || hs[String(i)];
      if (h) AT_HORAS[i] = h;
    });
  }
  atRenderDiasChips();
  atRenderHorasRows();
  if (!document.getElementById('at-cantidad').value)
    document.getElementById('at-cantidad').value = AT_QUEDAN || '';
  atSetDesde(p.ultimo_turno);
  atPlanInfo();
}

// Si el paciente ya tiene turnos futuros, arranca el día siguiente al último.
function atSetDesde(ultimo) {
  const hoy = new Date().toISOString().slice(0, 10);
  let desde = hoy;
  if (ultimo && ultimo >= hoy) {
    const d = new Date(ultimo + 'T12:00:00'); d.setDate(d.getDate() + 1);
    desde = d.toISOString().slice(0, 10);
  }
  document.getElementById('at-desde').value = desde;
}

function atModo(m) {
  AT_MODO = m;
  document.getElementById('at-modo-auto').style.display = m === 'auto' ? '' : 'none';
  document.getElementById('at-modo-manual').style.display = m === 'manual' ? '' : 'none';
  document.getElementById('at-tab-auto').classList.toggle('on', m === 'auto');
  document.getElementById('at-tab-manual').classList.toggle('on', m === 'manual');
  atBotonConfirmar();
}

// ---- Plan de sesiones (propone todo y confirmás) ----
function atPlanModo(m) {
  AT_PLAN_MODO = m;
  document.getElementById('at-pm-nuevo').classList.toggle('on', m === 'nuevo');
  document.getElementById('at-pm-ext').classList.toggle('on', m === 'extender');
  // "Extender" calcula la cantidad solo (las que faltan): se oculta el input.
  document.getElementById('at-cantidad-wrap').style.display = m === 'extender' ? 'none' : '';
  atPlanInfo();
  atInvalidarPropuesta();
}

function atPlanInfo() {
  const el = document.getElementById('at-plan-info');
  if (!el) return;
  if (!AT_PID) { el.textContent = ''; return; }
  if (AT_PLAN_MODO === 'extender')
    el.textContent = `Le quedan ${AT_QUEDAN} sesión(es). Voy a agendar las que falten (las que aún no tienen turno).`;
  else
    el.textContent = AT_QUEDAN ? `Le quedan ${AT_QUEDAN} sesión(es) por hacer.` : '';
}

const DIAS_FULL_JS = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo'];

// Los chips se dibujan SIEMPRE desde el estado (así no se desincronizan).
function atRenderDiasChips() {
  const cont = document.getElementById('at-dias-chips');
  if (!cont) return;
  cont.innerHTML = DIAS_ABBR.map((d, i) =>
    `<button type="button" class="dia-chip ${AT_DIAS.has(i) ? 'on' : ''}" data-i="${i}" onclick="atToggleDiaChip(${i})">${d}</button>`
  ).join('');
}
function atToggleDiaChip(i) {
  const agregado = !AT_DIAS.has(i);
  if (agregado) AT_DIAS.add(i);
  else { AT_DIAS.delete(i); delete AT_HORAS[i]; }
  atRenderDiasChips();
  atRenderHorasRows();
  // Al elegir un día, se despliega solo su menú de horarios.
  if (agregado) atAbrirPickDia(i);
  atInvalidarPropuesta();
}

// Cómo armar los turnos: "hora" (elijo el horario) o "recomendado" (sólo libres).
function atEstrategia(e) {
  AT_ESTRATEGIA = e;
  document.getElementById('at-es-hora').classList.toggle('on', e === 'hora');
  document.getElementById('at-es-recom').classList.toggle('on', e === 'recomendado');
  // En "recomendado" la app propone los días: se ocultan los chips de días.
  const diasField = document.getElementById('at-dias-field');
  if (diasField) diasField.style.display = e === 'recomendado' ? 'none' : '';
  const recom = document.getElementById('at-recom-wrap');
  if (recom) recom.style.display = e === 'recomendado' ? '' : 'none';
  const hints = {
    hora: 'Elegí los días y, en cada uno, el horario. Te muestro todas las horas con el semáforo (verde libre, amarillo casi lleno, rojo lleno).',
    recomendado: 'Sólo los horarios libres (en verde) de cada día, para ofrecer. Tocá el ✓ en los que el paciente acepte.',
  };
  const h = document.getElementById('at-es-hint');
  if (h) h.textContent = hints[e] || '';
  // Al cambiar de modo arranco el patrón de horas limpio.
  AT_HORAS = {};
  if (e === 'recomendado') { AT_DIAS = new Set(); atRenderDiasChips(); atCargarRecom(); }
  atRenderHorasRows();
  atInvalidarPropuesta();
}

// Texto de disponibilidad de un horario.
function atTxtLibres(libres) {
  if (libres >= 90) return 'libre';
  if (libres <= 0) return 'lleno';
  return libres + ' libre' + (libres > 1 ? 's' : '');
}

// Un bloque por día elegido. En las dos estrategias es un desplegable: se abre al
// tocar el día y, al elegir la hora, se cierra y queda sólo esa hora en pantalla.
function atRenderHorasRows() {
  const wrap = document.getElementById('at-horas-wrap');
  const rows = document.getElementById('at-horas-rows');
  const label = document.getElementById('at-horas-label');
  if (!rows) return;
  const dias = [...AT_DIAS].sort((a, b) => a - b);
  const mostrar = AT_ESTRATEGIA === 'hora' && dias.length;
  if (wrap) wrap.style.display = mostrar ? '' : 'none';
  if (!mostrar) { rows.innerHTML = ''; return; }
  if (label) label.textContent = 'Horario de cada día (en punto o y media)';
  rows.innerHTML = dias.map(i => `
    <div class="at-pick-dia" data-wd="${i}">
      <button type="button" class="at-pick-head" onclick="atTogglePickDia(${i})">
        <span class="at-pick-lbl">${DIAS_FULL_JS[i]}</span>
        <span class="at-pick-val" id="at-pick-val-${i}">${AT_HORAS[i] || 'Elegir horario'}</span>
        <span class="at-pick-arrow" id="at-pick-arr-${i}">▾</span>
      </button>
      <div class="at-pick-ops" id="at-pick-${i}" style="display:none;"></div>
    </div>`).join('');
}

// Abre/cierra el desplegable de horarios de un día (carga las opciones la 1ª vez).
function atTogglePickDia(wd) {
  const cont = document.getElementById('at-pick-' + wd);
  if (!cont) return;
  const abrir = cont.style.display === 'none';
  if (abrir) atAbrirPickDia(wd); else atCerrarPickDia(wd);
}
function atAbrirPickDia(wd) {
  const cont = document.getElementById('at-pick-' + wd);
  if (!cont) return;
  cont.style.display = '';
  const arr = document.getElementById('at-pick-arr-' + wd);
  if (arr) arr.textContent = '▴';
  if (!cont.dataset.cargado) {
    cont.innerHTML = '<span class="hint">Cargando horarios…</span>';
    atCargarOpcionesDia(wd);
  }
}
function atCerrarPickDia(wd) {
  const cont = document.getElementById('at-pick-' + wd);
  if (cont) cont.style.display = 'none';
  const arr = document.getElementById('at-pick-arr-' + wd);
  if (arr) arr.textContent = '▾';
}

// Trae TODOS los horarios del próximo día de esa semana (en punto y y media),
// cada uno con su semáforo: verde libre, amarillo casi lleno, rojo lleno.
async function atCargarOpcionesDia(wd) {
  const cont = document.getElementById('at-pick-' + wd);
  if (!cont) return;
  const desde = document.getElementById('at-desde').value;
  const d = await apiGet('/api/horas_dia?sede=' + atSedeElegida() + '&weekday=' + wd +
    (desde ? '&desde=' + desde : '') + '&todos=1');
  if (!d.opciones || !d.opciones.length) {
    cont.innerHTML = '<span class="hint">El centro no abre ese día.</span>'; return;
  }
  cont.dataset.cargado = '1';
  cont.innerHTML = d.opciones.map(o => {
    const cls = o.color === 'verde' ? 'libre' : (o.color === 'amar' ? 'casi' : 'lleno');
    const lleno = o.color === 'rojo';
    return `<button type="button" class="at-slot ${cls} ${AT_HORAS[wd] === o.hora ? 'sel' : ''}"
       data-h="${o.hora}" ${lleno ? 'disabled' : ''} onclick="atElegirHoraDia(${wd},'${o.hora}')">${o.hora}
       <small>${atTxtLibres(o.libres)}</small></button>`;
  }).join('');
}

// Al elegir la hora, queda sólo esa hora en pantalla (se cierra el desplegable).
function atElegirHoraDia(wd, hora) {
  AT_HORAS[wd] = hora;
  document.querySelectorAll('#at-pick-' + wd + ' .at-slot').forEach(b =>
    b.classList.toggle('sel', b.dataset.h === hora));
  const val = document.getElementById('at-pick-val-' + wd);
  if (val) val.textContent = hora;
  atCerrarPickDia(wd);
  atInvalidarPropuesta();
}

// ---- Recomendados: los horarios más vacíos de cada día hábil, para ofrecer ----
async function atCargarRecom() {
  const cont = document.getElementById('at-recom-list');
  if (!cont) return;
  cont.innerHTML = '<div class="hint">Buscando los horarios más vacíos…</div>';
  const desde = document.getElementById('at-desde').value;
  const d = await apiGet('/api/recomendados?sede=' + atSedeElegida() + (desde ? '&desde=' + desde : ''));
  if (!d.items || !d.items.length) { cont.innerHTML = '<div class="empty">No hay horarios para recomendar.</div>'; return; }
  cont.innerHTML = d.items.map(it => {
    const sel = AT_DIAS.has(it.weekday);
    const horaSel = sel ? AT_HORAS[it.weekday] : it.hora;
    const ops = (it.opciones || [{ hora: it.hora, libres: it.libres, color: it.color }]);
    return `<div class="at-recom-item ${it.color === 'verde' ? 'verde' : 'amar'} ${sel ? 'sel' : ''}" data-wd="${it.weekday}">
      <span class="at-recom-dia">${it.dia}</span>
      <select class="input at-recom-sel" data-wd="${it.weekday}" onchange="atRecomHora(${it.weekday}, this.value)">
        ${ops.map(o => `<option value="${o.hora}" ${o.hora === horaSel ? 'selected' : ''}>${o.hora} · ${atTxtLibres(o.libres)}</option>`).join('')}
      </select>
      <button type="button" class="at-recom-check" onclick="atToggleRecom(${it.weekday})" title="Ofrecer / aceptar">✓</button>
    </div>`;
  }).join('');
  atRecomInfo();
}
// Cambiar la hora del desplegable de un día (si ya estaba aceptado, la actualiza).
function atRecomHora(wd, hora) {
  if (AT_DIAS.has(wd)) { AT_HORAS[wd] = hora; atInvalidarPropuesta(); }
}
// Aceptar / sacar un día (queda como turno fijo semanal a la hora del desplegable).
function atToggleRecom(wd) {
  const sel = document.querySelector(`#at-recom-list .at-recom-sel[data-wd="${wd}"]`);
  const hora = sel ? sel.value : null;
  if (AT_DIAS.has(wd)) { AT_DIAS.delete(wd); delete AT_HORAS[wd]; }
  else if (hora) { AT_DIAS.add(wd); AT_HORAS[wd] = hora; }
  const b = document.querySelector(`#at-recom-list .at-recom-item[data-wd="${wd}"]`);
  if (b) b.classList.toggle('sel', AT_DIAS.has(wd));
  atRecomInfo();
  atInvalidarPropuesta();
}
function atRecomInfo() {
  const h = document.getElementById('at-es-hint');
  const n = AT_DIAS.size;
  if (h) h.textContent = n
    ? `Elegidos ${n} horario(s) fijo(s) por semana. Se repiten hasta completar las sesiones.`
    : 'Elegí la hora de cada día y tocá ✓ en los que el paciente acepte.';
}

// Si cambian los parámetros, la propuesta anterior queda vieja.
function atInvalidarPropuesta() {
  if (!AT_PROP && !AT_PROP_ABIERTA) return;
  AT_PROP = null; AT_PROP_ABIERTA = false;
  const cont = document.getElementById('at-propuesta');
  if (cont) cont.innerHTML = '';
  atBotonConfirmar(); atBotonVerPropuesta();
}

// Botón del pie: cambia según haya o no una propuesta a la vista.
function atBotonConfirmar() {
  const b = document.getElementById('at-confirmar');
  if (!b) return;
  if (AT_MODO !== 'auto') { b.textContent = 'Agregar turnos'; return; }
  if (AT_PROP && AT_PROP.length) {
    const n = AT_PROP.filter(r => !r.removed && r.estado !== 'feriado' && r.hora).length;
    b.textContent = `Confirmar y agendar (${n})`;
  } else {
    b.textContent = 'Agregar turnos';
  }
}
// Texto del botón "Ver / Ocultar propuesta".
function atBotonVerPropuesta() {
  const b = document.getElementById('at-ver-prop');
  if (b) b.textContent = AT_PROP_ABIERTA ? 'Ocultar propuesta' : 'Ver propuesta de turnos';
}

async function atProponer() {
  const cont = document.getElementById('at-propuesta');
  // Toggle: si ya está desplegada, la cierro.
  if (AT_PROP_ABIERTA) {
    AT_PROP_ABIERTA = false;
    cont.innerHTML = '';
    atBotonVerPropuesta(); atBotonConfirmar();
    return;
  }
  atError('');
  if (!AT_PID) { toast('Elegí un paciente', 'alert'); return; }
  if (!AT_DIAS.size) {
    atError(AT_ESTRATEGIA === 'recomendado'
      ? 'Tocá al menos un horario recomendado.'
      : 'Elegí al menos un día de la semana.'); return;
  }
  const horarios = {};
  for (const i of AT_DIAS) { if (AT_HORAS[i]) horarios[i] = AT_HORAS[i]; }
  if ([...AT_DIAS].some(i => !horarios[i])) {
    atError('Falta elegir el horario de algún día.'); return;
  }
  cont.innerHTML = '<div class="hint">Armando la propuesta…</div>';
  // El patrón (día → hora) ya está concreto: se genera recurrente semana a semana.
  const body = {
    paciente_id: AT_PID, dias: [...AT_DIAS], horarios,
    estrategia: 'hora',
    desde: document.getElementById('at-desde').value,
    modo: AT_PLAN_MODO, sede_id: atSedeElegida(),
  };
  if (AT_PLAN_MODO === 'nuevo') body.cantidad = document.getElementById('at-cantidad').value;
  const resp = await fetch('/api/plan_propuesta', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  let r = {}; try { r = await resp.json(); } catch (e) {}
  if (!resp.ok || r.ok === false) { cont.innerHTML = ''; atError(r.error || 'No se pudo armar la propuesta'); return; }
  // Para las llenas con alternativa, arranco con la alternativa cargada.
  AT_PROP = (r.items || []).map(it => {
    if (it.estado === 'lleno' && it.alternativa) { it.pedida = it.hora; it.hora = it.alternativa; }
    it.removed = false;
    return it;
  });
  AT_PROP_RESUMEN = r.resumen || {};
  AT_PROP_ABIERTA = true;
  atRenderPropuesta();
  atBotonConfirmar(); atBotonVerPropuesta();
}

let AT_PROP_RESUMEN = {};
function atPropVista(v) { AT_PROP_VISTA = v; atRenderPropuesta(); }

function atRenderPropuesta() {
  const cont = document.getElementById('at-propuesta');
  if (!AT_PROP) { cont.innerHTML = ''; return; }
  const rs = AT_PROP_RESUMEN || {};
  let head = `<div class="at-prop-head">Propuesta: <b>${rs.ok || 0}</b> ok`;
  if (rs.llenos) head += ` · <b class="rojo">${rs.llenos}</b> con horario lleno`;
  if (rs.feriados) head += ` · <b>${rs.feriados}</b> feriado(s) reprogramado(s)`;
  head += '. Ajustá lo que quieras y confirmá.</div>';
  const toggle = `<div class="seg seg-sm at-prop-vista">
      <button type="button" class="${AT_PROP_VISTA === 'lista' ? 'on' : ''}" onclick="atPropVista('lista')">Lista</button>
      <button type="button" class="${AT_PROP_VISTA === 'calendario' ? 'on' : ''}" onclick="atPropVista('calendario')">Calendario</button>
    </div>`;
  const cuerpo = AT_PROP_VISTA === 'calendario' ? atPropCalendario() : atPropLista();
  cont.innerHTML = head + toggle + cuerpo;
  if (AT_PROP_VISTA === 'lista') {
    cont.querySelectorAll('.at-prop-hora').forEach(inp => inp.oninput = () => {
      AT_PROP[+inp.dataset.idx].hora = inp.value;
      atBotonConfirmar();
    });
  }
}

function atPropLista() {
  return AT_PROP.map((it, idx) => {
    if (it.removed) return '';
    const d = new Date(it.fecha + 'T12:00:00');
    const dd = d.toLocaleDateString('es-AR', { weekday: 'long', day: 'numeric', month: 'short' });
    const fecha = dd.charAt(0).toUpperCase() + dd.slice(1);
    if (it.estado === 'feriado')
      return `<div class="at-prop-row feriado">
        <div class="at-prop-info"><div class="at-prop-fecha">${fecha}</div>
        <span class="at-prop-tag">Feriado — se reprograma</span></div></div>`;
    const aviso = it.estado === 'lleno'
      ? (it.pedida ? `<span class="at-prop-tag rojo">Estaba lleno ${it.pedida} → sugerido</span>`
                   : `<span class="at-prop-tag rojo">Lleno — sin lugar ese día</span>`)
      : `<span class="at-prop-tag ok">Libre</span>`;
    return `<div class="at-prop-row ${it.estado}">
      <div class="at-prop-info"><div class="at-prop-fecha">${fecha}</div>${aviso}</div>
      <input class="input at-prop-hora" type="time" step="900" data-idx="${idx}" value="${it.hora || ''}">
      <button class="x" onclick="atQuitarProp(${idx})" title="Quitar">&times;</button></div>`;
  }).join('');
}

function atQuitarProp(idx) {
  if (AT_PROP[idx]) AT_PROP[idx].removed = true;
  atRenderPropuesta(); atBotonConfirmar();
}

// Vista calendario: mini-almanaque por mes con los días marcados y su hora.
function atPropCalendario() {
  const marcados = {};
  AT_PROP.forEach(it => { if (!it.removed) marcados[it.fecha] = { hora: it.hora, estado: it.estado }; });
  const fechas = AT_PROP.filter(it => !it.removed).map(it => it.fecha).sort();
  if (!fechas.length) return '<div class="hint">No quedaron turnos.</div>';
  // Meses únicos que aparecen.
  const meses = [];
  fechas.forEach(f => {
    const [y, m] = f.split('-').map(Number);
    if (!meses.some(x => x.y === y && x.m === m - 1)) meses.push({ y, m: m - 1 });
  });
  return `<div class="at-cal-leg">
      <span><i class="mini-dot on"></i> Va</span>
      <span><i class="mini-dot lleno"></i> Estaba lleno</span>
      <span><i class="mini-dot feriado"></i> Feriado</span>
    </div>` + meses.map(mm => atMiniMes(mm.y, mm.m, marcados)).join('');
}

function atMiniMes(y, m, marcados) {
  const primero = new Date(y, m, 1);
  const ndias = new Date(y, m + 1, 0).getDate();
  const offset = (primero.getDay() + 6) % 7;   // Lun=0
  const nombre = primero.toLocaleDateString('es-AR', { month: 'long', year: 'numeric' });
  const dow = ['L', 'M', 'M', 'J', 'V', 'S', 'D'].map(x => `<div class="mini-dow">${x}</div>`).join('');
  let cells = '';
  for (let i = 0; i < offset; i++) cells += '<div class="mini-cell vacio"></div>';
  for (let d = 1; d <= ndias; d++) {
    const fecha = `${y}-${String(m + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
    const mk = marcados[fecha];
    if (mk) {
      const cls = mk.estado === 'feriado' ? 'feriado' : (mk.estado === 'lleno' ? 'lleno' : 'on');
      cells += `<div class="mini-cell ${cls}"><span class="n">${d}</span>${mk.hora ? `<span class="h">${mk.hora}</span>` : ''}</div>`;
    } else {
      cells += `<div class="mini-cell"><span class="n">${d}</span></div>`;
    }
  }
  return `<div class="mini-mes"><div class="mini-tit">${nombre.charAt(0).toUpperCase() + nombre.slice(1)}</div>
    <div class="mini-grid">${dow}${cells}</div></div>`;
}

function atAgregarFila(fecha, hora) {
  const cont = document.getElementById('at-manual-rows');
  if (!cont) return;
  const div = document.createElement('div');
  div.className = 'at-manual-row';
  div.innerHTML =
    `<input class="input" type="date" value="${fecha || ''}">` +
    `<input class="input" type="time" step="900" value="${hora || ''}">` +
    `<button class="x" onclick="this.parentNode.remove()" title="Quitar">&times;</button>`;
  cont.appendChild(div);
}

// Búsqueda de paciente (delegado, porque el modal se incluye en varias páginas).
document.addEventListener('input', function (e) {
  if (!e.target) return;
  // Si cambian los parámetros del plan, la propuesta anterior queda vieja.
  if (['at-cantidad', 'at-desde'].includes(e.target.id)) atInvalidarPropuesta();
  if (e.target.id === 'at-buscar') {
    clearTimeout(window._atbt);
    const term = e.target.value.trim();
    window._atbt = setTimeout(async () => {
      const cont = document.getElementById('at-resultados');
      if (!term) { cont.innerHTML = ''; return; }
      const rows = await apiGet('/api/pacientes?q=' + encodeURIComponent(term));
      cont.innerHTML = rows.map(p => `
        <div class="list-item" style="cursor:pointer;" onclick='atElegirPac(${JSON.stringify(p)})'>
          <div class="avatar">${iniciales(p.nombre_completo)}</div>
          <div class="li-main"><div class="li-name">${escapeHtml(p.nombre_completo)}</div>
          <div class="li-sub">${p.sesiones_quedan} sesiones restantes${p.dias ? ' · ' + escapeHtml(p.dias) : ''}</div></div>
        </div>`).join('') || '<div class="empty">Sin resultados</div>';
    }, 220);
  }
});

function atElegirPac(p) {
  AT_PID = p.id;
  document.getElementById('at-resultados').innerHTML = '';
  document.getElementById('at-buscar').value = p.nombre_completo;
  document.getElementById('at-elegido').innerHTML = '✓ ' + escapeHtml(p.nombre_completo) + ' seleccionado';
  document.getElementById('at-propuesta').innerHTML = '';
  AT_PROP = null; AT_PROP_ABIERTA = false;
  atAplicarPlanPaciente(p);
  atBotonConfirmar(); atBotonVerPropuesta();
}

// Cargar un paciente nuevo desde el modal de "Agregar turnos" y dejarlo elegido.
function atNuevoPaciente() {
  abrirNuevoPaciente((id, nombre) => {
    atElegirPac({
      id: id, nombre_completo: nombre, sesiones_quedan: 0,
      dias_idx: [], horarios: {}, ultimo_turno: null,
    });
  });
}

function atSedeElegida() {
  const sel = document.getElementById('at-sede');
  return sel && sel.value ? +sel.value : (window.SEDE_ACTUAL || null);
}

// Mensaje de error (rojo) dentro del modal de turnos, sin cerrarlo.
function atError(msg) {
  const e = document.getElementById('at-error');
  if (!e) return;
  e.textContent = msg || '';
  e.style.display = msg ? '' : 'none';
}
// Crea un turno sin mostrar toast (para poder manejar "lleno" a mano).
async function atPostTurno(body) {
  const r = await fetch('/api/turno', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  let d = {}; try { d = await r.json(); } catch (e) {}
  return { ok: r.ok && d.ok !== false, lleno: !!d.lleno, feriado: !!d.feriado,
           error: d.error || 'No se pudo dar el turno' };
}

async function atGenerar() {
  atError('');
  if (!AT_PID) { toast('Elegí un paciente', 'alert'); return; }
  const dur = AT_DUR;   // duración fija (30 min)
  const sede_id = atSedeElegida();
  if (AT_MODO === 'auto') {
    // Si todavía no hay propuesta a la vista, primero la armo para revisar.
    if (!AT_PROP || !AT_PROP.length) { atProponer(); return; }
    // Recolecto las filas desde el estado (sirve en vista lista y calendario).
    const rows = AT_PROP
      .filter(it => !it.removed && it.estado !== 'feriado' && it.fecha && it.hora)
      .map(it => ({ fecha: it.fecha, hora: it.hora }));
    if (!rows.length) { atError('No quedaron turnos para agendar.'); return; }
    const resp = await fetch('/api/plan_confirmar', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ paciente_id: AT_PID, rows, duracion: dur, sede_id }),
    });
    let r = {}; try { r = await resp.json(); } catch (e) {}
    if (!resp.ok || r.ok === false) { atError(r.error || 'No se pudieron asignar los turnos'); return; }
    if (r.llenos && r.llenos.length) {
      // Algún horario se llenó recién: aviso en rojo, el modal queda abierto.
      atError(r.aviso || 'Algunos horarios quedaron llenos.');
      if (AT_ONDONE) AT_ONDONE();
      return;
    }
    cerrarModal('modal-agturnos');
    toast(`${r.creados} turno(s) agregados ✓`, 'ok');
  } else {
    const filas = [].slice.call(document.querySelectorAll('#at-manual-rows .at-manual-row'));
    const turnos = filas.map(f => {
      const ins = f.querySelectorAll('input');
      return { fecha: ins[0].value, hora: ins[1].value };
    }).filter(t => t.fecha);
    if (!turnos.length) { toast('Agregá al menos una fecha', 'alert'); return; }
    let n = 0; const problemas = [];
    for (const t of turnos) {
      const r = await atPostTurno({ paciente_id: AT_PID, fecha: t.fecha, hora: t.hora, duracion: dur, sede_id });
      if (r.ok) n++; else problemas.push(r.error);
    }
    if (problemas.length) {
      // Horario lleno / feriado: mensaje en rojo y el modal QUEDA ABIERTO.
      atError((n ? (n + ' turno(s) agregados. ') : '') + problemas.join(' · '));
      if (n && AT_ONDONE) AT_ONDONE();
      return;
    }
    cerrarModal('modal-agturnos');
    toast(n + ' turno(s) agregados ✓', 'ok');
  }
  if (AT_ONDONE) AT_ONDONE();
}

// ---- Ofrecer turno libre: próximos horarios libres (dentro de Agregar turnos) ----
let AT_OF_DIAS = new Set();
function atToggleOfrecer() {
  const p = document.getElementById('at-of-panel');
  const abrir = p.style.display === 'none';
  p.style.display = abrir ? '' : 'none';
  document.getElementById('at-of-flecha').textContent = abrir ? '▴' : '▾';
  if (abrir && !document.getElementById('at-of-dias').children.length) {
    AT_OF_DIAS = new Set();
    document.getElementById('at-of-dias').innerHTML = DIAS_ABBR.map((d, i) =>
      `<button type="button" class="dia-chip" data-i="${i}" onclick="atOfToggleDia(${i})">${d}</button>`).join('');
    let opts = '<option value="">Cualquier hora</option>';
    for (let m = 7 * 60; m <= 21 * 60; m += 15) {
      const h = `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;
      opts += `<option value="${h}">${h}</option>`;
    }
    document.getElementById('at-of-hora').innerHTML = opts;
  }
}
function atOfToggleDia(i) {
  if (AT_OF_DIAS.has(i)) AT_OF_DIAS.delete(i); else AT_OF_DIAS.add(i);
  const b = document.querySelector(`#at-of-dias .dia-chip[data-i="${i}"]`);
  if (b) b.classList.toggle('on');
}
async function atBuscarOfrecer() {
  const cont = document.getElementById('at-of-res');
  const dias = [...AT_OF_DIAS].join(',');
  const hora = document.getElementById('at-of-hora').value;
  const sede = atSedeElegida();
  cont.innerHTML = '<div class="hint">Buscando…</div>';
  const d = await apiGet('/api/proximos_libres?sede=' + sede +
    (dias ? '&dias=' + dias : '') + (hora ? '&hora=' + hora : '') + '&limite=12');
  if (!d.items.length) { cont.innerHTML = '<div class="empty">No hay lugares libres con ese filtro en los próximos días.</div>'; return; }
  cont.innerHTML = d.items.map(it => {
    let dd = new Date(it.fecha + 'T12:00:00').toLocaleDateString('es-AR', { weekday: 'long', day: 'numeric', month: 'long' });
    dd = dd.charAt(0).toUpperCase() + dd.slice(1);
    return `<div class="of-item"><div class="of-info"><b>${dd}</b><span>${it.hora} · ${it.libres} libre${it.libres > 1 ? 's' : ''}</span></div>
      <button type="button" class="btn btn-primary btn-sm" onclick="atAgregarOfrecido('${it.fecha}','${it.hora}')">Agregar</button></div>`;
  }).join('');
}
// Agrega el horario elegido a la lista manual, listo para confirmar.
function atAgregarOfrecido(fecha, hora) {
  atAgregarFila(fecha, hora);
  atError('');
  toast('Agregado: ' + fecha + ' ' + hora + ' ✓', 'ok');
}
