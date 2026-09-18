# =============================================================================
# agent_notas.py — Agente de Notas, Alarmas y Recordatorios
# =============================================================================
# Responsabilidades:
#   · Notas: crear, leer, buscar, editar, eliminar (SQLite local)
#   · Alarmas: programar alarmas únicas y recurrentes con sonido
#   · Recordatorios: recordatorios con fecha/hora que Jarvis anuncia en voz
#   · Memoria de sesión: guarda info recolectada durante chats y búsquedas
#   · Resumen de sesión: al pedir resumen Jarvis cuenta qué aprendió hoy
#
# Interfaz pública:
#   init(ctx)                                              → inyectar contexto
#   ejecutar(accion, params, chat_widget) -> bool          → punto de entrada
#
# Acciones del dispatcher:
#   Notas:
#     "nota_crear"      → params: {titulo?, contenido}
#     "nota_leer"       → params: {id? | titulo?}        (sin params = todas)
#     "nota_buscar"     → params: {termino}
#     "nota_editar"     → params: {id | titulo, contenido?, titulo_nuevo?}
#     "nota_eliminar"   → params: {id | titulo}
#
#   Alarmas:
#     "alarma_crear"    → params: {hora, etiqueta?, repetir?}
#                            hora: "HH:MM" o "en X minutos"
#                            repetir: "diaria" | "semana" | None
#     "alarma_listar"   → params: {}
#     "alarma_eliminar" → params: {id | etiqueta}
#
#   Recordatorios:
#     "recordatorio_crear"    → params: {texto, fecha_hora?, minutos?, acompanamiento?, categoria?}
#     "recordatorio_listar"   → params: {}
#     "recordatorio_eliminar" → params: {id | texto}
#     "recordatorio_confirmar" → params: {id? | texto?}
#     "acompanamiento_resumen" → params: {}
#
#   Memoria de sesión:
#     "memoria_guardar"  → params: {clave, valor}
#     "memoria_leer"     → params: {clave?}              (sin clave = todo)
#     "memoria_resumir"  → params: {}
#     "memoria_limpiar"  → params: {}
#
# Dependencias inyectadas via init(ctx):
#   hablar, cola_voz, bridge, html_burbuja,
#   limpiar_html, markdown_a_html,
#   base_path, config
# =============================================================================

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from html import escape
from datetime import datetime, timedelta
from typing import Optional

# =============================================================================
# CONTEXTO INYECTADO
# =============================================================================

_ctx: dict = {}


def init(ctx: dict):
    """
    Inyecta el contexto compartido desde Jarvis_main.py.
    Llamar UNA VEZ antes de usar cualquier función.

    Ejemplo:
        import agent_notas
        agent_notas.init({
            "hablar":          hablar,
            "cola_voz":        _cola_voz,
            "bridge":          _bridge,
            "html_burbuja":    _html_burbuja,
            "limpiar_html":    _limpiar_html,
            "markdown_a_html": _markdown_a_html,
            "base_path":       base_path,
            "config":          config,
        })
    """
    global _ctx
    _ctx = ctx
    _init_db()
    _arrancar_monitor()


# =============================================================================
# HELPERS DE CONTEXTO
# =============================================================================

def _hablar(texto, chat_widget=None):
    _ctx["hablar"](texto, chat_widget)

def _bridge_html(html):
    _ctx["bridge"].append_html.emit(html)

def _bridge_scroll():
    _ctx["bridge"].scroll_down.emit()

def _burbuja(html):
    return _ctx["html_burbuja"](html)

def _cola_voz():
    return _ctx["cola_voz"]

def _base_path():
    return _ctx.get("base_path", os.getcwd())

def _config():
    return _ctx.get("config", {})

def _markdown(txt):
    fn = _ctx.get("markdown_a_html")
    return fn(txt) if fn else txt

def _limpiar(html):
    fn = _ctx.get("limpiar_html")
    return fn(html) if fn else re.sub(r"<[^>]+>", "", html)


# =============================================================================
# BASE DE DATOS SQLITE
# =============================================================================

_DB_FILE: str = ""


def _db_path() -> str:
    global _DB_FILE
    if not _DB_FILE:
        _DB_FILE = os.path.join(_base_path(), "jarvis_notas.db")
    return _DB_FILE


@contextmanager
def _get_conn():
    conn = sqlite3.connect(_db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _init_db():
    """Crea las tablas si no existen."""
    with _get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS notas (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                titulo    TEXT    NOT NULL DEFAULT '',
                contenido TEXT    NOT NULL DEFAULT '',
                creada    TEXT    NOT NULL,
                editada   TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS alarmas (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                hora      TEXT    NOT NULL,
                etiqueta  TEXT    NOT NULL DEFAULT '',
                repetir   TEXT,
                activa    INTEGER NOT NULL DEFAULT 1,
                creada    TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS recordatorios (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                texto       TEXT    NOT NULL,
                fecha_hora  TEXT    NOT NULL,
                completado  INTEGER NOT NULL DEFAULT 0,
                creado      TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS memoria_sesion (
                clave       TEXT    PRIMARY KEY,
                valor       TEXT    NOT NULL,
                categoria   TEXT    NOT NULL DEFAULT 'general',
                origen      TEXT    NOT NULL DEFAULT 'usuario',
                actualizado TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS contactos_confianza (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre    TEXT NOT NULL UNIQUE,
                destino   TEXT NOT NULL,
                canal     TEXT NOT NULL DEFAULT 'correo',
                correo    TEXT NOT NULL DEFAULT '',
                telefono  TEXT NOT NULL DEFAULT '',
                creado    TEXT NOT NULL
            );

                CREATE TABLE IF NOT EXISTS rutinas (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    nombre      TEXT NOT NULL UNIQUE,
                    acciones    TEXT NOT NULL,
                    activa      INTEGER NOT NULL DEFAULT 1,
                    proxima     TEXT,
                    creada      TEXT NOT NULL,
                    ultima      TEXT
                );

                CREATE TABLE IF NOT EXISTS rutinas_log (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    rutina_id   INTEGER NOT NULL,
                    accion      TEXT NOT NULL,
                    ejecutada   TEXT NOT NULL
                );
        """)
        columnas_contactos = {row[1] for row in conn.execute("PRAGMA table_info(contactos_confianza)")}
        for columna, sentencia in {
            "correo": "ALTER TABLE contactos_confianza ADD COLUMN correo TEXT NOT NULL DEFAULT ''",
            "telefono": "ALTER TABLE contactos_confianza ADD COLUMN telefono TEXT NOT NULL DEFAULT ''",
        }.items():
            if columna not in columnas_contactos:
                conn.execute(sentencia)
        columnas_memoria = {row[1] for row in conn.execute("PRAGMA table_info(memoria_sesion)")}
        for columna, sentencia in {
            "categoria": "ALTER TABLE memoria_sesion ADD COLUMN categoria TEXT NOT NULL DEFAULT 'general'",
            "origen": "ALTER TABLE memoria_sesion ADD COLUMN origen TEXT NOT NULL DEFAULT 'usuario'",
        }.items():
            if columna not in columnas_memoria:
                conn.execute(sentencia)
        conn.execute(
            """UPDATE contactos_confianza SET correo=destino
               WHERE correo='' AND canal='correo' AND destino LIKE '%@%'"""
        )
        # Migración ligera para instalaciones que ya tienen la base creada.
        columnas = {row[1] for row in conn.execute("PRAGMA table_info(recordatorios)")}
        migraciones = {
            "acompanamiento": "ALTER TABLE recordatorios ADD COLUMN acompanamiento INTEGER NOT NULL DEFAULT 0",
            "categoria": "ALTER TABLE recordatorios ADD COLUMN categoria TEXT NOT NULL DEFAULT ''",
            "intentos": "ALTER TABLE recordatorios ADD COLUMN intentos INTEGER NOT NULL DEFAULT 0",
            "max_intentos": "ALTER TABLE recordatorios ADD COLUMN max_intentos INTEGER NOT NULL DEFAULT 3",
            "intervalo_minutos": "ALTER TABLE recordatorios ADD COLUMN intervalo_minutos INTEGER NOT NULL DEFAULT 5",
        }
        for columna, sentencia in migraciones.items():
            if columna not in columnas:
                conn.execute(sentencia)


# =============================================================================
# 1. NOTAS
# =============================================================================

def nota_crear(contenido: str, titulo: str = "", chat_widget=None):
    """Crea una nota nueva. Si no hay título genera uno automático."""
    ahora = datetime.now().isoformat(timespec="seconds")
    if not titulo:
        # Primera línea como título (máx 50 chars)
        primera = contenido.strip().split("\n")[0][:50]
        titulo  = primera if primera else f"Nota {ahora[:10]}"

    with _get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO notas (titulo, contenido, creada, editada) VALUES (?,?,?,?)",
            (titulo, contenido.strip(), ahora, ahora)
        )
        nid = cur.lastrowid

    html = (
        f'<p style="color:#4db8ff;font-weight:bold;">📝 Nota guardada</p>'
        f'<p style="color:#ccd6f6;font-size:13px;"><b>#{nid}</b> — {titulo}</p>'
        f'<p style="color:#8899bb;font-size:12px;">{ahora[:16].replace("T"," ")}</p>'
    )
    _bridge_html(_burbuja(html))
    _bridge_scroll()
    _hablar(f"Nota guardada: {titulo}", chat_widget)
    return nid


def nota_leer(id: int = None, titulo: str = "", chat_widget=None):
    """Lee una nota específica o lista todas."""
    with _get_conn() as conn:
        if id:
            rows = conn.execute("SELECT * FROM notas WHERE id=?", (id,)).fetchall()
        elif titulo:
            rows = conn.execute(
                "SELECT * FROM notas WHERE titulo LIKE ?",
                (f"%{titulo}%",)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM notas ORDER BY editada DESC LIMIT 20"
            ).fetchall()

    if not rows:
        _hablar("No encontré notas.", chat_widget)
        return

    if len(rows) == 1:
        n = rows[0]
        contenido_html = _markdown(n["contenido"])
        html = (
            f'<p style="color:#4db8ff;font-weight:bold;">📝 #{n["id"]} — {n["titulo"]}</p>'
            f'<div style="color:#ccd6f6;font-size:13px;">{contenido_html}</div>'
            f'<p style="color:#556677;font-size:11px;">Creada: {n["creada"][:16].replace("T"," ")} · '
            f'Editada: {n["editada"][:16].replace("T"," ")}</p>'
        )
        _bridge_html(_burbuja(html))
        _bridge_scroll()
        _hablar(f"Nota {n['titulo']}", chat_widget)
    else:
        filas = "".join(
            f'<tr>'
            f'<td style="color:#4db8ff;padding:3px 10px;">#{r["id"]}</td>'
            f'<td style="color:#ccd6f6;padding:3px 8px;">{r["titulo"][:60]}</td>'
            f'<td style="color:#8899bb;font-size:11px;padding:3px 8px;">{r["editada"][:10]}</td>'
            f'</tr>'
            for r in rows
        )
        html = (
            f'<p style="color:#4db8ff;font-weight:bold;">📝 Notas ({len(rows)})</p>'
            f'<table cellspacing="2">{filas}</table>'
        )
        _bridge_html(_burbuja(html))
        _bridge_scroll()
        _hablar(f"Tienes {len(rows)} notas.", chat_widget)


def nota_buscar(termino: str, chat_widget=None):
    """Busca notas por título o contenido."""
    like = f"%{termino}%"
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM notas WHERE titulo LIKE ? OR contenido LIKE ? ORDER BY editada DESC",
            (like, like)
        ).fetchall()

    if not rows:
        _hablar(f"No encontré notas sobre '{termino}'.", chat_widget)
        return

    filas = "".join(
        f'<tr>'
        f'<td style="color:#4db8ff;padding:3px 10px;">#{r["id"]}</td>'
        f'<td style="color:#ccd6f6;padding:3px 8px;">{r["titulo"][:60]}</td>'
        f'</tr>'
        for r in rows
    )
    html = (
        f'<p style="color:#4db8ff;font-weight:bold;">🔍 "{termino}" — {len(rows)} resultado(s)</p>'
        f'<table cellspacing="2">{filas}</table>'
    )
    _bridge_html(_burbuja(html))
    _bridge_scroll()
    _hablar(f"Encontré {len(rows)} notas sobre {termino}.", chat_widget)


def nota_editar(id_o_titulo: str, contenido: str = None, titulo_nuevo: str = None, chat_widget=None):
    """Edita el título o contenido de una nota."""
    ahora = datetime.now().isoformat(timespec="seconds")
    with _get_conn() as conn:
        # Buscar por ID o título
        try:
            nid = int(id_o_titulo)
            row = conn.execute("SELECT * FROM notas WHERE id=?", (nid,)).fetchone()
        except ValueError:
            row = conn.execute(
                "SELECT * FROM notas WHERE titulo LIKE ? LIMIT 1",
                (f"%{id_o_titulo}%",)
            ).fetchone()

        if not row:
            _hablar(f"No encontré la nota '{id_o_titulo}'.", chat_widget)
            return

        nuevo_titulo    = titulo_nuevo  if titulo_nuevo  else row["titulo"]
        nuevo_contenido = contenido     if contenido     else row["contenido"]
        conn.execute(
            "UPDATE notas SET titulo=?, contenido=?, editada=? WHERE id=?",
            (nuevo_titulo, nuevo_contenido, ahora, row["id"])
        )

    _hablar(f"Nota '{nuevo_titulo}' actualizada.", chat_widget)
    html = (
        f'<p style="color:#4db8ff;">✏️ Nota actualizada: <b>{nuevo_titulo}</b></p>'
    )
    _bridge_html(_burbuja(html))
    _bridge_scroll()


def nota_eliminar(id_o_titulo: str, chat_widget=None):
    """Elimina una nota por ID o título."""
    with _get_conn() as conn:
        try:
            nid = int(id_o_titulo)
            row = conn.execute("SELECT titulo FROM notas WHERE id=?", (nid,)).fetchone()
            conn.execute("DELETE FROM notas WHERE id=?", (nid,))
        except ValueError:
            row = conn.execute(
                "SELECT id, titulo FROM notas WHERE titulo LIKE ? LIMIT 1",
                (f"%{id_o_titulo}%",)
            ).fetchone()
            if row:
                conn.execute("DELETE FROM notas WHERE id=?", (row["id"],))

    nombre = row["titulo"] if row else id_o_titulo
    _hablar(f"Nota '{nombre}' eliminada.", chat_widget)
    html = f'<p style="color:#ff6b6b;">🗑️ Nota eliminada: {nombre}</p>'
    _bridge_html(_burbuja(html))
    _bridge_scroll()


# =============================================================================
# 2. ALARMAS
# =============================================================================

def _parsear_hora_alarma(hora_str: str) -> Optional[datetime]:
    """
    Convierte 'HH:MM', 'en X minutos', 'en X horas' a datetime futuro.
    Devuelve None si no puede parsear.
    """
    hora_str = hora_str.strip().lower()
    ahora    = datetime.now()

    # "en X minutos"
    m = re.search(r"en\s+(\d+)\s+minuto", hora_str)
    if m:
        return ahora + timedelta(minutes=int(m.group(1)))

    # "en X horas"
    m = re.search(r"en\s+(\d+)\s+hora", hora_str)
    if m:
        return ahora + timedelta(hours=int(m.group(1)))

    # "HH:MM" o "H:MM"
    m = re.search(r"(\d{1,2}):(\d{2})", hora_str)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        dt = ahora.replace(hour=h, minute=mi, second=0, microsecond=0)
        if dt <= ahora:
            dt += timedelta(days=1)
        return dt

    return None


def alarma_crear(hora_str: str, etiqueta: str = "", repetir: str = None, chat_widget=None):
    """
    Crea una alarma.
    hora_str : "07:30" | "en 20 minutos" | "en 2 horas"
    repetir  : "diaria" | "semanal" | None
    """
    dt = _parsear_hora_alarma(hora_str)
    if not dt:
        _hablar(f"No entendí la hora '{hora_str}'. Di algo como '07:30' o 'en 20 minutos'.", chat_widget)
        return

    ahora = datetime.now().isoformat(timespec="seconds")
    if not etiqueta:
        etiqueta = "Alarma"
    hora_iso = dt.isoformat(timespec="seconds")

    with _get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO alarmas (hora, etiqueta, repetir, activa, creada) VALUES (?,?,?,1,?)",
            (hora_iso, etiqueta, repetir, ahora)
        )
        aid = cur.lastrowid

    diferencia = dt - datetime.now()
    minutos    = int(diferencia.total_seconds() // 60)
    msg_tiempo = f"en {minutos} min" if minutos < 60 else f"a las {dt.strftime('%H:%M')}"

    html = (
        f'<p style="color:#ffd700;font-weight:bold;">⏰ Alarma #{aid} programada</p>'
        f'<p style="color:#ccd6f6;font-size:13px;">'
        f'<b>{etiqueta}</b> — {dt.strftime("%H:%M")} ({msg_tiempo})'
        f'{"<br>🔁 " + repetir if repetir else ""}'
        f'</p>'
    )
    _bridge_html(_burbuja(html))
    _bridge_scroll()
    _hablar(f"Alarma '{etiqueta}' programada para las {dt.strftime('%H:%M')}.", chat_widget)


def alarma_listar(chat_widget=None):
    """Lista todas las alarmas activas."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM alarmas WHERE activa=1 ORDER BY hora"
        ).fetchall()

    if not rows:
        _hablar("No tienes alarmas activas.", chat_widget)
        return

    filas = "".join(
        f'<tr>'
        f'<td style="color:#ffd700;padding:3px 10px;">#{r["id"]}</td>'
        f'<td style="color:#ccd6f6;padding:3px 8px;">{r["etiqueta"]}</td>'
        f'<td style="color:#8899bb;font-size:12px;padding:3px 8px;">'
        f'{r["hora"][11:16]}'
        f'{"  🔁 " + r["repetir"] if r["repetir"] else ""}'
        f'</td>'
        f'</tr>'
        for r in rows
    )
    html = (
        f'<p style="color:#ffd700;font-weight:bold;">⏰ Alarmas activas ({len(rows)})</p>'
        f'<table cellspacing="2">{filas}</table>'
    )
    _bridge_html(_burbuja(html))
    _bridge_scroll()
    _hablar(f"Tienes {len(rows)} alarma(s) activa(s).", chat_widget)


def alarma_eliminar(id_o_etiqueta: str, chat_widget=None):
    """Desactiva (elimina lógicamente) una alarma."""
    with _get_conn() as conn:
        try:
            aid = int(id_o_etiqueta)
            row = conn.execute("SELECT etiqueta FROM alarmas WHERE id=?", (aid,)).fetchone()
            conn.execute("UPDATE alarmas SET activa=0 WHERE id=?", (aid,))
        except ValueError:
            row = conn.execute(
                "SELECT id, etiqueta FROM alarmas WHERE etiqueta LIKE ? AND activa=1 LIMIT 1",
                (f"%{id_o_etiqueta}%",)
            ).fetchone()
            if row:
                conn.execute("UPDATE alarmas SET activa=0 WHERE id=?", (row["id"],))

    nombre = row["etiqueta"] if row else id_o_etiqueta
    _hablar(f"Alarma '{nombre}' eliminada.", chat_widget)
    html = f'<p style="color:#ff6b6b;">🗑️ Alarma eliminada: {nombre}</p>'
    _bridge_html(_burbuja(html))
    _bridge_scroll()


def _disparar_alarma(alarma: sqlite3.Row):
    """Reproduce la alarma y avisa al usuario."""
    etiqueta = alarma["etiqueta"] or "Alarma"
    _hablar(f"¡{etiqueta}! Es la hora de tu alarma.", None)

    # Intentar reproducir sonido del sistema
    try:
        import winsound
        for _ in range(3):
            winsound.Beep(1000, 500)
            time.sleep(0.3)
    except Exception:
        pass

    html = (
        f'<p style="color:#ffd700;font-size:15px;font-weight:bold;">'
        f'⏰ ¡ALARMA! {etiqueta}</p>'
        f'<p style="color:#ccd6f6;font-size:13px;">{datetime.now().strftime("%H:%M")}</p>'
    )
    _bridge_html(_burbuja(html))
    _bridge_scroll()

    # Reprogramar si es recurrente
    if alarma["repetir"] == "diaria":
        nueva_hora = datetime.fromisoformat(alarma["hora"]) + timedelta(days=1)
        with _get_conn() as conn:
            conn.execute(
                "UPDATE alarmas SET hora=? WHERE id=?",
                (nueva_hora.isoformat(timespec="seconds"), alarma["id"])
            )
    elif alarma["repetir"] == "semanal":
        nueva_hora = datetime.fromisoformat(alarma["hora"]) + timedelta(weeks=1)
        with _get_conn() as conn:
            conn.execute(
                "UPDATE alarmas SET hora=? WHERE id=?",
                (nueva_hora.isoformat(timespec="seconds"), alarma["id"])
            )
    else:
        # Una sola vez → desactivar
        with _get_conn() as conn:
            conn.execute("UPDATE alarmas SET activa=0 WHERE id=?", (alarma["id"],))


# =============================================================================
# 3. RECORDATORIOS
# =============================================================================

def _parsear_fecha_hora(fecha_hora_str: str, minutos: int = None) -> Optional[datetime]:
    """Convierte texto a datetime futuro."""
    ahora = datetime.now()

    if minutos:
        return ahora + timedelta(minutes=minutos)

    if not fecha_hora_str:
        return None

    s = fecha_hora_str.strip().lower()

    # "en X minutos"
    m = re.search(r"en\s+(\d+)\s+minuto", s)
    if m:
        return ahora + timedelta(minutes=int(m.group(1)))

    # "en X horas"
    m = re.search(r"en\s+(\d+)\s+hora", s)
    if m:
        return ahora + timedelta(hours=int(m.group(1)))

    # ISO o "YYYY-MM-DD HH:MM"
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass

    # "HH:MM" sólo hora → hoy o mañana
    m = re.search(r"(\d{1,2}):(\d{2})", s)
    if m:
        dt = ahora.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
        if dt <= ahora:
            dt += timedelta(days=1)
        return dt

    return None


def recordatorio_crear(texto: str, fecha_hora_str: str = "", minutos: int = None,
                       acompanamiento: bool = False, categoria: str = "",
                       max_intentos: int = 3, intervalo_minutos: int = 5, chat_widget=None):
    """
    Crea un recordatorio.
    texto         : qué decir cuando llegue la hora
    fecha_hora_str: "2025-06-01 09:00" | "en 30 minutos" | "15:00"
    minutos       : alternativa directa si viene como int
    """
    dt = _parsear_fecha_hora(fecha_hora_str, minutos)
    if not dt:
        _hablar("Dime a qué hora quieres el recordatorio.", chat_widget)
        return

    ahora   = datetime.now().isoformat(timespec="seconds")
    dt_iso  = dt.isoformat(timespec="seconds")

    acompanamiento = bool(acompanamiento)
    categoria = str(categoria or "").strip()[:40]
    try:
        max_intentos = max(1, min(int(max_intentos), 10))
    except (TypeError, ValueError):
        max_intentos = 3
    try:
        intervalo_minutos = max(1, min(int(intervalo_minutos), 120))
    except (TypeError, ValueError):
        intervalo_minutos = 5

    with _get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO recordatorios
               (texto, fecha_hora, completado, creado, acompanamiento, categoria,
                intentos, max_intentos, intervalo_minutos)
               VALUES (?,?,0,?,?,?,?,?,?)""",
            (texto.strip(), dt_iso, ahora, int(acompanamiento), categoria,
             0, max_intentos, intervalo_minutos)
        )
        rid = cur.lastrowid

    diferencia = dt - datetime.now()
    min_total  = int(diferencia.total_seconds() // 60)
    msg_tiempo = f"en {min_total} min" if min_total < 60 else f"el {dt.strftime('%d/%m a las %H:%M')}"

    html = (
        f'<p style="color:#7ec8e3;font-weight:bold;">🔔 Recordatorio #{rid}</p>'
        f'<p style="color:#ccd6f6;font-size:13px;">"{texto}"</p>'
        f'<p style="color:#8899bb;font-size:12px;">{msg_tiempo}</p>'
    )
    _bridge_html(_burbuja(html))
    _bridge_scroll()
    modo = " con seguimiento" if acompanamiento else ""
    _hablar(f"Recordatorio creado{modo}: {texto}. Te aviso {msg_tiempo}.", chat_widget)


def recordatorio_listar(chat_widget=None):
    """Lista recordatorios pendientes."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM recordatorios WHERE completado=0 ORDER BY fecha_hora"
        ).fetchall()

    if not rows:
        _hablar("No tienes recordatorios pendientes.", chat_widget)
        return

    filas = "".join(
        f'<tr>'
        f'<td style="color:#7ec8e3;padding:3px 10px;">#{r["id"]}</td>'
        f'<td style="color:#ccd6f6;padding:3px 8px;">{r["texto"][:60]}</td>'
        f'<td style="color:#8899bb;font-size:12px;padding:3px 8px;">'
        f'{r["fecha_hora"][11:16]} {r["fecha_hora"][:10]}'
        f'</td>'
        f'</tr>'
        for r in rows
    )
    html = (
        f'<p style="color:#7ec8e3;font-weight:bold;">🔔 Recordatorios ({len(rows)})</p>'
        f'<table cellspacing="2">{filas}</table>'
    )
    _bridge_html(_burbuja(html))
    _bridge_scroll()
    _hablar(f"Tienes {len(rows)} recordatorio(s) pendiente(s).", chat_widget)


def recordatorio_eliminar(id_o_texto: str, chat_widget=None):
    """Marca un recordatorio como completado."""
    with _get_conn() as conn:
        try:
            rid = int(id_o_texto)
            row = conn.execute("SELECT texto FROM recordatorios WHERE id=?", (rid,)).fetchone()
            conn.execute("UPDATE recordatorios SET completado=1 WHERE id=?", (rid,))
        except ValueError:
            row = conn.execute(
                "SELECT id, texto FROM recordatorios WHERE texto LIKE ? AND completado=0 LIMIT 1",
                (f"%{id_o_texto}%",)
            ).fetchone()
            if row:
                conn.execute("UPDATE recordatorios SET completado=1 WHERE id=?", (row["id"],))

    nombre = row["texto"][:50] if row else id_o_texto
    _hablar(f"Recordatorio '{nombre}' eliminado.", chat_widget)
    html = f'<p style="color:#ff6b6b;">🗑️ Recordatorio eliminado: {nombre}</p>'
    _bridge_html(_burbuja(html))
    _bridge_scroll()


def recordatorio_confirmar(id_o_texto: str = "", chat_widget=None):
    """Confirma un recordatorio de acompañamiento pendiente."""
    with _get_conn() as conn:
        if id_o_texto:
            try:
                row = conn.execute(
                    "SELECT * FROM recordatorios WHERE id=? AND completado=0 AND acompanamiento=1",
                    (int(id_o_texto),)
                ).fetchone()
            except (TypeError, ValueError):
                row = conn.execute(
                    "SELECT * FROM recordatorios WHERE texto LIKE ? AND completado=0 AND acompanamiento=1 LIMIT 1",
                    (f"%{id_o_texto}%",)
                ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM recordatorios WHERE completado=0 AND acompanamiento=1 ORDER BY fecha_hora LIMIT 1"
            ).fetchone()

        if not row:
            _hablar("No encontré un recordatorio de acompañamiento pendiente para confirmar.", chat_widget)
            return
        conn.execute("UPDATE recordatorios SET completado=1 WHERE id=?", (row["id"],))

    texto = row["texto"]
    html = (
        f'<p style="color:#a8e6cf;font-size:15px;font-weight:bold;">✓ Recordatorio confirmado</p>'
        f'<p style="color:#ccd6f6;font-size:14px;">{texto}</p>'
    )
    _bridge_html(_burbuja(html))
    _bridge_scroll()
    _hablar(f"Confirmado: {texto}.", chat_widget)


def acompanamiento_resumen(chat_widget=None):
    """Resume la agenda local del día y los seguimientos pendientes."""
    ahora = datetime.now()
    inicio = ahora.replace(hour=0, minute=0, second=0, microsecond=0).isoformat(timespec="seconds")
    fin = (ahora + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).isoformat(timespec="seconds")

    with _get_conn() as conn:
        recordatorios = conn.execute(
            """SELECT * FROM recordatorios
               WHERE completado=0 AND fecha_hora>=? AND fecha_hora<?
               ORDER BY fecha_hora LIMIT 20""",
            (inicio, fin)
        ).fetchall()
        alarmas = conn.execute(
            """SELECT * FROM alarmas
               WHERE activa=1 AND hora>=? AND hora<?
               ORDER BY hora LIMIT 20""",
            (inicio, fin)
        ).fetchall()

    if not recordatorios and not alarmas:
        _hablar("No tienes recordatorios ni alarmas pendientes para hoy.", chat_widget)
        return

    bloques = [f'<p style="color:#7ec8e3;font-weight:bold;">📅 Resumen de hoy ({ahora.strftime("%d/%m")})</p>']
    voz = []
    if recordatorios:
        items = []
        for row in recordatorios:
            marca = " · requiere confirmación" if row["acompanamiento"] else ""
            items.append(
                f'<li style="color:#ccd6f6;">{row["fecha_hora"][11:16]} — '
                f'{row["texto"][:100]}{marca}</li>'
            )
            voz.append(f"a las {row['fecha_hora'][11:16]}: {row['texto']}")
        bloques.append('<p style="color:#7ec8e3;">🔔 Recordatorios</p><ul>' + ''.join(items) + '</ul>')
    if alarmas:
        items = [
            f'<li style="color:#ccd6f6;">{row["hora"][11:16]} — {row["etiqueta"]}</li>'
            for row in alarmas
        ]
        bloques.append('<p style="color:#ffd166;">⏰ Alarmas</p><ul>' + ''.join(items) + '</ul>')
        voz.extend(f"a las {row['hora'][11:16]}: {row['etiqueta']}" for row in alarmas)

    _bridge_html(_burbuja(''.join(bloques)))
    _bridge_scroll()
    total = len(recordatorios) + len(alarmas)
    detalle = '; '.join(voz[:4])
    _hablar(f"Tienes {total} pendientes hoy. {detalle}.", chat_widget)


def contacto_confianza_guardar(nombre: str, destino: str, canal: str = "correo",
                               chat_widget=None, correo: str = "", telefono: str = ""):
    """Guarda un contacto autorizado para futuras alertas, sin enviar nada."""
    nombre = str(nombre or "").strip()[:80]
    destino = str(destino or "").strip()[:160]
    canal = str(canal or "correo").strip().lower()[:30]
    correo = str(correo or (destino if canal == "correo" else "")).strip()[:160]
    telefono = str(telefono or (destino if canal == "telefono" else "")).strip()[:40]
    if not destino:
        destino = correo or telefono
    if not nombre or not destino:
        _hablar("Necesito el nombre y el destino del contacto.", chat_widget)
        return
    ahora = datetime.now().isoformat(timespec="seconds")
    with _get_conn() as conn:
        conn.execute(
                """INSERT INTO contactos_confianza
                    (nombre, destino, canal, correo, telefono, creado)
                    VALUES (?,?,?,?,?,?)
                    ON CONFLICT(nombre) DO UPDATE SET destino=excluded.destino,
                    canal=excluded.canal, correo=excluded.correo, telefono=excluded.telefono""",
                (nombre, destino, canal, correo, telefono, ahora)
        )
    _hablar(f"Contacto de confianza guardado: {nombre}. Todavía no se enviará ningún mensaje.", chat_widget)
    _bridge_html(_burbuja(
        f'<p style="color:#a8e6cf;font-weight:bold;">Contacto guardado</p>'
        f'<p style="color:#ccd6f6;">{escape(nombre)} · canal preferido: {escape(canal)}</p>'
    ))
    _bridge_scroll()


def contactos_confianza_listar(chat_widget=None):
    with _get_conn() as conn:
        rows = conn.execute("SELECT * FROM contactos_confianza ORDER BY nombre").fetchall()
    if not rows:
        _hablar("No tienes contactos de confianza configurados.", chat_widget)
        return
    filas = ''.join(
        f'<tr><td style="color:#a8e6cf;padding:3px 10px;">{escape(row["nombre"])}</td>'
        f'<td style="color:#ccd6f6;padding:3px 8px;">{escape(row["correo"] or "-")}</td>'
        f'<td style="color:#ccd6f6;padding:3px 8px;">{escape(row["telefono"] or "-")}</td>'
        f'<td style="color:#ccd6f6;padding:3px 8px;">{escape(row["canal"])}</td></tr>'
        for row in rows
    )
    _bridge_html(_burbuja(
        f'<p style="color:#a8e6cf;font-weight:bold;">Contactos de confianza ({len(rows)})</p>'
        f'<table cellspacing="2">{filas}</table>'
    ))
    _bridge_scroll()
    _hablar(f"Tienes {len(rows)} contactos de confianza.", chat_widget)


def contacto_confianza_eliminar(nombre: str, chat_widget=None):
    nombre = str(nombre or "").strip()
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT nombre FROM contactos_confianza WHERE nombre LIKE ? LIMIT 1",
            (f"%{nombre}%",)
        ).fetchone()
        if row:
            conn.execute("DELETE FROM contactos_confianza WHERE nombre=?", (row["nombre"],))
    if not row:
        _hablar(f"No encontré el contacto '{nombre}'.", chat_widget)
        return
    _hablar(f"Contacto de confianza eliminado: {row['nombre']}.", chat_widget)


def contacto_confianza_obtener(nombre: str):
    """Devuelve un contacto de confianza por coincidencia de nombre."""
    nombre = str(nombre or "").strip()
    if not nombre:
        return None
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM contactos_confianza WHERE nombre LIKE ? LIMIT 1",
            (f"%{nombre}%",)
        ).fetchone()
    return dict(row) if row else None


def guardar_correo_contacto(destinatario: str, nombre: str = ""):
    """Actualiza o crea el correo de un contacto tras un envío confirmado."""
    destinatario = str(destinatario or "").strip()
    nombre = str(nombre or "").strip()[:80]
    if not destinatario or "@" not in destinatario:
        return
    with _get_conn() as conn:
        row = None
        if nombre:
            row = conn.execute(
                "SELECT id FROM contactos_confianza WHERE nombre LIKE ? LIMIT 1",
                (f"%{nombre}%",)
            ).fetchone()
        if row:
            conn.execute(
                "UPDATE contactos_confianza SET destino=?, correo=?, canal='correo' WHERE id=?",
                (destinatario, destinatario, row["id"])
            )
        else:
            conn.execute(
                "INSERT OR IGNORE INTO contactos_confianza (nombre, destino, canal, correo, telefono, creado) VALUES (?,?,?,?,?,?)",
                (nombre or destinatario, destinatario, "correo", destinatario, "", datetime.now().isoformat(timespec="seconds"))
            )


def _disparar_recordatorio(rec: sqlite3.Row):
    """Anuncia un recordatorio y conserva seguimiento si está activado."""
    texto = rec["texto"]
    es_acompanamiento = bool(rec["acompanamiento"])
    if es_acompanamiento:
        intento = int(rec["intentos"] or 0) + 1
        max_intentos = int(rec["max_intentos"] or 3)
        _hablar(f"Recordatorio importante: {texto}. Di 'ya lo hice' cuando lo hayas realizado.", None)
    else:
        intento = 1
        max_intentos = 1
        _hablar(f"Recordatorio: {texto}", None)
    html = (
        f'<p style="color:#7ec8e3;font-size:15px;font-weight:bold;">'
        f'🔔 RECORDATORIO</p>'
        f'<p style="color:#ccd6f6;font-size:14px;">{texto}</p>'
        f'{"<p style=\'color:#ffd166;font-size:12px;\'>Pendiente de confirmación (" + str(intento) + "/" + str(max_intentos) + ")</p>" if es_acompanamiento else ""}'
    )
    _bridge_html(_burbuja(html))
    _bridge_scroll()
    with _get_conn() as conn:
        if es_acompanamiento and intento < max_intentos:
            siguiente = datetime.now() + timedelta(minutes=int(rec["intervalo_minutos"] or 5))
            conn.execute(
                "UPDATE recordatorios SET fecha_hora=?, intentos=? WHERE id=?",
                (siguiente.isoformat(timespec="seconds"), intento, rec["id"])
            )
        elif es_acompanamiento:
            conn.execute("UPDATE recordatorios SET intentos=? WHERE id=?", (intento, rec["id"]))
        else:
            conn.execute("UPDATE recordatorios SET completado=1 WHERE id=?", (rec["id"],))


# =============================================================================
# 4. MONITOR (hilo de fondo — revisa alarmas y recordatorios cada 30 s)
# =============================================================================

_monitor_activo = False
_recordatorios_en_proceso = set()
_recordatorios_lock = threading.Lock()
_alarmas_en_proceso = set()
_alarmas_lock = threading.Lock()


def _arrancar_monitor():
    global _monitor_activo
    if _monitor_activo:
        return
    _monitor_activo = True
    threading.Thread(target=_loop_monitor, daemon=True).start()


def _loop_monitor():
    """Revisa cada 30 segundos si hay alarmas o recordatorios que disparar."""
    while True:
        try:
            _revisar_alarmas()
            _revisar_recordatorios()
            _revisar_rutinas()
        except Exception as e:
            print(f"[agent_notas monitor] {e}")
        time.sleep(5)


def _revisar_alarmas():
    ahora = datetime.now()
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM alarmas WHERE activa=1"
        ).fetchall()
    for r in rows:
        try:
            dt = datetime.fromisoformat(r["hora"])
            if dt <= ahora:
                with _alarmas_lock:
                    if r["id"] in _alarmas_en_proceso:
                        continue
                    _alarmas_en_proceso.add(r["id"])
                threading.Thread(target=_disparar_alarma_segura, args=(r,), daemon=True).start()
        except Exception:
            pass


def _disparar_alarma_segura(alarma: sqlite3.Row):
    try:
        _disparar_alarma(alarma)
    finally:
        with _alarmas_lock:
            _alarmas_en_proceso.discard(alarma["id"])


def _revisar_recordatorios():
    ahora = datetime.now()
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM recordatorios WHERE completado=0"
        ).fetchall()
    for r in rows:
        try:
            dt = datetime.fromisoformat(r["fecha_hora"])
            if dt <= ahora:
                with _recordatorios_lock:
                    if r["id"] in _recordatorios_en_proceso:
                        continue
                    _recordatorios_en_proceso.add(r["id"])
                threading.Thread(target=_disparar_recordatorio_seguro, args=(r,), daemon=True).start()
        except Exception:
            pass


def _disparar_recordatorio_seguro(rec: sqlite3.Row):
    try:
        _disparar_recordatorio(rec)
    finally:
        with _recordatorios_lock:
            _recordatorios_en_proceso.discard(rec["id"])


# =============================================================================
# 5. MEMORIA DE SESIÓN
# =============================================================================
#
# La memoria de sesión es un diccionario clave→valor persistido en SQLite.
# Jarvis la usa para guardar datos recogidos durante el chat:
#   · Resultados de búsquedas importantes
#   · Preferencias mencionadas por el usuario
#   · Hechos que el usuario quiere recordar
# =============================================================================

def memoria_guardar(clave: str, valor: str, categoria: str = "general",
                    origen: str = "usuario", chat_widget=None):
    """Guarda o actualiza un dato en la memoria de sesión."""
    ahora = datetime.now().isoformat(timespec="seconds")
    categoria = str(categoria or "general").strip().lower()[:40] or "general"
    origen = str(origen or "usuario").strip()[:80] or "usuario"
    with _get_conn() as conn:
        conn.execute(
            """INSERT INTO memoria_sesion (clave, valor, categoria, origen, actualizado)
               VALUES (?,?,?,?,?)
               ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor,
               categoria=excluded.categoria, origen=excluded.origen,
               actualizado=excluded.actualizado""",
            (clave.strip().lower(), valor.strip(), categoria, origen, ahora)
        )
    html = (
        f'<p style="color:#a8e6cf;font-size:12px;">'
        f'🧠 Memorizado: <b>{escape(clave)}</b> → {escape(valor[:80])}'
        f' <span style="color:#8899bb;">[{escape(categoria)}]</span></p>'
    )
    _bridge_html(_burbuja(html))
    _bridge_scroll()


def memoria_leer(clave: str = "", chat_widget=None):
    """Lee uno o todos los datos de la memoria."""
    with _get_conn() as conn:
        if clave:
            rows = conn.execute(
                "SELECT * FROM memoria_sesion WHERE clave LIKE ? ORDER BY actualizado DESC",
                (f"%{clave.lower()}%",)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM memoria_sesion ORDER BY actualizado DESC LIMIT 30"
            ).fetchall()

    if not rows:
        _hablar("No hay nada en mi memoria sobre ese tema.", chat_widget)
        return

    filas = "".join(
        f'<tr>'
        f'<td style="color:#a8e6cf;padding:3px 10px;">{escape(r["clave"])}</td>'
        f'<td style="color:#ccd6f6;padding:3px 8px;">{escape(r["valor"][:80])}</td>'
        f'<td style="color:#7ec8e3;font-size:11px;padding:3px 8px;">{escape(r["categoria"])}</td>'
        f'<td style="color:#667799;font-size:11px;padding:3px 8px;">{escape(r["origen"])}</td>'
        f'<td style="color:#556677;font-size:11px;padding:3px 8px;">{r["actualizado"][:10]}</td>'
        f'</tr>'
        for r in rows
    )
    html = (
        f'<p style="color:#a8e6cf;font-weight:bold;">🧠 Memoria ({len(rows)} entradas)</p>'
        f'<table cellspacing="2">{filas}</table>'
    )
    _bridge_html(_burbuja(html))
    _bridge_scroll()
    _hablar(f"Tengo {len(rows)} cosas en memoria.", chat_widget)


def memoria_buscar(termino: str, chat_widget=None):
    """Busca un término en claves, valores, categorías y origen."""
    termino = str(termino or "").strip().lower()
    if not termino:
        _hablar("Dime qué quieres buscar en la memoria.", chat_widget)
        return
    patron = f"%{termino}%"
    with _get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM memoria_sesion
               WHERE lower(clave) LIKE ? OR lower(valor) LIKE ?
                  OR lower(categoria) LIKE ? OR lower(origen) LIKE ?
               ORDER BY actualizado DESC LIMIT 30""",
            (patron, patron, patron, patron),
        ).fetchall()
    if not rows:
        _hablar(f"No encontré memoria relacionada con {termino}.", chat_widget)
        return
    filas = "".join(
        f'<tr><td style="color:#a8e6cf;padding:3px 8px;">{escape(r["clave"])}</td>'
        f'<td style="color:#ccd6f6;padding:3px 8px;">{escape(r["valor"][:100])}</td>'
        f'<td style="color:#7ec8e3;padding:3px 8px;">{escape(r["categoria"])}</td>'
        f'<td style="color:#556677;padding:3px 8px;">{r["actualizado"][:10]}</td></tr>'
        for r in rows
    )
    _bridge_html(_burbuja(
        f'<p style="color:#a8e6cf;font-weight:bold;">🔎 Memoria encontrada ({len(rows)})</p>'
        f'<table cellspacing="2">{filas}</table>'
    ))
    _bridge_scroll()
    _hablar(f"Encontré {len(rows)} recuerdos relacionados.", chat_widget)


def memoria_olvidar(termino: str, chat_widget=None):
    """Elimina entradas cuyo nombre o contenido coincide con el término."""
    termino = str(termino or "").strip().lower()
    if not termino:
        _hablar("Dime qué recuerdo quieres olvidar.", chat_widget)
        return
    patron = f"%{termino}%"
    with _get_conn() as conn:
        cur = conn.execute(
            """DELETE FROM memoria_sesion
               WHERE lower(clave) LIKE ? OR lower(valor) LIKE ?""",
            (patron, patron),
        )
        borrados = cur.rowcount
    mensaje = f"He olvidado {borrados} recuerdo(s) relacionado(s) con {termino}."
    _bridge_html(_burbuja(f'<p style="color:#ff9b9b;">🧠 {escape(mensaje)}</p>'))
    _bridge_scroll()
    _hablar(mensaje, chat_widget)


def memoria_resumir(chat_widget=None):
    """
    Genera un resumen inteligente de todo lo que Jarvis recuerda de la sesión actual.
    También incluye notas del día y recordatorios próximos.
    """
    ahora = datetime.now()
    hoy   = ahora.date().isoformat()

    with _get_conn() as conn:
        mem  = conn.execute(
            "SELECT * FROM memoria_sesion ORDER BY actualizado DESC LIMIT 20"
        ).fetchall()
        notas_hoy = conn.execute(
            "SELECT * FROM notas WHERE creada >= ? ORDER BY creada DESC LIMIT 5",
            (hoy,)
        ).fetchall()
        rec_pendientes = conn.execute(
            "SELECT * FROM recordatorios WHERE completado=0 ORDER BY fecha_hora LIMIT 5"
        ).fetchall()
        alarmas_activas = conn.execute(
            "SELECT * FROM alarmas WHERE activa=1 ORDER BY hora LIMIT 5"
        ).fetchall()

    bloques = []

    if mem:
        items = "".join(
            f'<li style="color:#ccd6f6;font-size:12px;">'
            f'<b>{r["clave"]}</b>: {r["valor"][:70]}</li>'
            for r in mem
        )
        bloques.append(
            f'<p style="color:#a8e6cf;font-weight:bold;">🧠 Lo que recuerdo</p>'
            f'<ul>{items}</ul>'
        )

    if notas_hoy:
        items = "".join(
            f'<li style="color:#ccd6f6;font-size:12px;">{r["titulo"][:60]}</li>'
            for r in notas_hoy
        )
        bloques.append(
            f'<p style="color:#4db8ff;font-weight:bold;">📝 Notas de hoy</p>'
            f'<ul>{items}</ul>'
        )

    if rec_pendientes:
        items = "".join(
            f'<li style="color:#ccd6f6;font-size:12px;">'
            f'{r["texto"][:55]} <span style="color:#556677;">({r["fecha_hora"][11:16]})</span>'
            f'</li>'
            for r in rec_pendientes
        )
        bloques.append(
            f'<p style="color:#7ec8e3;font-weight:bold;">🔔 Recordatorios pendientes</p>'
            f'<ul>{items}</ul>'
        )

    if alarmas_activas:
        items = "".join(
            f'<li style="color:#ccd6f6;font-size:12px;">'
            f'{r["etiqueta"]} — {r["hora"][11:16]}'
            f'{"  🔁 " + r["repetir"] if r["repetir"] else ""}'
            f'</li>'
            for r in alarmas_activas
        )
        bloques.append(
            f'<p style="color:#ffd700;font-weight:bold;">⏰ Alarmas activas</p>'
            f'<ul>{items}</ul>'
        )

    if not bloques:
        _hablar("Todavía no he guardado nada en memoria.", chat_widget)
        return

    html = "<hr style='border-color:#1a2740;'>".join(bloques)
    _bridge_html(_burbuja(html))
    _bridge_scroll()
    _hablar("Aquí tienes un resumen de lo que tengo en memoria.", chat_widget)


def memoria_limpiar(chat_widget=None):
    """Borra toda la memoria de sesión."""
    with _get_conn() as conn:
        conn.execute("DELETE FROM memoria_sesion")
    _hablar("Memoria de sesión limpiada.", chat_widget)
    html = '<p style="color:#ff6b6b;">🧠 Memoria de sesión borrada.</p>'
    _bridge_html(_burbuja(html))
    _bridge_scroll()


def memoria_exportar(chat_widget=None):
    """Exporta memoria estructurada a un JSON local para el usuario."""
    ahora = datetime.now()
    with _get_conn() as conn:
        filas = [dict(row) for row in conn.execute(
            "SELECT clave, valor, categoria, origen, actualizado FROM memoria_sesion ORDER BY actualizado DESC"
        ).fetchall()]
    perfil = _ctx.get("memoria_usuario", {})
    destino = os.path.join(_base_path(), f"jarvis_memoria_export_{ahora.strftime('%Y%m%d_%H%M%S')}.json")
    datos = {"exportado": ahora.isoformat(timespec="seconds"), "perfil": perfil, "memoria_sesion": filas}
    with open(destino, "w", encoding="utf-8") as f:
        json.dump(datos, f, indent=2, ensure_ascii=False)
    _bridge_html(_burbuja(f'<p style="color:#a8e6cf;">📦 Memoria exportada en {escape(destino)}</p>'))
    _bridge_scroll()
    _hablar("He exportado tu memoria a un archivo local.", chat_widget)


def memoria_borrar_todo(chat_widget=None):
    """Borra memoria de sesión y reinicia el perfil personal, sin tocar notas."""
    with _get_conn() as conn:
        conn.execute("DELETE FROM memoria_sesion")
    perfil = _ctx.get("memoria_usuario")
    guardar = _ctx.get("guardar_memoria")
    if isinstance(perfil, dict):
        for clave in ("nombre", "ciudad", "barrio", "trabajo", "colegio", "edad", "mascotas"):
            perfil[clave] = None
        perfil["hobbies"] = []
        perfil["familia"] = {}
        perfil["preferencias"] = {}
        perfil["resumen_contexto"] = ""
        perfil["ultimo_tema"] = None
        perfil["extras"] = {}
        if guardar:
            guardar(perfil)
    _bridge_html(_burbuja('<p style="color:#ff6b6b;">🧠 Memoria personal y de sesión borrada.</p>'))
    _bridge_scroll()
    _hablar("He borrado la memoria personal y de sesión. Las notas no fueron modificadas.", chat_widget)


# =============================================================================
# 6. RUTINAS DE PRODUCTIVIDAD
# =============================================================================

_RUTINAS_NO_DESTRUCTIVAS = {
    "abrir_app", "minimizar_app", "maximizar_app", "subir_volumen",
    "bajar_volumen", "mute", "abrir_url", "modo",
}


def _rutina_acciones(params):
    acciones = params.get("acciones", []) if isinstance(params, dict) else []
    if isinstance(acciones, str):
        try:
            acciones = json.loads(acciones)
        except json.JSONDecodeError:
            acciones = []
    if not isinstance(acciones, list) or not acciones or len(acciones) > 20:
        return []
    validas = []
    for accion in acciones:
        if not isinstance(accion, dict):
            continue
        nombre = str(accion.get("accion", "")).strip()
        if nombre not in _RUTINAS_NO_DESTRUCTIVAS:
            continue
        validas.append({"accion": nombre, "params": accion.get("params", {}) or {}})
    return validas


def rutina_crear(nombre: str, acciones, chat_widget=None):
    acciones_validas = _rutina_acciones({"acciones": acciones})
    nombre = str(nombre or "").strip()[:80]
    if not nombre or not acciones_validas:
        _hablar("Necesito un nombre y al menos una acción segura para crear la rutina.", chat_widget)
        return
    ahora = datetime.now().isoformat(timespec="seconds")
    with _get_conn() as conn:
        conn.execute(
            """INSERT INTO rutinas (nombre, acciones, creada) VALUES (?,?,?)
               ON CONFLICT(nombre) DO UPDATE SET acciones=excluded.acciones,
               activa=1, creada=excluded.creada""",
            (nombre.lower(), json.dumps(acciones_validas, ensure_ascii=False), ahora),
        )
    _bridge_html(_burbuja(
        f'<p style="color:#7ec8e3;font-weight:bold;">⚙ Rutina guardada: {escape(nombre)}</p>'
        f'<p style="color:#8899bb;font-size:12px;">{len(acciones_validas)} acción(es) seguras</p>'
    ))
    _bridge_scroll()
    _hablar(f"Rutina {nombre} guardada. Puedes previsualizarla antes de ejecutarla.", chat_widget)


def _rutina_obtener(nombre: str):
    with _get_conn() as conn:
        row = conn.execute("SELECT * FROM rutinas WHERE lower(nombre) LIKE ?", (f"%{str(nombre).lower().strip()}%",)).fetchone()
    if not row:
        _hablar(f"No encontré la rutina {nombre}.", None)
        return None
    try:
        acciones = json.loads(row["acciones"])
    except (TypeError, json.JSONDecodeError):
        acciones = []
    return row, acciones


def rutina_listar(chat_widget=None):
    with _get_conn() as conn:
        rows = conn.execute("SELECT * FROM rutinas ORDER BY nombre").fetchall()
    if not rows:
        _hablar("No tienes rutinas guardadas.", chat_widget)
        return
    filas = "".join(
        f'<tr><td style="color:#7ec8e3;padding:4px 8px;">{escape(r["nombre"])}</td>'
        f'<td style="color:#ccd6f6;padding:4px 8px;">{len(json.loads(r["acciones"]))} acciones</td>'
        f'<td style="color:#a8e6cf;padding:4px 8px;">{"activa" if r["activa"] else "pausada"}</td>'
        f'<td style="color:#8899bb;padding:4px 8px;">{r["proxima"] or "manual"}</td></tr>'
        for r in rows
    )
    _bridge_html(_burbuja(f'<p style="color:#7ec8e3;font-weight:bold;">⚙ Rutinas</p><table>{filas}</table>'))
    _bridge_scroll()
    _hablar(f"Tienes {len(rows)} rutina(s).", chat_widget)


def rutina_previsualizar(nombre: str, chat_widget=None):
    resultado = _rutina_obtener(nombre)
    if not resultado:
        return
    row, acciones = resultado
    items = "".join(
        f'<li style="color:#ccd6f6;">{escape(a["accion"])}: {escape(json.dumps(a["params"], ensure_ascii=False))}</li>'
        for a in acciones
    )
    _bridge_html(_burbuja(
        f'<p style="color:#ffd166;font-weight:bold;">👁 Vista previa: {escape(row["nombre"])}</p>'
        f'<ol>{items}</ol><p style="color:#8899bb;font-size:12px;">Para ejecutar, di: ejecuta la rutina {escape(row["nombre"])}.</p>'
    ))
    _bridge_scroll()
    _hablar(f"Vista previa de {row['nombre']}: {len(acciones)} acciones. Confirma cuando quieras ejecutarla.", chat_widget)


def rutina_ejecutar(nombre: str, chat_widget=None):
    resultado = _rutina_obtener(nombre)
    if not resultado:
        return
    row, acciones = resultado
    ejecutar = _ctx.get("ejecutar_accion")
    if not ejecutar:
        _hablar("El motor de acciones todavía no está disponible.", chat_widget)
        return
    for accion in acciones:
        ejecutar(accion, chat_widget)
        _registrar_rutina(row["id"], accion["accion"])
    with _get_conn() as conn:
        conn.execute("UPDATE rutinas SET ultima=? WHERE id=?", (datetime.now().isoformat(timespec="seconds"), row["id"]))
    _hablar(f"Rutina {row['nombre']} ejecutada.", chat_widget)


def rutina_programar(nombre: str, fecha_hora: str, chat_widget=None):
    resultado = _rutina_obtener(nombre)
    if not resultado:
        return
    dt = _parsear_fecha_hora(fecha_hora)
    if not dt:
        _hablar("Indica una hora válida, por ejemplo 18:30 o en 20 minutos.", chat_widget)
        return
    row, _ = resultado
    with _get_conn() as conn:
        conn.execute("UPDATE rutinas SET proxima=?, activa=1 WHERE id=?", (dt.isoformat(timespec="seconds"), row["id"]))
    _hablar(f"Rutina {row['nombre']} programada para las {dt.strftime('%d/%m a las %H:%M')}.", chat_widget)


def rutina_pausar(nombre: str, pausar: bool = True, chat_widget=None):
    resultado = _rutina_obtener(nombre)
    if not resultado:
        return
    row, _ = resultado
    with _get_conn() as conn:
        conn.execute("UPDATE rutinas SET activa=? WHERE id=?", (0 if pausar else 1, row["id"]))
    estado = "pausada" if pausar else "reanudada"
    _hablar(f"Rutina {row['nombre']} {estado}.", chat_widget)


def rutina_historial(nombre: str, chat_widget=None):
    resultado = _rutina_obtener(nombre)
    if not resultado:
        return
    row, _ = resultado
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT accion, ejecutada FROM rutinas_log WHERE rutina_id=? ORDER BY ejecutada DESC LIMIT 30",
            (row["id"],),
        ).fetchall()
    if not rows:
        _hablar(f"La rutina {row['nombre']} todavía no tiene ejecuciones registradas.", chat_widget)
        return
    items = "".join(f'<li style="color:#ccd6f6;">{escape(r["accion"])} — {r["ejecutada"]}</li>' for r in rows)
    _bridge_html(_burbuja(f'<p style="color:#7ec8e3;font-weight:bold;">📋 Historial: {escape(row["nombre"])}</p><ul>{items}</ul>'))
    _bridge_scroll()
    _hablar(f"Hay {len(rows)} acciones registradas en {row['nombre']}.", chat_widget)


def _revisar_rutinas():
    ahora = datetime.now()
    with _get_conn() as conn:
        rows = conn.execute("SELECT * FROM rutinas WHERE activa=1 AND proxima IS NOT NULL").fetchall()
    pendientes = []
    for row in rows:
        try:
            if datetime.fromisoformat(row["proxima"]) <= ahora:
                pendientes.append(row)
        except Exception as exc:
            print(f"[Rutina] Fecha inválida en {row['nombre']}: {exc}")

    for row in pendientes:
        try:
            with _get_conn() as conn:
                conn.execute("UPDATE rutinas SET proxima=NULL, ultima=? WHERE id=?", (ahora.isoformat(timespec="seconds"), row["id"]))
            acciones = json.loads(row["acciones"])
            ejecutar = _ctx.get("ejecutar_accion")
            if ejecutar:
                for accion in acciones:
                    ejecutar(accion, None)
                    _registrar_rutina(row["id"], accion["accion"])
        except Exception as exc:
            print(f"[Rutina] Error ejecutando {row['nombre']}: {exc}")


def _registrar_rutina(rutina_id: int, accion: str):
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO rutinas_log (rutina_id, accion, ejecutada) VALUES (?,?,?)",
            (rutina_id, accion, datetime.now().isoformat(timespec="seconds")),
        )


# =============================================================================
# FUNCIÓN PRINCIPAL DEL AGENTE
# =============================================================================

def ejecutar(accion: str, params: dict, chat_widget=None) -> bool:
    """
    Punto de entrada único desde dispatcher.py.
    Devuelve True si procesó la acción.
    """
    p = params or {}

    # ── Notas ────────────────────────────────────────────────────────────────
    if accion == "nota_crear":
        nota_crear(
            contenido=p.get("contenido", ""),
            titulo=p.get("titulo", ""),
            chat_widget=chat_widget,
        )
        return True

    if accion == "nota_leer":
        nota_leer(
            id=p.get("id"),
            titulo=p.get("titulo", ""),
            chat_widget=chat_widget,
        )
        return True

    if accion == "nota_buscar":
        nota_buscar(p.get("termino", ""), chat_widget)
        return True

    if accion == "nota_editar":
        nota_editar(
            id_o_titulo=str(p.get("id") or p.get("titulo", "")),
            contenido=p.get("contenido"),
            titulo_nuevo=p.get("titulo_nuevo"),
            chat_widget=chat_widget,
        )
        return True

    if accion == "nota_eliminar":
        nota_eliminar(
            id_o_titulo=str(p.get("id") or p.get("titulo", "")),
            chat_widget=chat_widget,
        )
        return True

    # ── Alarmas ──────────────────────────────────────────────────────────────
    if accion == "alarma_crear":
        alarma_crear(
            hora_str=p.get("hora", ""),
            etiqueta=p.get("etiqueta", ""),
            repetir=p.get("repetir"),
            chat_widget=chat_widget,
        )
        return True

    if accion == "alarma_listar":
        alarma_listar(chat_widget)
        return True

    if accion == "alarma_eliminar":
        alarma_eliminar(
            id_o_etiqueta=str(p.get("id") or p.get("etiqueta", "")),
            chat_widget=chat_widget,
        )
        return True

    # ── Recordatorios ────────────────────────────────────────────────────────
    if accion == "recordatorio_crear":
        recordatorio_crear(
            texto=p.get("texto", ""),
            fecha_hora_str=p.get("fecha_hora", ""),
            minutos=p.get("minutos"),
            acompanamiento=p.get("acompanamiento", False),
            categoria=p.get("categoria", ""),
            max_intentos=p.get("max_intentos", 3),
            intervalo_minutos=p.get("intervalo_minutos", 5),
            chat_widget=chat_widget,
        )
        return True

    if accion == "recordatorio_listar":
        recordatorio_listar(chat_widget)
        return True

    if accion == "recordatorio_eliminar":
        recordatorio_eliminar(
            id_o_texto=str(p.get("id") or p.get("texto", "")),
            chat_widget=chat_widget,
        )
        return True

    if accion == "recordatorio_confirmar":
        recordatorio_confirmar(
            id_o_texto=str(p.get("id") or p.get("texto", "")),
            chat_widget=chat_widget,
        )
        return True

    if accion == "acompanamiento_resumen":
        acompanamiento_resumen(chat_widget)
        return True

    if accion == "contacto_confianza_guardar":
        contacto_confianza_guardar(
            p.get("nombre", ""), p.get("destino", ""), p.get("canal", "correo"), chat_widget
        )
        return True

    if accion == "contactos_confianza_listar":
        contactos_confianza_listar(chat_widget)
        return True

    if accion == "contacto_confianza_eliminar":
        contacto_confianza_eliminar(p.get("nombre", ""), chat_widget)
        return True

    # ── Memoria de sesión ────────────────────────────────────────────────────
    if accion == "memoria_guardar":
        memoria_guardar(
            clave=p.get("clave", ""),
            valor=p.get("valor", ""),
            categoria=p.get("categoria", "general"),
            origen=p.get("origen", "usuario"),
            chat_widget=chat_widget,
        )
        return True

    if accion == "memoria_leer":
        memoria_leer(p.get("clave", ""), chat_widget)
        return True

    if accion == "memoria_resumir":
        memoria_resumir(chat_widget)
        return True

    if accion == "memoria_buscar":
        memoria_buscar(p.get("termino", ""), chat_widget)
        return True

    if accion == "memoria_olvidar":
        memoria_olvidar(p.get("termino", ""), chat_widget)
        return True

    if accion == "memoria_exportar":
        memoria_exportar(chat_widget)
        return True

    if accion == "memoria_limpiar":
        memoria_limpiar(chat_widget)
        return True

    if accion == "memoria_borrar_todo":
        memoria_borrar_todo(chat_widget)
        return True

    if accion == "rutina_crear":
        rutina_crear(p.get("nombre", ""), p.get("acciones", []), chat_widget)
        return True
    if accion == "rutina_listar":
        rutina_listar(chat_widget)
        return True
    if accion == "rutina_previsualizar":
        rutina_previsualizar(p.get("nombre", ""), chat_widget)
        return True
    if accion == "rutina_ejecutar":
        rutina_ejecutar(p.get("nombre", ""), chat_widget)
        return True
    if accion == "rutina_programar":
        rutina_programar(p.get("nombre", ""), p.get("fecha_hora", ""), chat_widget)
        return True
    if accion == "rutina_pausar":
        rutina_pausar(p.get("nombre", ""), True, chat_widget)
        return True
    if accion == "rutina_reanudar":
        rutina_pausar(p.get("nombre", ""), False, chat_widget)
        return True
    if accion == "rutina_historial":
        rutina_historial(p.get("nombre", ""), chat_widget)
        return True

    print(f"[agent_notas] Acción desconocida: '{accion}'")
    return False
