// Utilidades compartidas por todas las pantallas.

// ---- Animación de inicio (una vez por sesión de navegador) ----
(function () {
  const splash = document.getElementById('splash');
  if (!splash) return;
  if (sessionStorage.getItem('kdym_splash')) {
    splash.remove();
    return;
  }
  sessionStorage.setItem('kdym_splash', '1');
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

// ---- Contador de notificaciones en el menú (todas las pantallas) ----
async function actualizarBadgeNotif() {
  const b = document.getElementById('nav-notif-badge');
  if (!b) return;
  try {
    const r = await apiGet('/api/notificaciones/count');
    if (r.count > 0) { b.textContent = r.count; b.style.display = 'inline-flex'; }
    else { b.style.display = 'none'; }
  } catch (e) {}
}
actualizarBadgeNotif();
setInterval(actualizarBadgeNotif, 15000);
