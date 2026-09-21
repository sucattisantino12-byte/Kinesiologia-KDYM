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
import base64
import sqlite3
import unicodedata
import threading
import shutil
import glob
import time
import re
import secrets
from datetime import datetime, date, timedelta

# Hora de Argentina. Los servidores en la nube (Railway) corren en UTC: sin esto,
# "hoy" cambiaba a las 21 h y el "no vino" automático marcaba ausentes 3 horas antes.
# '<-03>3' es UTC-3 fijo (Argentina no usa horario de verano) y no necesita tzdata.
if not os.environ.get("TZ"):
    os.environ["TZ"] = "<-03>3"
if hasattr(time, "tzset"):
    time.tzset()

from flask import (
    Flask, g, render_template, request, jsonify, redirect, url_for, abort,
    Response, send_file, session
)
from werkzeug.security import generate_password_hash, check_password_hash

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

# Nombre del centro que se ve en la app (en la demo pública: "Centro Demo").
MARCA = (os.environ.get("MARCA") or "KDYM").strip()
# Demo pública: datos de ejemplo, se entra sin contraseña y se reinicia todos los días.
# NUNCA se activa en la app real (hace falta la variable KDYM_DEMO=1).
ES_DEMO = os.environ.get("KDYM_DEMO") == "1"
DEMO_WHATSAPP = "".join(ch for ch in (os.environ.get("DEMO_WHATSAPP") or "") if ch.isdigit())
# Sesión de usuario: cookie firmada, no accesible desde JS, que no viaja en
# pedidos que vienen de otros sitios, y que dura 30 días (se renueva al usar la app).
app.config.update(
    SESSION_COOKIE_NAME="kdym_sesion",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=bool(os.environ.get("RAILWAY_PROJECT_ID") or os.environ.get("RAILWAY_ENVIRONMENT")
                               or os.environ.get("KDYM_HTTPS")),
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)

DURACION_DEFAULT = 30
TOLERANCIA_DEFAULT = 30   # minutos de tolerancia antes de marcar "no vino" automático
DIAS_ABBR = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]  # weekday() 0..6
DIAS_FULL = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]


def dia_semana(fecha_str):
    """Devuelve el día de la semana ('Lunes'...) de una fecha 'YYYY-MM-DD'."""
    try:
        return DIAS_FULL[date.fromisoformat(fecha_str).weekday()]
    except Exception:
        return ""


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
def _sin_acentos(s):
    """Pasa a minúsculas y saca acentos/tildes, para buscar sin importar cómo
    se escriba (ej: 'maria' encuentra 'María')."""
    if s is None:
        return ""
    s = unicodedata.normalize("NFD", str(s))
    return "".join(c for c in s if unicodedata.category(c) != "Mn").lower()


# Lista inicial de obras sociales/prepagas (después se edita en Configuración).
OBRAS_SOCIALES_BASE = [
    "OSDE", "Swiss Medical", "Galeno", "Medifé", "OMINT", "IOMA", "PAMI",
    "OSECAC", "OSDEPYM", "Unión Personal", "Sancor Salud", "Accord Salud",
    "Medicus", "Hospital Italiano", "Prevención Salud", "Federada Salud",
    "OSPE", "ART", "Particular",
]


def get_db():
    if "db" not in g:
        # timeout: espera si la base está ocupada (evita "database is locked"
        # cuando la recepción hace polling y hay una escritura en curso).
        g.db = sqlite3.connect(DB_PATH, timeout=15)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA busy_timeout = 15000")
        g.db.execute("PRAGMA journal_mode = WAL")
        try:
            g.db.create_function("sinacentos", 1, _sin_acentos, deterministic=True)
        except TypeError:  # SQLite viejo sin 'deterministic'
            g.db.create_function("sinacentos", 1, _sin_acentos)
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


_GZIP_TIPOS = ("text/html", "text/css", "application/javascript", "text/javascript",
               "application/json", "application/manifest+json", "image/svg+xml")
_GZIP_CACHE = {}   # estáticos ya comprimidos: (ruta, etag) -> bytes


@app.after_request
def no_cache_html(resp):
    """Las páginas HTML NO se cachean: así, apenas se sube una versión nueva,
    el navegador la muestra sí o sí. Los estáticos llevan ?v=<fecha> en la URL,
    así que se guardan por un año (cambia la URL cuando cambia el archivo).
    Además se comprime todo lo que es texto (la hoja de estilos pasa de 75 KB a ~15 KB)."""
    try:
        if resp.mimetype == "text/html":
            resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            resp.headers["Pragma"] = "no-cache"
            resp.headers["Expires"] = "0"
        elif request.path.startswith("/static/") and request.args.get("v"):
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        _comprimir(resp)
    except Exception:
        pass
    return resp


def _comprimir(resp):
    import gzip
    if resp.status_code != 200 or resp.mimetype not in _GZIP_TIPOS:
        return
    if "gzip" not in (request.headers.get("Accept-Encoding") or "").lower():
        return
    if resp.headers.get("Content-Encoding"):
        return
    resp.direct_passthrough = False
    clave = None
    if request.path.startswith("/static/"):
        clave = (request.path, resp.headers.get("ETag") or resp.headers.get("Last-Modified"))
        datos = _GZIP_CACHE.get(clave)
        if datos is None:
            crudo = resp.get_data()
            if len(crudo) < 800:
                return
            datos = gzip.compress(crudo, 6)
            if len(_GZIP_CACHE) > 60:
                _GZIP_CACHE.clear()
            _GZIP_CACHE[clave] = datos
    else:
        crudo = resp.get_data()
        if len(crudo) < 800:
            return
        datos = gzip.compress(crudo, 5)
    resp.set_data(datos)
    resp.headers["Content-Encoding"] = "gzip"
    resp.headers["Content-Length"] = str(len(datos))
    resp.headers.add("Vary", "Accept-Encoding")


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
            texto TEXT,
            cerrada INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS notif_cerradas (
            clave TEXT PRIMARY KEY
        );

        CREATE TABLE IF NOT EXISTS evoluciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paciente_id INTEGER NOT NULL,
            fecha TEXT,
            texto TEXT,
            FOREIGN KEY (paciente_id) REFERENCES pacientes(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS config (
            clave TEXT PRIMARY KEY,
            valor TEXT
        );

        CREATE TABLE IF NOT EXISTS sedes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            tope_turnos INTEGER DEFAULT 4,
            orden INTEGER DEFAULT 0,
            activo INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS plantillas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paciente_id INTEGER,
            nombre_libre TEXT,
            telefono_libre TEXT,
            sede_id INTEGER,
            estado TEXT DEFAULT 'pedida',
            fecha_molde TEXT,
            fecha_entrega TEXT,
            precio TEXT,
            senia TEXT,
            notas TEXT,
            creado TEXT
        );

        CREATE TABLE IF NOT EXISTS feriados (
            fecha TEXT PRIMARY KEY,
            nombre TEXT
        );

        CREATE TABLE IF NOT EXISTS pagos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paciente_id INTEGER,
            sede_id INTEGER,
            fecha TEXT,
            monto REAL,
            metodo TEXT,
            concepto TEXT,
            creado TEXT
        );

        CREATE TABLE IF NOT EXISTS adjuntos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paciente_id INTEGER NOT NULL,
            nombre TEXT,
            tipo TEXT,
            categoria TEXT,
            datos BLOB,
            fecha TEXT,
            FOREIGN KEY (paciente_id) REFERENCES pacientes(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS consentimientos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paciente_id INTEGER NOT NULL,
            fecha TEXT,
            aclaracion TEXT,
            firma BLOB,
            FOREIGN KEY (paciente_id) REFERENCES pacientes(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS precios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT,
            monto REAL
        );

        -- Tokens de la obra social (código que valida cada sesión).
        CREATE TABLE IF NOT EXISTS tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paciente_id INTEGER,
            turno_id INTEGER,
            fecha TEXT,
            numero TEXT,
            creado TEXT
        );

        -- Obras sociales / prepagas que se ofrecen al cargar un paciente.
        CREATE TABLE IF NOT EXISTS obras_sociales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT,
            creado TEXT
        );

        -- Personas que usan la app (cada una con su usuario y contraseña).
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT,
            usuario TEXT,
            clave TEXT,
            rol TEXT DEFAULT 'recepcion',
            activo INTEGER DEFAULT 1,
            creado TEXT,
            ultimo_acceso TEXT
        );

        -- Liquidación mensual a cada obra social: estado y valor por sesión.
        CREATE TABLE IF NOT EXISTS liquidaciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            obra_social TEXT,
            mes TEXT,
            estado TEXT DEFAULT 'pendiente',
            arancel REAL,
            actualizado TEXT
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
    if "peso" not in _cols(db, "ejercicios"):
        db.execute("ALTER TABLE ejercicios ADD COLUMN peso TEXT")
    if "turno_id" not in _cols(db, "ejercicios"):
        db.execute("ALTER TABLE ejercicios ADD COLUMN turno_id INTEGER")
    if "fecha" not in _cols(db, "ejercicios"):
        db.execute("ALTER TABLE ejercicios ADD COLUMN fecha TEXT")
    if "cerrada" not in _cols(db, "eventos"):
        db.execute("ALTER TABLE eventos ADD COLUMN cerrada INTEGER DEFAULT 0")
    if "sede_id" not in _cols(db, "boxes"):
        db.execute("ALTER TABLE boxes ADD COLUMN sede_id INTEGER")
    if "sede_id" not in _cols(db, "turnos"):
        db.execute("ALTER TABLE turnos ADD COLUMN sede_id INTEGER")
    # Marca de turnos que NO deben volver a marcarse "no vino" automáticamente
    # (cuando la recepción deshace el ausente automático).
    if "sin_auto" not in _cols(db, "turnos"):
        db.execute("ALTER TABLE turnos ADD COLUMN sin_auto INTEGER DEFAULT 0")
    # Marca de turnos generados por "Simular agenda" (para poder borrarlos).
    if "sim" not in _cols(db, "turnos"):
        db.execute("ALTER TABLE turnos ADD COLUMN sim INTEGER DEFAULT 0")
    # Sede donde se cargó el paciente (se usa si todavía no tiene turnos).
    if "sede_id" not in _cols(db, "pacientes"):
        db.execute("ALTER TABLE pacientes ADD COLUMN sede_id INTEGER")
    # Número de afiliado de la obra social (para la liquidación).
    if "nro_afiliado" not in _cols(db, "pacientes"):
        db.execute("ALTER TABLE pacientes ADD COLUMN nro_afiliado TEXT")
    # Valor por sesión que paga cada obra social (se propone en la liquidación).
    if "arancel" not in _cols(db, "obras_sociales"):
        db.execute("ALTER TABLE obras_sociales ADD COLUMN arancel REAL")
    # Precio de sesión (para calcular saldos / cobros).
    if "precio_sesion" not in _cols(db, "pacientes"):
        db.execute("ALTER TABLE pacientes ADD COLUMN precio_sesion REAL")
    # Plantillas: permitir personas libres (no sólo pacientes cargados).
    _pl_cols = db.execute("PRAGMA table_info(plantillas)").fetchall()
    _pl_pac = next((c for c in _pl_cols if c[1] == "paciente_id"), None)
    if _pl_pac and _pl_pac[3] == 1:   # notnull == 1 → hay que reconstruir la tabla
        db.executescript(
            """
            CREATE TABLE plantillas_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                paciente_id INTEGER, nombre_libre TEXT, telefono_libre TEXT,
                sede_id INTEGER, estado TEXT DEFAULT 'pedida',
                fecha_molde TEXT, fecha_entrega TEXT, precio TEXT, senia TEXT,
                notas TEXT, creado TEXT
            );
            INSERT INTO plantillas_new
                (id, paciente_id, sede_id, estado, fecha_molde, fecha_entrega,
                 precio, senia, notas, creado)
            SELECT id, paciente_id, sede_id, estado, fecha_molde, fecha_entrega,
                   precio, senia, notas, creado FROM plantillas;
            DROP TABLE plantillas;
            ALTER TABLE plantillas_new RENAME TO plantillas;
            """
        )
    else:
        if "nombre_libre" not in _cols(db, "plantillas"):
            db.execute("ALTER TABLE plantillas ADD COLUMN nombre_libre TEXT")
        if "telefono_libre" not in _cols(db, "plantillas"):
            db.execute("ALTER TABLE plantillas ADD COLUMN telefono_libre TEXT")
    db.commit()

    # Sedes: crear Morón y Ramos la primera vez.
    if db.execute("SELECT COUNT(*) FROM sedes").fetchone()[0] == 0:
        db.execute("INSERT INTO sedes (nombre, tope_turnos, orden) VALUES (?,?,?)",
                   ("Morón", 4, 0))
        db.execute("INSERT INTO sedes (nombre, tope_turnos, orden) VALUES (?,?,?)",
                   ("Ramos", 4, 1))
        db.commit()

    # Migración: todo lo que ya existía (boxes y turnos sin sede) queda en la
    # primera sede (Morón), para no perder datos al introducir las sedes.
    sede0 = db.execute("SELECT id FROM sedes ORDER BY orden, id LIMIT 1").fetchone()
    if sede0:
        sede0 = sede0[0]
        db.execute("UPDATE boxes SET sede_id=? WHERE sede_id IS NULL", (sede0,))
        db.execute("UPDATE turnos SET sede_id=? WHERE sede_id IS NULL", (sede0,))
        db.commit()

    if db.execute("SELECT COUNT(*) FROM boxes").fetchone()[0] == 0:
        for i in (1, 2, 3):
            db.execute("INSERT INTO boxes (nombre, sede_id) VALUES (?,?)",
                       (f"Box {i}", sede0))
        db.commit()

    if db.execute("SELECT COUNT(*) FROM catalogo_ejercicios").fetchone()[0] == 0:
        seed_catalogo(db)

    # Obras sociales: la primera vez se arma la lista con las más comunes y
    # las que ya tienen cargadas los pacientes (sin repetir por mayúsculas/tildes).
    if db.execute("SELECT COUNT(*) FROM obras_sociales").fetchone()[0] == 0:
        vistas, hoy_iso = set(), date.today().isoformat()
        existentes = [r[0] for r in db.execute(
            "SELECT DISTINCT TRIM(obra_social) FROM pacientes WHERE TRIM(COALESCE(obra_social,''))<>''")]
        for nom in OBRAS_SOCIALES_BASE + sorted(existentes):
            nom = " ".join(nom.split())
            if nom and _sin_acentos(nom) not in vistas:
                vistas.add(_sin_acentos(nom))
                db.execute("INSERT INTO obras_sociales (nombre, creado) VALUES (?,?)", (nom, hoy_iso))
        db.commit()

    if db.execute("SELECT COUNT(*) FROM pacientes").fetchone()[0] == 0:
        seed_demo(db)

    # Barrido final: cualquier turno/box de los seeds que haya quedado sin sede
    # se asigna a la primera sede.
    if sede0:
        db.execute("UPDATE turnos SET sede_id=? WHERE sede_id IS NULL", (sede0,))
        db.execute("UPDATE boxes SET sede_id=? WHERE sede_id IS NULL", (sede0,))
        db.commit()

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
    _hor = parse_horarios(p["horarios"] if "horarios" in keys else "")
    _idx = str_to_dias(p["dias"])
    _dias_horarios = [
        {"dia": DIAS_ABBR[i], "hora": _hor.get(str(i)) or _hor.get(i) or ""}
        for i in _idx
    ]
    return {
        "id": p["id"],
        "nombre": p["nombre"],
        "apellido": p["apellido"],
        "nombre_completo": nombre_completo(p),
        "dni": p["dni"] or "",
        "telefono": p["telefono"] or "",
        "obra_social": (p["obra_social"] if "obra_social" in keys else "") or "",
        "nro_afiliado": (p["nro_afiliado"] if "nro_afiliado" in keys else "") or "",
        "diagnostico": p["diagnostico"] or "",
        "sesiones_totales": p["sesiones_totales"] or 0,
        "sesiones_usadas": p["sesiones_usadas"] or 0,
        "sesiones_quedan": quedan,
        "dias": p["dias"] or "",
        "dias_idx": _idx,
        "horarios": _hor,
        "dias_horarios": _dias_horarios,
        "notas": p["notas"] or "",
    }


def registrar_evento(tipo, paciente_id=None, texto=""):
    run("INSERT INTO eventos (ts, tipo, paciente_id, texto) VALUES (?,?,?,?)",
        (datetime.now().isoformat(), tipo, paciente_id, texto))


def get_config():
    return {r["clave"]: r["valor"] for r in q("SELECT * FROM config")}


# --------------------------------------------------------------------------
# Sedes (Morón / Ramos). El resto de la app se filtra por la "sede activa",
# que se guarda en una cookie del navegador (sede_id).
# --------------------------------------------------------------------------
def sedes_list():
    return q("SELECT * FROM sedes WHERE activo=1 ORDER BY orden, id")


def sede_actual_id():
    """Sede activa según la cookie; si no hay/es inválida, la primera sede."""
    sid = request.cookies.get("sede_id")
    if sid:
        try:
            sid = int(sid)
            if q1("SELECT 1 FROM sedes WHERE id=? AND activo=1", (sid,)):
                return sid
        except Exception:
            pass
    r = q1("SELECT id FROM sedes WHERE activo=1 ORDER BY orden, id LIMIT 1")
    return r["id"] if r else None


def sede_nombre(sid):
    r = q1("SELECT nombre FROM sedes WHERE id=?", (sid,))
    return r["nombre"] if r else ""


def tope_de_sede(sid):
    r = q1("SELECT tope_turnos FROM sedes WHERE id=?", (sid,))
    return (r["tope_turnos"] if r and r["tope_turnos"] else 0) or 0


def _es_feriado(fecha):
    """True si esa fecha ('YYYY-MM-DD') está marcada como feriado."""
    return bool(q1("SELECT 1 FROM feriados WHERE fecha=?", (fecha,)))


def _sede_de_args():
    """Sede pasada en la query (?sede=), validada; si no, la sede activa.
    Permite ver el calendario de otra sede sin cambiar la sede activa."""
    sid = request.args.get("sede", type=int)
    if sid and q1("SELECT 1 FROM sedes WHERE id=? AND activo=1", (sid,)):
        return sid
    return sede_actual_id()


def _sede_de_request(data):
    """Sede que viene en el body (selector del modal) o la sede activa."""
    sid = data.get("sede_id")
    if sid:
        try:
            sid = int(sid)
            if q1("SELECT 1 FROM sedes WHERE id=? AND activo=1", (sid,)):
                return sid
        except Exception:
            pass
    return sede_actual_id()


def _slot_ocupado(sede_id, fecha, hora, excluir_turno=None, excluir_paciente=None):
    """Cuántos turnos 'vivos' (no ausente/perdido) hay en ese horario y sede.
    `excluir_paciente` sirve al reprogramar: los turnos de ese paciente se van a
    reemplazar, así que no deben contarse como ocupados."""
    sql = ("""SELECT COUNT(*) c FROM turnos
              WHERE sede_id=? AND fecha=? AND hora=? AND hora<>''
                AND estado NOT IN ('ausente','perdido')""")
    args = [sede_id, fecha, hora]
    if excluir_turno:
        sql += " AND id<>?"
        args.append(excluir_turno)
    if excluir_paciente:
        sql += " AND paciente_id<>?"
        args.append(excluir_paciente)
    return q1(sql, tuple(args))["c"]


def _hm_a_min(s, dv=0):
    try:
        hh, mm = map(int, str(s).split(":"))
        return hh * 60 + mm
    except Exception:
        return dv


def _slots_dia(sede_id, fecha):
    """Slots de 30' de ese día, según el horario del centro y el tope de la sede.
    Devuelve [(hora, libres, ocupados), ...]; [] si el centro cierra ese día."""
    cfg = get_config()
    tope = tope_de_sede(sede_id) or 0
    try:
        wd = date.fromisoformat(fecha).weekday()
    except Exception:
        return []
    hor = parse_horarios(cfg.get("centro_horarios", ""))
    if hor:
        dd = hor.get(str(wd))
        if not dd:
            return []   # el centro no abre ese día
        apertura, cierre = dd.get("a", "08:00"), dd.get("c", "20:00")
    else:
        apertura, cierre = "08:00", "20:00"
    counts = {}
    for r in q("""SELECT hora, COUNT(*) c FROM turnos
                  WHERE fecha=? AND sede_id=? AND estado NOT IN ('ausente','perdido')
                    AND hora IS NOT NULL AND hora<>'' GROUP BY hora""", (fecha, sede_id)):
        counts[r["hora"]] = r["c"]
    m0, m1 = _hm_a_min(apertura, 8 * 60), _hm_a_min(cierre, 20 * 60)
    out = []
    for m in range(m0, m1, 30):
        h = f"{m // 60:02d}:{m % 60:02d}"
        oc = counts.get(h, 0)
        libres = (max(0, tope - oc) if tope else 99)
        out.append((h, libres, oc))
    return out


def _alternativa_hora(sede_id, fecha, hora):
    """La hora libre más cercana a `hora` ese día (para sugerir si está llena)."""
    libres = [(h, lib) for h, lib, oc in _slots_dia(sede_id, fecha) if lib > 0]
    if not libres:
        return None
    base = _hm_a_min(hora, 0)
    libres.sort(key=lambda x: abs(_hm_a_min(x[0], 0) - base))
    return libres[0][0]


def _mejor_slot(sede_id, fecha):
    """El horario con menos gente de ese día (para 'mejores horas'/'recomendados').
    Devuelve (hora, libres) o None si el centro no abre ese día."""
    slots = _slots_dia(sede_id, fecha)
    if not slots:
        return None
    # Menos ocupados primero; a igualdad, el más temprano.
    best = min(slots, key=lambda x: (x[2], _hm_a_min(x[0], 0)))
    return (best[0], best[1])


def _color_libres(libres, tope):
    """Semáforo de un horario: verde (2+ libres), amarillo (1), rojo (lleno)."""
    if tope and libres <= 0:
        return "rojo"
    return "amar" if libres <= 1 else "verde"


def _proxima_ocurrencia(weekday, desde):
    """La próxima fecha (>= desde) de ese día de la semana que no sea feriado."""
    cur = date.fromisoformat(desde)
    for _ in range(70):
        if cur.weekday() == weekday and not _es_feriado(cur.isoformat()):
            return cur.isoformat()
        cur += timedelta(days=1)
    return None


@app.context_processor
def inject_asset_version():
    """Versión (mtime) de los archivos estáticos para evitar caché viejo:
    se agrega como ?v=... a los <link>/<script>. Cambia solo al editar el archivo."""
    def asset_v(filename):
        try:
            return int(os.path.getmtime(os.path.join(BASE_DIR, "static", filename)))
        except Exception:
            return 0
    return {"asset_v": asset_v}


@app.context_processor
def inject_sedes():
    """Deja disponibles la lista de sedes y la activa en todas las plantillas."""
    try:
        sedes = [dict(r) for r in sedes_list()]
        actual = sede_actual_id()
        nombre = next((s["nombre"] for s in sedes if s["id"] == actual), "")
        # Cantidad de boxes activos de la sede activa: se renderiza directo para
        # que "En sesión ahora" no muestre 0 y después salte al número real.
        nb = q1("SELECT COUNT(*) c FROM boxes WHERE activo=1 AND sede_id=?",
                (actual,)) if actual else None
        demo = (q1("SELECT valor FROM config WHERE clave='modo_demo'") or {"valor": "0"})["valor"] == "1"
        enc = q1("SELECT COUNT(*) c FROM turnos WHERE estado='en_curso' AND fecha=? AND sede_id=?",
                 (date.today().isoformat(), actual)) if actual else None
        try:
            notif_n = len(_alertas_abiertas())
        except Exception:
            notif_n = 0
        try:
            obras = _obras_sociales()
        except Exception:
            obras = list(OBRAS_SOCIALES_BASE)
        return {"sedes_all": sedes, "sede_actual_id": actual,
                "sede_actual_nombre": nombre,
                "side_boxes_n": (nb["c"] if nb else 0), "modo_demo": demo,
                "side_encurso_n": (enc["c"] if enc else 0), "notif_n": notif_n,
                "obras_sociales": obras}
    except Exception:
        return {"sedes_all": [], "sede_actual_id": None,
                "sede_actual_nombre": "", "side_boxes_n": 0, "modo_demo": False,
                "side_encurso_n": 0, "notif_n": 0, "obras_sociales": list(OBRAS_SOCIALES_BASE)}


# --------------------------------------------------------------------------
# Usuarios y acceso
# --------------------------------------------------------------------------
ROLES = {"admin": "Administrador", "recepcion": "Recepción"}
CLAVE_MIN = 8

# Lo único que se ve sin haber entrado: la pantalla de ingreso y lo que necesita.
_ENDPOINTS_PUBLICOS = {"login", "login_post", "primer_usuario", "static", "sw_js", "manifest", "demo_entrar"}
# Sólo administradores: la plata del centro, los usuarios, la base completa y el modo demo.
_ENDPOINTS_ADMIN = {
    "reportes_page", "api_reportes",
    "api_backup", "api_backups", "api_backup_ahora", "api_backup_descargar",
    "api_usuarios", "api_nuevo_usuario", "api_editar_usuario", "api_borrar_usuario",
    "api_nuevo_precio", "api_borrar_precio", "api_liquidacion_arancel",
    "api_seed_prueba", "api_simular_agenda", "api_limpiar_simulacion",
}


def _clave_de_sesion():
    """Clave que firma las cookies de sesión. Se genera una vez y se guarda en
    un archivo junto a la base (no en la tabla config, que se lee por la API)."""
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    ruta = os.path.join(_db_dir or BASE_DIR, ".kdym_clave_sesion")
    try:
        with open(ruta, encoding="utf-8") as f:
            k = f.read().strip()
        if len(k) >= 32:
            return k
    except OSError:
        pass
    k = secrets.token_hex(32)
    try:
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(k)
    except OSError:
        pass
    return k


def _huella(u):
    # Cambia cuando cambia la contraseña: así se cierran las sesiones viejas.
    return (u["clave"] or "")[-16:]


def usuario_actual():
    if "usuario" in g:
        return g.usuario
    u = None
    uid = session.get("uid")
    if uid:
        r = q1("SELECT * FROM usuarios WHERE id=?", (uid,))
        if r and r["activo"] and session.get("hv") == _huella(r):
            u = r
    g.usuario = u
    return u


def es_admin():
    u = usuario_actual()
    return bool(u and u["rol"] == "admin")


def _hay_usuarios():
    return bool(q1("SELECT 1 FROM usuarios LIMIT 1"))


def _iniciar_sesion(u, recordar=True):
    session.clear()
    session["uid"] = u["id"]
    session["hv"] = _huella(u)
    session.permanent = bool(recordar)
    run("UPDATE usuarios SET ultimo_acceso=? WHERE id=?",
        (datetime.now().strftime("%Y-%m-%d %H:%M"), u["id"]))


def _destino_seguro(nxt):
    # Sólo rutas propias ("/agenda"), nunca otro sitio ("//x.com", "https://...").
    nxt = (nxt or "").strip()
    if (nxt.startswith("/") and not nxt.startswith("//") and "\\" not in nxt
            and not any(c.isspace() or ord(c) < 32 for c in nxt) and not nxt.startswith("/login")):
        return nxt
    return "/"


# Freno a quien prueba contraseñas: 5 intentos fallidos por usuario (o 20 desde
# la misma conexión) en 10 minutos, y hay que esperar.
_INTENTOS = {}
_INTENTOS_LOCK = threading.Lock()
_HASH_VACIO = generate_password_hash(secrets.token_hex(8))


def _ip_cliente():
    # Railway agrega la IP real al final de X-Forwarded-For (lo de adelante lo puede inventar el cliente).
    return (request.headers.get("X-Forwarded-For") or request.remote_addr or "").split(",")[-1].strip()


def _intentos(clave):
    ahora = time.time()
    with _INTENTOS_LOCK:
        lst = [t for t in _INTENTOS.get(clave, []) if ahora - t < 600]
        _INTENTOS[clave] = lst
        return len(lst)


def _fallo(*claves):
    with _INTENTOS_LOCK:
        for c in claves:
            _INTENTOS.setdefault(c, []).append(time.time())


def _usuario_valido(txt):
    txt = (txt or "").strip().lower()
    return txt if re.fullmatch(r"[a-z0-9._-]{3,30}", txt) else ""


def _usuario_json(r):
    return {"id": r["id"], "nombre": r["nombre"] or "", "usuario": r["usuario"] or "",
            "rol": r["rol"], "rol_txt": ROLES.get(r["rol"], r["rol"]),
            "activo": bool(r["activo"]), "ultimo_acceso": r["ultimo_acceso"] or ""}


@app.before_request
def _exigir_ingreso():
    ep = request.endpoint
    if ep in _ENDPOINTS_PUBLICOS:
        return None
    u = usuario_actual()
    if not u:
        if request.path.startswith("/api/"):
            return jsonify(ok=False, login=True, error="Tu sesión se cerró. Volvé a entrar."), 401
        dest = request.full_path if request.query_string else request.path
        return redirect(url_for("login", next=dest))
    if ep in _ENDPOINTS_ADMIN and u["rol"] != "admin":
        if request.path.startswith("/api/"):
            return jsonify(ok=False, error="Esto lo puede hacer solo un administrador."), 403
        return redirect(url_for("recepcion"))
    if ES_DEMO:
        if request.method == "POST":
            _DEMO_ULT["actividad"] = time.time()
        elif not request.path.startswith("/api/"):
            _demo_animar_hoy()
    return None


@app.context_processor
def inject_usuario():
    try:
        u = usuario_actual()
    except Exception:
        u = None
    base = {"marca": MARCA, "es_demo": ES_DEMO, "demo_whatsapp": DEMO_WHATSAPP}
    if not u:
        return dict(base, usuario=None, es_admin=False)
    nom = (u["nombre"] or u["usuario"] or "").strip()
    ini = "".join(w[0] for w in nom.split()[:2]).upper() or "?"
    return dict(base, usuario={"nombre": nom, "usuario": u["usuario"], "rol": u["rol"],
                               "rol_txt": ROLES.get(u["rol"], u["rol"]), "iniciales": ini},
                es_admin=u["rol"] == "admin")


@app.route("/login")
def login():
    if usuario_actual():
        return redirect(_destino_seguro(request.args.get("next")))
    if ES_DEMO:
        return render_template("login.html", demo=True, alta=False, next="/", error="", valor="")
    return render_template("login.html", alta=not _hay_usuarios(),
                           next=_destino_seguro(request.args.get("next")), error="", valor="")


@app.route("/login", methods=["POST"])
def login_post():
    f = request.form
    nxt = _destino_seguro(f.get("next"))
    usuario = (f.get("usuario") or "").strip().lower()
    clave = f.get("clave") or ""
    ip = _ip_cliente()
    if _intentos(("u", usuario)) >= 5 or _intentos(("ip", ip)) >= 20:
        return render_template("login.html", alta=False, next=nxt, valor=usuario,
                               error="Demasiados intentos fallidos. Esperá 10 minutos y probá de nuevo."), 429
    r = q1("SELECT * FROM usuarios WHERE usuario=?", (usuario,)) if usuario else None
    if not r:
        check_password_hash(_HASH_VACIO, clave)   # tarda lo mismo exista o no el usuario
    if not r or not r["activo"] or not check_password_hash(r["clave"] or "", clave):
        _fallo(("u", usuario), ("ip", ip))
        err = ("Ese usuario está desactivado. Pedile a un administrador que lo vuelva a activar."
               if r and not r["activo"] and check_password_hash(r["clave"] or "", clave)
               else "Usuario o contraseña incorrectos.")
        return render_template("login.html", alta=False, next=nxt, valor=usuario, error=err), 401
    _iniciar_sesion(r, recordar=bool(f.get("recordar")))
    return redirect(nxt)


@app.route("/login/alta", methods=["POST"])
def primer_usuario():
    """Crea la cuenta del primer administrador. Sólo funciona mientras no haya
    ningún usuario (después, los usuarios se crean desde Configuración)."""
    if _hay_usuarios() or ES_DEMO:
        return redirect(url_for("login"))
    f = request.form
    nombre = " ".join((f.get("nombre") or "").split())
    usuario = _usuario_valido(f.get("usuario"))
    clave = f.get("clave") or ""
    err = ""
    if not nombre:
        err = "Escribí tu nombre."
    elif not usuario:
        err = "El usuario tiene que tener entre 3 y 30 letras o números, sin espacios."
    elif len(clave) < CLAVE_MIN:
        err = f"La contraseña tiene que tener al menos {CLAVE_MIN} caracteres."
    elif clave != (f.get("clave2") or ""):
        err = "Las dos contraseñas no coinciden."
    if err:
        return render_template("login.html", alta=True, next="/", error=err,
                               valor=(f.get("usuario") or "").strip(), nombre=nombre), 400
    uid = run("INSERT INTO usuarios (nombre, usuario, clave, rol, activo, creado) VALUES (?,?,?,?,1,?)",
              (nombre, usuario, generate_password_hash(clave), "admin", date.today().isoformat()))
    _iniciar_sesion(q1("SELECT * FROM usuarios WHERE id=?", (uid,)), recordar=True)
    return redirect("/")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify(ok=True)


@app.route("/api/yo/clave", methods=["POST"])
def api_cambiar_mi_clave():
    u = usuario_actual()
    if _es_usuario_demo(u):
        return jsonify(ok=False, error="En la demo no se cambian las contraseñas de los usuarios de ejemplo."), 400
    d = request.get_json(force=True, silent=True) or {}
    nueva = d.get("nueva") or ""
    if not check_password_hash(u["clave"] or "", d.get("actual") or ""):
        return jsonify(ok=False, error="La contraseña actual no es correcta."), 400
    if len(nueva) < CLAVE_MIN:
        return jsonify(ok=False, error=f"La contraseña nueva tiene que tener al menos {CLAVE_MIN} caracteres."), 400
    run("UPDATE usuarios SET clave=? WHERE id=?", (generate_password_hash(nueva), u["id"]))
    # Esta sesión sigue abierta; las de otros dispositivos se cierran.
    session["hv"] = _huella(q1("SELECT * FROM usuarios WHERE id=?", (u["id"],)))
    return jsonify(ok=True)


def _admins_activos(salvo_id=None):
    return q1("SELECT COUNT(*) c FROM usuarios WHERE rol='admin' AND activo=1 AND id<>?",
              (salvo_id or 0,))["c"]


@app.route("/api/usuarios")
def api_usuarios():
    yo = usuario_actual()["id"]
    return jsonify([dict(_usuario_json(r), yo=(r["id"] == yo))
                    for r in q("SELECT * FROM usuarios ORDER BY activo DESC, nombre COLLATE NOCASE")])


@app.route("/api/usuario", methods=["POST"])
def api_nuevo_usuario():
    d = request.get_json(force=True, silent=True) or {}
    nombre = " ".join((d.get("nombre") or "").split())
    usuario = _usuario_valido(d.get("usuario"))
    clave = d.get("clave") or ""
    rol = d.get("rol") if d.get("rol") in ROLES else "recepcion"
    if not nombre:
        return jsonify(ok=False, error="Escribí el nombre de la persona."), 400
    if not usuario:
        return jsonify(ok=False, error="El usuario tiene que tener entre 3 y 30 letras o números, sin espacios."), 400
    if q1("SELECT 1 FROM usuarios WHERE usuario=?", (usuario,)):
        return jsonify(ok=False, error="Ese usuario ya existe. Elegí otro."), 400
    if len(clave) < CLAVE_MIN:
        return jsonify(ok=False, error=f"La contraseña tiene que tener al menos {CLAVE_MIN} caracteres."), 400
    uid = run("INSERT INTO usuarios (nombre, usuario, clave, rol, activo, creado) VALUES (?,?,?,?,1,?)",
              (nombre, usuario, generate_password_hash(clave), rol, date.today().isoformat()))
    return jsonify(ok=True, id=uid)


@app.route("/api/usuario/<int:uid>", methods=["POST"])
def api_editar_usuario(uid):
    r = q1("SELECT * FROM usuarios WHERE id=?", (uid,))
    if not r:
        return jsonify(ok=False, error="Ese usuario no existe."), 404
    if _es_usuario_demo(r):
        return jsonify(ok=False, error="Es un usuario de ejemplo de la demo: no se puede cambiar. Probá creando uno nuevo."), 400
    d = request.get_json(force=True, silent=True) or {}
    yo = usuario_actual()["id"]
    if "nombre" in d:
        nombre = " ".join((d.get("nombre") or "").split())
        if not nombre:
            return jsonify(ok=False, error="Escribí el nombre."), 400
        run("UPDATE usuarios SET nombre=? WHERE id=?", (nombre, uid))
    if "rol" in d:
        if d["rol"] not in ROLES:
            return jsonify(ok=False, error="Rol inválido."), 400
        if d["rol"] != r["rol"]:
            if uid == yo:
                return jsonify(ok=False, error="No podés cambiar tu propio rol."), 400
            if r["rol"] == "admin" and r["activo"] and not _admins_activos(uid):
                return jsonify(ok=False, error="Tiene que quedar al menos un administrador."), 400
            run("UPDATE usuarios SET rol=? WHERE id=?", (d["rol"], uid))
    if "activo" in d:
        activo = 1 if d["activo"] else 0
        if not activo and uid == yo:
            return jsonify(ok=False, error="No podés desactivar tu propio usuario."), 400
        if not activo and r["rol"] == "admin" and not _admins_activos(uid):
            return jsonify(ok=False, error="Tiene que quedar al menos un administrador."), 400
        run("UPDATE usuarios SET activo=? WHERE id=?", (activo, uid))
    if d.get("clave"):
        if len(d["clave"]) < CLAVE_MIN:
            return jsonify(ok=False, error=f"La contraseña tiene que tener al menos {CLAVE_MIN} caracteres."), 400
        run("UPDATE usuarios SET clave=? WHERE id=?", (generate_password_hash(d["clave"]), uid))
        if uid == yo:
            session["hv"] = _huella(q1("SELECT * FROM usuarios WHERE id=?", (uid,)))
    return jsonify(ok=True)


@app.route("/api/usuario/<int:uid>/borrar", methods=["POST"])
def api_borrar_usuario(uid):
    r = q1("SELECT * FROM usuarios WHERE id=?", (uid,))
    if not r:
        return jsonify(ok=True)
    if uid == usuario_actual()["id"]:
        return jsonify(ok=False, error="No podés borrar tu propio usuario."), 400
    if _es_usuario_demo(r):
        return jsonify(ok=False, error="Es un usuario de ejemplo de la demo: no se puede borrar."), 400
    if r["rol"] == "admin" and r["activo"] and not _admins_activos(uid):
        return jsonify(ok=False, error="Tiene que quedar al menos un administrador."), 400
    run("DELETE FROM usuarios WHERE id=?", (uid,))
    return jsonify(ok=True)


# --------------------------------------------------------------------------
# Vistas
# --------------------------------------------------------------------------
@app.route("/")
def index():
    # Si ya eligió sede (cookie), va directo a recepción; si no, al hub.
    if request.cookies.get("sede_id"):
        return redirect(url_for("recepcion"))
    return redirect(url_for("hub"))


@app.route("/hub")
def hub():
    """Pantalla para elegir la sede (Morón / Ramos)."""
    sedes = []
    for s in sedes_list():
        n_boxes = q1("SELECT COUNT(*) c FROM boxes WHERE activo=1 AND sede_id=?",
                     (s["id"],))["c"]
        hoy = date.today().isoformat()
        n_turnos = q1("SELECT COUNT(*) c FROM turnos WHERE fecha=? AND sede_id=? "
                      "AND estado NOT IN ('ausente','perdido')", (hoy, s["id"]))["c"]
        sedes.append({"id": s["id"], "nombre": s["nombre"],
                      "boxes": n_boxes, "turnos_hoy": n_turnos})
    return render_template("hub.html", sedes=sedes)


@app.route("/sede/<int:sid>")
def elegir_sede(sid):
    """Guarda la sede activa en una cookie y vuelve a recepción."""
    if not q1("SELECT 1 FROM sedes WHERE id=? AND activo=1", (sid,)):
        return redirect(url_for("hub"))
    destino = request.args.get("next") or url_for("recepcion")
    resp = redirect(destino)
    resp.set_cookie("sede_id", str(sid), max_age=60 * 60 * 24 * 365,
                    samesite="Lax")
    return resp


@app.route("/recepcion")
def recepcion():
    return render_template("recepcion.html", activo="recepcion")


@app.route("/plantillas")
def plantillas_page():
    return render_template("plantillas.html", activo="plantillas")


@app.route("/reportes")
def reportes_page():
    return render_template("reportes.html", activo="reportes")


@app.route("/liquidacion")
def liquidacion_page():
    return render_template("liquidacion.html", activo="liquidacion")


@app.route("/pacientes")
def pacientes():
    hoy = date.today().isoformat()
    hoy_ids = {r["paciente_id"] for r in
               q("SELECT DISTINCT paciente_id FROM turnos WHERE fecha=?", (hoy,))}
    filas = q(
        "SELECT * FROM pacientes ORDER BY apellido COLLATE NOCASE, nombre COLLATE NOCASE"
    )
    # Sede(s) de cada paciente para el filtro (dónde se atiende ahora).
    mem = _sedes_de_pacientes()
    lista = []
    for p in filas:
        d = paciente_dict(p)
        d["hoy"] = d["id"] in hoy_ids
        d["sedes"] = mem.get(p["id"], [])
        lista.append(d)
    # Los que tienen turno hoy van primero.
    lista.sort(key=lambda x: (not x["hoy"], x["nombre_completo"].lower()))
    return render_template("pacientes.html", activo="pacientes",
                           pacientes=lista, sedes=sedes_list())


@app.route("/paciente/<int:pid>")
def ficha(pid):
    p = q1("SELECT * FROM pacientes WHERE id=?", (pid,))
    if not p:
        abort(404)
    exs = q("SELECT * FROM ejercicios WHERE paciente_id=? ORDER BY id", (pid,))
    hist_rows = q(
        """SELECT * FROM turnos WHERE paciente_id=?
           ORDER BY fecha ASC, hora ASC LIMIT 200""",
        (pid,),
    )
    # Ejercicios hechos en cada sesión (los que quedaron ligados a un turno).
    ej_por_turno = {}
    for e in q("SELECT * FROM ejercicios WHERE paciente_id=? AND turno_id IS NOT NULL", (pid,)):
        ej_por_turno.setdefault(e["turno_id"], []).append(e)
    tok_por_turno = {k["turno_id"]: k["numero"] for k in
                     q("SELECT turno_id, numero FROM tokens WHERE paciente_id=? AND turno_id IS NOT NULL", (pid,))}
    historial = []
    hoy_iso = date.today().isoformat()
    meses = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
    nombres_sede = {s["id"]: s["nombre"] for s in sedes_list()}
    proximo = None
    for h in hist_rows:
        est = h["estado"]
        pasado = (h["fecha"] or "") < hoy_iso
        # Texto y color del estado, pensado para la recepción.
        if est == "terminado":
            et, ec = "Vino", "ok"
        elif est in ("presente", "en_curso"):
            et, ec = ("En box" if est == "en_curso" else "Presente"), "ok"
        elif est == "ausente":
            et, ec = "No vino", "danger"
        elif est == "perdido":
            et, ec = "Perdido", "danger"
        elif pasado:
            et, ec = "Sin registrar", "warn"
        elif h["fecha"] == hoy_iso:
            et, ec = "Hoy", ""
        else:
            et, ec = "Agendado", "muted-pill"
        try:
            y, m, d = map(int, (h["fecha"] or "").split("-"))
            flinda = f"{d} {meses[m - 1]} {y}" if y != date.today().year else f"{d} {meses[m - 1]}"
        except Exception:
            flinda = h["fecha"] or ""
        futuro = not pasado and est in ("agendado", "en_espera")
        item = {
            "id": h["id"],
            "fecha": h["fecha"],
            "fecha_linda": flinda,
            "hora": h["hora"] or "",
            "dia": dia_semana(h["fecha"]),
            "estado": est,
            "estado_txt": et,
            "estado_cls": ec,
            "futuro": futuro,
            "sede": nombres_sede.get(h["sede_id"], "") if len(nombres_sede) > 1 else "",
            "token": tok_por_turno.get(h["id"], ""),
            "ejercicios": ej_por_turno.get(h["id"], []),
        }
        if futuro and proximo is None:
            proximo = item
        historial.append(item)
    stats_turnos = {
        "vino": sum(1 for x in historial if x["estado"] in ("terminado", "presente", "en_curso")),
        "no_vino": sum(1 for x in historial if x["estado"] in ("ausente", "perdido")),
        "pendientes": sum(1 for x in historial if x["futuro"]),
    }
    evo = q(
        "SELECT * FROM evoluciones WHERE paciente_id=? ORDER BY fecha DESC, id DESC",
        (pid,),
    )
    return render_template(
        "ficha.html", activo="ficha", p=paciente_dict(p),
        ejercicios=exs, historial=historial, evoluciones=evo,
        proximo=proximo, stats_turnos=stats_turnos,
    )


@app.route("/agenda")
def agenda():
    return render_template("agenda.html", activo="agenda")


@app.route("/ejercicios")
def ejercicios_page():
    return render_template("ejercicios.html", activo="ejercicios")


@app.route("/notificaciones")
def notificaciones_page():
    return render_template("notificaciones.html", activo="notificaciones")


@app.route("/configuracion")
def configuracion_page():
    return render_template("configuracion.html", activo="configuracion")


# Service worker (servido desde la raíz para tener alcance global).
_SW_JS = """
// Guarda en el celular los archivos que no cambian (estilos, scripts con ?v=,
// íconos y la tipografía): la app abre más rápido y gasta menos datos.
var CACHE = 'kdym-v2';
self.addEventListener('install', function(e){ self.skipWaiting(); });
self.addEventListener('activate', function(e){
  e.waitUntil(caches.keys().then(function(ks){
    return Promise.all(ks.filter(function(k){ return k !== CACHE; }).map(function(k){ return caches.delete(k); }));
  }).then(function(){ return self.clients.claim(); }));
});
self.addEventListener('fetch', function(e){
  var req = e.request;
  if (req.method !== 'GET') return;
  var url = new URL(req.url);
  var estatico = url.origin === location.origin && url.pathname.indexOf('/static/') === 0 && url.searchParams.has('v');
  var fuente = url.hostname === 'fonts.googleapis.com' || url.hostname === 'fonts.gstatic.com';
  if (!estatico && !fuente) return;
  e.respondWith(caches.open(CACHE).then(function(c){
    return c.match(req).then(function(hit){
      if (hit) return hit;
      return fetch(req).then(function(r){
        if (r && (r.ok || r.type === 'opaque')) c.put(req, r.clone());
        return r;
      });
    });
  }));
});
self.addEventListener('notificationclick', function(e){
  e.notification.close();
  e.waitUntil(clients.matchAll({type:'window', includeUncontrolled:true}).then(function(cs){
    for (var i=0;i<cs.length;i++){ if ('focus' in cs[i]) return cs[i].focus(); }
    if (clients.openWindow) return clients.openWindow('/recepcion');
  }));
});
"""


@app.route("/sw.js")
def sw_js():
    return Response(_SW_JS, mimetype="application/javascript")


# Manifest: permite "instalar" la app en el celular o la compu (ícono propio,
# pantalla completa, sin barra del navegador).
@app.route("/manifest.webmanifest")
def manifest():
    try:
        v = int(os.path.getmtime(os.path.join(BASE_DIR, "static", "icons", "icon-512.png")))
    except Exception:
        v = 0
    data = {
        "name": f"{MARCA} · Kinesiología",
        "short_name": MARCA[:12],
        "description": "Recepción, agenda y pacientes del centro de kinesiología.",
        "start_url": "/recepcion",
        "scope": "/",
        "display": "standalone",
        "orientation": "any",
        "background_color": "#F5F7FB",
        "theme_color": "#0F2350",
        "lang": "es-AR",
        "icons": [
            {"src": f"/static/icons/icon-192.png?v={v}", "sizes": "192x192", "type": "image/png"},
            {"src": f"/static/icons/icon-512.png?v={v}", "sizes": "512x512", "type": "image/png"},
            {"src": f"/static/icons/maskable-512.png?v={v}", "sizes": "512x512",
             "type": "image/png", "purpose": "maskable"},
        ],
        "shortcuts": [
            {"name": "Recepción", "url": "/recepcion"},
            {"name": "Agenda", "url": "/agenda"},
            {"name": "Pacientes", "url": "/pacientes"},
        ],
    }
    return Response(json.dumps(data, ensure_ascii=False), mimetype="application/manifest+json")


# --------------------------------------------------------------------------
# API — notificaciones (alertas de últimas sesiones + actividad)
# --------------------------------------------------------------------------
def _alertas_abiertas():
    cerradas = {r["clave"] for r in q("SELECT clave FROM notif_cerradas")}
    out = []
    for r in q("""SELECT * FROM pacientes WHERE sesiones_totales > 0
                  AND (sesiones_totales - sesiones_usadas) <= 2
                  ORDER BY (sesiones_totales - sesiones_usadas), apellido"""):
        clave = f"alerta:{r['id']}"
        if clave in cerradas:
            continue
        quedan = max(0, (r["sesiones_totales"] or 0) - (r["sesiones_usadas"] or 0))
        out.append({"clave": clave, "paciente_id": r["id"],
                    "nombre_completo": nombre_completo(r),
                    "obra_social": r["obra_social"] or "", "quedan": quedan})
    return out


@app.route("/api/notificaciones")
def api_notificaciones():
    alertas = _alertas_abiertas()
    eventos = [{"id": r["id"], "ts": r["ts"], "tipo": r["tipo"],
                "texto": r["texto"], "paciente_id": r["paciente_id"]}
               for r in q("SELECT * FROM eventos WHERE cerrada=0 ORDER BY id DESC LIMIT 60")]
    return jsonify({"alertas": alertas, "eventos": eventos,
                    "count": len(alertas) + len(eventos)})


@app.route("/api/notificaciones/count")
def api_notificaciones_count():
    # Sólo cuenta las de renovar (últimas sesiones).
    return jsonify(count=len(_alertas_abiertas()))


@app.route("/api/notificaciones/alerta/<int:pid>/cerrar", methods=["POST"])
def api_cerrar_alerta(pid):
    run("INSERT OR IGNORE INTO notif_cerradas (clave) VALUES (?)", (f"alerta:{pid}",))
    return jsonify(ok=True)


@app.route("/api/evento/<int:eid>/cerrar", methods=["POST"])
def api_cerrar_evento(eid):
    run("UPDATE eventos SET cerrada=1 WHERE id=?", (eid,))
    return jsonify(ok=True)


@app.route("/api/notificaciones/limpiar", methods=["POST"])
def api_limpiar_notif():
    run("UPDATE eventos SET cerrada=1 WHERE cerrada=0")
    for r in q("""SELECT id FROM pacientes WHERE sesiones_totales > 0
                  AND (sesiones_totales - sesiones_usadas) <= 2"""):
        run("INSERT OR IGNORE INTO notif_cerradas (clave) VALUES (?)",
            (f"alerta:{r['id']}",))
    return jsonify(ok=True)


# --------------------------------------------------------------------------
# API — estado en vivo de la recepción
# --------------------------------------------------------------------------
def _tolerancia_min():
    cfg = get_config()
    try:
        return max(0, int(cfg.get("tolerancia_min", TOLERANCIA_DEFAULT)))
    except (TypeError, ValueError):
        return TOLERANCIA_DEFAULT


def _auto_ausentes(sede=None):
    """Marca 'no vino' automáticamente a los turnos de HOY que ya pasaron su
    tolerancia (hora + N minutos) y siguen sin llegar. Se puede deshacer:
    al deshacer se marca sin_auto=1 para que no vuelva a auto-marcarse.
    Un solo UPDATE (evita bloqueos por hacerlo turno por turno)."""
    tol = _tolerancia_min()
    hoy = date.today().isoformat()
    ahora = datetime.now()
    now_min = ahora.hour * 60 + ahora.minute
    # hora "HH:MM" -> minutos; overdue si (hora + tolerancia) <= ahora.
    cond = ("""fecha=? AND estado IN ('agendado','en_espera')
               AND sin_auto=0 AND hora IS NOT NULL AND hora<>''
               AND length(hora)>=5
               AND (CAST(substr(hora,1,2) AS INTEGER)*60
                    + CAST(substr(hora,4,2) AS INTEGER) + ?) <= ?""")
    args = [hoy, tol, now_min]
    if sede is not None:
        cond += " AND sede_id=?"
        args.append(sede)
    run(f"UPDATE turnos SET estado='ausente', box_id=NULL WHERE {cond}", tuple(args))


@app.route("/api/estado")
def api_estado():
    hoy = date.today().isoformat()
    ahora = datetime.now()
    sede = _sede_de_args()   # opcional ?sede= (la agenda mira otra sede sin cambiarla)
    _auto_ausentes(sede)   # marca "no vino" a los que pasaron la tolerancia

    boxes = q("SELECT * FROM boxes WHERE activo=1 AND sede_id=? ORDER BY id", (sede,))
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

    # Sala del día: TODOS los turnos de hoy, agrupados por hora, con su estado.
    sala_rows = q(
        """SELECT t.*, p.nombre, p.apellido, p.diagnostico, p.obra_social,
                  p.dias, p.horarios, p.sesiones_totales, p.sesiones_usadas,
                  b.nombre AS box_nombre
           FROM turnos t JOIN pacientes p ON p.id = t.paciente_id
           LEFT JOIN boxes b ON b.id = t.box_id
           WHERE t.fecha=? AND t.sede_id=? ORDER BY t.hora, t.id""",
        (hoy, sede),
    )
    sala_por_hora = {}
    presentes = []
    for t in sala_rows:
        quedan = (t["sesiones_totales"] or 0) - (t["sesiones_usadas"] or 0)
        item = {
            "turno_id": t["id"], "paciente_id": t["paciente_id"],
            "paciente": f"{t['nombre']} {t['apellido']}", "hora": t["hora"] or "",
            "estado": t["estado"], "diagnostico": t["diagnostico"] or "",
            "obra_social": t["obra_social"] or "", "sesiones_quedan": quedan,
            "dias": t["dias"] or "", "horarios": parse_horarios(t["horarios"]),
            "box": t["box_nombre"] or "",
        }
        h = t["hora"] or "Sin hora"
        sala_por_hora.setdefault(h, []).append(item)
        if t["estado"] == "presente":
            presentes.append(item)
    sala = [{"hora": h, "cantidad": len(v), "turnos": v}
            for h, v in sorted(sala_por_hora.items())]

    def count(estado):
        return q1("SELECT COUNT(*) c FROM turnos WHERE fecha=? AND sede_id=? AND estado=?",
                  (hoy, sede, estado))["c"]

    total = q1("SELECT COUNT(*) c FROM turnos WHERE fecha=? AND sede_id=?",
               (hoy, sede))["c"]
    stats = {
        "total": total,
        "atendidos": count("presente") + count("en_curso") + count("terminado"),
        "en_curso": count("en_curso"),
        "presentes": count("presente"),
        "ausentes": count("ausente") + count("perdido"),
        "pendientes": count("agendado") + count("en_espera"),
    }

    return jsonify({
        "ahora": ahora.isoformat(), "boxes": box_estado, "libres": libres,
        "sala": sala, "presentes": presentes, "stats": stats,
        "sede": {"id": sede, "nombre": sede_nombre(sede)},
        "tope": tope_de_sede(sede),
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
    sede = _sede_de_args()   # permite ver Morón o Ramos sin cambiar la sede activa
    hoy = date.today().isoformat()
    if desde <= hoy <= hasta:
        _auto_ausentes(sede)
    rows = q(
        """SELECT t.*, p.nombre, p.apellido, p.telefono
           FROM turnos t JOIN pacientes p ON p.id = t.paciente_id
           WHERE t.fecha BETWEEN ? AND ? AND t.sede_id=?
           ORDER BY t.fecha, t.hora, t.id""",
        (desde, hasta, sede),
    )
    por_fecha = {}
    for t in rows:
        por_fecha.setdefault(t["fecha"], []).append({
            "turno_id": t["id"], "paciente_id": t["paciente_id"],
            "paciente": f"{t['nombre']} {t['apellido']}",
            "hora": t["hora"] or "", "estado": t["estado"],
            "telefono": t["telefono"] or "",
            "duracion": t["duracion_min"] or DURACION_DEFAULT,
        })
    feriados = {r["fecha"]: (r["nombre"] or "Feriado")
                for r in q("SELECT fecha, nombre FROM feriados WHERE fecha BETWEEN ? AND ?",
                           (desde, hasta))}
    return jsonify({"por_fecha": por_fecha, "tope": tope_de_sede(sede),
                    "sede_nombre": sede_nombre(sede), "feriados": feriados})


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


@app.route("/api/turno/<int:tid>/vino", methods=["POST"])
def api_vino(tid):
    """El paciente vino (✓): marca presente y cuenta la sesión (una sola vez)."""
    t = q1("""SELECT t.*, p.nombre, p.apellido FROM turnos t
              JOIN pacientes p ON p.id=t.paciente_id WHERE t.id=?""", (tid,))
    if not t:
        return jsonify(ok=False, error="Turno inexistente"), 404
    ya_conto = t["estado"] in ("presente", "en_curso", "terminado")
    run("UPDATE turnos SET estado='presente' WHERE id=?", (tid,))
    d = request.get_json(force=True, silent=True) or {}
    token_info = None
    if (d.get("token") or "").strip():
        token_info = _guardar_token(t["paciente_id"], d.get("token"), t["fecha"], tid)
    if not ya_conto:
        _descontar_sesion(t["paciente_id"])
        registrar_evento("vino", t["paciente_id"],
                         f"{t['nombre']} {t['apellido']} vino (sesión contada)")
    p = q1("SELECT sesiones_totales, sesiones_usadas FROM pacientes WHERE id=?",
           (t["paciente_id"],))
    quedan = (p["sesiones_totales"] or 0) - (p["sesiones_usadas"] or 0)
    return jsonify(ok=True, sesiones_quedan=quedan, token=token_info)


@app.route("/api/turno/<int:tid>/elegir_fecha", methods=["POST"])
def api_elegir_fecha(tid):
    """No vino: el kine elige una fecha nueva para el turno."""
    d = request.get_json(force=True, silent=True) or {}
    fecha = d.get("fecha")
    if not fecha:
        return jsonify(ok=False, error="Elegí una fecha"), 400
    t = q1("SELECT * FROM turnos WHERE id=?", (tid,))
    if not t:
        return jsonify(ok=False, error="Turno inexistente"), 404
    p = q1("SELECT * FROM pacientes WHERE id=?", (t["paciente_id"],))
    horarios = parse_horarios(p["horarios"]) if p else {}
    try:
        wd = date.fromisoformat(fecha).weekday()
    except Exception:
        return jsonify(ok=False, error="Fecha inválida"), 400
    hora = d.get("hora") or horarios.get(str(wd)) or t["hora"] or ""
    run("UPDATE turnos SET estado='ausente', box_id=NULL WHERE id=?", (tid,))
    nid = run(
        """INSERT INTO turnos (paciente_id, fecha, hora, estado, duracion_min, sede_id)
           VALUES (?,?,?, 'agendado', ?, ?)""",
        (t["paciente_id"], fecha, hora, t["duracion_min"] or DURACION_DEFAULT,
         t["sede_id"]),
    )
    return jsonify(ok=True, id=nid, fecha=fecha, hora=hora)


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
    box = q1("SELECT sede_id FROM boxes WHERE id=?", (box_id,))
    box_sede = box["sede_id"] if box else sede_actual_id()
    if t:
        tid = t["id"]
    else:
        tid = run(
            """INSERT INTO turnos (paciente_id, fecha, hora, estado, duracion_min, sede_id)
               VALUES (?,?,?, 'agendado', ?, ?)""",
            (pid, hoy, datetime.now().strftime("%H:%M"), dur, box_sede),
        )
    run(
        """UPDATE turnos SET estado='en_curso', box_id=?, inicio=?,
           duracion_min=?, fin=NULL, sede_id=? WHERE id=?""",
        (box_id, datetime.now().isoformat(), dur, box_sede, tid),
    )
    # Llegada directa al box: cuenta la sesión si el turno no la contó todavía.
    if not t or t["estado"] not in ("presente", "en_curso", "terminado"):
        _descontar_sesion(pid)
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
def api_terminar(tid):
    t = q1("""SELECT t.*, p.nombre, p.apellido, b.nombre AS box
              FROM turnos t JOIN pacientes p ON p.id=t.paciente_id
              LEFT JOIN boxes b ON b.id=t.box_id WHERE t.id=?""", (tid,))
    if not t:
        return jsonify(ok=False, error="Turno inexistente"), 404
    # La sesión ya se contó al marcar "vino" (✓); acá sólo se libera el box.
    run("UPDATE turnos SET estado='terminado', fin=?, box_id=NULL WHERE id=?",
        (datetime.now().isoformat(), tid))
    box = t["box"] or ""
    registrar_evento("fin", t["paciente_id"],
                     f"{t['nombre']} {t['apellido']} terminó" + (f" en {box}" if box else ""))
    p = q1("SELECT * FROM pacientes WHERE id=?", (t["paciente_id"],))
    quedan = (p["sesiones_totales"] or 0) - (p["sesiones_usadas"] or 0)
    return jsonify(ok=True, paciente=f"{t['nombre']} {t['apellido']}",
                   paciente_id=t["paciente_id"], turno_id=tid, box=box,
                   sesiones_quedan=quedan)


@app.route("/api/turno/<int:tid>/agregar_tiempo", methods=["POST"])
def api_agregar_tiempo(tid):
    """Suma minutos a un turno en curso (corta la alarma y extiende el timer)."""
    d = request.get_json(force=True, silent=True) or {}
    mins = int(d.get("minutos") or 10)
    t = q1("SELECT * FROM turnos WHERE id=?", (tid,))
    if not t:
        return jsonify(ok=False, error="Turno inexistente"), 404
    run("UPDATE turnos SET duracion_min = COALESCE(duracion_min, 0) + ? WHERE id=?",
        (mins, tid))
    return jsonify(ok=True, minutos=mins)


@app.route("/api/turno/<int:tid>/ausente", methods=["POST"])
def api_ausente(tid):
    run("UPDATE turnos SET estado='ausente', box_id=NULL WHERE id=?", (tid,))
    return jsonify(ok=True)


@app.route("/api/turno/<int:tid>/perdido", methods=["POST"])
def api_perdido(tid):
    run("UPDATE turnos SET estado='perdido', box_id=NULL WHERE id=?", (tid,))
    return jsonify(ok=True)


@app.route("/api/turno/<int:tid>/deshacer_ausente", methods=["POST"])
def api_deshacer_ausente(tid):
    """Cancela el 'no vino' (vuelve a agendado) y marca sin_auto=1 para que la
    tolerancia no lo vuelva a marcar 'no vino' solo."""
    t = q1("SELECT * FROM turnos WHERE id=?", (tid,))
    if not t:
        return jsonify(ok=False, error="Turno inexistente"), 404
    run("UPDATE turnos SET estado='agendado', box_id=NULL, sin_auto=1 WHERE id=?", (tid,))
    return jsonify(ok=True)


@app.route("/api/turno/<int:tid>/deshacer_vino", methods=["POST"])
def api_deshacer_vino(tid):
    """Deshace un 'vino' marcado por error: vuelve a agendado y devuelve la sesión."""
    t = q1("SELECT * FROM turnos WHERE id=?", (tid,))
    if not t:
        return jsonify(ok=False, error="Turno inexistente"), 404
    if t["estado"] == "presente":
        run("UPDATE turnos SET estado='agendado' WHERE id=?", (tid,))
        run("UPDATE pacientes SET sesiones_usadas = MAX(0, sesiones_usadas - 1) WHERE id=?",
            (t["paciente_id"],))
    return jsonify(ok=True)


def _proximo_disponible(t):
    """Calcula (fecha, hora, paciente_row) del próximo turno disponible para 't'
    después de la última sesión agendada del paciente, respetando sus días."""
    p = q1("SELECT * FROM pacientes WHERE id=?", (t["paciente_id"],))
    dias = str_to_dias(p["dias"]) if p else []
    horarios = parse_horarios(p["horarios"]) if p else {}
    ult = q1(
        """SELECT MAX(fecha) f FROM turnos
           WHERE paciente_id=? AND estado='agendado' AND id<>?""",
        (t["paciente_id"], t["id"]),
    )
    base = ult["f"] if ult and ult["f"] else t["fecha"]
    cur = date.fromisoformat(base) + timedelta(days=1)
    if not dias:
        dias = [date.fromisoformat(t["fecha"]).weekday()]
    for _ in range(400):
        # Próximo día que viene el paciente y que NO sea feriado.
        if cur.weekday() in dias and not _es_feriado(cur.isoformat()):
            break
        cur += timedelta(days=1)
    hora = horarios.get(str(cur.weekday())) or t["hora"] or ""
    return cur.isoformat(), hora, p


@app.route("/api/turno/<int:tid>/reprogramar_preview")
def api_reprogramar_preview(tid):
    """Muestra a qué fecha/hora se movería y los días/horarios del paciente."""
    t = q1("SELECT * FROM turnos WHERE id=?", (tid,))
    if not t:
        return jsonify(ok=False, error="Turno inexistente"), 404
    fecha, hora, p = _proximo_disponible(t)
    return jsonify(ok=True, fecha=fecha, hora=hora,
                   dias=(p["dias"] if p else "") or "",
                   horarios=parse_horarios(p["horarios"]) if p else {})


@app.route("/api/turno/<int:tid>/reprogramar", methods=["POST"])
def api_reprogramar(tid):
    """No asistió / cancela: mueve el turno a la próxima fecha disponible."""
    t = q1("SELECT * FROM turnos WHERE id=?", (tid,))
    if not t:
        return jsonify(ok=False, error="Turno inexistente"), 404
    fecha, hora, p = _proximo_disponible(t)
    run("UPDATE turnos SET estado='ausente', box_id=NULL WHERE id=?", (tid,))
    nid = run(
        """INSERT INTO turnos (paciente_id, fecha, hora, estado, duracion_min, sede_id)
           VALUES (?,?,?, 'agendado', ?, ?)""",
        (t["paciente_id"], fecha, hora, t["duracion_min"] or DURACION_DEFAULT,
         t["sede_id"]),
    )
    return jsonify(ok=True, id=nid, fecha=fecha, hora=hora)


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
    # Feriado: no se dan turnos ese día.
    if _es_feriado(fecha):
        return jsonify(ok=False, feriado=True,
                       error="Ese día es feriado — no se dan turnos."), 409
    sede = _sede_de_request(data)
    # Tope por horario: si ese horario ya está lleno, no deja dar más turnos.
    tope = tope_de_sede(sede)
    if hora and tope and _slot_ocupado(sede, fecha, hora) >= tope:
        return jsonify(ok=False, lleno=True,
                       error=f"Horario lleno: {hora} ya tiene {tope} turno(s) "
                             f"en {sede_nombre(sede)} (el tope)."), 409
    tid = run(
        """INSERT INTO turnos (paciente_id, fecha, hora, estado, duracion_min, sede_id)
           VALUES (?,?,?, 'agendado', ?, ?)""",
        (pid, fecha, hora, dur, sede),
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
    sede = _sede_de_request(d)
    tope = tope_de_sede(sede)

    # Guardar los días/horarios del paciente (su plan semanal).
    run("UPDATE pacientes SET dias=?, horarios=? WHERE id=?",
        (dias_to_str(dias), json.dumps(horarios), pid))

    # 1) Calcular las fechas destino (salteando feriados, que son días cerrados).
    fechas = []
    guard = 0
    while len(fechas) < cantidad and guard < 800:
        wd = cur.weekday()
        if wd in dias and not _es_feriado(cur.isoformat()):
            hora = horarios.get(str(wd)) or horarios.get(wd) or hora_default
            fechas.append((cur.isoformat(), hora))
        cur += timedelta(days=1)
        guard += 1

    # 2) Si AUNQUE SEA UNO está lleno, no se asigna nada y se avisa cuáles.
    if tope:
        llenos = [f + (" " + h if h else "")
                  for f, h in fechas if h and _slot_ocupado(sede, f, h) >= tope]
        if llenos:
            muestra = ", ".join(llenos[:6]) + ("…" if len(llenos) > 6 else "")
            return jsonify(ok=False, lleno=True,
                           error="No se asignó ningún turno porque estos horarios "
                                 "están llenos: " + muestra), 409

    # 3) Crear todos.
    for f, h in fechas:
        run("""INSERT INTO turnos (paciente_id, fecha, hora, estado, duracion_min, sede_id)
               VALUES (?,?,?, 'agendado', ?, ?)""", (pid, f, h, dur, sede))
    return jsonify(ok=True, creados=len(fechas), saltados=0)


@app.route("/api/plan_preview", methods=["POST"])
def api_plan_preview():
    """Vista previa: qué días saldrían y cómo está cada horario (para que el
    kine vea antes de confirmar cómo están los turnos que eligió el paciente)."""
    d = request.get_json(force=True, silent=True) or {}
    dias = sorted(set(int(x) for x in (d.get("dias") or [])))
    horarios = d.get("horarios") or {}
    hora_default = d.get("hora") or ""
    cantidad = int(d.get("cantidad") or 0)
    if not dias or cantidad <= 0:
        return jsonify(items=[])
    sede = _sede_de_request(d)
    tope = tope_de_sede(sede)
    cur = date.fromisoformat(d.get("desde") or date.today().isoformat())
    items = []
    guard = 0
    while len(items) < cantidad and guard < 800:
        wd = cur.weekday()
        if wd in dias:
            f = cur.isoformat()
            if _es_feriado(f):
                items.append({"fecha": f, "hora": "", "feriado": True})
            else:
                h = horarios.get(str(wd)) or horarios.get(wd) or hora_default
                oc = _slot_ocupado(sede, f, h) if h else 0
                libres = (max(0, tope - oc) if tope else 99)
                items.append({"fecha": f, "hora": h, "ocupados": oc, "tope": tope,
                              "libres": libres, "lleno": bool(tope and libres <= 0)})
        cur += timedelta(days=1)
        guard += 1
    return jsonify(items=items)


@app.route("/api/plan_propuesta", methods=["POST"])
def api_plan_propuesta():
    """Propone el plan completo: una sesión por cada día elegido, a la hora
    pedida. Marca los horarios llenos (con una alternativa cercana) y los
    feriados (que se saltan y se reprograman al próximo día válido)."""
    d = request.get_json(force=True, silent=True) or {}
    pid = d.get("paciente_id")
    dias = sorted(set(int(x) for x in (d.get("dias") or [])))
    hora = (d.get("hora") or "").strip()          # hora por defecto (compat)
    horarios = d.get("horarios") or {}            # {"0":"10:00","3":"15:00",...}
    # estrategia: "hora" (yo elijo la hora), "mejor_hora" (la app pone la hora con
    # menos gente en los días elegidos), "recomendado" (la app elige días y horas).
    estrategia = d.get("estrategia") or "hora"
    sede = _sede_de_request(d)
    tope = tope_de_sede(sede) or 0

    def hora_de(wd):
        return (horarios.get(str(wd)) or horarios.get(wd) or hora or "").strip()

    if not pid:
        return jsonify(ok=False, error="Falta el paciente"), 400
    if estrategia != "recomendado" and not dias:
        return jsonify(ok=False, error="Elegí al menos un día de la semana"), 400
    if estrategia == "hora" and not any(hora_de(wd) for wd in dias):
        return jsonify(ok=False, error="Elegí el horario de cada día"), 400
    p = q1("SELECT * FROM pacientes WHERE id=?", (pid,))
    if not p:
        return jsonify(ok=False, error="Paciente inexistente"), 404

    modo = d.get("modo") or "nuevo"
    quedan = (p["sesiones_totales"] or 0) - (p["sesiones_usadas"] or 0)
    desde_txt = d.get("desde") or date.today().isoformat()
    if modo == "extender":
        # Las que faltan por agendar = las que quedan menos las ya agendadas a futuro.
        fut = q1("""SELECT COUNT(*) c FROM turnos WHERE paciente_id=? AND fecha>=?
                    AND estado IN ('agendado','en_espera','presente')""",
                 (pid, date.today().isoformat()))["c"]
        cantidad = max(0, quedan - fut)
    elif modo == "reprogramar":
        # Cambiar días/horarios a mitad del tratamiento: se mueven los turnos que
        # todavía no pasaron. Las sesiones ya hechas no se tocan.
        cantidad = q1("""SELECT COUNT(*) c FROM turnos WHERE paciente_id=? AND fecha>=?
                         AND sede_id=? AND estado IN ('agendado','en_espera','presente')""",
                      (pid, desde_txt, sede))["c"]
        if cantidad <= 0:
            return jsonify(ok=False,
                           error="Este paciente no tiene turnos pendientes para mover en esta sede."), 400
    else:
        cantidad = int(d.get("cantidad") or quedan or 0)
    if cantidad <= 0:
        return jsonify(ok=False,
                       error="No hay sesiones para agendar. Revisá las sesiones del paciente."), 400

    cur = date.fromisoformat(d.get("desde") or date.today().isoformat())
    # En "recomendado" no filtro por días: uso todos los que el centro abre.
    filtra_dias = estrategia != "recomendado"
    items = []
    puestos = 0
    guard = 0
    while puestos < cantidad and guard < 900:
        guard += 1
        wd = cur.weekday()
        f = cur.isoformat()
        cur += timedelta(days=1)
        if filtra_dias and wd not in dias:
            continue
        if _es_feriado(f):
            if filtra_dias:   # sólo aviso el feriado si el paciente pidió ese día
                items.append({"fecha": f, "dia": DIAS_FULL[wd], "hora": "",
                              "estado": "feriado", "alternativa": None, "libres": 0})
            continue
        slots = _slots_dia(sede, f)
        if not slots:
            continue   # el centro no abre ese día
        if estrategia == "hora":
            h = hora_de(wd)
            oc = _slot_ocupado(sede, f, h,
                               excluir_paciente=(pid if modo == "reprogramar" else None))
            libres = (max(0, tope - oc) if tope else 99)
            if tope and libres <= 0:
                items.append({"fecha": f, "dia": DIAS_FULL[wd], "hora": h,
                              "estado": "lleno",
                              "alternativa": _alternativa_hora(sede, f, h),
                              "libres": 0})
            else:
                items.append({"fecha": f, "dia": DIAS_FULL[wd], "hora": h,
                              "estado": "ok", "alternativa": None, "libres": libres})
            puestos += 1
        else:
            # "mejor_hora" y "recomendado": la app elige el horario con menos gente.
            best = _mejor_slot(sede, f)
            if not best or (tope and best[1] <= 0):
                if filtra_dias:   # día lleno (sólo importa si lo pidió)
                    items.append({"fecha": f, "dia": DIAS_FULL[wd], "hora": "",
                                  "estado": "lleno", "alternativa": None, "libres": 0})
                    puestos += 1
                continue
            items.append({"fecha": f, "dia": DIAS_FULL[wd], "hora": best[0],
                          "estado": "ok", "alternativa": None, "libres": best[1]})
            puestos += 1

    resumen = {"ok": sum(1 for i in items if i["estado"] == "ok"),
               "llenos": sum(1 for i in items if i["estado"] == "lleno"),
               "feriados": sum(1 for i in items if i["estado"] == "feriado"),
               "cantidad": cantidad}
    return jsonify(ok=True, items=items, resumen=resumen,
                   paciente=nombre_completo(p), quedan=quedan,
                   cantidad=cantidad, modo=modo)


@app.route("/api/horas_dia")
def api_horas_dia():
    """Opciones de horario (con color) del próximo día de esa semana, para elegir
    en 'mejores horas'. Muestra los verdes y, si hay 6 o menos, también amarillos."""
    sede = _sede_de_args()
    tope = tope_de_sede(sede) or 0
    try:
        weekday = int(request.args.get("weekday"))
    except (TypeError, ValueError):
        return jsonify(ok=False, error="Falta el día"), 400
    desde = request.args.get("desde") or date.today().isoformat()
    fecha = _proxima_ocurrencia(weekday, desde)
    if not fecha:
        return jsonify(ok=True, fecha=None, abierto=False, opciones=[])
    slots = _slots_dia(sede, fecha)   # (hora, libres, ocupados)
    if not slots:
        return jsonify(ok=True, fecha=fecha, abierto=False, opciones=[])
    if request.args.get("todos") == "1":
        # Todos los horarios (en punto y y media), diciendo cómo está cada uno.
        ops = [{"hora": h, "libres": lib, "color": _color_libres(lib, tope)}
               for h, lib, oc in slots]
    else:
        verdes = [{"hora": h, "libres": lib, "color": "verde"}
                  for h, lib, oc in slots if (not tope or lib >= 2)]
        amarillos = [{"hora": h, "libres": lib, "color": "amar"}
                     for h, lib, oc in slots if tope and lib == 1]
        ops = list(verdes)
        if len(verdes) <= 6:
            ops += amarillos
    ops.sort(key=lambda x: _hm_a_min(x["hora"], 0))
    return jsonify(ok=True, fecha=fecha, abierto=True, opciones=ops)


@app.route("/api/recomendados")
def api_recomendados():
    """Hasta 7 slots recomendados (uno por día hábil que abre el local), con el
    horario con menos gente de cada día, para ofrecerle al paciente."""
    sede = _sede_de_args()
    tope = tope_de_sede(sede) or 0
    desde = request.args.get("desde") or date.today().isoformat()
    cur = date.fromisoformat(desde)
    vistos = set()
    out = []
    guard = 0
    while len(out) < 7 and len(vistos) < 7 and guard < 40:
        guard += 1
        wd = cur.weekday()
        f = cur.isoformat()
        cur += timedelta(days=1)
        if wd in vistos or _es_feriado(f):
            continue
        slots = _slots_dia(sede, f)
        vistos.add(wd)
        if not slots:
            continue   # el centro no abre ese día
        # Sólo horarios 100% libres (nadie) o en verde. Nada de amarillos.
        # s = (hora, libres, ocupados); van del más vacío al menos vacío.
        cand = [s for s in slots if s[2] == 0 or (tope and s[1] >= 2)]
        if not cand:
            continue   # ese día no tiene horarios recomendables
        cand.sort(key=lambda x: (x[2], _hm_a_min(x[0], 0)))
        opciones = [{"hora": h, "libres": lib, "color": _color_libres(lib, tope)}
                    for h, lib, oc in cand]
        out.append({"weekday": wd, "dia": DIAS_FULL[wd], "fecha": f,
                    "hora": opciones[0]["hora"], "libres": opciones[0]["libres"],
                    "color": opciones[0]["color"], "opciones": opciones})
    out.sort(key=lambda x: x["weekday"])
    return jsonify(items=out)


@app.route("/api/plan_confirmar", methods=["POST"])
def api_plan_confirmar():
    """Crea los turnos del plan ya revisado (lista de {fecha, hora}). Saltea
    feriados y filas sin hora, y avisa si algún horario quedó lleno."""
    d = request.get_json(force=True, silent=True) or {}
    pid = d.get("paciente_id")
    rows = d.get("rows") or []
    dur = int(d.get("duracion") or DURACION_DEFAULT)
    sede = _sede_de_request(d)
    tope = tope_de_sede(sede) or 0
    if not pid:
        return jsonify(ok=False, error="Falta el paciente"), 400
    if not rows:
        return jsonify(ok=False, error="No hay turnos para crear"), 400

    # Reprogramar: primero se sacan los turnos pendientes que se están moviendo
    # (así además liberan su lugar y no cuentan para el tope). Las sesiones ya
    # hechas o pasadas NO se tocan.
    movidos = 0
    reemplazar = (d.get("reemplazar_desde") or "").strip()
    if reemplazar:
        movidos = q1("""SELECT COUNT(*) c FROM turnos WHERE paciente_id=? AND fecha>=?
                        AND sede_id=? AND estado IN ('agendado','en_espera','presente')""",
                     (pid, reemplazar, sede))["c"]
        run("""DELETE FROM turnos WHERE paciente_id=? AND fecha>=? AND sede_id=?
               AND estado IN ('agendado','en_espera','presente')""",
            (pid, reemplazar, sede))

    creados, saltados, llenos = 0, 0, []
    for r in rows:
        f = (r.get("fecha") or "").strip()
        h = (r.get("hora") or "").strip()
        if not f or not h or _es_feriado(f):
            saltados += 1
            continue
        if tope and _slot_ocupado(sede, f, h) >= tope:
            llenos.append(f + " " + h)
            continue
        run("""INSERT INTO turnos (paciente_id, fecha, hora, estado, duracion_min, sede_id)
               VALUES (?,?,?, 'agendado', ?, ?)""", (pid, f, h, dur, sede))
        creados += 1

    # Guardar la preferencia de días/horarios del paciente (su plan semanal).
    dias, horarios = [], {}
    for r in rows:
        f, h = (r.get("fecha") or ""), (r.get("hora") or "")
        if f and h:
            try:
                wd = date.fromisoformat(f).weekday()
                dias.append(wd)
                horarios[str(wd)] = h
            except Exception:
                pass
    if dias:
        run("UPDATE pacientes SET dias=?, horarios=? WHERE id=?",
            (dias_to_str(sorted(set(dias))), json.dumps(horarios), pid))

    if llenos:
        muestra = ", ".join(llenos[:6]) + ("…" if len(llenos) > 6 else "")
        return jsonify(ok=True, creados=creados, saltados=saltados,
                       llenos=llenos, movidos=movidos,
                       aviso=f"{creados} turno(s) creados. Estos quedaron llenos y "
                             f"no se agendaron: {muestra}")
    return jsonify(ok=True, creados=creados, saltados=saltados, llenos=[], movidos=movidos)


@app.route("/api/turno/<int:tid>/borrar", methods=["POST"])
def api_borrar_turno(tid):
    run("DELETE FROM turnos WHERE id=?", (tid,))
    # El token (si tenía) se conserva, pero ya no queda atado a ese turno.
    run("UPDATE tokens SET turno_id=NULL WHERE turno_id=?", (tid,))
    return jsonify(ok=True)


@app.route("/api/turno/<int:tid>/editar", methods=["POST"])
def api_editar_turno(tid):
    """Mover/editar un turno (fecha, hora, duración) desde la agenda."""
    d = request.get_json(force=True, silent=True) or {}
    t = q1("SELECT * FROM turnos WHERE id=?", (tid,))
    if not t:
        return jsonify(ok=False, error="Turno inexistente"), 404
    fecha = d.get("fecha") or t["fecha"]
    hora = d.get("hora") if d.get("hora") is not None else t["hora"]
    dur = int(d.get("duracion") or t["duracion_min"] or DURACION_DEFAULT)
    # Al mover a otro horario, respetar el tope (sin contarse a sí mismo).
    sede = t["sede_id"] or sede_actual_id()
    tope = tope_de_sede(sede)
    if hora and tope and (fecha != t["fecha"] or hora != t["hora"]):
        if _slot_ocupado(sede, fecha, hora, excluir_turno=tid) >= tope:
            return jsonify(ok=False, lleno=True,
                           error=f"Horario lleno: {hora} ya tiene {tope} turno(s) (el tope)."), 409
    run("UPDATE turnos SET fecha=?, hora=?, duracion_min=? WHERE id=?",
        (fecha, hora, dur, tid))
    return jsonify(ok=True)


@app.route("/api/huecos")
def api_huecos():
    """Horarios libres de un día según la cantidad de boxes."""
    fecha = request.args.get("fecha") or date.today().isoformat()
    dur = int(request.args.get("duracion") or DURACION_DEFAULT)
    sede = _sede_de_args()
    n_boxes = q1("SELECT COUNT(*) c FROM boxes WHERE activo=1 AND sede_id=?",
                 (sede,))["c"] or 1
    rows = q(
        """SELECT hora, duracion_min FROM turnos
           WHERE fecha=? AND sede_id=? AND estado NOT IN ('ausente','perdido')""",
        (fecha, sede),
    )
    ocup = []
    for r in rows:
        if not r["hora"]:
            continue
        try:
            hh, mm = map(int, r["hora"].split(":"))
        except Exception:
            continue
        ini = hh * 60 + mm
        ocup.append((ini, ini + (r["duracion_min"] or DURACION_DEFAULT)))

    # Horario del centro (configurable).
    cfg = get_config()

    def tomin(s, defecto):
        try:
            hh, mm = map(int, str(s).split(":"))
            return hh * 60 + mm
        except Exception:
            return defecto
    try:
        wd = date.fromisoformat(fecha).weekday()
    except Exception:
        wd = 0

    # Horario por día (centro_horarios JSON: {"0":{"a":"09:00","c":"13:00"}, ...})
    hor = parse_horarios(cfg.get("centro_horarios", ""))
    apertura, cierre, abierto = "08:00", "20:00", True
    if hor:
        dd = hor.get(str(wd))
        if dd:
            apertura, cierre = dd.get("a", "08:00"), dd.get("c", "20:00")
        else:
            abierto = False
    else:  # compatibilidad con la config vieja (un solo horario)
        apertura = cfg.get("centro_apertura", "08:00")
        cierre = cfg.get("centro_cierre", "20:00")
        dias_c = (cfg.get("centro_dias", "") or "").split(",") if cfg.get("centro_dias") else []
        abierto = (not dias_c) or (str(wd) in dias_c)

    m0 = tomin(apertura, 8 * 60)
    m1 = tomin(cierre, 20 * 60)
    slots = []
    for m in range(m0, m1, 30):
        fin = m + dur
        solap = sum(1 for (a, b) in ocup if a < fin and m < b)
        slots.append({"hora": f"{m // 60:02d}:{m % 60:02d}",
                      "libres": max(0, n_boxes - solap)})
    return jsonify({"boxes": n_boxes, "slots": slots, "abierto": abierto,
                    "apertura": apertura, "cierre": cierre})


@app.route("/api/horarios_libres")
def api_horarios_libres():
    """Para ofrecerle horarios al paciente: por cada franja del día, cuántos
    lugares quedan según el TOPE de la sede. Verde/amarillo/rojo en el front."""
    fecha = request.args.get("fecha") or date.today().isoformat()
    sede = _sede_de_args()
    tope = tope_de_sede(sede) or 0
    cfg = get_config()
    try:
        wd = date.fromisoformat(fecha).weekday()
    except Exception:
        wd = 0
    hor = parse_horarios(cfg.get("centro_horarios", ""))
    apertura, cierre, abierto = "08:00", "20:00", True
    if hor:
        dd = hor.get(str(wd))
        if dd:
            apertura, cierre = dd.get("a", "08:00"), dd.get("c", "20:00")
        else:
            abierto = False

    def tomin(s, dv):
        try:
            hh, mm = map(int, str(s).split(":"))
            return hh * 60 + mm
        except Exception:
            return dv

    counts = {}
    for r in q("""SELECT hora, COUNT(*) c FROM turnos
                  WHERE fecha=? AND sede_id=? AND estado NOT IN ('ausente','perdido')
                    AND hora IS NOT NULL AND hora<>'' GROUP BY hora""", (fecha, sede)):
        counts[r["hora"]] = r["c"]
    feriado = _es_feriado(fecha)
    m0, m1 = tomin(apertura, 8 * 60), tomin(cierre, 20 * 60)
    slots = []
    for m in range(m0, m1, 30):
        h = f"{m // 60:02d}:{m % 60:02d}"
        c = counts.get(h, 0)
        libres = (max(0, tope - c) if tope else 99)
        slots.append({"hora": h, "libres": libres, "ocupados": c})
    return jsonify({"slots": slots, "tope": tope,
                    "abierto": abierto and not feriado, "feriado": feriado})


@app.route("/api/proximos_libres")
def api_proximos_libres():
    """Lista los próximos turnos libres (para ofrecerle al paciente). Se puede
    filtrar por días de la semana y por hora. Devuelve fecha, día, hora, libres."""
    sede = _sede_de_args()
    tope = tope_de_sede(sede) or 0
    limite = min(30, int(request.args.get("limite") or 12))
    hora_f = (request.args.get("hora") or "").strip()
    dias_f = request.args.get("dias") or ""
    dias_set = set(int(x) for x in dias_f.split(",") if x.strip().isdigit()) if dias_f else set()
    cfg = get_config()
    hor = parse_horarios(cfg.get("centro_horarios", ""))

    def rango(wd):
        if hor:
            dd = hor.get(str(wd))
            if not dd:
                return None
            return dd.get("a", "08:00"), dd.get("c", "20:00")
        return "08:00", "20:00"

    def tomin(s, dv):
        try:
            hh, mm = map(int, str(s).split(":"))
            return hh * 60 + mm
        except Exception:
            return dv

    out = []
    cur = date.today()
    guard = 0
    while len(out) < limite and guard < 120:
        guard += 1
        cur += timedelta(days=1)
        wd = cur.weekday()
        if dias_set and wd not in dias_set:
            continue
        if _es_feriado(cur.isoformat()):
            continue
        rg = rango(wd)
        if not rg:
            continue
        m0, m1 = tomin(rg[0], 480), tomin(rg[1], 1200)
        # conteo por hora ese día
        counts = {}
        for r in q("""SELECT hora, COUNT(*) c FROM turnos WHERE fecha=? AND sede_id=?
                      AND estado NOT IN ('ausente','perdido') AND hora<>'' GROUP BY hora""",
                   (cur.isoformat(), sede)):
            counts[r["hora"]] = r["c"]
        horas = [hora_f] if hora_f else [f"{m//60:02d}:{m%60:02d}" for m in range(m0, m1, 30)]
        for h in horas:
            hm = tomin(h, -1)
            if hm < m0 or hm >= m1:
                continue
            libres = (tope - counts.get(h, 0)) if tope else 99
            if libres > 0:
                out.append({"fecha": cur.isoformat(),
                            "dia": DIAS_FULL[wd], "hora": h, "libres": libres})
                if len(out) >= limite:
                    break
    return jsonify(items=out)


# --------------------------------------------------------------------------
# API — pacientes
# --------------------------------------------------------------------------
@app.route("/api/pacientes")
def api_pacientes():
    term = (request.args.get("q") or "").strip()
    sede = (request.args.get("sede") or "").strip()   # "" o "todas" = ambas
    try:
        sid = int(sede)
    except Exception:
        sid = None

    where, params = [], []
    if term:
        like = f"%{_sin_acentos(term)}%"   # busca sin acentos ni mayúsculas
        where.append("(sinacentos(nombre) LIKE ? OR sinacentos(apellido) LIKE ? "
                     "OR sinacentos(nombre || ' ' || apellido) LIKE ? "
                     "OR sinacentos(COALESCE(dni,'')) LIKE ?)")
        params += [like, like, like, like]

    sql = "SELECT * FROM pacientes"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY apellido COLLATE NOCASE"
    filas = q(sql, tuple(params))

    mem = _sedes_de_pacientes()
    out = []
    for p in filas:
        if sid is not None and sid not in mem.get(p["id"], []):
            continue
        d = paciente_dict(p)
        d["sedes"] = mem.get(p["id"], [])
        out.append(d)
        if term and len(out) >= 50:
            break
    return jsonify(out)


@app.route("/api/paciente/<int:pid>/resumen")
def api_paciente_resumen(pid):
    """Datos clave del paciente para el panel rápido de recepción."""
    p = q1("SELECT * FROM pacientes WHERE id=?", (pid,))
    if not p:
        return jsonify(ok=False, error="No existe"), 404
    exs = q("SELECT * FROM ejercicios WHERE paciente_id=? ORDER BY id DESC LIMIT 6", (pid,))
    evo = q("SELECT * FROM evoluciones WHERE paciente_id=? ORDER BY fecha DESC, id DESC LIMIT 3", (pid,))
    prox = q1(
        """SELECT fecha, hora FROM turnos
           WHERE paciente_id=? AND fecha >= ? AND estado IN ('agendado','en_espera','presente')
           ORDER BY fecha, hora LIMIT 1""",
        (pid, date.today().isoformat()),
    )
    ult = q1(
        """SELECT MAX(fecha) AS f FROM turnos
           WHERE paciente_id=? AND estado IN ('agendado','en_espera','presente')""",
        (pid,),
    )
    d = paciente_dict(p)
    d["ultimo_turno"] = ult["f"] if ult and ult["f"] else None
    d["ejercicios"] = [
        {"nombre": e["nombre"], "categoria": e["categoria"] or "",
         "series": e["series"] or "", "reps": e["reps"] or "",
         "peso": (e["peso"] if "peso" in e.keys() else "") or ""}
        for e in exs
    ]
    d["evoluciones"] = [{"fecha": e["fecha"] or "", "texto": e["texto"] or ""} for e in evo]
    d["proximo_turno"] = ({"fecha": prox["fecha"], "hora": prox["hora"] or ""} if prox else None)
    return jsonify(ok=True, **d)


def _nombre_prolijo(txt):
    """'juan perez' o 'JUAN PEREZ' -> 'Juan Perez'. Si ya viene mezclado (McDonald), se respeta."""
    txt = " ".join((txt or "").split())
    if txt and (txt.islower() or txt.isupper()):
        return " ".join(w[:1].upper() + w[1:].lower() for w in txt.split(" "))
    return txt


def _obras_sociales():
    return [r["nombre"] for r in q("SELECT nombre FROM obras_sociales ORDER BY nombre COLLATE NOCASE")]


def _obra_social_canonica(txt, agregar=True):
    """Devuelve la obra social como figura en la lista ('osde' -> 'OSDE').
    Si no está, la agrega a la lista para que aparezca la próxima vez."""
    txt = " ".join((txt or "").split())
    if not txt:
        return ""
    clave = _sin_acentos(txt)
    for r in q("SELECT nombre FROM obras_sociales"):
        if _sin_acentos(r["nombre"]) == clave:
            return r["nombre"]
    if agregar:
        run("INSERT INTO obras_sociales (nombre, creado) VALUES (?,?)",
            (txt, date.today().isoformat()))
    return txt


def _sedes_de_pacientes():
    """Sede(s) de cada paciente para el filtro de la lista.

    Se mira dónde se atiende ahora: turnos reales (no los de "Simular agenda")
    de los últimos 45 días o próximos. Si no tiene, la sede de su último turno;
    si nunca tuvo, la sede donde se lo cargó. Sin ningún dato → aparece en todas.
    """
    desde = (date.today() - timedelta(days=45)).isoformat()
    actual, ultimo = {}, {}
    for r in q("""SELECT paciente_id, sede_id, fecha FROM turnos
                  WHERE paciente_id IS NOT NULL AND sede_id IS NOT NULL
                    AND COALESCE(sim,0)=0 ORDER BY fecha""", ()):
        pid = r["paciente_id"]
        if (r["fecha"] or "") >= desde:
            actual.setdefault(pid, set()).add(r["sede_id"])
        ultimo[pid] = r["sede_id"]
    todas = [x["id"] for x in sedes_list()]
    out = {}
    for p in q("SELECT id, sede_id FROM pacientes", ()):
        pid = p["id"]
        if pid in actual:
            out[pid] = sorted(actual[pid])
        elif pid in ultimo:
            out[pid] = [ultimo[pid]]
        elif p["sede_id"]:
            out[pid] = [p["sede_id"]]
        else:
            out[pid] = todas
    return out


@app.route("/api/paciente", methods=["POST"])
def api_nuevo_paciente():
    d = request.get_json(force=True, silent=True) or {}
    nombre = _nombre_prolijo(d.get("nombre"))
    apellido = _nombre_prolijo(d.get("apellido"))
    if not nombre or not apellido:
        return jsonify(ok=False, error="Nombre y apellido son obligatorios"), 400
    pid = run(
        """INSERT INTO pacientes
           (nombre, apellido, dni, telefono, obra_social, diagnostico,
            sesiones_totales, sesiones_usadas, dias, notas, creado, sede_id, nro_afiliado)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            nombre, apellido, (d.get("dni") or "").strip(),
            (d.get("telefono") or "").strip(), _obra_social_canonica(d.get("obra_social")),
            (d.get("diagnostico") or "").strip(),
            int(d.get("sesiones_totales") or 0), int(d.get("sesiones_usadas") or 0),
            (d.get("dias") or "").strip(), (d.get("notas") or "").strip(),
            date.today().isoformat(), _sede_de_request(d), (d.get("nro_afiliado") or "").strip(),
        ),
    )
    return jsonify(ok=True, id=pid)


@app.route("/api/paciente/<int:pid>", methods=["POST"])
def api_editar_paciente(pid):
    d = request.get_json(force=True, silent=True) or {}
    # Si no le cambiaron la obra social, no se vuelve a sumar a la lista
    # (puede ser una que quitaron a propósito en Configuración).
    antes = q1("SELECT obra_social FROM pacientes WHERE id=?", (pid,))
    cambio = _sin_acentos(" ".join((d.get("obra_social") or "").split())) !=         _sin_acentos(" ".join(((antes["obra_social"] if antes else "") or "").split()))
    run(
        """UPDATE pacientes SET
             nombre=?, apellido=?, dni=?, telefono=?, obra_social=?, diagnostico=?,
             sesiones_totales=?, sesiones_usadas=?, dias=?, notas=?
           WHERE id=?""",
        (
            _nombre_prolijo(d.get("nombre")), _nombre_prolijo(d.get("apellido")),
            (d.get("dni") or "").strip(), (d.get("telefono") or "").strip(),
            _obra_social_canonica(d.get("obra_social"), agregar=cambio), (d.get("diagnostico") or "").strip(),
            int(d.get("sesiones_totales") or 0), int(d.get("sesiones_usadas") or 0),
            (d.get("dias") or "").strip(), (d.get("notas") or "").strip(), pid,
        ),
    )
    # El nº de afiliado se toca sólo si viene (así no lo borran pantallas que no lo muestran).
    if "nro_afiliado" in d:
        run("UPDATE pacientes SET nro_afiliado=? WHERE id=?", ((d.get("nro_afiliado") or "").strip(), pid))
    # Si le renovaron/cambiaron sesiones, re-habilitar su alerta de últimas sesiones.
    run("DELETE FROM notif_cerradas WHERE clave=?", (f"alerta:{pid}",))
    return jsonify(ok=True)


@app.route("/api/paciente/<int:pid>/afiliado", methods=["POST"])
def api_paciente_afiliado(pid):
    d = request.get_json(force=True, silent=True) or {}
    if not q1("SELECT 1 FROM pacientes WHERE id=?", (pid,)):
        return jsonify(ok=False, error="Paciente inexistente"), 404
    run("UPDATE pacientes SET nro_afiliado=? WHERE id=?", ((d.get("nro_afiliado") or "").strip(), pid))
    return jsonify(ok=True)


@app.route("/api/paciente/<int:pid>/borrar", methods=["POST"])
def api_borrar_paciente(pid):
    # Borrar el paciente arrastra sus registros para no dejar datos huérfanos.
    for t in ("turnos", "ejercicios", "evoluciones", "pagos",
              "adjuntos", "consentimientos", "plantillas", "eventos", "tokens"):
        try:
            run(f"DELETE FROM {t} WHERE paciente_id=?", (pid,))
        except Exception:
            pass
    run("DELETE FROM pacientes WHERE id=?", (pid,))
    return jsonify(ok=True)


# --------------------------------------------------------------------------
# API — tokens de la obra social
# --------------------------------------------------------------------------
def _token_duplicado(numero, excluir_id=None):
    """Si ese número de token ya está cargado (en cualquier paciente), devuelve dónde."""
    sql = """SELECT k.id, k.fecha, p.nombre, p.apellido FROM tokens k
             LEFT JOIN pacientes p ON p.id=k.paciente_id WHERE k.numero=?"""
    args = [numero]
    if excluir_id:
        sql += " AND k.id<>?"
        args.append(excluir_id)
    r = q1(sql + " LIMIT 1", tuple(args))
    if not r:
        return None
    return {"paciente": f"{r['nombre'] or ''} {r['apellido'] or ''}".strip(), "fecha": r["fecha"]}


def _guardar_token(pid, numero, fecha, turno_id=None, token_id=None):
    """Crea o actualiza un token. Si viene atado a un turno que ya tenía token, lo reemplaza."""
    numero = " ".join((numero or "").split())
    fecha = (fecha or "").strip() or date.today().isoformat()
    turno_id = int(turno_id) if str(turno_id or "").isdigit() else None
    if not token_id and turno_id:
        ex = q1("SELECT id FROM tokens WHERE turno_id=? AND paciente_id=?", (turno_id, pid))
        if ex:
            token_id = ex["id"]
    dup = _token_duplicado(numero, token_id)
    if token_id:
        run("UPDATE tokens SET numero=?, fecha=?, turno_id=? WHERE id=?",
            (numero, fecha, turno_id, token_id))
    else:
        token_id = run("INSERT INTO tokens (paciente_id, turno_id, fecha, numero, creado) VALUES (?,?,?,?,?)",
                       (pid, turno_id, fecha, numero, datetime.now().isoformat(timespec="seconds")))
    return {"id": token_id, "numero": numero, "fecha": fecha, "duplicado": dup}


@app.route("/api/paciente/<int:pid>/tokens")
def api_tokens_paciente(pid):
    tokens = [dict(r) for r in q(
        """SELECT k.id, k.numero, k.fecha, k.turno_id, t.hora, t.fecha AS turno_fecha, t.estado AS turno_estado
           FROM tokens k LEFT JOIN turnos t ON t.id=k.turno_id
           WHERE k.paciente_id=? ORDER BY k.fecha, k.id""", (pid,))]
    por_turno = {k["turno_id"]: k for k in tokens if k["turno_id"]}
    sesiones = []
    for t in q("""SELECT id, fecha, hora, estado FROM turnos
                  WHERE paciente_id=? AND estado NOT IN ('ausente','perdido')
                  ORDER BY fecha, hora, id""", (pid,)):
        k = por_turno.get(t["id"])
        sesiones.append({"turno_id": t["id"], "fecha": t["fecha"], "hora": t["hora"] or "",
                         "estado": t["estado"], "dia": dia_semana(t["fecha"]),
                         "token_id": k["id"] if k else None, "numero": k["numero"] if k else ""})
    vino = [x for x in sesiones if x["estado"] in ("presente", "en_curso", "terminado")]
    return jsonify(ok=True, tokens=tokens, sesiones=sesiones, resumen={
        "cargados": len(tokens),
        "sesiones_vino": len(vino),
        "vino_sin_token": sum(1 for x in vino if not x["numero"]),
    })


@app.route("/api/paciente/<int:pid>/token", methods=["POST"])
def api_nuevo_token(pid):
    d = request.get_json(force=True, silent=True) or {}
    if not (d.get("numero") or "").strip():
        return jsonify(ok=False, error="Escribí el número de token"), 400
    if not q1("SELECT 1 FROM pacientes WHERE id=?", (pid,)):
        return jsonify(ok=False, error="Paciente inexistente"), 404
    r = _guardar_token(pid, d.get("numero"), d.get("fecha"), d.get("turno_id"))
    return jsonify(ok=True, **r)


@app.route("/api/token/<int:kid>", methods=["POST"])
def api_editar_token(kid):
    k = q1("SELECT * FROM tokens WHERE id=?", (kid,))
    if not k:
        return jsonify(ok=False, error="Token inexistente"), 404
    d = request.get_json(force=True, silent=True) or {}
    if not (d.get("numero") or "").strip():
        return jsonify(ok=False, error="Escribí el número de token"), 400
    turno = d.get("turno_id", k["turno_id"])
    # Si lo pasan a un turno que ya tenía otro token, ese otro se desasocia.
    if str(turno or "").isdigit():
        run("UPDATE tokens SET turno_id=NULL WHERE turno_id=? AND id<>?", (int(turno), kid))
    r = _guardar_token(k["paciente_id"], d.get("numero"), d.get("fecha") or k["fecha"],
                       turno, token_id=kid)
    return jsonify(ok=True, **r)


@app.route("/api/token/<int:kid>/borrar", methods=["POST"])
def api_borrar_token(kid):
    run("DELETE FROM tokens WHERE id=?", (kid,))
    return jsonify(ok=True)


@app.route("/api/paciente/<int:pid>/tokens_lote", methods=["POST"])
def api_tokens_lote(pid):
    """Carga (o corrige) los tokens de varias sesiones juntas.
    items: [{turno_id, fecha, numero}] — un número vacío borra el token de esa sesión."""
    d = request.get_json(force=True, silent=True) or {}
    guardados, borrados, duplicados = 0, 0, []
    for it in (d.get("items") or []):
        numero = (it.get("numero") or "").strip()
        turno_id = it.get("turno_id")
        if not numero:
            if str(turno_id or "").isdigit():
                n = q1("SELECT COUNT(*) c FROM tokens WHERE turno_id=? AND paciente_id=?", (int(turno_id), pid))["c"]
                if n:
                    run("DELETE FROM tokens WHERE turno_id=? AND paciente_id=?", (int(turno_id), pid))
                    borrados += n
            continue
        r = _guardar_token(pid, numero, it.get("fecha"), turno_id)
        guardados += 1
        if r["duplicado"]:
            duplicados.append({"numero": r["numero"], **r["duplicado"]})
    return jsonify(ok=True, guardados=guardados, borrados=borrados, duplicados=duplicados)


@app.route("/api/paciente/<int:pid>/ejercicio", methods=["POST"])
def api_nuevo_ejercicio(pid):
    d = request.get_json(force=True, silent=True) or {}
    nombre = (d.get("nombre") or "").strip()
    if not nombre:
        return jsonify(ok=False, error="Falta el nombre del ejercicio"), 400
    turno_id = d.get("turno_id")
    eid = run(
        """INSERT INTO ejercicios
           (paciente_id, nombre, categoria, series, reps, peso, notas, turno_id, fecha)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            pid, nombre, (d.get("categoria") or "").strip(),
            (d.get("series") or "").strip(), (d.get("reps") or "").strip(),
            (d.get("peso") or "").strip(), (d.get("notas") or "").strip(),
            int(turno_id) if turno_id else None, date.today().isoformat(),
        ),
    )
    return jsonify(ok=True, id=eid)


@app.route("/api/ejercicio/<int:eid>/borrar", methods=["POST"])
def api_borrar_ejercicio(eid):
    run("DELETE FROM ejercicios WHERE id=?", (eid,))
    return jsonify(ok=True)


@app.route("/api/paciente/<int:pid>/evolucion", methods=["POST"])
def api_nueva_evolucion(pid):
    d = request.get_json(force=True, silent=True) or {}
    texto = (d.get("texto") or "").strip()
    if not texto:
        return jsonify(ok=False, error="Escribí la nota de evolución"), 400
    fecha = d.get("fecha") or date.today().isoformat()
    eid = run("INSERT INTO evoluciones (paciente_id, fecha, texto) VALUES (?,?,?)",
              (pid, fecha, texto))
    return jsonify(ok=True, id=eid, fecha=fecha)


@app.route("/api/evolucion/<int:eid>/borrar", methods=["POST"])
def api_borrar_evolucion(eid):
    run("DELETE FROM evoluciones WHERE id=?", (eid,))
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
    if "modo_demo" in d and not es_admin():
        return jsonify(ok=False, error="El modo demo lo cambia un administrador."), 403
    for k, v in d.items():
        run("INSERT INTO config (clave, valor) VALUES (?,?) "
            "ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor",
            (k, str(v)))
    return jsonify(ok=True)


# --------------------------------------------------------------------------
# API — sedes (Morón / Ramos)
# --------------------------------------------------------------------------
@app.route("/api/sedes")
def api_sedes():
    actual = sede_actual_id()
    out = []
    for s in sedes_list():
        n_boxes = q1("SELECT COUNT(*) c FROM boxes WHERE activo=1 AND sede_id=?",
                     (s["id"],))["c"]
        out.append({"id": s["id"], "nombre": s["nombre"],
                    "tope_turnos": s["tope_turnos"] or 0,
                    "boxes": n_boxes, "actual": s["id"] == actual})
    return jsonify({"sedes": out, "actual": actual})


@app.route("/api/sede/<int:sid>", methods=["POST"])
def api_editar_sede(sid):
    d = request.get_json(force=True, silent=True) or {}
    s = q1("SELECT * FROM sedes WHERE id=?", (sid,))
    if not s:
        return jsonify(ok=False, error="Sede inexistente"), 404
    nombre = (d.get("nombre") or s["nombre"]).strip() or s["nombre"]
    try:
        tope = int(d.get("tope_turnos"))
    except (TypeError, ValueError):
        tope = s["tope_turnos"] or 0
    tope = max(0, tope)
    run("UPDATE sedes SET nombre=?, tope_turnos=? WHERE id=?", (nombre, tope, sid))
    return jsonify(ok=True)


# --------------------------------------------------------------------------
# API — feriados (días sin turnos). Son globales (valen para todas las sedes).
# --------------------------------------------------------------------------
@app.route("/api/feriados")
def api_feriados():
    rows = q("SELECT fecha, nombre FROM feriados ORDER BY fecha")
    return jsonify({r["fecha"]: (r["nombre"] or "Feriado") for r in rows})


@app.route("/api/feriado", methods=["POST"])
def api_nuevo_feriado():
    d = request.get_json(force=True, silent=True) or {}
    fecha = (d.get("fecha") or "").strip()
    if not fecha:
        return jsonify(ok=False, error="Falta la fecha"), 400
    nombre = (d.get("nombre") or "Feriado").strip() or "Feriado"
    run("INSERT INTO feriados (fecha, nombre) VALUES (?,?) "
        "ON CONFLICT(fecha) DO UPDATE SET nombre=excluded.nombre", (fecha, nombre))
    return jsonify(ok=True)


@app.route("/api/feriado/borrar", methods=["POST"])
def api_borrar_feriado():
    d = request.get_json(force=True, silent=True) or {}
    fecha = (d.get("fecha") or "").strip()
    run("DELETE FROM feriados WHERE fecha=?", (fecha,))
    return jsonify(ok=True)


# Feriados de Argentina (próximos, según el calendario oficial 2026 que pasó el centro).
FERIADOS_AR = [
    ("2026-10-12", "Día del Respeto a la Diversidad Cultural"),
    ("2026-11-20", "Día de la Soberanía Nacional"),
    ("2026-12-07", "Feriado con fines turísticos (puente)"),
    ("2026-12-08", "Inmaculada Concepción de María"),
    ("2026-12-25", "Navidad"),
]


@app.route("/api/feriados/cargar_ar", methods=["POST"])
def api_cargar_feriados_ar():
    n = 0
    for fecha, nombre in FERIADOS_AR:
        run("INSERT INTO feriados (fecha, nombre) VALUES (?,?) "
            "ON CONFLICT(fecha) DO UPDATE SET nombre=excluded.nombre", (fecha, nombre))
        n += 1
    return jsonify(ok=True, cargados=n)


@app.route("/api/feriado/turnos")
def api_feriado_turnos():
    """Cuántos turnos 'vivos' hay en una fecha (para avisar al marcar feriado)."""
    fecha = request.args.get("fecha") or ""
    sede = _sede_de_args()
    n = q1("""SELECT COUNT(*) c FROM turnos WHERE fecha=? AND sede_id=?
              AND estado IN ('agendado','en_espera','presente')""", (fecha, sede))["c"]
    return jsonify(cantidad=n)


@app.route("/api/feriado/reprogramar_turnos", methods=["POST"])
def api_feriado_reprogramar_turnos():
    """Reprograma todos los turnos vivos de una fecha (sede) a la próxima fecha
    disponible de cada paciente (salteando feriados). Se usa al marcar un feriado."""
    d = request.get_json(force=True, silent=True) or {}
    fecha = (d.get("fecha") or "").strip()
    sede = _sede_de_request(d)
    if not fecha:
        return jsonify(ok=False, error="Falta la fecha"), 400
    turnos = q("""SELECT * FROM turnos WHERE fecha=? AND sede_id=?
                  AND estado IN ('agendado','en_espera','presente')""", (fecha, sede))
    movidos = 0
    for t in turnos:
        nf, nh, _p = _proximo_disponible(t)
        run("UPDATE turnos SET estado='ausente', box_id=NULL WHERE id=?", (t["id"],))
        run("""INSERT INTO turnos (paciente_id, fecha, hora, estado, duracion_min, sede_id)
               VALUES (?,?,?, 'agendado', ?, ?)""",
            (t["paciente_id"], nf, nh, t["duracion_min"] or DURACION_DEFAULT, t["sede_id"]))
        movidos += 1
    return jsonify(ok=True, movidos=movidos)


# --------------------------------------------------------------------------
# API — plantillas ortopédicas (RPG). Lista global (todas las sedes).
# --------------------------------------------------------------------------
PLANTILLA_ESTADOS = ["pedida", "fabricacion", "lista", "entregada"]


@app.route("/api/plantillas")
def api_plantillas():
    rows = q(
        """SELECT pl.*, p.nombre, p.apellido, p.telefono, s.nombre AS sede_nombre
           FROM plantillas pl
           LEFT JOIN pacientes p ON p.id = pl.paciente_id
           LEFT JOIN sedes s ON s.id = pl.sede_id
           ORDER BY
             CASE pl.estado WHEN 'entregada' THEN 1 ELSE 0 END,
             pl.id DESC""",
    )
    out = []
    for r in rows:
        if r["paciente_id"] and r["nombre"] is not None:
            nombre = f"{r['nombre']} {r['apellido']}"
            tel = r["telefono"] or r["telefono_libre"] or ""
        else:
            nombre = (r["nombre_libre"] or "Sin nombre")
            tel = r["telefono_libre"] or ""
        out.append({
            "id": r["id"], "paciente_id": r["paciente_id"],
            "es_paciente": bool(r["paciente_id"] and r["nombre"] is not None),
            "paciente": nombre, "telefono": tel,
            "sede_id": r["sede_id"], "sede_nombre": r["sede_nombre"] or "—",
            "estado": r["estado"] or "pedida",
            "fecha_molde": r["fecha_molde"] or "", "fecha_entrega": r["fecha_entrega"] or "",
            "precio": r["precio"] or "", "senia": r["senia"] or "",
            "notas": r["notas"] or "",
        })
    return jsonify({"plantillas": out, "estados": PLANTILLA_ESTADOS})


@app.route("/api/plantilla", methods=["POST"])
def api_nueva_plantilla():
    d = request.get_json(force=True, silent=True) or {}
    pid = d.get("paciente_id") or None
    nombre_libre = (d.get("nombre_libre") or "").strip()
    # Puede ser un paciente cargado O una persona suelta (con nombre libre).
    if not pid and not nombre_libre:
        return jsonify(ok=False, error="Elegí un paciente o escribí un nombre"), 400
    estado = d.get("estado") if d.get("estado") in PLANTILLA_ESTADOS else "pedida"
    plid = run(
        """INSERT INTO plantillas
           (paciente_id, nombre_libre, telefono_libre, sede_id, estado,
            fecha_molde, fecha_entrega, precio, senia, notas, creado)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (pid, nombre_libre, (d.get("telefono_libre") or "").strip(),
         _sede_de_request(d), estado,
         (d.get("fecha_molde") or "").strip(), (d.get("fecha_entrega") or "").strip(),
         (str(d.get("precio") or "")).strip(), (str(d.get("senia") or "")).strip(),
         (d.get("notas") or "").strip(), date.today().isoformat()),
    )
    return jsonify(ok=True, id=plid)


@app.route("/api/plantilla/<int:plid>", methods=["POST"])
def api_editar_plantilla(plid):
    d = request.get_json(force=True, silent=True) or {}
    pl = q1("SELECT * FROM plantillas WHERE id=?", (plid,))
    if not pl:
        return jsonify(ok=False, error="Plantilla inexistente"), 404
    estado = d.get("estado") if d.get("estado") in PLANTILLA_ESTADOS else pl["estado"]
    sede = pl["sede_id"]
    if d.get("sede_id"):
        sede = _sede_de_request(d)
    def keep(k):
        return d.get(k) if d.get(k) is not None else pl[k]
    run(
        """UPDATE plantillas SET sede_id=?, estado=?, fecha_molde=?, fecha_entrega=?,
               precio=?, senia=?, notas=?, nombre_libre=?, telefono_libre=? WHERE id=?""",
        (sede, estado,
         keep("fecha_molde") or "", keep("fecha_entrega") or "",
         (str(d.get("precio")) if d.get("precio") is not None else pl["precio"]) or "",
         (str(d.get("senia")) if d.get("senia") is not None else pl["senia"]) or "",
         keep("notas") or "", keep("nombre_libre") or "", keep("telefono_libre") or "",
         plid),
    )
    return jsonify(ok=True)


@app.route("/api/plantilla/<int:plid>/borrar", methods=["POST"])
def api_borrar_plantilla(plid):
    run("DELETE FROM plantillas WHERE id=?", (plid,))
    return jsonify(ok=True)


@app.route("/api/seed_prueba", methods=["POST"])
def api_seed_prueba():
    """Carga pacientes de prueba con turnos repartidos en todo el día de hoy.
    Sirve para probar la app (sala del día, boxes, agenda) sin cargar datos reales."""
    hoy = date.today().isoformat()
    wd = date.today().weekday()
    horas = ["08:00", "09:00", "10:00", "11:00", "12:00",
             "14:00", "15:00", "16:00", "17:00", "18:00", "19:00"]
    nombres = [
        ("Sofía", "Álvarez", "OSDE", "Tendinitis de hombro"),
        ("Mateo", "Ríos", "Swiss Medical", "Lumbalgia mecánica"),
        ("Valentina", "Torres", "IOMA", "Esguince de rodilla"),
        ("Benjamín", "Sosa", "PAMI", "Cervicalgia"),
        ("Camila", "Díaz", "Galeno", "Post-operatorio de menisco"),
        ("Thiago", "Molina", "OSDE", "Fascitis plantar"),
        ("Martina", "Castro", "Medifé", "Bursitis de cadera"),
        ("Joaquín", "Herrera", "OSPE", "Epicondilitis"),
        ("Renata", "Vega", "OSDE", "Contractura cervical"),
        ("Bautista", "Núñez", "IOMA", "Distensión isquiotibial"),
        ("Delfina", "Aguirre", "Swiss Medical", "Rehabilitación de tobillo"),
    ]
    # días de la semana en los que viene (siempre incluye hoy), sólo Lun-Vie
    dias_idx = sorted(set([wd] + [(wd + 2) % 5, (wd + 4) % 5]))
    sede = sede_actual_id()
    creados = 0
    for i, (nom, ape, os_, diag) in enumerate(nombres):
        hora = horas[i % len(horas)]
        horarios = {str(dx): hora for dx in dias_idx}
        pid = run(
            """INSERT INTO pacientes
               (nombre, apellido, dni, telefono, obra_social, diagnostico,
                sesiones_totales, sesiones_usadas, dias, horarios, creado)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (nom, ape, "", "", os_, diag, 12, i % 8,
             dias_to_str(dias_idx), json.dumps(horarios), hoy),
        )
        run("""INSERT INTO turnos (paciente_id, fecha, hora, estado, duracion_min, sede_id)
               VALUES (?,?,?, 'agendado', ?, ?)""",
            (pid, hoy, hora, DURACION_DEFAULT, sede))
        creados += 1
    return jsonify(ok=True, creados=creados)


@app.route("/api/simular_agenda", methods=["POST"])
def api_simular_agenda():
    """Llena la agenda del mes (sede activa) con turnos de ejemplo para poder
    ver el calendario/semáforo con datos. Se marcan sim=1 para borrarlos luego."""
    import random
    d = request.get_json(force=True, silent=True) or {}
    sede = _sede_de_request(d)
    # Mes a simular: 'YYYY-MM' o el mes actual.
    mes = d.get("mes") or date.today().strftime("%Y-%m")
    try:
        anio, m = map(int, mes.split("-"))
        primero = date(anio, m, 1)
    except Exception:
        primero = date.today().replace(day=1)
    # Último día del mes.
    if primero.month == 12:
        siguiente = date(primero.year + 1, 1, 1)
    else:
        siguiente = date(primero.year, primero.month + 1, 1)

    pacientes = q("SELECT id FROM pacientes ORDER BY id")
    if not pacientes:
        return jsonify(ok=False, error="Cargá algún paciente antes de simular"), 400
    pids = [p["id"] for p in pacientes]
    horas = ["08:00", "09:00", "10:00", "11:00", "12:00",
             "14:00", "15:00", "16:00", "17:00", "18:00", "19:00"]
    tope = tope_de_sede(sede) or 4

    creados = 0
    hoy = date.today()
    cur = primero
    while cur < siguiente:
        # Sólo días futuros y de semana (no ensucia hoy ni dispara el "no vino").
        if cur > hoy and cur.weekday() < 5:
            # Elegir algunas horas del día y meter personas SIN pasar el tope.
            for hora in random.sample(horas, k=random.randint(3, 6)):
                libres = max(0, tope - _slot_ocupado(sede, cur.isoformat(), hora))
                if libres <= 0:
                    continue
                for _ in range(random.randint(1, libres)):
                    pid = random.choice(pids)
                    run("""INSERT INTO turnos
                           (paciente_id, fecha, hora, estado, duracion_min, sede_id, sim)
                           VALUES (?,?,?, 'agendado', ?, ?, 1)""",
                        (pid, cur.isoformat(), hora, DURACION_DEFAULT, sede))
                    creados += 1
        cur += timedelta(days=1)
    return jsonify(ok=True, creados=creados)


@app.route("/api/limpiar_simulacion", methods=["POST"])
def api_limpiar_simulacion():
    """Borra todos los turnos de simulación (sim=1) de la sede indicada."""
    sede = _sede_de_request(request.get_json(force=True, silent=True) or {})
    n = q1("SELECT COUNT(*) c FROM turnos WHERE sim=1 AND sede_id=?", (sede,))["c"]
    run("DELETE FROM turnos WHERE sim=1 AND sede_id=?", (sede,))
    return jsonify(ok=True, borrados=n)


@app.route("/api/backup")
def api_backup():
    """Descarga una copia de seguridad de toda la base (kinesio.db)."""
    # Con WAL, los últimos cambios pueden estar en el archivo -wal; hacemos un
    # checkpoint para que el .db descargado tenga TODO al día.
    try:
        get_db().execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception:
        pass
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    return send_file(DB_PATH, as_attachment=True,
                     download_name=f"kdym_backup_{stamp}.db")


@app.route("/api/backups")
def api_backups():
    out = []
    for f in sorted(glob.glob(os.path.join(_backup_dir(), "kdym_*.db")), reverse=True):
        st = os.stat(f)
        out.append({"nombre": os.path.basename(f),
                    "ts": datetime.fromtimestamp(st.st_mtime).isoformat(),
                    "kb": round(st.st_size / 1024)})
    return jsonify({"backups": out, "ultimo": out[0]["ts"] if out else None})


@app.route("/api/backup/ahora", methods=["POST"])
def api_backup_ahora():
    return jsonify(ok=bool(hacer_backup()))


@app.route("/api/backup/archivo/<nombre>")
def api_backup_descargar(nombre):
    if (not nombre.startswith("kdym_") or not nombre.endswith(".db")
            or "/" in nombre or "\\" in nombre or ".." in nombre):
        abort(404)
    p = os.path.join(_backup_dir(), nombre)
    if not os.path.exists(p):
        abort(404)
    return send_file(p, as_attachment=True, download_name=nombre)


# --------------------------------------------------------------------------
# API — pagos y bonos
# --------------------------------------------------------------------------
@app.route("/api/paciente/<int:pid>/pagos")
def api_pagos_paciente(pid):
    rows = q("SELECT * FROM pagos WHERE paciente_id=? ORDER BY fecha DESC, id DESC", (pid,))
    p = q1("SELECT sesiones_usadas, sesiones_totales, precio_sesion FROM pacientes WHERE id=?", (pid,))
    pagos = [{"id": r["id"], "fecha": r["fecha"] or "", "monto": r["monto"] or 0,
              "metodo": r["metodo"] or "", "concepto": r["concepto"] or ""} for r in rows]
    total = sum((r["monto"] or 0) for r in rows)
    precio = (p["precio_sesion"] if p else 0) or 0
    usadas = (p["sesiones_usadas"] if p else 0) or 0
    esperado = precio * usadas
    return jsonify({"pagos": pagos, "total_pagado": round(total, 2),
                    "precio_sesion": precio, "sesiones_usadas": usadas,
                    "esperado": round(esperado, 2), "saldo": round(esperado - total, 2)})


@app.route("/api/paciente/<int:pid>/pago", methods=["POST"])
def api_nuevo_pago(pid):
    d = request.get_json(force=True, silent=True) or {}
    try:
        monto = float(d.get("monto") or 0)
    except (TypeError, ValueError):
        monto = 0
    if monto <= 0:
        return jsonify(ok=False, error="Poné un monto"), 400
    run("""INSERT INTO pagos (paciente_id, sede_id, fecha, monto, metodo, concepto, creado)
           VALUES (?,?,?,?,?,?,?)""",
        (pid, sede_actual_id(), d.get("fecha") or date.today().isoformat(), monto,
         (d.get("metodo") or "").strip(), (d.get("concepto") or "").strip(),
         datetime.now().isoformat()))
    return jsonify(ok=True)


@app.route("/api/pago/<int:pgid>/borrar", methods=["POST"])
def api_borrar_pago(pgid):
    run("DELETE FROM pagos WHERE id=?", (pgid,))
    return jsonify(ok=True)


@app.route("/api/paciente/<int:pid>/precio_sesion", methods=["POST"])
def api_precio_sesion(pid):
    d = request.get_json(force=True, silent=True) or {}
    try:
        precio = float(d.get("precio") or 0)
    except (TypeError, ValueError):
        precio = 0
    run("UPDATE pacientes SET precio_sesion=? WHERE id=?", (precio, pid))
    return jsonify(ok=True)


# --------------------------------------------------------------------------
# Liquidación mensual a las obras sociales
# --------------------------------------------------------------------------
MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio",
         "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
ESTADOS_LIQ = {"pendiente": "Pendiente", "presentada": "Presentada", "cobrada": "Cobrada"}


def _es_particular(os_):
    k = _sin_acentos(" ".join((os_ or "").split()))
    return not k or k in ("particular", "sin obra social", "ninguna", "no tiene", "-")


def _mes_param(txt):
    txt = (txt or "").strip()
    if re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", txt):
        return txt
    return date.today().strftime("%Y-%m")


def _mes_txt(mes):
    y, m = mes.split("-")
    return f"{MESES[int(m) - 1]} {y}"


def _datos_liquidacion(mes, sede):
    """Sesiones realizadas del mes (vino / en sesión / terminó), agrupadas por
    obra social y paciente, con el token de cada una. No cuenta los turnos de
    'Simular agenda' ni a los particulares."""
    sql = """SELECT t.id tid, t.fecha, t.hora, p.id pid, p.nombre, p.apellido, p.dni,
                    p.nro_afiliado, p.obra_social
             FROM turnos t JOIN pacientes p ON p.id = t.paciente_id
             WHERE t.fecha >= ? AND t.fecha <= ? AND COALESCE(t.sim, 0) = 0
               AND t.estado IN ('presente', 'en_curso', 'terminado')"""
    args = [mes + "-01", mes + "-31"]
    if str(sede or "").isdigit():
        sql += " AND t.sede_id = ?"
        args.append(int(sede))
    filas = q(sql + " ORDER BY p.apellido COLLATE NOCASE, p.nombre COLLATE NOCASE, t.fecha, t.hora", args)

    # Tokens: los ligados al turno, y si no, uno cargado suelto para ese día.
    pids = sorted({f["pid"] for f in filas})
    por_turno, sueltos = {}, {}
    for i in range(0, len(pids), 500):
        lote = pids[i:i + 500]
        for k in q(f"SELECT * FROM tokens WHERE paciente_id IN ({','.join('?' * len(lote))})", lote):
            if k["turno_id"]:
                por_turno[k["turno_id"]] = k
            else:
                sueltos.setdefault((k["paciente_id"], k["fecha"]), []).append(k)

    obras = {_sin_acentos(o["nombre"]): o for o in q("SELECT * FROM obras_sociales")}
    liqs = {_sin_acentos(r["obra_social"]): r for r in q("SELECT * FROM liquidaciones WHERE mes=?", (mes,))}
    grupos, particulares = {}, 0
    for f in filas:
        os_ = " ".join((f["obra_social"] or "").split())
        if _es_particular(os_):
            particulares += 1
            continue
        k = _sin_acentos(os_)
        if k not in grupos:
            o, lq = obras.get(k), liqs.get(k)
            arancel = lq["arancel"] if (lq and lq["arancel"] is not None) else (o["arancel"] if o else None)
            grupos[k] = {"obra_social": o["nombre"] if o else os_, "clave": k,
                         "estado": (lq["estado"] if lq else "pendiente"), "arancel": arancel,
                         "pacientes": {}}
        pacs = grupos[k]["pacientes"]
        if f["pid"] not in pacs:
            pacs[f["pid"]] = {"id": f["pid"], "nombre": f"{f['apellido']}, {f['nombre']}",
                              "dni": f["dni"] or "", "afiliado": f["nro_afiliado"] or "", "sesiones": []}
        tk = por_turno.get(f["tid"])
        if not tk and sueltos.get((f["pid"], f["fecha"])):
            tk = sueltos[(f["pid"], f["fecha"])].pop(0)
        pacs[f["pid"]]["sesiones"].append({"turno_id": f["tid"], "fecha": f["fecha"], "hora": f["hora"] or "",
                                           "token": (tk["numero"] if tk else "") or "",
                                           "token_id": tk["id"] if tk else None})

    out = []
    for gr in sorted(grupos.values(), key=lambda x: _sin_acentos(x["obra_social"])):
        pacientes = list(gr.pop("pacientes").values())
        ses = [x for pc in pacientes for x in pc["sesiones"]]
        con = sum(1 for x in ses if x["token"])
        for pc in pacientes:
            pc["sin_token"] = sum(1 for x in pc["sesiones"] if not x["token"])
        gr.update(pacientes=pacientes, sesiones=len(ses), con_token=con, sin_token=len(ses) - con,
                  sin_afiliado=sum(1 for pc in pacientes if not pc["afiliado"]),
                  total=(round(gr["arancel"] * len(ses), 2) if gr["arancel"] else None),
                  estado_txt=ESTADOS_LIQ.get(gr["estado"], gr["estado"]))
        out.append(gr)
    return out, particulares


@app.route("/api/liquidacion")
def api_liquidacion():
    mes = _mes_param(request.args.get("mes"))
    sede = request.args.get("sede") or ""
    obras, particulares = _datos_liquidacion(mes, sede)
    admin = es_admin()
    if not admin:   # la plata la ve sólo un administrador
        for o in obras:
            o["arancel"] = o["total"] = None
    res = {"sesiones": sum(o["sesiones"] for o in obras),
           "con_token": sum(o["con_token"] for o in obras),
           "sin_token": sum(o["sin_token"] for o in obras),
           "sin_afiliado": sum(o["sin_afiliado"] for o in obras),
           "pacientes": sum(len(o["pacientes"]) for o in obras),
           "total": (round(sum(o["total"] or 0 for o in obras), 2) if admin else None),
           "sin_arancel": (sum(1 for o in obras if not o["arancel"]) if admin else None)}
    return jsonify(ok=True, mes=mes, mes_txt=_mes_txt(mes), sede=sede, es_admin=admin,
                   particulares=particulares, resumen=res, obras=obras)


def _liq_fila(obra_social, mes):
    k = _sin_acentos(" ".join((obra_social or "").split()))
    for r in q("SELECT * FROM liquidaciones WHERE mes=?", (mes,)):
        if _sin_acentos(r["obra_social"]) == k:
            return r
    lid = run("INSERT INTO liquidaciones (obra_social, mes, estado, actualizado) VALUES (?,?,?,?)",
              (" ".join(obra_social.split()), mes, "pendiente", datetime.now().strftime("%Y-%m-%d %H:%M")))
    return q1("SELECT * FROM liquidaciones WHERE id=?", (lid,))


@app.route("/api/liquidacion/estado", methods=["POST"])
def api_liquidacion_estado():
    d = request.get_json(force=True, silent=True) or {}
    estado, os_ = d.get("estado"), (d.get("obra_social") or "").strip()
    if estado not in ESTADOS_LIQ or not os_:
        return jsonify(ok=False, error="Datos incompletos"), 400
    mes = _mes_param(d.get("mes"))
    r = _liq_fila(os_, mes)
    run("UPDATE liquidaciones SET estado=?, actualizado=? WHERE id=?",
        (estado, datetime.now().strftime("%Y-%m-%d %H:%M"), r["id"]))
    return jsonify(ok=True, estado=estado, estado_txt=ESTADOS_LIQ[estado])


@app.route("/api/liquidacion/arancel", methods=["POST"])
def api_liquidacion_arancel():
    """Valor por sesión de una obra social para ese mes. También queda como
    valor propuesto para los meses siguientes."""
    d = request.get_json(force=True, silent=True) or {}
    os_ = (d.get("obra_social") or "").strip()
    v = d.get("arancel")
    try:
        if isinstance(v, str):   # acepta "12.500,50" o "12500.5"
            v = v.strip().replace("$", "").replace(" ", "")
            if "," in v:
                v = v.replace(".", "").replace(",", ".")
        arancel = float(v or 0)
    except (TypeError, ValueError):
        return jsonify(ok=False, error="El valor tiene que ser un número"), 400
    if not os_ or arancel < 0:
        return jsonify(ok=False, error="Datos incompletos"), 400
    mes = _mes_param(d.get("mes"))
    r = _liq_fila(os_, mes)
    run("UPDATE liquidaciones SET arancel=?, actualizado=? WHERE id=?",
        (arancel or None, datetime.now().strftime("%Y-%m-%d %H:%M"), r["id"]))
    nombre = _obra_social_canonica(os_)
    run("UPDATE obras_sociales SET arancel=? WHERE nombre=?", (arancel or None, nombre))
    return jsonify(ok=True, arancel=arancel)


@app.route("/api/liquidacion/excel")
def api_liquidacion_excel():
    from io import BytesIO
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    mes = _mes_param(request.args.get("mes"))
    sede = request.args.get("sede") or ""
    solo = _sin_acentos((request.args.get("os") or "").strip())
    obras, _ = _datos_liquidacion(mes, sede)
    if solo:
        obras = [o for o in obras if o["clave"] == solo]
    admin = es_admin()
    sede_nom = next((x["nombre"] for x in sedes_list() if str(x["id"]) == str(sede)), "Todas las sedes")

    wb = Workbook()
    negrita, titulo = Font(bold=True), Font(bold=True, size=14)
    cab = PatternFill("solid", fgColor="0F2350")
    amarillo = PatternFill("solid", fgColor="FFF4D6")
    fino = Side(style="thin", color="D5DCE8")
    borde = Border(left=fino, right=fino, top=fino, bottom=fino)
    usados = set()

    def hoja_nombre(txt):
        base = re.sub(r"[\[\]\:\*\?\/\\]", " ", txt).strip()[:28] or "Hoja"
        nom, i = base, 2
        while nom.lower() in usados:
            nom, i = f"{base[:25]} ({i})", i + 1
        usados.add(nom.lower())
        return nom

    # Resumen
    ws = wb.active
    ws.title = hoja_nombre("Resumen")
    ws.append([f"{MARCA} · Liquidación a obras sociales"]); ws["A1"].font = titulo
    ws.append([f"Período: {_mes_txt(mes)}", "", f"Sede: {sede_nom}"])
    ws.append([])
    cols = ["Obra social", "Pacientes", "Sesiones", "Con token", "Sin token", "Estado"]
    if admin:
        cols += ["Valor por sesión", "Total"]
    ws.append(cols)
    for c in ws[4]:
        c.font = Font(bold=True, color="FFFFFF"); c.fill = cab; c.border = borde
    for o in obras:
        fila = [o["obra_social"], len(o["pacientes"]), o["sesiones"], o["con_token"], o["sin_token"], o["estado_txt"]]
        if admin:
            fila += [o["arancel"] or None, o["total"] or None]
        ws.append(fila)
        for c in ws[ws.max_row]:
            c.border = borde
        if o["sin_token"]:
            ws.cell(ws.max_row, 5).fill = amarillo
    if admin and obras:
        ws.append(["Total", sum(len(o["pacientes"]) for o in obras), sum(o["sesiones"] for o in obras),
                   sum(o["con_token"] for o in obras), sum(o["sin_token"] for o in obras), "", "",
                   sum(o["total"] or 0 for o in obras)])
        for c in ws[ws.max_row]:
            c.font = negrita; c.border = borde
        for r in ws.iter_rows(min_row=5, min_col=7, max_col=8):
            for c in r:
                c.number_format = '"$" #,##0.00'
    for col, ancho in zip("ABCDEFGH", [28, 11, 10, 11, 10, 13, 16, 16]):
        ws.column_dimensions[col].width = ancho

    # Una hoja por obra social: una fila por sesión
    for o in obras:
        ws = wb.create_sheet(hoja_nombre(o["obra_social"]))
        ws.append([f"Liquidación {o['obra_social']}"]); ws["A1"].font = titulo
        ws.append([f"Período: {_mes_txt(mes)}", "", f"Sede: {sede_nom}"])
        ws.append([])
        ws.append(["Paciente", "DNI", "Nº de afiliado", "Fecha", "Hora", "Token"])
        for c in ws[4]:
            c.font = Font(bold=True, color="FFFFFF"); c.fill = cab; c.border = borde
        for pc in o["pacientes"]:
            for x in pc["sesiones"]:
                ws.append([pc["nombre"], pc["dni"], pc["afiliado"],
                           date.fromisoformat(x["fecha"]).strftime("%d/%m/%Y"), x["hora"], x["token"]])
                for c in ws[ws.max_row]:
                    c.border = borde
                if not x["token"]:
                    ws.cell(ws.max_row, 6).fill = amarillo
                if not pc["afiliado"]:
                    ws.cell(ws.max_row, 3).fill = amarillo
        ws.append([])
        ws.append(["Pacientes", len(o["pacientes"])])
        ws.append(["Sesiones", o["sesiones"]])
        if o["sin_token"]:
            ws.append(["Sesiones sin token", o["sin_token"]])
        if admin and o["arancel"]:
            ws.append(["Valor por sesión", o["arancel"]]); ws.cell(ws.max_row, 2).number_format = '"$" #,##0.00'
            ws.append(["Total", o["total"]]); ws.cell(ws.max_row, 2).number_format = '"$" #,##0.00'
            ws.cell(ws.max_row, 1).font = negrita; ws.cell(ws.max_row, 2).font = negrita
        for col, ancho in zip("ABCDEF", [30, 13, 18, 12, 8, 18]):
            ws.column_dimensions[col].width = ancho
        ws.freeze_panes = "A5"
        for c in ws["B"] + ws["C"] + ws["F"]:
            c.alignment = Alignment(horizontal="left")

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    nombre = f"liquidacion_{mes}" + (f"_{re.sub(r'[^a-z0-9]+', '_', solo)}" if solo else "") + ".xlsx"
    return send_file(buf, as_attachment=True, download_name=nombre,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route("/api/obras_sociales")
def api_obras_sociales():
    usos = {}
    for r in q("SELECT obra_social FROM pacientes WHERE TRIM(COALESCE(obra_social,''))<>''"):
        k = _sin_acentos(" ".join(r["obra_social"].split()))
        usos[k] = usos.get(k, 0) + 1
    rows = q("SELECT id, nombre FROM obras_sociales ORDER BY nombre COLLATE NOCASE")
    return jsonify([{"id": r["id"], "nombre": r["nombre"],
                     "pacientes": usos.get(_sin_acentos(r["nombre"]), 0)} for r in rows])


def _obra_social_repetida(nombre, salvo_id=None):
    clave = _sin_acentos(nombre)
    for r in q("SELECT id, nombre FROM obras_sociales"):
        if r["id"] != salvo_id and _sin_acentos(r["nombre"]) == clave:
            return r
    return None


@app.route("/api/obra_social", methods=["POST"])
def api_nueva_obra_social():
    d = request.get_json(force=True, silent=True) or {}
    nombre = " ".join((d.get("nombre") or "").split())
    if not nombre:
        return jsonify(ok=False, error="Escribí el nombre"), 400
    if _obra_social_repetida(nombre):
        return jsonify(ok=False, error="Esa obra social ya está en la lista"), 400
    oid = run("INSERT INTO obras_sociales (nombre, creado) VALUES (?,?)",
              (nombre, date.today().isoformat()))
    return jsonify(ok=True, id=oid)


@app.route("/api/obra_social/<int:oid>", methods=["POST"])
def api_editar_obra_social(oid):
    """Renombra (ej: corregir 'Swis Medical'). Los pacientes que la tenían pasan
    al nombre nuevo. Si el nombre nuevo ya existe, se unen en una sola."""
    d = request.get_json(force=True, silent=True) or {}
    nombre = " ".join((d.get("nombre") or "").split())
    actual = q1("SELECT id, nombre FROM obras_sociales WHERE id=?", (oid,))
    if not actual:
        return jsonify(ok=False, error="No existe"), 404
    if not nombre:
        return jsonify(ok=False, error="Escribí el nombre"), 400
    otra = _obra_social_repetida(nombre, salvo_id=oid)
    if otra:
        nombre = otra["nombre"]
        run("DELETE FROM obras_sociales WHERE id=?", (oid,))
    else:
        run("UPDATE obras_sociales SET nombre=? WHERE id=?", (nombre, oid))
    viejo = _sin_acentos(actual["nombre"])
    ids = [r["id"] for r in q("SELECT id, obra_social FROM pacientes WHERE TRIM(COALESCE(obra_social,''))<>''")
           if _sin_acentos(" ".join(r["obra_social"].split())) == viejo]
    for pid in ids:
        run("UPDATE pacientes SET obra_social=? WHERE id=?", (nombre, pid))
    return jsonify(ok=True, nombre=nombre, unida=bool(otra), pacientes=len(ids))


@app.route("/api/obra_social/<int:oid>/borrar", methods=["POST"])
def api_borrar_obra_social(oid):
    # Sólo la saca de la lista: los pacientes que la tienen la conservan.
    run("DELETE FROM obras_sociales WHERE id=?", (oid,))
    return jsonify(ok=True)


@app.route("/api/precios")
def api_precios():
    rows = q("SELECT id, nombre, monto FROM precios ORDER BY monto")
    return jsonify([{"id": r["id"], "nombre": r["nombre"] or "", "monto": r["monto"] or 0}
                    for r in rows])


@app.route("/api/precio", methods=["POST"])
def api_nuevo_precio():
    d = request.get_json(force=True, silent=True) or {}
    nombre = (d.get("nombre") or "").strip()
    try:
        monto = float(d.get("monto") or 0)
    except (TypeError, ValueError):
        monto = 0
    if not nombre or monto <= 0:
        return jsonify(ok=False, error="Poné nombre y monto"), 400
    pid = run("INSERT INTO precios (nombre, monto) VALUES (?,?)", (nombre, monto))
    return jsonify(ok=True, id=pid)


@app.route("/api/precio/<int:prid>/borrar", methods=["POST"])
def api_borrar_precio(prid):
    run("DELETE FROM precios WHERE id=?", (prid,))
    return jsonify(ok=True)


# --------------------------------------------------------------------------
# API — adjuntos (estudios, recetas, fotos) — guardados en la base
# --------------------------------------------------------------------------
@app.route("/api/paciente/<int:pid>/adjuntos")
def api_adjuntos(pid):
    rows = q("""SELECT id, nombre, tipo, categoria, fecha, LENGTH(datos) tam
                FROM adjuntos WHERE paciente_id=? ORDER BY id DESC""", (pid,))
    return jsonify([{"id": r["id"], "nombre": r["nombre"] or "archivo",
                     "tipo": r["tipo"] or "", "categoria": r["categoria"] or "",
                     "fecha": r["fecha"] or "", "kb": round((r["tam"] or 0) / 1024),
                     "es_img": (r["tipo"] or "").startswith("image/")} for r in rows])


@app.route("/api/paciente/<int:pid>/adjunto", methods=["POST"])
def api_subir_adjunto(pid):
    f = request.files.get("archivo")
    if not f:
        return jsonify(ok=False, error="Falta el archivo"), 400
    datos = f.read()
    if len(datos) > 8 * 1024 * 1024:
        return jsonify(ok=False, error="El archivo es muy grande (máx 8 MB)"), 400
    run("""INSERT INTO adjuntos (paciente_id, nombre, tipo, categoria, datos, fecha)
           VALUES (?,?,?,?,?,?)""",
        (pid, f.filename, f.mimetype, (request.form.get("categoria") or "").strip(),
         datos, date.today().isoformat()))
    return jsonify(ok=True)


@app.route("/api/adjunto/<int:aid>")
def api_ver_adjunto(aid):
    r = q1("SELECT nombre, tipo, datos FROM adjuntos WHERE id=?", (aid,))
    if not r:
        abort(404)
    resp = Response(r["datos"], mimetype=r["tipo"] or "application/octet-stream")
    disp = "attachment" if request.args.get("dl") else "inline"
    resp.headers["Content-Disposition"] = f'{disp}; filename="{r["nombre"] or "archivo"}"'
    return resp


@app.route("/api/adjunto/<int:aid>/borrar", methods=["POST"])
def api_borrar_adjunto(aid):
    run("DELETE FROM adjuntos WHERE id=?", (aid,))
    return jsonify(ok=True)


# --------------------------------------------------------------------------
# API — consentimiento informado (firma)
# --------------------------------------------------------------------------
@app.route("/api/paciente/<int:pid>/consentimiento")
def api_consentimiento_get(pid):
    r = q1("""SELECT id, fecha, aclaracion FROM consentimientos
              WHERE paciente_id=? ORDER BY id DESC LIMIT 1""", (pid,))
    if not r:
        return jsonify(firmado=False)
    return jsonify(firmado=True, id=r["id"], fecha=r["fecha"] or "",
                   aclaracion=r["aclaracion"] or "")


@app.route("/api/paciente/<int:pid>/consentimiento", methods=["POST"])
def api_consentimiento_set(pid):
    d = request.get_json(force=True, silent=True) or {}
    firma = d.get("firma") or ""
    blob = None
    if firma.startswith("data:image"):
        try:
            blob = base64.b64decode(firma.split(",", 1)[1])
        except Exception:
            blob = None
    run("INSERT INTO consentimientos (paciente_id, fecha, aclaracion, firma) VALUES (?,?,?,?)",
        (pid, date.today().isoformat(), (d.get("aclaracion") or "").strip(), blob))
    return jsonify(ok=True)


@app.route("/api/consentimiento/<int:cid>/firma")
def api_consentimiento_firma(cid):
    r = q1("SELECT firma FROM consentimientos WHERE id=?", (cid,))
    if not r or not r["firma"]:
        abort(404)
    return Response(r["firma"], mimetype="image/png")


# --------------------------------------------------------------------------
# API — reportes
# --------------------------------------------------------------------------
@app.route("/api/reportes")
def api_reportes():
    mes = request.args.get("mes") or date.today().strftime("%Y-%m")
    try:
        y, m = map(int, mes.split("-"))
        ini = date(y, m, 1).isoformat()
        fin = (date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)).isoformat()
    except Exception:
        ini = date.today().replace(day=1).isoformat()
        fin = date.today().isoformat()

    sede_f = request.args.get("sede", type=int)
    sf_sql, sf_args = ("AND sede_id=?", (sede_f,)) if sede_f else ("", ())

    def cnt(extra="", args=()):
        return q1(f"SELECT COUNT(*) c FROM turnos WHERE fecha>=? AND fecha<? {sf_sql} {extra}",
                  (ini, fin, *sf_args, *args))["c"]

    total = cnt()
    vinieron = cnt("AND estado IN ('presente','en_curso','terminado')")
    ausentes = cnt("AND estado IN ('ausente','perdido')")
    hoy_iso = date.today().isoformat()
    pendientes = cnt("AND estado IN ('agendado','en_espera') AND fecha>=?", (hoy_iso,))
    # Turnos de días que ya pasaron y nadie marcó si vino o no.
    sin_registrar = cnt("AND estado IN ('agendado','en_espera') AND fecha<?", (hoy_iso,))
    # Turnos por día del mes (para el gráfico).
    por_dia = {r["fecha"]: {"total": r["c"], "vinieron": r["v"], "ausentes": r["a"]} for r in q(
        f"""SELECT fecha, COUNT(*) c,
                   SUM(CASE WHEN estado IN ('presente','en_curso','terminado') THEN 1 ELSE 0 END) v,
                   SUM(CASE WHEN estado IN ('ausente','perdido') THEN 1 ELSE 0 END) a
            FROM turnos WHERE fecha>=? AND fecha<? {sf_sql} GROUP BY fecha""", (ini, fin, *sf_args))}
    ing = q1(f"SELECT COALESCE(SUM(monto),0) s, COUNT(*) c FROM pagos WHERE fecha>=? AND fecha<? {sf_sql}",
             (ini, fin, *sf_args))
    por_sede = [{"sede": s["nombre"], "id": s["id"],
                 "cant": q1("SELECT COUNT(*) c FROM turnos WHERE fecha>=? AND fecha<? AND sede_id=?",
                            (ini, fin, s["id"]))["c"]} for s in sedes_list()]
    filas_os = q(
        """SELECT COALESCE(NULLIF(TRIM(p.obra_social),''),'Sin obra social') os, COUNT(*) c
           FROM turnos t JOIN pacientes p ON p.id=t.paciente_id
           WHERE t.fecha>=? AND t.fecha<? """ + ("AND t.sede_id=? " if sede_f else "") +
        """GROUP BY os ORDER BY c DESC""", (ini, fin, *sf_args))
    por_os = [{"obra_social": r["os"], "cant": r["c"]} for r in filas_os]

    # Cobros pendientes: saldo (precio_sesion * usadas - pagado) agrupado por obra social.
    pend = {}
    for p in q("SELECT id, obra_social, sesiones_usadas, precio_sesion FROM pacientes"):
        precio = p["precio_sesion"] or 0
        if not precio:
            continue
        pagado = q1("SELECT COALESCE(SUM(monto),0) s FROM pagos WHERE paciente_id=?",
                    (p["id"],))["s"] or 0
        saldo = precio * (p["sesiones_usadas"] or 0) - pagado
        if saldo > 0.5:
            k = (p["obra_social"] or "").strip() or "Particular"
            pend[k] = pend.get(k, 0) + saldo
    cobros = [{"obra_social": k, "saldo": round(v, 2)}
              for k, v in sorted(pend.items(), key=lambda x: -x[1])]

    return jsonify({
        "mes": mes, "total": total, "vinieron": vinieron, "ausentes": ausentes,
        # La asistencia se mide sobre los turnos que ya se resolvieron (vino / no vino),
        # no sobre los que todavía no llegaron.
        "asistencia_pct": round(100 * vinieron / (vinieron + ausentes)) if (vinieron + ausentes) else None,
        "pendientes": pendientes, "sin_registrar": sin_registrar, "por_dia": por_dia,
        "ingresos": round(ing["s"] or 0, 2), "pagos_cant": ing["c"],
        "por_sede": por_sede, "por_obra_social": por_os, "cobros_pendientes": cobros,
    })


# --------------------------------------------------------------------------
# API — boxes
# --------------------------------------------------------------------------
@app.route("/api/box", methods=["POST"])
def api_nuevo_box():
    d = request.get_json(force=True, silent=True) or {}
    nombre = (d.get("nombre") or "").strip() or "Box"
    sede = _sede_de_request(d)
    bid = run("INSERT INTO boxes (nombre, sede_id) VALUES (?,?)", (nombre, sede))
    return jsonify(ok=True, id=bid)


@app.route("/api/box/<int:bid>/borrar", methods=["POST"])
def api_borrar_box(bid):
    run("UPDATE boxes SET activo=0 WHERE id=?", (bid,))
    return jsonify(ok=True)


# --------------------------------------------------------------------------
# Backup automático programado (una copia diaria de la base, con rotación).
# --------------------------------------------------------------------------
def _backup_dir():
    d = os.path.join(_db_dir or BASE_DIR, "backups")
    os.makedirs(d, exist_ok=True)
    return d


def hacer_backup():
    """Copia la base a backups/kdym_<fecha>.db y deja las últimas 10."""
    try:
        d = _backup_dir()
        try:  # con WAL, volcar lo pendiente para que el backup esté completo
            con = sqlite3.connect(DB_PATH)
            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            con.close()
        except Exception:
            pass
        dest = os.path.join(d, "kdym_" + datetime.now().strftime("%Y%m%d_%H%M") + ".db")
        shutil.copy2(DB_PATH, dest)
        files = sorted(glob.glob(os.path.join(d, "kdym_*.db")))
        for f in files[:-10]:
            try:
                os.remove(f)
            except Exception:
                pass
        return dest
    except Exception:
        return None


def _ultimo_backup_ts():
    files = sorted(glob.glob(os.path.join(_backup_dir(), "kdym_*.db")))
    return os.path.getmtime(files[-1]) if files else 0


def _backup_loop():
    while True:
        time.sleep(6 * 3600)              # revisa cada 6 h
        if time.time() - _ultimo_backup_ts() >= 24 * 3600 - 60:
            hacer_backup()                # ~1 backup por día


def _start_backup_thread():
    if os.environ.get("KDYM_NO_BACKUP"):
        return
    try:
        if time.time() - _ultimo_backup_ts() >= 12 * 3600:
            hacer_backup()                # uno al arrancar si no hay reciente
        threading.Thread(target=_backup_loop, daemon=True).start()
    except Exception:
        pass


# --------------------------------------------------------------------------
# Demo pública (sólo con KDYM_DEMO=1): datos de ejemplo que se reinician todos
# los días, y "hoy" se rearma según la hora para que siempre haya movimiento.
# --------------------------------------------------------------------------
DEMO_USUARIOS = {"admin": ("demo-admin", "Laura Méndez"), "recepcion": ("demo-recepcion", "Sofía Ruiz")}

DEMO_PACIENTES = [  # nombre, apellido, obra social, diagnóstico, sede (0 = Centro, 1 = Norte)
    ("Martina", "Acosta", "OSDE", "Esguince de tobillo grado II", 0),
    ("Julián", "Benítez", "Swiss Medical", "Post-operatorio de ligamento cruzado anterior", 0),
    ("Valentina", "Cabrera", "IOMA", "Lumbalgia mecánica", 0),
    ("Tomás", "Domínguez", "OSDE", "Tendinitis del manguito rotador", 0),
    ("Camila", "Espinoza", "Galeno", "Cervicalgia", 0),
    ("Mateo", "Fernández", "PAMI", "Post-operatorio de prótesis de rodilla", 0),
    ("Sofía", "García", "Particular", "Fascitis plantar", 0),
    ("Benjamín", "Herrera", "Medifé", "Epicondilitis lateral", 0),
    ("Lucía", "Ibarra", "OSDE", "Hombro congelado", 0),
    ("Santiago", "Juárez", "IOMA", "Hernia de disco L5-S1", 0),
    ("Emma", "Luna", "Swiss Medical", "Síndrome del túnel carpiano", 0),
    ("Joaquín", "Medina", "PAMI", "Rehabilitación post ACV", 0),
    ("Isabella", "Navarro", "Particular", "Contractura de trapecio", 0),
    ("Lautaro", "Ortiz", "OSDE", "Desgarro de isquiotibiales", 0),
    ("Mía", "Paz", "Galeno", "Condromalacia rotuliana", 0),
    ("Felipe", "Quiroga", "OMINT", "Fractura de radio distal (post yeso)", 0),
    ("Catalina", "Ríos", "Sancor Salud", "Tendinopatía aquiliana", 1),
    ("Thiago", "Sosa", "OSDE", "Lumbociatalgia", 1),
    ("Victoria", "Torres", "IOMA", "Escoliosis", 1),
    ("Bautista", "Vega", "Swiss Medical", "Esguince de rodilla", 1),
    ("Olivia", "Zapata", "PAMI", "Artrosis de cadera", 1),
    ("Agustín", "Álvarez", "Particular", "Pubalgia", 1),
    ("Renata", "Blanco", "Accord Salud", "Bursitis de hombro", 1),
    ("Nicolás", "Castro", "Medifé", "Post-operatorio de menisco", 1),
    ("Delfina", "Díaz", "OSDE", "Cervicobraquialgia", 1),
    ("Facundo", "Giménez", "Galeno", "Esguince de muñeca", 1),
]
DEMO_EVOLUCIONES = [
    "Buena evolución. Disminuye el dolor (EVA 4/10). Se progresa carga.",
    "Refiere molestia al final del rango. Se trabaja movilidad y fortalecimiento isométrico.",
    "Mejora el rango articular. Tolera bien los ejercicios de propiocepción.",
    "Sin dolor en reposo. Se agregan ejercicios para hacer en casa.",
    "Primera sesión: evaluación inicial, plan de 10 sesiones. Objetivo: volver a correr.",
]


def _es_usuario_demo(u):
    return bool(ES_DEMO and u and u["usuario"] in {v[0] for v in DEMO_USUARIOS.values()})


def _demo_db():
    db = sqlite3.connect(DB_PATH, timeout=30)
    db.row_factory = sqlite3.Row
    return db


def _demo_reset():
    """Borra todo y carga el centro de ejemplo. Sólo corre en la demo."""
    if not ES_DEMO:
        return
    import random
    rnd = random.Random(date.today().toordinal())
    hoy = date.today()
    db = _demo_db()
    try:
        for t in ("pacientes", "ejercicios", "turnos", "eventos", "notif_cerradas", "evoluciones",
                  "plantillas", "feriados", "pagos", "adjuntos", "consentimientos", "precios",
                  "tokens", "liquidaciones", "obras_sociales", "boxes", "config"):
            db.execute(f"DELETE FROM {t}")
        db.execute("DELETE FROM usuarios WHERE usuario NOT IN (?, ?)",
                   tuple(v[0] for v in DEMO_USUARIOS.values()))

        # Sedes y boxes
        sedes = [r["id"] for r in db.execute("SELECT id FROM sedes ORDER BY orden, id")]
        while len(sedes) < 2:
            sedes.append(db.execute("INSERT INTO sedes (nombre) VALUES ('x')").lastrowid)
        db.execute("UPDATE sedes SET nombre='Centro', tope_turnos=4, orden=0, activo=1 WHERE id=?", (sedes[0],))
        db.execute("UPDATE sedes SET nombre='Norte', tope_turnos=3, orden=1, activo=1 WHERE id=?", (sedes[1],))
        db.execute(f"UPDATE sedes SET activo=0 WHERE id NOT IN ({sedes[0]}, {sedes[1]})")
        for sede, n in ((sedes[0], 4), (sedes[1], 3)):
            for i in range(1, n + 1):
                db.execute("INSERT INTO boxes (nombre, activo, sede_id) VALUES (?, 1, ?)", (f"Box {i}", sede))

        # Configuración del centro
        horarios = {str(d): {"a": "07:00", "c": "23:59"} for d in range(7)}
        for k, v in {"centro_horarios": json.dumps(horarios), "tolerancia_min": "30",
                     "retiro_horario": "Lun a Vie de 9 a 18 hs", "retiro_direccion": "Av. Siempre Viva 742",
                     "modo_demo": "0"}.items():
            db.execute("INSERT INTO config (clave, valor) VALUES (?, ?)", (k, v))
        aranceles = {"OSDE": 14500, "Swiss Medical": 15000, "Galeno": 13000, "IOMA": 9800,
                     "PAMI": 8500, "Medifé": 13500, "OMINT": 15500}
        for nom in OBRAS_SOCIALES_BASE:
            db.execute("INSERT INTO obras_sociales (nombre, creado, arancel) VALUES (?, ?, ?)",
                       (nom, hoy.isoformat(), aranceles.get(nom)))
        for nom, monto in (("Sesión particular", 18000), ("Bono 10 sesiones", 160000), ("Evaluación inicial", 20000)):
            db.execute("INSERT INTO precios (nombre, monto) VALUES (?, ?)", (nom, monto))

        # Pacientes con su tratamiento: días fijos, horario fijo, sesiones hacia atrás y hacia adelante.
        catalogo = [(r["nombre"], r["categoria"]) for r in db.execute("SELECT nombre, categoria FROM catalogo_ejercicios")]
        slots = [f"{h:02d}:{m:02d}" for h in range(8, 20) for m in (0, 30)]
        mes_ant = (hoy.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
        pids = []
        for i, (nom, ape, os_, diag, si) in enumerate(DEMO_PACIENTES):
            sede = sedes[si]
            sabado = i % 5 == 0
            dias = sorted(rnd.sample(range(5), 2 if i % 3 else 3))
            if sabado:
                dias = [dias[0], 5]
            hora = slots[(i * 7) % len(slots)]
            hor = {str(d): (hora if d < 5 else f"{9 + i % 4:02d}:00") for d in dias}
            totales = rnd.choice([10, 10, 12, 15, 20])
            inicio = hoy - timedelta(days=rnd.randint(10, 55))
            fechas, d = [], inicio
            while len(fechas) < totales and d <= hoy + timedelta(days=35):
                if d.weekday() in dias:
                    fechas.append(d)
                d += timedelta(days=1)
            if os_ == "Particular":
                afiliado = ""
            elif rnd.random() < .12:
                afiliado = ""   # le falta: aparece en la liquidación
            elif os_ == "OSDE":
                afiliado = f"61 {rnd.randint(100000, 999999)} {rnd.randint(1, 9)} 01"
            elif os_ == "IOMA":
                afiliado = f"{rnd.randint(1000000, 9999999)}/0{rnd.randint(0, 3)}"
            elif os_ == "PAMI":
                afiliado = f"15{rnd.randint(1000000000, 9999999999)} 00"
            else:
                afiliado = str(rnd.randint(10000000, 99999999))
            pid = db.execute(
                """INSERT INTO pacientes (nombre, apellido, dni, telefono, obra_social, nro_afiliado,
                   diagnostico, sesiones_totales, sesiones_usadas, dias, horarios, notas, creado, sede_id,
                   precio_sesion) VALUES (?,?,?,?,?,?,?,?,0,?,?,?,?,?,?)""",
                (nom, ape, str(rnd.randint(20_000_000, 45_999_999)), f"11 0000-{1000 + i:04d}", os_, afiliado,
                 diag, totales, dias_to_str(dias), json.dumps(hor),
                 "Paciente de ejemplo de la demo." if i % 4 == 0 else "", inicio.isoformat(), sede,
                 18000 if os_ == "Particular" else None)).lastrowid
            pids.append(pid)
            for f in fechas:
                if f == hoy:
                    continue   # los de hoy se arman según la hora (ver _demo_animar_hoy)
                h = hor[str(f.weekday())]
                if f < hoy:
                    estado = "ausente" if rnd.random() < .09 else "terminado"
                    ini = datetime.combine(f, datetime.min.time()) + timedelta(hours=int(h[:2]), minutes=int(h[3:]))
                    tid = db.execute(
                        """INSERT INTO turnos (paciente_id, fecha, hora, estado, inicio, fin, duracion_min, sede_id, sim)
                           VALUES (?,?,?,?,?,?,30,?,0)""",
                        (pid, f.isoformat(), h, estado, ini.isoformat() if estado == "terminado" else None,
                         (ini + timedelta(minutes=30)).isoformat() if estado == "terminado" else None, sede)).lastrowid
                    if estado == "terminado" and os_ != "Particular":
                        falta = rnd.random() < (.3 if (hoy - f).days <= 6 else .04)
                        if not falta:
                            db.execute("INSERT INTO tokens (paciente_id, turno_id, fecha, numero, creado) VALUES (?,?,?,?,?)",
                                       (pid, tid, f.isoformat(), str(rnd.randint(100000, 999999)), f.isoformat()))
                    if estado == "terminado" and os_ == "Particular":
                        db.execute("INSERT INTO pagos (paciente_id, sede_id, fecha, monto, metodo, concepto, creado) VALUES (?,?,?,?,?,?,?)",
                                   (pid, sede, f.isoformat(), 18000, rnd.choice(["Efectivo", "Transferencia", "Mercado Pago"]),
                                    "Sesión", f.isoformat()))
                else:
                    db.execute("""INSERT INTO turnos (paciente_id, fecha, hora, estado, duracion_min, sede_id, sim)
                                  VALUES (?,?,?,'agendado',30,?,0)""", (pid, f.isoformat(), h, sede))
            # Ejercicios y evolución para algunos
            if catalogo and i % 2 == 0:
                for nomej, cat in rnd.sample(catalogo, 3):
                    db.execute("INSERT INTO ejercicios (paciente_id, nombre, categoria, series, reps, notas) VALUES (?,?,?,?,?,?)",
                               (pid, nomej, cat, str(rnd.choice([2, 3, 4])), rnd.choice(["10", "12", "15", "30 seg"]), ""))
            if i % 3 == 0:
                for k in range(rnd.randint(1, 3)):
                    db.execute("INSERT INTO evoluciones (paciente_id, fecha, texto) VALUES (?,?,?)",
                               (pid, (inicio + timedelta(days=4 * k)).isoformat(), DEMO_EVOLUCIONES[(i + k) % len(DEMO_EVOLUCIONES)]))

        # Plantillas ortopédicas en distintos pasos
        for idx, (estado, dm, precio, senia) in enumerate([("pedida", None, "48000", ""), ("fabricacion", 6, "48000", "20000"),
                                                            ("fabricacion", 3, "52000", "25000"), ("lista", 12, "48000", "20000"),
                                                            ("entregada", 25, "45000", "45000")]):
            db.execute("""INSERT INTO plantillas (paciente_id, sede_id, estado, fecha_molde, fecha_entrega, precio, senia, notas, creado)
                          VALUES (?,?,?,?,?,?,?,?,?)""",
                       (pids[idx * 3], sedes[0], estado, (hoy - timedelta(days=dm)).isoformat() if dm else None,
                        (hoy - timedelta(days=dm - 10)).isoformat() if estado in ("lista", "entregada") and dm else None,
                        precio, senia, "", (hoy - timedelta(days=(dm or 1) + 2)).isoformat()))
        db.execute("""INSERT INTO plantillas (nombre_libre, telefono_libre, sede_id, estado, fecha_molde, precio, senia, creado)
                      VALUES ('Roberto Sánchez', '11 0000-2001', ?, 'lista', ?, '50000', '25000', ?)""",
                   (sedes[1], (hoy - timedelta(days=9)).isoformat(), (hoy - timedelta(days=10)).isoformat()))

        # Liquidación del mes pasado: una cobrada y una presentada
        for os_, est in (("OSDE", "cobrada"), ("Swiss Medical", "presentada")):
            db.execute("INSERT INTO liquidaciones (obra_social, mes, estado, arancel, actualizado) VALUES (?,?,?,?,?)",
                       (os_, mes_ant, est, aranceles.get(os_), hoy.isoformat()))
        db.commit()
    finally:
        db.close()
    _demo_animar_hoy(forzar=True)


_DEMO_ULT = {"t": 0.0, "actividad": 0.0}
_DEMO_LOCK = threading.Lock()


def _demo_animar_hoy(forzar=False):
    """Arma los turnos de HOY según la hora: los de antes ya atendidos, algunos
    en los boxes con el reloj corriendo, otros esperando en la sala y el resto
    por venir. Se rehace cada 20 minutos, pero nunca mientras alguien la está
    usando (así no se le borra lo que acaba de hacer)."""
    if not ES_DEMO:
        return
    with _DEMO_LOCK:
        ahora_ts = time.time()
        if not forzar and (ahora_ts - _DEMO_ULT["t"] < 1200 or ahora_ts - _DEMO_ULT["actividad"] < 900):
            return
        _DEMO_ULT["t"] = ahora_ts
    import random
    rnd = random.Random()
    ahora = datetime.now()
    hoy = date.today()
    hoy_s, wd = hoy.isoformat(), hoy.weekday()
    min_ahora = ahora.hour * 60 + ahora.minute
    db = _demo_db()
    try:
        db.execute("DELETE FROM tokens WHERE turno_id IN (SELECT id FROM turnos WHERE fecha=?)", (hoy_s,))
        db.execute("DELETE FROM turnos WHERE fecha=?", (hoy_s,))
        libres = {}
        for b in db.execute("SELECT id, sede_id FROM boxes WHERE activo=1 ORDER BY id"):
            libres.setdefault(b["sede_id"], []).append(b["id"])
        de_hoy = []
        for p in db.execute("SELECT * FROM pacientes WHERE creado <= ?", (hoy_s,)):
            h = parse_horarios(p["horarios"]).get(str(wd))
            if not h:
                continue
            hechas = db.execute("""SELECT COUNT(*) FROM turnos WHERE paciente_id=?
                                   AND estado IN ('presente','en_curso','terminado')""", (p["id"],)).fetchone()[0]
            if hechas >= (p["sesiones_totales"] or 0):
                continue
            de_hoy.append((int(h[:2]) * 60 + int(h[3:]), h, p))
        de_hoy.sort(key=lambda x: x[0])
        en_box = 0
        for hm, h, p in de_hoy:
            base = datetime.combine(hoy, datetime.min.time()) + timedelta(minutes=hm)
            box, ini, fin, estado = None, None, None, "agendado"
            if hm <= min_ahora - 40:
                estado, ini, fin = "terminado", base, base + timedelta(minutes=30)
            elif hm <= min_ahora and libres.get(p["sede_id"]):
                estado, box = "en_curso", libres[p["sede_id"]].pop(0)
                ini = ahora - timedelta(minutes=max(2, min(min_ahora - hm, 26)))
                en_box += 1
            elif hm <= min_ahora + 15:
                estado = "presente"
            tid = db.execute(
                """INSERT INTO turnos (paciente_id, fecha, hora, estado, box_id, inicio, fin, duracion_min, sede_id, sim)
                   VALUES (?,?,?,?,?,?,?,?,?,0)""",
                (p["id"], hoy_s, h, estado, box, ini.isoformat() if ini else None,
                 fin.isoformat() if fin else None, 45 if hm % 60 == 30 else 30, p["sede_id"])).lastrowid
            if estado == "terminado" and p["obra_social"] != "Particular" and rnd.random() < .8:
                db.execute("INSERT INTO tokens (paciente_id, turno_id, fecha, numero, creado) VALUES (?,?,?,?,?)",
                           (p["id"], tid, hoy_s, str(rnd.randint(100000, 999999)), hoy_s))
        # A cualquier hora que se abra la demo, que haya gente en los boxes y en la sala.
        slot = f"{ahora.hour:02d}:{0 if ahora.minute < 30 else 30:02d}"
        prox = (datetime.combine(hoy, datetime.min.time()) + timedelta(hours=ahora.hour, minutes=(60 if ahora.minute >= 30 else 30)))
        prox_s = prox.strftime("%H:%M") if prox.date() == hoy else "23:30"
        ocupados = {r[0] for r in db.execute(
            "SELECT paciente_id FROM turnos WHERE fecha=? AND estado IN ('agendado','presente','en_curso')", (hoy_s,))}
        candidatos = [p for p in db.execute("""SELECT p.*, (SELECT COUNT(*) FROM turnos t WHERE t.paciente_id = p.id
                                                  AND t.estado IN ('presente','en_curso','terminado')) hechas
                                               FROM pacientes p ORDER BY p.id""")
                      if p["id"] not in ocupados and (p["sesiones_totales"] or 0) - p["hechas"] >= 3]
        rnd.shuffle(candidatos)
        def _nuevo(p, estado, hora, box=None, ini=None):
            db.execute("""INSERT INTO turnos (paciente_id, fecha, hora, estado, box_id, inicio, duracion_min, sede_id, sim)
                          VALUES (?,?,?,?,?,?,?,?,0)""",
                       (p["id"], hoy_s, hora, estado, box, ini, rnd.choice([30, 30, 45]), p["sede_id"]))
        # Por sede: 2 en los boxes, 2 esperando y 2 por venir en la próxima media hora.
        for sede in list(libres.keys()):
            de_sede = [p for p in candidatos if p["sede_id"] == sede]
            en_curso = db.execute("SELECT COUNT(*) FROM turnos WHERE fecha=? AND estado='en_curso' AND sede_id=?",
                                  (hoy_s, sede)).fetchone()[0]
            en_sala = db.execute("SELECT COUNT(*) FROM turnos WHERE fecha=? AND estado='presente' AND sede_id=?",
                                 (hoy_s, sede)).fetchone()[0]
            por_venir = db.execute("SELECT COUNT(*) FROM turnos WHERE fecha=? AND estado='agendado' AND sede_id=?",
                                   (hoy_s, sede)).fetchone()[0]
            while en_curso < 2 and libres[sede] and de_sede:
                _nuevo(de_sede.pop(), "en_curso", slot, libres[sede].pop(0),
                       (ahora - timedelta(minutes=rnd.randint(3, 24))).isoformat())
                en_curso += 1
            while en_sala < 2 and de_sede:
                _nuevo(de_sede.pop(), "presente", slot)
                en_sala += 1
            while por_venir < 2 and de_sede:
                _nuevo(de_sede.pop(), "agendado", prox_s)
                por_venir += 1
        db.execute("""UPDATE pacientes SET sesiones_usadas = (SELECT COUNT(*) FROM turnos t
                      WHERE t.paciente_id = pacientes.id AND t.estado IN ('presente','en_curso','terminado'))""")
        db.commit()
    finally:
        db.close()


def _demo_loop():
    # Reinicia la demo todos los días a las 5 de la mañana.
    while True:
        ahora = datetime.now()
        prox = datetime.combine(ahora.date(), datetime.min.time()) + timedelta(hours=5)
        if prox <= ahora:
            prox += timedelta(days=1)
        time.sleep(max(60, (prox - ahora).total_seconds()))
        try:
            _demo_reset()
        except Exception:
            pass


@app.route("/demo/entrar", methods=["POST"])
def demo_entrar():
    """En la demo se entra sin contraseña, eligiendo cómo verla."""
    if not ES_DEMO:
        abort(404)
    rol = "admin" if request.form.get("rol") == "admin" else "recepcion"
    usuario, nombre = DEMO_USUARIOS[rol]
    r = q1("SELECT * FROM usuarios WHERE usuario=?", (usuario,))
    if not r:
        run("INSERT INTO usuarios (nombre, usuario, clave, rol, activo, creado) VALUES (?,?,?,?,1,?)",
            (nombre, usuario, generate_password_hash(secrets.token_hex(24)), rol, date.today().isoformat()))
    else:
        run("UPDATE usuarios SET nombre=?, rol=?, activo=1 WHERE id=?", (nombre, rol, r["id"]))
    _iniciar_sesion(q1("SELECT * FROM usuarios WHERE usuario=?", (usuario,)), recordar=False)
    _demo_animar_hoy()
    return redirect("/hub")


# init_db() se ejecuta al importar el módulo para que las tablas existan también
# cuando corre bajo gunicorn (Railway no ejecuta el bloque __main__).
init_db()
app.secret_key = _clave_de_sesion()
if ES_DEMO:
    _demo_reset()
    threading.Thread(target=_demo_loop, daemon=True).start()
else:
    _start_backup_thread()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8090))
    app.run(host="0.0.0.0", port=port, debug=False)
