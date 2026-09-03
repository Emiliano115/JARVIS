# =============================================================================
# Jarvis_main.py — Cerebro Central / Orquestador de Agentes
# =============================================================================
# Estructura:
#   1.  IMPORTS Y RUTAS
#   2.  CONFIGURACIÓN Y PERFIL
#   3.  UTILIDADES DE TEXTO (normalize, TTS helpers)
#   4.  KEYS Y APIs
#   5.  MOTOR DE VOZ (cola TTS, ElevenLabs/SAPI5/Edge)
#   6.  MEMORIA DE APPS Y ARCHIVOS
#   7.  ESCANEO DE APPS DEL SISTEMA
#   8.  HISTORIAL Y MEMORIA DE USUARIO
#   9.  PROMPT DEL SISTEMA (herramientas de todos los agentes)
#  10.  DISPATCHER: _ejecutar_accion
#  11.  CEREBRO IA: Groq + Gemini → JSON de acciones
#  12.  interpretar_multiple → punto de entrada principal
#  13.  INICIALIZACIÓN DE AGENTES (init de todos)
#  14.  INTERFAZ GRÁFICA (PySide6)
#  15.  MAIN
#
# Agentes externos:
#   agent_search.py  — búsqueda web, noticias, clima, cálculos
#   agent_images.py  — búsqueda y generación de imágenes
#   agent_pc.py      — apps, volumen, brillo, encendido
#   agent_google.py  — Gmail, Calendar, Tasks, Contactos, Drive
#   agent_notas.py   — notas, alarmas, recordatorios, memoria sesión
# =============================================================================

from __future__ import annotations

# =============================================================================
# 1. IMPORTS Y RUTAS
# =============================================================================
import sys, os, re, json, threading, time, unicodedata, random, shutil, sqlite3, wave, webbrowser
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs
from http.server import HTTPServer, BaseHTTPRequestHandler
import queue as _queue

# Forzar salida UTF-8 en consolas Windows para evitar UnicodeEncodeError con emojis
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import requests
import numpy as np

# Windows-specific
try:
    import win32gui, win32con
    import ctypes
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False

try:
    import keyboard
    HAS_KEYBOARD = True
except ImportError:
    HAS_KEYBOARD = False

try:
    import pyttsx3
    HAS_PYTTSX3 = True
except ImportError:
    HAS_PYTTSX3 = False

try:
    import whisper as _whisper_lib
    HAS_WHISPER = True
except ImportError:
    HAS_WHISPER = False

try:
    import sounddevice as sd
    HAS_SD = True
except ImportError:
    HAS_SD = False

try:
    from word2number_es import w2n
    HAS_W2N = True
except ImportError:
    HAS_W2N = False

try:
    from thefuzz import process as fuzz_process, fuzz
    HAS_FUZZ = True
except ImportError:
    HAS_FUZZ = False

try:
    import pygame
    # Deshabilitar ducking ANTES de que pygame registre el dispositivo
    try:
        import winreg as _wr
        _k = _wr.OpenKey(_wr.HKEY_CURRENT_USER,
            r"Software\Microsoft\Multimedia\Audio", 0, _wr.KEY_SET_VALUE)
        _wr.SetValueEx(_k, "UserDuckingPreference", 0, _wr.REG_DWORD, 3)
        _wr.CloseKey(_k)
    except Exception:
        pass
    pygame.mixer.pre_init(44100, -16, 2, 2048)
    pygame.mixer.init()
    HAS_PYGAME = True
except Exception:
    HAS_PYGAME = False

try:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from google.auth.transport.requests import Request
    HAS_GOOGLE = True
except ImportError:
    HAS_GOOGLE = False

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QTextBrowser, QLineEdit, QPushButton,
    QHBoxLayout, QDialog, QLabel, QCheckBox, QScrollArea, QFrame,
    QGridLayout, QMessageBox, QStyle,
    QTabWidget, QComboBox,
)
from PySide6.QtGui import QFont, QColor, QPalette, QDesktopServices, QPixmap, QImage, QIcon, QPainter
from PySide6.QtCore import Qt, Signal, QObject, QEvent, QTimer, QUrl, QSize, QPoint
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineSettings, QWebEnginePage
from PySide6.QtSvg import QSvgRenderer

# ─── Recursos y datos del usuario ────────────────────────────────────────────
if getattr(sys, 'frozen', False):
    base_path = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    data_path = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), 'Jarvis')
else:
    base_path = os.path.dirname(os.path.abspath(__file__))
    data_path = base_path

os.makedirs(data_path, exist_ok=True)
BASE_DIR = base_path
os.chdir(BASE_DIR)

apps_file     = os.path.join(data_path, "memoria_apps.txt")
archivos_file = os.path.join(data_path, "memoria_archivos.txt")

EXTENSIONES_PERMITIDAS   = {".pdf", ".docx", ".xlsx", ".pptx", ".txt", ".csv",
                             ".mp4", ".mp3", ".png", ".jpg", ".jpeg", ".wav"}
CARPETAS_IGNORAR         = {"AppData", "Local", "Temp", "Windows", "anaconda3", "node_modules"}

SERVIDOR_AUTH = "https://jarvis-server-j5ze.onrender.com"

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/tasks",
    "https://mail.google.com/",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/contacts",
]

VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP   = 0xAF

MAPA_SISTEMA: dict = {}

MESES = {
    "enero":"01","febrero":"02","marzo":"03","abril":"04","mayo":"05","junio":"06",
    "julio":"07","agosto":"08","septiembre":"09","octubre":"10","noviembre":"11","diciembre":"12",
}

GROQ_BASE_URL  = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL     = "llama-3.3-70b-versatile"
ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL    = "claude-sonnet-4-20250514"

# =============================================================================
# 2. CONFIGURACIÓN Y PERFIL
# =============================================================================
config_file = os.path.join(data_path, "jarvis_config.json")
modos_file  = os.path.join(data_path, "jarvis_modos.json")

modos = {
    "estudio":      ["teams", "office"],
    "gaming":       ["steam", "msi afterburner"],
    "programacion": ["vscode", "claude", "gemini"],
}

def cargar_config() -> dict:
    defaults = {
        "google_calendar": True, "google_maps": True,
        "guardar_links_apps": True, "guardar_archivos_recientes": True,
        "modo_carga_apps": None, "usar_tts_gratis": True,
    }
    if os.path.exists(config_file):
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                defaults.update(json.load(f))
        except Exception:
            pass
    return defaults

def guardar_config(cfg: dict):
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def _dispositivo_microfono():
    """Devuelve el dispositivo de entrada elegido o deja que PortAudio decida."""
    elegido = config.get("microfono_dispositivo") if "config" in globals() else None
    if elegido in (None, "", "default"):
        return None
    try:
        return int(elegido)
    except (TypeError, ValueError):
        return None

def cargar_modos_extra():
    if os.path.exists(modos_file):
        try:
            with open(modos_file, "r", encoding="utf-8") as f:
                modos.update(json.load(f))
        except Exception:
            pass

config = cargar_config()
cargar_modos_extra()


def _permiso_concedido(nombre: str) -> bool:
    """Permisos locales por capacidad; nunca concede privilegios de Windows."""
    return bool(config.get(f"permiso_{nombre}", False))


def _solicitar_permisos_iniciales() -> None:
    """Solicita una vez las capacidades sensibles y permite continuar limitado."""
    permisos = [
        ("escaneo_apps", "Buscar aplicaciones instaladas y sus rutas para poder abrirlas por nombre."),
        ("microfono", "Usar el micrófono para escuchar comandos de voz."),
        ("pantalla", "Capturar temporalmente la pantalla para verla o analizarla."),
        ("teclado", "Controlar teclado y ratón cuando pidas acciones explícitas en pantalla."),
    ]
    cambios = False
    for nombre, descripcion in permisos:
        clave = f"permiso_{nombre}"
        if clave in config:
            continue
        respuesta = QMessageBox.question(
            None,
            "Permiso de Jarvis",
            f"Jarvis solicita permiso para:\n\n{descripcion}\n\n"
            "Puedes denegarlo y cambiarlo después desde Configuración.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        config[clave] = respuesta == QMessageBox.StandardButton.Yes
        cambios = True
    if cambios:
        guardar_config(config)

# =============================================================================
# 3. UTILIDADES DE TEXTO
# =============================================================================

import html as _html_mod

def quitar_tildes(texto: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFD', texto)
                   if unicodedata.category(c) != 'Mn')

def normalizar_nombre_app(nombre: str) -> str:
    return quitar_tildes(nombre.lower().strip())

def _limpiar_html(texto: str) -> str:
    """HTML → texto plano para TTS."""
    texto = re.sub(r'<[^>]+>', ' ', texto)
    texto = _html_mod.unescape(texto)
    texto = re.sub(r'[\*`]', '', texto)
    texto = re.sub(r'\s+', ' ', texto).strip()
    return texto

def _markdown_a_html(texto: str) -> str:
    """Convierte markdown básico a HTML de forma segura (evita asteriscos sueltos)."""
    if not texto:
        return texto

    # Negrita **texto**
    texto = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', texto)
    # Encabezados
    texto = re.sub(r'^### (.+)$', r'<h4>\1</h4>', texto, flags=re.MULTILINE)
    texto = re.sub(r'^## (.+)$',  r'<h4>\1</h4>', texto, flags=re.MULTILINE)
    texto = re.sub(r'^# (.+)$',   r'<h3>\1</h3>', texto, flags=re.MULTILINE)
    # Itálica *texto* (un solo asterisco, par completo en la misma línea)
    texto = re.sub(r'(?<!\*)\*([^\*\n]+?)\*(?!\*)', r'<i>\1</i>', texto)

    # Viñetas '- ', '* ' o '• ' al inicio de línea → agrupar en <ul><li>
    lineas = texto.split('\n')
    salida = []
    en_lista = False
    for linea in lineas:
        m = re.match(r'^\s*[\-\*•]\s+(.+)$', linea)
        if m:
            if not en_lista:
                salida.append('<ul>')
                en_lista = True
            salida.append(f'<li>{m.group(1)}</li>')
        else:
            if en_lista:
                salida.append('</ul>')
                en_lista = False
            salida.append(linea)
    if en_lista:
        salida.append('</ul>')
    texto = '\n'.join(salida)

    # Limpieza de seguridad: cualquier asterisco suelto que sobreviva se elimina
    # (nunca debe llegar un "*" literal a pantalla ni mucho menos a la voz)
    texto = texto.replace('*', '')

    texto = re.sub(r'\n\n+', '</p><p>', texto)
    if not texto.startswith('<'):
        texto = f'<p>{texto}</p>'
    return texto

def _latex_a_html(texto: str) -> str:
    """Pasa LaTeX básico a texto simple (para QTextBrowser)."""
    texto = re.sub(r'\\\((.+?)\\\)', r' \1 ', texto, flags=re.DOTALL)
    texto = re.sub(r'\\\[(.+?)\\\]', r'<br>\1<br>', texto, flags=re.DOTALL)
    return texto

def formatear_fecha(fecha_str: str) -> str:
    try:
        dt = datetime.fromisoformat(fecha_str.replace("Z", "+00:00")).replace(tzinfo=None)
        return dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return fecha_str

def _html_burbuja(html_contenido: str) -> str:
    return (
        f'<div style="background:rgba(10,30,60,0.85);border-radius:12px;'
        f'padding:10px 14px;margin:6px 2px;border-left:3px solid #4db8ff;">'
        f'{html_contenido}</div>'
    )

def _html_burbuja_jarvis(html_contenido: str) -> str:
    return (
        f'<div style="background:rgba(5,15,35,0.90);border-radius:12px;'
        f'padding:10px 14px;margin:6px 2px;border-left:3px solid #1a5fa8;">'
        f'<span style="color:#4db8ff;font-size:11px;font-weight:bold;">◈ JARVIS</span><br>'
        f'{html_contenido}</div>'
    )

def _html_burbuja_usuario(texto: str) -> str:
    return (
        f'<div style="background:rgba(20,50,100,0.70);border-radius:12px;'
        f'padding:8px 14px;margin:6px 2px;border-right:3px solid #4db8ff;text-align:right;">'
        f'<span style="color:#8fb8e0;font-size:11px;">Tú</span><br>'
        f'<span style="color:#dde6f5;">{texto}</span></div>'
    )


_PALETA_RAMAS = [
    ("#00d4ff", "rgba(0,212,255,0.45)",  "rgba(0,18,38,0.92)",  "#8fe3ff"),
    ("#33ffcc", "rgba(51,255,204,0.40)", "rgba(0,30,28,0.92)",  "#9bffe6"),
    ("#ff9d4d", "rgba(255,157,77,0.40)", "rgba(35,20,5,0.92)",  "#ffc999"),
    ("#c792ff", "rgba(199,146,255,0.40)","rgba(25,12,38,0.92)", "#e0c2ff"),
    ("#ff6b9d", "rgba(255,107,157,0.40)","rgba(35,8,20,0.92)",  "#ffb3cd"),
    ("#7affb0", "rgba(122,255,176,0.40)","rgba(5,30,18,0.92)",  "#b8ffd2"),
    ("#ffe066", "rgba(255,224,102,0.40)","rgba(35,28,5,0.92)",  "#fff0b3"),
    ("#66c2ff", "rgba(102,194,255,0.40)","rgba(5,20,38,0.92)",  "#b3e0ff"),
]


def _extraer_tema_de_comando(texto: str) -> str:
    if not texto:
        return ""
    t = str(texto).strip()
    t = re.sub(r'^(?:haz|hace|crea|genera|realiza|arma|organiza|muestra|muéstrame|enseña|enséñame|ayúdame|ayudame)\s+', '', t, flags=re.IGNORECASE)
    t = re.sub(r'^(?:un|una|el|la|los|las)\s+', '', t, flags=re.IGNORECASE)
    t = re.sub(r'\b(?:mapa\s+mental|mapa\s+conceptual|mapa\s+de\s+ideas|diagrama\s+de\s+ideas)\b', '', t, flags=re.IGNORECASE)
    t = re.sub(r'^(?:sobre|de|del|de\s+la|de\s+los|de\s+las|en)\s+', '', t, flags=re.IGNORECASE)
    t = re.sub(r'\s+', ' ', t).strip(" .,:;")
    if not t:
        return "Mapa mental"
    return t[:1].upper() + t[1:]


def _resumen_mapa_mental(tema: str, ramas: list) -> str:
    if not ramas:
        return ""
    partes = []
    for i, rama in enumerate(ramas[:4]):
        if isinstance(rama, dict):
            titulo = str(rama.get("titulo") or rama.get("nombre") or f"Rama {i+1}").strip()
            hijos = rama.get("hijos") or []
            hijos_text = []
            for h in hijos[:3]:
                if isinstance(h, dict):
                    hijos_text.append(str(h.get("titulo") or h.get("nombre") or "").strip())
                else:
                    hijos_text.append(str(h).strip())
            hijos_text = [x for x in hijos_text if x]
            if hijos_text:
                partes.append(f"<li><b>{_escape_html(titulo)}</b>: {_escape_html(', '.join(hijos_text))}</li>")
            else:
                partes.append(f"<li><b>{_escape_html(titulo)}</b></li>")
        else:
            partes.append(f"<li><b>{_escape_html(str(rama))}</b></li>")
    if not partes:
        return ""
    items = "".join(partes)
    return f"<div style='margin-top:8px;padding:8px 10px;border:1px solid rgba(77,184,255,0.18);border-radius:10px;background:rgba(3,10,24,0.72);'><p style='margin:0 0 6px 0;color:#8fb8e0;font-size:11px;letter-spacing:1px;'>🧩 RESUMEN</p><ul style='margin:0;padding-left:16px;color:#dceeff;font-size:12px;'>{items}</ul></div>"


def _copiar_al_portapapeles(texto: str) -> bool:
    """Intenta copiar el texto al portapapeles del sistema."""
    try:
        import pyperclip
        pyperclip.copy(texto)
        return True
    except Exception:
        try:
            import tkinter as tk
            root = tk.Tk()
            root.withdraw()
            root.clipboard_clear()
            root.clipboard_append(texto)
            root.update()
            root.destroy()
            return True
        except Exception as exc:
            print(f"[Eraser] No se pudo copiar al portapapeles: {exc}")
            return False


def _pegar_en_eraser(texto: str) -> bool:
    """Intenta abrir Eraser y pegar el texto usando automatización local del navegador."""
    try:
        import pyautogui
        import pyperclip
        import time
        import pygetwindow as gw
        pyperclip.copy(texto)
        webbrowser.open("https://app.eraser.io")
        time.sleep(3)
        try:
            for win in gw.getAllWindows():
                if "eraser" in win.title.lower() or "chrome" in win.title.lower() or "edge" in win.title.lower():
                    try:
                        win.activate()
                        time.sleep(0.5)
                    except Exception:
                        pass
        except Exception:
            pass
        pyautogui.PAUSE = 0.15
        pyautogui.FAILSAFE = True
        for _ in range(4):
            try:
                pyautogui.hotkey('ctrl', 'v')
                time.sleep(0.3)
            except Exception:
                pass
        time.sleep(0.5)
        return True
    except Exception as exc:
        print(f"[Eraser] No se pudo automatizar el pegado: {exc}")
        return False


def _guardar_borrador_eraser(tema: str, texto_eraser: str) -> str:
    """Guarda un borrador local con el contenido listo para pegar en Eraser."""
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        slug = re.sub(r"[^A-Za-z0-9._-]+", "_", (tema or "mapa_mental").strip().lower())[:60] or "mapa_mental"
        file_path = os.path.join(base_dir, f"{slug}_eraser_draft.txt")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(texto_eraser + "\n")
        return file_path
    except Exception as exc:
        print(f"[Eraser] No se pudo guardar el borrador local: {exc}")
        return ""


def _crear_url_eraser_con_contexto(tema: str, ramas: list) -> str:
    """Devuelve la URL base de Eraser; no depende de parámetros que la app no interprete."""
    return "https://app.eraser.io/"


def _preparar_texto_eraser(tema: str, ramas: list) -> str:
    """Prepara un bloque listo para pegar en Eraser como prompt de mapa mental."""
    tema_txt = str(tema or "Mapa mental").strip() or "Mapa mental"
    lineas = [
        "PROMPT PARA ERASER",
        "",
        f"Crea un mapa mental visual, claro y bien organizado sobre: {tema_txt}.",
        "Usa una estructura jerárquica con ideas principales, subideas y ejemplos concretos.",
        "Hazlo con nodos conectados y un diseño fácil de leer.",
        "",
        f"# {tema_txt}",
        "",
        "## Estructura del mapa",
        "",
    ]
    for i, rama in enumerate(ramas[:8], 1):
        if isinstance(rama, dict):
            titulo = str(rama.get("titulo") or rama.get("nombre") or f"Rama {i}").strip()
            hijos = rama.get("hijos") or []
            hijos_txt = []
            for h in hijos[:4]:
                if isinstance(h, dict):
                    hijos_txt.append(str(h.get("titulo") or h.get("nombre") or "").strip())
                else:
                    hijos_txt.append(str(h).strip())
            hijos_txt = [x for x in hijos_txt if x]
            lineas.append(f"{i}. {titulo}")
            for hijo in hijos_txt:
                lineas.append(f"   - {hijo}")
        else:
            lineas.append(f"{i}. {str(rama).strip()}")
    return "\n".join(lineas).strip()


def _get_eraser_server_url() -> str:
    """Obtiene la URL del servidor MCP de Eraser desde config o .env."""
    try:
        if os.path.exists(config_file):
            with open(config_file, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            if isinstance(cfg, dict):
                servers = cfg.get("servers", {}) or {}
                if isinstance(servers, dict):
                    eraser_cfg = servers.get("eraser") or servers.get("Eraser")
                    if isinstance(eraser_cfg, dict):
                        url = str(eraser_cfg.get("url") or "").strip()
                        if url:
                            return url
                for key in ("eraser_mcp_url", "eraser_url", "eraser_server_url"):
                    val = cfg.get(key)
                    if isinstance(val, str) and val.strip():
                        return val.strip()
    except Exception:
        pass

    env = _leer_env()
    for key in ("ERASER_MCP_URL", "ERASER_URL", "ERASER_SERVER_URL"):
        val = env.get(key, "").strip()
        if val:
            return val
    return "https://app.eraser.io/api/mcp"


def _generar_mapa_mental_eraser(tema: str, ramas: list) -> dict:
    """Genera un bloque HTML para mostrar un mapa mental vía Eraser MCP.
    Si el endpoint responde, intenta invocar una herramienta de creación de diagramas.
    Si no, devuelve un fallback con un enlace a Eraser para abrir el mapa.
    """
    tema = str(tema or "Mapa mental").strip() or "Mapa mental"
    ramas = ramas or []

    resumen = _resumen_mapa_mental(tema, ramas)
    prompt = f"Crea un mapa mental claro y visual para: {tema}."
    if ramas:
        prompt += " Usa estas ramas: " + "; ".join(
            str(r.get("titulo") or r.get("nombre") or str(r)) for r in ramas[:6]
        )

    eraser_url = _crear_url_eraser_con_contexto(tema, ramas)
    server_url = _get_eraser_server_url()
    texto_eraser = _preparar_texto_eraser(tema, ramas)
    file_path = _guardar_borrador_eraser(tema, texto_eraser)
    clipboard_ok = _copiar_al_portapapeles(texto_eraser)
    pasted_ok = _pegar_en_eraser(texto_eraser)
    try:
        webbrowser.open(eraser_url)
    except Exception:
        pass
    html = (
        f"<div class='eraser-card' style='margin:8px 0;padding:12px 14px;border:1px solid rgba(0,212,255,0.22);border-radius:12px;background:rgba(2,10,20,0.85);'>"
        f"<div style='font-size:11px;letter-spacing:1px;color:#8fb8e0;margin-bottom:8px;'>🧠 MAPA MENTAL · ERASER</div>"
        f"<div style='color:#e8f4ff;font-size:13px;line-height:1.45;margin-bottom:8px;'>{_escape_html(tema)}</div>"
        f"{resumen or '<div style=\'color:#9dc8ff;font-size:12px;\'>Estoy abriendo Eraser y dejando el prompt preparado para que lo pegue directamente.</div>'}"
        f"<div style='color:#9dc8ff;font-size:12px;margin-top:6px;white-space:pre-wrap;max-height:140px;overflow:auto;'>{_escape_html(texto_eraser)}</div>"
        f"<div style='margin-top:8px;'><a href='{eraser_url}' target='_blank' rel='noopener' style='display:inline-block;padding:7px 12px;background:rgba(0,212,255,0.12);color:#4ddcff;border-radius:8px;text-decoration:none;font-size:12px;'>Abrir Eraser</a></div>"
        f"</div>"
    )

    try:
        init_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "Jarvis", "version": "5.5"},
            },
        }
        init_resp = requests.post(server_url, json=init_payload, timeout=12)
        if init_resp.ok:
            try:
                init_body = init_resp.json()
            except Exception:
                init_body = {}
            tools = []
            tools_resp = None
            try:
                tools_resp = requests.post(
                    server_url,
                    json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                    timeout=12,
                )
                if tools_resp.ok:
                    tools_data = tools_resp.json()
                    tools = tools_data.get("result", {}).get("tools", []) or []
            except Exception:
                tools = []

            if tools:
                tool_names = [str(t.get("name") or "") for t in tools if isinstance(t, dict)]
                tool_name = next((name for name in tool_names if any(k in name.lower() for k in ["mind", "diagram", "canvas", "map", "flow"])) , None)
                if tool_name:
                    call_payload = {
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "tools/call",
                        "params": {"name": tool_name, "arguments": {"prompt": prompt, "theme": tema}},
                    }
                    try:
                        call_resp = requests.post(server_url, json=call_payload, timeout=15)
                        if call_resp.ok:
                            try:
                                call_body = call_resp.json()
                            except Exception:
                                call_body = {}
                            content_text = ""
                            if isinstance(call_body, dict):
                                content_text = json.dumps(call_body, ensure_ascii=False, indent=2)[:1800]
                            if content_text:
                                html = (
                                    f"<div class='eraser-card' style='margin:8px 0;padding:12px 14px;border:1px solid rgba(0,212,255,0.22);border-radius:12px;background:rgba(2,10,20,0.85);'>"
                                    f"<div style='font-size:11px;letter-spacing:1px;color:#8fb8e0;margin-bottom:8px;'>🧠 MAPA MENTAL · ERASER</div>"
                                    f"<div style='color:#e8f4ff;font-size:13px;line-height:1.45;margin-bottom:8px;'>{_escape_html(tema)}</div>"
                                    f"<div style='color:#9dc8ff;font-size:12px;white-space:pre-wrap;max-height:220px;overflow:auto;'>{_escape_html(content_text)}</div>"
                                    f"<div style='margin-top:8px;'><a href='{eraser_url}' target='_blank' rel='noopener' style='display:inline-block;padding:7px 12px;background:rgba(0,212,255,0.12);color:#4ddcff;border-radius:8px;text-decoration:none;font-size:12px;'>Abrir Eraser con contexto</a></div>"
                                    f"</div>"
                                )
                    except Exception as exc:
                        print(f"[Eraser] Error al invocar herramienta: {exc}")
    except Exception as exc:
        print(f"[Eraser] Error al conectar con Eraser MCP: {exc}")

    return {
        "html": html,
        "url": eraser_url,
        "title": tema,
        "server_url": server_url,
        "file_path": file_path,
        "clipboard_text": texto_eraser if clipboard_ok or pasted_ok else "",
    }


def _generar_ramas_automaticas(tema: str) -> list:
    tema_l = quitar_tildes(str(tema or "").lower())
    if any(k in tema_l for k in ["fauna", "animal", "especie", "biodiversidad", "wildlife"]):
        return [
            {"titulo": "Hábitat y distribución", "hijos": [
                {"titulo": "Zonas principales", "hijos": ["Ártico", "Bosques", "Montañas"]},
                {"titulo": "Adaptaciones", "hijos": ["Clima", "Alimentación", "Migración"]}
            ]},
            {"titulo": "Ecología y rol", "hijos": [
                {"titulo": "Cadena alimenticia", "hijos": ["Depredadores", "Presas", "Descomponedores"]},
                {"titulo": "Impacto ambiental", "hijos": ["Biodiversidad", "Equilibrio", "Conservación"]}
            ]},
            {"titulo": "Amenazas", "hijos": [
                {"titulo": "Riesgos", "hijos": ["Cambio climático", "Pérdida de hábitat", "Caza"]},
                {"titulo": "Soluciones", "hijos": ["Protección", "Investigación", "Educación"]}
            ]},
        ]
    if any(k in tema_l for k in ["ia", "inteligencia artificial", "machine learning", "modelo", "robot"]):
        return [
            {"titulo": "Fundamentos", "hijos": ["Datos", "Algoritmos", "Entrenamiento"]},
            {"titulo": "Aplicaciones", "hijos": ["Salud", "Educación", "Industria"]},
            {"titulo": "Riesgos y ética", "hijos": ["Privacidad", "Sesgo", "Transparencia"]},
            {"titulo": "Impacto social", "hijos": ["Productividad", "Innovación", "Oportunidades"]},
        ]
    if any(k in tema_l for k in ["clima", "sostenible", "energ", "medio ambiente", "ecolog", "cambio climatico"]):
        return [
            {"titulo": "Problema central", "hijos": ["Emisiones", "Recursos", "Consumo"]},
            {"titulo": "Soluciones", "hijos": ["Energías limpias", "Reutilización", "Movilidad"]},
            {"titulo": "Impacto", "hijos": ["Salud", "Economía", "Comunidades"]},
            {"titulo": "Acción", "hijos": ["Políticas", "Tecnología", "Educación"]},
        ]
    return [
        {"titulo": "Idea central", "hijos": ["Definición", "Contexto", "Por qué importa"]},
        {"titulo": "Componentes clave", "hijos": ["Factores", "Procesos", "Recursos"]},
        {"titulo": "Aplicaciones", "hijos": ["Casos de uso", "Usuarios", "Beneficios"]},
        {"titulo": "Retos y oportunidades", "hijos": ["Limitaciones", "Mejoras", "Impacto social"]},
    ]


def _fallback_ramas_por_pais(tema: str) -> list:
    """Fallback simple y local: si el tema menciona países/regiones conocidos,
    devuelve ramas con fauna agrupada por categorías (mamíferos, aves, etc.).
    Esto evita depender exclusivamente de la LLM cuando hay límites de cuota.
    """
    if not tema:
        return []
    t = quitar_tildes(tema.lower())
    datos = {
        'noruega': {
            'Mamíferos': ['Lobo gris', 'Zorro ártico', 'Reno', 'Lince boreal', 'Urogallo'],
            'Aves': ['Águila pescadora', 'Gaviota polar', 'Búho nival'],
            'Otros': ['Trucha', 'Foca común']
        },
        'suecia': {
            'Mamíferos': ['Alce', 'Zorro rojo', 'Lince', 'Ciervo rojo'],
            'Aves': ['Buitre negro', 'Pato común', 'Gaviota'],
        },
        'suiza': {
            'Mamíferos': ['Cabra montés (Íbice)', 'Marmota', 'Zorro rojo'],
            'Aves': ['Quebrantahuesos', 'Buitre'],
        },
        'svalbard': {
            'Mamíferos': ['Oso polar', 'Zorro ártico', 'Liebre ártica'],
            'Aves': ['Arao', 'Gaviota ártica'],
        },
        'groenlandia': {
            'Mamíferos': ['Oso polar', 'Foca anillada', 'Narval'],
            'Aves': ['Águila marina', 'Gaviota'],
        }
    }
    for k, v in datos.items():
        if k in t:
            ramas = []
            for cat, lista in v.items():
                ramas.append({'titulo': cat, 'hijos': lista})
            return ramas
    return []


def _escape_html(texto: str) -> str:
    return _html_mod.escape(str(texto)).replace('\n', '<br>')


def _describir_lugar_nominatim(resultado: dict) -> str:
    if not resultado:
        return ''
    address = resultado.get('address', {}) or {}
    clase = resultado.get('class', '')
    tipo = resultado.get('type', '')
    labels = []
    if clase:
        labels.append(clase.replace('_', ' ').capitalize())
    if tipo and tipo not in clase:
        labels.append(tipo.replace('_', ' '))
    detalles = []
    if labels:
        detalles.append(f"<b>Tipo:</b> {' / '.join(labels)}")
    direccion = []
    for key in ('road', 'house_number', 'suburb', 'city', 'town', 'village', 'state', 'postcode', 'country'):
        if address.get(key):
            direccion.append(address[key])
    if direccion:
        detalles.append(f"<b>Dirección:</b> {_escape_html(', '.join(direccion))}")
    if address.get('amenity'):
        detalles.append(f"<b>Amenidad:</b> {_escape_html(address.get('amenity'))}")
    if address.get('shop'):
        detalles.append(f"<b>Tienda:</b> {_escape_html(address.get('shop'))}")
    if address.get('tourism'):
        detalles.append(f"<b>Turismo:</b> {_escape_html(address.get('tourism'))}")
    if address.get('attraction'):
        detalles.append(f"<b>Atracción:</b> {_escape_html(address.get('attraction'))}")
    return ''.join(f'<p>{line}</p>' for line in detalles)


def _normalizar_lugar(q: str) -> str:
    if not q:
        return q
    q_norm = quitar_tildes(q.lower()).strip()
    q_norm = re.sub(r'\s+', ' ', q_norm)
    correcciones = {
        'bogta': 'bogota',
        'bogotá': 'bogota',
        'bogota': 'bogota',
        'chia': 'chia',
        'andres crane de res': 'andres carne de res',
        'andres crane de res en chia': 'andres carne de res chia',
        'restaurante andres crane de res': 'restaurante andres carne de res',
        'restaurante andres crane de res en chia': 'restaurante andres carne de res en chia',
        'restaurante andres carne de res': 'andres carne de res',
        'restaurante andres carne de res en chia': 'andres carne de res chia',
    }
    for mal, bien in correcciones.items():
        if mal in q_norm:
            q_norm = q_norm.replace(mal, bien)
    # Normalizar algunas palabras clave comunes
    q_norm = re.sub(r'\b(av|av\.|avenida)\b', 'avenida', q_norm)
    q_norm = re.sub(r'\b(cra|cra\.|kr|kr\.|carrera)\b', 'carrera', q_norm)
    q_norm = re.sub(r'\b(cl|cl\.|calle)\b', 'calle', q_norm)
    return q_norm


def _wikidata_image_url(wikidata_id: str) -> str:
    if not wikidata_id:
        return ''
    import requests as _req
    try:
        wdRes = _req.get(
            'https://www.wikidata.org/w/api.php',
            params={
                'action': 'wbgetentities',
                'ids': wikidata_id,
                'props': 'claims',
                'format': 'json',
                'origin': '*'
            },
            timeout=10
        )
        if wdRes.status_code != 200:
            return ''
        wdJ = wdRes.json()
        entities = wdJ.get('entities', {})
        ent = next(iter(entities.values()), None)
        claims = ent.get('claims', {}) if ent else {}
        p18 = claims.get('P18', [{}])[0].get('mainsnak', {}).get('datavalue', {}).get('value')
        if not p18:
            return ''
        file_name = p18.replace(' ', '_')
        comRes = _req.get(
            'https://commons.wikimedia.org/w/api.php',
            params={
                'action': 'query',
                'titles': f'File:{file_name}',
                'prop': 'imageinfo',
                'iiprop': 'url',
                'format': 'json',
                'origin': '*'
            },
            timeout=10
        )
        if comRes.status_code != 200:
            return ''
        comJ = comRes.json()
        pages = comJ.get('query', {}).get('pages', {})
        page = next(iter(pages.values()), None)
        if page and page.get('imageinfo'):
            return page['imageinfo'][0].get('url', '')
    except Exception:
        return ''
    return ''

def _wikimedia_commons_image_url(query: str) -> str:
    if not query:
        return ''
    import requests as _req
    try:
        search_term = re.sub(r'[^\w\s]', ' ', query).strip()[:60]
        if not search_term:
            return ''
        res = _req.get(
            'https://commons.wikimedia.org/w/api.php',
            params={
                'action': 'query',
                'list': 'search',
                'srsearch': search_term,
                'srnamespace': '6',
                'srlimit': 6,
                'format': 'json',
                'origin': '*'
            },
            timeout=10
        )
        if res.status_code != 200:
            return ''
        data = res.json()
        titles = [item.get('title') for item in data.get('query', {}).get('search', []) if item.get('title')]
        if not titles:
            return ''
        pages = _req.get(
            'https://commons.wikimedia.org/w/api.php',
            params={
                'action': 'query',
                'titles': '|'.join(titles[:5]),
                'prop': 'imageinfo',
                'iiprop': 'url',
                'format': 'json',
                'origin': '*'
            },
            timeout=10
        )
        if pages.status_code != 200:
            return ''
        page_data = pages.json().get('query', {}).get('pages', {})
        for page in page_data.values():
            imageinfo = page.get('imageinfo')
            if imageinfo:
                url = imageinfo[0].get('url', '')
                if url and (url.endswith('.jpg') or url.endswith('.jpeg') or url.endswith('.png')):
                    return url
    except Exception:
        return ''
    return ''

# =============================================================================
# 4. KEYS Y APIs
# =============================================================================

_env_cache: dict | None = None

def _leer_env() -> dict:
    global _env_cache
    if _env_cache is not None:
        return _env_cache
    env, path = {}, os.path.join(data_path, ".env")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
    _env_cache = env
    return env

def _cargar_keys_desde_servidor() -> dict:
    """
    Intenta conectar al servidor de keys con un timeout único de 120s.
    Render free tier puede tardar 60-90s en despertar desde cold start.
    Estrategia: ping de wake-up → espera con timeout único (no reintentos múltiples).
    """
    url = f"{SERVIDOR_AUTH}/config"

    # ── Paso 1: ping rápido para despertar el servidor (sin bloquear mucho) ──
    try:
        requests.get(url, timeout=5)
    except Exception:
        pass  # normal si está dormido — el ping lo despierta en background

    # ── Paso 2: Un único timeout de 120s (2 minutos) para que se conecte ──
    try:
        timeout_segundos = 120  # 2 minutos
        print(f"[Config] Esperando servidor (timeout={timeout_segundos}s / 2 min)...")
        resp = requests.get(url, timeout=timeout_segundos)
        if resp.status_code == 200:
            data = resp.json()
            ng = len(data.get("groq_keys", []))
            gm = 1 if data.get("gemini_api_key") else 0
            print(f"✅ [Config] Keys cargadas — Groq:{ng} Gemini:{gm}")
            return data
        print(f"⚠️ [Config] Servidor respondió {resp.status_code}")
        return {}
    except requests.exceptions.Timeout:
        print(f"⚠️ [Config] Timeout (120s) — usando .env local")
        return {}
    except requests.exceptions.ConnectionError as e:
        print(f"⚠️ [Config] Sin conexión: {e}")
        return {}
    except Exception as e:
        print(f"⚠️ [Config] Error inesperado: {e}")
        return {}

def _inicializar_keys() -> dict:
    server_keys = _cargar_keys_desde_servidor()
    local_env   = _leer_env()

    def _get(sk, ek, default=""):
        return server_keys.get(sk) or local_env.get(ek, default)

    groq_keys = server_keys.get("groq_keys", [])
    if not groq_keys:
        k = local_env.get("GROQ_API_KEY", "").strip()
        if k: groq_keys.append(k)
        for i in range(2, 10):
            k = local_env.get(f"GROQ_API_KEY_{i}", "").strip()
            if k: groq_keys.append(k)

    gemini_keys = []
    for srv_key, env_key in [("gemini_api_key", "GEMINI_API_KEY"),
                              ("gemini_api_key_2", "GEMINI_API_KEY_2")]:
        v = server_keys.get(srv_key) or local_env.get(env_key, "").strip()
        if v and v not in gemini_keys:
            gemini_keys.append(v)

    return {
        "groq_keys":             groq_keys,
        "gemini_keys":           gemini_keys,
        "anthropic_api_key":     _get("anthropic_api_key", "ANTHROPIC_API_KEY"),
        "news_api_key":          _get("news_api_key", "NEWS_API_KEY"),
        "unsplash_access_key":   _get("unsplash_access_key", "UNSPLASH_ACCESS_KEY"),
        "pexels_api_key":        _get("pexels_api_key", "PEXELS_API_KEY"),
        "google_search_api_key": _get("google_search_api_key", "GOOGLE_SEARCH_API_KEY"),
        "google_search_cx":      _get("google_search_cx", "GOOGLE_SEARCH_CX"),
        "elevenlabs_api_key":    _get("elevenlabs_api_key", "ELEVENLABS_API_KEY"),
    }

# ── Variables globales de keys ────────────────────────────────────────────────
_KEYS: dict           = {}
_KEYS_LISTAS          = threading.Event()
_groq_keys: list      = []
_gemini_keys: list    = []
_groq_key_index: int  = 0
_gemini_key_index: int = 0

GROQ_API_KEY          = ""
GEMINI_API_KEY        = ""
NEWS_API_KEY          = ""
ANTHROPIC_API_KEY     = ""
GOOGLE_SEARCH_API_KEY = ""
GOOGLE_SEARCH_CX      = ""
UNSPLASH_ACCESS_KEY   = ""
PEXELS_API_KEY        = ""
ELEVENLABS_API_KEY    = ""

_groq_tokens = {"prompt": 0, "completion": 0, "total": 0, "llamadas": 0}

def _groq_key_activa() -> str:
    return _groq_keys[_groq_key_index % len(_groq_keys)] if _groq_keys else ""

def _groq_rotar_key(motivo=""):
    global _groq_key_index
    _groq_key_index = (_groq_key_index + 1) % max(1, len(_groq_keys))
    print(f"[Groq] Rotando key → #{_groq_key_index + 1} ({motivo})")

def _gemini_key_activa() -> str:
    return _gemini_keys[_gemini_key_index % len(_gemini_keys)] if _gemini_keys else ""

def _gemini_rotar_key(motivo=""):
    global _gemini_key_index
    _gemini_key_index = (_gemini_key_index + 1) % max(1, len(_gemini_keys))


def _mask_key(k: str) -> str:
    try:
        if not k:
              return ''
        s = str(k)
        if len(s) <= 8:
            return '****'
        return s[:3] + '...' + s[-3:]
    except Exception:
        return '****'


def imprimir_estado_keys():
    """Imprime un diagnóstico seguro sobre las keys cargadas (mascaradas)."""
    print('=== DIAGNOSTICO KEYS ===')
    print('Groq keys count:', len(_groq_keys))
    if _groq_keys:
        print('Groq sample masked:', [_mask_key(k) for k in _groq_keys[:8]])
    print('Groq active index:', _groq_key_index)
    print('Gemini keys count:', len(_gemini_keys))
    if _gemini_keys:
        print('Gemini sample masked:', [_mask_key(k) for k in _gemini_keys[:8]])
    print('Gemini active index:', _gemini_key_index)
    print('========================')


def _handle_quota(provider: str, body: str = '', status: int = 0):
    """Registro y acción cuando detectamos quota_exceeded en un proveedor.
    Toma medidas conservadoras: deshabilita la key del proveedor en memoria
    para evitar más errores hasta que el usuario lo re-enable.
    """
    print(f"[Quota Detector] {provider} reported quota issue (HTTP {status}).")
    snippet = body[:600].replace('\n', ' ')
    print(f"[Quota Detector] body: {snippet}")
    try:
        if provider.lower().startswith('eleven'):
            global ELEVENLABS_API_KEY
            ELEVENLABS_API_KEY = ""
            # Preferible marcar en config para persistir, pero evitamos escribir config automáticamente
            print('[Quota Detector] ElevenLabs key disabled in-memory (fallback to edge/SAPI).')
        if provider.lower().startswith('gemini'):
            _gemini_rotar_key('quota_detected')
        if provider.lower().startswith('groq'):
            _groq_rotar_key('quota_detected')
    except Exception as e:
        print(f"[Quota Detector] Error al manejar quota: {e}")

def _guardar_tokens():
    try:
        path = os.path.join(data_path, "jarvis_tokens.json")
        with open(path, "w") as f:
            json.dump(_groq_tokens, f)
    except Exception:
        pass

def _cargar_groq_keys() -> list:
    return list(_groq_keys) if _groq_keys else []

def _cargar_keys_background():
    global _KEYS, _groq_keys, _gemini_keys
    global GROQ_API_KEY, GEMINI_API_KEY, NEWS_API_KEY, ANTHROPIC_API_KEY
    global GOOGLE_SEARCH_API_KEY, GOOGLE_SEARCH_CX, UNSPLASH_ACCESS_KEY
    global PEXELS_API_KEY, ELEVENLABS_API_KEY
    _KEYS             = _inicializar_keys()
    _groq_keys        = _KEYS.get("groq_keys", [])
    _gemini_keys      = _KEYS.get("gemini_keys", [])
    GROQ_API_KEY      = _groq_key_activa()
    GEMINI_API_KEY    = _gemini_keys[0] if _gemini_keys else ""
    NEWS_API_KEY      = _KEYS.get("news_api_key", "")
    ANTHROPIC_API_KEY = _KEYS.get("anthropic_api_key", "")
    GOOGLE_SEARCH_API_KEY = _KEYS.get("google_search_api_key", "")
    GOOGLE_SEARCH_CX      = _KEYS.get("google_search_cx", "")
    UNSPLASH_ACCESS_KEY   = _KEYS.get("unsplash_access_key", "")
    PEXELS_API_KEY        = _KEYS.get("pexels_api_key", "")
    ELEVENLABS_API_KEY    = _KEYS.get("elevenlabs_api_key", "")
    _KEYS_LISTAS.set()

    # Log y alerta visual si faltan keys críticas
    if _groq_keys and _gemini_keys:
        print(f"[Keys] ✅ Groq:{len(_groq_keys)} Gemini:{len(_gemini_keys)} Anthropic:{'✓' if ANTHROPIC_API_KEY else '✗'}")
        _bridge.append_html.emit(_html_burbuja_jarvis(
            f'<span style="color:#44cc88;font-size:12px;">✓ IA conectada — '
            f'Groq({len(_groq_keys)}) + Gemini({len(_gemini_keys)})</span>'
        ))
    elif _groq_keys:
        print(f"[Keys] ⚠️ Solo Groq ({len(_groq_keys)} keys) — sin Gemini")
        _bridge.append_html.emit(_html_burbuja_jarvis(
            f'<span style="color:#ffaa44;font-size:12px;">⚠️ IA parcial — '
            f'Groq({len(_groq_keys)}) activo, Gemini no disponible</span>'
        ))
    elif _gemini_keys:
        print(f"[Keys] ⚠️ Solo Gemini — sin Groq")
        _bridge.append_html.emit(_html_burbuja_jarvis(
            '<span style="color:#ffaa44;font-size:12px;">⚠️ IA parcial — Gemini activo, Groq no disponible</span>'
        ))
    else:
        print("[Keys] ❌ SIN KEYS DE IA — el servidor no respondió y no hay .env")
        _bridge.append_html.emit(_html_burbuja_jarvis(
            '<span style="color:#ff5555;font-size:13px;">❌ Sin conexión a la IA</span><br>'
            '<span style="color:#8899bb;font-size:12px;">'
            'El servidor de keys no respondió. Soluciones:<br>'
            '1. Espera 60s y reinicia Jarvis (Render en cold start)<br>'
            '2. Crea un archivo <b>.env</b> en la carpeta de Jarvis con tus API keys<br>'
            '&nbsp;&nbsp;&nbsp;GROQ_API_KEY=gsk_tu_key_aqui<br>'
            '&nbsp;&nbsp;&nbsp;GEMINI_API_KEY=AIza_tu_key_aqui</span>'
        ))
    _bridge.scroll_down.emit()

# =============================================================================
# 5. MOTOR DE VOZ
# =============================================================================

_cola_voz = _queue.Queue()
_jarvis_hablando = threading.Event()
_tts_sapi_ref = [None]   # referencia global para poder interrumpir desde stop

def hablar(texto: str, chat_widget=None):
    """Encola texto para TTS y siempre lo muestra en chat también."""
    if not texto:
        return
    try:
        _bridge.append_html.emit(_html_burbuja_jarvis(f"<p>{_limpiar_html(texto)}</p>"))
    except Exception:
        pass
    try:
        _bridge.scroll_down.emit()
    except Exception:
        pass
    if not config.get("tts_activado", True):
        return
    _cola_voz.put(texto)

def _deshabilitar_ducking_windows():
    """
    Deshabilita el ducking de comunicaciones de Windows via registro.
    Equivale a: Panel de Control → Sonido → Comunicaciones → No hacer nada.
    Valor 3 = Do Nothing, 0 = Reduce by 80%, 1 = Reduce by 50%, 2 = Mute.
    """
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Multimedia\Audio",
            0, winreg.KEY_SET_VALUE
        )
        winreg.SetValueEx(key, "UserDuckingPreference", 0, winreg.REG_DWORD, 3)
        winreg.CloseKey(key)
        print("[Audio] ✅ Ducking deshabilitado (otras apps no bajan volumen)")
    except Exception as e:
        print(f"[Audio] No pude editar registro para ducking: {e}")


def _detener_tts():
    """Interrumpe inmediatamente la reproducción activa (pygame + SAPI5)."""
    if HAS_PYGAME:
        try:
            pygame.mixer.music.stop()
        except Exception:
            pass
    if _tts_sapi_ref[0] is not None:
        try:
            _tts_sapi_ref[0].Skip("Sentence", 999)
        except Exception:
            pass
    _jarvis_hablando.clear()

def _reproducir_edge_tts(texto: str) -> bool:
    """Reproduce texto con edge-tts (voz neural, NO activa Communications mode)."""
    try:
        import asyncio, tempfile, edge_tts
        async def _gen():
            communicate = edge_tts.Communicate(texto[:2500], "es-CO-SalomeNeural",
                                               rate="+5%", volume="+0%")
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
            tmp.close()
            await communicate.save(tmp.name)
            return tmp.name
        # Crear event loop propio para este hilo
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            ruta_mp3 = loop.run_until_complete(_gen())
        finally:
            loop.close()
        if HAS_PYGAME and os.path.exists(ruta_mp3):
            pygame.mixer.music.load(ruta_mp3)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                time.sleep(0.05)
            try:
                os.remove(ruta_mp3)
            except Exception:
                pass
            return True
    except Exception as e:
        print(f"[TTS-Edge] {e}")
    return False


def _dividir_para_tts(texto: str, max_len: int = 2500) -> list:
    """Divide texto largo en partes por oraciones para evitar truncado abrupto en TTS."""
    if len(texto) <= max_len:
        return [texto]
    partes, actual = [], ""
    for oracion in re.split(r'(?<=[.!?])\s+', texto):
        if len(actual) + len(oracion) + 1 <= max_len:
            actual = (actual + " " + oracion).strip()
        else:
            if actual:
                partes.append(actual)
            actual = oracion
    if actual:
        partes.append(actual)
    return partes


def _hilo_tts():
    """Hilo de TTS: ElevenLabs -> edge-tts -> SAPI5 (fallback final)."""
    import pythoncom
    import win32com.client
    import ctypes
    pythoncom.CoInitialize()

    # Deshabilitar ducking desde el hilo de audio
    try:
        import winreg as _wr
        _k = _wr.OpenKey(_wr.HKEY_CURRENT_USER,
            r"Software\Microsoft\Multimedia\Audio", 0, _wr.KEY_SET_VALUE)
        _wr.SetValueEx(_k, "UserDuckingPreference", 0, _wr.REG_DWORD, 3)
        _wr.CloseKey(_k)
    except Exception:
        pass

    # Marcar hilo como "Games" para que Windows no active ducking de comunicaciones
    try:
        avrt = ctypes.windll.avrt
        task_index = ctypes.c_ulong(0)
        avrt.AvSetMmThreadCharacteristicsW("Games", ctypes.byref(task_index))
    except Exception:
        pass

    # SAPI5 solo como fallback final — preparar silenciosamente
    tts_sapi = None
    try:
        tts_sapi = win32com.client.Dispatch("SAPI.SpVoice")
        tts_sapi.Rate = 0
        tts_sapi.Volume = 100
        voces = tts_sapi.GetVoices()
        for i in range(voces.Count):
            desc = voces.Item(i).GetDescription().lower()
            if "helena" in desc or "sabina" in desc or "spanish" in desc or "español" in desc:
                tts_sapi.Voice = voces.Item(i)
                break
        _tts_sapi_ref[0] = tts_sapi
    except Exception as e:
        print(f"[TTS] SAPI5 no disponible: {e}")

    # Detectar si edge-tts está instalado
    try:
        import edge_tts
        HAS_EDGE_TTS = True
    except ImportError:
        HAS_EDGE_TTS = False
        print("[TTS] edge-tts no instalado — instala con: pip install edge-tts")

    while True:
        try:
            texto = _cola_voz.get(timeout=0.3)
        except _queue.Empty:
            continue

        if texto is None:
            break
        texto_limpio = _limpiar_html(texto)
        if not texto_limpio.strip():
            continue

        _jarvis_hablando.set()
        try:
            partes_tts = _dividir_para_tts(texto_limpio, max_len=2500)
            for parte in partes_tts:
                reproducido = False

                # 1. ElevenLabs (mejor calidad, si hay key)
                if ELEVENLABS_API_KEY and len(ELEVENLABS_API_KEY) > 20:
                    try:
                        import requests as _req
                        r = _req.post(
                            "https://api.elevenlabs.io/v1/text-to-speech/pNInz6obpgDQGcFmaJgB",
                            headers={"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"},
                            json={"text": parte, "model_id": "eleven_multilingual_v2",
                                  "voice_settings": {"stability": 0.5, "similarity_boost": 0.8}},
                            timeout=30
                        )
                        if r.status_code == 200 and HAS_PYGAME:
                            import tempfile
                            tmp = None
                            try:
                                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
                                tmp.write(r.content)
                                tmp.close()
                                pygame.mixer.music.load(tmp.name)
                                pygame.mixer.music.play()
                                while pygame.mixer.music.get_busy():
                                    time.sleep(0.05)
                                reproducido = True
                            except Exception as e_mp3:
                                print(f"[TTS-Pygame] ERROR REAL: {type(e_mp3).__name__}: {e_mp3}")
                            finally:
                                if tmp:
                                    try: os.remove(tmp.name)
                                    except Exception: pass
                        elif r.status_code != 200:
                            print(f"[TTS-EL] HTTP {r.status_code}: {r.text[:200]}")
                            body_l = (r.text or '').lower()
                            if 'quota' in body_l or 'quota_exceeded' in body_l or 'quota-exceeded' in body_l:
                                _handle_quota('ElevenLabs', r.text, r.status_code)
                    except Exception as e_el:
                        print(f"[TTS-EL] ERROR REAL: {type(e_el).__name__}: {e_el}")

                # 2. edge-tts (voz neural, NO activa Communications mode)
                if not reproducido and HAS_EDGE_TTS:
                    reproducido = _reproducir_edge_tts(parte)

                # 3. SAPI5 último recurso (activa ducking — solo si los otros fallan)
                if not reproducido and tts_sapi:
                    try:
                        tts_sapi.Speak(parte, 0)
                        reproducido = True
                    except Exception as e_s:
                        print(f"[TTS-SAPI5] ERROR REAL: {type(e_s).__name__}: {e_s}")

                if not reproducido:
                    print(f"[TTS] ⚠️ No se pudo reproducir parte: '{parte[:80]}...'")

        except Exception as e:
            print(f"[TTS hilo] ERROR REAL: {type(e).__name__}: {e}")
        finally:
            _jarvis_hablando.clear()

threading.Thread(target=_hilo_tts, daemon=True, name="HiloTTS").start()

# =============================================================================
# 6. MEMORIA DE APPS Y ARCHIVOS
# =============================================================================

apps: dict             = {}   # nombre_norm → ruta
archivos_memoria: dict = {}   # nombre_norm → ruta

def _cargar_apps():
    global apps
    if os.path.exists(apps_file):
        try:
            with open(apps_file, "r", encoding="utf-8") as f:
                for line in f:
                    parts = line.strip().split("|", 1)
                    if len(parts) == 2:
                        apps[parts[0]] = parts[1]
        except Exception:
            pass

def _cargar_archivos():
    global archivos_memoria
    if os.path.exists(archivos_file):
        try:
            with open(archivos_file, "r", encoding="utf-8") as f:
                for line in f:
                    parts = line.strip().split("|", 1)
                    if len(parts) == 2:
                        archivos_memoria[quitar_tildes(parts[0].lower())] = parts[1]
        except Exception:
            pass

_cargar_apps()
_cargar_archivos()

def buscar_archivo_en_memoria(termino: str):
    """Devuelve (ruta, etiqueta) o None."""
    t = quitar_tildes(termino.lower())
    for k, v in archivos_memoria.items():
        if t in k:
            return (v, k)
    return None

# =============================================================================
# 7. ESCANEO DE APPS DEL SISTEMA
# =============================================================================

def obtener_apps_sistema(modo: str = "normal", max_cache_age_hours: int = 1) -> dict:
    """Escanea Start Menu + rutas conocidas. Devuelve dict nombre_norm → ruta."""
    if not _permiso_concedido("escaneo_apps"):
        print("[Permisos] Escaneo de apps omitido: permiso no concedido")
        return {}
    cache_file = os.path.join(data_path, f"memoria_auto_{modo}.json")
    if os.path.exists(cache_file):
        age = (time.time() - os.path.getmtime(cache_file)) / 3600
        if age < max_cache_age_hours:
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if len(data) >= 150:   # cache válido solo si tiene suficientes entradas
                    return data
            except Exception:
                pass

    mapa: dict = {}
    import glob

    # 1. Start Menu
    for ruta_base in [
        os.path.expandvars(r"%ProgramData%\Microsoft\Windows\Start Menu\Programs"),
        os.path.expandvars(r"%AppData%\Microsoft\Windows\Start Menu\Programs"),
    ]:
        for ext in ("*.lnk", "*.url", "*.appref-ms"):
            for ruta_item in glob.glob(os.path.join(ruta_base, "**", ext), recursive=True):
                nombre = os.path.splitext(os.path.basename(ruta_item))[0]
                mapa[quitar_tildes(nombre.lower().strip())] = ruta_item

    # 2. Rutas conocidas de apps populares (CRÍTICO: siempre buscar estas)
    _CONOCIDAS = [
        # Gaming / Stores
        (r"C:\Program Files (x86)\Steam\steam.exe",             "steam"),
        (r"C:\Program Files\Steam\steam.exe",                   "steam"),
        (r"C:\Program Files (x86)\Epic Games\Launcher\Portal\Binaries\Win32\EpicGamesLauncher.exe", "epic games"),
        (r"C:\Program Files\Epic Games\Launcher\Portal\Binaries\Win64\EpicGamesLauncher.exe",       "epic games"),
        (r"C:\Program Files\Epic Games Launcher\Portal\Binaries\Win64\EpicGamesLauncher.exe",       "epic games launcher"),
        (r"C:\Program Files (x86)\Epic Games\Launcher\Engine\Binaries\Win32\EpicGamesLauncher.exe", "epic games"),
        (r"C:\Program Files\Epic Games\Launcher\Engine\Binaries\Win64\EpicGamesLauncher.exe",       "epic games"),
        (r"C:\Riot Games\Riot Client\RiotClientServices.exe",   "riot games"),
        (r"C:\Riot Games\League of Legends\LeagueClient.exe",   "league of legends"),
        (r"C:\Program Files (x86)\Battle.net\Battle.net.exe",   "battle net"),
        
        # Communication
        (os.path.expandvars(r"%LocalAppData%\Discord\Update.exe"),                "discord"),
        (os.path.expandvars(r"%LocalAppData%\Discord\app-\Discord.exe"),          "discord"),
        (os.path.expandvars(r"%ProgramFiles%\Telegram Desktop\Telegram.exe"),     "telegram"),
        (os.path.expandvars(r"%LocalAppData%\Telegram Desktop\Telegram.exe"),     "telegram"),
        (os.path.expandvars(r"%LocalAppData%\Microsoft\Teams\current\Teams.exe"), "microsoft teams"),
        (os.path.expandvars(r"%ProgramFiles%\Microsoft\Teams\current\Teams.exe"),  "microsoft teams"),
        (os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Teams\current\Teams.exe"), "microsoft teams"),
        
        # Media & Entertainment
        (os.path.expandvars(r"%AppData%\Spotify\Spotify.exe"),                    "spotify"),
        (r"C:\Program Files\VideoLAN\VLC\vlc.exe",              "vlc"),
        
        # Development
        (os.path.expandvars(r"%LocalAppData%\Programs\Microsoft VS Code\Code.exe"), "vscode"),
        (os.path.expandvars(r"%LocalAppData%\Programs\Microsoft VS Code\Code.exe"), "visual studio code"),
        (r"C:\Program Files\Git\cmd\git.exe",                   "git"),
        (r"C:\Program Files\Python311\python.exe",              "python"),
        
        # Browsers
        (r"C:\Program Files\Google\Chrome\Application\chrome.exe",       "google chrome"),
        (r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe", "google chrome"),
        (r"C:\Program Files\Mozilla Firefox\firefox.exe",       "firefox"),
        (r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe", "firefox"),
        (r"C:\Program Files\Microsoft\Edge\Application\msedge.exe", "edge"),
        
        # Office & Productivity
        (r"C:\Program Files\Microsoft Office\root\Office16\OUTLOOK.EXE", "outlook"),
        (r"C:\Program Files (x86)\Microsoft Office\root\Office16\OUTLOOK.EXE", "outlook"),
        (r"C:\Program Files\Microsoft Office\root\Office16\WINWORD.EXE", "word"),
        (r"C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE", "excel"),
        
        # System Settings & Tools
        # ms-settings: va PRIMERO para que mapa.setdefault lo tome (Win10/11)
        ("ms-settings:",                                                     "settings"),
        ("ms-settings:",                                                     "configuracion"),
        ("ms-settings:",                                                     "configuración"),
        ("shell:AppsFolder\\Microsoft.Windows.ImmersiveControlPanel_cw5n1h2txyewy!microsoft.windows.immersivecontrolpanel", "windows settings"),
        ("shell:AppsFolder\\Microsoft.WindowsTerminal_8wekyb3d8bbwe!App",   "windows terminal"),
        (os.path.expandvars(r"%windir%\System32\cmd.exe"),                  "command prompt"),
        (os.path.expandvars(r"%windir%\System32\powershell.exe"),           "powershell"),
        
        # ROG & Gaming Tools
        (r"C:\Program Files (x86)\ASUS\ARMOURY CRATE\ArmouryCrate.exe",     "armoury crate"),
        (r"C:\Program Files (x86)\ASUS\ROG Command Center\RogCC.exe",       "rog command center"),
        (r"C:\Program Files\ASUS\ARMOURY CRATE\ArmouryCrate.exe",           "armoury crate"),
        (r"C:\Program Files\ASUS\ROG Command Center\RogCC.exe",             "rog command center"),
        
        # Creative & Media
        (r"C:\Program Files\Notepad++\notepad++.exe",           "notepad++"),
        (r"C:\Program Files\obs-studio\bin\64bit\obs64.exe",    "obs"),
        (r"C:\Program Files\GIMP 2\bin\gimp-2.10.exe",          "gimp"),
        (r"C:\Program Files (x86)\Audacity\Audacity.exe",       "audacity"),
        
        # Other Tools
        (r"C:\Program Files\7-Zip\7zFM.exe",                    "7zip"),
        (r"C:\Program Files\WinRAR\WinRAR.exe",                 "winrar"),
    ]
    for ruta_exe, nom in _CONOCIDAS:
        if ruta_exe.startswith(("shell:", "ms-settings:")) or os.path.exists(ruta_exe):
            mapa.setdefault(quitar_tildes(nom), ruta_exe)

    # 3. Escaneo exhaustivo de folders de programas
    def _escanear_carpeta_apps(base_dir: str, max_depth: int = 4):
        base_dir = os.path.expandvars(base_dir)
        if not os.path.isdir(base_dir):
            return
        base_norm = os.path.normpath(base_dir)
        base_depth = base_norm.count(os.sep)
        for root, dirs, files in os.walk(base_norm, topdown=True, onerror=lambda e: None):
            if root.count(os.sep) - base_depth >= max_depth:
                dirs[:] = []
            lc_root = root.lower()
            if "\\windows\\" in lc_root or "\\microsoft visual studio\\" in lc_root:
                continue
            for file in files:
                if not file.lower().endswith((".exe", ".lnk", ".url", ".appref-ms")):
                    continue
                ruta_item = os.path.join(root, file)
                nombre = os.path.splitext(file)[0]
                mapa.setdefault(quitar_tildes(nombre.lower().strip()), ruta_item)

    for carpeta in [
        r"%ProgramFiles%",
        r"%ProgramFiles(x86)%",
        r"%LocalAppData%\Programs",
        r"%LocalAppData%\Microsoft\WindowsApps",
    ]:
        _escanear_carpeta_apps(carpeta, max_depth=4)

    # 4. Buscar apps en otros discos
    for drive in ["C:", "D:", "E:", "F:"]:
        for cand, nom in [
            (f"{drive}\\Program Files\\Epic Games\\Launcher\\Portal\\Binaries\\Win64\\EpicGamesLauncher.exe", "epic games"),
            (f"{drive}\\Program Files (x86)\\Epic Games\\Launcher\\Portal\\Binaries\\Win64\\EpicGamesLauncher.exe", "epic games"),
            (f"{drive}\\Program Files\\Epic Games Launcher\\Portal\\Binaries\\Win64\\EpicGamesLauncher.exe", "epic games"),
            (f"{drive}\\Program Files (x86)\\Epic Games\\Launcher\\Engine\\Binaries\\Win64\\EpicGamesLauncher.exe", "epic games"),
            (f"{drive}\\Epic Games\\Launcher\\Portal\\Binaries\\Win64\\EpicGamesLauncher.exe", "epic games"),
            (f"{drive}\\Steam\\steam.exe", "steam"),
            (f"{drive}\\Program Files (x86)\\Steam\\steam.exe", "steam"),
            (f"{drive}\\Program Files\\Steam\\steam.exe", "steam"),
            (f"{drive}\\Games\\Epic Games Launcher\\Binaries\\Win64\\EpicGamesLauncher.exe", "epic games"),
        ]:
            if os.path.exists(cand):
                mapa.setdefault(quitar_tildes(nom), cand)

    # 5. Apps aprendidas manualmente
    mapa.update(apps)

    # Normalizar rutas corruptas: "explorer shell:appsFolder{..." → "shell:AppsFolder\{..."
    for k, v in list(mapa.items()):
        v_str = str(v)
        if "explorer shell:appsFolder{" in v_str.lower():
            import re as _re2
            v_fixed = _re2.sub(
                r'(?i)explorer\s+shell:appsFolder\{',
                r'shell:AppsFolder\\{',
                v_str
            )
            mapa[k] = v_fixed

    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(mapa, f, indent=2, ensure_ascii=False)
    except Exception:
        pass
    return mapa

def ejecutar_app(nombre: str, ruta: str, chat_widget=None):
    """Abre una app. Usa hilo no-daemon para asegurar que se abra."""
    import subprocess
    ruta = str(ruta).split("|")[0].strip()
    print(f"[ejecutar_app] Iniciando apertura: nombre={nombre}, ruta={ruta}")

    def _abrir():
        try:
            ruta_l = ruta.lower()
            print(f"[ejecutar_app] Tipo: {'URL' if ruta_l.startswith(('http://', 'https://')) else 'APP'}")

            if ruta.startswith(("http://", "https://")):
                import webbrowser
                print(f"[ejecutar_app] Abriendo navegador...")
                webbrowser.open(ruta)
            elif ruta_l.startswith("ms-settings:"):
                # Configuración de Windows — usar start directo
                print(f"[ejecutar_app] Abriendo ms-settings: {ruta}")
                subprocess.Popen(f'start "" "{ruta}"', shell=True)
            elif "shell:appsfolder" in ruta_l:
                # Caso 1: ruta con GUID → "shell:AppsFolder\{GUID}\ruta\al\archivo.exe"
                # El exe está dentro de Program Files, buscar en prefijos conocidos
                m_exe = re.search(
                    r'shell:appsFolder\\?\{[^}]+\}\\(.+\.exe)',
                    ruta, re.IGNORECASE
                )
                if m_exe:
                    exe_relativo = m_exe.group(1)  # ej: "Epic Games\Launcher\Portal\Binaries\Win64\EpicGamesLauncher.exe"
                    exe_encontrado = None
                    _PREFIJOS = [
                        r"C:\Program Files",
                        r"C:\Program Files (x86)",
                        r"D:\Program Files",
                        r"D:\Program Files (x86)",
                        r"E:\Program Files",
                        r"C:",
                        r"D:",
                        r"E:",
                    ]
                    for prefijo in _PREFIJOS:
                        candidato = os.path.join(prefijo, exe_relativo)
                        if os.path.exists(candidato):
                            exe_encontrado = candidato
                            break
                    if exe_encontrado:
                        print(f"[ejecutar_app] EXE resuelto: {exe_encontrado}")
                        subprocess.Popen([exe_encontrado], shell=False)
                    else:
                        # Fallback: buscar el nombre del exe en todo el sistema
                        exe_nombre = os.path.basename(exe_relativo)
                        print(f"[ejecutar_app] Buscando {exe_nombre} en el sistema...")
                        import glob as _glob
                        for patron in [
                            rf"C:\Program Files\**\{exe_nombre}",
                            rf"C:\Program Files (x86)\**\{exe_nombre}",
                            rf"D:\**\{exe_nombre}",
                            rf"E:\**\{exe_nombre}",
                        ]:
                            resultados = _glob.glob(patron, recursive=True)
                            if resultados:
                                exe_encontrado = resultados[0]
                                break
                        if exe_encontrado:
                            print(f"[ejecutar_app] EXE encontrado via glob: {exe_encontrado}")
                            subprocess.Popen([exe_encontrado], shell=False)
                        else:
                            print(f"[ejecutar_app] No se encontró el exe, abriendo con start shell")
                            subprocess.Popen(f'start "" "{ruta}"', shell=True)
                else:
                    # Caso 2: AppID UWP real → "shell:AppsFolder\Publisher.App!App"
                    m_uwp = re.search(r'shell:appsFolder\\([^\s"\\{][^\s"\\]+)', ruta, re.IGNORECASE)
                    if m_uwp:
                        appid = m_uwp.group(1)
                        no_win = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
                        print(f"[ejecutar_app] UWP app: {appid}")
                        subprocess.Popen(
                            ['powershell', '-WindowStyle', 'Hidden', '-Command',
                             f'Start-Process "shell:AppsFolder\\{appid}"'],
                            shell=False, creationflags=no_win,
                        )
                    else:
                        subprocess.Popen(f'start "" "{ruta}"', shell=True)
            elif ruta_l.startswith("shell:") and "appsfolder" not in ruta_l:
                print(f"[ejecutar_app] Abriendo shell URI: {ruta}")
                subprocess.Popen(f'start "" "{ruta}"', shell=True)
            elif ruta_l.endswith(".lnk"):
                print(f"[ejecutar_app] Abriendo shortcut con startfile")
                os.startfile(ruta)
            elif ruta_l.endswith(".exe"):
                print(f"[ejecutar_app] Abriendo EXE con Popen")
                subprocess.Popen([ruta], shell=False)
            else:
                print(f"[ejecutar_app] Abriendo con startfile (genérico)")
                os.startfile(ruta)
            print(f"[ejecutar_app] ✅ Comando ejecutado: {nombre}")
            hablar(f"Abriendo {nombre}", chat_widget)
        except Exception as e:
            print(f"[ejecutar_app] ❌ Error primario: {e}")
            try:
                print(f"[ejecutar_app] Reintentando con start shell...")
                subprocess.Popen(f'start "" "{ruta}"', shell=True)
                print(f"[ejecutar_app] ✅ Fallback ejecutado: {nombre}")
                hablar(f"Abriendo {nombre}", chat_widget)
            except Exception as e2:
                print(f"[ejecutar_app] ❌ Error fallback: {e2}")
                hablar(f"No pude abrir {nombre}", chat_widget)

    hilo = threading.Thread(target=_abrir, daemon=False)
    hilo.start()
    print(f"[ejecutar_app] Thread iniciado (no-daemon)")

def _score_app_v9(nombre_usuario: str, nombre_app: str) -> int:
    """Score de similitud con penalización por diferencia de longitud."""
    if not HAS_FUZZ:
        nu = quitar_tildes(nombre_usuario.lower())
        na = quitar_tildes(nombre_app.lower())
        return 100 if nu == na else (70 if nu in na else 0)

    nu = quitar_tildes(nombre_usuario.lower().strip())
    na = quitar_tildes(nombre_app.lower().strip())

    if nu == na:
        return 100

    score = fuzz.token_set_ratio(nu, na)

    # Penalizar si la app tiene nombre mucho más largo que la query
    # Ej: "reloj" (5) vs "microsoft project" (17) → penalizar
    len_u = max(1, len(nu.replace(" ", "")))
    len_a = max(1, len(na.replace(" ", "")))
    ratio = len_a / len_u
    if ratio > 3.0:
        score = max(0, score - 35)
    elif ratio > 2.0:
        score = max(0, score - 18)
    elif ratio > 1.6:
        score = max(0, score - 8)

    # Bonus si las palabras de la query están exactamente en el nombre
    palabras_u = set(nu.split())
    palabras_a = set(na.split())
    if palabras_u and palabras_u <= palabras_a:
        score = min(100, score + 10)

    return score

# =============================================================================
# 8. HISTORIAL Y MEMORIA DE USUARIO
# =============================================================================

_MAX_HISTORIAL = 250  # Historial muy grande para contexto conversacional profundo y referencias a hace muchos mensajes atrás

# Archivo para persistir historial de chat (restaurable al iniciar)
_historial_file = os.path.join(data_path, "jarvis_historial.json")
_memoria_chat_file = os.path.join(data_path, "memoria_chat.json")


def _cargar_historial() -> list:
    datos = []
    for ruta in (_historial_file, _memoria_chat_file):
        try:
            if os.path.exists(ruta):
                with open(ruta, 'r', encoding='utf-8') as hf:
                    data = json.load(hf)
                    if isinstance(data, list):
                        datos.extend(data)
        except Exception:
            continue

    # Unificar por rol + texto + hora, manteniendo el último turno si se repite.
    vistos = set()
    unicos = []
    for item in reversed(datos):
        if not isinstance(item, dict):
            continue
        clave = (str(item.get('rol','')), str(item.get('texto','')).strip(), str(item.get('ts','')))
        if clave in vistos:
            continue
        vistos.add(clave)
        unicos.append(item)
    unicos.reverse()
    return unicos[-_MAX_HISTORIAL:]

_historial: list = _cargar_historial()

_memoria_file  = os.path.join(data_path, "jarvis_memoria.json")
_patrones      = {}

_MEMORIA_VACIA = {
    "nombre": None, "ciudad": None, "barrio": None,
    "zona_horaria": "UTC-5", "idioma": "español colombiano",
    "idioma_codigo": "es", "trabajo": None, "colegio": None,
    "edad": None, "mascotas": None, "hobbies": [], "familia": {},
    "preferencias": {}, "resumen_contexto": "",
    "ultimo_tema": None, "extras": {}
}

def _cargar_memoria() -> dict:
    if os.path.exists(_memoria_file):
        try:
            with open(_memoria_file, "r", encoding="utf-8") as f:
                datos = json.load(f)
                m = _MEMORIA_VACIA.copy()
                m.update(datos)
                # Limpiar contexto conversacional de sesión anterior para evitar confusión
                m['resumen_contexto'] = ''
                m['ultimo_tema'] = None
                return m
        except Exception:
            pass
    return _MEMORIA_VACIA.copy()

def _guardar_memoria(m: dict):
    try:
        with open(_memoria_file, "w", encoding="utf-8") as f:
            json.dump(m, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[Memoria] {e}")

memoria_usuario: dict = _cargar_memoria()

def _agregar_historial(rol: str, texto: str):
    texto = re.sub(r'\s+', ' ', str(texto)).strip()
    if not texto:
        return
    _historial.append({"rol": rol, "texto": texto[:1500],
                        "ts": datetime.now().strftime("%H:%M")})
    # Mantener tamaño acotado
    if len(_historial) > _MAX_HISTORIAL:
        while len(_historial) > _MAX_HISTORIAL:
            _historial.pop(0)
    # Persistir historial en disco (no crítico)
    try:
        with open(_historial_file, 'w', encoding='utf-8') as hf:
            json.dump(_historial, hf, indent=2, ensure_ascii=False)
        with open(_memoria_chat_file, 'w', encoding='utf-8') as hf:
            json.dump(_historial, hf, indent=2, ensure_ascii=False)
    except Exception:
        pass


def _marcar_nueva_sesion():
    """
    Inserta un marcador de sesión en el historial. Se llama UNA VEZ al arrancar Jarvis.
    Sirve para que el contexto crudo de la conversación (lo que se le manda al modelo)
    nunca mezcle turnos de una sesión anterior (ya cerrada) con la sesión actual,
    evitando que un tema viejo y sin relación "se cuele" en una pregunta nueva.
    """
    marca = {
        "rol": "sistema",
        "texto": "NUEVA_SESION",
        "ts": datetime.now().strftime("%H:%M"),
    }
    _historial.append(marca)
    try:
        with open(_historial_file, 'w', encoding='utf-8') as hf:
            json.dump(_historial, hf, indent=2, ensure_ascii=False)
        with open(_memoria_chat_file, 'w', encoding='utf-8') as hf:
            json.dump(_historial, hf, indent=2, ensure_ascii=False)
    except Exception:
        pass


def _indice_inicio_sesion() -> int:
    """Devuelve el índice del historial donde empezó la sesión actual (0 si no hay marca)."""
    for i in range(len(_historial) - 1, -1, -1):
        h = _historial[i]
        if h.get('rol') == 'sistema' and h.get('texto') == 'NUEVA_SESION':
            return i
    return 0


def _historial_sesion_actual() -> list:
    """Solo los turnos de usuario/jarvis de la sesión activa (sin marcas de sistema)."""
    idx = _indice_inicio_sesion()
    return [h for h in _historial[idx:] if h.get('rol') in ('usuario', 'jarvis')]

_STOPWORDS_ES = {
    "esta", "estan", "estás", "están", "tiene", "tienen", "puede", "pueden", "creo",
    "sabe", "tengo", "hacer", "bueno", "buena", "malo", "mala", "cosa", "cosas",
    "hora", "horas", "dia", "dias", "día", "días", "bien", "mal", "otro", "otra",
    "otros", "otras", "puedo", "digo", "varias", "varios", "donde", "dónde",
    "cuando", "cuándo", "porque", "por qué", "entonces", "tambien", "también",
    "ahora", "antes", "despues", "después", "siempre", "nunca", "mucho", "muchos",
    "mucha", "muchas", "poco", "pocos", "poca", "pocas", "alguno", "alguna",
    "algunos", "algunas", "ninguno", "ninguna", "todo", "toda", "todos", "todas",
    "este", "esa", "esas", "esos", "ese", "aquel", "aquella", "aquellos",
    "quiero", "quieres", "podrias", "podrías", "dime", "dame", "para", "sobre",
    "como", "cómo", "claro", "vale", "listo", "gracias", "favor", "porfa",
    "necesito", "necesitas", "deberia", "debería", "habia", "había", "fueron",
    "estaba", "estaban", "habria", "habría", "seria", "sería", "hicieron",
    "hizo", "decir", "dicho", "hace", "hizo", "vamos", "vienes", "vamos",
}

_REGLAS_TEMAS = {
    "mapas/ubicaciones":   ("mapa", "maps", "ruta", "lugar", "dirección", "direccion", "ubicación", "ubicacion", "google maps"),
    "notas/recordatorios": ("nota", "recordatorio", "alarma", "tarea"),
    "correo/calendario":   ("correo", "gmail", "calendar", "evento", "agenda", "reunión", "reunion"),
    "apps/pc":             ("abrir", "cerrar", "app", "windows", "pc", "archivo", "volumen", "brillo"),
    "clima/noticias":      ("clima", "noticias", "tiempo", "weather"),
    "imagenes":            ("imagen", "foto", "fotos", "imágenes", "imagenes", "visual"),
    "peliculas/series":    ("película", "pelicula", "películas", "peliculas", "serie", "series", "netflix", "actor", "actriz", "director"),
    "ciencia/matematicas": ("física", "fisica", "matemática", "matematica", "ecuación", "ecuacion", "fórmula", "formula", "teorema"),
    "tecnologia":          ("ia", "inteligencia artificial", "modelo", "software", "hardware", "código", "codigo", "programación", "programacion"),
}


def _extraer_temas_recientes() -> list:
    temas = []
    for h in reversed(_historial_sesion_actual()[-40:]):
        txt = str(h.get('texto', '')).lower()
        for tema, palabras in _REGLAS_TEMAS.items():
            if any(p in txt for p in palabras):
                temas.append(tema)
                break
    vistos = set()
    uniq = []
    for t in temas:
        if t not in vistos:
            vistos.add(t)
            uniq.append(t)
    return uniq[:4]


# ── Memoria de entidades: nombre propio/tema → {primera_mencion, ultima_mencion, frecuencia} ──
_entidades_sesion: dict = {}


def _registrar_entidades(texto: str, idx_mensaje: int):
    """Extrae entidades nombradas (multi-palabra capitalizadas) y las registra
    con su posición en el historial para poder rastrear recencia real."""
    if not texto:
        return
    # Entidades multi-palabra: secuencias de 1-4 palabras capitalizadas consecutivas
    candidatos = re.findall(r'\b[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){0,3}\b', texto)
    _IGNORAR = {"Si", "No", "El", "La", "Es", "Sí", "Pero", "Yo", "Tu", "Tú", "Jarvis", "Hola"}
    for cand in candidatos:
        cand = cand.strip()
        if cand in _IGNORAR or len(cand) < 3:
            continue
        clave = cand.lower()
        if clave in _entidades_sesion:
            _entidades_sesion[clave]["frecuencia"] += 1
            _entidades_sesion[clave]["ultima_mencion"] = idx_mensaje
        else:
            _entidades_sesion[clave] = {
                "texto":          cand,
                "frecuencia":     1,
                "primera_mencion": idx_mensaje,
                "ultima_mencion":  idx_mensaje,
            }


def _reconstruir_entidades_sesion():
    """Reconstruye el mapa de entidades desde cero a partir del historial de la sesión actual.
    Se llama una vez por turno para mantener consistencia tras reinicios o restauración de disco."""
    global _entidades_sesion
    _entidades_sesion = {}
    historial_sesion = _historial_sesion_actual()
    for idx, h in enumerate(historial_sesion):
        _registrar_entidades(h.get('texto', ''), idx)


_PRONOMBRES_REFERENCIA = {
    "eso", "esa", "ese", "esos", "esas", "él", "el", "ella", "ello",
    "lo", "la", "los", "las", "ábrelo", "abrelo", "ábrela", "abrela",
    "el primero", "la primera", "el último", "la última", "el anterior",
    "la anterior", "lo anterior", "lo que dijiste", "lo que dijiste antes",
    "ese tema", "esa cosa", "eso que", "el que", "la que",
}


def _detectar_referencia_pronominal(texto: str) -> bool:
    """Detecta si el mensaje usa un pronombre/referencia que apunta a algo
    mencionado antes, sin nombrarlo explícitamente."""
    txt = texto.lower().strip()
    palabras = txt.split()
    if len(palabras) <= 6:
        if any(p in txt for p in _PRONOMBRES_REFERENCIA):
            return True
    return False


def _entidad_mas_relevante(excluir_ultimo_n: int = 0) -> str:
    """Devuelve el texto original de la entidad con mayor score de relevancia
    (frecuencia * peso_recencia). Útil para resolver 'eso', 'ábrelo', etc."""
    if not _entidades_sesion:
        return ""
    total_msgs = max(1, len(_historial_sesion_actual()))
    mejor, mejor_score = None, -1
    for clave, datos in _entidades_sesion.items():
        recencia = datos["ultima_mencion"] / total_msgs  # 0..1, más reciente = más alto
        score = datos["frecuencia"] * (0.4 + 0.6 * recencia)
        if score > mejor_score:
            mejor_score = score
            mejor = datos["texto"]
    return mejor or ""


def _actualizar_resumen_contexto() -> str:
    temas = _extraer_temas_recientes()
    resumen = ""
    if temas:
        resumen = "Temas recientes: " + ", ".join(temas) + "."
    historial_sesion = _historial_sesion_actual()
    if historial_sesion:
        ultimo_usuario = next((h.get('texto', '') for h in reversed(historial_sesion) if h.get('rol') == 'usuario'), '')
        ultimo_jarvis = next((h.get('texto', '') for h in reversed(historial_sesion) if h.get('rol') == 'jarvis'), '')
        resumen += f" Última pregunta: {ultimo_usuario[:120]}. Última respuesta: {ultimo_jarvis[:120]}."
    memoria_usuario['resumen_contexto'] = resumen.strip()
    memoria_usuario['ultimo_tema'] = temas[0] if temas else None
    _guardar_memoria(memoria_usuario)
    return memoria_usuario['resumen_contexto']


def _es_extension_respuesta(texto: str) -> bool:
    """Detecta si el usuario pide una extensión/ampliación de la respuesta anterior."""
    if not texto or not isinstance(texto, str):
        return False
    
    txt_lower = texto.lower().strip()
    
    # Palabras clave para detectar extensiones
    _PALABRAS_EXTENSION = {
        "extiéndelo", "extendelo", "extiendelo", "extenderlo",
        "continúa", "continua", "continualo", "sigue", "síguele", "sigueme",
        "cuéntame más", "dime más", "dame más", "más detalles", "con más detalles",
        "profundiza", "profundizar", "profundizalo", "profundizaré", "profundízalo",
        "amplía", "amplia", "amplialo", "ampliáselo", "expande", "expandelo",
        "elabora", "elaboralo", "desarrolla", "desarrollalo", "desarrollaré",
        "detallalo", "detalla más", "más información", "más info",
        "ahonda", "ahondalo", "y qué más", "qué más hay", "qué más",
        "todo", "cuéntame todo", "explica más", "explícalo más",
        "profundidad", "más profundo", "mucho más", "sigue contando",
        "y eso", "y al respecto", "y qué implica", "y entonces",
    }
    
    # Búsqueda directa de palabras clave
    for palabra in _PALABRAS_EXTENSION:
        if palabra in txt_lower:
            return True
    
    # Patrones regex adicionales para frases más complejas
    patrones = [
        r'(cuéntame|dime|dame|explica|desarrolla|profundiza|expande|amplia|extiende|continua|sigue)\s+(?:más|todo|detalles)',
        r'\b(más|todo|eso|anterior|lo anterior|la anterior|eso que dijiste)\b',
        r'(?:con|en|de)\s+(más|mayor)\s+(detalle|profundidad|información)',
    ]
    
    for patron in patrones:
        if re.search(patron, txt_lower):
            return True
    
    # Si el mensaje es muy corto (1-3 palabras) y contiene palabras clave de continuación
    words = txt_lower.split()
    if len(words) <= 3:
        continuacion_simple = {"más", "todo", "continúa", "sigue", "extiende", "elabora", "profundiza"}
        if any(w in continuacion_simple for w in words):
            return True
    
    return False

def _obtener_ultima_respuesta_jarvis() -> str:
    """Extrae la última respuesta completa de Jarvis del historial de la SESIÓN ACTUAL."""
    for h in reversed(_historial_sesion_actual()):
        if h.get('rol') == 'jarvis':
            texto = h.get('texto', '')
            # Remover etiquetas HTML/JSON si existen
            texto_limpio = re.sub(r'<[^>]+>', '', texto)
            texto_limpio = re.sub(r'\[\{"accion".*', '', texto_limpio)
            return texto_limpio.strip() if texto_limpio else texto
    return ""

def _obtener_contexto_conversacional_profundo(mensaje_actual: str = "") -> str:
    """Construye contexto conversacional profundo usando el motor de entidades
    persistente (frecuencia + recencia), limitado a la SESIÓN ACTUAL.
    Si el mensaje actual usa una referencia pronominal ('eso', 'ábrelo', etc.),
    resuelve explícitamente a qué entidad se refiere."""
    historial_sesion = _historial_sesion_actual()
    if not historial_sesion:
        return ""

    _reconstruir_entidades_sesion()

    contexto_partes = []

    # Resolver referencia pronominal explícita si aplica
    if mensaje_actual and _detectar_referencia_pronominal(mensaje_actual):
        referente = _entidad_mas_relevante()
        if referente:
            contexto_partes.append(
                f"[RESOLUCIÓN DE REFERENCIA]: el usuario usa una palabra como 'eso'/'ábrelo' "
                f"que probablemente se refiere a: {referente}"
            )

    # Top entidades por score (frecuencia ponderada por recencia)
    if _entidades_sesion:
        total_msgs = max(1, len(historial_sesion))
        scored = []
        for clave, datos in _entidades_sesion.items():
            recencia = datos["ultima_mencion"] / total_msgs
            score = datos["frecuencia"] * (0.4 + 0.6 * recencia)
            scored.append((datos["texto"], score, datos["frecuencia"]))
        scored.sort(key=lambda x: x[1], reverse=True)
        # Solo entidades mencionadas más de una vez o muy recientes
        relevantes = [s[0] for s in scored if s[2] > 1][:4]
        if not relevantes and scored:
            relevantes = [scored[0][0]]
        if relevantes:
            contexto_partes.append(f"[ENTIDADES RELEVANTES]: {', '.join(relevantes)}")

    # Palabras clave temáticas (sustantivos frecuentes, con stopwords completas)
    palabras_clave = {}
    for h in historial_sesion[-20:]:
        texto = h.get('texto', '').lower()
        for palabra in re.findall(r'\b[a-záéíóúñ]{4,}\b', texto):
            if palabra not in _STOPWORDS_ES and len(palabra) >= 5:
                palabras_clave[palabra] = palabras_clave.get(palabra, 0) + 1
    temas_top = [p for p, c in sorted(palabras_clave.items(), key=lambda x: x[1], reverse=True) if c > 1][:3]
    if temas_top:
        contexto_partes.append(f"[TEMA RECIENTE]: {', '.join(temas_top)}")

    # Última pregunta y respuesta
    ultimos_20 = historial_sesion[-20:]
    ultimo_usuario = next((h.get('texto', '') for h in reversed(ultimos_20) if h.get('rol') == 'usuario'), '')
    if ultimo_usuario:
        contexto_partes.append(f"[ÚLTIMA PREGUNTA]: {ultimo_usuario[:150]}")

    return "\n".join(contexto_partes)




def _formatear_historial(pregunta: str = "") -> str:
    if not _historial:
        return "(sin historial)"

    _actualizar_resumen_contexto()
    lineas = [f"[resumen] {memoria_usuario.get('resumen_contexto', '')}" ] if memoria_usuario.get('resumen_contexto') else []

    # CRÍTICO: el transcript crudo que se le muestra al modelo se limita a la
    # SESIÓN ACTUAL. Así, un tema viejo y sin relación de una sesión ya cerrada
    # nunca se mezcla con una pregunta nueva en una sesión recién iniciada.
    historial_sesion = _historial_sesion_actual()

    if not historial_sesion:
        lineas.append("(sesión nueva, sin mensajes previos todavía)")
        return "\n".join(lineas)

    # Obtener últimos 80 mensajes de la sesión actual
    ultimos_80 = historial_sesion[-80:]
    
    # Buscar la ÚLTIMA respuesta de Jarvis (de atrás hacia adelante)
    ultima_respuesta_jarvis_idx = None
    for i in range(len(ultimos_80) - 1, -1, -1):
        if ultimos_80[i].get('rol') == 'jarvis':
            ultima_respuesta_jarvis_idx = i
            break
    
    for i, h in enumerate(ultimos_80):
        rol_label = "USUARIO" if h['rol'] == 'usuario' else "JARVIS"
        texto = re.sub(r'\s+', ' ', str(h.get('texto', ''))).strip()
        if texto:
            # Marcar la ÚLTIMA respuesta de Jarvis claramente
            if i == ultima_respuesta_jarvis_idx:
                lineas.append(f"[{h.get('ts', '--:--')}] {rol_label} [ÚLTIMA RESPUESTA]: {texto}")
            else:
                lineas.append(f"[{h.get('ts', '--:--')}] {rol_label}: {texto}")
    
    # Agregar nota sobre continuidad si hay historial muy antiguo (de esta misma sesión)
    if len(historial_sesion) > 80:
        lineas.insert(1, f"--- (Historial previo de esta sesión: {len(historial_sesion) - 80} mensajes anteriores no mostrados) ---")
    
    return "\n".join(lineas)

def _aprender_del_usuario(texto: str):
    global memoria_usuario
    txt = texto.lower()
    aprendio = False
    _PATRONES_MEM = [
        ("nombre",  r'(?:me llamo|mi nombre es|soy|llámame)\s+([A-ZÁÉÍÓÚÑa-záéíóúñ]{2,20})\b'),
        ("ciudad",  r'(?:vivo en|soy de|estoy en|mi ciudad es)\s+([A-ZÁÉÍÓÚÑa-záéíóúñ\s]{2,30}?)(?:\s*,|\s*$)'),
        ("trabajo", r'(?:trabajo en|trabajo para|mi empresa es)\s+([A-ZÁÉÍÓÚÑa-záéíóúñ\s]{2,40}?)(?:\s*,|\s*$)'),
        ("edad",    r'(?:tengo|cumplí)\s+(\d{1,2})\s+años'),
    ]
    for campo, pat in _PATRONES_MEM:
        if not memoria_usuario.get(campo):
            m = re.search(pat, texto, re.IGNORECASE)
            if m:
                valor = m.group(1).strip().capitalize()
                memoria_usuario[campo] = valor
                aprendio = True

    if 'me gusta' in txt or 'me encanta' in txt or 'prefiero' in txt:
        preferencia = re.sub(r'^(me gusta|me encanta|prefiero)\s+', '', txt)
        preferencia = re.sub(r'\bque\b', '', preferencia).strip()
        if preferencia:
            memoria_usuario.setdefault('preferencias', {})['gusto'] = preferencia[:80]
            aprendio = True
    if 'no me gusta' in txt or 'odio' in txt:
        dislike = re.sub(r'^(no me gusta|odio)\s+', '', txt).strip()
        if dislike:
            memoria_usuario.setdefault('preferencias', {})['evito'] = dislike[:80]
            aprendio = True
    if 'recuerda que' in txt or 'no olvides que' in txt or 'anota que' in txt:
        detalle = re.sub(r'^(recuerda que|no olvides que|anota que)\s+', '', txt).strip()
        memoria_usuario.setdefault('extras', {})['recordatorio_pasivo'] = detalle[:160]
        aprendio = True

    if aprendio:
        _guardar_memoria(memoria_usuario)
        _actualizar_resumen_contexto()

def _contexto_actual(mensaje_actual: str = "") -> str:
    m = memoria_usuario
    partes = []
    # Resumen breve del contexto conversacional para ayudar al razonamiento del modelo.
    _actualizar_resumen_contexto()
    tema_actual = memoria_usuario.get('ultimo_tema') or "conversación general"
    if not memoria_usuario.get('resumen_contexto') and _historial:
        tema_actual = "conversación general"
    if m.get("nombre"):  partes.append(f"nombre: {m['nombre']}")
    if m.get("ciudad"):  partes.append(f"ciudad: {m['ciudad']}")
    if m.get("trabajo"): partes.append(f"trabajo: {m['trabajo']}")
    if m.get("edad"):    partes.append(f"edad: {m['edad']}")
    usuario_str = "Usuario — " + ", ".join(partes) + "." if partes else "Usuario: datos desconocidos."
    n_apps = len(MAPA_SISTEMA)
    resumen_ctx = memoria_usuario.get('resumen_contexto', '').strip()
    preferencias = memoria_usuario.get('preferencias', {}) or {}
    prefs_txt = ""
    if preferencias:
        prefs_txt = " Preferencias detectadas: " + "; ".join(f"{k}={v}" for k, v in preferencias.items()) + "."
    
    # CONTEXTO CONVERSACIONAL PROFUNDO (ultra-mejorado para detectar temas y entidades)
    contexto_profundo = _obtener_contexto_conversacional_profundo(mensaje_actual)
    contexto_profundo_txt = f"\n{contexto_profundo}" if contexto_profundo else ""
    
    # Información sobre continuidad conversacional
    continuidad = ""
    n_msgs_sesion = len(_historial_sesion_actual())
    if n_msgs_sesion > 80:
        continuidad = f" [NOTA: Conversación activa con {n_msgs_sesion} mensajes en esta sesión — recuerda temas antiguos cuando el usuario los mencione de nuevo]"
    
    return (
        f"{usuario_str}\n"
        f"Tema reciente: {tema_actual}.\n"
        f"Resumen del chat: {resumen_ctx if resumen_ctx else 'Sin resumen aún.'}\n"
        f"{prefs_txt}\n"
        f"Idioma: {m.get('idioma','español colombiano')}. "
        f"Zona horaria: UTC-5.\n"
        f"Apps conocidas: {n_apps} apps escaneadas.\n"
        f"Modos: {', '.join(modos.keys())}.\n"
        f"Fecha/hora: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"
        f"{continuidad}\n"
        f"{contexto_profundo_txt}\n"
    )

# =============================================================================
# 9. PROMPT DEL SISTEMA — incluye herramientas de TODOS los agentes
# =============================================================================

_HERRAMIENTAS = """
# AGENTE PC (agent_pc)
- abrir_app        {nombre}          → abre una aplicación
- cerrar_app       {nombre}          → cierra una app por ventana
- minimizar_app    {nombre}          → minimiza ventana
- maximizar_app    {nombre}          → maximiza ventana
- subir_volumen    {porcentaje?}     → sube volumen (def: 10)
- bajar_volumen    {porcentaje?}     → baja volumen
- poner_volumen    {porcentaje}      → volumen absoluto 0-100
- mute                               → silenciar/desilenciar
- subir_brillo     {porcentaje?}     → sube brillo
- bajar_brillo     {porcentaje?}     → baja brillo
- apagar                             → apagar el PC
- reiniciar                          → reiniciar el PC
- bloquear                           → bloquear sesión
- suspender                          → suspender el PC
- modo             {nombre}          → activar modo de trabajo (gaming, estudio, programacion)
- buscar_archivo   {termino}         → buscar y abrir archivo en disco

# AGENTE BÚSQUEDA (agent_search)
- buscar_web       {pregunta}        → buscar información en internet
- mostrar_mapa     {lugar}           → mostrar mapa interactivo de un lugar dentro de Jarvis (ciudades, países, direcciones)
- abrir_url        {consulta}        → abrir página web específica (ej: "página oficial de SpaceX", "noticias Caracol", "YouTube", "Instagram de NASA")
- noticias         {tema?, categoria?}→ noticias recientes
- clima            {ciudad?}         → clima actual (def: Bogotá)
- calcular         {expresion}       → calcular expresión matemática

# AGENTE IMÁGENES (agent_images)
- buscar_imagen    {termino, max_imgs?} → buscar imágenes del tema
- generar_imagen   {prompt}          → generar imagen con IA (pendiente API)

# AGENTE GOOGLE (agent_google)
- gmail_leer       {max_msgs?}       → leer bandeja de entrada
- gmail_buscar     {consulta}        → buscar correos
- gmail_enviar     {destinatario, asunto, cuerpo} → enviar email
- gmail_eliminar   {consulta}        → eliminar correos
- ver_eventos                        → ver eventos de Google Calendar
- crear_evento     {nombre, fecha?, hora?} → crear evento
- editar_evento    {nombre_buscar, nombre_nuevo?, fecha?, hora?}
- eliminar_evento  {nombre_buscar}
- ver_tareas                         → ver Google Tasks
- crear_tarea      {titulo, fecha?}
- editar_tarea     {titulo_buscar, titulo_nuevo?, fecha?}
- eliminar_tarea   {titulo_buscar}
- buscar_contacto  {nombre}          → buscar en Google Contacts
- drive_buscar     {consulta}        → buscar en Google Drive

# AGENTE NOTAS (agent_notas)
- nota_crear       {contenido, titulo?} → guardar una nota
- nota_leer        {id?, titulo?}    → leer notas (sin params = todas)
- nota_buscar      {termino}         → buscar en notas
- nota_editar      {id|titulo, contenido?, titulo_nuevo?}
- nota_eliminar    {id|titulo}
- alarma_crear     {hora, etiqueta?, repetir?} → hora: "07:30" o "en 20 minutos"
- alarma_listar                      → ver alarmas activas
- alarma_eliminar  {id|etiqueta}
- recordatorio_crear {texto, fecha_hora?, minutos?}
- recordatorio_listar
- recordatorio_eliminar {id|texto}
- memoria_guardar  {clave, valor}    → guardar dato en memoria de sesión
- memoria_leer     {clave?}          → leer memoria de sesión
- memoria_resumir                    → resumen de todo lo que Jarvis recuerda
- memoria_limpiar                    → borrar memoria de sesión

# AGENTE PANTALLA (observación y control explícito)
- ver_pantalla                                         → abrir el visor de pantalla en tiempo real
- analizar_pantalla                                    → describir visualmente la pantalla actual
- hacer_click         {x?, y?, boton?, clicks?}          → hacer clic en las coordenadas dadas o en el cursor actual
- hacer_zoom          {cantidad?}                       → zoom in/out en la ventana activa
- escribir            {texto, intervalo?}              → escribir en la ventana activa
- pulsar_tecla        {tecla}                          → pulsar una tecla permitida
- desplazarse         {cantidad, x?, y?}               → desplazar la ventana activa

# RESPUESTA DIRECTA
- responder        {texto}           → responder en HTML al usuario (párrafo <p>, tabla <table> o lista <ul>, según el dato)
"""

_PROMPT_SISTEMA_TEMPLATE = (
    "Eres J.A.R.V.I.S., asistente de IA personal. Hablas con tono formal, cortés y profesional, como Jarvis de Iron Man. "
    "Evita modismos, jerga de la calle, expresiones como 'parce', 'bro', 'mano' o similares.\n\n"
    "Tu trabajo: INTERPRETAR lo que pide el usuario y devolver UN ARRAY JSON de acciones.\n\n"
    "HISTORIAL (últimos turnos de la conversación):\nHISTORIAL_PLACEHOLDER\n\n"
    "CONTEXTO (resumen de temas, lugares, personas y preferencias recordadas):\nCONTEXTO_PLACEHOLDER\n\n"
    "HERRAMIENTAS DISPONIBLES:\nHERRAMIENTAS_PLACEHOLDER\n\n"
    "REGLAS CRÍTICAS:\n"
    "1. Devuelve SOLO el JSON array. Empieza con [ y termina con ]. NUNCA objeto suelto.\n"
    "2. Para texto usa HTML: <p>, <b>, <ul><li>. NUNCA markdown. NUNCA <h3> ni títulos en respuestas conversacionales.\n"
    "3. Comillas dobles ASCII siempre.\n"
    "4. MULTI-COMANDO: si el usuario pide varias cosas, devuelve todas en el mismo array.\n"
    '   Ej: "abre spotify y sube el volumen" → [{"accion":"abrir_app","params":{"nombre":"spotify"}},{"accion":"subir_volumen","params":{"porcentaje":20}}]\n'
    "5. ⭐⭐⭐ EXTENSIONES Y CONTINUACIONES: REGLA ABSOLUTAMENTE CRÍTICA ⭐⭐⭐\n"
    "   DETECCIÓN: Si el usuario dice: 'extiéndelo', 'más detalles', 'cuéntame más', 'continúa', 'profundiza', 'amplia', 'sigue', etc.\n"
    "   ACCIÓN REQUERIDA: SIEMPRE expande tu respuesta anterior. NUNCA JAMÁS pidas 'proporciona más información'.\n"
    "   ¿POR QUÉ? Porque el usuario YA te dio contexto. Dice 'cuéntame más' sobre LO QUE ACABO DE CONTAR. No necesita dar más detalles.\n"
    "   CÓMO EXPANDIR:\n"
    "      1. Lee la respuesta anterior en el historial (marca [ÚLTIMA RESPUESTA])\n"
    "      2. Ahora DESARROLLA esa respuesta con:\n"
    "         • Ejemplos nuevos y CONCRETOS (números, fechas, nombres reales)\n"
    "         • Argumentos más PROFUNDOS y COMPLEJOS\n"
    "         • Conexiones con otros temas\n"
    "         • Implicaciones y consecuencias (¿qué pasa si...?)\n"
    "         • Detalles técnicos, históricos o contextuales\n"
    "         • Comparaciones y contrastes\n"
    "      3. NO repitas lo ya dicho. COMPLEMENTA y ELABORA.\n"
    "   ⛔ PROHIBIDO:\n"
    "      ❌ 'Proporciona más información...'\n"
    "      ❌ 'Para poder ayudarte mejor...'\n"
    "      ❌ '¿Podrías decirme...?'\n"
    "      ❌ Repetir lo ya dicho\n"
    "      ❌ Pedir aclaraciones cuando ya hay contexto suficiente\n"
    "   ✅ PERMITIDO: Expandir, profundizar, agregar ejemplos, conectar con otros temas\n"
    "6. ⭐⭐ MEMORIA CONVERSACIONAL ULTRA-PROFUNDA (CRÍTICO) ⭐⭐\n"
    "   CONTEXTO PERSISTENTE: Recuerda TODOS los tópicos, películas, series, libros, personas, lugares mencionados en la CONVERSACIÓN COMPLETA.\n"
    "      • Usuario preguntó sobre 'Avengers Doomsday' hace 5 mensajes.\n"
    "      • Luego preguntó sobre otros temas.\n"
    "      • Ahora solo dice 'cuéntame más' → Entiende que se refiere a 'Avengers Doomsday'.\n"
    "   REFERENCIAS PRONOMINALES: 'eso', 'ese', 'él/ella', 'ábrelo', 'el primero', 'la anterior', 'lo que dijiste'\n"
    "      → Busca en TODO el historial qué fue lo último mencionado de ese tipo.\n"
    "      → Si el CONTEXTO incluye una línea '[RESOLUCIÓN DE REFERENCIA]: ...', el sistema YA calculó "
    "a qué entidad se refiere el pronombre. ÚSALA directamente, no preguntes 'a qué te refieres'.\n"
    "      → Si el CONTEXTO incluye '[ENTIDADES RELEVANTES]: ...', son los temas/nombres más mencionados "
    "recientemente — úsalos para desambiguar antes de pedir aclaración.\n"
    "   CONEXIONES TEMÁTICAS: Si mencionó películas Marvel → luego pregunta sobre superhéroes → CONECTA ambas.\n"
    "   TEMA DOMINANTE: Mantén el tema actual a menos que haya cambio EXPLÍCITO de tema.\n"
    "   ENTIDADES: Recuerda nombres (actores, directores, personajes, ciudades) mencionados anteriormente.\n"
    "7. RESPUESTAS VARIADAS, NATURALES Y CONVERSACIONALES:\n"
    "   ▪ Estructura Título: valor es PROHIBIDA.\n"
    "   ▪ Escribe como persona real, no como máquina. Usa transiciones naturales.\n"
    "   ▪ MAL: 'Ubicación: Ártico. Dieta: focas. Tamaño: 3m.'\n"
    "   ▪ BIEN: 'Viven en el Ártico donde se alimentan principalmente de focas. "
    "Son animales enormes, pueden alcanzar hasta 3 metros de largo.'\n"
    "8. ROUTING DE AGENTES:\n"
    "   ▪ Apps/volumen/brillo/PC → abrir_app, subir_volumen, etc.\n"
    "   ▪ Buscar/investigar/noticias/clima/mapas → buscar_web/noticias/clima/mostrar_mapa.\n"
    "   ▪ Fotos/imágenes de temas → buscar_imagen (SIEMPRE usa esto para imágenes)\n"
    "   ▪ Notas/alarmas/recordatorios → agente notas.\n"
    "   ▪ Correo/calendar/tareas → agente google.\n"
    "9. MAPAS INTELIGENTES: cuando usuario pide 'mostrar', 'mapa', 'dónde está'\n"
    "   → usa mostrar_mapa con el NOMBRE MÁS COMPLETO posible:\n"
    "   Ej: 'Andrés Carne de Res en Chía', 'Torre Eiffel en París', 'Calle 93 Bogotá'\n"
    "10. ANTI-REPETICIÓN: si historial muestra '[ejecutado: X]' para el MISMO comando anterior,\n"
    "    NO lo repitas sin motivo nuevo o sin que el usuario lo pida explícitamente.\n"
    "11. NO incluyas 'responder' ANTES de acciones que hablan por sí solas:\n"
    "    nota_leer, nota_buscar, ver_tareas, ver_eventos, gmail_leer, gmail_buscar,\n"
    "    alarma_listar, recordatorio_listar, memoria_resumir, memoria_leer, drive_buscar,\n"
    "    buscar_imagen, buscar_web, noticias, clima, mostrar_mapa.\n"
    "12. RESPUESTAS DE VOZ: máximo 2 oraciones. RESPUESTAS DE CHAT: puedes dar más detalle en HTML.\n"
    "13. ESTRUCTURA JSON VÁLIDA: NUNCA devuelvas HTML suelto.\n"
    "    ▪ Tu respuesta SIEMPRE debe ser un array JSON válido.\n"
    "    ▪ Si quieres responder, DEBE ser: [{\"accion\":\"responder\",\"params\":{\"texto\":\"<p>tu texto</p>\"}}]\n"
    "    ▪ El texto debe ser HTML: máximo 3 oraciones o 4 bullets, máximo 400 caracteres.\n"
    "    ▪ CRÍTICO: NUNCA empieces con '<p>', '<b>', markdown o texto libre. SIEMPRE empieza con '['.\n"
    "14. COMBINACIONES INTELIGENTES: si usuario dice 'busca sobre el Ártico y muestra un mapa',\n"
    "    devuelve: buscar_web + mostrar_mapa. PERO si dice 'muéstrame fotos del Ártico',\n"
    "    devuelve: buscar_imagen (no buscar_web).\n"
    "15. BÚSQUEDA DE LUGARES CON CONTEXTO:\n"
    "    ▪ 'Muéstrame un mapa' + contexto previo → usar lugar previo\n"
    "    ▪ 'Mapa de [lugar]' → usar [lugar]\n"
    "    ▪ 'El lugar que mencioné' → buscar en historial\n"
    "16. ⭐ FORMATO INTELIGENTE DE RESPUESTAS — elige SIEMPRE el formato que mejor represente el dato:\n"
    "    ▪ Datos tabulares (calendarios, horarios, fechas de eventos/carreras, comparativas, estadísticas, precios) "
    "→ usa SIEMPRE una <table> HTML con <tr><th>...</th></tr> y filas <tr><td>...</td></tr>. NUNCA los listes con guiones o asteriscos sueltos.\n"
    "    ▪ Listas cortas de datos puntuales (3+ ítems sin estructura de columnas) → usa <ul><li> real.\n"
    "    ▪ Texto narrativo (películas, biografías, explicaciones, resúmenes, historia) → usa <p> fluido, sin títulos ni bullets.\n"
    "    ▪ Si el usuario pide 'fuentes APA 7', 'referencias APA', 'bibliografía', 'citas' o 'fuentes', "
    "incluye una lista de referencias cuando sea posible y no inventes datos.\n"
    "    ▪ PROHIBIDO ABSOLUTO: nunca generes viñetas escribiendo '*' o '-' como texto plano. Si necesitas una lista, "
    "es HTML real: <ul><li>. Un asterisco o guion suelto en el texto se LEE EN VOZ ALTA como 'asterisco' o 'guion', "
    "así que jamás debe aparecer fuera de una etiqueta HTML.\n\n"
    "EJEMPLOS:\n"
    '[{"accion":"abrir_app","params":{"nombre":"spotify"}},{"accion":"subir_volumen","params":{"porcentaje":20}}]\n'
    '[{"accion":"buscar_web","params":{"pregunta":"clima en Bogotá hoy"}}]\n'
    '[{"accion":"mostrar_mapa","params":{"lugar":"Catedral de Notre-Dame París"}}]\n'
    '[{"accion":"buscar_imagen","params":{"termino":"osos polares en su hábitat","max_imgs":5}}]\n'
    '[{"accion":"responder","params":{"texto":"<p>Los osos polares viven en el Ártico y son nadadores excepcionales.</p>"}}]\n'
    '[{"accion":"responder","params":{"texto":"<table><tr><th>Carrera</th><th>Fecha</th><th>Circuito</th></tr><tr><td>GP de Austria</td><td>29 jun</td><td>Red Bull Ring</td></tr><tr><td>GP de Mónaco</td><td>25 may</td><td>Circuit de Monaco</td></tr></table>"}}]\n'
    '[{"accion":"mostrar_mapa","params":{"lugar":"Calle 93 Bogotá Colombia"}}]\n'
)

def _construir_prompt(historial: str, contexto: str) -> str:
    """Construye el prompt del sistema sin usar .format() para evitar KeyError con llaves en _HERRAMIENTAS."""
    return (
        _PROMPT_SISTEMA_TEMPLATE
        .replace("HISTORIAL_PLACEHOLDER", historial)
        .replace("CONTEXTO_PLACEHOLDER", contexto)
        .replace("HERRAMIENTAS_PLACEHOLDER", _HERRAMIENTAS)
    )

# =============================================================================
# 9.5. SERVIDOR HTTP LOCAL (para evitar CORS issues)
# =============================================================================
class LocalHTTPHandler(BaseHTTPRequestHandler):
    """Manejador HTTP que sirve archivos estáticos con CORS headers."""

    def do_GET(self):
        """Servir archivos GET con CORS headers."""
        try:
            # Remover query string para la ruta, pero guardar parámetros
            full_path = self.path
            path = full_path.split('?')[0]
            print(f"[HTTP] GET {path}")

            # ===== API ENDPOINTS =====
            if path.startswith('/api/search-image'):
                # Endpoint para buscar imágenes (deshabilitado temporalmente)
                response = json.dumps({'success': False, 'image_url': None})
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Content-Length', str(len(response)))
                self.end_headers()
                self.wfile.write(response.encode('utf-8'))
                return

            # ===== ARCHIVOS ESTÁTICOS =====
            # Ruta del archivo
            file_path = os.path.join(base_path, path.lstrip('/'))
            file_path = os.path.normpath(file_path)

            # Seguridad: no permitir traversal fuera del directorio base
            if not file_path.startswith(os.path.normpath(base_path)):
                print(f"[HTTP] ✗ Acceso denegado (traversal): {file_path}")
                self.send_error(403, "Access denied")
                return

            # Si es un directorio, servir V5.html por defecto
            if os.path.isdir(file_path):
                file_path = os.path.join(file_path, "V5.html")
                print(f"[HTTP] Directorio detectado, sirviendo V5.html: {file_path}")

            # Servir el archivo
            if os.path.exists(file_path) and os.path.isfile(file_path):
                with open(file_path, 'rb') as f:
                    content = f.read()

                # Determinar el content type
                if file_path.endswith('.html'):
                    content_type = 'text/html; charset=utf-8'
                elif file_path.endswith('.js'):
                    content_type = 'application/javascript'
                elif file_path.endswith('.css'):
                    content_type = 'text/css'
                elif file_path.endswith('.json'):
                    content_type = 'application/json'
                elif file_path.endswith('.png'):
                    content_type = 'image/png'
                elif file_path.endswith('.jpg') or file_path.endswith('.jpeg'):
                    content_type = 'image/jpeg'
                elif file_path.endswith('.gif'):
                    content_type = 'image/gif'
                elif file_path.endswith('.svg'):
                    content_type = 'image/svg+xml'
                else:
                    content_type = 'application/octet-stream'

                self.send_response(200)
                self.send_header('Content-Type', content_type)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
                self.send_header('Pragma', 'no-cache')
                self.send_header('Expires', '0')
                self.send_header('Content-Length', str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                print(f"[HTTP] ✓ Sirviendo {os.path.basename(file_path)} ({len(content)} bytes)")
            else:
                print(f"[HTTP] ✗ Archivo no encontrado: {file_path}")
                self.send_error(404, "File not found")
        except Exception as e:
            print(f"[HTTP] ✗ Error sirviendo {self.path}: {e}")
            self.send_error(500, "Internal server error")

    def do_OPTIONS(self):
        """Manejar preflight CORS requests."""
        print(f"[HTTP] OPTIONS {self.path}")
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def log_message(self, format, *args):
        """Silenciar logs HTTP normales (ya tenemos logging personalizado)."""
        pass

class LocalHTTPServer:
    """Servidor HTTP local para servir V5.html sin problemas de CORS."""

    def __init__(self, port=9999):
        self.port = port
        self.server = None
        self.thread = None

    def start(self):
        """Iniciar el servidor en un hilo daemon."""
        try:
            self.server = HTTPServer(('127.0.0.1', self.port), LocalHTTPHandler)
            print(f"[HTTP] Servidor iniciado en http://127.0.0.1:{self.port}")

            self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.thread.start()
            return True
        except Exception as e:
            print(f"[HTTP] Error iniciando servidor: {e}")
            return False

    def stop(self):
        """Detener el servidor."""
        if self.server:
            self.server.shutdown()

_http_server = None

# =============================================================================
# 10. BRIDGE Qt (señales cross-thread)
# =============================================================================

class _UIBridge(QObject):
    append_html = Signal(str)
    scroll_down = Signal()
    quit_app    = Signal()
    append_to_v5_chat = Signal(str)
    append_to_v5_map  = Signal(float, float, str, str, bool)  # lat, lon, nombre, info_html, mostrar_anillos
    open_config_dialog = Signal()  # abre VentanaConfig desde botón V5
    open_commands_dialog = Signal()
    open_extensions_dialog = Signal()
    show_screen_overlay = Signal()  # abre el visor desde el hilo Qt principal
    analyze_screen = Signal(str)  # analiza después de que el stream tenga un frame

_bridge = _UIBridge()
_webview_ref = None  # Referencia global al WebView para inyectar JS
_v5_ready = False
_v5_pending_messages = []


def _vaciar_pendientes_v5():
    """Inyecta mensajes pendientes cuando la webview ya está lista."""
    global _v5_pending_messages
    if _webview_ref is None:
        return
    while _v5_pending_messages:
        html_content = _v5_pending_messages.pop(0)
        _ejecutar_js_v5(html_content)


def _inyectar_en_v5(html_content: str):
    """Thread-safe: encola el contenido hasta que la webview esté lista."""
    global _v5_ready, _v5_pending_messages
    if not html_content:
        return
    if not _v5_ready or _webview_ref is None:
        _v5_pending_messages.append(html_content)
        return
    _bridge.append_to_v5_chat.emit(html_content)


# Connect append_html globally to ensure V5 receives messages even if UI
# instance connects later. This is idempotent if JarvisUI also connects.
try:
    _bridge.append_html.connect(_inyectar_en_v5)
except Exception:
    pass


def _ejecutar_js_v5(html_content: str):
    """Ejecuta el JS en V5.html. SOLO llamar desde el hilo Qt principal (via señal)."""
    global _webview_ref
    if _webview_ref is None:
        return
    try:
        if html_content == "__RESET_MIC__":
            _webview_ref.page().runJavaScript(
                'if(window.micBtn){window.micBtn.classList.remove("active");}'
                'if(window.voiceBars){window.voiceBars.classList.remove("active");}'
            )
            return
        if html_content == "__ACTIVATE_MIC__":
            _webview_ref.page().runJavaScript(
                'if(window.micBtn){window.micBtn.classList.add("active");}'
                'if(window.voiceBars){window.voiceBars.classList.add("active");}'
            )
            return

        js_payload = json.dumps(html_content)
        script = (
            f"(function(){{"
            f"const payload = {js_payload};"
            f"console.log('[Jarvis Main] inject payload len=' + payload.length);"
            f"if (window.jarvisAppendHtmlDirect) {{ const result = window.jarvisAppendHtmlDirect(payload); console.log('[Jarvis Main] jarvisAppendHtmlDirect ->', result); return; }}"
            f"const root = document.getElementById('chatBox');"
            f"if (!root) {{ console.warn('[Jarvis Main] chatBox not found'); return; }}"
            f"const div = document.createElement('div');"
            f"div.className = 'msg ai';"
            f"const time = new Date().toLocaleTimeString('es-ES', {{hour:'2-digit', minute:'2-digit'}});"
            f"div.innerHTML = payload + '<span class=\"msg-time\">' + time + '</span>';"
            f"root.appendChild(div);"
            f"setTimeout(function(){{ root.scrollTop = root.scrollHeight; }}, 50);"
            f"}})();"
        )
        _webview_ref.page().runJavaScript(script)
    except Exception as e:
        print(f"[V5] Error JS: {e}")


def _ejecutar_js_mapa_v5(lat: float, lon: float, nombre: str, info_html: str = "", anillos: bool = False):
    """Abre Google Maps una sola vez mediante el navegador externo, sin crear ventanas dobles."""
    try:
        query = (nombre or "lugar").strip() or f"{lat},{lon}"
        from urllib.parse import quote as _q
        url = f"https://www.google.com/maps/search/?api=1&query={_q(query)}"
        QDesktopServices.openUrl(QUrl(url))
        print(f"[V5 Mapa] Abriendo Google Maps: {query}")
    except Exception as e:
        print(f"[V5 Mapa] Error al abrir Google Maps    : {e}")


def _reset_v5_mic():
    """Thread-safe: emite señal para resetear el botón mic en el hilo Qt."""
    _bridge.append_to_v5_chat.emit("__RESET_MIC__")


def _ejecutar_reset_mic_js():
    """Solo llamar desde hilo Qt principal (conectado a señal)."""
    global _webview_ref
    if _webview_ref is None:
        return
    try:
        _webview_ref.page().runJavaScript(
            'if(window.micBtn){window.micBtn.classList.remove("active");}'
            'if(window.voiceBars){window.voiceBars.classList.remove("active");}'
        )
    except Exception as e:
        print(f"[V5] Error reset mic: {e}")


class JarvisWebPage(QWebEnginePage):
    """Intercepta esquemas jarvis:// en V5.html para ejecutar comandos."""

    def acceptNavigationRequest(self, url, navType, isMainFrame):
        esquema = url.scheme().lower()
        if esquema == "jarvis":
            comando = url.path().lstrip("/") or url.host()
            query = parse_qs(url.query())
            if comando == "cmd":
                texto = query.get("text", [""])[0]
                if texto == "__OPEN_CONFIG__":
                    # Abrir diálogo de configuración en el hilo Qt principal
                    _bridge.open_config_dialog.emit()
                    return False
                if texto == "__OPEN_COMMANDS__":
                    _bridge.open_commands_dialog.emit()
                    return False
                if texto == "__OPEN_EXTENSIONS__":
                    _bridge.open_extensions_dialog.emit()
                    return False
                if texto == "__CLOSE_JARVIS__":
                    # Cerrar solo Jarvis, no apagar el PC
                    hablar("Hasta luego.", None)
                    import time as _t
                    def _cerrar():
                        _t.sleep(1.2)
                        _bridge.quit_app.emit()
                    threading.Thread(target=_cerrar, daemon=True).start()
                    return False
                # Toggle rings UI from V5
                if texto == "__TOGGLE_RINGS__":
                    try:
                        if _webview_ref:
                            _webview_ref.page().runJavaScript('window.toggleRings && window.toggleRings();')
                    except Exception as _e:
                        print('[V5] toggle rings error', _e)
                    return False
                if texto:
                    print(f"[V5] comando jarvis recibido: {texto}")
                    threading.Thread(
                        target=interpretar_multiple,
                        args=(texto, None, False),
                        daemon=True
                    ).start()
                return False
            if comando == "open":
                # jarvis://open?url=ENCODED_URL  -> abrir en navegador mediante _abrir_url_especifica
                u = query.get("url", [""])[0]
                if u:
                    try:
                        from urllib.parse import unquote as _unq
                        _abrir_url_especifica(_unq(u))
                    except Exception as _e:
                        print('[V5] open url failed', _e)
                return False

        # Abrir en navegador externo solo enlaces remotos; permitir servidor local y archivos locales dentro del WebView
        if esquema in ("http", "https", "mailto", "tel", "ftp"):
            # Permitir que URLs del servidor HTTP local se carguen en la WebView
            host = url.host() or ""
            port = url.port() or 80
            if host in ("127.0.0.1", "localhost") and port == 9999:
                # Es del servidor local, permitir en WebView
                return True
            # Otros HTTP/HTTPS: abrir en navegador
            QDesktopServices.openUrl(url)
            return False
        if esquema == "file":
            # Permitir que el WebView cargue archivos locales (ej: V5.html)
            return True

        return super().acceptNavigationRequest(url, navType, isMainFrame)

    def createWindow(self, _type):
        """Intercepta target="_blank" y otras nuevas ventanas para abrirlas externamente."""
        temp_page = QWebEnginePage(self.profile(), self)
        temp_page.urlChanged.connect(lambda url: QDesktopServices.openUrl(url))
        return temp_page

# =============================================================================
# 11. DISPATCHER → _ejecutar_accion
# =============================================================================

import agent_search
import agent_images
import agent_pc
import agent_screen
import agent_google
import agent_notas

_ultima_vision_solicitud = 0.0
_vision_lock = threading.Lock()


def _analizar_pantalla_con_vision(chat_widget=None, pregunta=""):
    """Envía un frame efímero al modelo multimodal y devuelve la respuesta al chat."""
    global _ultima_vision_solicitud
    with _vision_lock:
        ahora = time.monotonic()
        if ahora - _ultima_vision_solicitud < 2.0:
            print("[Vision] Solicitud duplicada ignorada")
            return
        _ultima_vision_solicitud = ahora

    def _trabajo():
        try:
            def _mostrar_error(mensaje):
                _bridge.append_html.emit(_html_burbuja_jarvis(f"<b>Visión de pantalla</b><br>{_escape_html(mensaje)}"))
                _bridge.scroll_down.emit()

            if not _KEYS_LISTAS.is_set():
                _KEYS_LISTAS.wait(timeout=15)
            frame = agent_screen.obtener_ultimo_frame() or agent_screen.capturar_frame()
            if frame is None or (not _groq_keys and not _gemini_keys):
                _mostrar_error("No tengo un frame disponible o no hay una clave de visión activa.")
                return
            import base64
            from io import BytesIO
            frame.thumbnail((1280, 800))
            if frame.mode != "RGB":
                frame = frame.convert("RGB")
            buffer = BytesIO()
            frame.save(buffer, format="JPEG", quality=70, optimize=True)
            encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
            instruccion = pregunta or """Observa la pantalla como una persona que quiere entender qué está viendo el usuario y ayudarle. Responde en español, de forma natural y breve, con lo que tenga utilidad para comprender la pantalla: identifica la aplicación o página, el título principal, el contenido visible relevante, la acción principal y, si hay un artículo o texto, resume sus ideas importantes. No enumeres todo lo que aparece. Ignora URLs, direcciones web, rutas, nombres técnicos de enlaces, breadcrumbs, menús de navegación, botones genéricos, etiquetas repetitivas, categorías decorativas y elementos de interfaz que no aporten contexto. Solo menciona un enlace, menú o categoría si su texto es esencial para entender el tema o responder una pregunta del usuario. No leas literalmente cada elemento visible ni describas el overlay de Jarvis. Si algo no se puede leer, dilo claramente."""
            payload = {
                "model": "meta-llama/llama-4-maverick-17b-128e-instruct",
                "messages": [{"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}},
                    {"type": "text", "text": instruccion},
                ]}],
                "max_tokens": 1400,
                "temperature": 0.2,
            }
            texto = ""
            if not texto and _gemini_keys:
                gemini_payload = {
                    "contents": [{"parts": [
                        {"text": instruccion},
                        {"inline_data": {"mime_type": "image/jpeg", "data": encoded}},
                    ]}],
                    "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1400},
                }
                for modelo in ("gemini-2.5-flash", "gemini-2.0-flash"):
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent?key={_gemini_key_activa()}"
                    try:
                        gem_resp = requests.post(url, json=gemini_payload, timeout=30)
                        if gem_resp.status_code == 200:
                            partes = gem_resp.json().get("candidates", [{}])[0].get("content", {}).get("parts", [])
                            texto = "".join(p.get("text", "") for p in partes).strip()
                            if texto:
                                break
                        else:
                            print(f"[Vision/Gemini] {modelo} HTTP {gem_resp.status_code}: {gem_resp.text[:220]}")
                    except Exception as gem_exc:
                        print(f"[Vision/Gemini] {modelo}: {gem_exc}")

            if not texto and _groq_keys:
                for modelo in (
                    "meta-llama/llama-4-maverick-17b-128e-instruct",
                    "meta-llama/llama-4-scout-17b-16e-instruct",
                ):
                    payload["model"] = modelo
                    try:
                        resp = requests.post(
                            GROQ_BASE_URL,
                            json=payload,
                            headers={"Authorization": f"Bearer {_groq_key_activa()}", "Content-Type": "application/json"},
                            timeout=30,
                        )
                        if resp.status_code == 200:
                            texto = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                            if texto:
                                break
                        else:
                            print(f"[Vision/Groq] {modelo} HTTP {resp.status_code}: {resp.text[:300]}")
                    except Exception as groq_exc:
                        print(f"[Vision/Groq] {modelo}: {groq_exc}")

            if not texto:
                _mostrar_error("No pude analizar visualmente la pantalla. Revisa la cuota de Gemini o el acceso a los modelos de visión de Groq.")
                return
            if texto:
                html = _markdown_a_html(texto)
                _bridge.append_html.emit(_html_burbuja_jarvis(f"<b>Visión de pantalla</b><br>{html}"))
                _bridge.scroll_down.emit()
                _agregar_historial("jarvis", texto[:1000])
                _cola_voz.put(_limpiar_html(texto)[:400])
        except Exception as exc:
            print(f"[Vision] Error analizando pantalla: {exc}")
            _bridge.append_html.emit(_html_burbuja_jarvis("<b>Visión de pantalla</b><br>Ocurrió un error al analizar la pantalla."))
            _bridge.scroll_down.emit()
    threading.Thread(target=_trabajo, daemon=True, name="ScreenVision").start()

# =============================================================================
# MAPA DE SITIOS WEB CONOCIDOS
# =============================================================================

_SITIOS_WEB = {
    # Redes sociales
    "youtube":           "https://youtube.com",
    "instagram":         "https://instagram.com",
    "facebook":          "https://facebook.com",
    "twitter":           "https://x.com",
    "x":                 "https://x.com",
    "tiktok":            "https://tiktok.com",
    "twitch":            "https://twitch.tv",
    "reddit":            "https://reddit.com",
    "linkedin":          "https://linkedin.com",
    "pinterest":         "https://pinterest.com",
    # Noticias Colombia
    "caracol":           "https://www.caracoltv.com",
    "caracol noticias":  "https://caracol.com.co",
    "rcn":               "https://www.rcnradio.com",
    "rcn television":    "https://www.canalrcn.com",
    "el tiempo":         "https://eltiempo.com",
    "el colombiano":     "https://www.elcolombiano.com",
    "semana":            "https://semana.com",
    "el espectador":     "https://www.elespectador.com",
    "noticias caracol":  "https://noticias.caracoltv.com",
    "city tv":           "https://citytv.com.co",
    "blu radio":         "https://www.bluradio.com",
    # Noticias internacionales
    "bbc":               "https://bbc.com/mundo",
    "cnn":               "https://cnnespanol.cnn.com",
    "cnn español":       "https://cnnespanol.cnn.com",
    "infobae":           "https://infobae.com",
    "the verge":         "https://theverge.com",
    "techcrunch":        "https://techcrunch.com",
    # Tecnología / IA
    "spacex":            "https://spacex.com",
    "nasa":              "https://nasa.gov",
    "openai":            "https://openai.com",
    "anthropic":         "https://anthropic.com",
    "google":            "https://google.com",
    "microsoft":         "https://microsoft.com",
    "apple":             "https://apple.com",
    "meta":              "https://meta.com",
    "tesla":             "https://tesla.com",
    "github":            "https://github.com",
    "stackoverflow":     "https://stackoverflow.com",
    # Productividad / Trabajo
    "gmail":             "https://mail.google.com",
    "drive":             "https://drive.google.com",
    "docs":              "https://docs.google.com",
    "sheets":            "https://sheets.google.com",
    "slides":            "https://slides.google.com",
    "meet":              "https://meet.google.com",
    "classroom":         "https://classroom.google.com",
    "calendar":          "https://calendar.google.com",
    "outlook":           "https://outlook.live.com",
    "office":            "https://office.com",
    "onedrive":          "https://onedrive.live.com",
    "notion":            "https://notion.so",
    "trello":            "https://trello.com",
    "slack":             "https://slack.com",
    "zoom":              "https://zoom.us",
    "figma":             "https://figma.com",
    "canva":             "https://canva.com",
    # IA / Chat
    "chatgpt":           "https://chatgpt.com",
    "claude":            "https://claude.ai",
    "gemini":            "https://gemini.google.com",
    "copilot":           "https://copilot.microsoft.com",
    "perplexity":        "https://perplexity.ai",
    "midjourney":        "https://midjourney.com",
    # Entretenimiento
    "netflix":           "https://netflix.com",
    "spotify":           "https://open.spotify.com",
    "disney":            "https://disneyplus.com",
    "hbo":               "https://hbomax.com",
    "prime":             "https://primevideo.com",
    "amazon":            "https://amazon.com",
    "mercadolibre":      "https://mercadolibre.com.co",
    # Mapas / Viajes
    "maps":              "https://maps.google.com",
    "google maps":       "https://maps.google.com",
    "waze":              "https://waze.com",
    "airbnb":            "https://airbnb.com",
    "booking":           "https://booking.com",
    # Educación
    "wikipedia":         "https://es.wikipedia.org",
    "udemy":             "https://udemy.com",
    "coursera":          "https://coursera.org",
    "duolingo":          "https://duolingo.com",
    "khan academy":      "https://es.khanacademy.org",
    # Finanzas Colombia
    "bancolombia":       "https://bancolombia.com",
    "davivienda":        "https://davivienda.com",
    "nequi":             "https://nequi.com.co",
    "daviplata":         "https://daviplata.com",
    "dian":              "https://dian.gov.co",
    # Marcas de autos
    "porsche":           "https://www.porsche.com/latam/es",
    "ferrari":           "https://www.ferrari.com",
    "lamborghini":       "https://www.lamborghini.com",
    "bmw":               "https://www.bmw.com.co",
    "mercedes":          "https://www.mercedes-benz.com.co",
    "mercedes benz":     "https://www.mercedes-benz.com.co",
    "audi":              "https://www.audi.com.co",
    "toyota":            "https://www.toyota.com.co",
    "ford":              "https://www.ford.com.co",
    "chevrolet":         "https://www.chevrolet.com.co",
    "mazda":             "https://www.mazda.com.co",
    "honda":             "https://www.honda.com.co",
    "hyundai":           "https://www.hyundai.com.co",
    "kia":               "https://www.kia.com/co",
    "volkswagen":        "https://www.volkswagen.com.co",
    "jeep":              "https://www.jeep.com.co",
    "dodge":             "https://www.dodge.com",
    "bugatti":           "https://www.bugatti.com",
    "mclaren":           "https://www.mclaren.com",
    "rolls royce":       "https://www.rolls-roycemotorcars.com",
    # Videojuegos / Gaming
    "steam":             "https://store.steampowered.com",
    "epic games":        "https://store.epicgames.com",
    "riot games":        "https://www.riotgames.com",
    "league of legends": "https://www.leagueoflegends.com",
    "valorant":          "https://playvalorant.com",
    "minecraft":         "https://minecraft.net",
    "roblox":            "https://www.roblox.com",
    "playstation":       "https://www.playstation.com",
    "xbox":              "https://www.xbox.com",
    "nintendo":          "https://www.nintendo.com",
    # Otros populares
    "aliexpress":        "https://aliexpress.com",
    "ebay":              "https://ebay.com",
    "paypal":            "https://paypal.com",
    "dropbox":           "https://dropbox.com",
    "discord":           "https://discord.com",
    "whatsapp":          "https://web.whatsapp.com",
    "telegram":          "https://web.telegram.org",
}

def _abrir_url_especifica(consulta: str, chat_widget=None):
    """
    Abre una página web específica.
    1. Busca coincidencia exacta/parcial en _SITIOS_WEB.
    2. Si no hay coincidencia, usa Google 'I'm Feeling Lucky' con la consulta.
    """
    import webbrowser as _wb

    if not consulta:
        hablar("¿Qué página quieres abrir?", chat_widget)
        return

    c = quitar_tildes(consulta.lower().strip())
    # Limpiar palabras de relleno para mejorar matching
    c_clean = re.sub(
        r'\b(abre?|abrir|pagina|página|sitio|web|oficial|de|la|el|los|las|canal|cuenta)\b',
        ' ', c
    ).strip()
    c_clean = re.sub(r'\s+', ' ', c_clean).strip()

    # 1. Coincidencia exacta
    url = _SITIOS_WEB.get(c_clean) or _SITIOS_WEB.get(c)

    # 2. Coincidencia parcial — buscar la clave más larga que esté contenida
    # Ordenar por longitud DESC para que "spacex" gane sobre "x", "caracol noticias" sobre "caracol"
    if not url:
        mejor_clave, mejor_len = None, 0
        for clave in sorted(_SITIOS_WEB.keys(), key=len, reverse=True):
            if clave in c_clean or clave in c:
                mejor_clave = clave
                break
        if mejor_clave:
            url = _SITIOS_WEB[mejor_clave]

    # 3. Fallback inteligente: intentar dominio obvio primero, sino Google
    if not url:
        from urllib.parse import quote as _q
        # Si la consulta parece un dominio directo (una sola palabra sin espacios raros)
        palabras = c_clean.split()
        if len(palabras) == 1 and re.match(r'^[a-z0-9]+$', palabras[0]):
            # Intentar .com directamente
            url = f"https://www.{palabras[0]}.com"
        else:
            # Búsqueda Google con "sitio oficial"
            query_google = f"{consulta} sitio oficial"
            url = f"https://www.google.com/search?q={_q(query_google)}"
        nombre_voz = consulta
    else:
        nombre_voz = consulta

    # Mostrar en chat
    etiqueta = consulta if not url.startswith('http') else (urlparse(url).netloc or consulta)
    etiqueta = re.sub(r'^www\.', '', etiqueta)
    html = (
        f'<p style="color:#4db8ff;">🌐 Abriendo <b>{_escape_html(etiqueta)}</b></p>'
        f'<p style="color:#556677;font-size:11px;">{_escape_html(url)}</p>'
    )
    _bridge.append_html.emit(_html_burbuja_jarvis(html))
    _bridge.scroll_down.emit()
    _inyectar_en_v5(_html_burbuja_jarvis(html))

    hablar("Abriendo la página solicitada.", chat_widget)
    _wb.open(url)

def _ejecutar_accion(accion: dict, chat_widget=None):
    """Despacha una acción del JSON al agente correspondiente."""
    if not isinstance(accion, dict):
        return

    nombre = accion.get("accion", "").strip()
    p      = accion.get("params", {}) or {}

    # DEBUG: Log all actions
    print(f"[_ejecutar_accion] Accion={nombre}, Params={p}")

    # Respuestas variadas de confirmacion (para TTS)
    _CONF_ABRIR = ["Abriendo {}", "Listo, abriendo {}", "Va {}", "En un momento, {}"]
    _CONF_CERRAR = ["Cerrando {}", "Listo", "Hecho"]
    _random_conf = lambda lista, *args: random.choice(lista).format(*args) if args else random.choice(lista)

    # Soportar respuestas de agente anidado devueltas por el modelo
    if nombre in ("agent_pc", "agent_search", "agent_google", "agent_images", "agent_notas"):
        nested = p if isinstance(p, dict) else {}
        if isinstance(nested.get("params"), dict) and nested["params"].get("accion"):
            _ejecutar_accion(nested["params"], chat_widget)
            return
        if nested.get("accion"):
            _ejecutar_accion(nested, chat_widget)
            return
        if nested.get("action"):
            nested["accion"] = nested.pop("action")
            _ejecutar_accion(nested, chat_widget)
            return

    # ── Respuesta directa ──────────────────────────────────────────────────────
    if nombre == "responder":
        texto_html = p.get("texto", "")
        if texto_html:
            # Detectar tag de imagen <!--IMG:termino-->
            img_match = re.search(r'<!--IMG:(.*?)-->', texto_html)
            texto_limpio = re.sub(r'<!--IMG:.*?-->', '', texto_html).strip()

            # Sanitizar: si el modelo dejó markdown crudo (asteriscos/guiones de viñeta)
            # en lugar de HTML real, convertirlo correctamente para que no se lea literal.
            if texto_limpio and '<' not in texto_limpio:
                texto_limpio = _markdown_a_html(texto_limpio)
            elif '*' in texto_limpio:
                texto_limpio = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', texto_limpio)
                texto_limpio = texto_limpio.replace('*', '')

            if texto_limpio:
                html_burbuja = _html_burbuja_jarvis(texto_limpio)
                _bridge.append_html.emit(html_burbuja)
                _bridge.scroll_down.emit()
                # Registrar respuesta para memoria conversacional (cubre Groq, Gemini y comandos directos)
                _agregar_historial("jarvis", _limpiar_html(texto_limpio)[:300])
                voz = _limpiar_html(texto_limpio)
                if voz:
                    _cola_voz.put(voz[:400])

            if img_match:
                termino = img_match.group(1).strip()
                agent_images.ejecutar("buscar", {"termino": termino, "max_imgs": 3}, chat_widget)
        return

    # ── Agente Pantalla ────────────────────────────────────────────────────────
    _ACCIONES_PANTALLA = {
        "ver_pantalla", "analizar_pantalla", "activar_gestos", "desactivar_gestos",
        "hacer_click", "escribir", "pulsar_tecla", "desplazarse", "hacer_zoom",
    }
    if nombre in _ACCIONES_PANTALLA:
        try:
            if nombre in {"ver_pantalla", "analizar_pantalla"} and not _permiso_concedido("pantalla"):
                hablar("El acceso a la pantalla está desactivado en Configuración.", chat_widget)
                return
            if nombre in {"activar_gestos", "desactivar_gestos", "hacer_click", "escribir", "pulsar_tecla", "desplazarse", "hacer_zoom"} and not _permiso_concedido("teclado"):
                hablar("El control de teclado y ratón está desactivado en Configuración.", chat_widget)
                return
            if nombre == "analizar_pantalla":
                _bridge.show_screen_overlay.emit()
                _bridge.analyze_screen.emit(str(p.get("pregunta") or ""))
            else:
                agent_screen.ejecutar(nombre, p, chat_widget)
            if nombre == "ver_pantalla":
                _bridge.show_screen_overlay.emit()
                _bridge.analyze_screen.emit("")
        except Exception as e:
            print(f"[ERROR→Screen] agent_screen.ejecutar fallo: {e}")
            hablar("No pude acceder al control de pantalla.", chat_widget)
        return

    # ── Agente PC ──────────────────────────────────────────────────────────────
    _ACCIONES_PC = {
        "abrir_app", "cerrar_app", "minimizar_app", "maximizar_app",
        "poner_volumen", "subir_volumen", "bajar_volumen", "mute",
        "subir_brillo", "bajar_brillo", "poner_brillo",
        "apagar", "reiniciar", "bloquear", "suspender", "hibernar",
        "modo", "buscar_archivo", "aprender_app",
    }
    # Mapeo: accion JSON → (accion agent_pc, params_transform)
    _MAP_PC = {
        "abrir_app":     ("abrir",         lambda p: {"nombre": p.get("nombre","")}),
        "cerrar_app":    ("cerrar",        lambda p: {"nombre": p.get("nombre","")}),
        "minimizar_app": ("minimizar",     lambda p: {"nombre": p.get("nombre","")}),
        "maximizar_app": ("maximizar",     lambda p: {"nombre": p.get("nombre","")}),
        "poner_volumen": ("poner_volumen", lambda p: p),
        "subir_volumen": ("subir_volumen", lambda p: p),
        "bajar_volumen": ("bajar_volumen", lambda p: p),
        "mute":          ("mute",          lambda p: {}),
        "subir_brillo":  ("subir_brillo",  lambda p: p),
        "bajar_brillo":  ("bajar_brillo",  lambda p: p),
        "poner_brillo":  ("poner_brillo",  lambda p: p),
        "apagar":        ("apagar",        lambda p: {}),
        "reiniciar":     ("reiniciar",     lambda p: {}),
        "bloquear":      ("bloquear",      lambda p: {}),
        "suspender":     ("suspender",     lambda p: {}),
        "hibernar":      ("hibernar",      lambda p: {}),
        "modo":          ("modo",          lambda p: p),
        "buscar_archivo":("buscar_archivo",lambda p: p),
        "aprender_app":  ("aprender_app",  lambda p: p),
    }
    if nombre in _MAP_PC:
        ac_pc, transform = _MAP_PC[nombre]
        params_transform = transform(p)
        print(f"[Dispatch→PC] Accion PC={ac_pc}, Params={params_transform}")
        try:
            agent_pc.ejecutar(ac_pc, params_transform, chat_widget)
        except Exception as e:
            print(f"[ERROR→PC] agent_pc.ejecutar fallo: {e}")
            import traceback
            traceback.print_exc()
        return

    # ── Agente Búsqueda ────────────────────────────────────────────────────────
    if nombre == "buscar_web":
        if not config.get("busqueda_web", True):
            hablar("La extensión de búsqueda web está desactivada en Extensiones.", chat_widget)
            return
        print(f"[Dispatch→Search] Buscando: {p.get('pregunta', '')}")
        try:
            agent_search.ejecutar("buscar_web", {"pregunta": p.get("pregunta","")}, chat_widget)
        except Exception as e:
            print(f"[ERROR→Search] agent_search.ejecutar fallo: {e}")
            hablar("Error en búsqueda web.", chat_widget)
        return

    if nombre == "mostrar_mapa":
        if not config.get("google_maps", True):
            hablar("La extensión de mapas está desactivada en Extensiones.", chat_widget)
            return
        lugar = p.get("lugar", p.get("consulta", p.get("ciudad", ""))).strip()
        if lugar:
            _bridge.append_html.emit(_html_burbuja_jarvis(f'📍 Localizando <b>{lugar}</b>...'))
            _bridge.scroll_down.emit()
            def _geo_y_mostrar(q=lugar):
                from urllib.parse import quote as _q
                import requests as _req

                q = _normalizar_lugar(q)
                lat, lon, nombre_lugar = None, None, q

                # 1. Nominatim — soporta calles, negocios, direcciones exactas
                try:
                    headers_nom = {"User-Agent": "Jarvis/5.4 (personal assistant)"}
                    r = _req.get(
                        f"https://nominatim.openstreetmap.org/search"
                        f"?q={_q(q)}&format=json&limit=1&addressdetails=1&extratags=1&namedetails=1",
                        timeout=8, headers=headers_nom
                    )
                    nominatim_res = None
                    if r.status_code == 200 and r.json():
                        nominatim_res = r.json()[0]
                        lat  = float(nominatim_res["lat"])
                        lon  = float(nominatim_res["lon"])
                        nombre_lugar = nominatim_res.get("display_name", q).split(",")[0].strip()
                except Exception as e:
                    print(f"[Mapa] Nominatim falló: {e}")

                # 2. Open-Meteo geocoding como respaldo (solo para ciudades/países)
                if lat is None:
                    try:
                        r2 = _req.get(
                            f"https://geocoding-api.open-meteo.com/v1/search"
                            f"?name={_q(q)}&count=1&language=es&format=json",
                            timeout=8
                        )
                        if r2.status_code == 200 and r2.json().get("results"):
                            res2 = r2.json()["results"][0]
                            lat  = res2["latitude"]
                            lon  = res2["longitude"]
                            nombre_lugar = res2.get("name", q)
                    except Exception as e:
                        print(f"[Mapa] Open-Meteo falló: {e}")

                if lat is not None and lon is not None:
                    descripcion_lugar = _describir_lugar_nominatim(nominatim_res)
                    info_lugar = descripcion_lugar if descripcion_lugar else ''
                    img_url = ''
                    wikidata_id = None
                    if isinstance(nominatim_res.get('extratags'), dict):
                        wikidata_id = nominatim_res['extratags'].get('wikidata')
                    if wikidata_id:
                        img_url = _wikidata_image_url(wikidata_id)
                    if not img_url:
                        img_url = _wikimedia_commons_image_url(nombre_lugar or q)
                    if not img_url:
                        img_url = _wikimedia_commons_image_url(q)
                    if img_url:
                        info_lugar = (
                            f"<div style='margin-bottom:10px;'><img src='{_escape_html(img_url)}' "
                            f"style='width:100%;height:auto;border-radius:10px;object-fit:cover;'/></div>"
                            + info_lugar
                        )
                    if info_lugar:
                        info_lugar += "<p style='color:#9adcff;font-size:11px;'>Reseñas reales disponibles en Google Maps.</p>"
                    _bridge.append_to_v5_map.emit(float(lat), float(lon), nombre_lugar, info_lugar, config.get('anillos_interfaz', False))
                    if descripcion_lugar:
                        html_mapa = (
                            f"<div style='background:rgba(5,14,35,0.96);border:1px solid rgba(77,184,255,0.20);"
                            f"padding:12px 14px;border-radius:14px;margin:8px 0;'>"
                            f"<strong>{_escape_html(nombre_lugar)}</strong>"
                            f"{descripcion_lugar}"
                            f"<p>"
                            f"<a href='https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=18/{lat}/{lon}' "
                            f"style='color:#73d9ff;text-decoration:none;margin-right:12px;'>Ver en OpenStreetMap</a>"
                            f"<a href='https://www.google.com/maps/search/?api=1&query={_q(nombre_lugar or q)}' "
                            f"style='color:#73d9ff;text-decoration:none;'>Ver en Google Maps</a></p>"
                            f"</div>"
                        )
                        _bridge.append_html.emit(_html_burbuja_jarvis(html_mapa))
                    else:
                        _bridge.append_html.emit(_html_burbuja_jarvis(f'📍 Mostrando <b>{_escape_html(nombre_lugar)}</b> en el mapa.'))
                    hablar(f"Mostrando {nombre_lugar}", chat_widget)
                else:
                    # Fallback: no abrir automáticamente el navegador.
                    maps_url = f"https://www.google.com/maps/search/?api=1&query={_q(q)}"
                    html_fallback = (
                        f"<div style='background:rgba(5,14,35,0.96);border:1px solid rgba(77,184,255,0.20);"
                        f"padding:12px 14px;border-radius:14px;margin:8px 0;'>"
                        f"No pude localizar exactamente <strong>{_escape_html(q)}</strong>. "
                        f"Puedes abrirlo manualmente aquí: "
                        f"<a href='{maps_url}' style='color:#73d9ff;text-decoration:none;' target='_blank' rel='noopener'>Ver en Google Maps</a>"
                        f"</div>"
                    )
                    _bridge.append_html.emit(_html_burbuja_jarvis(html_fallback))
                    hablar(f"No pude localizar exactamente {q}. He añadido un enlace en el chat.", chat_widget)

            import threading as _th
            _th.Thread(target=_geo_y_mostrar, daemon=True).start()
        return

    if nombre == "noticias":
        try:
            agent_search.ejecutar("noticias", p, chat_widget)
        except Exception as e:
            print(f"[ERROR→Search] noticias fallo: {e}")
        return
    if nombre == "clima":
        agent_search.ejecutar("clima", p, chat_widget)
        return
    if nombre == "calcular":
        agent_search.ejecutar("calcular", p, chat_widget)
        return

    # ── Abrir URL específica ───────────────────────────────────────────────────
    if nombre == "abrir_url":
        _abrir_url_especifica(p.get("consulta", p.get("url", "")), chat_widget)
        return

    # ── Agente Imágenes ────────────────────────────────────────────────────────
    if nombre == "buscar_imagen":
        if not config.get("imagenes_auto", True):
            hablar("La extensión de imágenes está desactivada en Extensiones.", chat_widget)
            return
        agent_images.ejecutar("buscar", p, chat_widget)
        return
    if nombre == "generar_imagen":
        agent_images.ejecutar("generar", p, chat_widget)
        return

    # ── Agente Google ──────────────────────────────────────────────────────────
    _ACCIONES_GOOGLE = {
        "gmail_leer", "gmail_buscar", "gmail_enviar", "gmail_eliminar",
        "ver_eventos", "crear_evento", "editar_evento", "eliminar_evento",
        "ver_tareas", "crear_tarea", "editar_tarea", "eliminar_tarea",
        "buscar_contacto", "drive_buscar",
        # alias legacy
        "mostrar_eventos", "mostrar_agenda", "mostrar_tareas",
    }
    _ALIAS_GOOGLE = {
        "mostrar_eventos": "ver_eventos",
        "mostrar_agenda":  "ver_eventos",
        "mostrar_tareas":  "ver_tareas",
    }
    if nombre in _ACCIONES_GOOGLE:
        ac_g = _ALIAS_GOOGLE.get(nombre, nombre)
        extension_por_accion = {
            "gmail_leer": "google_gmail", "gmail_buscar": "google_gmail",
            "gmail_enviar": "google_gmail", "gmail_eliminar": "google_gmail",
            "ver_eventos": "google_calendar", "crear_evento": "google_calendar",
            "editar_evento": "google_calendar", "eliminar_evento": "google_calendar",
            "ver_tareas": "google_tasks", "crear_tarea": "google_tasks",
            "editar_tarea": "google_tasks", "eliminar_tarea": "google_tasks",
            "buscar_contacto": "google_contacts", "drive_buscar": "google_drive",
        }
        clave_extension = extension_por_accion.get(ac_g)
        if clave_extension and not config.get(clave_extension, False):
            hablar("Esa extensión está desactivada. Actívala desde Extensiones.", chat_widget)
            return
        agent_google.ejecutar(ac_g, p, chat_widget)
        return

    # ── Agente Notas ───────────────────────────────────────────────────────────
    _ACCIONES_NOTAS = {
        "nota_crear", "nota_leer", "nota_buscar", "nota_editar", "nota_eliminar",
        "alarma_crear", "alarma_listar", "alarma_eliminar",
        "recordatorio_crear", "recordatorio_listar", "recordatorio_eliminar",
        "memoria_guardar", "memoria_leer", "memoria_resumir", "memoria_limpiar",
    }
    if nombre in _ACCIONES_NOTAS:
        agent_notas.ejecutar(nombre, p, chat_widget)
        return

    # ── Acciones especiales ────────────────────────────────────────────────────
    if nombre == "iniciar_escucha_microfono":
        global _grabar_manual_activa
        if not _permiso_concedido("microfono"):
            hablar("El acceso al micrófono está desactivado en Configuración.", chat_widget)
            return
        # Si ya está grabando, parar la grabación
        if _grabar_manual_activa:
            print("[V5] Deteniendo grabación manual")
            _detener_grabacion_manual.set()
            return
        # Comando desde V5.html: activar escucha manual del micrófono
        def _escuchar_manual():
            try:
                texto = escuchar_microfono(duracion=30.0)
                if texto:
                    print(f"[Escucha Manual] Grabado: {texto}")
                    try:
                        interpretar_multiple(texto, chat_widget)
                    except Exception as e_interp:
                        print(f"[Escucha Manual] Error interpretando: {e_interp}")
                        hablar("Error procesando comando.", chat_widget)
                else:
                    hablar("No escuché nada claro.", chat_widget)
            except Exception as e:
                print(f"[Escucha Manual] Error general: {e}")
                import traceback
                traceback.print_exc()
                hablar("Error en la grabación.", chat_widget)
            finally:
                try:
                    _reset_v5_mic()
                except Exception as e:
                    print(f"[Escucha Manual] Error reset mic: {e}")
        threading.Thread(target=_escuchar_manual, daemon=True).start()
        return
    if nombre in ("salir", "adios", "cerrar_jarvis"):
        hablar("Hasta luego. Jarvis apagándose.", chat_widget)
        time.sleep(1.5)
        _bridge.quit_app.emit()
        return

    print(f"[Dispatcher] Acción no reconocida: '{nombre}' | params: {p}")

# =============================================================================
# 12. CEREBRO IA — Groq + Gemini
# =============================================================================

def _limpiar_json(raw: str) -> str:
    raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
    for v, n in [("\u201c",'"'),("\u201d",'"'),("\u2018","'"),("\u2019","'")]:
        raw = raw.replace(v, n)

    # Caso 0: el modelo devolvió HTML puro (empieza con <p>, <b>, <ul>, <div>, etc.)
    # Esto pasa cuando Groq ignora las instrucciones y responde en texto libre
    if re.match(r'^\s*<[a-zA-Z]', raw) or (not raw.startswith('[') and not raw.startswith('{')):
        # Verificar que no sea JSON disfrazado
        if '"accion"' not in raw and '"action"' not in raw:
            # Es texto/HTML puro — envolverlo en responder
            texto_safe = raw.replace('"', '\\"').replace('\n', ' ')[:800]
            return f'[{{"accion":"responder","params":{{"texto":"{texto_safe}"}}}}]'

    # Caso 1: ya es un array [ ... ]
    ini, fin = raw.find("["), raw.rfind("]")
    if ini != -1 and fin != -1 and ini < fin:
        candidato = raw[ini:fin+1].strip()
        try:
            json.loads(candidato)
            return candidato
        except Exception:
            pass

    # Caso 2: objeto suelto { "accion": ... } o { "acciones": [...] }
    io, fo = raw.find("{"), raw.rfind("}")
    if io != -1 and fo != -1 and io < fo:
        candidato = raw[io:fo+1].strip()
        try:
            obj = json.loads(candidato)
            if "accion" in obj:
                return json.dumps([obj])
            for key in ("acciones", "actions", "steps", "commands"):
                if key in obj and isinstance(obj[key], list):
                    return json.dumps(obj[key])
            return json.dumps([obj])
        except Exception:
            pass

    return '[{"accion":"responder","params":{"texto":"<p>No pude procesar la respuesta.</p>"}}]'


# =============================================================================
# 9b. BÚSQUEDA DE IMÁGENES (backend - sin CORS) - DESHABILITADA POR AHORA
# =============================================================================
def _buscar_imagen_wikidata(name: str, tipo: str = None) -> str:
    """
    Búsqueda de imágenes deshabilitada temporalmente.
    Causaba spam en logs y ralentizaba mapa.
    Se re-habilitará después con mejor implementación.
    """
    return None


def _llamar_groq(mensaje: str) -> list:
    # Esperar a que las keys estén listas antes de verificar
    if not _KEYS_LISTAS.is_set():
        _KEYS_LISTAS.wait(timeout=60)
    if not _groq_keys:
        return []

    system = _construir_prompt(
        historial=_formatear_historial(mensaje),
        contexto=_contexto_actual(mensaje),
    )
    
    # Detectar si el usuario pide una extensión/ampliación de respuesta anterior
    es_extension = _es_extension_respuesta(mensaje)
    mensaje_final = mensaje
    
    if es_extension:
        ultima_respuesta = _obtener_ultima_respuesta_jarvis()
        if ultima_respuesta:
            # Agregar instrucción explícita de extensión al mensaje
            extension_hint = (
                f"\n\n[INSTRUCCIÓN CRÍTICA DE EXTENSIÓN: El usuario pide que amplíes/continúes tu respuesta anterior. "
                f"Tu anterior respuesta fue exactamente esta: '{ultima_respuesta[:500]}...' "
                f"AHORA: Expande significativamente esa respuesta con más detalles, ejemplos concretos, argumentos profundos y profundidad. "
                f"NUNCA repitas lo ya dicho. SOLO complementa y elabora MÁS. "
                f"No pidas 'proporciona más información', ya tienes suficiente contexto.]"
            )
            mensaje_final = mensaje + extension_hint
        else:
            # Si no hay última respuesta de Jarvis, simplemente enviar el mensaje
            mensaje_final = mensaje
    
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": mensaje_final},
        ],
        "temperature": 0.4,
        "max_tokens":  1500,
    }

    resp = None
    for _ in range(max(1, len(_groq_keys) * 2)):
        headers = {
            "Authorization": f"Bearer {_groq_key_activa()}",
            "Content-Type": "application/json",
        }
        try:
            resp = requests.post(GROQ_BASE_URL, json=payload, headers=headers, timeout=25)
        except requests.exceptions.ConnectionError:
            time.sleep(2)
            continue

        if resp.status_code == 429:
            _groq_rotar_key("429")
            time.sleep(1)
            resp = None
            continue
        if resp.status_code == 401:
            _groq_rotar_key("401")
            resp = None
            continue
        if resp.status_code != 200:
            print(f"[Groq] HTTP {resp.status_code}: {resp.text[:200]}")
            return []
        break

    if resp is None:
        return []

    # Parsear UNA SOLA VEZ para evitar KeyError al llamar .json() dos veces
    try:
        resp_data = resp.json()
        raw = resp_data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"[Groq] Error parseando respuesta: {e} | texto: {resp.text[:300]}")
        return []

    # Contar tokens usando resp_data (no resp.json() de nuevo)
    usage = resp_data.get("usage", {})
    _groq_tokens["total"]    += usage.get("total_tokens", 0)
    _groq_tokens["llamadas"] += 1

    print(f"[Groq] Raw: {raw[:200]}")   # log para depuración
    raw_limpio = _limpiar_json(raw)
    try:
        r = json.loads(raw_limpio)
    except json.JSONDecodeError as e:
        print(f"[Groq] JSON inválido: {e} | raw_limpio: {raw_limpio[:200]}")
        return [{"accion": "responder", "params": {"texto": f"<p>{raw[:400]}</p>"}}]

    r = r if isinstance(r, list) else [r]

    # Validar que cada elemento sea un dict con "accion"
    r_valido = []
    for a in r:
        if not isinstance(a, dict):
            print(f"[Groq] Elemento inválido ignorado: {a}")
            continue
        if "accion" not in a:
            print(f"[Groq] Elemento sin 'accion' ignorado: {a}")
            continue
        if "params" not in a:
            a["params"] = {}
        r_valido.append(a)

    if not r_valido:
        print(f"[Groq] Sin acciones válidas en: {r}")
        return [{"accion": "responder", "params": {"texto": f"<p>{raw[:400]}</p>"}}]

    # Guardar en historial
    _ACCIONES_SISTEMA = {
        "abrir_app", "cerrar_app", "minimizar_app", "maximizar_app",
        "poner_volumen", "subir_volumen", "bajar_volumen", "mute",
        "subir_brillo", "bajar_brillo", "modo", "buscar_archivo",
    }
    for a in r_valido:
        ac = a.get("accion", "")
        if ac in _ACCIONES_SISTEMA:
            nombre_app = a.get("params", {}).get("nombre", "")
            _agregar_historial("jarvis", f"[ejecutado: {ac}{' ' + nombre_app if nombre_app else ''}]")

    return r_valido


def _llamar_gemini_cerebro(mensaje: str) -> list:
    """Gemini como fallback del cerebro."""
    import json as _json, urllib.request as _ur, urllib.error as _ue

    gemini_key = _gemini_key_activa()
    if not gemini_key:
        return []

    system = _construir_prompt(
        historial=_formatear_historial(mensaje),
        contexto=_contexto_actual(mensaje),
    )
    payload_bytes = _json.dumps({
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"parts": [{"text": mensaje}]}],
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 1500},
    }).encode("utf-8")

    for modelo in ["gemini-2.5-flash", "gemini-2.0-flash"]:
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{modelo}:generateContent?key={gemini_key}")
        req = _ur.Request(url, data=payload_bytes,
                          headers={"Content-Type": "application/json"}, method="POST")
        try:
            with _ur.urlopen(req, timeout=20) as resp:
                data = _json.loads(resp.read())
            partes = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            raw = "".join(p.get("text","") for p in partes if "text" in p).strip()
            if not raw:
                continue
            print(f"[Gemini] Raw: {raw[:200]}")   # log para depuración
            # Detectar mensajes de cuota en el cuerpo
            if isinstance(raw, str) and ('quota' in raw.lower() or 'quota_exceeded' in raw.lower() or 'quota-exceeded' in raw.lower()):
                print('[Gemini] Advertencia: respuesta contiene indicios de quota_exceeded')
                _gemini_rotar_key('quota_detected_in_body')
                continue
            raw_limpio = _limpiar_json(raw)
            r = _json.loads(raw_limpio)
            r = r if isinstance(r, list) else [r]
            # Validar elementos
            r_valido = [a for a in r if isinstance(a, dict) and "accion" in a]
            if r_valido:
                # Asegurar que todos tienen "params"
                for a in r_valido:
                    if "params" not in a:
                        a["params"] = {}
                return r_valido
        except _ue.HTTPError as e:
            try:
                body = e.read().decode('utf-8', errors='replace')
            except Exception:
                body = '<no body>'
            print(f"[Gemini] HTTP {e.code}: {body[:600]}")
            if e.code in (429, 401):
                _gemini_rotar_key(str(e.code))
                continue
        except _ue.URLError as e:
            print(f"[Gemini] URLError: {e}")
        except Exception as e:
            print(f"[Gemini cerebro] {type(e).__name__}: {e}")
    return []

# =============================================================================
# 12b. COMANDOS DIRECTOS (sin LLM para comandos de volumen/brillo/etc.)
# =============================================================================

_COMANDOS_DIRECTOS = [
    # ── Gestos y cámara ───────────────────────────────────────────────────────
    (r'(?:activar|activa|enciende|encender)\s+(?:el\s+)?(?:modo\s+)?(?:de\s+)?(?:gestos|control\s+por\s+gestos|camara|cámara)',
                                                      "activar_gestos", {}),
    (r'(?:desactivar|desactiva|apaga|apagar|cierra|cerrar)\s+(?:el\s+)?(?:modo\s+)?(?:de\s+)?(?:gestos|control\s+por\s+gestos|camara|cámara)',
                                                      "desactivar_gestos", {}),
    # ── Volumen ────────────────────────────────────────────────────────────────
    (r'sube\s+(el\s+)?volumen|m[aá]s\s+volumen|volumen\s+(m[aá]s|arriba|sube)',
                                                      "subir_volumen",  {"porcentaje": 20}),
    (r'baja\s+(el\s+)?volumen|menos\s+volumen|volumen\s+(menos|abajo|baja)',
                                                      "bajar_volumen",  {"porcentaje": 20}),
    # ── Calendario y tareas ────────────────────────────────────────────────────
    (r'mu[eé]strame?\s+(mis\s+)?eventos?|mis\s+eventos?|ver\s+agenda|qu[eé]\s+tengo\s+(hoy|esta\s+semana)|agenda\s+(de\s+)?hoy',
                                                      "ver_eventos",   {}),
    (r'mu[eé]strame?\s+(mis\s+)?tareas?|ver\s+tareas?|tareas\s+pendientes?|qu[eé]\s+tengo\s+pendiente',
                                                      "ver_tareas",    {}),
    # ── Gmail ──────────────────────────────────────────────────────────────────
    (r'leer?\s+correo|revisar?\s+correo|mis\s+(?:[uú]ltimos?\s+)?correos?|bandeja\s+de\s+entrada|qu[eé]\s+(correos?|emails?)\s+tengo|ver?\s+gmail',
                                                      "gmail_leer",    {"max_msgs": 5}),
    # ── Notas ──────────────────────────────────────────────────────────────────
    (r'mu[eé]strame?\s+(mis\s+)?notas?|mis\s+notas?|ver\s+notas?|qu[eé]\s+notas?\s+tengo',
                                                      "nota_leer",     {}),
    # ── Alarmas ────────────────────────────────────────────────────────────────
    (r'mis\s+alarmas?|ver\s+alarmas?|qu[eé]\s+alarmas?\s+tengo',
                                                      "alarma_listar", {}),
    # ── Recordatorios ──────────────────────────────────────────────────────────
    (r'mis\s+recordatorios?|ver\s+recordatorios?|qu[eé]\s+recordatorios?\s+tengo',
                                                      "recordatorio_listar", {}),
    # ── Memoria ────────────────────────────────────────────────────────────────
    (r'resumen\s+(de\s+)?memoria|qu[eé]\s+recuerdas?|qu[eé]\s+(sabes|tienes)\s+de\s+m[ií]',
                                                      "memoria_resumir", {}),
    # ── PC control ────────────────────────────────────────────────────────────
    (r'bloquea?\s+(el\s+)?(pc|computador|equipo)|bloquear',
                                                      "bloquear",      {}),
    (r'apaga?\s+(el\s+)?(pc|computador|equipo)',
                                                      "apagar",        {}),
    (r'reinicia?\s+(el\s+)?(pc|computador|equipo)',
                                                      "reiniciar",     {}),
    (r'suspende?\s+(el\s+)?(pc|computador|equipo)',
                                                      "suspender",     {}),
    (r'(silencia|mutea?|silencio)\s+(el\s+)?volumen|volumen\s+(silencio|mute)',
                                                      "mute",          {}),
]

def _intentar_comando_directo(texto: str) -> dict | None:
    txt = texto.lower().strip()

    def _extraer_coordenadas(texto: str) -> tuple[int, int] | None:
        patrones = [
            r'\b(?:click|clic|pulsa?|presiona?|toca?|haz|da|dale)(?:.*?)(\d{1,4})\s*[,;\s]+\s*(\d{1,4})\b',
            r'\b(?:click|clic|pulsa?|presiona?|toca?|haz|da|dale)(?:.*?)(?:x|posx|posición x|posición x)\s*[:=]?\s*(\d{1,4})\D+?(?:y|posy|posición y|posición y)\s*[:=]?\s*(\d{1,4})\b',
            r'\b(?:click|clic|pulsa?|presiona?|toca?|haz|da|dale).*?en\s+(\d{1,4})\s*(?:[,;]|\s+|\s+y\s*|\s*)\s*(\d{1,4})\b',
            r'\b(\d{1,4})\s*[xX,]\s*(\d{1,4})\b',
            r'\b(\d{1,4})\s+(\d{1,4})\b',
        ]
        for patron in patrones:
            coords = re.search(patron, texto)
            if coords:
                try:
                    x = int(coords.group(1))
                    y = int(coords.group(2))
                    return x, y
                except Exception:
                    pass
        return None

    def _extraer_objetivo_click(texto: str) -> str | None:
        m = re.search(
            r'\b(?:click|clic|pulsa?|presiona?|toca?|haz|da|dale)(?:.*?)(?:en|sobre|sobre el|en el|en la|en los|en las)\s+([a-záéíóúñ0-9 ]{2,100})',
            texto,
        )
        if not m:
            m = re.search(
                r'\b(?:haz|da|dale|realiza|ejecuta)\s+(?:click|clic|pulsa|presiona|toca)\s+(?:en\s+|al\s+|a\s+)?([a-záéíóúñ0-9 ]{2,100})',
                texto,
            )
        if not m:
            m = re.search(
                r'\b(?:click|clic|pulsa|presiona|toca)\s+(?:en\s+|al\s+|a\s+)?([a-záéíóúñ0-9 ]{2,100})',
                texto,
            )
        if not m:
            return None
        objetivo = m.group(1).strip()
        objetivo = re.sub(r'[.,!?\\s]*$', '', objetivo).strip()
        objetivo = re.sub(r'\b(?:ahora|por favor|porfa|porfavor|gracias|gracia)\b.*$', '', objetivo).strip()
        if not objetivo or re.search(r'\d', objetivo):
            return None
        if any(k in objetivo for k in ('arriba', 'abajo', 'derecha', 'izquierda', 'centro', 'superior', 'inferior', 'esquina', 'lado', 'medio', 'center')):
            return None
        return objetivo

    def _extraer_coordenadas_relativas(texto: str) -> tuple[int, int] | None:
        try:
            import pyautogui
            screen_w, screen_h = pyautogui.size()
            x = screen_w // 2
            y = screen_h // 2
            if 'izquierda' in texto or 'left' in texto:
                x = int(screen_w * 0.15)
            elif 'derecha' in texto or 'right' in texto:
                x = int(screen_w * 0.85)
            if 'arriba' in texto or 'superior' in texto or 'top' in texto:
                y = int(screen_h * 0.15)
            elif 'abajo' in texto or 'inferior' in texto or 'bottom' in texto:
                y = int(screen_h * 0.85)
            if 'centro' in texto or 'medio' in texto or 'center' in texto:
                x = screen_w // 2
                y = screen_h // 2
            if 'esquina' in texto and 'izquierda' in texto and 'arriba' in texto:
                x = int(screen_w * 0.08); y = int(screen_h * 0.08)
            if 'esquina' in texto and 'derecha' in texto and 'arriba' in texto:
                x = int(screen_w * 0.92); y = int(screen_h * 0.08)
            if 'esquina' in texto and 'izquierda' in texto and 'abajo' in texto:
                x = int(screen_w * 0.08); y = int(screen_h * 0.92)
            if 'esquina' in texto and 'derecha' in texto and 'abajo' in texto:
                x = int(screen_w * 0.92); y = int(screen_h * 0.92)
            return x, y
        except Exception:
            return None

    def _extraer_cantidad(texto: str, defecto: int) -> int:
        m = re.search(r'(-?\d{1,4})', texto)
        if m:
            try:
                valor = abs(int(m.group(1)))
                if valor > 0:
                    return min(1000, max(30, valor))
            except Exception:
                pass
        return defecto

    if re.search(r'\b(ver|mira|observa|vigila)\b.*\b(pantalla|escritorio)\b', txt):
        return {"accion": "ver_pantalla", "params": {}}
    if re.search(r'\b(qu[eé]|dime|describe|explica)\b.*\b(ves|v[eé]s|pantalla|escritorio)\b', txt):
        return {"accion": "analizar_pantalla", "params": {}}
    if re.search(r'\b(resume|resumir|resumen|explica|explicar|para qu[eé] sirve|qu[eé] es)\b', txt) and re.search(r'\b(pantalla|p[aá]gina|art[ií]culo|texto|esto|aqu[ií])\b', txt):
        return {"accion": "analizar_pantalla", "params": {"pregunta": texto}}
    if re.search(r'\b(?:activar|activa|enciende|encender)\b.*\b(?:modo\s+)?(?:de\s+)?(?:gestos|control\s+por\s+gestos|camara|cámara)\b', txt):
        return {"accion": "activar_gestos", "params": {}}
    if re.search(r'\b(?:desactivar|desactiva|apaga|apagar|cerrar|cierra)\b.*\b(?:modo\s+)?(?:de\s+)?(?:gestos|control\s+por\s+gestos|camara|cámara)\b', txt):
        return {"accion": "desactivar_gestos", "params": {}}

    if re.search(r'\b(?:click|clic|pulsa(?:r)?|presiona(?:r)?|toca(?:r)?|haz|da|dale|realiza|ejecuta)\b', txt) and re.search(r'\b(?:click|clic|pulsa(?:r)?|presiona(?:r)?|toca(?:r)?)\b', txt):
        boton = "left"
        if re.search(r'\b(?:derecho|right)\b', txt):
            boton = "right"
        elif re.search(r'\b(?:medio|middle)\b', txt):
            boton = "middle"
        clicks = 2 if re.search(r'\b(?:doble|dos)\b.*\b(?:click|clic)\b', txt) else 1
        params = {"boton": boton, "clicks": clicks}
        if coord := _extraer_coordenadas(txt):
            params["x"], params["y"] = coord
        else:
            objetivo = _extraer_objetivo_click(txt)
            if objetivo:
                params["objetivo"] = objetivo
            elif coord_rel := _extraer_coordenadas_relativas(txt):
                params["x"], params["y"] = coord_rel
        return {"accion": "hacer_click", "params": params}

    if re.search(r'\b(?:scroll|desplaz(?:a|ar|ate)|baja|abajo|arriba|sube|up|down|desliza|mueve)\b', txt) and not re.search(r'\bvolumen\b', txt):
        cantidad = _extraer_cantidad(txt, 300)
        if re.search(r'\b(?:baja|bajar|abajo|down|inferior|inferiores|desliza(?: hacia)? abajo|scroll\s+down)\b', txt):
            return {"accion": "desplazarse", "params": {"cantidad": -cantidad}}
        if re.search(r'\b(?:sube|subir|arriba|up|superior|desliza(?: hacia)? arriba|scroll\s+up)\b', txt):
            return {"accion": "desplazarse", "params": {"cantidad": cantidad}}

    if re.search(r'\b(?:zoom(?:\s+in)?|acerca(?:r)?|aumenta(?:r)?(?: el)? zoom|amplia(?:r)?|acercar|agrandar)\b', txt):
        return {"accion": "hacer_zoom", "params": {"cantidad": 240}}
    if re.search(r'\b(?:zoom\s*out|aleja(?:r)?|reduce(?:r)?(?: el)? zoom|achica(?:r)?|reducir)\b', txt):
        return {"accion": "hacer_zoom", "params": {"cantidad": -240}}

    # ── Google Maps explícito → abrir en navegador ─────────────────────────────
    # DEBE ir ANTES del regex de mapa interno
    if re.search(r'\bgoogle\s+maps?\b', txt) or txt.strip() in ("maps", "google maps", "abre maps", "abrir maps", "abre google maps", "abrir google maps"):
        return {"accion": "abrir_url", "params": {"consulta": "google maps"}}

    # Las aplicaciones locales tienen prioridad sobre sitios con el mismo nombre.
    # Para abrir la web se puede decir "abre la página de Spotify".
    m_app_explicita = re.match(r'^abre?\s+(?:el\s+|la\s+)?(.+)$', txt, re.IGNORECASE)
    if m_app_explicita:
        candidato = m_app_explicita.group(1).strip().rstrip(".,!?")
        aplicaciones_conocidas = {
            "spotify", "discord", "telegram", "steam", "epic games",
            "outlook", "vscode", "visual studio code", "chrome",
            "google chrome", "firefox", "edge", "notepad++", "vlc",
        }
        if candidato in aplicaciones_conocidas:
            return {"accion": "abrir_app", "params": {"nombre": candidato}}

    # ── Mapa interactivo ───────────────────────────────────────────────────────
    m_mapa = re.search(
        r'^(?:dame|mu[eé]strame?|abre?|ver?|pon|enseña(?:me)?|muestra(?:me)?|busca|llévame|ir\s+a|ve\s+a|navega(?:r)?\s+(?:a|hacia)?)\s+'
        r'(?:el\s+|un\s+|la\s+|los\s+|las\s+)?(?:mapa\s+(?:de\s+|del\s+|de\s+la\s+|de\s+el\s+)?)?'
        r'(.+)$',
        txt, re.IGNORECASE
    )
    if m_mapa:
        lugar = m_mapa.group(1).strip().rstrip(".,!?")
        # Solo activar si hay palabra "mapa" en el comando O es claramente un lugar
        tiene_mapa = "mapa" in txt
        tiene_calle = any(kw in txt for kw in [
            "calle", "carrera", "avenida", "transversal", "diagonal",
            "cra", " cl ", " av ", "street", "avenue", "road",
        ])
        tiene_lugar = any(kw in txt for kw in [
            "restaurante", "hotel", "parque", "museo", "aeropuerto",
            "centro comercial", "universidad", "colegio", "iglesia",
            "estadio", "barrio", "plaza", "mall",
        ])
        if lugar and (tiene_mapa or tiene_calle or tiene_lugar):
            # No capturar si el "lugar" es google maps u otro servicio web
            if not re.search(r'\bgoogle\b|\bmaps?\b|\bwaze\b', lugar):
                return {"accion": "mostrar_mapa", "params": {"lugar": lugar}}

    m_mapa2 = re.search(
        r'^mapa\s+(?:de\s+|del\s+|de\s+la\s+)?(.+)$',
        txt, re.IGNORECASE
    )
    if m_mapa2:
        lugar = m_mapa2.group(1).strip().rstrip(".,!?")
        if lugar and not re.search(r'\bgoogle\b|\bmaps?\b|\bwaze\b', lugar):
            return {"accion": "mostrar_mapa", "params": {"lugar": lugar}}

    # ── Volumen absoluto ───────────────────────────────────────────────────────
    m = re.search(r'volumen\s+(?:al|a)\s+(\d{1,3})\s*(?:%|porciento)?', txt)
    if m:
        return {"accion": "poner_volumen", "params": {"porcentaje": int(m.group(1))}}
    if re.search(r'volumen\s+(?:al\s+)?m[aá]ximo', txt):
        return {"accion": "poner_volumen", "params": {"porcentaje": 100}}
    if re.search(r'volumen\s+(?:al\s+)?m[ií]nimo|silencio', txt):
        return {"accion": "poner_volumen", "params": {"porcentaje": 0}}

    # ── NOTAS — toma nota / anota / guarda nota ────────────────────────────────
    m = re.search(
        r'^(?:toma\s+(?:una?\s+)?nota|anota|apunta|guarda\s+(?:una?\s+)?nota|nota[:;,]?)\s*[:\-]?\s*(.+)$',
        txt, re.IGNORECASE
    )
    if m:
        contenido = m.group(1).strip()
        if contenido:
            return {"accion": "nota_crear", "params": {"contenido": contenido}}

    # ── BÚSQUEDA — busca / qué es / quién es / cómo funciona ─────────────────
    m_busca = re.search(
        r'^(?:busca(?:r)?\s+(?:sobre\s+|información\s+(?:sobre|de)\s+)?|'
        r'investiga(?:r)?\s+(?:sobre\s+|acerca\s+de\s+)?|'
        r'qu[eé]\s+(?:es|son|fue|fueron|significa)\s+|'
        r'qui[eé]n\s+(?:es|fue|era)\s+|'
        r'c[oó]mo\s+(?:funciona|se\s+hace|es)\s+|'
        r'cu[aá]l(?:es)?\s+(?:es|son)\s+|'
        r'd[oó]nde\s+(?:est[aá]|queda|vive)\s+|'
        r'cu[aá]ndo\s+(?:fue|es|nació)\s+|'
        r'para\s+qu[eé]\s+sirve\s+|'
        r'h[aá]blame\s+(?:de|sobre)\s+|'
        r'cu[eé]ntame\s+(?:sobre|de)\s+|'
        r'informaci[oó]n\s+(?:sobre|de)\s+)(.+)$',
        txt, re.IGNORECASE
    )
    if m_busca:
        pregunta = m_busca.group(0).strip()
        return {"accion": "buscar_web", "params": {"pregunta": pregunta}}

    # ── ABRIR URL / PÁGINA WEB ESPECÍFICA ────────────────────────────────────
    m_url = re.search(
        r'^(?:abre?|abrir|entra?|entrar|ir\s+a|ve\s+a|visita?|visitar|navega?(?:r)?\s+(?:a|hacia)?)\s+'
        r'(?:la\s+)?(?:p[aá]gina\s+(?:de|oficial\s+de|web\s+de)?|'
        r'sitio\s+(?:web\s+)?(?:de|oficial\s+de)?|'
        r'web\s+(?:de|oficial\s+de)?|'
        r'canal\s+(?:de\s+youtube\s+de)?|'
        r'cuenta\s+(?:de\s+instagram\s+de)?|'
        r'(?:el\s+|la\s+)?(?:portal|blog|foro)\s+(?:de\s+)?)?'
        r'(.+)$',
        txt, re.IGNORECASE
    )
    if m_url:
        consulta_url = m_url.group(1).strip().rstrip(".,!?")
        # Verificar que sea claramente una web (tiene palabras clave de sitio en el comando original)
        _KEYWORDS_WEB = {
            "página", "pagina", "sitio", "web", "portal", "canal de youtube",
            "cuenta de", "instagram de", "twitter de", "facebook de",
        }
        es_web = any(kw in txt for kw in _KEYWORDS_WEB)
        # O que la consulta coincida directamente con un sitio conocido
        c_norm = quitar_tildes(consulta_url.lower())
        c_clean = re.sub(r'\b(la|el|los|las|de|oficial)\b', ' ', c_norm).strip()
        c_clean = re.sub(r'\s+', ' ', c_clean).strip()
        en_mapa = any(
            clave in c_clean or clave in c_norm
            for clave in _SITIOS_WEB
        )
        if es_web or en_mapa:
            return {"accion": "abrir_url", "params": {"consulta": consulta_url}}

    # ── Abrir app ─────────────────────────────────────────────────────────────
    m = re.search(
        r'^(?:abre?|abrir|lanza?|lanzar|ejecuta?|ejecutar|inicia?|iniciar|pon|poner|arranca?|arrancar|mostrar?|muestra?|sierra?)\s+(?:el\s+|la\s+|los\s+|las\s+)?(.+)$',
        txt, re.IGNORECASE
    )
    if m:
        nombre_app = m.group(1).strip().rstrip(".,!?")
        _NO_APP = {"correo", "gmail", "correos", "noticias", "clima", "musica", "música",
                   "archivo", "carpeta", "foto", "fotos", "imagen", "imagenes", "imágenes"}
        if nombre_app and nombre_app not in _NO_APP and len(nombre_app) >= 2:
            print(f"[Intérprete] 📋 Comando directo detectado: abrir_app='{nombre_app}'")
            return {"accion": "abrir_app", "params": {"nombre": nombre_app}}

    # ── Cerrar app ────────────────────────────────────────────────────────────
    m = re.search(
        r'^(?:cierra?|cerrar)\s+(?:el\s+|la\s+)?(.+)$',
        txt, re.IGNORECASE
    )
    if m:
        nombre_app = m.group(1).strip().rstrip(".,!?")
        if nombre_app and len(nombre_app) >= 2:
            return {"accion": "cerrar_app", "params": {"nombre": nombre_app}}

    # ── Resto de comandos directos de la tabla ────────────────────────────────
    for patron, accion, params in _COMANDOS_DIRECTOS:
        if re.search(patron, txt, re.IGNORECASE):
            return {"accion": accion, "params": params}
    return None

# =============================================================================
# 13. interpretar_multiple — punto de entrada principal
# =============================================================================

_STOP_PHRASES = {"silencio", "para", "calla", "stop", "basta", "sh", "shh", "shhh"}
_modo_conversacion = threading.Event()

def _activar_modo_conversacion():
    _modo_conversacion.set()
    # Auto-desactivar en 5 minutos de inactividad
    def _desactivar():
        time.sleep(300)
        _modo_conversacion.clear()
    threading.Thread(target=_desactivar, daemon=True).start()


def interpretar_multiple(comando: str, chat_widget=None, mostrar_usuario: bool = True):
    """
    Punto de entrada principal. Recibe el texto del usuario (voz o escrito),
    lo procesa y delega a los agentes correspondientes.
    """
    if not comando or not comando.strip():
        return

    _activar_modo_conversacion()

    # Silencio / stop
    cmd_lower = comando.lower().strip().rstrip(".,!?;:")
    if cmd_lower in _STOP_PHRASES:
        while not _cola_voz.empty():
            try: _cola_voz.get_nowait()
            except: break
        _detener_tts()
        return

    if cmd_lower == "iniciar_escucha_microfono":
        _ejecutar_accion({"accion": "iniciar_escucha_microfono", "params": {}}, chat_widget)
        return

    # Registrar SIEMPRE el turno del usuario en el historial (comando directo, Groq o Gemini)
    _agregar_historial("usuario", comando)

    # Aprender del usuario pasivamente
    _aprender_del_usuario(comando)

    # Guardar en la memoria de notas automáticamente si el usuario menciona algo útil
    # (se hace en segundo plano sin bloquear)
    def _auto_memoria():
        try:
            _TRIGGERS_MEMORIA = [
                "recuerda que", "anota que", "guarda que", "no olvides que",
                "apunta que", "toma nota de", "memoriza"
            ]
            cmd_l = comando.lower()
            for trigger in _TRIGGERS_MEMORIA:
                if trigger in cmd_l:
                    idx = cmd_l.index(trigger) + len(trigger)
                    contenido = comando[idx:].strip()
                    if contenido:
                        agent_notas.ejecutar("nota_crear",
                            {"contenido": contenido, "titulo": f"Auto: {datetime.now().strftime('%d/%m %H:%M')}"},
                            chat_widget)
                    break
        except Exception:
            pass
    threading.Thread(target=_auto_memoria, daemon=True).start()

    # Mostrar mensaje del usuario en el chat
    if mostrar_usuario:
        _bridge.append_html.emit(_html_burbuja_usuario(comando))
        _bridge.scroll_down.emit()

    # ── Resolver estados pendientes (app vs web, archivo Office) ─────────────
    import agent_pc as _apc
    if _apc.hay_destino_pendiente():
        if _apc.resolver_destino_pendiente(comando, chat_widget):
            return
    # Comando de control directo de mic manual desde V5
    if cmd_lower == "iniciar_escucha_microfono":
        _ejecutar_accion({"accion": "iniciar_escucha_microfono", "params": {}}, chat_widget)
        return
    # Estado archivo Office pendiente
    if getattr(_apc, '_archivo_office_pendiente', None):
        ruta_off = _apc._archivo_office_pendiente
        cmd_l2 = comando.lower()
        if any(x in cmd_l2 for x in ["app", "aplicacion", "aplicación", "local", "office", "word", "excel"]):
            _apc._archivo_office_pendiente = None
            try:
                os.startfile(ruta_off)
                hablar(f"Abriendo {os.path.basename(ruta_off)} en la app.", chat_widget)
            except Exception:
                hablar("No pude abrir el archivo.", chat_widget)
            return
        elif any(x in cmd_l2 for x in ["web", "online", "navegador", "browser", "365"]):
            _apc._archivo_office_pendiente = None
            import webbrowser as _wb
            _wb.open("https://office.com")
            hablar("Abriendo Office en la web.", chat_widget)
            return

    # ── Comandos determinísticos (sin LLM) ────────────────────────────────────
    accion_directa = _intentar_comando_directo(cmd_lower)
    if accion_directa:
        _ejecutar_accion(accion_directa, chat_widget)
        return

    # ── Cerebro IA: Groq → Gemini → fallback ─────────────────────────────────
    # Si las keys aún no cargaron, esperar (servidor Render puede tardar 90-120s)
    if not _KEYS_LISTAS.is_set():
        _bridge.append_html.emit(_html_burbuja_jarvis(
            '<span style="color:#ffaa44;font-size:12px;">'
            '⏳ Conectando con la IA... (el servidor puede tardar hasta 2 min en despertar)</span>'
        ))
        _bridge.scroll_down.emit()
        _KEYS_LISTAS.wait(timeout=130)

    acciones = None

    if not _groq_keys and not _gemini_keys:
        _bridge.append_html.emit(_html_burbuja_jarvis(
            '<span style="color:#ff5555;font-size:13px;">❌ Sin IA disponible</span><br>'
            '<span style="color:#8899bb;font-size:12px;">'
            'Espera 60s y vuelve a intentar, o reinicia Jarvis.<br>'
            'Si el problema persiste, crea un <b>.env</b> con tus API keys.</span>'
        ))
        _bridge.scroll_down.emit()
        return

    # ── Routing: Gemini para análisis/búsqueda, Groq para comandos simples ──
    _KEYWORDS_ANALISIS = [
        "qué", "que", "quién", "quien", "cómo", "como", "cuál", "cual",
        "cuándo", "cuando", "dónde", "donde", "explica", "explícame",
        "busca", "buscar", "investiga", "información", "noticias",
        "clima", "tiempo", "cuánto", "cuanto", "por qué", "porque",
        "significa", "es", "son", "fue", "fueron", "cuéntame", "cuentame",
        "háblame", "hablame", "historia", "origen", "diferencia",
        "ventajas", "desventajas", "recomienda", "sugiere", "analiza",
    ]
    _KEYWORDS_COMANDO = [
        "abre", "abrir", "cierra", "cerrar", "sube", "baja", "pon",
        "apaga", "reinicia", "bloquea", "silencia", "maximiza", "minimiza",
        "crea", "nota", "alarma", "recordatorio", "tarea", "modo",
        "buscar archivo", "busca archivo",
    ]

    cmd_lower_routing = comando.lower()
    es_comando_simple = any(cmd_lower_routing.startswith(kw) or f" {kw} " in f" {cmd_lower_routing} "
                            for kw in _KEYWORDS_COMANDO)
    es_analisis = any(kw in cmd_lower_routing for kw in _KEYWORDS_ANALISIS)

    # Usar Gemini si: es análisis/búsqueda Y hay Gemini disponible
    usar_gemini_primero = es_analisis and not es_comando_simple and bool(_gemini_keys)

    if usar_gemini_primero:
        # Gemini primero para análisis y búsqueda
        if _gemini_keys:
            try:
                acciones = _llamar_gemini_cerebro(comando)
            except Exception as e:
                import traceback
                print(f"[Gemini] Excepción: {e}")
                traceback.print_exc()
                acciones = []
        # Fallback a Groq si Gemini falla
        if not acciones and _groq_keys:
            try:
                acciones = _llamar_groq(comando)
            except Exception as e:
                print(f"[Groq fallback] {e}")
                acciones = []
    else:
        # Groq primero para comandos simples
        if _groq_keys:
            try:
                acciones = _llamar_groq(comando)
            except Exception as e:
                import traceback
                print(f"[Groq] Excepción: {e}")
                traceback.print_exc()
                acciones = []
        # Fallback a Gemini si Groq falla
        if not acciones and _gemini_keys:
            try:
                acciones = _llamar_gemini_cerebro(comando)
            except Exception as e:
                print(f"[Gemini fallback] {e}")
                acciones = None

    if acciones:
        for accion in acciones:
            _ejecutar_accion(accion, chat_widget)
        return

    # ── Fallback: respuesta simple si no hay IA disponible ────────────────────
    _bridge.append_html.emit(_html_burbuja_jarvis(
        '<span style="color:#ff5555;">❌ La IA no respondió</span><br>'
        '<span style="color:#8899bb;font-size:12px;">'
        'Groq y Gemini fallaron. Posibles causas:<br>'
        '• Keys inválidas o sin saldo<br>'
        '• Sin conexión a internet<br>'
        '• Rate limit alcanzado (espera 1 minuto)</span>'
    ))
    _bridge.scroll_down.emit()
    hablar("No pude conectar con la IA. Revisa la consola para más detalles.", chat_widget)

# =============================================================================
# 13b. MOTOR DE ESCUCHA (Groq Whisper)
# =============================================================================

_whisper_model = True  # Flag para indicar que Groq Whisper está listo

def _transcribir_con_groq_whisper(audio_data: np.ndarray, language: str = "es") -> str:
    """Transcribe audio usando Groq Whisper API. Devuelve el texto o vacío."""
    if not _groq_keys:
        return ""
    
    import io
    import wave as _wave_module
    
    try:
        # Convertir numpy array a bytes WAV
        fs = 16000
        audio_data = np.asarray(audio_data, dtype=np.float32)
        
        # Sanitizar NaN/inf que causan overflow
        audio_data = np.nan_to_num(audio_data, nan=0.0, posinf=0.0, neginf=0.0)
        
        # Normalizar si es necesario
        max_val = np.abs(audio_data).max()
        if max_val > 1.0:
            audio_data = audio_data / max_val
        elif max_val == 0.0:
            return ""  # Audio vacío
        
        # Convertir a int16
        audio_int16 = np.int16(audio_data * 32767)
        
        # Crear buffer WAV
        wav_buffer = io.BytesIO()
        with _wave_module.open(wav_buffer, 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(fs)
            wav_file.writeframes(audio_int16.tobytes())
        wav_buffer.seek(0)
        
        # Llamar a Groq Whisper API
        files = {'file': ('audio.wav', wav_buffer, 'audio/wav')}
        data = {
            'model': 'whisper-large-v3-turbo',
            'language': language,
            'prompt': 'jarvis',
        }
        headers = {'Authorization': f'Bearer {_groq_key_activa()}'}
        
        resp = requests.post(
            'https://api.groq.com/openai/v1/audio/transcriptions',
            files=files, data=data, headers=headers, timeout=30
        )
        
        if resp.status_code == 200:
            texto = resp.json().get('text', '').strip()
            return texto
        elif resp.status_code == 429:
            print("[Groq Whisper] Rate limit — rotando key")
            _groq_rotar_key("429 Whisper")
        elif resp.status_code == 401:
            print("[Groq Whisper] Auth error — rotando key")
            _groq_rotar_key("401 Whisper")
        else:
            print(f"[Groq Whisper] HTTP {resp.status_code}: {resp.text[:200]}")
        
        return ""
    except Exception as e:
        print(f"[Groq Whisper] Error: {e}")
        return ""

def cargar_whisper():
    """Inicializar Groq Whisper (sin descargar modelo local)."""
    global _whisper_model
    
    # ── CRÍTICO: Esperar a que las keys estén cargadas ──
    print("[Whisper] Esperando a que se carguen las keys...")
    _KEYS_LISTAS.wait(timeout=120)
    
    if not _groq_keys:
        print("[Whisper] Sin keys de Groq — escucha de voz desactivada")
        _bridge.append_html.emit(_html_burbuja_jarvis(
            '<span style="color:#ff6655;font-size:12px;">'
            '⚠️ Sin API key de Groq — escucha de voz desactivada</span>'
        ))
        _whisper_model = None
        return
    
    _whisper_model = True
    print("[Whisper] 🎤 Groq Whisper listo")
    _bridge.append_html.emit(_html_burbuja_jarvis(
        '<span style="color:#44cc88;font-size:12px;">✓ Voz lista — di <b>"Jarvis"</b> para activar</span>'
    ))
    _bridge.scroll_down.emit()

def _grabar_hasta_silencio(max_duracion: float = 18.0,
                            min_amp: float = 0.002,
                            silencio_timeout: float = 5.0) -> np.ndarray:
    """Graba audio hasta silencio sostenido del usuario o hasta que se interrumpa.
    Usa bloques finos (0.3s) y RMS acumulado para no cortar por micro-pausas."""
    global _detener_grabacion_manual
    fs = 16000
    block_dur = 0.3
    block_len = int(block_dur * fs)
    bloques = []
    started = False
    silent_time = 0.0

    try:
        stream_kwargs = {"samplerate": fs, "channels": 1, "dtype": "float32", "blocksize": block_len}
        dispositivo = _dispositivo_microfono()
        if dispositivo is not None:
            stream_kwargs["device"] = dispositivo
        with sd.InputStream(**stream_kwargs) as stream:
            inicio = time.time()
            while time.time() - inicio < max_duracion:
                if _detener_grabacion_manual.is_set():
                    print("[Whisper] Grabación interrumpida por usuario")
                    break

                try:
                    bloque, overflowed = stream.read(block_len)
                except Exception as e:
                    print(f"[Whisper] Error leyendo audio: {e}")
                    break
                if overflowed:
                    print("[Whisper] Advertencia: overflow de audio durante grabación")
                bloques.append(bloque.copy())
                rms = float(np.sqrt(np.mean(bloque.astype(np.float64) ** 2)))
                if rms >= min_amp:
                    started = True
                    silent_time = 0.0
                elif started:
                    silent_time += block_dur
                if started and silent_time >= silencio_timeout:
                    print("[Whisper] Silencio sostenido detectado, finalizando grabación")
                    break

    except sd.PortAudioError as e:
        print(f"[Whisper] Error de PortAudio (stream interrumpido): {e}")
        pass
    except Exception as e:
        print(f"[Whisper] Error de audio en InputStream: {e}")
        pass

    if not bloques:
        return np.array([], dtype='float32')
    try:
        return np.concatenate(bloques, axis=0).flatten()
    except Exception as e:
        print(f"[Whisper] Error concatenando bloques: {e}")
        return np.array([], dtype='float32')


def escuchar_microfono(duracion: float = 15.0) -> str | None:
    """Graba audio y transcribe con Groq Whisper. Devuelve texto o None."""
    global _grabar_manual_activa, _detener_grabacion_manual

    if not HAS_SD or not _whisper_model or not _groq_keys:
        print("[Whisper] Error: SD/Whisper/Groq no disponibles")
        _bridge.append_html.emit(_html_burbuja_jarvis(
            '<span style="color:#ffb86b;font-size:12px;">'
            '⚠️ Voz no disponible: revisa el permiso del micrófono y la conexión de Groq.</span>'
        ))
        return None

    _grabar_manual_activa = True
    _detener_grabacion_manual.clear()

    try:
        print("[Whisper] Iniciando grabación manual — presiona mic de nuevo para parar...")
        _pausar_escucha_continua.set()
        try:
            with _sd_audio_lock:
                audio_np = _grabar_hasta_silencio(max_duracion=duracion, min_amp=0.002)
        except Exception as e_audio:
            print(f"[Whisper] Error capturando audio: {e_audio}")
            _bridge.append_html.emit(_html_burbuja_jarvis(
                f'<span style="color:#ff6655;font-size:12px;">'
                f'⚠️ No pude abrir el micrófono. Selecciona otro dispositivo en Configuración.<br>'
                f'<small>{_escape_html(e_audio)}</small></span>'
            ))
            return None

        if audio_np.size == 0 or float(np.max(np.abs(audio_np))) < 0.002:
            print(f"[Whisper] No hubo voz clara (amp={float(np.max(np.abs(audio_np))) if audio_np.size else 0:.4f})")
            return None

        try:
            texto = _transcribir_con_groq_whisper(audio_np, language="es")
            print(f"[Whisper] Transcripción: {texto}")
            return texto if texto else None
        except Exception as e_transcribe:
            print(f"[Whisper] Error transcribiendo: {e_transcribe}")
            return None
    except Exception as e:
        print(f"[Whisper] Error general en escuchar_microfono: {e}")
        return None
    finally:
        _grabar_manual_activa = False
        _detener_grabacion_manual.clear()
        try:
            _pausar_escucha_continua.clear()
        except Exception:
            pass
        # Dar tiempo para que los threads de audio se cierren correctamente
        time.sleep(0.5)

# Variable para escucha continua
_escucha_activa = threading.Event()
_pausar_escucha_continua = threading.Event()
_sd_audio_lock = threading.Lock()
_grabar_manual_activa = False
_detener_grabacion_manual = threading.Event()

def _hilo_siempre_escuchando():
    """Escucha continua con wake word 'Jarvis' — solo transcribe en Groq cuando detecta sonido."""
    _KEYS_LISTAS.wait(timeout=30)
    if not HAS_SD or not _groq_keys:
        print("[Escucha] Sin Groq/sounddevice — escucha desactivada")
        return
    print("[Escucha] 🎤 Escucha continua activa — di 'Jarvis' para activar")

    fs        = 16000
    chunk_dur = 4.0   # chunk más largo para capturar frases completas
    cmd_dur   = 18.0  # permite terminar la frase sin cortar al principio

    # Wake words — solo variaciones naturales del español, sin sobreextender
    _WAKE = {
        "jarvis", "jarvi", "jarbe", "jarbis", "yarvis",
        "harvis", "garvis", "sarvis", "darvis",
    }
    _WAKE_SUBSTR = ["jarvi"]   # solo substring muy cercano
    _AMP_MIN     = 0.0025  # Umbral wake word para micrófonos con señal baja
    _AMP_MIN_CMD = 0.003  # Umbral de comandos; evita perder voz normal
    _MIN_CHUNK_DURATION_S = 1.2  # El wake word debe estar en al menos 1.2s de audio real
    _MIN_WORDS_VALID      = 2    # Mínimo 2 palabras para considerar comando real

    def _validar_transcripcion(txt: str) -> bool:
        if not txt or len(txt) < 3:
            return False
        palabras = txt.split()
        # Mínimo 1 palabra real (no solo ruido)
        if len(palabras) < 1:
            return False
        if len(palabras) > 20:  # >20 palabras = ruido/audio ambiente largo
            return False
        especiales = sum(1 for c in txt if not c.isalnum() and c not in ' áéíóúñü.,!?-\'')
        if especiales > len(txt) * 0.25:
            return False
        # Rechazar si parece un idioma diferente al español (muchas palabras sin vocales típicas)
        _NO_ES_PALABRAS = {"the", "and", "this", "that", "with", "from", "have", "been",
                           "will", "would", "could", "should", "their", "there"}
        palabras_lower = {p.lower() for p in palabras}
        if len(palabras_lower & _NO_ES_PALABRAS) >= 2:
            return False
        # Rechazar la frase genérica de ejemplo que a veces devuelve Whisper como si fuera un comando real.
        _PROMPT_HALLUCINATION = {"abre", "busca", "reproduce", "sube", "baja", "volumen", "brillo", "clima", "noticias", "notas"}
        if len(palabras) >= 6 and len(palabras_lower & _PROMPT_HALLUCINATION) >= 5:
            return False
        return True

    def _es_wake_valido(texto_clean: str, palabras: list, amp: float, rms: float) -> bool:
        """Valida que el wake word sea genuino y no ruido/audio ambiente."""
        # Amplitud y RMS mínimos
        if amp < _AMP_MIN or rms < 0.0015:
            return False
        # Debe contener la wake word real y no una lista genérica de verbos.
        tiene_wake = (
            any(w in _WAKE for w in palabras[:3])
            or any(sub in texto_clean for sub in _WAKE_SUBSTR)
        )
        # Si la transcripción es un bloque genérico de comandos sin ninguna referencia a Jarvis,
        # descartarla como falso positivo de ruido/TV.
        if not tiene_wake and len(palabras) >= 5 and any(w in texto_clean for w in ['abre', 'busca', 'sube', 'baja', 'clima', 'noticias']):
            return False
        if not tiene_wake:
            return False
        # Requerir que la wake word aparezca al inicio del texto transcrito.
        if not palabras:
            return False
        if palabras[0] not in _WAKE and not any(sub in palabras[0] for sub in _WAKE_SUBSTR):
            return False
        # Si hay más de 5 palabras y la primera no es wake word, ignorar.
        if len(palabras) > 5 and not any(w in palabras[:2] for w in _WAKE):
            return False
        # Rechazar si el texto es muy largo sin wake word al inicio (audio ambiente con "jarvis" accidental)
        if len(palabras) > 8 and not any(w in _WAKE for w in palabras[:3]):
            return False
        return True

    while True:
        try:
            # Anti-eco: no grabar mientras Jarvis habla
            if _jarvis_hablando.is_set():
                _jarvis_hablando.wait(timeout=10)
                time.sleep(0.2)
                continue

            # Pausar la escucha continua mientras el mic manual está activo
            while _pausar_escucha_continua.is_set():
                time.sleep(0.15)

            # Monitorear sonido (no transcribir todo)
            try:
                with _sd_audio_lock:
                    rec_kwargs = {"samplerate": fs, "channels": 1, "dtype": "float32"}
                    dispositivo = _dispositivo_microfono()
                    if dispositivo is not None:
                        rec_kwargs["device"] = dispositivo
                    chunk = sd.rec(int(chunk_dur * fs), **rec_kwargs)
                    sd.wait()
            except Exception as e:
                print(f"[Escucha] Error audio continuo: {e}")
                time.sleep(1)
                continue

            # Descartar si empezó a hablar durante grabación
            if _jarvis_hablando.is_set():
                continue

            chunk_np = chunk.flatten()
            # Sanitizar NaN/inf antes de calcular métricas
            chunk_np = np.nan_to_num(chunk_np, nan=0.0, posinf=0.0, neginf=0.0)
            amp = float(np.max(np.abs(chunk_np)))
            rms = float(np.sqrt(np.mean(chunk_np * chunk_np))) if chunk_np.size > 0 else 0.0

            # Solo transcribir si hay sonido significativo y estable
            if chunk_np.size == 0 or amp < _AMP_MIN or rms < 0.0015:
                continue

            # Transcribir SOLO este chunk
            texto = _transcribir_con_groq_whisper(chunk_np, language="es")
            if not texto or not _validar_transcripcion(texto):
                continue

            texto_clean = re.sub(r'[^\w\s]', '', texto.lower())
            palabras = texto_clean.split()

            detectado = _es_wake_valido(texto_clean, palabras, amp, rms)

            if detectado:
                print(f"[Escucha] 🔔 Wake word: '{texto}'")

                # Remover wake word para ver el comando
                palabras_full = palabras.copy()
                for word in palabras_full[:]:
                    if word in _WAKE or any(sub in word for sub in _WAKE_SUBSTR):
                        palabras_full.remove(word)
                        break

                if len(palabras_full) >= 1:
                    try:
                        with _sd_audio_lock:
                            extra = sd.rec(int(4.0 * fs), samplerate=fs, channels=1, dtype='float32')
                            sd.wait()
                        extra_np = extra.flatten()
                        extra_amp = float(np.max(np.abs(extra_np))) if extra_np.size > 0 else 0.0
                        if extra_amp >= _AMP_MIN_CMD:
                            audio_completo = np.concatenate([chunk_np, extra_np])
                            texto_completo = _transcribir_con_groq_whisper(audio_completo, language="es")
                            if texto_completo and _validar_transcripcion(texto_completo):
                                texto_clean2 = re.sub(r'[^\w\s]', '', texto_completo.lower())
                                palabras2 = texto_clean2.split()
                                for word in palabras2[:]:
                                    if word in _WAKE or any(sub in word for sub in _WAKE_SUBSTR):
                                        palabras2.remove(word)
                                        break
                                if palabras2 and len(' '.join(palabras2)) >= 4:
                                    palabras_full = palabras2
                    except Exception:
                        pass

                    if len(' '.join(palabras_full)) < 4:
                        palabras_full = []

                    if palabras_full:
                        cmd_rapido = ' '.join(palabras_full)
                        print(f"[Escucha] ⚡ Comando rápido detectado: '{cmd_rapido}'")
                        _bridge.append_html.emit(_html_burbuja_jarvis(
                            f'<span style="color:#ffff88;font-size:11px;">⚡ Procesando: {cmd_rapido}</span>'
                        ))
                        _bridge.scroll_down.emit()
                        threading.Thread(
                            target=interpretar_multiple,
                            args=(cmd_rapido, None),
                            daemon=True
                        ).start()
                        continue
                
                # ── FLUJO NORMAL: esperar comando ──
                _bridge.append_html.emit(_html_burbuja_jarvis(
                    '<span style="color:#44cc88;font-size:11px;">🎤 Escuchando...</span>'
                ))
                _bridge.scroll_down.emit()
                hablar("Dime", None)
                time.sleep(0.2)
                
                # Esperar a que Jarvis termine
                for _ in range(30):
                    if not _jarvis_hablando.is_set():
                        break
                    time.sleep(0.1)
                time.sleep(0.1)

                # Grabar el comando con anti-silencio mejorado
                cmd_np = _grabar_hasta_silencio(max_duracion=cmd_dur)
                
                # Verificar amplitud máxima del comando grabado
                max_amp_cmd = float(np.max(np.abs(cmd_np))) if cmd_np.size > 0 else 0.0
                if cmd_np.size == 0 or max_amp_cmd < _AMP_MIN_CMD:
                    # Silencio o sonido muy débil - no procesar
                    print(f"[Escucha] 🔇 Silencio detectado (amp={max_amp_cmd:.4f}, min={_AMP_MIN_CMD}), ignorando...")
                    continue

                # Filtrar comandos demasiado cortos o ruidosos
                cmd_rms = float(np.sqrt(np.mean(cmd_np * cmd_np))) if cmd_np.size > 0 else 0.0
                if cmd_rms < 0.001:
                    print(f"[Escucha] 🔇 Comando demasiado débil/ruidoso (rms={cmd_rms:.4f}), ignorando...")
                    continue
                
                # Transcribir comando con Groq
                cmd_txt = _transcribir_con_groq_whisper(cmd_np, language="es")
                if cmd_txt and _validar_transcripcion(cmd_txt):
                    print(f"[Escucha] 📝 '{cmd_txt}'")
                    threading.Thread(
                        target=interpretar_multiple,
                        args=(cmd_txt, None),
                        daemon=True
                    ).start()
        except Exception as e:
            print(f"[Escucha] Error: {e}")
            time.sleep(1)

def _inicializar_agentes():
    """Inyecta el contexto compartido en todos los agentes."""

    ctx_base = {
        "hablar":          hablar,
        "cola_voz":        _cola_voz,
        "bridge":          _bridge,
        "html_burbuja":    _html_burbuja,
        "limpiar_html":    _limpiar_html,
        "markdown_a_html": _markdown_a_html,
        "base_path":       data_path,
        "resource_path":   base_path,
        "config":          config,
    }

    # ── agent_search ──────────────────────────────────────────────────────────
    agent_search.init({
        **ctx_base,
        "html_burbuja_jarvis": _html_burbuja_jarvis,
        "latex_a_html":        _latex_a_html,
        "KEYS_LISTAS":         _KEYS_LISTAS,
        "groq_keys":           lambda: _groq_keys,
        "groq_key_activa":     _groq_key_activa,
        "groq_rotar_key":      _groq_rotar_key,
        "gemini_key_activa":   _gemini_key_activa,
        "gemini_rotar_key":    _gemini_rotar_key,
        "gemini_keys":         lambda: _gemini_keys,
        "GROQ_BASE_URL":       GROQ_BASE_URL,
        "GROQ_MODEL":          GROQ_MODEL,
        "groq_tokens":         _groq_tokens,
        "guardar_tokens":      _guardar_tokens,
        "historial":           lambda: _historial,
        "agregar_historial":   _agregar_historial,
        "formatear_historial": _formatear_historial,
        "memoria_usuario":     memoria_usuario,
        "guardar_memoria":     _guardar_memoria,
        "patrones":            _patrones,
        "NEWS_API_KEY":        lambda: NEWS_API_KEY,
        "GOOGLE_SEARCH_API_KEY": lambda: GOOGLE_SEARCH_API_KEY,
        "GOOGLE_SEARCH_CX":    lambda: GOOGLE_SEARCH_CX,
        "ANTHROPIC_API_KEY":   lambda: ANTHROPIC_API_KEY,
        "ANTHROPIC_BASE_URL":  ANTHROPIC_BASE_URL,
        "ANTHROPIC_MODEL":     ANTHROPIC_MODEL,
    })
    print("[Agentes] ✅ agent_search listo")

    # ── agent_images ──────────────────────────────────────────────────────────
    agent_images.init({
        **ctx_base,
        "UNSPLASH_ACCESS_KEY": lambda: UNSPLASH_ACCESS_KEY,
        "PEXELS_API_KEY":      lambda: PEXELS_API_KEY,
        "GOOGLE_SEARCH_API_KEY": lambda: GOOGLE_SEARCH_API_KEY,
        "GOOGLE_SEARCH_CX":    lambda: GOOGLE_SEARCH_CX,
    })
    print("[Agentes] ✅ agent_images listo")

    agent_screen.init({
        **ctx_base,
        "notify": lambda texto: print(f"[Screen] {texto}"),
        "analizar_pantalla": _analizar_pantalla_con_vision,
    })
    print("[Agentes] ✅ agent_screen listo")

    # ── agent_pc ──────────────────────────────────────────────────────────────
    agent_pc.init({
        **ctx_base,
        "MAPA_SISTEMA":          lambda: MAPA_SISTEMA,
        "apps":                  apps,
        "archivos_memoria":      archivos_memoria,
        "modos":                 modos,
        "quitar_tildes":         quitar_tildes,
        "normalizar_nombre_app": normalizar_nombre_app,
        "_score_app_v9":         _score_app_v9,
        "obtener_apps_sistema":  obtener_apps_sistema,
        "ejecutar_app":          ejecutar_app,
        "buscar_archivo_en_memoria": buscar_archivo_en_memoria,
        "EXTENSIONES_PERMITIDAS":  EXTENSIONES_PERMITIDAS,
        "CARPETAS_IGNORAR":        CARPETAS_IGNORAR,
        "VK_VOLUME_MUTE":          VK_VOLUME_MUTE,
        "VK_VOLUME_DOWN":          VK_VOLUME_DOWN,
        "VK_VOLUME_UP":            VK_VOLUME_UP,
    })
    print("[Agentes] ✅ agent_pc listo")

    # ── agent_google ──────────────────────────────────────────────────────────
    agent_google.init({
        **ctx_base,
        "obtener_credenciales": None,  # agent_google tiene su propio OAuth
        "quitar_tildes":        quitar_tildes,
        "formatear_fecha":      formatear_fecha,
        "SERVIDOR_AUTH":        SERVIDOR_AUTH,
        "SCOPES":               SCOPES,
    })
    print("[Agentes] ✅ agent_google listo")

    # ── agent_notas ───────────────────────────────────────────────────────────
    agent_notas.init({
        **ctx_base,
    })
    print("[Agentes] ✅ agent_notas listo")

# =============================================================================
# 15. INTERFAZ GRÁFICA
# =============================================================================

ESTILO_DIALOG = """
QDialog, QWidget {
    background: #060d1a;
    color: #ccd6f6;
    font-family: 'Segoe UI', sans-serif;
    font-size: 14px;
}
QLabel#titulo { color: #4db8ff; font-size: 18px; font-weight: bold; }
QLabel#sub    { color: #8899bb; font-size: 13px; }
QPushButton   { background: rgba(14,48,120,0.80); color: #4db8ff;
                border: 1px solid #1a5fa8; border-radius: 10px;
                padding: 10px 20px; font-size: 14px; }
QPushButton:hover   { background: #1a3fc0; color: white; }
QPushButton#guardar { background: #0d4a90; }
QPushButton#cerrar  { background: rgba(80,20,20,0.7); color: #e07070; }
QLineEdit     { background: rgba(10,20,40,0.85); color: #dde6f5;
                border: 1.5px solid rgba(77,184,255,0.4);
                border-radius: 8px; padding: 8px 12px; }
QFrame#linea  { color: rgba(77,184,255,0.3); }
"""


class ScreenFrameBridge(QObject):
    frame_ready = Signal(object)


def _icono_svg_jarvis(svg_path: str) -> QIcon:
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="{svg_path}" fill="#b9ddff"/></svg>'.encode("utf-8")
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    QSvgRenderer(svg).render(painter)
    painter.end()
    return QIcon(pixmap)


class PantallaOverlay(QWidget):
    """HUD de 200x200; la pantalla real permanece visible detrás y fuera de la captura."""

    def __init__(self, parent=None):
        # Crear el overlay como ventana independiente de nivel superior
        super().__init__(None)
        self.setWindowTitle("Jarvis HUD")
        # Use Window instead of Tool to get more stable top-level behavior on Windows
        self.setWindowFlags(
            Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.FramelessWindowHint
        )
        self.setFixedSize(308, 66)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        # Ensure overlay stays interactive even when application loses focus
        try:
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        except Exception:
            pass
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._global_eventfilter_installed = False
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setStyleSheet(
            "QWidget { background: rgba(6, 12, 24, 0.94); color: #b9ddff; border:1px solid rgba(0,212,255,0.25); border-radius:16px; }"
            "QPushButton { background: rgba(2, 18, 36, 0.95); color: #8fd7ff; border:1px solid rgba(77,184,255,0.22); border-radius:14px; }"
            "QPushButton:hover { background: rgba(0, 112, 210, 0.16); color: #ffffff; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Header removed per user request; overlay draggable from non-button areas.
        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        button_row.addStretch()
        chat = QPushButton()
        chat.setIcon(_icono_svg_jarvis("M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H6l-2 2V4h16v12z"))
        chat.setToolTip("Abrir chat")
        chat.clicked.connect(self._toggle_small_chat)
        self._chat_button = chat
        config_button = QPushButton()
        config_button.setIcon(_icono_svg_jarvis("M19.14,12.94c0.04-0.3,0.06-0.61,0.06-0.94c0-0.32-0.02-0.64-0.07-0.94l2.03-1.58c0.18-0.14,0.23-0.41,0.12-0.61 l-1.92-3.32c-0.12-0.22-0.37-0.29-0.59-0.22l-2.39,0.96c-0.5-0.38-1.03-0.7-1.62-0.94L14.4,2.81c-0.04-0.24-0.24-0.41-0.48-0.41h-3.84c-0.24,0-0.43,0.17-0.47,0.41L9.25,5.35C8.66,5.59,8.12,5.92,7.63,6.29L5.24,5.33c-0.22-0.08-0.47,0-0.59,0.22L2.74,8.87c-0.12,0.21-0.08,0.47,0.12,0.61l2.03,1.58C4.84,11.36,4.8,11.69,4.8,12s0.04,0.64,0.07,0.94l-2.03,1.58c-0.18,0.14-0.23,0.41-0.12,0.61l1.92,3.32c0.12,0.22,0.37,0.29,0.59,0.22l2.39-0.96c0.5,0.38,1.03,0.7,1.62,0.94l0.36,2.54c0.04,0.24,0.24,0.41,0.48,0.41h3.84c0.24,0,0.44-0.17,0.47-0.41l0.36-2.54c0.59-0.24,1.13-0.56,1.62-0.94l2.39,0.96c0.22,0.08,0.47,0,0.59-0.22l1.92-3.32c0.12-0.22,0.07-0.47-0.12-0.61L19.14,12.94z M12,15.6c-1.98,0-3.6-1.62-3.6-3.6s1.62-3.6,3.6-3.6s3.6,1.62,3.6,3.6S13.98,15.6,12,15.6z"))
        config_button.setToolTip("Configuración")
        config_button.clicked.connect(self._open_config_local)
        mic = QPushButton()
        mic.setIcon(_icono_svg_jarvis("M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z"))
        mic.setToolTip("Activar micrófono")
        mic.clicked.connect(self._on_mic_clicked)
        self._mic_button = mic
        screen = QPushButton()
        screen.setIcon(_icono_svg_jarvis("M21 3H3c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h7v2H7v2h10v-2h-3v-2h7c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm0 14H3V5h18v12z"))
        screen.setToolTip("Analizar la pantalla")
        screen.clicked.connect(self._on_screen_clicked)
        close = QPushButton("×")
        close.setToolTip("Cerrar visor en tiempo real")
        close.setFixedSize(42, 42)
        close.setStyleSheet(
            "QPushButton { background: rgba(5, 10, 25, 0.9); color: #dde6f5; border:1px solid rgba(77,184,255,0.2); border-radius:12px; }"
            "QPushButton:hover { background: rgba(255,255,255,0.12); }"
        )
        close.clicked.connect(self._cerrar)
        for button in (chat, config_button, mic, screen):
            button.setFixedSize(52, 52)
            button.setIconSize(QSize(24, 24))
            button.setMouseTracking(True)
            button_row.addWidget(button)
        button_row.addWidget(close)
        layout.addLayout(button_row)
        # pending messages for overlay chat when compact view is closed
        self._pending_overlay_messages = []
        self._drag_pos = None
        self._dragging = False
        # debug flag to print eventFilter decisions when True (temporarily enabled)
        self._debug_overlay = False
        # --- Chat compacto como ventana separada (oculto por defecto)
        self._small_chat_window = QWidget(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self._small_chat_window.setWindowFlags(self._small_chat_window.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self._small_chat_window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._small_chat_window.setStyleSheet("background: rgba(6,12,24,0.95); border:1px solid rgba(77,184,255,0.2); border-radius:8px;")
        self._small_chat_window.setFixedSize(220, 520)
        sc_layout = QVBoxLayout(self._small_chat_window)
        sc_layout.setContentsMargins(8,8,8,8)
        sc_layout.setSpacing(6)

        header_bar = QWidget()
        header_bar.setStyleSheet("background: transparent;")
        header_layout = QHBoxLayout(header_bar)
        header_layout.setContentsMargins(0,0,0,0)
        header_layout.setSpacing(6)
        header_title = QLabel("Chat rápido")
        header_title.setStyleSheet("color:#dde6f5;font-size:13px;font-weight:600;")
        header_close = QPushButton("×")
        header_close.setFixedSize(22,22)
        header_close.setStyleSheet(
            "QPushButton { background: rgba(5,10,25,0.85); color: #dde6f5; border:none; border-radius:11px; }"
            "QPushButton:hover { background: rgba(255,255,255,0.12); }"
        )
        header_close.clicked.connect(lambda: self._small_chat_window.hide())
        header_layout.addWidget(header_title)
        header_layout.addStretch()
        header_layout.addWidget(header_close)
        sc_layout.addWidget(header_bar)

        self._small_chat_view = QTextBrowser()
        self._small_chat_input = QLineEdit()
        self._small_chat_input.setPlaceholderText('Escribe aquí...')
        self._small_chat_input.returnPressed.connect(self._send_small_chat)
        sc_layout.addWidget(self._small_chat_view)
        sc_layout.addWidget(self._small_chat_input)
        self._small_chat_window.hide()
        self._frame_bridge = ScreenFrameBridge()
        self._stream_stop = threading.Event()
        self._stream_thread = None
        _bridge.append_html.connect(self._overlay_append_html)
        # Mic animation timer
        self._mic_anim_timer = QTimer(self)
        self._mic_anim_timer.setInterval(350)
        self._mic_anim_timer.timeout.connect(self._mic_anim_step)
        self._mic_anim_state = False

    def _cerrar(self):
        self.detener_stream()
        self.hide()

    def _capturar_en_segundo_plano(self):
        while not self._stream_stop.is_set():
            try:
                imagen = agent_screen.capturar_frame()
                if imagen is not None:
                    rgba = imagen.convert("RGBA")
                    agent_screen.publicar_frame(rgba)
            except Exception as exc:
                print(f"[Overlay] Error en stream: {exc}")
            self._stream_stop.wait(0.5)

    def _toggle_small_chat(self):
        try:
            vis = not self._small_chat_window.isVisible()
            if vis:
                # posicionar la ventana justo debajo del overlay
                try:
                    # posicionar la ventana justo debajo del overlay, pero mantenerla dentro de la pantalla
                    screen = self.screen().availableGeometry() if self.screen() else QApplication.primaryScreen().availableGeometry()
                    gp = self.mapToGlobal(QPoint(0, self.height()))
                    x = gp.x()
                    y = gp.y()
                    # clamp horizontally
                    if x + self._small_chat_window.width() > screen.right():
                        x = max(screen.left(), screen.right() - self._small_chat_window.width() - 8)
                    if y + self._small_chat_window.height() > screen.bottom():
                        y = max(screen.top(), screen.bottom() - self._small_chat_window.height() - 8)
                    self._small_chat_window.move(x, y)
                except Exception:
                    pass
                # Cargar historial de la sesión actual en la vista de chat
                try:
                    html = []
                    for item in _historial_sesion_actual():
                        rol = str(item.get('rol','')).lower()
                        texto = str(item.get('texto','') or '')
                        if rol in ('assistant','jarvis'):
                            html.append(_html_burbuja_jarvis(_limpiar_html(texto)))
                        else:
                            html.append(_html_burbuja_usuario(_limpiar_html(texto)))
                    self._small_chat_view.setHtml('<div style="padding:6px">' + '\n'.join(html) + '</div>')
                    sb = self._small_chat_view.verticalScrollBar()
                    sb.setValue(sb.maximum())
                    self._small_chat_window.show()
                    self._small_chat_window.raise_()
                    # Volcar mensajes pendientes recibidos mientras la vista estaba cerrada
                    try:
                        if getattr(self, '_pending_overlay_messages', None):
                            for m in self._pending_overlay_messages:
                                try:
                                    self._small_chat_view.append(m)
                                except Exception:
                                    pass
                            self._pending_overlay_messages.clear()
                            sb = self._small_chat_view.verticalScrollBar()
                            sb.setValue(sb.maximum())
                    except Exception:
                        pass
                except Exception as e:
                    print(f"[Overlay] Error cargando historial: {e}")
                    self._small_chat_window.show()
                    self._small_chat_window.raise_()
                    # if we moved the overlay to fit the chat, remember and adjust
                    try:
                        screen = self.screen().availableGeometry() if self.screen() else QApplication.primaryScreen().availableGeometry()
                        chat_h = self._small_chat_window.height()
                        overlay_geo = self.geometry()
                        overlay_x = overlay_geo.x()
                        overlay_y = overlay_geo.y()
                        bottom_needed = overlay_y + overlay_geo.height() + chat_h
                        if bottom_needed > screen.bottom():
                            delta = bottom_needed - screen.bottom() + 8
                            new_y = max(screen.top() + 8, overlay_y - delta)
                            # store original
                            if not hasattr(self, '_moved_for_chat') or not self._moved_for_chat:
                                self._saved_pos = self.pos()
                                self._moved_for_chat = True
                            self.move(overlay_x, new_y)
                    except Exception:
                        pass
                self._small_chat_input.setFocus()
            else:
                # hide and restore overlay position if moved
                try:
                    self._small_chat_window.hide()
                    if hasattr(self, '_moved_for_chat') and self._moved_for_chat and hasattr(self, '_saved_pos') and self._saved_pos is not None:
                        try:
                            self.move(self._saved_pos)
                        except Exception:
                            pass
                        self._moved_for_chat = False
                        self._saved_pos = None
                except Exception:
                    pass
        except Exception as e:
            print(f"[Overlay] Error toggling small chat: {e}")

    def _send_small_chat(self):
        txt = (self._small_chat_input.text() or "").strip()
        if not txt:
            return
        try:
            # Mostrar en la vista compacta
            try:
                self._small_chat_view.append(_html_burbuja_usuario(_escape_html(txt)))
                sb = self._small_chat_view.verticalScrollBar()
                sb.setValue(sb.maximum())
            except Exception:
                pass
            # También enviar al flujo normal para procesar
            threading.Thread(target=interpretar_multiple, args=(txt, None, False), daemon=True).start()
        except Exception as e:
            print(f"[Overlay] Error enviando mensaje: {e}")
        self._small_chat_input.clear()

    def _on_mic_clicked(self):
        # Control local del micrófono manual (inicia/parar)
        global _grabar_manual_activa, _detener_grabacion_manual
        try:
            if not getattr(self, '_mic_recording', False):
                # Iniciar
                self._mic_recording = True
                try:
                    # use light blue similar to main UI for active mic
                    self._mic_button.setStyleSheet('background:#00d4ff;color:#021025;border:1px solid #1a5fa8;')
                except Exception:
                    pass
                threading.Thread(target=lambda: _ejecutar_accion({"accion": "iniciar_escucha_microfono", "params": {}}, None), daemon=True).start()
                try:
                    # trigger V5 visual mic (if available)
                    _inyectar_en_v5("__ACTIVATE_MIC__")
                except Exception:
                    pass
                try:
                    # iniciar animación del mic
                    self._mic_anim_state = False
                    self._mic_anim_timer.start()
                except Exception:
                    pass
                # Watcher que reseteará el botón cuando termine la grabación global
                def _watch():
                    try:
                        # Esperar a que la grabación empiece en el global
                        waited = 0.0
                        while waited < 5.0 and not _grabar_manual_activa:
                            time.sleep(0.1); waited += 0.1
                        # Ahora esperar a que termine
                        while _grabar_manual_activa:
                            time.sleep(0.2)
                    except Exception:
                        pass
                    finally:
                        try:
                            self._mic_recording = False
                            self._mic_button.setStyleSheet('')
                        except Exception:
                            pass
                threading.Thread(target=_watch, daemon=True).start()
            else:
                # Parar la grabación global
                try:
                    _detener_grabacion_manual.set()
                except Exception:
                    pass
                self._mic_recording = False
                try:
                    self._mic_anim_timer.stop()
                    self._mic_button.setIconSize(QSize(24, 24))
                    # restore default style
                    self._mic_button.setStyleSheet('')
                    # reset V5 mic visuals
                    _reset_v5_mic()
                except Exception:
                    pass
        except Exception as e:
            print(f"[Overlay] Error mic toggle: {e}")

    def _on_screen_clicked(self):
        try:
            threading.Thread(target=lambda: _ejecutar_accion({"accion": "analizar_pantalla", "params": {}}, None), daemon=True).start()
            # provide quick visual feedback
            try:
                self._mic_button.setStyleSheet('background:#074;color:#b9ddff;')
                QTimer.singleShot(800, lambda: self._mic_button.setStyleSheet(''))
            except Exception:
                pass
        except Exception as e:
            print(f"[Overlay] Error screen analyze click: {e}")

    def _overlay_append_html(self, html: str):
        try:
            if getattr(self, '_small_chat_window', None) and self._small_chat_window.isVisible():
                try:
                    self._small_chat_view.append(html)
                    sb = self._small_chat_view.verticalScrollBar()
                    sb.setValue(sb.maximum())
                except Exception:
                    pass
            else:
                try:
                    # store pending messages to show when compact chat opens
                    if not hasattr(self, '_pending_overlay_messages'):
                        self._pending_overlay_messages = []
                    self._pending_overlay_messages.append(html)
                except Exception:
                    pass
        except Exception:
            pass

    def _open_config_local(self):
        try:
            dlg = VentanaConfig(self)
            # Position near overlay but centered on screen if possible
            try:
                screen = QApplication.primaryScreen().availableGeometry()
                x = screen.center().x() - dlg.width() // 2
                y = screen.center().y() - dlg.height() // 2
                dlg.move(max(screen.left() + 20, min(x, screen.right() - dlg.width() - 20)),
                         max(screen.top() + 20, min(y, screen.bottom() - dlg.height() - 20)))
            except Exception:
                pass
            dlg.exec()
        except Exception as e:
            print(f"[Overlay] Error opening local config: {e}")

    def _mic_anim_step(self):
        try:
            # alternar tamaño de icono como pulso
            if self._mic_anim_state:
                self._mic_button.setIconSize(QSize(24, 24))
            else:
                self._mic_button.setIconSize(QSize(18, 18))
            self._mic_anim_state = not self._mic_anim_state
        except Exception:
            pass

    # --- Mouse events to implement dragging without intercepting button clicks ---
    def mousePressEvent(self, event):
        try:
            if event.button() == Qt.MouseButton.LeftButton:
                local = event.pos()
                child = self.childAt(local)
                # start drag only if not clicking a button
                if child is None or not isinstance(child, QPushButton):
                    self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()
                    self._dragging = False
                    event.accept()
                    return
        except Exception:
            pass
        return super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        try:
            if getattr(self, '_drag_pos', None) is not None and event.buttons() & Qt.MouseButton.LeftButton:
                self._dragging = True
                try:
                    new_pos = event.globalPos() - self._drag_pos
                    self.move(new_pos)
                except Exception:
                    pass
                event.accept()
                return
        except Exception:
            pass
        return super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        try:
            if event.button() == Qt.MouseButton.LeftButton and getattr(self, '_drag_pos', None) is not None:
                self._drag_pos = None
                self._dragging = False
                event.accept()
                return
        except Exception:
            pass
        return super().mouseReleaseEvent(event)

    def iniciar_stream(self):
        self.show()
        # record original position to allow restoring after chat
        try:
            self._orig_pos = self.pos()
        except Exception:
            self._orig_pos = None
        self._configurar_exclusion_captura()
        pantalla = self.screen().availableGeometry() if self.screen() else None
        if pantalla:
            self.move(pantalla.right() - self.width() - 18, pantalla.top() + 18)
        self.raise_()
        if self._stream_thread is None or not self._stream_thread.is_alive():
            self._stream_stop.clear()
            self._stream_thread = threading.Thread(
                target=self._capturar_en_segundo_plano,
                daemon=True,
                name="ScreenStream",
            )
            self._stream_thread.start()

        # ensure overlay accepts mouse events (prevent click-through to underlying UI)
        try:
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
            self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        except Exception:
            pass

    def detener_stream(self):
        self._stream_stop.set()

    def _configurar_exclusion_captura(self):
        try:
            import ctypes
            hwnd = int(self.winId())
            ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, 0x11)
        except Exception as exc:
            print(f"[Overlay] Exclusión de captura no disponible: {exc}")


class VentanaModoArranque(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Jarvis — Modo de inicio")
        self.setFixedSize(380, 220)
        self.setStyleSheet(ESTILO_DIALOG)
        self.modo_elegido = "normal"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(10)
        titulo = QLabel("🚀 ¿Cómo cargo las apps?"); titulo.setObjectName("titulo")
        layout.addWidget(titulo)
        sub = QLabel("Normal: solo menú inicio (rápido)\nPower: incluye Microsoft Store (más lento)")
        sub.setObjectName("sub"); sub.setWordWrap(True)
        layout.addWidget(sub)
        layout.addSpacing(10)
        btns = QHBoxLayout()
        btn_n = QPushButton("📂 Normal"); btn_n.clicked.connect(lambda: self._elegir("normal"))
        btn_p = QPushButton("⚡ Power");  btn_p.clicked.connect(lambda: self._elegir("power"))
        btns.addWidget(btn_n); btns.addWidget(btn_p)
        layout.addLayout(btns)

    def _elegir(self, modo):
        self.modo_elegido = modo
        self.accept()


class Interruptor(QPushButton):
    """Interruptor compacto tipo sistema, sin checks ni cuadrados."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(46, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("QPushButton { border: none; background: transparent; }")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor("#32c759" if self.isChecked() else "#3a3f45"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(1, 3, 44, 20, 10, 10)
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(24 if self.isChecked() else 4, 5, 16, 16)


class VentanaConfig(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configuración — Jarvis")
        self.setMinimumSize(480, 620)
        self.setStyleSheet(ESTILO_DIALOG)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        contenedor = QWidget()
        layout = QVBoxLayout(contenedor)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(8)

        titulo = QLabel("⚙️ Configuración")
        titulo.setObjectName("titulo")
        layout.addWidget(titulo)

        def _seccion(nombre):
            lbl = QLabel(nombre)
            lbl.setStyleSheet("color:#4db8ff;font-size:13px;font-weight:bold;margin-top:10px;")
            layout.addWidget(lbl)
            sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
            sep.setStyleSheet("color:rgba(77,184,255,0.25);")
            layout.addWidget(sep)

        def _chk(texto, config_key, default=True):
            fila = QWidget()
            fila_layout = QHBoxLayout(fila)
            fila_layout.setContentsMargins(0, 2, 0, 2)
            etiqueta = QLabel(texto)
            etiqueta.setStyleSheet("color:#c9d7eb;background:transparent;border:none;")
            cb = Interruptor()
            cb.setChecked(config.get(config_key, default))
            fila_layout.addWidget(etiqueta)
            fila_layout.addStretch()
            fila_layout.addWidget(cb)
            layout.addWidget(fila)
            return cb, config_key

        # ── Integración Google ──
        _seccion("🔗 Integración Google")
        self._chks = []
        self._chks.append(_chk("📅 Google Calendar (eventos y reuniones)", "google_calendar", True))
        self._chks.append(_chk("📋 Google Tasks (tareas)", "google_tasks", True))
        self._chks.append(_chk("📧 Gmail (correos)", "google_gmail", True))
        self._chks.append(_chk("📂 Google Drive (archivos)", "google_drive", True))
        self._chks.append(_chk("👤 Google Contacts (contactos)", "google_contacts", True))

        # ── Permisos locales ──
        _seccion("🛡️ Permisos locales")
        self._chks.append(_chk("📦 Buscar aplicaciones instaladas y sus rutas", "permiso_escaneo_apps", False))
        self._chks.append(_chk("🎙️ Usar el micrófono", "permiso_microfono", False))
        self._chks.append(_chk("🖥️ Capturar temporalmente la pantalla", "permiso_pantalla", False))
        self._chks.append(_chk("⌨️ Controlar teclado y ratón", "permiso_teclado", False))

        # ── Mapas y Ubicación ──
        _seccion("🗺️ Mapas y Ubicación")
        self._chks.append(_chk("🗺️ Google Maps (abrir mapas externos)", "google_maps", True))
        self._chks.append(_chk("📍 Mapa Jarvis interno (Leaflet)", "mapa_interno", True))
        self._chks.append(_chk("📍 Geocodificación Nominatim (calles/negocios)", "nominatim_geo", True))
        self._chks.append(_chk("✨ Anillos animados en la interfaz", "anillos_interfaz", False))

        # ── Privacidad de Datos ──
        _seccion("🔒 Privacidad de Datos")
        self._chks.append(_chk("💾 Guardar historial de conversación", "guardar_historial", True))
        self._chks.append(_chk("🧠 Memoria del usuario (nombre, ciudad, etc.)", "guardar_memoria_usuario", True))
        self._chks.append(_chk("📝 Guardar notas automáticas de conversación", "notas_auto", True))
        self._chks.append(_chk("📱 Guardar rutas de apps aprendidas", "guardar_links_apps", True))
        self._chks.append(_chk("📁 Guardar archivos recientes en memoria", "guardar_archivos_recientes", True))
        self._chks.append(_chk("🪙 Registrar tokens de IA usados", "registrar_tokens", True))

        # ── Voz y Audio ──
        _seccion("🎤 Voz y Audio")
        self._chks.append(_chk("👂 Escucha continua (wake word 'Jarvis')", "escucha_continua", True))
        self._chks.append(_chk("🔊 TTS activado (respuestas de voz)", "tts_activado", True))
        self._chks.append(_chk("🎙️ ElevenLabs TTS (alta calidad, requiere key)", "usar_elevenlabs", True))
        self._chks.append(_chk("🆓 Edge TTS (voz neural gratis)", "usar_tts_gratis", True))
        _seccion("🎚️ Dispositivo de entrada")
        self._microfono_combo = QComboBox()
        self._microfono_combo.addItem("Predeterminado de Windows", "default")
        if HAS_SD:
            try:
                for indice, dispositivo in enumerate(sd.query_devices()):
                    if int(dispositivo.get("max_input_channels", 0)) > 0:
                        self._microfono_combo.addItem(
                            f"{indice}: {dispositivo.get('name', 'Micrófono')}", indice
                        )
            except Exception as exc:
                print(f"[Config] No se pudieron listar micrófonos: {exc}")
        seleccionado = config.get("microfono_dispositivo", "default")
        posicion = self._microfono_combo.findData(seleccionado)
        self._microfono_combo.setCurrentIndex(max(0, posicion))
        layout.addWidget(self._microfono_combo)

        # ── IA y Búsqueda ──
        _seccion("🤖 IA y Búsqueda")
        self._chks.append(_chk("✨ Gemini para análisis y búsquedas complejas", "usar_gemini_analisis", True))
        self._chks.append(_chk("⚡ Groq para comandos rápidos", "usar_groq_comandos", True))
        self._chks.append(_chk("🔍 Búsqueda web habilitada", "busqueda_web", True))
        self._chks.append(_chk("📰 Noticias automáticas habilitadas", "noticias_habilitadas", True))
        self._chks.append(_chk("🌦️ Clima automático habilitado", "clima_habilitado", True))

        # ── Comportamiento ──
        _seccion("⚡ Comportamiento")
        self._chks.append(_chk("🚀 Modo power (más apps escaneadas al inicio)", "modo_power_inicio", False))
        self._chks.append(_chk("📷 Búsqueda automática de imágenes en respuestas", "imagenes_auto", True))
        self._chks.append(_chk("🔗 Abrir links en navegador por defecto", "abrir_links_navegador", True))
        self._chks.append(_chk("💬 Mostrar panel de chat Qt (F12)", "chat_qt_visible", False))

        layout.addStretch()
        scroll.setWidget(contenedor)

        # Configuración reúne también las dos guías principales en pestañas.
        pestañas = QTabWidget()
        pestañas.setStyleSheet(
            "QTabWidget::pane { border: 1px solid rgba(77,184,255,0.22); border-radius: 10px; }"
            "QTabBar::tab { background: rgba(8,20,40,0.9); color: #8899bb; padding: 10px 18px; margin-right: 3px; }"
            "QTabBar::tab:selected { background: #0d4a90; color: white; }"
        )
        pestañas.addTab(scroll, "⚙ General")
        pestañas.addTab(VentanaComandos(self), "⌘ Comandos")
        pestañas.addTab(VentanaExtensiones(self), "🔌 Extensiones")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(pestañas)

        btns_widget = QWidget()
        btns_widget.setStyleSheet("background: #060d1a; border-top: 1px solid rgba(77,184,255,0.2);")
        btns = QHBoxLayout(btns_widget)
        btns.setContentsMargins(24, 12, 24, 12)
        btn_reset = QPushButton("↩ Restablecer"); btn_reset.setObjectName("cerrar")
        btn_reset.clicked.connect(self._restablecer)
        btn_g = QPushButton("✅ Guardar"); btn_g.setObjectName("guardar")
        btn_g.clicked.connect(self._guardar)
        btn_c = QPushButton("Cancelar"); btn_c.setObjectName("cerrar")
        btn_c.clicked.connect(self.reject)
        btns.addWidget(btn_reset); btns.addStretch()
        btns.addWidget(btn_c); btns.addWidget(btn_g)
        root.addWidget(btns_widget)

    def _guardar(self):
        for cb, key in self._chks:
            config[key] = cb.isChecked()
        config["microfono_dispositivo"] = self._microfono_combo.currentData()
        guardar_config(config)
        self.accept()

    def _restablecer(self):
        """Restablecer todos a valores por defecto."""
        _DEFAULTS = {
            "google_calendar": True, "google_tasks": True, "google_gmail": True,
            "google_drive": True, "google_contacts": True, "google_maps": True,
            "mapa_interno": True, "nominatim_geo": True, "anillos_interfaz": False, "guardar_historial": True,
            "guardar_memoria_usuario": True, "notas_auto": True,
            "guardar_links_apps": True, "guardar_archivos_recientes": True,
            "registrar_tokens": True, "escucha_continua": True,
            "tts_activado": True, "usar_elevenlabs": True, "usar_tts_gratis": True,
            "usar_gemini_analisis": True, "usar_groq_comandos": True,
            "busqueda_web": True, "noticias_habilitadas": True, "clima_habilitado": True,
            "modo_power_inicio": False, "imagenes_auto": True,
            "abrir_links_navegador": True, "chat_qt_visible": False,
            "permiso_escaneo_apps": False, "permiso_microfono": False,
            "permiso_pantalla": False, "permiso_teclado": False,
        }
        for cb, key in self._chks:
            cb.setChecked(_DEFAULTS.get(key, True))


class VentanaComandos(QDialog):
    """Catálogo local de comandos, sin ejecutar acciones al abrirlo."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Jarvis — Comandos")
        self.setMinimumSize(560, 620)
        self.setStyleSheet(ESTILO_DIALOG)
        layout = QVBoxLayout(self)
        titulo = QLabel("⌘ Comandos de Jarvis"); titulo.setObjectName("titulo")
        layout.addWidget(titulo)
        sub = QLabel("Di una frase natural. Las acciones sensibles requieren el permiso correspondiente.")
        sub.setObjectName("sub"); sub.setWordWrap(True); layout.addWidget(sub)
        texto = QTextBrowser()
        texto.setOpenLinks(False)
        texto.setStyleSheet("QTextBrowser { background:rgba(4,10,22,0.9); border:1px solid rgba(77,184,255,0.25); border-radius:10px; padding:12px; }")
        texto.setHtml("""
        <h3>Aplicaciones y archivos</h3>
        <p>• Abre Chrome / abre Spotify / cierra Discord<br>• Busca el archivo presupuesto 2026</p>
        <h3>Pantalla</h3>
        <p>• Ver pantalla / analiza mi pantalla<br>• Haz clic en [objetivo] / escribe [texto]<br>• Sube la pantalla / baja la pantalla / haz zoom</p>
        <h3>Voz</h3>
        <p>• Jarvis, escucha / detén la escucha<br>• Lee esta respuesta / responde por texto</p>
        <h3>Productividad</h3>
        <p>• Crea una nota / recuérdame [tarea]<br>• Muéstrame mi agenda / crea un evento</p>
        <h3>Web y mapas</h3>
        <p>• Busca [tema] / muestra el mapa de [lugar]<br>• Busca imágenes de [tema]</p>
        """)
        layout.addWidget(texto)
        cerrar = QPushButton("Cerrar"); cerrar.setObjectName("cerrar"); cerrar.clicked.connect(self.accept)
        layout.addWidget(cerrar)


_EXTENSION_LOGOS = {
    "google_calendar": "googlecalendar",
    "google_tasks": "googletasks",
    "google_gmail": "gmail",
    "google_drive": "googledrive",
    "google_contacts": "google",
    "google_maps": "googlemaps",
    "busqueda_web": "google",
    "imagenes_auto": "googlephotos",
    "permiso_pantalla": "windows11",
}


def _estado_extension(clave: str) -> tuple[bool, str]:
    """Distingue permiso activado de conexión OAuth realmente disponible."""
    if not config.get(clave, False):
        return False, "Desconectada"
    scopes_por_extension = {
        "google_calendar": "https://www.googleapis.com/auth/calendar",
        "google_tasks": "https://www.googleapis.com/auth/tasks",
        "google_gmail": "https://mail.google.com/",
        "google_drive": "https://www.googleapis.com/auth/drive",
        "google_contacts": "https://www.googleapis.com/auth/contacts",
    }
    scope_requerido = scopes_por_extension.get(clave)
    if scope_requerido:
        try:
            token_file = os.path.join(data_path, "token.json")
            with open(token_file, "r", encoding="utf-8") as archivo:
                token_data = json.load(archivo)
            scopes = set(token_data.get("scopes", []))
            if not token_data.get("refresh_token") or scope_requerido not in scopes:
                return False, "Desconectada"
        except (OSError, ValueError, TypeError):
            return False, "Desconectada"
    return True, "Conectada"


def _logo_extension(clave: str, tamaño: int = 48) -> QPixmap:
    """Crea un icono de respaldo inmediato mientras llega el logo real."""
    pixmap = QPixmap(tamaño, tamaño)
    pixmap.fill(QColor("#24282e"))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QColor("#8fb8e0"))
    painter.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
    iniciales = {"google_gmail": "G", "google_calendar": "31", "google_tasks": "T", "google_drive": "D", "google_contacts": "C", "google_maps": "M", "busqueda_web": "G", "imagenes_auto": "I", "permiso_pantalla": "S"}
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, iniciales.get(clave, "J"))
    painter.end()
    return pixmap


class _LogoBridge(QObject):
    logo_ready = Signal(str, bytes)


_logo_bridge = _LogoBridge()


def _cargar_logo_async(clave: str, etiqueta: QLabel) -> None:
    """Descarga el SVG fuera del hilo UI y actualiza la etiqueta al terminar."""
    slug = _EXTENSION_LOGOS.get(clave, "link")

    def trabajo():
        try:
            respuesta = requests.get(f"https://cdn.simpleicons.org/{slug}", timeout=3)
            if respuesta.ok and respuesta.content:
                _logo_bridge.logo_ready.emit(clave, respuesta.content)
        except Exception:
            pass

    def aplicar(clave_recibida: str, contenido: bytes):
        if clave_recibida != clave:
            return
        try:
            renderer = QSvgRenderer(contenido)
            pixmap = QPixmap(48, 48)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            renderer.render(painter)
            painter.end()
            etiqueta.setPixmap(pixmap)
        except Exception:
            pass

    _logo_bridge.logo_ready.connect(aplicar)
    threading.Thread(target=trabajo, daemon=True, name=f"Logo-{clave}").start()


class VentanaExtensiones(QDialog):
    """Conexiones independientes; cada integración se puede apagar."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Jarvis — Extensiones")
        self.setMinimumSize(760, 620)
        self.setStyleSheet(ESTILO_DIALOG)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)
        titulo = QLabel("🔌 Extensiones"); titulo.setObjectName("titulo")
        layout.addWidget(titulo)
        sub = QLabel("Conecta cada servicio por separado. Jarvis solo usará las extensiones que estén activas.")
        sub.setObjectName("sub"); sub.setWordWrap(True); layout.addWidget(sub)
        conexiones = [
            ("Google Calendar", "Eventos y reuniones", "google_calendar"),
            ("Google Tasks", "Tareas pendientes", "google_tasks"),
            ("Gmail", "Consultar y gestionar correo", "google_gmail"),
            ("Google Drive", "Buscar y abrir archivos", "google_drive"),
            ("Google Contacts", "Buscar contactos", "google_contacts"),
            ("Google Maps", "Buscar lugares y rutas", "google_maps"),
            ("Búsqueda web", "Noticias, clima y consultas", "busqueda_web"),
            ("Imágenes", "Buscar imágenes", "imagenes_auto"),
            ("Pantalla", "Observar o controlar el escritorio", "permiso_pantalla"),
        ]
        self._chks = []
        grid = QGridLayout()
        grid.setHorizontalSpacing(10); grid.setVerticalSpacing(10)
        for indice, (nombre, detalle, clave) in enumerate(conexiones):
            tarjeta = QFrame()
            tarjeta.setObjectName("extensionCard")
            tarjeta.setStyleSheet(
                "QFrame#extensionCard { background: #17191d; border: 1px solid #30343a; border-radius: 10px; }"
                "QLabel#extensionIcon { background: #24282e; border: 1px solid #3d434c; border-radius: 8px; font-size: 24px; }"
                "QLabel#extensionName { color: #f1f3f5; font-size: 14px; font-weight: 600; }"
                "QLabel#extensionDetail { color: #9da5ae; font-size: 11px; }"
                "QLabel#extensionState { background: transparent; border: none; }"
                "QPushButton { background: #2a2e33; color: #d9dde2; border: none; border-radius: 6px; padding: 7px 12px; font-size: 11px; }"
                "QPushButton:hover { background: #3b424a; }"
            )
            card_layout = QHBoxLayout(tarjeta)
            card_layout.setContentsMargins(12, 12, 12, 12); card_layout.setSpacing(10)
            icon = QLabel(); icon.setObjectName("extensionIcon"); icon.setAlignment(Qt.AlignmentFlag.AlignCenter); icon.setFixedSize(48, 48)
            icon.setPixmap(_logo_extension(clave))
            _cargar_logo_async(clave, icon)
            info = QVBoxLayout(); info.setSpacing(3)
            name_label = QLabel(nombre); name_label.setObjectName("extensionName")
            detail_label = QLabel(detalle); detail_label.setObjectName("extensionDetail"); detail_label.setWordWrap(True)
            info.addWidget(name_label); info.addWidget(detail_label); info.addStretch()
            estado = QLabel(); estado.setObjectName("extensionState"); estado.setAlignment(Qt.AlignmentFlag.AlignCenter); estado.setFixedWidth(88)
            estado.setProperty("clave", clave)
            conectado, texto_estado = _estado_extension(clave)
            estado.setText(texto_estado)
            estado.setStyleSheet("color:#69d27a;font-size:11px;font-weight:600;" if conectado else "color:#8b929a;font-size:11px;font-weight:600;")
            interruptor = Interruptor(); interruptor.setProperty("clave", clave); interruptor.setChecked(bool(config.get(clave, False)))
            interruptor.toggled.connect(lambda activo, boton=interruptor, etiqueta=estado: self._alternar_extension(boton, etiqueta))
            card_layout.addWidget(icon); card_layout.addLayout(info, 1); card_layout.addWidget(estado); card_layout.addWidget(interruptor)
            grid.addWidget(tarjeta, indice // 2, indice % 2)
            self._chks.append((estado, clave))
        layout.addLayout(grid)
        nota = QLabel("Las conexiones de Google requieren autorización OAuth la primera vez que se usan.")
        nota.setStyleSheet("color:#6f7882;font-size:11px;padding-top:6px;"); nota.setWordWrap(True); layout.addWidget(nota)
        layout.addStretch()
        botones = QHBoxLayout()
        cerrar = QPushButton("Cancelar"); cerrar.setObjectName("cerrar"); cerrar.clicked.connect(self.reject)
        guardar = QPushButton("Guardar conexiones"); guardar.setObjectName("guardar"); guardar.clicked.connect(self._guardar)
        botones.addWidget(cerrar); botones.addWidget(guardar); layout.addLayout(botones)

    def _alternar_extension(self, boton, etiqueta):
        clave = boton.property("clave")
        config[clave] = boton.isChecked()
        conectado, texto_estado = _estado_extension(clave)
        etiqueta.setText(texto_estado)
        etiqueta.setStyleSheet("color:#69d27a;font-size:11px;font-weight:600;" if conectado else "color:#8b929a;font-size:11px;font-weight:600;")

    def _guardar(self):
        guardar_config(config)
        self.accept()


class ChatCompleto(QDialog):
    """Ventana de chat completo con historial scrollable."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("J.A.R.V.I.S. — Chat")
        self.setMinimumSize(700, 500)
        self.setStyleSheet(ESTILO_DIALOG)
        self._bloques: list = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        self.chat = QTextBrowser()
        self.chat.setOpenLinks(False)
        self.chat.setStyleSheet(
            "QTextBrowser { background: rgba(4,10,22,0.95); "
            "border: 1px solid rgba(77,184,255,0.25); border-radius: 10px; "
            "color: #dde6f5; font-size: 13px; padding: 8px; }"
        )
        layout.addWidget(self.chat)

        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Escribe un mensaje...")
        self.input.returnPressed.connect(self._enviar)
        self.input.setStyleSheet(
            "QLineEdit { background: rgba(10,20,40,0.9); color: #dde6f5; "
            "border: 1.5px solid rgba(77,184,255,0.3); border-radius: 10px; "
            "padding: 10px 14px; font-size: 13px; }"
            "QLineEdit:focus { border: 1.5px solid transparent; outline: none; }"
        )
        btn = QPushButton("➤"); btn.setFixedSize(42, 42)
        btn.clicked.connect(self._enviar)
        row.addWidget(self.input); row.addWidget(btn)
        layout.addLayout(row)

        # Conectar señales del bridge a este chat
        _bridge.append_html.connect(self._agregar_html)
        _bridge.scroll_down.connect(self._scroll)

    def _agregar_html(self, html: str):
        self._bloques.append(html)
        if len(self._bloques) > 80:
            self._bloques = self._bloques[-80:]
        doc = (
            '<html><body style="background:transparent;color:#dde6f5;'
            'font-family:Segoe UI,sans-serif;font-size:13px;margin:0;padding:6px;">'
            + "".join(self._bloques[-40:])
            + '</body></html>'
        )
        self.chat.setHtml(doc)

    def _scroll(self):
        sb = self.chat.verticalScrollBar()
        QTimer.singleShot(60,  lambda: sb.setValue(sb.maximum()))
        QTimer.singleShot(250, lambda: sb.setValue(sb.maximum()))

    def _enviar(self):
        texto = self.input.text().strip()
        if texto:
            self.input.clear()
            threading.Thread(
                target=interpretar_multiple, args=(texto, None, False), daemon=True
            ).start()


class JarvisUI(QWidget):
    """UI principal con canvas JARVIS V5 — sin sidebar, pantalla completa."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("J.A.R.V.I.S.")
        self.setWindowFlags(Qt.WindowType.Window)
        self._bloques: list = []
        self._chat_visible = False

        # Cargar HTML desde archivo V5.html (usar carga por URL local para evitar renderizado como texto)
        v5_html_path = os.path.join(base_path, "V5.html")
        try:
            if not os.path.exists(v5_html_path):
                raise FileNotFoundError(v5_html_path)
        except Exception as e:
            print(f"[UI] Error: V5.html no encontrado: {e}")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── WebView V5 — ocupa toda la pantalla ──────────────────────────────
        self._webview = QWebEngineView()
        self._webview.setPage(JarvisWebPage(self._webview))
        self._webview.settings().setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
        self._webview.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        # Deshabilitar caché para asegurar que siempre carga la versión más reciente
        self._webview.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, False)
        # Habilitar herramientas de desarrollo para poder inspeccionar la consola si es necesario
        try:
            self._webview.settings().setAttribute(QWebEngineSettings.WebAttribute.DeveloperExtrasEnabled, True)
        except Exception:
            pass
        # Registrar evento de carga para detectar fallos y volcar contenido si falla
        def _on_v5_load(ok: bool):
            global _v5_ready
            print(f"[UI] V5.html loadFinished: {ok}")
            if ok:
                _v5_ready = True
                QTimer.singleShot(250, _vaciar_pendientes_v5)
            else:
                print(f"[UI] V5.html loadFinished false, keeping _v5_ready={_v5_ready}")
                try:
                    def _dump(html: str):
                        snippet = html[:800].replace('\n', '\\n')
                        print(f"[UI] V5.html content snippet: {snippet}")
                    self._webview.page().toHtml(_dump)
                except Exception as e:
                    print(f"[UI] toHtml error: {e}")

        self._webview.loadFinished.connect(_on_v5_load)
        try:
            self._webview.page().javaScriptConsoleMessage.connect(
                lambda level, msg, line, source: print(f"[V5 console][{level}] {msg} @ {source}:{line}")
            )
        except Exception:
            pass
        self._webview.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)

        # Iniciar servidor HTTP local para evitar CORS issues
        global _http_server
        try:
            print(f"[UI] Inicializando servidor HTTP en puerto 9999...")
            print(f"[UI] Base path: {base_path}")
            print(f"[UI] V5.html path: {v5_html_path}")

            _http_server = LocalHTTPServer(port=9999)
            if _http_server.start():
                print("[UI] ✓ Servidor HTTP iniciado correctamente")
                # Pequeña pausa para asegurar que el servidor está listo
                import time as _time
                _time.sleep(1)

                # Intentar cargar V5.html desde el servidor HTTP con query de versión para evitar caché
                url = QUrl(f"http://127.0.0.1:9999/V5.html?v={int(time.time())}")
                print(f"[UI] Cargando URL en WebView: {url.toString()}")
                print(f"[UI] WebView settings: JavaScriptEnabled={self._webview.settings().testAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled)}, WebGLEnabled={self._webview.settings().testAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled)}")

                self._webview.load(url)
                print("[UI] ✓ load() completado, esperando loadFinished signal...")

            else:
                print("[UI] ✗ Servidor HTTP no pudo iniciar")
                raise Exception("HTTP Server failed to start")

        except Exception as e:
            print(f"[UI] ✗ Error con servidor HTTP: {e}")
            import traceback
            traceback.print_exc()

            # Fallback a file://
            print("[UI] Usando fallback file:// protocol")
            try:
                file_url = QUrl.fromLocalFile(os.path.abspath(v5_html_path))
                file_url.setQuery(f"v={int(time.time())}")
                print(f"[UI] Cargando: {file_url.toString()}")
                self._webview.load(file_url)
            except Exception as e2:
                print(f"[UI] ✗ Error crítico cargando V5.html: {e2}")
                import traceback
                traceback.print_exc()

        # Guardar referencia global para inyectar JS desde agentes
        global _webview_ref
        _webview_ref = self._webview

        root.addWidget(self._webview, stretch=1)

        # ── Panel de chat Qt (oculto por defecto, se muestra con F12) ────────
        self._chat_panel = QWidget()
        self._chat_panel.setFixedHeight(240)
        self._chat_panel.setVisible(False)
        self._chat_panel.setStyleSheet(
            "QWidget { background: rgba(0,6,14,0.97);"
            "border-top: 1px solid rgba(0,212,255,0.3); }"
        )
        chat_layout = QVBoxLayout(self._chat_panel)
        chat_layout.setContentsMargins(10, 6, 10, 8)
        chat_layout.setSpacing(6)

        self._chat_view = QTextBrowser()
        self._chat_view.setOpenLinks(False)
        self._chat_view.document().setDefaultStyleSheet(
            "body { background: transparent; color: #dde6f5; "
            "font-family: Segoe UI, sans-serif; font-size: 13px; margin: 0; padding: 4px; }"
        )
        self._chat_view.setStyleSheet(
            "QTextBrowser { background: transparent; border: none; color: #dde6f5; font-size: 13px; }"
        )
        chat_layout.addWidget(self._chat_view)
        self._chat_view.anchorClicked.connect(self._link_clickeado)

        input_row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText("Escribe un mensaje o usa el micrófono...")
        self._input.setStyleSheet(
            "QLineEdit { background:rgba(0,10,25,0.95);color:#dde6f5;"
            "border:1.5px solid rgba(0,212,255,0.35);border-radius:10px;"
            "padding:9px 14px;font-size:13px; }"
            "QLineEdit:focus { border:1.5px solid transparent; outline: none; }"
        )
        self._input.returnPressed.connect(self._enviar)
        btn_send = QPushButton("➤")
        btn_send.setFixedSize(42, 42)
        btn_send.setStyleSheet(
            "QPushButton { background:rgba(0,40,80,0.85);color:#00d4ff;"
            "border:1px solid rgba(0,212,255,0.4);border-radius:10px;font-size:16px; }"
            "QPushButton:hover { background:rgba(0,80,160,0.9);color:white; }"
        )
        btn_send.clicked.connect(self._enviar)
        input_row.addWidget(self._input)
        input_row.addWidget(btn_send)
        chat_layout.addLayout(input_row)

        root.addWidget(self._chat_panel)

        # ── Conectar bridge ───────────────────────────────────────────────────
        _bridge.append_html.connect(self._agregar_html)
        _bridge.append_to_v5_chat.connect(_ejecutar_js_v5)
        _bridge.append_to_v5_map.connect(_ejecutar_js_mapa_v5)
        _bridge.scroll_down.connect(self._scroll)
        _bridge.quit_app.connect(self.close)
        _bridge.open_config_dialog.connect(self._abrir_cfg)
        _bridge.open_commands_dialog.connect(self._abrir_comandos)
        _bridge.open_extensions_dialog.connect(self._abrir_extensiones)

    # ── Slots del chat ────────────────────────────────────────────────────────

    def _toggle_chat(self):
        self._chat_visible = not self._chat_visible
        self._chat_panel.setVisible(self._chat_visible)

    def _agregar_html(self, html: str):
        """Inserta HTML de forma incremental — no reconstruye el documento completo."""
        try:
            # Debug: log when a Jarvis (assistant) message arrives to this Qt chat
            if '◈ JARVIS' in html or 'JARVIS' in html and '<div' in html:
                print(f"[UI Debug] Jarvis HTML received in _agregar_html: {html[:120].replace('\n','')}...")
        except Exception:
            pass
        try:
            self._bloques.append(html)
            if len(self._bloques) > 120:
                self._bloques = self._bloques[-120:]
            from PySide6.QtGui import QTextCursor
            self._chat_view.append(html)
            self._chat_view.moveCursor(QTextCursor.MoveOperation.End)
            sb = self._chat_view.verticalScrollBar()
            QTimer.singleShot(50, lambda: sb.setValue(sb.maximum()))
        except Exception as exc:
            print(f"[UI Debug] _agregar_html failed: {exc}")

    def _scroll(self):
        self._chat_view.moveCursor(
            __import__('PySide6.QtGui', fromlist=['QTextCursor']).QTextCursor.MoveOperation.End
        )
        sb = self._chat_view.verticalScrollBar()
        QTimer.singleShot(50, lambda: sb.setValue(sb.maximum()))

    def _enviar(self):
        texto = self._input.text().strip()
        if texto:
            self._input.clear()
            # Insertar mensaje del usuario directamente (sin animación de escritura)
            from PySide6.QtGui import QTextCursor
            cursor = self._chat_view.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.insertHtml(
                f'<div style="background:rgba(20,50,100,0.70);border-radius:12px;'
                f'padding:8px 14px;margin:6px 2px;border-right:3px solid #00d4ff;text-align:right;">'
                f'<span style="color:#8fb8e0;font-size:11px;">Tú</span><br>'
                f'<span style="color:#dde6f5;">{texto}</span></div>'
            )
            self._chat_view.setTextCursor(cursor)
            sb = self._chat_view.verticalScrollBar()
            QTimer.singleShot(30, lambda: sb.setValue(sb.maximum()))
            threading.Thread(
                target=interpretar_multiple, args=(texto, None, False), daemon=True
            ).start()

    def _animar_escritura_usuario(self, texto: str):
        """Inserta el texto del usuario en el chat letra por letra."""
        from PySide6.QtGui import QTextCursor

        # Insertar cabecera del bloque usuario
        c = self._chat_view.textCursor()
        c.movePosition(QTextCursor.MoveOperation.End)
        c.insertHtml(
            '<div style="background:rgba(20,50,100,0.70);border-radius:12px;'
            'padding:8px 14px;margin:6px 2px;border-right:3px solid #4db8ff;text-align:right;">'
            '<span style="color:#8fb8e0;font-size:11px;">Tú</span><br>'
        )
        self._chat_view.setTextCursor(c)

        idx = [0]

        def _tick():
            if idx[0] < len(texto):
                cur = self._chat_view.textCursor()
                cur.movePosition(QTextCursor.MoveOperation.End)
                cur.insertText(texto[idx[0]])
                self._chat_view.setTextCursor(cur)
                self._chat_view.verticalScrollBar().setValue(
                    self._chat_view.verticalScrollBar().maximum()
                )
                idx[0] += 1
                QTimer.singleShot(30, _tick)
            else:
                # Cerrar el div
                cur = self._chat_view.textCursor()
                cur.movePosition(QTextCursor.MoveOperation.End)
                cur.insertHtml('</div>')
                self._chat_view.setTextCursor(cur)
                self._chat_view.verticalScrollBar().setValue(
                    self._chat_view.verticalScrollBar().maximum()
                )

        QTimer.singleShot(10, _tick)

    def _escuchar(self):
        if _sd_audio_lock.locked() or _pausar_escucha_continua.is_set():
            hablar("El micrófono ya está en uso. Espera un momento.", None)
            return
        def _tarea():
            texto = escuchar_microfono(duracion=15.0)
            if texto:
                interpretar_multiple(texto, None)
            else:
                hablar("No escuché nada.", None)
        threading.Thread(target=_tarea, daemon=True).start()

    def _abrir_cfg(self):
        dlg = VentanaConfig(self)
        dlg.exec()

    def _abrir_comandos(self):
        VentanaComandos(self).exec()

    def _abrir_extensiones(self):
        VentanaExtensiones(self).exec()

    def _link_clickeado(self, url: QUrl):
        """Maneja clicks en links del chat: archivos, correos, URLs web, imgs."""
        import subprocess, os, webbrowser
        esquema = url.scheme().lower()
        ruta    = url.toString()

        if esquema == "img":
            # Vista previa de imagen
            img_url = ruta[4:]  # quitar "img:"
            visor = QDialog(self)
            visor.setWindowTitle("Vista previa")
            visor.resize(700, 520)
            visor.setStyleSheet("QDialog { background:#060d1a; }")
            lay = QVBoxLayout(visor)
            lbl = QLabel()
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
            manager = QNetworkAccessManager(visor)
            def _on_img(reply):
                data = reply.readAll()
                pix = __import__('PySide6.QtGui', fromlist=['QPixmap']).QPixmap()
                pix.loadFromData(data)
                lbl.setPixmap(pix.scaled(660, 480,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation))
            manager.finished.connect(_on_img)
            manager.get(QNetworkRequest(QUrl(img_url)))
            lay.addWidget(lbl)
            visor.exec()
            return

        if esquema in ("http", "https"):
            webbrowser.open(ruta)
            return

        if esquema == "file" or (esquema == "" and os.path.exists(ruta)):
            path = url.toLocalFile() if esquema == "file" else ruta
            try:
                os.startfile(path)
            except Exception:
                subprocess.Popen(['explorer', path])
            return

        if esquema == "open":
            # open:ruta_de_archivo — para archivos mostrados como clickeables
            path = ruta[5:]
            if os.path.exists(path):
                try:
                    os.startfile(path)
                except Exception:
                    subprocess.Popen(['explorer', path])
            return

        if esquema == "cmd":
            # cmd:texto_comando — reenviar texto al interprete de Jarvis
            comando = ruta[4:]
            threading.Thread(
                target=interpretar_multiple, args=(comando, None), daemon=True
            ).start()
            return

        # Fallback: abrir como URL
        QDesktopServices.openUrl(url)


# =============================================================================
# 16. MAIN
# =============================================================================
if __name__ == "__main__":
    # Flags para mantener animación WebGL activa en background
    flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
        f"{flags} --disable-renderer-backgrounding "
        "--disable-background-timer-throttling "
        "--disable-backgrounding-occluded-windows "
        "--disable-renderer-accessibility "
        "--disable-features=Throttle,ThrottleMainThread "
        "--run-all-compositor-stages-before-draw"
    ).strip()

    app = QApplication(sys.argv)

    # Preguntar modo de carga de apps si no está configurado
    modo_actual  = config.get("modo_carga_apps", None)
    cache_normal = os.path.join(data_path, "memoria_auto_normal.json")
    cache_power  = os.path.join(data_path, "memoria_auto_power.json")
    cache_existe = os.path.exists(cache_normal) or os.path.exists(cache_power)

    if modo_actual not in ("normal", "power") or not cache_existe:
        dlg = VentanaModoArranque()
        dlg.exec()
        modo_actual = dlg.modo_elegido
        config["modo_carga_apps"] = modo_actual
        guardar_config(config)

    _solicitar_permisos_iniciales()

    # Inicializar agentes ANTES de la UI (MAPA_SISTEMA empieza vacío, se llena en background)
    _marcar_nueva_sesion()
    _inicializar_agentes()

    # Auto-iniciar modo gestos si se solicita via env o argumento
    try:
        auto_gestos = os.environ.get("JARVIS_AUTO_GESTOS", "0")
        if auto_gestos.lower() in ("1", "true", "yes") or "--gestos" in sys.argv:
            try:
                print("[Init] Auto-activando modo gestos (flag)")
                agent_screen.activar_modo_gestos()
            except Exception as _e:
                print(f"[Init] No pude activar modo gestos: {_e}")
        if "--calibrar-gestos" in sys.argv:
            try:
                print("[Init] Ejecutando calibración de gestos al inicio")
                agent_screen.calibrar_gestos(6)
            except Exception as _e:
                print(f"[Init] Calibración falló: {_e}")
    except Exception:
        pass

    # Borrar caché de apps siempre al arranque para que los fixes de rutas surtan efecto
    # (el escaneo tarda <5s en background, no bloquea la UI)
    for _cf in ["memoria_auto_normal.json", "memoria_auto_power.json"]:
        _cfp = os.path.join(data_path, _cf)
        if os.path.exists(_cfp):
            try:
                os.remove(_cfp)
                print(f"[Init] Caché de apps eliminado para regenerar: {_cf}")
            except Exception:
                pass

    # Escanear apps en background para no trabar la UI
    # IMPORTANTE: usar MAPA_SISTEMA.update() y NO re-asignar la variable,
    # porque agent_pc tiene una lambda capturando el objeto dict original.
    def _escanear_apps_background():
        print("🔍 Escaneando apps del sistema...")
        nuevo_mapa = obtener_apps_sistema(modo_actual, max_cache_age_hours=1)
        MAPA_SISTEMA.update(nuevo_mapa)
        print(f"✅ {len(MAPA_SISTEMA)} apps encontradas")
    threading.Thread(target=_escanear_apps_background, daemon=True, name="EscaneoApps").start()

    # ── ORDEN CRÍTICO: 1) KEYS → 2) WHISPER → 3) ESCUCHA ──
    # cargar_whisper() espera a _KEYS_LISTAS.wait(), así que las keys DEBEN cargarse primero
    print("[Init] 🔑 1️⃣ Iniciando carga de keys...")
    threading.Thread(target=_cargar_keys_background, daemon=True, name="CargarKeys").start()
    
    # Pequeño retraso para que las keys comiencen a cargar en background
    time.sleep(0.3) 

    # Cargar Whisper en background (esperará internamente a _KEYS_LISTAS)
    print("[Init] 🎤 2️⃣ Preparando Whisper (esperará a keys)...")
    threading.Thread(target=cargar_whisper, daemon=True, name="CargarWhisper").start()

    # Lanzar escucha continua con wake word (con retraso para que cargue Whisper)
    def _lanzar_escucha():
        time.sleep(5)  # 5 segundos de espera para que Whisper cargue
        if not config.get("escucha_continua", True) or not _permiso_concedido("microfono"):
            print("[Init] 👂 Escucha continua desactivada en config")
            return
        print("[Init] 👂 3️⃣ Iniciando escucha continua...")
        _hilo_siempre_escuchando()
    threading.Thread(target=_lanzar_escucha, daemon=True, name="EscuchaContinua").start()

    # UI
    ui = JarvisUI()
    ui.showFullScreen()
    _screen_overlay = PantallaOverlay(ui)
    _bridge.show_screen_overlay.connect(_screen_overlay.iniciar_stream)
    _bridge.analyze_screen.connect(
        lambda pregunta: QTimer.singleShot(
            900,
            lambda: _analizar_pantalla_con_vision(None, pregunta),
        )
    )

    # Saludo inicial
    hora   = datetime.now().hour
    saludo = "Buenos días" if hora < 12 else "Buenas tardes" if hora < 18 else "Buenas noches"
    nombre = memoria_usuario.get("nombre")
    _n     = f", {nombre}" if nombre else ""
    _SALUDOS = [
        "Hola, soy Jarvis. ¿En qué puedo ayudarte?",
        "Bienvenido. ¿Qué quieres que haga ahora?",
        "Estoy listo. Dime qué necesitas.",
    ]
    def _saludo():
        time.sleep(0.8)
        if _SALUDOS:
            hablar(random.choice(_SALUDOS), None)
    threading.Thread(target=_saludo, daemon=True).start()

    sys.exit(app.exec())
