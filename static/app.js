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
    _ALARM_AUDIO.loop = true; _ALARM_AUDIO.volume = 1; _ALARM_TIPO = tipo;
  }
  return _ALARM_AUDIO;
}
function sonarContinuo() { const a = alarmAudio(); if (a.paused) a.play().catch(() => {}); }
function pararSonido() { if (_ALARM_AUDIO && !_ALARM_AUDIO.paused) { _ALARM_AUDIO.pause(); _ALARM_AUDIO.currentTime = 0; } }
function probarAlarma() { sonarContinuo(); setTimeout(pararSonido, 3000); toast('🔊 Así suena la alarma elegida', 'ok'); }
