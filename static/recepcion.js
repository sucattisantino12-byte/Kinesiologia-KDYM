// Pantalla de recepción: boxes en vivo, sala del día (por horas, vino/no vino), stats.

let ESTADO = null;
let AVISADOS = new Set();   // boxes ya avisados como "terminados" (aviso inicial)
let REPEAT_LAST = {};       // último re-beep por box (para repetir alarma)
let TURNO_INICIAR = null;   // turno pendiente de asignar a un box
let ABOX_BOX = null;        // box elegido para "añadir a box"
let NOVINO = null;          // turno en el modal "no vino"
let CONFIG = {};            // config (WhatsApp de la kine, etc.)

const DIAS = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom'];

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

// Alarmas ~3-4 segundos (duran más).
function reproducirAlarma(tipo) {
  try {
    const ctx = audioCtx();
    const n = ctx.currentTime;
    if (tipo === 'triple') {
      for (let i = 0; i < 8; i++) tono(ctx, 880, n + i * 0.30, 0.16, 0.4);
    } else if (tipo === 'suave') {
      for (let i = 0; i < 4; i++) {
        tono(ctx, 523, n + i * 0.8, 0.3, 0.3);
        tono(ctx, 659, n + i * 0.8 + 0.18, 0.5, 0.3);
      }
    } else if (tipo === 'sirena') {
      sweep(ctx, n, 3.0, 600, 1000, 0.5, 'sawtooth');
    } else if (tipo === 'fuerte') {
      for (let i = 0; i < 16; i++) tono(ctx, 1000, n + i * 0.19, 0.12, 0.9, 'square');
    } else if (tipo === 'sirena_intensa') {
      for (let i = 0; i < 4; i++) sweep(ctx, n + i * 0.9, 0.9, 500, 1200, 0.9, 'sawtooth');
    } else if (tipo === 'timbre') {
      tono(ctx, 480, n, 3.2, 0.9, 'square');
      tono(ctx, 620, n, 3.2, 0.5, 'square');
    } else if (tipo === 'alarma') {
      for (let i = 0; i < 26; i++) tono(ctx, i % 2 ? 1200 : 900, n + i * 0.14, 0.1, 0.85, 'square');
    } else { // campana
      for (let i = 0; i < 4; i++) {
        tono(ctx, 988, n + i * 0.85, 0.9, 0.4);
        tono(ctx, 1319, n + i * 0.85, 0.9, 0.22);
      }
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
function probarAlarma() {
  reproducirAlarma(alarmaSeleccionada());
  toast('🔊 Así suena la alarma', 'ok');
}

// Muestra/oculta el campo de minutos según se elija "Personalizado" en el select.
function toggleDur(selId, inpId) {
  const sel = document.getElementById(selId);
  const inp = document.getElementById(inpId);
  const custom = sel.value === 'custom';
  inp.style.display = custom ? '' : 'none';
  if (custom) setTimeout(() => inp.focus(), 50);
}
// Devuelve la duración elegida (recomendada o personalizada).
function leerDur(selId, inpId) {
  const sel = document.getElementById(selId);
  if (sel.value === 'custom') return +document.getElementById(inpId).value || 30;
  return +sel.value;
}
// Resetea el selector de duración a 30 min (recomendado) y oculta el personalizado.
function resetDur(selId, inpId) {
  document.getElementById(selId).value = '30';
  const inp = document.getElementById(inpId);
  inp.value = ''; inp.style.display = 'none';
}

function fmt(seg) {
  const neg = seg < 0; seg = Math.abs(seg);
  const m = Math.floor(seg / 60), s = seg % 60;
  return (neg ? '+' : '') + m + ':' + String(s).padStart(2, '0');
}

function escapeJs(s) {
  return (s || '').replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/"/g, '\\"');
}

// ---- Render principal ----
function render() {
  if (!ESTADO) return;
  pintarStats();
  pintarBoxes();
  pintarSala();
}

function pintarStats() {
  const s = ESTADO.stats;
  const items = [
    [s.total, 'Turnos hoy'],
    [s.atendidos, 'Vinieron'],
    [s.en_curso, 'En box'],
    [s.presentes, 'Presentes'],
    [s.pendientes, 'Por venir'],
    [s.ausentes, 'No vinieron'],
  ];
  document.getElementById('stats').innerHTML = items.map(([n, l]) =>
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

// ---- Sala del día (agrupada por hora, con vino/no vino) ----
function pintarSala() {
  const cont = document.getElementById('sala-list');
  const sala = ESTADO.sala || [];
  if (!sala.length) {
    cont.innerHTML = '<div class="card"><div class="empty">No hay turnos cargados para hoy</div></div>';
    return;
  }
  cont.innerHTML = sala.map(g => `
    <div class="hora-block">
      <div class="hora-head">
        <span class="h">${escapeHtml(g.hora)}</span>
        <span class="hora-count">${g.cantidad} ${g.cantidad === 1 ? 'persona' : 'personas'}</span>
      </div>
      <div class="card">${g.turnos.map(filaSala).join('')}</div>
    </div>`).join('');
}

function filaSala(t) {
  const os = t.obra_social ? `<span class="pill">${escapeHtml(t.obra_social)}</span> ` : '';
  const ses = t.sesiones_quedan <= 1 ? 'warn' : '';
  let acciones = '', badge = '';
  if (t.estado === 'agendado' || t.estado === 'en_espera') {
    acciones = `
      <button class="btn btn-ok btn-sm" title="Vino" onclick="vino(${t.turno_id})">✓ Vino</button>
      <button class="btn btn-danger-soft btn-sm" title="No vino" onclick="noVino(${t.turno_id})">✗</button>`;
  } else if (t.estado === 'presente') {
    badge = `<span class="pill ok">Presente ✓</span>`;
    acciones = `<button class="btn btn-primary btn-sm" onclick="pedirIniciar(${t.turno_id}, '${escapeJs(t.paciente)}')">A un box →</button>`;
  } else if (t.estado === 'en_curso') {
    badge = `<span class="pill">En ${escapeHtml(t.box || 'box')}</span>`;
  } else if (t.estado === 'terminado') {
    badge = `<span class="pill ok">Terminó</span>`;
  } else if (t.estado === 'ausente') {
    badge = `<span class="pill danger">No vino</span>`;
  } else if (t.estado === 'perdido') {
    badge = `<span class="pill danger">Perdido</span>`;
  }
  return `<div class="espera-item">
    <div class="avatar">${iniciales(t.paciente)}</div>
    <div class="li-main">
      <a href="/paciente/${t.paciente_id}" class="li-name">${escapeHtml(t.paciente)}</a>
      <div class="li-sub">${os}<span class="pill ${ses}">${t.sesiones_quedan} ses.</span> ${badge}</div>
    </div>
    <div class="li-actions">${acciones}</div>
  </div>`;
}

// ---- Vino / No vino ----
async function vino(tid) {
  const r = await api(`/api/turno/${tid}/vino`);
  toast(`Vino ✓ — sesión contada · quedan ${r.sesiones_quedan}`, 'ok');
  refrescar();
}

function noVino(tid) {
  const t = (ESTADO.sala || []).flatMap(g => g.turnos).find(x => x.turno_id === tid);
  if (!t) return;
  NOVINO = t;
  document.getElementById('novino-nombre').textContent = t.paciente + ' no vino. ¿Qué hacemos?';
  // Mostrar los horarios del paciente.
  let hs = '';
  if (t.horarios && Object.keys(t.horarios).length) {
    hs = Object.keys(t.horarios).sort().map(k => `${DIAS[k]} ${t.horarios[k]}`).join(' · ');
  }
  const dias = t.dias || '—';
  document.getElementById('novino-horarios').innerHTML =
    `Sus días: <b>${escapeHtml(dias)}</b>` + (hs ? `<br>Horarios: <b>${escapeHtml(hs)}</b>` : '');
  document.getElementById('novino-fecha').value = '';
  abrirModal('modal-novino');
}

async function reprogNovino() {
  const r = await api(`/api/turno/${NOVINO.turno_id}/reprogramar`);
  cerrarModal('modal-novino');
  toast('Reprogramado al ' + r.fecha + ' ✓', 'ok');
  refrescar();
}
async function elegirFechaNovino() {
  const f = document.getElementById('novino-fecha').value;
  if (!f) { toast('Elegí una fecha', 'alert'); return; }
  const r = await api(`/api/turno/${NOVINO.turno_id}/elegir_fecha`, { fecha: f });
  cerrarModal('modal-novino');
  toast('Turno movido al ' + r.fecha + ' ✓', 'ok');
  refrescar();
}
function dejarDespues() {
  cerrarModal('modal-novino');
  toast('Lo dejamos para después', 'ok');
}

// ---- Ticking local del timer ----
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
    if (r === 0) dispararAviso(box ? box.dataset.box : null, box);
  });
}

function dispararAviso(boxId, box) {
  if (boxId && AVISADOS.has(boxId)) return;
  if (boxId) AVISADOS.add(boxId);
  const nom = box ? box.querySelector('.box-nom').textContent : 'Un box';
  const pac = box ? box.querySelector('.box-pac').textContent : '';
  beep();
  vibrar([700, 300, 700]);
  toast(`⏰ ${nom} terminó — ${pac}`, 'alert');
}

// ---- Acciones de box ----
async function terminar(tid) {
  pararVibracion();
  await api(`/api/turno/${tid}/terminar`);
  toast('Box liberado ✓', 'ok');
  refrescar();
}

function pedirIniciar(tid, nombre) {
  TURNO_INICIAR = tid;
  document.getElementById('iniciar-titulo').textContent = 'Enviar a box: ' + nombre;
  const sel = document.getElementById('iniciar-box');
  if (!ESTADO.libres.length) { toast('No hay boxes libres en este momento', 'alert'); return; }
  sel.innerHTML = ESTADO.libres.map(b => `<option value="${b.id}">${escapeHtml(b.nombre)}</option>`).join('');
  resetDur('iniciar-dur', 'iniciar-dur-custom');
  abrirModal('modal-iniciar');
}

document.getElementById('iniciar-confirm').addEventListener('click', async () => {
  const box_id = document.getElementById('iniciar-box').value;
  const dur = leerDur('iniciar-dur', 'iniciar-dur-custom');
  await api(`/api/turno/${TURNO_INICIAR}/iniciar`, { box_id: +box_id, duracion: dur });
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

// ---- Añadir a box: sólo pacientes presentes ----
function ponerEnBox(boxId, nombre) {
  ABOX_BOX = boxId;
  document.getElementById('abox-titulo').textContent = 'Añadir a ' + nombre;
  resetDur('abox-dur', 'abox-dur-custom');
  const pres = ESTADO.presentes || [];
  const cont = document.getElementById('abox-resultados');
  if (!pres.length) {
    cont.innerHTML = '<div class="empty">No hay pacientes presentes.<br>Marcá ✓ Vino en la sala del día primero.</div>';
  } else {
    cont.innerHTML = pres.map(p => `
      <div class="list-item">
        <div class="avatar">${iniciales(p.paciente)}</div>
        <div class="li-main"><div class="li-name">${escapeHtml(p.paciente)}</div>
        <div class="li-sub">${p.hora ? p.hora + ' · ' : ''}${p.sesiones_quedan} sesiones</div></div>
        <button class="btn btn-primary btn-sm" onclick="confirmarAbox(${p.turno_id})">Al box</button>
      </div>`).join('');
  }
  abrirModal('modal-abox');
}
async function confirmarAbox(turnoId) {
  const dur = leerDur('abox-dur', 'abox-dur-custom');
  await api(`/api/turno/${turnoId}/iniciar`, { box_id: ABOX_BOX, duracion: dur });
  cerrarModal('modal-abox');
  toast('Paciente en el box ✓', 'ok');
  refrescar();
}

// ---- Registrar llegada (walk-in): marca vino ----
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
  const cont = document.getElementById('checkin-resultados');
  if (!term) { cont.innerHTML = '<div class="empty">Escribí un nombre para buscar</div>'; return; }
  const rows = await apiGet('/api/pacientes?q=' + encodeURIComponent(term));
  if (!rows.length) { cont.innerHTML = '<div class="empty">Sin resultados</div>'; return; }
  cont.innerHTML = rows.map(p => `
    <div class="list-item">
      <div class="avatar">${iniciales(p.nombre_completo)}</div>
      <div class="li-main">
        <div class="li-name">${escapeHtml(p.nombre_completo)}</div>
        <div class="li-sub">${p.dni ? 'DNI ' + escapeHtml(p.dni) + ' · ' : ''}${p.sesiones_quedan} sesiones restantes</div>
      </div>
      <button class="btn btn-primary btn-sm" onclick="registrarLlegada(${p.id}, '${escapeJs(p.nombre_completo)}')">Vino ✓</button>
    </div>`).join('');
}

async function registrarLlegada(pid, nombre) {
  const hoy = new Date().toISOString().slice(0, 10);
  const hora = new Date().toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' });
  const est = await apiGet('/api/estado');
  const enSala = (est.sala || []).flatMap(g => g.turnos)
    .find(t => t.paciente_id === pid && (t.estado === 'agendado' || t.estado === 'en_espera'));
  let turnoId;
  if (enSala) turnoId = enSala.turno_id;
  else { const r = await api('/api/turno', { paciente_id: pid, fecha: hoy, hora }); turnoId = r.id; }
  await api(`/api/turno/${turnoId}/vino`);
  cerrarModal('modal-checkin');
  toast(`${nombre}: vino ✓`, 'ok');
  refrescar();
}

// ---- WhatsApp ----
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

// ---- Vibración del celular ----
function vibrar(pattern) {
  if (navigator.vibrate) { try { navigator.vibrate(pattern || [700, 300]); } catch (e) {} }
}
function pararVibracion() {
  if (navigator.vibrate) { try { navigator.vibrate(0); } catch (e) {} }
}

// Desbloquear el audio en el primer toque (los celulares lo bloquean hasta que
// el usuario interactúa). Así la alarma suena sin problemas.
function unlockAudio() { try { audioCtx(); } catch (e) {} }
['click', 'touchstart', 'keydown'].forEach(ev =>
  document.addEventListener(ev, unlockAudio, { once: true }));

// ---- Alarma continua + vibración mientras un box siga vencido ----
let LAST_SOUND = 0;
function hayVencido() { return !!document.querySelector('.box.ocupado.vencido'); }

function alarmaLoop() {
  if (hayVencido()) {
    vibrar([800, 250]);   // vibra siempre que un box esté vencido (hasta Terminar)
    const rep = document.getElementById('sound-repeat');
    const soundOn = document.getElementById('sound-on');
    if (rep && rep.checked && soundOn && soundOn.checked) {
      const now = Date.now();
      if (now - LAST_SOUND > 3200) { reproducirAlarma(alarmaSeleccionada()); LAST_SOUND = now; }
    }
  } else {
    pararVibracion();
  }
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

// Al volver a la pestaña/app, re-sincronizar al instante (evita que quede colgada).
document.addEventListener('visibilitychange', () => { if (!document.hidden) refrescar(); });
window.addEventListener('focus', refrescar);

pintarFecha();
cargarConfig().then(refrescar);
setInterval(refrescar, 5000);
setInterval(tick, 1000);
setInterval(alarmaLoop, 1000);
setInterval(pintarFecha, 30000);
