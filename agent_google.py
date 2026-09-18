# =============================================================================
# agent_google.py — Agente de Google: Correo, Contactos, Calendario y Tareas
# =============================================================================
# Responsabilidades:
#   · Gmail: leer bandeja, buscar correos, enviar correos, eliminar correos
#   · Google Calendar: ver eventos, crear, editar, eliminar reuniones
#   · Google Tasks: ver, crear, editar, eliminar tareas
#   · Google People (Contactos): buscar contactos, obtener email/teléfono
#   · Google Drive: buscar archivos, abrir en el navegador
#
# Interfaz pública:
#   init(ctx)                                              → inyectar contexto
#   ejecutar(accion, params, chat_widget) -> bool          → punto de entrada
#
# Acciones del dispatcher:
#   Gmail:
#     "gmail_leer"     → params: {max_msgs?}
#     "gmail_buscar"   → params: {consulta}
#     "gmail_enviar"   → params: {destinatario, asunto, cuerpo}
#     "gmail_eliminar" → params: {consulta}
#
#   Calendario:
#     "ver_eventos"    → params: {}
#     "crear_evento"   → params: {nombre, fecha?, hora?}
#     "editar_evento"  → params: {nombre_buscar, nombre_nuevo?, fecha?, hora?}
#     "eliminar_evento"→ params: {nombre_buscar}
#
#   Tareas:
#     "ver_tareas"     → params: {}
#     "crear_tarea"    → params: {titulo, fecha?}
#     "editar_tarea"   → params: {titulo_buscar, titulo_nuevo?, fecha?}
#     "eliminar_tarea" → params: {titulo_buscar}
#
#   Contactos:
#     "buscar_contacto"→ params: {nombre}
#
#   Drive:
#     "drive_buscar"   → params: {consulta}
#
# Dependencias inyectadas via init(ctx):
#   hablar, cola_voz, bridge, html_burbuja,
#   obtener_credenciales, base_path, config,
#   quitar_tildes, formatear_fecha,
#   SERVIDOR_AUTH, SCOPES
# =============================================================================

from __future__ import annotations

import base64
import json
import os
import re
import threading
import time
import webbrowser
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from http.server import HTTPServer, BaseHTTPRequestHandler
from html import escape
from urllib.parse import urlparse, parse_qs

import requests

# =============================================================================
# CONTEXTO INYECTADO
# =============================================================================

_ctx: dict = {}


def init(ctx: dict):
    """
    Inyecta el contexto compartido desde Jarvis_main.py.
    Llamar UNA VEZ antes de usar cualquier función.

    Ejemplo:
        import agent_google
        agent_google.init({
            "hablar":               hablar,
            "cola_voz":             _cola_voz,
            "bridge":               _bridge,
            "html_burbuja":         _html_burbuja,
            "obtener_credenciales": _obtener_credenciales,
            "base_path":            base_path,
            "config":               config,
            "quitar_tildes":        quitar_tildes,
            "formatear_fecha":      formatear_fecha,
            "SERVIDOR_AUTH":        SERVIDOR_AUTH,
            "SCOPES":               SCOPES,
        })
    """
    global _ctx
    _ctx = ctx
    _arrancar_monitor_calendar()


# =============================================================================
# HELPERS DE ACCESO AL CONTEXTO
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

def _config():
    return _ctx.get("config", {})

def _quitar_tildes(texto):
    return _ctx["quitar_tildes"](texto)

def _formatear_fecha(fecha_str):
    fn = _ctx.get("formatear_fecha")
    if fn:
        return fn(fecha_str)
    # Fallback simple
    try:
        dt = datetime.fromisoformat(fecha_str.replace("Z", "+00:00")).replace(tzinfo=None)
        return dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return fecha_str


# =============================================================================
# AUTENTICACIÓN GOOGLE (OAuth reutilizando el flujo del monolito)
# =============================================================================

_token_recibido   = None
_servidor_activo  = False
_oauth_lock       = threading.Lock()

# Servicios lazy — se crean al primer uso
_svc_gmail    = None
_svc_calendar = None
_svc_tasks    = None
_svc_people   = None
_svc_drive    = None

_correo_pendiente = None
_correo_lock = threading.Lock()
_monitor_calendar_activo = False
_avisos_calendar = set()
_avisos_calendar_lock = threading.Lock()


def _obtener_credenciales():
    """Delega al monolito si está disponible; si no, ejecuta el flujo propio."""
    fn = _ctx.get("obtener_credenciales")
    if fn:
        return fn()
    return _flujo_oauth_propio()


def _guardar_token_json(token_file: str, token_data: dict):
    if not isinstance(token_data, dict):
        raise ValueError("Token OAuth inválido")
    os.makedirs(os.path.dirname(token_file) or ".", exist_ok=True)
    with open(token_file, "w", encoding="utf-8") as f:
        json.dump(token_data, f, indent=2, ensure_ascii=False)


def _flujo_oauth_propio():
    """Flujo OAuth completo si agent_google se usa de forma independiente."""
    global _token_recibido, _servidor_activo

    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request as _GReq

    base_path    = _ctx.get("base_path", os.getcwd())
    token_file   = os.path.join(base_path, "token.json")
    servidor_auth = _ctx.get("SERVIDOR_AUTH", "https://jarvis-server-j5ze.onrender.com")

    if os.path.exists(token_file):
        try:
            creds = Credentials.from_authorized_user_file(token_file)
            if creds.valid:
                return creds
            if creds.expired and creds.refresh_token:
                creds.refresh(_GReq())
                _guardar_token_json(token_file, json.loads(creds.to_json()))
                return creds
        except Exception as e:
            print(f"[OAuth] Token inválido, reintentando: {e}")
            try:
                os.remove(token_file)
            except Exception:
                pass

    with _oauth_lock:
        if os.path.exists(token_file):
            try:
                creds = Credentials.from_authorized_user_file(token_file)
                if creds.valid:
                    return creds
            except Exception:
                pass

        _token_recibido = None

        _bridge_html(_burbuja(
            '<p style="color:#ffaa44;font-size:13px;">⏳ Iniciando Google OAuth...</p>'
            '<p style="color:#8899bb;font-size:12px;">'
            'Si el navegador no abre, revisa que el servidor de auth esté activo.<br>'
            'Jarvis espera a que Google devuelva el token para guardarlo como token.json.</p>'
        ))
        _bridge_scroll()

        try:
            srv_ping = requests.get(f"{servidor_auth}/config", timeout=8, allow_redirects=False)
            print(f"[OAuth] Ping servidor auth: {srv_ping.status_code}")
        except Exception as e:
            print(f"[OAuth] No se pudo contactar al servidor auth: {e}")

        try:
            requests.get(f"{servidor_auth}/conectar", timeout=8, allow_redirects=False)
        except Exception as e:
            print(f"[OAuth] Error al despertar /conectar: {e}")
        time.sleep(3)

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                global _token_recibido
                parsed = urlparse(self.path)
                codigo = parse_qs(parsed.query).get("codigo", [None])[0]
                if codigo:
                    try:
                        r = requests.get(f"{servidor_auth}/obtener_token/{codigo}", timeout=20)
                        print(f"[OAuth] obtener_token -> {r.status_code}")
                        if r.status_code == 200:
                            try:
                                _token_recibido = r.json()
                                print(f"[OAuth] Token recibido: {list(_token_recibido.keys())[:8]}")
                            except Exception as e:
                                print(f"[OAuth] JSON del token inválido: {e} | cuerpo={r.text[:250]}")
                    except Exception as e:
                        print(f"[OAuth] Error al pedir token: {e}")
                self.send_response(200)
                self.end_headers()
                try:
                    self.wfile.write(b"OK")
                except Exception:
                    pass
            def log_message(self, *a): pass

        if not _servidor_activo:
            def _srv():
                global _servidor_activo
                _servidor_activo = True
                try:
                    HTTPServer(("localhost", 7845), _Handler).handle_request()
                finally:
                    _servidor_activo = False
            threading.Thread(target=_srv, daemon=True).start()

        webbrowser.open(f"{servidor_auth}/conectar")
        for _ in range(600):
            if _token_recibido:
                break
            time.sleep(0.5)

        if not _token_recibido:
            print("[OAuth] No se recibió token del servidor de auth.")
            return None

        try:
            _guardar_token_json(token_file, _token_recibido)
        except Exception as e:
            print(f"[OAuth] Error guardando token.json: {e}")
            return None

        return Credentials.from_authorized_user_file(token_file)


def _build(api: str, version: str):
    """Construye un servicio de Google API de forma lazy."""
    from googleapiclient.discovery import build
    creds = _obtener_credenciales()
    if not creds:
        return None
    return build(api, version, credentials=creds)


def _gmail():
    global _svc_gmail
    if _svc_gmail is None:
        _svc_gmail = _build("gmail", "v1")
    return _svc_gmail


def _calendar():
    global _svc_calendar
    if _svc_calendar is None:
        _svc_calendar = _build("calendar", "v3")
    return _svc_calendar


def _arrancar_monitor_calendar():
    global _monitor_calendar_activo
    if _monitor_calendar_activo:
        return
    _monitor_calendar_activo = True
    threading.Thread(target=_loop_monitor_calendar, daemon=True, name="GoogleCalendarMonitor").start()


def _loop_monitor_calendar():
    """Avisa una vez cuando un evento de Calendar comienza en unos 15 minutos."""
    while True:
        time.sleep(30)
        try:
            if (_config().get("google_calendar", True)
                    and _config().get("avisos_calendar_activados", True)):
                calendar_revisar_avisos()
        except Exception as exc:
            print(f"[Calendar monitor] {type(exc).__name__}: {exc}")


def calendar_revisar_avisos():
    """Consulta eventos próximos y anuncia los que están a 15 minutos."""
    token_file = os.path.join(_ctx.get("base_path", os.getcwd()), "token.json")
    if not _token_reutilizable(token_file) and _svc_calendar is None:
        return
    svc = _calendar()
    if not svc:
        return
    ahora = datetime.now(timezone.utc)
    limite_inferior = ahora + timedelta(minutes=14)
    limite_superior = ahora + timedelta(minutes=16)
    try:
        eventos = svc.events().list(
            calendarId="primary",
            singleEvents=True,
            orderBy="startTime",
            timeMin=limite_inferior.isoformat().replace("+00:00", "Z"),
            timeMax=limite_superior.isoformat().replace("+00:00", "Z"),
            maxResults=20,
        ).execute().get("items", [])
    except Exception as exc:
        print(f"[Calendar avisos] No se pudo consultar: {type(exc).__name__}: {exc}")
        return

    for evento in eventos:
        inicio = evento.get("start", {}).get("dateTime")
        if not inicio:
            continue
        try:
            inicio_dt = datetime.fromisoformat(inicio.replace("Z", "+00:00"))
            if inicio_dt.tzinfo is None:
                inicio_dt = inicio_dt.replace(tzinfo=timezone.utc)
            minutos = (inicio_dt - ahora).total_seconds() / 60
        except ValueError:
            continue
        if not 14 <= minutos <= 16:
            continue
        clave = f"{evento.get('id', '')}:{inicio}"
        with _avisos_calendar_lock:
            if clave in _avisos_calendar:
                continue
            _avisos_calendar.add(clave)
        titulo = str(evento.get("summary") or "Evento sin título").strip()
        hora = inicio_dt.astimezone().strftime("%H:%M")
        mensaje = f"Aviso de Google Calendar: {titulo} comienza aproximadamente en 15 minutos, a las {hora}."
        _bridge_html(_burbuja(
            f'<p style="color:#ffd166;font-weight:bold;">📅 Evento próximo</p>'
            f'<p style="color:#ccd6f6;">{escape(titulo)}</p>'
            f'<p style="color:#8899bb;font-size:12px;">Comienza a las {hora}, en aproximadamente 15 minutos.</p>'
        ))
        _bridge_scroll()
        _hablar(mensaje, None)


def _token_reutilizable(token_file: str) -> bool:
    if not os.path.exists(token_file):
        return False
    try:
        from google.oauth2.credentials import Credentials
        credenciales = Credentials.from_authorized_user_file(token_file)
        return bool(credenciales.valid or credenciales.refresh_token)
    except Exception:
        return False


def _tasks():
    global _svc_tasks
    if _svc_tasks is None:
        _svc_tasks = _build("tasks", "v1")
    return _svc_tasks


def _people():
    global _svc_people
    if _svc_people is None:
        _svc_people = _build("people", "v1")
    return _svc_people


def _drive():
    global _svc_drive
    if _svc_drive is None:
        _svc_drive = _build("drive", "v3")
    return _svc_drive


# =============================================================================
# 1. GMAIL
# =============================================================================

def _decodificar_cuerpo(payload) -> str:
    """Extrae el cuerpo de texto plano de un mensaje Gmail."""
    partes = payload.get("parts", [])
    if partes:
        for parte in partes:
            if parte.get("mimeType") == "text/plain":
                data = parte.get("body", {}).get("data", "")
                if data:
                    return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore")
        for parte in partes:
            sub = _decodificar_cuerpo(parte)
            if sub:
                return sub
    data = payload.get("body", {}).get("data", "")
    if data:
        return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore")
    return ""


def gmail_leer(max_msgs: int = 5, chat_widget=None):
    """Muestra los últimos correos de la bandeja de entrada."""
    _hablar("Revisando Gmail...", chat_widget)
    svc = _gmail()
    if not svc:
        html_err = (
            '<p style="color:#ff6655;font-size:13px;">⚠️ <b>Sin acceso a Gmail</b></p>'
            '<p style="color:#8899bb;font-size:12px;">'
            'Para conectar Google escribe <b>"conectar google"</b>.<br>'
            'Se abrirá el navegador para autorizar el acceso.<br>'
            '<span style="color:#556677;">Si el navegador no abre, revisa la consola.</span></p>'
        )
        _bridge_html(_burbuja(html_err))
        _bridge_scroll()
        _hablar("Necesito que autorices el acceso a Google primero.", chat_widget)
        return
    try:
        res  = svc.users().messages().list(userId="me", labelIds=["INBOX"], maxResults=max_msgs).execute()
        msgs = res.get("messages", [])
        if not msgs:
            _hablar("No tienes correos nuevos.", chat_widget)
            return

        filas       = ""
        resumen_voz = []
        for m in msgs:
            msg = svc.users().messages().get(
                userId="me", id=m["id"], format="metadata",
                metadataHeaders=["From", "Subject", "Date"]
            ).execute()
            headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
            asunto  = headers.get("Subject", "(sin asunto)")[:60]
            remite  = headers.get("From", "?")[:40]
            fecha   = headers.get("Date", "")[:16]
            url     = f"https://mail.google.com/mail/u/0/#inbox/{m['id']}"
            filas  += (
                f'<tr><td style="padding:5px 8px;border-bottom:1px solid #1a2740;">'
                f'<a href="{url}" style="color:#4db8ff;text-decoration:none;font-size:13px;">{asunto}</a>'
                f'<br><span style="color:#8899bb;font-size:11px;">{remite} · {fecha}</span>'
                f'</td></tr>'
            )
            resumen_voz.append(asunto)

        html = (
            f'<b>📧 Últimos {len(msgs)} correos</b>'
            f'<br><table width="100%" cellspacing="0" cellpadding="0">{filas}</table>'
            f'<br><span style="color:#556677;font-size:11px;">📡 Gmail API</span>'
        )
        _bridge_html(_burbuja(html))
        _bridge_scroll()
        _hablar(f"Tienes correos de: {', '.join(resumen_voz[:3])}.", chat_widget)
    except Exception as e:
        print(f"[Gmail leer] {e}")
        _hablar("Error al leer Gmail.", chat_widget)


def gmail_buscar(consulta: str, chat_widget=None):
    """Busca correos por texto o remitente."""
    _hablar(f"Buscando en Gmail: {consulta}...", chat_widget)
    svc = _gmail()
    if not svc:
        _hablar("No pude conectar con Gmail.", chat_widget)
        return
    try:
        res  = svc.users().messages().list(userId="me", q=consulta, maxResults=5).execute()
        msgs = res.get("messages", [])
        if not msgs:
            _hablar(f"No encontré correos de '{consulta}'.", chat_widget)
            return

        filas = ""
        for m in msgs:
            msg = svc.users().messages().get(
                userId="me", id=m["id"], format="metadata",
                metadataHeaders=["From", "Subject", "Date"]
            ).execute()
            headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
            asunto  = headers.get("Subject", "(sin asunto)")[:60]
            remite  = headers.get("From", "?")[:40]
            url     = f"https://mail.google.com/mail/u/0/#search/{m['id']}"
            filas  += (
                f'<tr><td style="padding:5px 8px;border-bottom:1px solid #1a2740;">'
                f'<a href="{url}" style="color:#4db8ff;text-decoration:none;">{asunto}</a>'
                f'<br><span style="color:#8899bb;font-size:11px;">{remite}</span>'
                f'</td></tr>'
            )
        html = (
            f'<b>📧 Resultados: "{consulta}"</b>'
            f'<br><table width="100%">{filas}</table>'
            f'<br><span style="color:#556677;font-size:11px;">📡 Gmail API</span>'
        )
        _bridge_html(_burbuja(html))
        _bridge_scroll()
        _hablar(f"Encontré {len(msgs)} correo(s) sobre '{consulta}'.", chat_widget)
    except Exception as e:
        print(f"[Gmail buscar] {e}")
        _hablar("Error buscando en Gmail.", chat_widget)


def gmail_enviar(destinatario: str, asunto: str, cuerpo: str, chat_widget=None, nombre_contacto: str = ""):
    """Prepara un correo y solicita confirmación antes de enviarlo."""
    global _correo_pendiente
    destinatario = str(destinatario or "").strip()
    asunto = str(asunto or "(sin asunto)").strip()
    cuerpo = str(cuerpo or "").strip()
    if not destinatario:
        _hablar("Necesito un destinatario para preparar el correo.", chat_widget)
        return
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", destinatario):
        _hablar("No reconocí un correo completo. Repítelo con el nombre, arroba y dominio.", chat_widget)
        return

    with _correo_lock:
        _correo_pendiente = {
            "destinatario": destinatario,
            "asunto": asunto,
            "cuerpo": cuerpo,
            "nombre_contacto": nombre_contacto,
            "chat_widget": chat_widget,
        }

    vista_previa = re.sub(r"\s+", " ", cuerpo).strip()[:180]
    resumen = f"Para {destinatario}. Asunto: {asunto}."
    if vista_previa:
        resumen += f" Texto: {vista_previa}."
    _hablar(f"He preparado el correo. {resumen} ¿Confirmas que lo envíe?", chat_widget)
    html = (
        '<b>📧 Correo listo para enviar</b><br>'
        f'<span style="color:#8899bb;">Para:</span> <span style="color:#4db8ff;">{destinatario}</span><br>'
        f'<span style="color:#8899bb;">Asunto:</span> <span style="color:#cce0ff;">{asunto}</span><br>'
        '<span style="color:#ffaa44;">Di "sí, envíalo" para confirmar o "cancela" para descartarlo.</span>'
    )
    _bridge_html(_burbuja(html))
    _bridge_scroll()


def hay_correo_pendiente() -> bool:
    with _correo_lock:
        return _correo_pendiente is not None


def resolver_correo_pendiente(comando: str, chat_widget=None) -> bool:
    """Resuelve la confirmación pendiente; devuelve True si consumió el comando."""
    global _correo_pendiente
    texto = _quitar_tildes(str(comando or "").lower()).strip(" .,!?:;")
    confirmaciones = ("si", "si envialo", "confirmo", "confirmar", "envialo", "enviar")
    cancelaciones = ("no", "cancela", "cancelar", "anula", "anular", "descarta")
    es_confirmacion = any(texto == opcion or texto.startswith(opcion + " ") for opcion in confirmaciones)
    es_cancelacion = any(texto == opcion or texto.startswith(opcion + " ") for opcion in cancelaciones)
    if not es_confirmacion and not es_cancelacion:
        return False

    with _correo_lock:
        pendiente = _correo_pendiente
        _correo_pendiente = None
    if not pendiente:
        return True
    if es_cancelacion:
        _hablar("Correo cancelado. No se envió nada.", chat_widget or pendiente.get("chat_widget"))
        return True

    _enviar_correo_confirmado(
        pendiente["destinatario"], pendiente["asunto"], pendiente["cuerpo"],
        chat_widget or pendiente.get("chat_widget"), pendiente.get("nombre_contacto", ""),
    )
    return True


def _enviar_correo_confirmado(destinatario: str, asunto: str, cuerpo: str,
                              chat_widget=None, nombre_contacto: str = ""):
    """Realiza la llamada Gmail únicamente después de confirmar."""
    _hablar(f"Enviando correo a {destinatario}...", chat_widget)
    svc = _gmail()
    if not svc:
        _hablar("No pude conectar con Gmail.", chat_widget)
        return
    try:
        msg           = MIMEText(cuerpo)
        msg["to"]     = destinatario
        msg["subject"]= asunto
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        svc.users().messages().send(userId="me", body={"raw": raw}).execute()
        guardar_contacto = _ctx.get("guardar_contacto_confianza")
        if guardar_contacto:
            try:
                guardar_contacto(destinatario, nombre_contacto)
            except Exception as exc:
                print(f"[Gmail] No se pudo guardar el correo del contacto: {exc}")
        _hablar(f"Correo enviado a {destinatario}.", chat_widget)
        html = (
            f'<b>📧 Correo enviado</b><br>'
            f'<span style="color:#8899bb;">Para:</span> <span style="color:#4db8ff;">{destinatario}</span><br>'
            f'<span style="color:#8899bb;">Asunto:</span> <span style="color:#cce0ff;">{asunto}</span>'
        )
        _bridge_html(_burbuja(html))
        _bridge_scroll()
    except Exception as e:
        print(f"[Gmail enviar] {e}")
        _hablar(f"No pude enviar el correo: {e}", chat_widget)


def gmail_eliminar(consulta: str, chat_widget=None):
    """Manda a la papelera los correos que coincidan con la búsqueda."""
    _hablar(f"Eliminando correos de '{consulta}'...", chat_widget)
    svc = _gmail()
    if not svc:
        _hablar("No pude conectar con Gmail.", chat_widget)
        return
    try:
        res  = svc.users().messages().list(userId="me", q=consulta, maxResults=5).execute()
        msgs = res.get("messages", [])
        if not msgs:
            _hablar(f"No encontré correos de '{consulta}'.", chat_widget)
            return
        for m in msgs:
            svc.users().messages().trash(userId="me", id=m["id"]).execute()
        _hablar(f"{len(msgs)} correo(s) enviado(s) a la papelera.", chat_widget)
    except Exception as e:
        print(f"[Gmail eliminar] {e}")
        _hablar("Error al eliminar correos.", chat_widget)


# =============================================================================
# 2. GOOGLE CALENDAR
# =============================================================================

def _extraer_nombre_fecha_hora(texto: str, tipo: str = "evento"):
    """Extrae nombre, fecha y hora de un comando de voz."""
    MESES = {
        "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
        "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
        "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
    }
    fecha = datetime.now()

    # Fecha dd/mm/yyyy
    m = re.search(r"(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})", texto)
    if m:
        fecha = datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    else:
        # "el 15 de mayo"
        m2 = re.search(r"el\s+(\d{1,2})\s+de\s+(\w+)", texto, re.IGNORECASE)
        if m2:
            mes_num = MESES.get(m2.group(2).lower())
            if mes_num:
                year = datetime.now().year
                fecha = datetime(year, mes_num, int(m2.group(1)))
                if fecha.date() < datetime.now().date():
                    fecha = fecha.replace(year=year + 1)
        elif "mañana" in texto:
            fecha = datetime.now() + timedelta(days=1)

    # Hora "a las X"
    m_hora = re.search(r"a las (\d{1,2})", texto)
    hora   = int(m_hora.group(1)) if m_hora else 8
    fecha  = fecha.replace(hour=hora, minute=0, second=0, microsecond=0)

    # Limpiar nombre
    nombre = texto
    if tipo == "evento":
        nombre = re.sub(r"\b(crear|crea)\s+(una?\s+)?(reunión|reunion|evento)\s*", "", nombre, flags=re.IGNORECASE)
    else:
        nombre = re.sub(r"\b(crear|crea|agregar|agrega|añadir|añade)\s+(una?\s+)?tarea\s*", "", nombre, flags=re.IGNORECASE)
    nombre = re.sub(r"(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{4})", "", nombre)
    nombre = re.sub(r"\ba las \d{1,2}\b", "", nombre)
    nombre = re.sub(r"\b(mañana|hoy)\b", "", nombre)
    nombre = nombre.strip(" ,.-") or ("Reunión Jarvis" if tipo == "evento" else "Tarea sin nombre")

    return nombre, fecha, hora


def calendar_ver_eventos(chat_widget=None):
    """Muestra los próximos eventos del calendario."""
    _hablar("Revisando tu calendario...", chat_widget)
    svc = _calendar()
    if not svc:
        html_err = (
            '<p style="color:#ff6655;font-size:13px;">⚠️ <b>Sin acceso a Google Calendar</b></p>'
            '<p style="color:#8899bb;font-size:12px;">'
            'Escribe <b>"conectar google"</b> para autorizar el acceso.</p>'
        )
        _bridge_html(_burbuja(html_err))
        _bridge_scroll()
        _hablar("Necesito que autorices el acceso a Google Calendar.", chat_widget)
        return
    try:
        ahora = datetime.utcnow().isoformat() + "Z"
        res   = svc.events().list(
            calendarId="primary", maxResults=10,
            singleEvents=True, orderBy="startTime", timeMin=ahora,
        ).execute()
        eventos = res.get("items", [])
        if not eventos:
            html = (
                '<b>📅 Próximos eventos (0)</b>'
                '<br><span style="color:#8899bb;font-size:12px;">No tienes eventos próximos.</span>'
            )
            _bridge_html(_burbuja(html))
            _bridge_scroll()
            _hablar("No tienes eventos próximos.", chat_widget)
            return

        hoy    = datetime.now().date()
        manana = hoy + timedelta(days=1)
        filas  = ""
        voz    = []
        for e in eventos:
            inicio    = e.get("start", {})
            fecha_str = inicio.get("dateTime") or inicio.get("date", "")
            titulo    = e.get("summary", "Sin título")
            try:
                if "T" in fecha_str:
                    dt      = datetime.fromisoformat(fecha_str.replace("Z", "+00:00")).replace(tzinfo=None)
                    hora_fmt = dt.strftime("%I:%M %p").lstrip("0")
                    if dt.date() == hoy:
                        prefijo = "Hoy"
                    elif dt.date() == manana:
                        prefijo = "Mañana"
                    else:
                        prefijo = dt.strftime("%d/%m")
                    etiqueta = f"{prefijo} {hora_fmt}"
                else:
                    dt      = datetime.strptime(fecha_str, "%Y-%m-%d")
                    etiqueta = dt.strftime("%d/%m") + " (todo el día)"
            except Exception:
                etiqueta = fecha_str

            filas += (
                f'<tr><td style="color:#4db8ff;padding:4px 10px;font-size:13px;">{titulo}</td>'
                f'<td style="color:#8899bb;font-size:12px;padding:4px 8px;">{etiqueta}</td></tr>'
            )
            voz.append(f"{titulo} — {etiqueta}")

        html = (
            f'<b>📅 Próximos eventos ({len(eventos)})</b>'
            f'<br><table cellspacing="0" cellpadding="0" width="100%">{filas}</table>'
            f'<br><span style="color:#556677;font-size:11px;">📡 Google Calendar API</span>'
        )
        _bridge_html(_burbuja(html))
        _bridge_scroll()
        _hablar(". ".join(voz[:3]), chat_widget)
    except Exception as e:
        print(f"[Calendar ver] {e}")
        _hablar("Error al leer el calendario.", chat_widget)


def calendar_crear_evento(comando: str, chat_widget=None):
    """Crea un evento en Google Calendar a partir de un comando de voz."""
    svc = _calendar()
    if not svc:
        _hablar("No pude conectar con Google Calendar.", chat_widget)
        return
    nombre, fecha, hora = _extraer_nombre_fecha_hora(comando, tipo="evento")
    start = fecha.isoformat()
    end   = (fecha + timedelta(hours=1)).isoformat()
    try:
        svc.events().insert(
            calendarId="primary",
            body={
                "summary": nombre,
                "start":   {"dateTime": start, "timeZone": "America/Bogota"},
                "end":     {"dateTime": end,   "timeZone": "America/Bogota"},
            }
        ).execute()
        _hablar(f"Reunión '{nombre}' creada el {_formatear_fecha(start)}.", chat_widget)
        html = (
            f'<b>📅 Evento creado</b><br>'
            f'<span style="color:#4db8ff;">{nombre}</span>'
            f'<br><span style="color:#8899bb;font-size:12px;">{_formatear_fecha(start)}</span>'
        )
        _bridge_html(_burbuja(html))
        _bridge_scroll()
    except Exception as e:
        print(f"[Calendar crear] {e}")
        _hablar(f"No pude crear el evento: {e}", chat_widget)


def calendar_eliminar_evento(nombre_buscar: str, chat_widget=None):
    """Elimina el primer evento cuyo título coincida con nombre_buscar."""
    svc = _calendar()
    if not svc:
        _hablar("No pude conectar con Google Calendar.", chat_widget)
        return
    try:
        ahora   = datetime.utcnow().isoformat() + "Z"
        res     = svc.events().list(
            calendarId="primary", maxResults=20,
            singleEvents=True, orderBy="startTime", timeMin=ahora,
        ).execute()
        eventos = res.get("items", [])
        nb      = _quitar_tildes(nombre_buscar.lower())
        evento  = next(
            (e for e in eventos if nb in _quitar_tildes(e.get("summary", "").lower())),
            eventos[0] if eventos else None,
        )
        if not evento:
            _hablar("No encontré reuniones para eliminar.", chat_widget)
            return
        svc.events().delete(calendarId="primary", eventId=evento["id"]).execute()
        _hablar(f"Reunión '{evento.get('summary', nombre_buscar)}' eliminada.", chat_widget)
    except Exception as e:
        print(f"[Calendar eliminar] {e}")
        _hablar("Error al eliminar el evento.", chat_widget)


def calendar_editar_evento(nombre_buscar: str, nombre_nuevo: str = None,
                            fecha_str: str = None, hora: int = None, chat_widget=None):
    """Edita el título y/o fecha de un evento existente."""
    svc = _calendar()
    if not svc:
        _hablar("No pude conectar con Google Calendar.", chat_widget)
        return
    try:
        ahora   = datetime.utcnow().isoformat() + "Z"
        res     = svc.events().list(
            calendarId="primary", maxResults=20,
            singleEvents=True, orderBy="startTime", timeMin=ahora,
        ).execute()
        eventos = res.get("items", [])
        nb      = _quitar_tildes(nombre_buscar.lower())
        evento  = next(
            (e for e in eventos if nb in _quitar_tildes(e.get("summary", "").lower())),
            None,
        )
        if not evento:
            _hablar(f"No encontré ningún evento con '{nombre_buscar}'.", chat_widget)
            return
        body = {"summary": nombre_nuevo or evento["summary"]}
        if fecha_str and hora is not None:
            inicio = datetime.fromisoformat(fecha_str).replace(hour=hora, minute=0)
            body["start"] = {"dateTime": inicio.isoformat(), "timeZone": "America/Bogota"}
            body["end"]   = {"dateTime": (inicio + timedelta(hours=1)).isoformat(), "timeZone": "America/Bogota"}
        svc.events().update(calendarId="primary", eventId=evento["id"], body=body).execute()
        _hablar(f"Evento '{body['summary']}' actualizado.", chat_widget)
    except Exception as e:
        print(f"[Calendar editar] {e}")
        _hablar("Error al editar el evento.", chat_widget)


# =============================================================================
# 3. GOOGLE TASKS
# =============================================================================

_tasklist_id_cache: str | None = None


def _default_tasklist_id() -> str:
    """Devuelve el ID de @default o el primero disponible."""
    global _tasklist_id_cache
    if _tasklist_id_cache:
        return _tasklist_id_cache
    svc = _tasks()
    if not svc:
        return "@default"
    try:
        listas = svc.tasklists().list().execute().get("items", [])
        _tasklist_id_cache = listas[0]["id"] if listas else "@default"
        return _tasklist_id_cache
    except Exception:
        return "@default"


def tasks_ver(chat_widget=None):
    """Muestra las tareas pendientes."""
    _hablar("Revisando tus tareas...", chat_widget)
    svc = _tasks()
    if not svc:
        _hablar("No pude conectar con Google Tasks.", chat_widget)
        return
    try:
        lid  = _default_tasklist_id()
        res  = svc.tasks().list(tasklist=lid, maxResults=20, showCompleted=False).execute()
        tareas = res.get("items", [])
        if not tareas:
            _hablar("No tienes tareas pendientes.", chat_widget)
            return

        filas = ""
        voz   = []
        for t in tareas:
            titulo = t.get("title", "")[:70]
            due    = t.get("due", "")[:10]
            etiq   = due if due else "Sin fecha"
            filas += (
                f'<tr><td style="padding:4px 10px;border-bottom:1px solid #1a2740;">'
                f'<span style="color:#ffcc44;">☐</span> '
                f'<span style="color:#cce0ff;">{titulo}</span>'
                f'<br><span style="color:#8899bb;font-size:11px;">{etiq}</span>'
                f'</td></tr>'
            )
            voz.append(titulo)

        html = (
            f'<b>✅ Tareas pendientes ({len(tareas)})</b>'
            f'<br><table width="100%">{filas}</table>'
            f'<br><span style="color:#556677;font-size:11px;">📡 Google Tasks API</span>'
        )
        _bridge_html(_burbuja(html))
        _bridge_scroll()
        _hablar(f"Tienes {len(tareas)} tarea(s). " + ", ".join(voz[:3]), chat_widget)
    except Exception as e:
        print(f"[Tasks ver] {e}")
        _hablar("Error al leer las tareas.", chat_widget)


def tasks_crear(titulo: str, fecha=None, chat_widget=None):
    """Crea una tarea nueva."""
    svc = _tasks()
    if not svc:
        _hablar("No pude conectar con Google Tasks.", chat_widget)
        return
    try:
        lid  = _default_tasklist_id()
        body = {"title": titulo}
        if fecha:
            if isinstance(fecha, str):
                # Puede venir como hora sola ("18"), fecha+hora, o ISO
                fecha_str = fecha.strip()
                if re.match(r'^\d{1,2}$', fecha_str):
                    # Solo hora → usar hoy con esa hora
                    fecha = datetime.now().replace(hour=int(fecha_str), minute=0, second=0, microsecond=0)
                elif re.match(r'^\d{4}-\d{2}-\d{2}$', fecha_str):
                    fecha = datetime.strptime(fecha_str, "%Y-%m-%d")
                else:
                    try:
                        fecha = datetime.fromisoformat(fecha_str)
                    except ValueError:
                        fecha = None
            if fecha:
                body["due"] = fecha.replace(hour=0, minute=0, second=0, microsecond=0).isoformat() + "Z"
        svc.tasks().insert(tasklist=lid, body=body).execute()
        _hablar(f"Tarea '{titulo}' creada.", chat_widget)
        _bridge_html(_burbuja(f'<b>✅ Tarea creada</b><br><span style="color:#cce0ff;">{titulo}</span>'))
        _bridge_scroll()
    except Exception as e:
        print(f"[Tasks crear] {e}")
        _hablar(f"No pude crear la tarea: {e}", chat_widget)


def tasks_eliminar(titulo_buscar: str, chat_widget=None):
    """Elimina la primera tarea que coincida con el texto."""
    svc = _tasks()
    if not svc:
        _hablar("No pude conectar con Google Tasks.", chat_widget)
        return
    try:
        lid    = _default_tasklist_id()
        res    = svc.tasks().list(tasklist=lid, maxResults=20, showCompleted=False).execute()
        tareas = res.get("items", [])
        nb     = _quitar_tildes(titulo_buscar.lower())
        tarea  = next(
            (t for t in tareas if nb in _quitar_tildes(t.get("title", "").lower())),
            None,
        )
        if not tarea:
            _hablar(f"No encontré ninguna tarea con '{titulo_buscar}'.", chat_widget)
            return
        svc.tasks().delete(tasklist=lid, task=tarea["id"]).execute()
        _hablar(f"Tarea '{tarea.get('title', titulo_buscar)}' eliminada.", chat_widget)
    except Exception as e:
        print(f"[Tasks eliminar] {e}")
        _hablar("Error al eliminar la tarea.", chat_widget)


def tasks_editar(titulo_buscar: str, titulo_nuevo: str = None, fecha=None, chat_widget=None):
    """Edita el título y/o fecha de una tarea existente."""
    svc = _tasks()
    if not svc:
        _hablar("No pude conectar con Google Tasks.", chat_widget)
        return
    try:
        lid    = _default_tasklist_id()
        res    = svc.tasks().list(tasklist=lid, maxResults=20, showCompleted=False).execute()
        tareas = res.get("items", [])
        nb     = _quitar_tildes(titulo_buscar.lower())
        tarea  = next(
            (t for t in tareas if nb in _quitar_tildes(t.get("title", "").lower())),
            None,
        )
        if not tarea:
            _hablar(f"No encontré ninguna tarea con '{titulo_buscar}'.", chat_widget)
            return
        body = {}
        if titulo_nuevo:
            body["title"] = titulo_nuevo
        if fecha:
            if isinstance(fecha, str):
                fecha = datetime.fromisoformat(fecha)
            body["due"] = fecha.date().isoformat() + "T00:00:00Z"
        svc.tasks().patch(tasklist=lid, task=tarea["id"], body=body).execute()
        _hablar(f"Tarea '{titulo_nuevo or tarea.get('title')}' actualizada.", chat_widget)
    except Exception as e:
        print(f"[Tasks editar] {e}")
        _hablar("Error al editar la tarea.", chat_widget)


# =============================================================================
# 4. CONTACTOS (Google People API)
# =============================================================================

def contactos_buscar(nombre: str, chat_widget=None) -> list:
    """
    Busca contactos por nombre.
    Devuelve lista de dicts {nombre, email, tel}.
    """
    svc = _people()
    if not svc:
        _hablar("No pude conectar con Contactos.", chat_widget)
        return []
    try:
        res       = svc.people().searchContacts(
            query=nombre, readMask="names,emailAddresses,phoneNumbers", pageSize=5
        ).execute()
        resultados = res.get("results", [])
        contactos  = []
        for r in resultados:
            persona = r.get("person", {})
            nombres = persona.get("names", [{}])
            emails  = persona.get("emailAddresses", [{}])
            tels    = persona.get("phoneNumbers", [{}])
            contactos.append({
                "nombre": nombres[0].get("displayName", "?") if nombres else "?",
                "email":  emails[0].get("value", "") if emails else "",
                "tel":    tels[0].get("value", "") if tels else "",
            })
        if not contactos:
            _hablar(f"No encontré contactos para '{nombre}'.", chat_widget)
            return []

        filas = "".join(
            f'<tr>'
            f'<td style="color:#4db8ff;padding:4px 10px;">{c["nombre"]}</td>'
            f'<td style="color:#8899bb;font-size:12px;padding:4px 8px;">{c["email"]}</td>'
            f'<td style="color:#8899bb;font-size:12px;padding:4px 8px;">{c["tel"]}</td>'
            f'</tr>'
            for c in contactos
        )
        html = (
            f'<b>👤 Contactos — "{nombre}"</b>'
            f'<br><table cellspacing="4">{filas}</table>'
            f'<br><span style="color:#556677;font-size:11px;">📡 Google People API</span>'
        )
        _bridge_html(_burbuja(html))
        _bridge_scroll()

        resumen = ", ".join(c["nombre"] for c in contactos[:3])
        _hablar(f"Encontré: {resumen}.", chat_widget)
        return contactos
    except Exception as e:
        print(f"[People] {e}")
        _hablar("Error al buscar contactos.", chat_widget)
        return []


# =============================================================================
# 5. GOOGLE DRIVE
# =============================================================================

_ICONOS_DRIVE = {
    "application/vnd.google-apps.spreadsheet": "📊",
    "application/vnd.google-apps.document":    "📄",
    "application/vnd.google-apps.presentation":"📑",
    "application/vnd.google-apps.folder":      "📁",
    "application/pdf":                          "📕",
}


def drive_buscar(consulta: str, chat_widget=None):
    """Busca archivos en Google Drive y los muestra con links."""
    _hablar(f"Buscando en Drive: {consulta}...", chat_widget)
    svc = _drive()
    if not svc:
        _hablar("No pude conectar con Google Drive.", chat_widget)
        return
    try:
        q   = f"name contains '{consulta}' and trashed=false"
        res = svc.files().list(
            q=q, pageSize=6,
            fields="files(id,name,mimeType,modifiedTime,webViewLink)"
        ).execute()
        archivos = res.get("files", [])
        if not archivos:
            _hablar(f"No encontré '{consulta}' en Drive.", chat_widget)
            return

        filas = ""
        for f in archivos:
            ico  = _ICONOS_DRIVE.get(f.get("mimeType", ""), "📎")
            name = f.get("name", "?")[:55]
            url  = f.get("webViewLink", "#")
            mod  = f.get("modifiedTime", "")[:10]
            filas += (
                f'<tr><td style="padding:5px 8px;border-bottom:1px solid #1a2740;">'
                f'{ico} <a href="{url}" style="color:#4db8ff;text-decoration:none;">{name}</a>'
                f'<br><span style="color:#8899bb;font-size:11px;">Modificado: {mod}</span>'
                f'</td></tr>'
            )
        html = (
            f'<b>📂 Drive — "{consulta}"</b>'
            f'<br><table width="100%">{filas}</table>'
            f'<br><span style="color:#556677;font-size:11px;">📡 Google Drive API</span>'
        )
        _bridge_html(_burbuja(html))
        _bridge_scroll()
        _hablar(f"Encontré {len(archivos)} archivo(s) en Drive.", chat_widget)
    except Exception as e:
        print(f"[Drive buscar] {e}")
        _hablar("Error al buscar en Drive.", chat_widget)


# =============================================================================
# FUNCIÓN PRINCIPAL DEL AGENTE
# =============================================================================

def ejecutar(accion: str, params: dict, chat_widget=None) -> bool:
    """
    Punto de entrada único desde dispatcher.py.
    Devuelve True si procesó la acción.
    """
    p = params or {}

    # ── Gmail ─────────────────────────────────────────────────────────────────
    if accion == "gmail_leer":
        gmail_leer(int(p.get("max_msgs", 5)), chat_widget)
        return True

    if accion == "gmail_buscar":
        gmail_buscar(p.get("consulta", ""), chat_widget)
        return True

    if accion == "gmail_enviar":
        gmail_enviar(
            p.get("destinatario", ""),
            p.get("asunto", "(sin asunto)"),
            p.get("cuerpo", ""),
            chat_widget,
            p.get("nombre_contacto", ""),
        )
        return True

    if accion == "gmail_eliminar":
        gmail_eliminar(p.get("consulta", ""), chat_widget)
        return True

    # ── Calendario ────────────────────────────────────────────────────────────
    if accion == "ver_eventos":
        calendar_ver_eventos(chat_widget)
        return True

    if accion == "crear_evento":
        # El dispatcher puede pasar el comando en bruto o los campos extraídos
        if "comando" in p:
            calendar_crear_evento(p["comando"], chat_widget)
        else:
            # Reconstruir comando mínimo si viene descompuesto
            nombre = p.get("nombre", "Reunión")
            fecha  = p.get("fecha", "")
            hora   = p.get("hora", "")
            cmd    = f"crear evento {nombre}"
            if fecha: cmd += f" {fecha}"
            if hora:  cmd += f" a las {hora}"
            calendar_crear_evento(cmd, chat_widget)
        return True

    if accion == "editar_evento":
        calendar_editar_evento(
            p.get("nombre_buscar", ""),
            p.get("nombre_nuevo"),
            p.get("fecha"),
            p.get("hora"),
            chat_widget,
        )
        return True

    if accion == "eliminar_evento":
        calendar_eliminar_evento(p.get("nombre_buscar", ""), chat_widget)
        return True

    # ── Tareas ────────────────────────────────────────────────────────────────
    if accion == "ver_tareas":
        tasks_ver(chat_widget)
        return True

    if accion == "crear_tarea":
        tasks_crear(p.get("titulo", "Nueva tarea"), p.get("fecha"), chat_widget)
        return True

    if accion == "editar_tarea":
        tasks_editar(
            p.get("titulo_buscar", ""),
            p.get("titulo_nuevo"),
            p.get("fecha"),
            chat_widget,
        )
        return True

    if accion == "eliminar_tarea":
        tasks_eliminar(p.get("titulo_buscar", ""), chat_widget)
        return True

    # ── Contactos ─────────────────────────────────────────────────────────────
    if accion == "buscar_contacto":
        contactos_buscar(p.get("nombre", ""), chat_widget)
        return True

    # ── Drive ─────────────────────────────────────────────────────────────────
    if accion == "drive_buscar":
        drive_buscar(p.get("consulta", ""), chat_widget)
        return True

    print(f"[agent_google] Acción desconocida: '{accion}'")
    return False
