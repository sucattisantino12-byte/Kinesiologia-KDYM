// Pantalla de recepción: estado en vivo de boxes, sala de espera, agenda y stats.

let ESTADO = null;
let AVISADOS = new Set();   // boxes ya avisados como "terminados" (aviso inicial)
let REPEAT_LAST = {};       // último re-beep por box (para repetir alarma)
let TURNO_INICIAR = null;   // turno pendiente de asignar a un box
let ABOX_BOX = null;        // box elegido para "poner paciente directo"
let CONFIG = {};            // config (WhatsApp de la kine, etc.)
let ALERTAS = [];           // pacientes con pocas sesiones

// ---- Reloj / fecha ----
function pintarFecha() {
  const d = new Date();
  const opt = { weekday: 'long', day: 'numeric', month: 'long' };
  let txt = d.toLocaleDateString('es-AR', opt);
  txt = txt.charAt(0).toUpperCase() + txt.slice(1);
  const el = document.getElementById('fecha-hoy');
  if (el) el.textContent = txt + ' · ' +
    d.toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' });
}

// ---- Alarmas (Web Audio, sin archivos) ----
let AUDIO_CTX = null;
function audioCtx() {
  if (!AUDIO_CTX) AUDIO_CTX = new (window.AudioContext || window.webkitAudioContext)();
  if (AUDIO_CTX.state === 'suspended') AUDIO_CTX.resume();
  return AUDIO_CTX;
}

// Un tono simple con envolvente.
function tono(ctx, freq, t0, dur, vol, tipo) {
  const o = ctx.createOscillator();
  const g = ctx.createGain();
  o.connect(g); g.connect(ctx.destination);
  o.type = tipo || 'sine';
  o.frequency.setValueAtTime(freq, t0);
  g.gain.setValueAtTime(0.0001, t0);
  g.gain.exponentialRampToValueAtTime(vol, t0 + 0.02);
  g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
  o.start(t0); o.stop(t0 + dur);
}

// Barrido de sirena (para sirena / sirena intensa).
function sweep(ctx, t0, dur, f1, f2, vol, tipo) {
  const o = ctx.createOscillator(), g = ctx.createGain();
  o.connect(g); g.connect(ctx.destination); o.type = tipo || 'sawtooth';
  o.frequency.setValueAtTime(f1, t0);
  o.frequency.linearRampToValueAtTime(f2, t0 + dur / 2);
  o.frequency.linearRampToValueAtTime(f1, t0 + dur);
  g.gain.setValueAtTime(0.0001, t0);
  g.gain.exponentialRampToValueAtTime(vol, t0 + 0.05);
  g.gain.setValueAtTime(vol, t0 + dur - 0.05);
  g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
  o.start(t0); o.stop(t0 + dur);
}

function reproducirAlarma(tipo) {
  try {
    const ctx = audioCtx();
    const n = ctx.currentTime;
    if (tipo === 'triple') {
      [0, 0.22, 0.44].forEach(dt => tono(ctx, 880, n + dt, 0.16, 0.4));
    } else if (tipo === 'suave') {
      tono(ctx, 523, n, 0.3, 0.3);
      tono(ctx, 659, n + 0.18, 0.5, 0.3);
    } else if (tipo === 'sirena') {
      sweep(ctx, n, 1.0, 600, 1000, 0.5, 'sawtooth');
    } else if (tipo === 'fuerte') {
      // Beeps cuadrados rápidos y fuertes.
      for (let i = 0; i < 5; i++) tono(ctx, 1000, n + i * 0.16, 0.11, 0.9, 'square');
    } else if (tipo === 'sirena_intensa') {
      // Dos barridos de ida y vuelta, bien fuertes.
      sweep(ctx, n, 0.9, 500, 1200, 0.9, 'sawtooth');
      sweep(ctx, n + 0.9, 0.9, 500, 1200, 0.9, 'sawtooth');
    } else if (tipo === 'timbre') {
      // Zumbido continuo tipo timbre de puerta.
      tono(ctx, 480, n, 1.2, 0.9, 'square');
      tono(ctx, 620, n, 1.2, 0.5, 'square');
    } else if (tipo === 'alarma') {
      // Alarma de reloj: on/off rápido y estridente.
      for (let i = 0; i < 8; i++) tono(ctx, i % 2 ? 1200 : 900, n + i * 0.12, 0.09, 0.85, 'square');
    } else { // campana (default)
      tono(ctx, 988, n, 0.9, 0.4);
      tono(ctx, 1319, n, 0.9, 0.22);
    }
  } catch (e) {}
}

function alarmaSeleccionada() {
  const s = document.getElementById('sound-tipo');
  return s ? s.value : 'campana';
}

function beep() {
  if (!document.getElementById('sound-on').checked) return;
  reproducirAlarma(alarmaSeleccionada());
}

// Botón "Probar": suena siempre (aunque la alarma esté apagada).
function probarAlarma() {
  reproducirAlarma(alarmaSeleccionada());
  toast('🔊 Así suena la alarma', 'ok');
}

function fmt(seg) {
  const neg = seg < 0;
  seg = Math.abs(seg);
  const m = Math.floor(seg / 60);
  const s = seg % 60;
  return (neg ? '+' : '') + m + ':' + String(s).padStart(2, '0');
}

// ---- Render principal ----
function render() {
  if (!ESTADO) return;
  pintarStats();
  pintarBoxes();
  pintarEspera();
  pintarAgendaMini();
  pintarAlertas();
}

function pintarAlertas() {
  const cont = document.getElementById('alertas-wrap');
  if (!cont) return;
  if (!ALERTAS.length) { cont.innerHTML = ''; return; }
  const items = ALERTAS.map(a => {
    const cls = a.quedan <= 0 ? 'danger' : 'warn';
    const txt = a.quedan <= 0 ? 'sin sesiones' : `${a.quedan} restante(s)`;
    return `<a href="/paciente/${a.id}" class="chip">
      <span class="st ${a.quedan <= 0 ? 'perdido' : ''}"></span>
      ${escapeHtml(a.nombre_completo)} · <b>${txt}</b></a>`;
  }).join('');
  cont.innerHTML = `<div class="card card-pad alerta-card">
    <div class="alerta-title">⚠️ Últimas sesiones — por renovar bono/autorización</div>
    <div>${items}</div></div>`;
}

function pintarStats() {
  const s = ESTADO.stats;
  const items = [
    ['n', s.total, 'Turnos hoy'],
    ['', s.atendidos, 'Atendidos'],
    ['', s.en_curso, 'En sesión'],
    ['', s.espera, 'En espera'],
    ['', s.pendientes, 'Por venir'],
    ['', s.ausentes, 'Ausentes'],
  ];
  document.getElementById('stats').innerHTML = items.map(([_, n, l]) =>
    `<div class="stat"><div class="n">${n}</div><div class="l">${l}</div></div>`
  ).join('');
}

function pintarBoxes() {
  const cont = document.getElementById('boxes');
  cont.innerHTML = ESTADO.boxes.map(b => {
    if (!b.ocupado) {
      return `<div class="box libre">
        <div class="box-head">
          <span class="box-nom">${escapeHtml(b.nombre)}</span>
          <span class="box-badge badge-libre">Libre</span>
        </div>
        <div class="box-libre-txt">Disponible</div>
        <div class="box-actions">
          <button class="btn btn-primary btn-sm grow" onclick="ponerEnBox(${b.id}, '${escapeJs(b.nombre)}')">+ Paciente</button>
          <button class="btn btn-danger-soft btn-sm" onclick="borrarBox(${b.id})" title="Quitar box">✕</button>
        </div>
      </div>`;
    }
    const venc = b.vencido;
    const wa = (venc && CONFIG.wa_kine)
      ? `<button class="btn btn-ghost btn-sm" onclick="avisarWa('${escapeJs(b.paciente)}','${escapeJs(b.nombre)}')" title="Avisar por WhatsApp">📲</button>` : '';
    return `<div class="box ocupado ${venc ? 'vencido' : ''}" data-box="${b.id}">
      <div class="box-head">
        <span class="box-nom">${escapeHtml(b.nombre)}</span>
        <span class="box-badge ${venc ? 'badge-vencido' : 'badge-ocupado'}">
          ${venc ? '¡Terminó!' : 'En sesión'}</span>
      </div>
      <a href="/paciente/${b.paciente_id}" class="box-pac">${escapeHtml(b.paciente)}</a>
      <div class="box-diag">${escapeHtml(b.diagnostico || '')}</div>
      <div class="timer" data-restante="${b.restante_seg}">${fmt(b.restante_seg)}</div>
      <div class="box-actions">
        <button class="btn btn-ok btn-sm grow" onclick="terminar(${b.turno_id})">✓ Terminar</button>
        ${wa}
      </div>
    </div>`;
  }).join('');
}

function pintarEspera() {
  const cont = document.getElementById('espera-list');
  if (!ESTADO.espera.length) {
    cont.innerHTML = '<div class="empty">Nadie esperando 🙌</div>';
    return;
  }
  cont.innerHTML = ESTADO.espera.map(e => {
    const sesTxt = e.sesiones_quedan > 0
      ? `${e.sesiones_quedan} sesiones restantes`
      : 'sin sesiones';
    const warn = e.sesiones_quedan <= 1 ? 'warn' : '';
    const os = e.obra_social ? `<span class="pill">${escapeHtml(e.obra_social)}</span> ` : '';
    return `<div class="espera-item">
      <div class="avatar">${iniciales(e.paciente)}</div>
      <div class="li-main">
        <div class="li-name">${escapeHtml(e.paciente)}</div>
        <div class="li-sub">${e.hora ? e.hora + ' · ' : ''}${os}<span class="pill ${warn}">${sesTxt}</span></div>
      </div>
      <div class="li-actions">
        <button class="btn btn-primary btn-sm" onclick="pedirIniciar(${e.turno_id}, '${escapeJs(e.paciente)}')">A un box →</button>
      </div>
    </div>`;
  }).join('');
}

function pintarAgendaMini() {
  const cont = document.getElementById('agenda-mini');
  if (!ESTADO.agenda_por_hora.length) {
    cont.innerHTML = '<div class="empty">No hay turnos cargados para hoy</div>';
    return;
  }
  cont.innerHTML = ESTADO.agenda_por_hora.map(g => {
    const chips = g.turnos.map(t =>
      `<span class="chip"><span class="st ${t.estado}"></span>${escapeHtml(t.paciente)}</span>`
    ).join('');
    return `<div class="hora-block">
      <div class="hora-head">
        <span class="h">${escapeHtml(g.hora)}</span>
        <span class="hora-count">${g.cantidad} ${g.cantidad === 1 ? 'persona' : 'personas'}</span>
      </div>
      <div>${chips}</div>
    </div>`;
  }).join('');
}

function escapeJs(s) {
  return (s || '').replace(/'/g, "\\'").replace(/"/g, '\\"');
}

// ---- Ticking local del timer entre polls (para que no se congele) ----
function tick() {
  document.querySelectorAll('.timer[data-restante]').forEach(el => {
    let r = parseInt(el.dataset.restante, 10) - 1;
    el.dataset.restante = r;
    el.textContent = fmt(r);
    const box = el.closest('.box');
    if (r <= 0 && box && !box.classList.contains('vencido')) {
      box.classList.add('vencido');
      const badge = box.querySelector('.box-badge');
      if (badge) { badge.className = 'box-badge badge-vencido'; badge.textContent = '¡Terminó!'; }
    }
    // Aviso al cruzar el cero.
    if (r === 0) {
      const id = box ? box.dataset.box : null;
      dispararAviso(id, box);
    }
  });
}

function dispararAviso(boxId, box) {
  if (boxId && AVISADOS.has(boxId)) return;
  if (boxId) AVISADOS.add(boxId);
  const nom = box ? box.querySelector('.box-nom').textContent : 'Un box';
  const pac = box ? box.querySelector('.box-pac').textContent : '';
  beep();
  toast(`⏰ ${nom} terminó — ${pac}`, 'alert');
}

// ---- Acciones ----
async function terminar(tid) {
  await api(`/api/turno/${tid}/terminar`);
  toast('Sesión terminada ✓', 'ok');
  refrescar();
}

function pedirIniciar(tid, nombre) {
  TURNO_INICIAR = tid;
  document.getElementById('iniciar-titulo').textContent = 'Enviar a box: ' + nombre;
  const sel = document.getElementById('iniciar-box');
  if (!ESTADO.libres.length) {
    toast('No hay boxes libres en este momento', 'alert');
    return;
  }
  sel.innerHTML = ESTADO.libres.map(b => `<option value="${b.id}">${escapeHtml(b.nombre)}</option>`).join('');
  abrirModal('modal-iniciar');
}

document.getElementById('iniciar-confirm').addEventListener('click', async () => {
  const box_id = document.getElementById('iniciar-box').value;
  const dur = document.getElementById('iniciar-dur').value;
  await api(`/api/turno/${TURNO_INICIAR}/iniciar`, { box_id: +box_id, duracion: +dur });
  cerrarModal('modal-iniciar');
  toast('Sesión iniciada', 'ok');
  refrescar();
});

async function agregarBox() {
  const nombre = prompt('Nombre del box:', 'Box ' + (ESTADO.boxes.length + 1));
  if (!nombre) return;
  await api('/api/box', { nombre });
  refrescar();
}

async function borrarBox(id) {
  if (!confirm('¿Quitar este box de la sala?')) return;
  await api(`/api/box/${id}/borrar`);
  refrescar();
}

// ---- Check-in / registrar llegada ----
function abrirCheckin() {
  document.getElementById('checkin-buscar').value = '';
  document.getElementById('checkin-resultados').innerHTML =
    '<div class="empty">Escribí un nombre para buscar</div>';
  abrirModal('modal-checkin');
  setTimeout(() => document.getElementById('checkin-buscar').focus(), 100);
}

let buscarTimer = null;
document.getElementById('checkin-buscar').addEventListener('input', e => {
  clearTimeout(buscarTimer);
  const term = e.target.value.trim();
  buscarTimer = setTimeout(() => buscarPacientes(term), 220);
});

async function buscarPacientes(term) {
  if (!term) {
    document.getElementById('checkin-resultados').innerHTML =
      '<div class="empty">Escribí un nombre para buscar</div>';
    return;
  }
  const rows = await apiGet('/api/pacientes?q=' + encodeURIComponent(term));
  const cont = document.getElementById('checkin-resultados');
  if (!rows.length) {
    cont.innerHTML = '<div class="empty">Sin resultados</div>';
    return;
  }
  cont.innerHTML = rows.map(p => `
    <div class="list-item">
      <div class="avatar">${iniciales(p.nombre_completo)}</div>
      <div class="li-main">
        <div class="li-name">${escapeHtml(p.nombre_completo)}</div>
        <div class="li-sub">${p.dni ? 'DNI ' + escapeHtml(p.dni) + ' · ' : ''}${p.sesiones_quedan} sesiones restantes</div>
      </div>
      <button class="btn btn-primary btn-sm" onclick="registrarLlegada(${p.id}, '${escapeJs(p.nombre_completo)}')">Llegó</button>
    </div>`).join('');
}

async function registrarLlegada(pid, nombre) {
  // Busca un turno de hoy agendado; si no hay, crea uno al vuelo.
  const hoy = new Date().toISOString().slice(0, 10);
  const hora = new Date().toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' });
  let turnoId = null;

  // ¿Tiene turno agendado hoy?
  const est = await apiGet('/api/estado');
  const enAgenda = est.agenda_por_hora
    .flatMap(g => g.turnos)
    .find(t => t.paciente_id === pid && t.estado === 'agendado');

  if (enAgenda) {
    turnoId = enAgenda.turno_id;
  } else {
    const r = await api('/api/turno', { paciente_id: pid, fecha: hoy, hora });
    turnoId = r.id;
  }
  await api(`/api/turno/${turnoId}/asistencia`);
  cerrarModal('modal-checkin');
  toast(`${nombre} en sala de espera ✓`, 'ok');
  refrescar();
}

// ---- Poner paciente directo en un box (cuenta como asistencia) ----
function ponerEnBox(boxId, nombre) {
  ABOX_BOX = boxId;
  document.getElementById('abox-titulo').textContent = 'Poner en ' + nombre;
  document.getElementById('abox-buscar').value = '';
  document.getElementById('abox-resultados').innerHTML = '<div class="empty">Buscá un paciente</div>';
  abrirModal('modal-abox');
  setTimeout(() => document.getElementById('abox-buscar').focus(), 100);
}

let aboxTimer = null;
document.getElementById('abox-buscar').addEventListener('input', e => {
  clearTimeout(aboxTimer);
  const term = e.target.value.trim();
  aboxTimer = setTimeout(() => buscarAbox(term), 220);
});

async function buscarAbox(term) {
  const cont = document.getElementById('abox-resultados');
  if (!term) { cont.innerHTML = '<div class="empty">Buscá un paciente</div>'; return; }
  const rows = await apiGet('/api/pacientes?q=' + encodeURIComponent(term));
  cont.innerHTML = rows.length ? rows.map(p => `
    <div class="list-item">
      <div class="avatar">${iniciales(p.nombre_completo)}</div>
      <div class="li-main"><div class="li-name">${escapeHtml(p.nombre_completo)}</div>
      <div class="li-sub">${p.sesiones_quedan} sesiones restantes</div></div>
      <button class="btn btn-primary btn-sm" onclick="confirmarAbox(${p.id})">Al box</button>
    </div>`).join('') : '<div class="empty">Sin resultados</div>';
}

async function confirmarAbox(pid) {
  const dur = document.getElementById('abox-dur').value;
  await api('/api/paciente/' + pid + '/a_box', { box_id: ABOX_BOX, duracion: +dur });
  cerrarModal('modal-abox');
  toast('Paciente en el box — asistencia registrada ✓', 'ok');
  refrescar();
}

// ---- WhatsApp (puente manual; base para el bot/IA a futuro) ----
function waLink(msg) {
  return 'https://wa.me/' + (CONFIG.wa_kine || '').replace(/[^0-9]/g, '') +
    '?text=' + encodeURIComponent(msg);
}
function avisarWa(paciente, box) {
  if (!CONFIG.wa_kine) { toast('Primero configurá el WhatsApp en ⚙', 'alert'); return; }
  window.open(waLink(`${paciente} terminó su sesión en ${box}. Ya podés pasar 🙌`), '_blank');
}

async function cargarConfig() { try { CONFIG = await apiGet('/api/config'); } catch (e) {} }
function abrirConfig() {
  document.getElementById('cfg-wa').value = CONFIG.wa_kine || '';
  abrirModal('modal-config');
}
async function guardarConfig() {
  const wa = document.getElementById('cfg-wa').value.replace(/[^0-9]/g, '');
  await api('/api/config', { wa_kine: wa });
  CONFIG.wa_kine = wa;
  cerrarModal('modal-config');
  toast('Guardado ✓', 'ok');
  if (ESTADO) render();
}

// ---- Alertas de últimas sesiones ----
async function cargarAlertas() {
  try { ALERTAS = await apiGet('/api/alertas'); pintarAlertas(); } catch (e) {}
}

// ---- Repetición de alarma mientras un box siga vencido ----
function repetirAlarmas() {
  const rep = document.getElementById('sound-repeat');
  if (!rep || !rep.checked || !document.getElementById('sound-on').checked || !ESTADO) return;
  const now = Date.now();
  ESTADO.boxes.forEach(b => {
    if (b.ocupado && b.vencido) {
      if (!(b.id in REPEAT_LAST)) { REPEAT_LAST[b.id] = now; return; } // 1er aviso lo da tick()
      if (now - REPEAT_LAST[b.id] > 5000) { reproducirAlarma(alarmaSeleccionada()); REPEAT_LAST[b.id] = now; }
    } else {
      delete REPEAT_LAST[b.id];
    }
  });
}

// ---- Polling ----
async function refrescar() {
  try {
    ESTADO = await apiGet('/api/estado');
    ESTADO.boxes.forEach(b => {
      if (!b.ocupado || b.restante_seg > 0) { AVISADOS.delete(String(b.id)); delete REPEAT_LAST[b.id]; }
    });
    render();
  } catch (e) { /* silencioso */ }
}

pintarFecha();
cargarConfig().then(refrescar);
cargarAlertas();
setInterval(refrescar, 5000);       // sincroniza con el server cada 5s
setInterval(cargarAlertas, 20000);  // alertas de sesiones
setInterval(tick, 1000);            // baja el timer local cada segundo
setInterval(repetirAlarmas, 1000);  // repite la alarma si sigue vencido
setInterval(pintarFecha, 30000);
