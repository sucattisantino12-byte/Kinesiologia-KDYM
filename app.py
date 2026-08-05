"""
KINESIO — App de recepción para centros de kinesiología.

Recepción en tiempo real (boxes con timer + alarma), fichas de pacientes
(datos, obra social, diagnóstico, ejercicios por categoría, sesiones),
agenda con calendario mensual, planificación por "días que viene" con
horario distinto por día, alertas de últimas sesiones, y registro de
eventos (base para automatizar avisos por WhatsApp / bot).

Stack: Flask + SQLite (kinesio.db). Corre en el puerto 8090.
"""

import os
import json
import sqlite3
from datetime import datetime, date, timedelta

from flask import (
    Flask, g, render_template, request, jsonify, redirect, url_for, abort
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# En local usa el archivo junto al código. En Railway (u otro hosting) definir la
# variable de entorno DB_PATH apuntando a un disco persistente (Volume),
# por ejemplo: DB_PATH=/data/kinesio.db  (si no, los datos se borran en cada deploy).
DB_PATH = os.environ.get("DB_PATH") or os.path.join(BASE_DIR, "kinesio.db")

# Asegura que la carpeta de la base exista (si DB_PATH apunta a un dir que no
# existe todavía, la crea; así la app no se cae al arrancar).
_db_dir = os.path.dirname(DB_PATH)
if _db_dir:
    os.makedirs(_db_dir, exist_ok=True)

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True

DURACION_DEFAULT = 30
DIAS_ABBR = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]  # weekday() 0..6


def dias_to_str(idxs):
    return ", ".join(DIAS_ABBR[i] for i in sorted(set(int(x) for x in idxs)))


def str_to_dias(s):
    return [i for i, a in enumerate(DIAS_ABBR) if a in (s or "")]


def parse_horarios(s):
    try:
        return json.loads(s) if s else {}
    except Exception:
        return {}


# --------------------------------------------------------------------------
# Base de datos
# --------------------------------------------------------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def q(sql, args=()):
    return get_db().execute(sql, args).fetchall()


def q1(sql, args=()):
    return get_db().execute(sql, args).fetchone()


def run(sql, args=()):
    db = get_db()
    cur = db.execute(sql, args)
    db.commit()
    return cur.lastrowid


def _cols(db, table):
    return [r[1] for r in db.execute(f"PRAGMA table_info({table})")]


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS pacientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            apellido TEXT NOT NULL,
            dni TEXT,
            telefono TEXT,
            obra_social TEXT,
            diagnostico TEXT,
            sesiones_totales INTEGER DEFAULT 0,
            sesiones_usadas INTEGER DEFAULT 0,
            dias TEXT,
            horarios TEXT,
            notas TEXT,
            creado TEXT
        );

        CREATE TABLE IF NOT EXISTS ejercicios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paciente_id INTEGER NOT NULL,
            nombre TEXT NOT NULL,
            categoria TEXT,
            series TEXT,
            reps TEXT,
            notas TEXT,
            FOREIGN KEY (paciente_id) REFERENCES pacientes(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS catalogo_ejercicios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            categoria TEXT
        );

        CREATE TABLE IF NOT EXISTS boxes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            activo INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS turnos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paciente_id INTEGER NOT NULL,
            fecha TEXT NOT NULL,
            hora TEXT,
            box_id INTEGER,
            estado TEXT DEFAULT 'agendado',
            inicio TEXT,
            fin TEXT,
            duracion_min INTEGER DEFAULT 30,
            FOREIGN KEY (paciente_id) REFERENCES pacientes(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS eventos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT,
            tipo TEXT,
            paciente_id INTEGER,
            texto TEXT
        );

        CREATE TABLE IF NOT EXISTS config (
            clave TEXT PRIMARY KEY,
            valor TEXT
        );
        """
    )
    db.commit()

    # Migraciones para bases existentes.
    if "obra_social" not in _cols(db, "pacientes"):
        db.execute("ALTER TABLE pacientes ADD COLUMN obra_social TEXT")
    if "horarios" not in _cols(db, "pacientes"):
        db.execute("ALTER TABLE pacientes ADD COLUMN horarios TEXT")
    if "categoria" not in _cols(db, "ejercicios"):
        db.execute("ALTER TABLE ejercicios ADD COLUMN categoria TEXT")
    db.commit()

    if db.execute("SELECT COUNT(*) FROM boxes").fetchone()[0] == 0:
        for i in (1, 2, 3):
            db.execute("INSERT INTO boxes (nombre) VALUES (?)", (f"Box {i}",))
        db.commit()

    if db.execute("SELECT COUNT(*) FROM catalogo_ejercicios").fetchone()[0] == 0:
        seed_catalogo(db)

    if db.execute("SELECT COUNT(*) FROM pacientes").fetchone()[0] == 0:
        seed_demo(db)

    db.close()


def seed_catalogo(db):
    catalogo = {
        "Miembro inferior": [
            "Sentadilla asistida", "Extensión de rodilla", "Puente de glúteos",
            "Elevación de talones", "Estocada / desplante",
        ],
        "Miembro superior": [
            "Elevación de hombro con banda", "Rotación externa de hombro",
            "Flexión de codo", "Press de hombro",
        ],
        "Columna / Core": [
            "Plancha abdominal", "Bird-dog", "Puente lumbar", "Gato-camello",
        ],
        "Cervical": [
            "Retracción cervical", "Isométrico cervical", "Estiramiento de trapecio",
        ],
        "Propiocepción / Equilibrio": [
            "Apoyo unipodal", "Bosu", "Tabla de equilibrio",
        ],
        "Estiramientos": ["Isquiotibiales", "Cuádriceps", "Gemelos", "Pectoral"],
        "Cardio / Aeróbico": ["Bicicleta fija", "Cinta", "Elíptico"],
    }
    for cat, exs in catalogo.items():
        for nom in exs:
            db.execute(
                "INSERT INTO catalogo_ejercicios (nombre, categoria) VALUES (?,?)",
                (nom, cat),
            )
    db.commit()


def seed_demo(db):
    hoy = date.today().isoformat()
    demo = [
        ("Juan", "Pérez", "30111222", "1145678901", "OSDE",
         "Esguince de tobillo grado II", 10, 3, "Lun, Mié, Vie"),
        ("María", "Gómez", "28999888", "1156789012", "Swiss Medical",
         "Cervicalgia crónica", 12, 7, "Mar, Jue"),
        ("Lucía", "Fernández", "35222333", "1167890123", "IOMA",
         "Post-operatorio LCA", 20, 5, "Lun, Mar, Mié, Jue, Vie"),
        ("Carlos", "Ramírez", "27333444", "1178901234", "PAMI",
         "Lumbalgia mecánica", 8, 6, "Lun, Jue"),
    ]
    ids = []
    for d in demo:
        cur = db.execute(
            """INSERT INTO pacientes
               (nombre, apellido, dni, telefono, obra_social, diagnostico,
                sesiones_totales, sesiones_usadas, dias, creado)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (*d, hoy),
        )
        ids.append(cur.lastrowid)

    ejercicios = {
        ids[0]: [
            ("Apoyo unipodal", "Propiocepción / Equilibrio", "3", "30 seg", "Ojos abiertos"),
            ("Elevación de talones", "Miembro inferior", "3", "15", "Sin dolor"),
        ],
        ids[1]: [
            ("Estiramiento de trapecio", "Cervical", "3", "20 seg", ""),
            ("Retracción cervical", "Cervical", "3", "12", "Suave"),
        ],
        ids[2]: [
            ("Extensión de rodilla", "Miembro inferior", "4", "12", "Con banda"),
            ("Sentadilla asistida", "Miembro inferior", "3", "10", "Rango parcial"),
        ],
    }
    for pid, exs in ejercicios.items():
        for e in exs:
            db.execute(
                """INSERT INTO ejercicios
                   (paciente_id, nombre, categoria, series, reps, notas)
                   VALUES (?,?,?,?,?,?)""",
                (pid, *e),
            )

    turnos = [
        (ids[0], "09:00"), (ids[1], "09:00"), (ids[2], "10:00"),
        (ids[3], "10:00"), (ids[0], "11:00"), (ids[1], "11:00"), (ids[2], "11:00"),
    ]
    for pid, hora in turnos:
        db.execute(
            """INSERT INTO turnos (paciente_id, fecha, hora, estado, duracion_min)
               VALUES (?,?,?, 'agendado', ?)""",
            (pid, hoy, hora, DURACION_DEFAULT),
        )
    db.commit()


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def nombre_completo(row):
    return f"{row['nombre']} {row['apellido']}".strip()


def paciente_dict(p):
    quedan = (p["sesiones_totales"] or 0) - (p["sesiones_usadas"] or 0)
    keys = p.keys()
    return {
        "id": p["id"],
        "nombre": p["nombre"],
        "apellido": p["apellido"],
        "nombre_completo": nombre_completo(p),
        "dni": p["dni"] or "",
        "telefono": p["telefono"] or "",
        "obra_social": (p["obra_social"] if "obra_social" in keys else "") or "",
        "diagnostico": p["diagnostico"] or "",
        "sesiones_totales": p["sesiones_totales"] or 0,
        "sesiones_usadas": p["sesiones_usadas"] or 0,
        "sesiones_quedan": quedan,
        "dias": p["dias"] or "",
        "dias_idx": str_to_dias(p["dias"]),
        "horarios": parse_horarios(p["horarios"] if "horarios" in keys else ""),
        "notas": p["notas"] or "",
    }


def registrar_evento(tipo, paciente_id=None, texto=""):
    run("INSERT INTO eventos (ts, tipo, paciente_id, texto) VALUES (?,?,?,?)",
        (datetime.now().isoformat(), tipo, paciente_id, texto))


def get_config():
    return {r["clave"]: r["valor"] for r in q("SELECT * FROM config")}


# --------------------------------------------------------------------------
# Vistas
# --------------------------------------------------------------------------
@app.route("/")
def index():
    return redirect(url_for("recepcion"))


@app.route("/recepcion")
def recepcion():
    return render_template("recepcion.html", activo="recepcion")


@app.route("/pacientes")
def pacientes():
    filas = q(
        "SELECT * FROM pacientes ORDER BY apellido COLLATE NOCASE, nombre COLLATE NOCASE"
    )
    return render_template(
        "pacientes.html", activo="pacientes",
        pacientes=[paciente_dict(p) for p in filas],
    )


@app.route("/paciente/<int:pid>")
def ficha(pid):
    p = q1("SELECT * FROM pacientes WHERE id=?", (pid,))
    if not p:
        abort(404)
    exs = q("SELECT * FROM ejercicios WHERE paciente_id=? ORDER BY id", (pid,))
    hist = q(
        """SELECT * FROM turnos WHERE paciente_id=?
           ORDER BY fecha DESC, hora DESC LIMIT 40""",
        (pid,),
    )
    return render_template(
        "ficha.html", activo="pacientes", p=paciente_dict(p),
        ejercicios=exs, historial=hist,
    )


@app.route("/agenda")
def agenda():
    return render_template("agenda.html", activo="agenda")


@app.route("/ejercicios")
def ejercicios_page():
    return render_template("ejercicios.html", activo="ejercicios")


# --------------------------------------------------------------------------
# API — estado en vivo de la recepción
# --------------------------------------------------------------------------
@app.route("/api/estado")
def api_estado():
    hoy = date.today().isoformat()
    ahora = datetime.now()

    boxes = q("SELECT * FROM boxes WHERE activo=1 ORDER BY id")
    box_estado = []
    ocupados = set()

    for b in boxes:
        turno = q1(
            """SELECT t.*, p.nombre, p.apellido, p.diagnostico
               FROM turnos t JOIN pacientes p ON p.id = t.paciente_id
               WHERE t.box_id=? AND t.estado='en_curso'
               ORDER BY t.inicio DESC LIMIT 1""",
            (b["id"],),
        )
        info = {"id": b["id"], "nombre": b["nombre"], "ocupado": False}
        if turno:
            ocupados.add(b["id"])
            inicio = datetime.fromisoformat(turno["inicio"])
            dur = turno["duracion_min"] or DURACION_DEFAULT
            restante = int(dur * 60 - (ahora - inicio).total_seconds())
            info.update({
                "ocupado": True, "turno_id": turno["id"],
                "paciente_id": turno["paciente_id"],
                "paciente": f"{turno['nombre']} {turno['apellido']}",
                "diagnostico": turno["diagnostico"] or "", "duracion": dur,
                "restante_seg": restante, "vencido": restante <= 0,
            })
        box_estado.append(info)

    libres = [{"id": b["id"], "nombre": b["nombre"]}
              for b in boxes if b["id"] not in ocupados]

    espera_rows = q(
        """SELECT t.*, p.nombre, p.apellido, p.diagnostico, p.obra_social,
                  p.sesiones_totales, p.sesiones_usadas
           FROM turnos t JOIN pacientes p ON p.id = t.paciente_id
           WHERE t.fecha=? AND t.estado='en_espera'
           ORDER BY t.hora, t.id""",
        (hoy,),
    )
    espera = [{
        "turno_id": t["id"], "paciente_id": t["paciente_id"],
        "paciente": f"{t['nombre']} {t['apellido']}", "hora": t["hora"] or "",
        "diagnostico": t["diagnostico"] or "", "obra_social": t["obra_social"] or "",
        "sesiones_quedan": (t["sesiones_totales"] or 0) - (t["sesiones_usadas"] or 0),
    } for t in espera_rows]

    agenda_rows = q(
        """SELECT t.*, p.nombre, p.apellido
           FROM turnos t JOIN pacientes p ON p.id = t.paciente_id
           WHERE t.fecha=? AND t.estado NOT IN ('terminado','ausente','perdido')
           ORDER BY t.hora, t.id""",
        (hoy,),
    )
    por_hora = {}
    for t in agenda_rows:
        h = t["hora"] or "Sin hora"
        por_hora.setdefault(h, []).append({
            "turno_id": t["id"], "paciente_id": t["paciente_id"],
            "paciente": f"{t['nombre']} {t['apellido']}", "estado": t["estado"],
        })
    agenda_por_hora = [{"hora": h, "cantidad": len(v), "turnos": v}
                       for h, v in sorted(por_hora.items())]

    def count(estado):
        return q1("SELECT COUNT(*) c FROM turnos WHERE fecha=? AND estado=?",
                  (hoy, estado))["c"]

    total = q1("SELECT COUNT(*) c FROM turnos WHERE fecha=?", (hoy,))["c"]
    stats = {
        "total": total, "atendidos": count("terminado"),
        "en_curso": count("en_curso"), "espera": count("en_espera"),
        "ausentes": count("ausente") + count("perdido"),
        "pendientes": count("agendado"),
    }

    return jsonify({
        "ahora": ahora.isoformat(), "boxes": box_estado, "libres": libres,
        "espera": espera, "agenda_por_hora": agenda_por_hora, "stats": stats,
    })


@app.route("/api/alertas")
def api_alertas():
    """Pacientes con pocas sesiones (por renovar bono/autorización)."""
    rows = q(
        """SELECT * FROM pacientes
           WHERE sesiones_totales > 0
             AND (sesiones_totales - sesiones_usadas) <= 2
           ORDER BY (sesiones_totales - sesiones_usadas), apellido"""
    )
    return jsonify([{
        "id": r["id"], "nombre_completo": nombre_completo(r),
        "obra_social": r["obra_social"] or "",
        "quedan": max(0, (r["sesiones_totales"] or 0) - (r["sesiones_usadas"] or 0)),
    } for r in rows])


@app.route("/api/eventos")
def api_eventos():
    rows = q("SELECT * FROM eventos ORDER BY id DESC LIMIT 40")
    return jsonify([{
        "ts": r["ts"], "tipo": r["tipo"], "texto": r["texto"],
        "paciente_id": r["paciente_id"],
    } for r in rows])


# --------------------------------------------------------------------------
# API — agenda / calendario
# --------------------------------------------------------------------------
@app.route("/api/agenda_rango")
def api_agenda_rango():
    desde = request.args.get("desde") or date.today().isoformat()
    hasta = request.args.get("hasta") or desde
    rows = q(
        """SELECT t.*, p.nombre, p.apellido
           FROM turnos t JOIN pacientes p ON p.id = t.paciente_id
           WHERE t.fecha BETWEEN ? AND ?
           ORDER BY t.fecha, t.hora, t.id""",
        (desde, hasta),
    )
    por_fecha = {}
    for t in rows:
        por_fecha.setdefault(t["fecha"], []).append({
            "turno_id": t["id"], "paciente_id": t["paciente_id"],
            "paciente": f"{t['nombre']} {t['apellido']}",
            "hora": t["hora"] or "", "estado": t["estado"],
        })
    return jsonify(por_fecha)


# --------------------------------------------------------------------------
# API — flujo de turnos
# --------------------------------------------------------------------------
@app.route("/api/turno/<int:tid>/asistencia", methods=["POST"])
def api_asistencia(tid):
    t = q1("""SELECT t.*, p.nombre, p.apellido FROM turnos t
              JOIN pacientes p ON p.id=t.paciente_id WHERE t.id=?""", (tid,))
    run("UPDATE turnos SET estado='en_espera' WHERE id=?", (tid,))
    if t:
        registrar_evento("llegada", t["paciente_id"],
                          f"{t['nombre']} {t['apellido']} llegó (sala de espera)")
    return jsonify(ok=True)


@app.route("/api/turno/<int:tid>/iniciar", methods=["POST"])
def api_iniciar(tid):
    data = request.get_json(force=True, silent=True) or {}
    box_id = data.get("box_id")
    dur = int(data.get("duracion") or DURACION_DEFAULT)
    if not box_id:
        return jsonify(ok=False, error="Falta el box"), 400
    if q1("SELECT 1 FROM turnos WHERE box_id=? AND estado='en_curso'", (box_id,)):
        return jsonify(ok=False, error="Ese box está ocupado"), 409
    run(
        """UPDATE turnos SET estado='en_curso', box_id=?, inicio=?,
           duracion_min=?, fin=NULL WHERE id=?""",
        (box_id, datetime.now().isoformat(), dur, tid),
    )
    t = q1("""SELECT t.*, p.nombre, p.apellido, b.nombre AS box
              FROM turnos t JOIN pacientes p ON p.id=t.paciente_id
              LEFT JOIN boxes b ON b.id=t.box_id WHERE t.id=?""", (tid,))
    if t:
        registrar_evento("a_box", t["paciente_id"],
                          f"{t['nombre']} {t['apellido']} → {t['box']}")
    return jsonify(ok=True)


@app.route("/api/paciente/<int:pid>/a_box", methods=["POST"])
def api_a_box(pid):
    """Pone al paciente directo en un box. Cuenta como asistencia:
    usa el turno de hoy si existe, o crea uno."""
    data = request.get_json(force=True, silent=True) or {}
    box_id = data.get("box_id")
    dur = int(data.get("duracion") or DURACION_DEFAULT)
    if not box_id:
        return jsonify(ok=False, error="Falta el box"), 400
    if q1("SELECT 1 FROM turnos WHERE box_id=? AND estado='en_curso'", (box_id,)):
        return jsonify(ok=False, error="Ese box está ocupado"), 409

    hoy = date.today().isoformat()
    t = q1(
        """SELECT * FROM turnos WHERE paciente_id=? AND fecha=?
           AND estado IN ('agendado','en_espera') ORDER BY hora LIMIT 1""",
        (pid, hoy),
    )
    if t:
        tid = t["id"]
    else:
        tid = run(
            """INSERT INTO turnos (paciente_id, fecha, hora, estado, duracion_min)
               VALUES (?,?,?, 'agendado', ?)""",
            (pid, hoy, datetime.now().strftime("%H:%M"), dur),
        )
    run(
        """UPDATE turnos SET estado='en_curso', box_id=?, inicio=?,
           duracion_min=?, fin=NULL WHERE id=?""",
        (box_id, datetime.now().isoformat(), dur, tid),
    )
    info = q1("""SELECT p.nombre, p.apellido, b.nombre AS box
                 FROM pacientes p, boxes b WHERE p.id=? AND b.id=?""",
              (pid, box_id))
    if info:
        registrar_evento("a_box", pid,
                          f"{info['nombre']} {info['apellido']} → {info['box']}")
    return jsonify(ok=True, turno_id=tid)


def _descontar_sesion(pid):
    run(
        """UPDATE pacientes
           SET sesiones_usadas = MIN(sesiones_totales, sesiones_usadas + 1)
           WHERE id=?""",
        (pid,),
    )


@app.route("/api/turno/<int:tid>/terminar", methods=["POST"])
@app.route("/api/turno/<int:tid>/asistio", methods=["POST"])
def api_terminar(tid):
    t = q1("""SELECT t.*, p.nombre, p.apellido, b.nombre AS box
              FROM turnos t JOIN pacientes p ON p.id=t.paciente_id
              LEFT JOIN boxes b ON b.id=t.box_id WHERE t.id=?""", (tid,))
    if not t:
        return jsonify(ok=False, error="Turno inexistente"), 404
    ya_contaba = t["estado"] == "terminado"
    run("UPDATE turnos SET estado='terminado', fin=?, box_id=NULL WHERE id=?",
        (datetime.now().isoformat(), tid))
    if not ya_contaba:
        _descontar_sesion(t["paciente_id"])
    box = t["box"] or ""
    registrar_evento("fin", t["paciente_id"],
                     f"{t['nombre']} {t['apellido']} terminó" + (f" en {box}" if box else ""))
    p = q1("SELECT * FROM pacientes WHERE id=?", (t["paciente_id"],))
    quedan = (p["sesiones_totales"] or 0) - (p["sesiones_usadas"] or 0)
    return jsonify(ok=True, paciente=f"{t['nombre']} {t['apellido']}",
                   box=box, sesiones_quedan=quedan)


@app.route("/api/turno/<int:tid>/ausente", methods=["POST"])
def api_ausente(tid):
    run("UPDATE turnos SET estado='ausente', box_id=NULL WHERE id=?", (tid,))
    return jsonify(ok=True)


@app.route("/api/turno/<int:tid>/perdido", methods=["POST"])
def api_perdido(tid):
    run("UPDATE turnos SET estado='perdido', box_id=NULL WHERE id=?", (tid,))
    return jsonify(ok=True)


@app.route("/api/turno/<int:tid>/reprogramar", methods=["POST"])
def api_reprogramar(tid):
    """No asistió: mueve el turno a la próxima fecha disponible después de la
    última sesión agendada del paciente, respetando sus días y horarios."""
    t = q1("SELECT * FROM turnos WHERE id=?", (tid,))
    if not t:
        return jsonify(ok=False, error="Turno inexistente"), 404
    p = q1("SELECT * FROM pacientes WHERE id=?", (t["paciente_id"],))
    dias = str_to_dias(p["dias"]) if p else []
    horarios = parse_horarios(p["horarios"]) if p else {}

    ult = q1(
        """SELECT MAX(fecha) f FROM turnos
           WHERE paciente_id=? AND estado='agendado' AND id<>?""",
        (t["paciente_id"], tid),
    )
    base = ult["f"] if ult and ult["f"] else t["fecha"]
    cur = date.fromisoformat(base) + timedelta(days=1)
    if not dias:
        dias = [date.fromisoformat(t["fecha"]).weekday()]
    for _ in range(400):
        if cur.weekday() in dias:
            break
        cur += timedelta(days=1)

    hora = horarios.get(str(cur.weekday())) or t["hora"] or ""
    run("UPDATE turnos SET estado='ausente', box_id=NULL WHERE id=?", (tid,))
    nid = run(
        """INSERT INTO turnos (paciente_id, fecha, hora, estado, duracion_min)
           VALUES (?,?,?, 'agendado', ?)""",
        (t["paciente_id"], cur.isoformat(), hora, t["duracion_min"] or DURACION_DEFAULT),
    )
    return jsonify(ok=True, id=nid, fecha=cur.isoformat())


@app.route("/api/turno/<int:tid>/cancelar", methods=["POST"])
def api_cancelar_estado(tid):
    run("UPDATE turnos SET estado='en_espera', box_id=NULL, inicio=NULL WHERE id=?",
        (tid,))
    return jsonify(ok=True)


@app.route("/api/turno", methods=["POST"])
def api_nuevo_turno():
    data = request.get_json(force=True, silent=True) or {}
    pid = data.get("paciente_id")
    fecha = data.get("fecha") or date.today().isoformat()
    hora = data.get("hora") or ""
    dur = int(data.get("duracion") or DURACION_DEFAULT)
    if not pid:
        return jsonify(ok=False, error="Falta el paciente"), 400
    tid = run(
        """INSERT INTO turnos (paciente_id, fecha, hora, estado, duracion_min)
           VALUES (?,?,?, 'agendado', ?)""",
        (pid, fecha, hora, dur),
    )
    return jsonify(ok=True, id=tid)


@app.route("/api/plan", methods=["POST"])
def api_plan():
    """Genera turnos según los días que viene el paciente, con horario
    distinto por día. Guarda dias + horarios en el paciente."""
    d = request.get_json(force=True, silent=True) or {}
    pid = d.get("paciente_id")
    dias = d.get("dias") or []
    horarios = d.get("horarios") or {}   # {"0":"18:30","1":"10:30",...}
    dur = int(d.get("duracion") or DURACION_DEFAULT)
    if not pid:
        return jsonify(ok=False, error="Falta el paciente"), 400
    if not dias:
        return jsonify(ok=False, error="Elegí al menos un día de la semana"), 400

    dias = sorted(set(int(x) for x in dias))
    p = q1("SELECT * FROM pacientes WHERE id=?", (pid,))
    if not p:
        return jsonify(ok=False, error="Paciente inexistente"), 404

    restantes = (p["sesiones_totales"] or 0) - (p["sesiones_usadas"] or 0)
    cantidad = int(d.get("cantidad") or restantes or 0)
    if cantidad <= 0:
        return jsonify(ok=False, error="No hay sesiones para agendar"), 400

    desde = d.get("desde") or date.today().isoformat()
    cur = date.fromisoformat(desde)
    hora_default = d.get("hora") or ""

    creados = 0
    guard = 0
    while creados < cantidad and guard < 800:
        wd = cur.weekday()
        if wd in dias:
            hora = horarios.get(str(wd)) or horarios.get(wd) or hora_default
            run(
                """INSERT INTO turnos (paciente_id, fecha, hora, estado, duracion_min)
                   VALUES (?,?,?, 'agendado', ?)""",
                (pid, cur.isoformat(), hora, dur),
            )
            creados += 1
        cur += timedelta(days=1)
        guard += 1

    run("UPDATE pacientes SET dias=?, horarios=? WHERE id=?",
        (dias_to_str(dias), json.dumps(horarios), pid))
    return jsonify(ok=True, creados=creados)


@app.route("/api/turno/<int:tid>/borrar", methods=["POST"])
def api_borrar_turno(tid):
    run("DELETE FROM turnos WHERE id=?", (tid,))
    return jsonify(ok=True)


# --------------------------------------------------------------------------
# API — pacientes
# --------------------------------------------------------------------------
@app.route("/api/pacientes")
def api_pacientes():
    term = (request.args.get("q") or "").strip()
    if term:
        like = f"%{term}%"
        filas = q(
            """SELECT * FROM pacientes
               WHERE nombre LIKE ? OR apellido LIKE ? OR dni LIKE ?
               ORDER BY apellido COLLATE NOCASE LIMIT 50""",
            (like, like, like),
        )
    else:
        filas = q("SELECT * FROM pacientes ORDER BY apellido COLLATE NOCASE LIMIT 50")
    return jsonify([paciente_dict(p) for p in filas])


@app.route("/api/paciente", methods=["POST"])
def api_nuevo_paciente():
    d = request.get_json(force=True, silent=True) or {}
    nombre = (d.get("nombre") or "").strip()
    apellido = (d.get("apellido") or "").strip()
    if not nombre or not apellido:
        return jsonify(ok=False, error="Nombre y apellido son obligatorios"), 400
    pid = run(
        """INSERT INTO pacientes
           (nombre, apellido, dni, telefono, obra_social, diagnostico,
            sesiones_totales, sesiones_usadas, dias, notas, creado)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            nombre, apellido, (d.get("dni") or "").strip(),
            (d.get("telefono") or "").strip(), (d.get("obra_social") or "").strip(),
            (d.get("diagnostico") or "").strip(),
            int(d.get("sesiones_totales") or 0), int(d.get("sesiones_usadas") or 0),
            (d.get("dias") or "").strip(), (d.get("notas") or "").strip(),
            date.today().isoformat(),
        ),
    )
    return jsonify(ok=True, id=pid)


@app.route("/api/paciente/<int:pid>", methods=["POST"])
def api_editar_paciente(pid):
    d = request.get_json(force=True, silent=True) or {}
    run(
        """UPDATE pacientes SET
             nombre=?, apellido=?, dni=?, telefono=?, obra_social=?, diagnostico=?,
             sesiones_totales=?, sesiones_usadas=?, dias=?, notas=?
           WHERE id=?""",
        (
            (d.get("nombre") or "").strip(), (d.get("apellido") or "").strip(),
            (d.get("dni") or "").strip(), (d.get("telefono") or "").strip(),
            (d.get("obra_social") or "").strip(), (d.get("diagnostico") or "").strip(),
            int(d.get("sesiones_totales") or 0), int(d.get("sesiones_usadas") or 0),
            (d.get("dias") or "").strip(), (d.get("notas") or "").strip(), pid,
        ),
    )
    return jsonify(ok=True)


@app.route("/api/paciente/<int:pid>/borrar", methods=["POST"])
def api_borrar_paciente(pid):
    run("DELETE FROM pacientes WHERE id=?", (pid,))
    return jsonify(ok=True)


@app.route("/api/paciente/<int:pid>/ejercicio", methods=["POST"])
def api_nuevo_ejercicio(pid):
    d = request.get_json(force=True, silent=True) or {}
    nombre = (d.get("nombre") or "").strip()
    if not nombre:
        return jsonify(ok=False, error="Falta el nombre del ejercicio"), 400
    eid = run(
        """INSERT INTO ejercicios (paciente_id, nombre, categoria, series, reps, notas)
           VALUES (?,?,?,?,?,?)""",
        (
            pid, nombre, (d.get("categoria") or "").strip(),
            (d.get("series") or "").strip(), (d.get("reps") or "").strip(),
            (d.get("notas") or "").strip(),
        ),
    )
    return jsonify(ok=True, id=eid)


@app.route("/api/ejercicio/<int:eid>/borrar", methods=["POST"])
def api_borrar_ejercicio(eid):
    run("DELETE FROM ejercicios WHERE id=?", (eid,))
    return jsonify(ok=True)


# --------------------------------------------------------------------------
# API — catálogo de ejercicios
# --------------------------------------------------------------------------
@app.route("/api/catalogo")
def api_catalogo():
    rows = q("SELECT * FROM catalogo_ejercicios ORDER BY categoria, nombre")
    por_cat = {}
    for r in rows:
        cat = r["categoria"] or "Sin categoría"
        por_cat.setdefault(cat, []).append({"id": r["id"], "nombre": r["nombre"]})
    return jsonify(por_cat)


@app.route("/api/catalogo", methods=["POST"])
def api_nuevo_catalogo():
    d = request.get_json(force=True, silent=True) or {}
    nombre = (d.get("nombre") or "").strip()
    categoria = (d.get("categoria") or "").strip() or "Sin categoría"
    if not nombre:
        return jsonify(ok=False, error="Falta el nombre"), 400
    cid = run("INSERT INTO catalogo_ejercicios (nombre, categoria) VALUES (?,?)",
              (nombre, categoria))
    return jsonify(ok=True, id=cid)


@app.route("/api/catalogo/<int:cid>/borrar", methods=["POST"])
def api_borrar_catalogo(cid):
    run("DELETE FROM catalogo_ejercicios WHERE id=?", (cid,))
    return jsonify(ok=True)


# --------------------------------------------------------------------------
# API — config (teléfono de la kine para avisos de WhatsApp, etc.)
# --------------------------------------------------------------------------
@app.route("/api/config")
def api_config_get():
    return jsonify(get_config())


@app.route("/api/config", methods=["POST"])
def api_config_set():
    d = request.get_json(force=True, silent=True) or {}
    for k, v in d.items():
        run("INSERT INTO config (clave, valor) VALUES (?,?) "
            "ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor",
            (k, str(v)))
    return jsonify(ok=True)


# --------------------------------------------------------------------------
# API — boxes
# --------------------------------------------------------------------------
@app.route("/api/box", methods=["POST"])
def api_nuevo_box():
    d = request.get_json(force=True, silent=True) or {}
    nombre = (d.get("nombre") or "").strip() or "Box"
    bid = run("INSERT INTO boxes (nombre) VALUES (?)", (nombre,))
    return jsonify(ok=True, id=bid)


@app.route("/api/box/<int:bid>/borrar", methods=["POST"])
def api_borrar_box(bid):
    run("UPDATE boxes SET activo=0 WHERE id=?", (bid,))
    return jsonify(ok=True)


# init_db() se ejecuta al importar el módulo para que las tablas existan también
# cuando corre bajo gunicorn (Railway no ejecuta el bloque __main__).
init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8090))
    app.run(host="0.0.0.0", port=port, debug=False)
