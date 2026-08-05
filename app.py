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
