// Utilidades compartidas por todas las pantallas.

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
  setTimeout(() => splash.classList.add('hide'), 3300);
  setTimeout(() => { splash.remove(); document.body.classList.remove('splashing'); }, 3950);
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

function cerrarModal(id) { document.getElementById(id).classList.remove('show'); }
function abrirModal(id) { document.getElementById(id).classList.add('show'); }

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
           <input type="time" class="input" data-dia="${i}" value="${state.horarios[i] || ''}">
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
let NP_PICKER = null;
function abrirNuevoPaciente(onSaved) {
  if (!document.getElementById('modal-paciente')) return;
  ['np-nombre', 'np-apellido', 'np-dni', 'np-telefono', 'np-obra',
   'np-diagnostico', 'np-notas'].forEach(id => {
    const el = document.getElementById(id); if (el) el.value = '';
  });
  document.getElementById('np-tot').value = '0';
  document.getElementById('np-usadas').value = '0';
  const desde = document.getElementById('np-desde');
  if (desde) desde.value = new Date().toISOString().slice(0, 10);
  NP_PICKER = crearDiasPicker('np-dias-picker', 'np-dias-rows');
  NP_CB = onSaved || null;
  abrirModal('modal-paciente');
  setTimeout(() => document.getElementById('np-nombre').focus(), 100);
}

async function guardarNuevoPaciente() {
  const v = id => (document.getElementById(id) || {}).value || '';
  const plan = NP_PICKER ? NP_PICKER.getData() : { dias: [], horarios: {} };
  const body = {
    nombre: v('np-nombre'), apellido: v('np-apellido'), dni: v('np-dni'),
    telefono: v('np-telefono'), obra_social: v('np-obra'),
    diagnostico: v('np-diagnostico'), sesiones_totales: v('np-tot'),
    sesiones_usadas: v('np-usadas'),
    dias: plan.dias.map(i => DIAS_ABBR[i]).join(', '), notas: v('np-notas'),
  };
  if (!body.nombre.trim() || !body.apellido.trim()) {
    toast('Nombre y apellido son obligatorios', 'alert'); return;
  }
  const r = await api('/api/paciente', body);

  // Si eligió días, genera los turnos automáticamente.
  if (plan.dias.length) {
    const tot = parseInt(v('np-tot'), 10) || 0;
    const usadas = parseInt(v('np-usadas'), 10) || 0;
    const cantidad = Math.max(0, tot - usadas);
    if (cantidad > 0) {
      await api('/api/plan', {
        paciente_id: r.id, dias: plan.dias, horarios: plan.horarios,
        desde: v('np-desde'), cantidad,
      });
    }
  }
  toast('Paciente guardado ✓', 'ok');
  cerrarModal('modal-paciente');
  if (NP_CB) NP_CB(r.id, (body.nombre + ' ' + body.apellido).trim());
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
function probarAlarma() { sonarContinuo(); setTimeout(pararSonido, 3000); toast('🔊 Así suena la alarma elegida', 'ok'); }

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
  document.getElementById('at-preview').textContent = '';
  document.getElementById('at-manual-rows').innerHTML = '';
  poblarSelectSede('at-sede');
  AT_PICKER = crearDiasPicker('at-dias-picker', 'at-dias-rows');
  atModo('auto');
  atAgregarFila();
  abrirModal('modal-agturnos');
  if (AT_PID) atCargarPlanPaciente(AT_PID);
}

async function atCargarPlanPaciente(pid) {
  try {
    const p = await apiGet('/api/paciente/' + pid + '/resumen');
    if (AT_PICKER) AT_PICKER.setData(p.dias_idx || [], p.horarios || {});
    if (!document.getElementById('at-cantidad').value)
      document.getElementById('at-cantidad').value = p.sesiones_quedan > 0 ? p.sesiones_quedan : '';
    atSetDesde(p.ultimo_turno);
    atPreview();
  } catch (e) {}
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
}

function atAgregarFila(fecha, hora) {
  const cont = document.getElementById('at-manual-rows');
  if (!cont) return;
  const div = document.createElement('div');
  div.className = 'at-manual-row';
  div.innerHTML =
    `<input class="input" type="date" value="${fecha || ''}">` +
    `<input class="input" type="time" value="${hora || ''}">` +
    `<button class="x" onclick="this.parentNode.remove()" title="Quitar">&times;</button>`;
  cont.appendChild(div);
}

function atPreview() {
  const el = document.getElementById('at-preview');
  if (!el) return;
  const cant = parseInt(document.getElementById('at-cantidad').value, 10);
  const data = AT_PICKER ? AT_PICKER.getData() : { dias: [] };
  if (!data.dias.length || !cant) { el.textContent = ''; return; }
  const dias = data.dias.map(i => DIAS_ABBR[i]).join(', ');
  el.textContent = `Se generarán ${cant} turno(s) los días ${dias}, desde el ${document.getElementById('at-desde').value}.`;
}

// Búsqueda de paciente y preview (delegado, porque el modal se incluye en varias páginas).
document.addEventListener('input', function (e) {
  if (!e.target) return;
  if (e.target.id === 'at-cantidad' || e.target.id === 'at-desde') atPreview();
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
  document.getElementById('at-cantidad').value = p.sesiones_quedan > 0 ? p.sesiones_quedan : '';
  if (AT_PICKER) AT_PICKER.setData(p.dias_idx || [], p.horarios || {});
  atSetDesde(p.ultimo_turno);
  atPreview();
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

async function atGenerar() {
  if (!AT_PID) { toast('Elegí un paciente', 'alert'); return; }
  const dur = document.getElementById('at-dur').value;
  const sede_id = atSedeElegida();
  if (AT_MODO === 'auto') {
    const data = AT_PICKER ? AT_PICKER.getData() : { dias: [], horarios: {} };
    if (!data.dias.length) { toast('Elegí al menos un día', 'alert'); return; }
    const cant = document.getElementById('at-cantidad').value;
    if (!cant || +cant <= 0) { toast('Poné cuántas sesiones agregar', 'alert'); return; }
    const r = await api('/api/plan', {
      paciente_id: AT_PID, dias: data.dias, horarios: data.horarios,
      desde: document.getElementById('at-desde').value, cantidad: cant,
      duracion: dur, sede_id,
    });
    cerrarModal('modal-agturnos');
    let msg = `${r.creados} turno(s) agregados ✓`;
    if (r.saltados) msg += ` · ${r.saltados} saltado(s) por horario lleno`;
    toast(msg, r.saltados ? 'alert' : 'ok');
  } else {
    const filas = [].slice.call(document.querySelectorAll('#at-manual-rows .at-manual-row'));
    const turnos = filas.map(f => {
      const ins = f.querySelectorAll('input');
      return { fecha: ins[0].value, hora: ins[1].value };
    }).filter(t => t.fecha);
    if (!turnos.length) { toast('Agregá al menos una fecha', 'alert'); return; }
    let n = 0, llenos = 0;
    for (const t of turnos) {
      try {
        await api('/api/turno', { paciente_id: AT_PID, fecha: t.fecha, hora: t.hora, duracion: dur, sede_id });
        n++;
      } catch (e) { llenos++; }  // horario lleno (tope): lo salta y sigue
    }
    cerrarModal('modal-agturnos');
    let msg = `${n} turno(s) agregados ✓`;
    if (llenos) msg += ` · ${llenos} no entraron (horario lleno)`;
    toast(msg, llenos ? 'alert' : 'ok');
  }
  if (AT_ONDONE) AT_ONDONE();
}
