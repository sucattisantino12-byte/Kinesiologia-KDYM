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

// El motor de sonido (alarmAudio / sonarContinuo / pararSonido / probarAlarma /
// alarmaSeleccionada / alarmaEncendida) vive en app.js y usa el sonido elegido
// en Configuración (localStorage 'kdym_alarma').

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
    // Modo prueba (simulación de 10s) en un box libre.
    if (!b.ocupado && TESTS[b.id] !== undefined) {
      const rest = Math.round((TESTS[b.id] - Date.now()) / 1000);
      const venc = rest <= 0;
      return `<div class="box ocupado ${venc ? 'vencido' : ''}" data-box="t${b.id}">
        <div class="box-head">
          <span class="box-nom">${escapeHtml(b.nombre)}</span>
          <span class="box-badge ${venc ? 'badge-vencido' : 'badge-ocupado'}">${venc ? '¡Terminó!' : '🧪 Prueba'}</span>
        </div>
        <div class="box-pac">🧪 Prueba de alarma</div>
        <div class="box-diag"></div>
        <div class="timer" data-restante="${rest}">${fmt(rest)}</div>
        <div class="box-actions">
          <button class="btn btn-ok btn-sm btn-block" onclick="terminarPrueba(${b.id})">✓ Terminar prueba</button>
        </div>
      </div>`;
    }
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
        <button class="btn btn-line btn-sm" onclick="agregarTiempo(${b.turno_id})">+ tiempo</button>
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
    acciones = `<button class="btn btn-primary btn-sm" onclick="pedirIniciar(${t.turno_id}, '${escapeJs(t.paciente)}')">A un box →</button>
      <button class="btn btn-ghost btn-sm" onclick="deshacerVino(${t.turno_id})" title="Marqué por error — deshacer">↺</button>`;
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
  if (!confirm('¿Confirmás que vino? Se le cuenta la sesión.')) return;
  const r = await api(`/api/turno/${tid}/vino`);
  toast(`Vino ✓ — sesión contada · quedan ${r.sesiones_quedan}`, 'ok');
  refrescar();
}
async function deshacerVino(tid) {
  await api(`/api/turno/${tid}/deshacer_vino`);
  toast('Deshecho — vuelve a agendado', 'ok');
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
  NOVINO_PREVIEW = null;
  abrirModal('modal-novino');
  // Mostrar a qué fecha se reprogramaría.
  apiGet('/api/turno/' + tid + '/reprogramar_preview').then(pv => {
    NOVINO_PREVIEW = pv;
    document.getElementById('novino-horarios').innerHTML +=
      `<br>Reprogramar lo mueve al <b>${pv.fecha}${pv.hora ? ' a las ' + pv.hora : ''}</b>.`;
  }).catch(() => {});
}

let NOVINO_PREVIEW = null;
async function reprogNovino() {
  const dest = NOVINO_PREVIEW ? (NOVINO_PREVIEW.fecha + (NOVINO_PREVIEW.hora ? ' a las ' + NOVINO_PREVIEW.hora : '')) : 'la próxima fecha';
  if (!confirm('Se reprograma al ' + dest + '. ¿Confirmar?')) return;
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
  const pacEl = box ? box.querySelector('.box-pac') : null;
  const pac = pacEl ? pacEl.textContent : '';
  vibrar([700, 300, 700]);
  if (alarmaEncendida()) sonarContinuo();
  mostrarNotif(boxId || 'x', '⏰ ' + nom + ' terminó', pac);
  toast(`⏰ ${nom} terminó — ${pac}`, 'alert');
}

// ---- Acciones de box ----
async function terminar(tid) {
  pararSonido(); pararVibracion(); cerrarTodasNotifs();
  const r = await api(`/api/turno/${tid}/terminar`);
  refrescar();
  if (r.paciente_id) abrirEjHoy(r.paciente_id, r.paciente);
  else toast('Box liberado ✓', 'ok');
}

// ---- Menú de ejercicios al terminar un box ----
let EJHOY_PID = null, EJHOY_CAT = null, CATALOGO_R = {};
async function abrirEjHoy(pid, nombre) {
  EJHOY_PID = pid;
  document.getElementById('ejhoy-titulo').textContent = 'Ejercicios de hoy — ' + nombre;
  document.getElementById('ejhoy-ficha').href = '/paciente/' + pid;
  if (!Object.keys(CATALOGO_R).length) { try { CATALOGO_R = await apiGet('/api/catalogo'); } catch (e) {} }
  EJHOY_CAT = Object.keys(CATALOGO_R)[0] || null;
  pintarEjHoy();
  abrirModal('modal-ejhoy');
}
function pintarEjHoy() {
  const cats = Object.keys(CATALOGO_R);
  document.getElementById('ejhoy-cats').innerHTML = cats.map(c =>
    `<button class="cat-tab ${c === EJHOY_CAT ? 'on' : ''}" onclick="ejHoyCat('${escapeJs(c)}')">${escapeHtml(c)}</button>`).join('');
  document.getElementById('ejhoy-lista').innerHTML = (CATALOGO_R[EJHOY_CAT] || []).map(o =>
    `<div class="cat-op" onclick="ejHoyAdd('${escapeJs(o.nombre)}','${escapeJs(EJHOY_CAT)}')">
       <span>${escapeHtml(o.nombre)}</span><span class="c">+ agregar</span></div>`).join('')
    || '<div class="empty">Sin ejercicios en esta categoría</div>';
}
function ejHoyCat(c) { EJHOY_CAT = c; pintarEjHoy(); }
async function ejHoyAdd(nombre, cat) {
  await api('/api/paciente/' + EJHOY_PID + '/ejercicio', { nombre, categoria: cat });
  toast('Agregado: ' + nombre + ' ✓', 'ok');
}

async function agregarTiempo(tid) {
  const m = prompt('¿Cuántos minutos agregar?', '10');
  if (!m) return;
  const min = parseInt(m, 10);
  if (!min || min <= 0) { toast('Poné un número de minutos', 'alert'); return; }
  pararSonido(); pararVibracion(); cerrarTodasNotifs();
  await api(`/api/turno/${tid}/agregar_tiempo`, { minutos: min });
  toast('+' + min + ' min agregados ✓', 'ok');
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
  if (!CONFIG.wa_kine) { toast('Primero cargá el WhatsApp en Configuración', 'alert'); return; }
  window.open(waLink(`${paciente} terminó su sesión en ${box}. Ya podés pasar 🙌`), '_blank');
}

async function cargarConfig() { try { CONFIG = await apiGet('/api/config'); } catch (e) {} }

// Probar la alarma en el box elegido desde el modal "+ Paciente".
function probarDesdeAbox() {
  cerrarModal('modal-abox');
  if (ABOX_BOX != null) probarBox(ABOX_BOX);
}

// ---- Vibración del celular ----
function vibrar(pattern) {
  if (navigator.vibrate) { try { navigator.vibrate(pattern || [700, 300]); } catch (e) {} }
}
function pararVibracion() {
  if (navigator.vibrate) { try { navigator.vibrate(0); } catch (e) {} }
}

// (El sonido en bucle vive en app.js: sonarContinuo / pararSonido / alarmAudio.)

// ---- Notificaciones del sistema (avisan aunque estés en otra app del navegador) ----
let SW_REG = null;
async function initServiceWorker() {
  if ('serviceWorker' in navigator) {
    try { SW_REG = await navigator.serviceWorker.register('/sw.js'); } catch (e) {}
  }
}
function pedirPermisoNotif() {
  if ('Notification' in window && Notification.permission === 'default') {
    try { Notification.requestPermission(); } catch (e) {}
  }
}
function mostrarNotif(id, titulo, cuerpo) {
  if (!('Notification' in window) || Notification.permission !== 'granted') return;
  const opts = { body: cuerpo, tag: 'kdym-' + id, requireInteraction: true,
                 vibrate: [600, 300, 600, 300, 600], renotify: true };
  try {
    if (SW_REG && SW_REG.showNotification) SW_REG.showNotification(titulo, opts);
    else new Notification(titulo, opts);
  } catch (e) {}
}
function cerrarTodasNotifs() {
  if (SW_REG && SW_REG.getNotifications) SW_REG.getNotifications().then(ns => ns.forEach(n => n.close()));
}

// ---- Wake Lock: mantener la pantalla encendida mientras la app esté abierta ----
let WAKE = null;
async function pedirWakeLock() {
  if (!('wakeLock' in navigator) || WAKE) return;
  try { WAKE = await navigator.wakeLock.request('screen'); WAKE.addEventListener('release', () => { WAKE = null; }); } catch (e) {}
}

// Primer toque: desbloquea audio, pide permiso de notificaciones y wake lock.
function primerToque() {
  try { const a = alarmAudio(); a.play().then(() => { a.pause(); a.currentTime = 0; }).catch(() => {}); } catch (e) {}
  pedirPermisoNotif();
  pedirWakeLock();
}
['click', 'touchstart', 'keydown'].forEach(ev =>
  document.addEventListener(ev, primerToque, { once: true }));

// ---- Modo prueba: simulación de 10 segundos por box ----
let TESTS = {};   // boxId -> timestamp de fin (ms)
function probarBox(boxId) {
  primerToque();
  TESTS[boxId] = Date.now() + 10000;
  toast('🧪 Prueba: la alarma sonará en 10 segundos…', 'ok');
  pintarBoxes();
}
function terminarPrueba(boxId) {
  delete TESTS[boxId];
  AVISADOS.delete('t' + boxId);
  pintarBoxes();
  if (!hayVencido()) { pararSonido(); pararVibracion(); cerrarTodasNotifs(); }
}

// ---- Alarma continua (sonido en bucle + vibración) mientras haya box vencido ----
function hayVencido() { return !!document.querySelector('.box.vencido'); }

function alarmaLoop() {
  if (hayVencido()) {
    vibrar([800, 250]);
    if (alarmaEncendida()) sonarContinuo();
    pedirWakeLock();
  } else {
    pararSonido();
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

// Al volver a la pestaña/app, re-sincronizar y re-pedir la pantalla encendida.
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) { refrescar(); pedirWakeLock(); }
});
window.addEventListener('focus', refrescar);

initServiceWorker();
pintarFecha();
cargarConfig().then(refrescar);
setInterval(refrescar, 5000);
setInterval(tick, 1000);
setInterval(alarmaLoop, 1000);
setInterval(pintarFecha, 30000);
