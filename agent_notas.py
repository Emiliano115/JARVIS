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
#     "recordatorio_crear"    → params: {texto, fecha_hora?, minutos?}
#     "recordatorio_listar"   → params: {}
#     "recordatorio_eliminar" → params: {id | texto}
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


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


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
                actualizado TEXT    NOT NULL
            );
        """)


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


def recordatorio_crear(texto: str, fecha_hora_str: str = "", minutos: int = None, chat_widget=None):
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

    with _get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO recordatorios (texto, fecha_hora, completado, creado) VALUES (?,?,0,?)",
            (texto.strip(), dt_iso, ahora)
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
    _hablar(f"Recordatorio creado: {texto}. Te aviso {msg_tiempo}.", chat_widget)


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


def _disparar_recordatorio(rec: sqlite3.Row):
    """Anuncia el recordatorio y lo marca como completado."""
    texto = rec["texto"]
    _hablar(f"Recordatorio: {texto}", None)
    html = (
        f'<p style="color:#7ec8e3;font-size:15px;font-weight:bold;">'
        f'🔔 RECORDATORIO</p>'
        f'<p style="color:#ccd6f6;font-size:14px;">{texto}</p>'
    )
    _bridge_html(_burbuja(html))
    _bridge_scroll()
    with _get_conn() as conn:
        conn.execute("UPDATE recordatorios SET completado=1 WHERE id=?", (rec["id"],))


# =============================================================================
# 4. MONITOR (hilo de fondo — revisa alarmas y recordatorios cada 30 s)
# =============================================================================

_monitor_activo = False


def _arrancar_monitor():
    global _monitor_activo
    if _monitor_activo:
        return
    _monitor_activo = True
    threading.Thread(target=_loop_monitor, daemon=True).start()


def _loop_monitor():
    """Revisa cada 30 segundos si hay alarmas o recordatorios que disparar."""
    while True:
        time.sleep(30)
        try:
            _revisar_alarmas()
            _revisar_recordatorios()
        except Exception as e:
            print(f"[agent_notas monitor] {e}")


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
                threading.Thread(target=_disparar_alarma, args=(r,), daemon=True).start()
        except Exception:
            pass


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
                threading.Thread(target=_disparar_recordatorio, args=(r,), daemon=True).start()
        except Exception:
            pass


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

def memoria_guardar(clave: str, valor: str, chat_widget=None):
    """Guarda o actualiza un dato en la memoria de sesión."""
    ahora = datetime.now().isoformat(timespec="seconds")
    with _get_conn() as conn:
        conn.execute(
            """INSERT INTO memoria_sesion (clave, valor, actualizado)
               VALUES (?,?,?)
               ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor, actualizado=excluded.actualizado""",
            (clave.strip().lower(), valor.strip(), ahora)
        )
    html = (
        f'<p style="color:#a8e6cf;font-size:12px;">'
        f'🧠 Memorizado: <b>{clave}</b> → {valor[:80]}</p>'
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
        f'<td style="color:#a8e6cf;padding:3px 10px;">{r["clave"]}</td>'
        f'<td style="color:#ccd6f6;padding:3px 8px;">{r["valor"][:80]}</td>'
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

    # ── Memoria de sesión ────────────────────────────────────────────────────
    if accion == "memoria_guardar":
        memoria_guardar(
            clave=p.get("clave", ""),
            valor=p.get("valor", ""),
            chat_widget=chat_widget,
        )
        return True

    if accion == "memoria_leer":
        memoria_leer(p.get("clave", ""), chat_widget)
        return True

    if accion == "memoria_resumir":
        memoria_resumir(chat_widget)
        return True

    if accion == "memoria_limpiar":
        memoria_limpiar(chat_widget)
        return True

    print(f"[agent_notas] Acción desconocida: '{accion}'")
    return False
