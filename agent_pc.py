# =============================================================================
# agent_pc.py — Agente de Control del PC
# =============================================================================
# Responsabilidades:
#   · Abrir, cerrar, minimizar, maximizar aplicaciones
#   · Control de volumen (absoluto y relativo) con pycaw + fallback por teclas
#   · Control de brillo (WMI)
#   · Apagar, reiniciar, bloquear el PC
#   · Activar modos de trabajo (gaming, estudio, programación...)
#   · Búsqueda de archivos y carpetas en disco
#   · Memoria de apps aprendidas y archivos recientes
#   · Escaneo del sistema (Start Menu, Steam, Epic Games, Store)
#
# Interfaz pública:
#   init(ctx)                                              → inyectar contexto
#   ejecutar(accion, params, chat_widget) -> bool          → punto de entrada
#
# Acciones del dispatcher:
#   "abrir"          → params: {nombre}
#   "cerrar"         → params: {nombre}
#   "minimizar"      → params: {nombre}
#   "maximizar"      → params: {nombre}
#   "poner_volumen"  → params: {porcentaje}
#   "subir_volumen"  → params: {porcentaje?}
#   "bajar_volumen"  → params: {porcentaje?}
#   "mute"           → params: {}
#   "subir_brillo"   → params: {porcentaje?}
#   "bajar_brillo"   → params: {porcentaje?}
#   "apagar"         → params: {}
#   "reiniciar"      → params: {}
#   "bloquear"       → params: {}
#   "modo"           → params: {nombre}
#   "buscar_archivo" → params: {termino, carpeta?}
#   "aprender_app"   → params: {nombre, ruta}
#
# Dependencias inyectadas via init(ctx):
#   hablar, cola_voz, bridge, html_burbuja,
#   MAPA_SISTEMA, apps, archivos_memoria,
#   modos, config, base_path,
#   quitar_tildes, normalizar_nombre_app, _score_app_v9,
#   obtener_apps_sistema, ejecutar_app,
#   buscar_archivo_en_memoria,
#   EXTENSIONES_PERMITIDAS, CARPETAS_IGNORAR,
#   VK_VOLUME_MUTE, VK_VOLUME_DOWN, VK_VOLUME_UP
# =============================================================================

from __future__ import annotations

import ctypes
import os
import re
import time

import win32gui
import win32con

# =============================================================================
# CONTEXTO INYECTADO
# =============================================================================

_ctx: dict = {}


def init(ctx: dict):
    """
    Inyecta el contexto compartido desde Jarvis_main.py.
    Llamar UNA VEZ antes de usar cualquier función.

    Ejemplo:
        import agent_pc
        agent_pc.init({
            "hablar":               hablar,
            "cola_voz":             _cola_voz,
            "bridge":               _bridge,
            "html_burbuja":         _html_burbuja,
            "MAPA_SISTEMA":         lambda: MAPA_SISTEMA,
            "apps":                 apps,
            "archivos_memoria":     archivos_memoria,
            "modos":                modos,
            "config":               config,
            "base_path":            base_path,
            "quitar_tildes":        quitar_tildes,
            "normalizar_nombre_app": normalizar_nombre_app,
            "_score_app_v9":        _score_app_v9,
            "obtener_apps_sistema": obtener_apps_sistema,
            "ejecutar_app":         ejecutar_app,
            "buscar_archivo_en_memoria": buscar_archivo_en_memoria,
            "EXTENSIONES_PERMITIDAS":  EXTENSIONES_PERMITIDAS,
            "CARPETAS_IGNORAR":        CARPETAS_IGNORAR,
            "VK_VOLUME_MUTE":      VK_VOLUME_MUTE,
            "VK_VOLUME_DOWN":      VK_VOLUME_DOWN,
            "VK_VOLUME_UP":        VK_VOLUME_UP,
        })
    """
    global _ctx
    _ctx = ctx


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

def _mapa_sistema():
    getter = _ctx.get("MAPA_SISTEMA")
    return getter() if callable(getter) else (getter or {})

def _apps():
    return _ctx.get("apps", {})

def _archivos_memoria():
    return _ctx.get("archivos_memoria", {})

def _modos():
    return _ctx.get("modos", {})

def _config():
    return _ctx.get("config", {})

def _base_path():
    return _ctx.get("base_path", os.getcwd())

def _quitar_tildes(texto):
    return _ctx["quitar_tildes"](texto)

def _score_app(nombre_usuario, nombre_app):
    return _ctx["_score_app_v9"](nombre_usuario, nombre_app)

def _ejecutar_app(nombre, ruta, chat_widget=None):
    return _ctx["ejecutar_app"](nombre, ruta, chat_widget)

def _buscar_archivo_en_memoria(termino):
    return _ctx["buscar_archivo_en_memoria"](termino)

def _obtener_apps_sistema(modo="normal"):
    return _ctx["obtener_apps_sistema"](modo)

def _extensiones_permitidas():
    return _ctx.get("EXTENSIONES_PERMITIDAS", {
        ".pdf", ".docx", ".xlsx", ".pptx", ".txt", ".csv",
        ".mp4", ".mp3", ".png", ".jpg", ".jpeg", ".wav"
    })

def _carpetas_ignorar():
    return _ctx.get("CARPETAS_IGNORAR", {"AppData", "Local", "Temp", "Windows"})

def _vk(nombre):
    return _ctx.get(nombre, 0)


# =============================================================================
# 1. VENTANAS
# =============================================================================

def _encontrar_ventana(nombre: str):
    """Busca un HWND por título exacto o parcial."""
    hwnd = win32gui.FindWindow(None, nombre)
    if hwnd == 0:
        hwnds = []
        def _enum(h, _):
            if nombre.lower() in win32gui.GetWindowText(h).lower():
                hwnds.append(h)
        win32gui.EnumWindows(_enum, None)
        return hwnds[0] if hwnds else None
    return hwnd


def minimizar_app(nombre: str, chat_widget=None):
    hwnd = _encontrar_ventana(nombre)
    if hwnd:
        win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
        _hablar(f"{nombre} minimizada", chat_widget)
    else:
        _hablar(f"No encontré la ventana de {nombre}", chat_widget)


def maximizar_app(nombre: str, chat_widget=None):
    hwnd = _encontrar_ventana(nombre)
    if hwnd:
        win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
        _hablar(f"{nombre} maximizada", chat_widget)
    else:
        _hablar(f"No encontré la ventana de {nombre}", chat_widget)


def cerrar_app(nombre: str, chat_widget=None):
    hwnd = _encontrar_ventana(nombre)
    if hwnd:
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        _hablar(f"{nombre} cerrada", chat_widget)
    else:
        _hablar(f"No encontré la ventana de {nombre}", chat_widget)


# =============================================================================
# 2. VOLUMEN
# =============================================================================

def _get_volume_interface():
    """Devuelve la interfaz de volumen de Windows (pycaw) o None si no disponible."""
    try:
        from ctypes import POINTER, cast
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        devices   = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return cast(interface, POINTER(IAudioEndpointVolume))
    except Exception:
        return None


def _get_volumen_actual() -> int:
    """Devuelve el volumen actual del sistema (0-100). -1 si no disponible."""
    vol = _get_volume_interface()
    if vol:
        try:
            return int(round(vol.GetMasterVolumeLevelScalar() * 100))
        except Exception:
            pass
    return -1


def poner_volumen(porcentaje: int, chat_widget=None):
    """Establece el volumen del sistema en un porcentaje absoluto (0-100)."""
    porcentaje = max(0, min(100, porcentaje))
    vol = _get_volume_interface()
    if vol:
        try:
            vol.SetMasterVolumeLevelScalar(porcentaje / 100.0, None)
            _hablar(f"Volumen al {porcentaje} por ciento", chat_widget)
            return
        except Exception:
            pass
    # Fallback: teclas de volumen — bajar al mínimo y luego subir
    VK_DOWN = _vk("VK_VOLUME_DOWN")
    VK_UP   = _vk("VK_VOLUME_UP")
    for _ in range(50):
        ctypes.windll.user32.keybd_event(VK_DOWN, 0, 0, 0)
        ctypes.windll.user32.keybd_event(VK_DOWN, 0, 2, 0)
    for _ in range(int(porcentaje // 2)):
        ctypes.windll.user32.keybd_event(VK_UP, 0, 0, 0)
        ctypes.windll.user32.keybd_event(VK_UP, 0, 2, 0)
    _hablar(f"Volumen al {porcentaje} por ciento", chat_widget)


def ajustar_volumen_relativo(porcentaje: int, chat_widget=None):
    """Sube o baja el volumen un porcentaje relativo al actual."""
    vol = _get_volume_interface()
    if vol:
        try:
            actual = vol.GetMasterVolumeLevelScalar()
            nuevo  = max(0.0, min(1.0, actual + porcentaje / 100.0))
            vol.SetMasterVolumeLevelScalar(nuevo, None)
            _hablar(f"Volumen al {int(round(nuevo * 100))} por ciento", chat_widget)
            return
        except Exception:
            pass
    # Fallback: teclas
    pasos = max(1, int(abs(porcentaje) // 2))
    tecla = _vk("VK_VOLUME_UP") if porcentaje > 0 else _vk("VK_VOLUME_DOWN")
    for _ in range(pasos):
        ctypes.windll.user32.keybd_event(tecla, 0, 0, 0)
        ctypes.windll.user32.keybd_event(tecla, 0, 2, 0)
    direccion = "subido" if porcentaje > 0 else "bajado"
    _hablar(f"Volumen {direccion} {abs(porcentaje)} por ciento", chat_widget)


def subir_volumen(porcentaje: int = 10, chat_widget=None):
    ajustar_volumen_relativo(porcentaje, chat_widget)


def bajar_volumen(porcentaje: int = 10, chat_widget=None):
    ajustar_volumen_relativo(-porcentaje, chat_widget)


def mute_volumen(chat_widget=None):
    ctypes.windll.user32.keybd_event(_vk("VK_VOLUME_MUTE"), 0, 0, 0)
    _hablar("Volumen silenciado o activado", chat_widget)


# =============================================================================
# 3. BRILLO
# =============================================================================

_wmi_obj = None


def _get_wmi():
    global _wmi_obj
    if _wmi_obj is None:
        try:
            import wmi as _wmi_mod
            _wmi_obj = _wmi_mod.WMI(namespace='wmi')
        except Exception:
            _wmi_obj = False
    return _wmi_obj if _wmi_obj else None


def get_brightness() -> int:
    w = _get_wmi()
    if not w:
        return 50
    try:
        for b in w.WmiMonitorBrightness():
            return b.CurrentBrightness
    except Exception:
        pass
    return 50


def set_brightness(valor: int, chat_widget=None):
    w = _get_wmi()
    if not w:
        _hablar("Control de brillo no disponible en este equipo.", chat_widget)
        return
    valor = max(0, min(100, valor))
    try:
        for b in w.WmiMonitorBrightnessMethods():
            b.WmiSetBrightness(valor, 0)
        _hablar(f"Brillo ajustado a {valor} por ciento", chat_widget)
    except Exception as e:
        _hablar(f"No pude ajustar el brillo: {e}", chat_widget)


def ajustar_brillo_relativo(porcentaje: int, chat_widget=None):
    set_brightness(get_brightness() + porcentaje, chat_widget)


def subir_brillo(porcentaje: int = 10, chat_widget=None):
    ajustar_brillo_relativo(porcentaje, chat_widget)


def bajar_brillo(porcentaje: int = 10, chat_widget=None):
    ajustar_brillo_relativo(-porcentaje, chat_widget)


# =============================================================================
# 4. ENCENDIDO / ENERGÍA
# =============================================================================

def apagar_pc(chat_widget=None):
    _hablar("Apagando el sistema en un momento.", chat_widget)
    import subprocess
    subprocess.Popen("shutdown /s /t 3", shell=True)

def reiniciar_pc(chat_widget=None):
    _hablar("Reiniciando el sistema.", chat_widget)
    import subprocess
    subprocess.Popen("shutdown /r /t 3", shell=True)

def bloquear_pc(chat_widget=None):
    _hablar("Bloqueando el equipo.", chat_widget)
    import subprocess
    subprocess.Popen("rundll32.exe user32.dll,LockWorkStation", shell=True)

def suspender_pc(chat_widget=None):
    _hablar("Suspendiendo el equipo.", chat_widget)
    import subprocess
    subprocess.Popen("rundll32.exe powrprof.dll,SetSuspendState 0,1,0", shell=True)

def hibernar_pc(chat_widget=None):
    _hablar("Hibernando el equipo.", chat_widget)
    import subprocess
    subprocess.Popen("shutdown /h", shell=True)


# =============================================================================
# 5. ABRIR APLICACIONES
# =============================================================================

# Estado interno para flujo de confirmación app vs web
_estado_abrir_destino: dict | None = None
_archivo_office_pendiente: str | None = None

OFFICE_EXTENSIONES = {".docx", ".xlsx", ".pptx"}


def abrir_app(nombre_usuario: str, chat_widget=None, pedir_confirmacion: bool = True):
    """
    Abre una app o archivo buscando en memoria de apps, MAPA_SISTEMA y archivos.
    Mismo algoritmo que Jarvis_v17 extraído como función pura.
    """
    global _estado_abrir_destino, _archivo_office_pendiente

    nombre_usuario = nombre_usuario.lower().strip()
    print(f"[agent_pc] Buscando app: {nombre_usuario}")
    apps           = _apps()
    mapa           = _mapa_sistema()
    archivos       = _archivos_memoria()
    config         = _config()
    print(f"[agent_pc] Apps en memoria: {len(apps)}, Mapa sistema: {len(mapa)}")

    # ── 1. Buscar en archivos aprendidos primero ─────────────────────────────
    if archivos:
        res = _buscar_archivo_en_memoria(nombre_usuario)
        if res:
            if isinstance(res, tuple):
                ruta_arch, etiq_arch = res
            else:
                ruta_arch, etiq_arch = res, os.path.basename(str(res))
            if os.path.exists(ruta_arch):
                ext = os.path.splitext(ruta_arch)[1].lower()
                if ext in OFFICE_EXTENSIONES:
                    _hablar(f"Encontré {os.path.basename(ruta_arch)}. ¿En la app o en la web?", chat_widget)
                    _archivo_office_pendiente = ruta_arch
                else:
                    _hablar(f"Abriendo {etiq_arch}", chat_widget)
                    os.startfile(ruta_arch)
                return

    def normalizar_ruta(ruta):
        return str(ruta).split("|")[0].strip() if ruta else ""

    def construir_candidatos():
        by_label = {}
        for fuente in (apps, mapa):
            for key, ruta in fuente.items():
                r    = normalizar_ruta(ruta)
                if not r:
                    continue
                tipo  = "web" if r.startswith(("http://", "https://")) else "app"
                label = f"{key}::{tipo}"
                by_label[label] = {"label": label, "nombre": key, "ruta": r, "tipo": tipo}
        return by_label

    by_label = construir_candidatos()
    if not by_label:
        print(f"[agent_pc] Sin apps en memoria")
        _hablar("No tengo apps en memoria todavía.", chat_widget)
        return

    explicit_web = any(x in nombre_usuario for x in ["web", "navegador", "online", "tienda", "store"])
    explicit_app = any(x in nombre_usuario for x in ["app", "aplicacion", "aplicación", "launcher", "local"])

    def rankear():
        scored = []
        for label, data in by_label.items():
            score = _score_app(nombre_usuario, data["nombre"])
            if data["tipo"] == "app":
                score += 3
            if explicit_web and data["tipo"] == "web":
                score += 8
            if explicit_app and data["tipo"] == "app":
                score += 8
            scored.append((label, min(100, score)))
        return sorted(scored, key=lambda t: t[1], reverse=True)[:30]

    top = rankear()
    print(f"[agent_pc] Top matches: {[(t[0].split('::')[0], t[1]) for t in top[:3]]}")

    # ── 2. Re-escanear si la mejor coincidencia es baja ──────────────────────
    if top and top[0][1] < 65:
        mapa_actual = _mapa_sistema()
        # Si el mapa está vacío, el escaneo de background aún no terminó — esperar
        if len(mapa_actual) < 10:
            _hablar("Cargando apps del sistema, un momento...", chat_widget)
            for _ in range(30):  # esperar hasta 15 segundos
                time.sleep(0.5)
                if len(_mapa_sistema()) >= 10:
                    break
            by_label = construir_candidatos()
            top      = rankear() if by_label else []
        else:
            for f in ["memoria_auto_normal.json", "memoria_auto_power.json"]:
                try:
                    fp = os.path.join(_base_path(), f)
                    if os.path.exists(fp):
                        os.remove(fp)
                except Exception:
                    pass
            _hablar("Buscando en el sistema...", chat_widget)
            nuevo_mapa = _obtener_apps_sistema(config.get("modo_carga_apps", "normal"))
            # Actualizar el mapa (puede ser dict directo o accedido via lambda)
            mapa_ref = _ctx.get("MAPA_SISTEMA")
            if callable(mapa_ref):
                mr = mapa_ref()
                if isinstance(mr, dict):
                    mr.clear(); mr.update(nuevo_mapa)
            elif isinstance(mapa_ref, dict):
                mapa_ref.clear(); mapa_ref.update(nuevo_mapa)
            by_label = construir_candidatos()
            top      = rankear() if by_label else []

    # ── 3. Seleccionar mejor app y mejor web ─────────────────────────────────
    best_app = best_web = None
    for label, score in (top or []):
        data = by_label.get(label)
        if not data:
            continue
        if data["tipo"] == "app":
            if best_app is None or score > best_app["score"]:
                best_app = {"data": data, "score": score}
        else:
            if best_web is None or score > best_web["score"]:
                best_web = {"data": data, "score": score}

    if best_app is None and best_web is None:
        _hablar(f"No encontré ninguna app parecida a {nombre_usuario}.", chat_widget)
        return

    query_words = [w for w in re.sub(r"[^a-z0-9áéíóúñü\s]", " ", nombre_usuario).split() if len(w) > 2]
    # Umbral más flexible para detectar apps: 60 en lugar de 70
    min_seguro = 60

    if explicit_web and best_web and best_web["score"] >= min_seguro:
        _ejecutar_app(best_web["data"]["nombre"], best_web["data"]["ruta"], chat_widget)
        return
    if explicit_app and best_app and best_app["score"] >= min_seguro:
        _ejecutar_app(best_app["data"]["nombre"], best_app["data"]["ruta"], chat_widget)
        return

    if (pedir_confirmacion and best_app and best_web
            and best_app["score"] >= min_seguro and best_web["score"] >= min_seguro):
        _estado_abrir_destino = {"app": best_app["data"], "web": best_web["data"]}
        _hablar(
            f"Tengo '{best_app['data']['nombre']}' como app y '{best_web['data']['nombre']}' como web. "
            f"¿En cuál lo abro: app o web?",
            chat_widget,
        )
        return

    elegido = (
        best_app
        if (best_app and (best_web is None or best_app["score"] >= best_web["score"]))
        else best_web
    )
    print(f"[agent_pc] Elegido: {elegido['data']['nombre'] if elegido else 'None'} (score={elegido['score'] if elegido else 'N/A'})")
    if elegido and len(query_words) >= 2 and elegido["score"] < min_seguro:
        print(f"[agent_pc] Score bajo ({elegido['score']}) con {len(query_words)} palabras — Google search")
        import webbrowser as _wb
        from urllib.parse import quote as _q
        _hablar(f"No encontré {nombre_usuario} instalado. Buscando en Google.", chat_widget)
        _wb.open(f"https://www.google.com/search?q={_q(nombre_usuario + ' página oficial')}")
        return
    if elegido and elegido["score"] >= min_seguro:
        print(f"[agent_pc] Ejecutando: {elegido['data']['nombre']} (score={elegido['score']})")
        _ejecutar_app(elegido["data"]["nombre"], elegido["data"]["ruta"], chat_widget)
        return

    print(f"[agent_pc] No hay app elegida para {nombre_usuario}")
    # Fallback final: Google con "página oficial"
    import webbrowser as _wb
    from urllib.parse import quote as _q
    _hablar(f"No encontré {nombre_usuario} instalado. Buscando en Google.", chat_widget)
    _wb.open(f"https://www.google.com/search?q={_q(nombre_usuario + ' página oficial')}")


def resolver_destino_pendiente(respuesta: str, chat_widget=None) -> bool:
    """
    Resuelve la confirmación de 'app vs web' cuando está pendiente.
    Devuelve True si había algo pendiente y se resolvió.
    """
    global _estado_abrir_destino
    if not _estado_abrir_destino:
        return False
    resp = respuesta.lower()
    if any(x in resp for x in ["app", "aplicacion", "aplicación", "launcher", "local"]):
        data = _estado_abrir_destino.get("app")
        _estado_abrir_destino = None
        if data:
            _ejecutar_app(data["nombre"], data["ruta"], chat_widget)
    elif any(x in resp for x in ["web", "navegador", "online", "tienda", "store"]):
        data = _estado_abrir_destino.get("web")
        _estado_abrir_destino = None
        if data:
            _ejecutar_app(data["nombre"], data["ruta"], chat_widget)
    else:
        _hablar("Dime si quieres abrirlo en la app o en la web.", chat_widget)
    return True


def hay_destino_pendiente() -> bool:
    return _estado_abrir_destino is not None


# =============================================================================
# 6. MODOS DE TRABAJO
# =============================================================================

def activar_modo(nombre_modo: str, chat_widget=None):
    """Activa un modo predefinido (abre varias apps a la vez)."""
    nombre_modo = nombre_modo.lower().strip()
    modos       = _modos()
    if nombre_modo not in modos:
        _hablar(f"No existe el modo {nombre_modo}. Los modos disponibles son: {', '.join(modos.keys())}.", chat_widget)
        return
    _hablar(f"Activando modo {nombre_modo}", chat_widget)
    for app_item in modos[nombre_modo]:
        abrir_app(app_item, chat_widget, pedir_confirmacion=False)
        time.sleep(1)


# =============================================================================
# 7. BÚSQUEDA DE ARCHIVOS EN DISCO
# =============================================================================

def buscar_archivos(termino: str, carpeta: str = None) -> list:
    """Busca archivos en disco que coincidan con el término."""
    from thefuzz import fuzz
    if carpeta is None:
        carpeta = os.path.expanduser("~")
    ext_ok       = _extensiones_permitidas()
    ignorar      = _carpetas_ignorar()
    termino_norm = _quitar_tildes(termino.lower())
    palabras     = [w for w in termino_norm.split() if len(w) > 2]
    resultados   = []

    for root, dirs, files in os.walk(carpeta, onerror=lambda e: None):
        dirs[:] = [d for d in dirs if d not in ignorar]
        for file in files:
            nombre_norm    = _quitar_tildes(file.lower())
            nombre_sin_ext = os.path.splitext(nombre_norm)[0]
            ext            = os.path.splitext(nombre_norm)[1]
            if ext not in ext_ok:
                continue
            if len(palabras) >= 2:
                if all(w in nombre_sin_ext for w in palabras):
                    resultados.append(os.path.join(root, file))
            else:
                if termino_norm in nombre_norm or fuzz.token_set_ratio(termino_norm, nombre_sin_ext) >= 75:
                    resultados.append(os.path.join(root, file))
            if len(resultados) >= 100:
                break
        if len(resultados) >= 100:
            break

    resultados_unique = list(dict.fromkeys(resultados))
    resultados_unique.sort(key=lambda p: os.path.basename(p).lower())
    return resultados_unique[:20]


def buscar_y_abrir_archivo(termino: str, chat_widget=None):
    """Busca archivos en disco. Muestra lista clickeable. Solo abre si hay 1 resultado o el termino incluye 'abrir'."""
    import threading as _th

    abrir_directo = any(x in termino.lower() for x in ["abrir", "abre", "open"])
    termino_busq  = re.sub(r'\b(abrir?|abre|open)\b', '', termino, flags=re.IGNORECASE).strip()

    def _worker():
        global _archivo_office_pendiente
        _hablar("Buscando...", chat_widget)
        encontrados = buscar_archivos(termino_busq or termino)
        if not encontrados:
            _hablar(f"No encontré nada parecido a '{termino_busq or termino}'.", chat_widget)
            return

        if len(encontrados) == 1 or abrir_directo:
            # Abrir el primero directamente
            ruta   = encontrados[0]
            nombre = os.path.basename(ruta)
            ext    = os.path.splitext(ruta)[1].lower()
            if ext in OFFICE_EXTENSIONES:
                _hablar(f"Encontré {nombre}. ¿Lo abro en la app o en la web?", chat_widget)
                _archivo_office_pendiente = ruta
            else:
                _hablar(f"Abriendo {nombre}.", chat_widget)
                os.startfile(ruta)
            if len(encontrados) > 1:
                # Mostrar el resto como clickeables igual
                nombres_extra = encontrados[1:8]
                filas = "".join(
                    f'<tr><td style="padding:3px 8px;">'
                    f'<a href="open:{r}" style="color:#4db8ff;font-size:12px;">'
                    f'📄 {os.path.basename(r)}</a></td></tr>'
                    for r in nombres_extra
                )
                html = (
                    f'<p style="color:#8899bb;font-size:12px;">Otros resultados (click para abrir):</p>'
                    f'<table>{filas}</table>'
                )
                _ctx["bridge"].append_html.emit(_burbuja(html))
                _ctx["bridge"].scroll_down.emit()
        else:
            # Mostrar lista clickeable — el usuario elige cuál abrir
            nombres = encontrados[:10]
            filas = "".join(
                f'<tr><td style="padding:4px 8px;border-bottom:1px solid #0d1f3a;">'
                f'<a href="open:{r}" style="color:#4db8ff;text-decoration:none;font-size:13px;">'
                f'📄 {os.path.basename(r)}</a>'
                f'<br><span style="color:#556677;font-size:10px;">{os.path.dirname(r)}</span>'
                f'</td></tr>'
                for r in nombres
            )
            html = (
                f'<p style="color:#cce0ff;font-size:13px;">Encontré <b>{len(encontrados)}</b> '
                f'archivo(s) — haz click para abrir:</p>'
                f'<table width="100%" cellspacing="0">{filas}</table>'
            )
            _ctx["bridge"].append_html.emit(_burbuja(html))
            _ctx["bridge"].scroll_down.emit()
            _hablar(f"Encontré {len(encontrados)} archivos. Haz click en el que quieres abrir.", chat_widget)

    _th.Thread(target=_worker, daemon=True).start()


def aprender_app(nombre: str, ruta: str, chat_widget=None):
    """Registra una app nueva en memoria."""
    apps = _apps()
    nombre_norm = nombre.lower().strip()
    apps[nombre_norm] = ruta
    # Persistir en el archivo de memoria del contexto
    apps_file = os.path.join(_base_path(), "memoria_apps.txt")
    try:
        with open(apps_file, "a", encoding="utf-8") as f:
            f.write(f"{nombre_norm}|{ruta}\n")
    except Exception as e:
        print(f"[agent_pc] Error guardando app: {e}")
    _hablar(f"He aprendido la aplicación {nombre}.", chat_widget)


# =============================================================================
# FUNCIÓN PRINCIPAL DEL AGENTE
# =============================================================================

def ejecutar(accion: str, params: dict, chat_widget=None) -> bool:
    """
    Punto de entrada único desde dispatcher.py.

    Devuelve True si procesó la acción, False si la acción no existe.
    """
    p = params or {}

    # ── Ventanas ─────────────────────────────────────────────────────────────
    if accion == "abrir":
        abrir_app(p.get("nombre", ""), chat_widget)
        return True

    if accion == "cerrar":
        cerrar_app(p.get("nombre", ""), chat_widget)
        return True

    if accion == "minimizar":
        minimizar_app(p.get("nombre", ""), chat_widget)
        return True

    if accion == "maximizar":
        maximizar_app(p.get("nombre", ""), chat_widget)
        return True

    # ── Volumen ───────────────────────────────────────────────────────────────
    if accion == "poner_volumen":
        poner_volumen(int(p.get("porcentaje", p.get("nivel", 50))), chat_widget)
        return True

    if accion == "subir_volumen":
        subir_volumen(int(p.get("porcentaje", 10)), chat_widget)
        return True

    if accion == "bajar_volumen":
        bajar_volumen(int(p.get("porcentaje", 10)), chat_widget)
        return True

    if accion == "mute":
        mute_volumen(chat_widget)
        return True

    # ── Brillo ────────────────────────────────────────────────────────────────
    if accion == "subir_brillo":
        subir_brillo(int(p.get("porcentaje", 10)), chat_widget)
        return True

    if accion == "bajar_brillo":
        bajar_brillo(int(p.get("porcentaje", 10)), chat_widget)
        return True

    if accion == "poner_brillo":
        set_brightness(int(p.get("porcentaje", p.get("nivel", 50))), chat_widget)
        return True

    # ── Encendido / Energía ───────────────────────────────────────────────────
    if accion == "apagar":
        apagar_pc(chat_widget)
        return True

    if accion == "reiniciar":
        reiniciar_pc(chat_widget)
        return True

    if accion == "bloquear":
        bloquear_pc(chat_widget)
        return True

    if accion == "suspender":
        suspender_pc(chat_widget)
        return True

    if accion == "hibernar":
        hibernar_pc(chat_widget)
        return True

    # ── Modos ─────────────────────────────────────────────────────────────────
    if accion == "modo":
        activar_modo(p.get("nombre", ""), chat_widget)
        return True

    # ── Archivos ──────────────────────────────────────────────────────────────
    if accion == "buscar_archivo":
        termino = p.get("termino", "").strip()
        if not termino:
            _hablar("¿Qué archivo estás buscando?", chat_widget)
            return True
        buscar_y_abrir_archivo(termino, chat_widget)
        return True

    if accion == "aprender_app":
        nombre = p.get("nombre", "").strip()
        ruta   = p.get("ruta", "").strip()
        if nombre and ruta:
            aprender_app(nombre, ruta, chat_widget)
        return True

    # ── Estado: resolver destino app vs web pendiente ─────────────────────────
    if accion == "resolver_destino":
        resolver_destino_pendiente(p.get("respuesta", ""), chat_widget)
        return True

    print(f"[agent_pc] Acción desconocida: '{accion}'")
    return False
