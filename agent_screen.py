"""Observacion y control explicito de la pantalla en Windows."""

from __future__ import annotations

import math
import os
import threading
import time

try:
    from PIL import ImageGrab
    HAS_SCREEN_CAPTURE = True
except ImportError:
    ImageGrab = None
    HAS_SCREEN_CAPTURE = False

try:
    import pyautogui
    HAS_INPUT_CONTROL = True
except ImportError:
    pyautogui = None
    HAS_INPUT_CONTROL = False

try:
    import cv2
    HAS_CV2 = True
except Exception:
    cv2 = None
    HAS_CV2 = False

try:
    import mediapipe as mp
    HAS_MEDIAPIPE = False
    try:
        if hasattr(mp, "solutions"):
            HAS_MEDIAPIPE = True
        else:
            import importlib
            try:
                sol = importlib.import_module("mediapipe.python.solutions")
                setattr(mp, "solutions", sol)
                HAS_MEDIAPIPE = True
            except Exception:
                pass
    except Exception:
        pass

    if not HAS_MEDIAPIPE:
        try:
            import importlib
            tasks_module = importlib.import_module("mediapipe.tasks.python")
            setattr(mp, "tasks", tasks_module)
            HAS_MEDIAPIPE = True
        except Exception:
            pass
except Exception:
    mp = None
    HAS_MEDIAPIPE = False

try:
    import numpy as np
    HAS_NUMPY = True
except Exception:
    np = None
    HAS_NUMPY = False

try:
    import sounddevice as sd
    HAS_SOUNDDEVICE = True
except Exception:
    sd = None
    HAS_SOUNDDEVICE = False

_ctx: dict = {}
_latest_frame = None
_frame_lock = threading.Lock()
_modo_gestos_activo = False
_gestos_lock = threading.Lock()
_gestos_thread = None
_cam_gestos = None
_clap_thread = None
_clap_count = 0
_ultimo_clap = 0.0
_ultimo_distancia_manos = None
_gestos_pointer = {"x": 0, "y": 0}
_gestos_drag_active = False
_gestos_pinch_active = False
_gestos_pinch_type = None
_gestos_pinch_candidate_started = 0.0
_gestos_pinch_last_seen = 0.0
_gestos_pinch_started = 0.0
_gestos_last_zoom = None
_gestos_last_zoom_ts = 0.0

# Gesture tuning
_GESTOS_MIRROR = True  # Mirror camera X -> screen (front camera) to avoid left/right inversion
_GESTOS_SMOOTH_ALPHA = 0.8  # smoothing factor for pointer (0..1 new weight)
_GESTOS_PINCH_SCALE = 0.03  # pinch threshold as fraction of diagonal (fallback)
_GESTOS_MIN_PINCH_PIX = None  # absolute pixel threshold calculated by calibration
_GESTOS_MOVE_DURATION = 0.01
_GESTOS_FRAME_SKIP = 1  # process every Nth frame (0=no skip)
_GESTOS_LAST_ACTION_TS = 0.0
_GESTOS_MIX_PINCH_HOLD = 0.22
_GESTOS_PINCH_LOSS_GRACE = 0.32
_GESTOS_SCROLL_AMOUNT = 45
_GESTOS_ACTION_DEBOUNCE = 0.22

# Verbose logging for calibration/debugging
_GESTOS_VERBOSE_LOG = False
_GESTOS_LOG_PATH = "gestos_detailed_log.txt"


def _gestos_log(*parts):
    if not _GESTOS_VERBOSE_LOG:
        return
    try:
        msg = " ".join(str(p) for p in parts)
        ts = time.strftime("%Y-%m-%d %H:%M:%S") + f".{int((time.time()%1)*1000):03d}"
        log_path = os.path.join(_ctx.get("base_path", ""), _GESTOS_LOG_PATH) if _ctx.get("base_path") else _GESTOS_LOG_PATH
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass



def init(ctx: dict):
    global _ctx
    _ctx = ctx


def _say(text: str, chat_widget=None):
    hablar = _ctx.get("hablar")
    if callable(hablar):
        hablar(text, chat_widget)


def _notify(text: str):
    notify = _ctx.get("notify")
    if callable(notify):
        notify(text)


def capturar_pantalla() -> object | None:
    if not HAS_SCREEN_CAPTURE:
        return None
    try:
        return ImageGrab.grab(all_screens=True)
    except Exception as exc:
        print(f"[Screen] No se pudo capturar la pantalla: {exc}")
        return None


def capturar_frame() -> object | None:
    """Obtiene un frame efímero; nunca lo escribe en disco."""
    return capturar_pantalla()


def publicar_frame(imagen):
    global _latest_frame
    with _frame_lock:
        _latest_frame = imagen.copy() if imagen is not None else None


def obtener_ultimo_frame():
    with _frame_lock:
        return _latest_frame.copy() if _latest_frame is not None else None


def _require_control(chat_widget=None) -> bool:
    if not HAS_INPUT_CONTROL:
        _say("El control de pantalla requiere instalar pyautogui.", chat_widget)
        return False
    try:
        pyautogui.PAUSE = 0.08
        pyautogui.FAILSAFE = True
        return True
    except Exception:
        return False


def _diagnose_requirements():
    """Return tuple (missing:list[str], info:list[str]) with installed versions."""
    missing = []
    info = []
    try:
        if HAS_CV2:
            try:
                info.append(f"OpenCV {cv2.__version__}")
            except Exception:
                info.append("OpenCV (installed)")
        else:
            missing.append("opencv-python (cv2)")
    except Exception:
        missing.append("opencv-python (cv2)")

    try:
        if HAS_NUMPY:
            try:
                info.append(f"NumPy {np.__version__}")
            except Exception:
                info.append("NumPy (installed)")
        else:
            missing.append("numpy")
    except Exception:
        missing.append("numpy")

    try:
        if HAS_MEDIAPIPE:
            try:
                ver = getattr(mp, "__version__", None) or getattr(mp, "version", None)
                info.append(f"MediaPipe {ver if ver else 'installed'}")
            except Exception:
                info.append("MediaPipe (installed)")
        else:
            missing.append("mediapipe")
    except Exception:
        missing.append("mediapipe")

    return missing, info


def _buscar_objetivo_en_pantalla(objetivo: str) -> tuple[int, int] | None:
    if not HAS_SCREEN_CAPTURE:
        return None
    try:
        import pytesseract
        from pytesseract import Output
    except Exception:
        return None
    try:
        imagen = ImageGrab.grab(all_screens=True)
        datos = pytesseract.image_to_data(imagen, output_type=Output.DICT, lang='spa+eng')
        objetivo_norm = objetivo.lower().strip()
        for idx, texto in enumerate(datos.get('text', [])):
            if not texto:
                continue
            if objetivo_norm in texto.lower():
                x = int(datos['left'][idx] + datos['width'][idx] / 2)
                y = int(datos['top'][idx] + datos['height'][idx] / 2)
                return x, y
    except Exception as exc:
        print(f"[Screen] OCR objetivo falló: {exc}")
    return None


def hacer_click(x: int | None = None, y: int | None = None, boton: str = "left", clicks: int = 1, objetivo: str | None = None, chat_widget=None):
    if not _require_control(chat_widget):
        return
    try:
        if x is None or y is None:
            if objetivo:
                coords = _buscar_objetivo_en_pantalla(objetivo)
                if coords is not None:
                    x, y = coords
                    _notify(f"Objetivo '{objetivo}' localizado en {x}, {y}")
                else:
                    _say(
                        f"No encontré '{objetivo}' en pantalla. Haré clic donde esté el cursor.",
                        chat_widget,
                    )
            if x is None or y is None:
                pt = pyautogui.position()
                x = pt.x
                y = pt.y
        if x is None or y is None:
            _say("No pude determinar dónde hacer clic.", chat_widget)
            return
        pyautogui.click(
            int(x), int(y),
            clicks=max(1, min(3, int(clicks))),
            button=boton if boton in ("left", "right", "middle") else "left",
        )
        _notify(f"Click en {int(x)}, {int(y)}")
    except Exception as exc:
        print(f"[Screen] Click falló: {exc}")
        _say("No pude hacer ese clic.", chat_widget)


def escribir(texto: str, intervalo: float = 0.02, chat_widget=None):
    if not _require_control(chat_widget):
        return
    try:
        pyautogui.write(str(texto or ""), interval=max(0, min(0.2, float(intervalo))))
        _notify("Texto escrito")
    except Exception as exc:
        print(f"[Screen] Escritura falló: {exc}")
        _say("No pude escribir en la ventana activa.", chat_widget)


def pulsar_tecla(tecla: str, chat_widget=None):
    if not _require_control(chat_widget):
        return
    tecla = str(tecla or "").strip().lower()
    permitidas = {"enter", "esc", "escape", "tab", "space", "backspace", "delete", "home", "end", "up", "down", "left", "right", "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12", "ctrl", "alt", "shift"}
    if len(tecla) != 1 and tecla not in permitidas:
        _say("Esa tecla no está permitida por el control de pantalla.", chat_widget)
        return
    try:
        pyautogui.press("esc" if tecla == "escape" else tecla)
        _notify(f"Tecla: {tecla}")
    except Exception as exc:
        print(f"[Screen] Tecla falló: {exc}")
        _say("No pude pulsar esa tecla.", chat_widget)


def desplazarse(cantidad: int, x: int | None = None, y: int | None = None, chat_widget=None):
    if not _require_control(chat_widget):
        return
    try:
        if x is not None and y is not None:
            pyautogui.moveTo(int(x), int(y), duration=0.1)
        # Scroll amount is a wheel delta; allow a broader range for voice commands.
        cantidad_int = max(-1000, min(1000, int(cantidad)))
        pyautogui.scroll(cantidad_int)
        _notify(f"Desplazamiento: {cantidad_int}")
    except Exception as exc:
        print(f"[Screen] Desplazamiento falló: {exc}")
        _say("No pude desplazar la pantalla.", chat_widget)


def hacer_zoom(cantidad: int = 120, chat_widget=None):
    if not _require_control(chat_widget):
        return
    try:
        pyautogui.keyDown('ctrl')
        pyautogui.scroll(int(cantidad))
        pyautogui.keyUp('ctrl')
        _notify(f"Zoom ejecutado: {int(cantidad)}")
    except Exception as exc:
        print(f"[Screen] Zoom falló: {exc}")
        _say("No pude ejecutar zoom.", chat_widget)


def _calcular_distancia(p1, p2):
    return math.hypot(p1[0] - p2[0], p1[1] - p2[1])


def _finger_extended(coords, tip_idx, pip_idx):
    try:
        wrist = coords[0]
        tip = coords[tip_idx]
        pip = coords[pip_idx]
        wrist_to_tip = _calcular_distancia(wrist, tip)
        wrist_to_pip = _calcular_distancia(wrist, pip)
        return wrist_to_tip > wrist_to_pip * 1.1
    except Exception:
        return False


def _count_extended_fingers(coords):
    """Count fingers extended using distances from wrist and pip joints."""
    try:
        thumb_extended = _finger_extended(coords, 4, 2)
        index_extended = _finger_extended(coords, 8, 6)
        middle_extended = _finger_extended(coords, 12, 10)
        ring_extended = _finger_extended(coords, 16, 14)
        pinky_extended = _finger_extended(coords, 20, 18)
        return sum((thumb_extended, index_extended, middle_extended, ring_extended, pinky_extended))
    except Exception:
        return 0


def _hand_open(coords):
    return _count_extended_fingers(coords) >= 3


def _is_thumb_index_scroll(coords):
    return (
        _finger_extended(coords, 4, 2)
        and _finger_extended(coords, 8, 6)
        and not _finger_extended(coords, 12, 10)
        and not _finger_extended(coords, 16, 14)
        and not _finger_extended(coords, 20, 18)
    )


def _is_index_middle_scroll(coords):
    return (
        _finger_extended(coords, 8, 6)
        and _finger_extended(coords, 12, 10)
        and not _finger_extended(coords, 4, 2)
        and not _finger_extended(coords, 16, 14)
        and not _finger_extended(coords, 20, 18)
    )


def _mirror_x(x, frame_w, screen_w):
    # Mirror horizontal coordinate from camera to screen if needed
    if _GESTOS_MIRROR:
        return int(screen_w - (x * screen_w / float(frame_w)))
    return int(x * screen_w / float(frame_w))


def _manejar_gestos_por_camara(chat_widget=None):
    global _ultimo_distancia_manos
    if not (HAS_CV2 and HAS_MEDIAPIPE and HAS_NUMPY):
        missing, info = _diagnose_requirements()
        msg_lines = []
        if info:
            msg_lines.append("Detectado: " + ", ".join(info))
        if missing:
            msg_lines.append("Faltan paquetes: " + ", ".join(missing))
            msg_lines.append("Instálalos ejecutando:")
            msg_lines.append("    python -m pip install --user opencv-python mediapipe numpy")
        msg_lines.append("Si ya están instalados, revisa que la cámara esté disponible y que Python tenga permisos para acceder a ella.")
        _say(" ".join(msg_lines), chat_widget)
        print("[Screen] Requisitos faltantes o no detectados:", missing, "; info:", info)
        return False

    with _gestos_lock:
        global _modo_gestos_activo, _cam_gestos, _gestos_thread
        if _modo_gestos_activo and _cam_gestos is not None and _cam_gestos.isOpened():
            return True

        if _cam_gestos is None:
            # Try multiple camera indices in case builtin camera lives on another index
            opened = False
            for idx in range(0, 4):
                try:
                    cap = cv2.VideoCapture(idx)
                    if cap is not None and cap.isOpened():
                        _cam_gestos = cap
                        opened = True
                        break
                    else:
                        try:
                            cap.release()
                        except Exception:
                            pass
                except Exception:
                    continue
            if not opened:
                _say("No pude abrir la cámara del equipo.", chat_widget)
                _cam_gestos = None
                return False

        _modo_gestos_activo = True
        if _gestos_thread is None or not _gestos_thread.is_alive():
            _gestos_thread = threading.Thread(target=_hilo_gestos, daemon=True, name="JarvisGestos")
            _gestos_thread.start()
        _notify("Modo de gestos activado")
        return True


def _hilo_gestos():
    global _modo_gestos_activo, _ultimo_distancia_manos, _cam_gestos, _gestos_pointer, _gestos_drag_active, _gestos_pinch_active, _gestos_pinch_type, _gestos_pinch_candidate_started, _gestos_pinch_last_seen, _gestos_pinch_started, _gestos_last_zoom, _gestos_last_zoom_ts, _GESTOS_LAST_ACTION_TS

    if not (HAS_CV2 and HAS_MEDIAPIPE and HAS_NUMPY):
        return

    # Determine backend: solutions Hands or Tasks HandLandmarker
    use_solutions = False
    hand_detector = None
    tasks_backend = None
    try:
        if hasattr(mp, 'solutions') and hasattr(mp.solutions, 'hands'):
            use_solutions = True
            hand_detector = mp.solutions.hands.Hands(max_num_hands=2, min_detection_confidence=0.7, min_tracking_confidence=0.6)
        else:
            # Try Tasks API
            try:
                from mediapipe.tasks.python import vision
                from mediapipe.tasks.python.core.base_options import BaseOptions
                from mediapipe.tasks.python.vision.core import image as image_lib
                # Attempt to find a local model asset
                model_path = None
                try:
                    import os, glob
                    script_dir = os.path.abspath(os.path.dirname(__file__))
                    cwd = os.path.abspath(os.getcwd())
                    base_paths = list(getattr(mp, '__path__', []))
                    resource_dir = _ctx.get("resource_path")
                    search_dirs = [script_dir, cwd]
                    if resource_dir:
                        search_dirs.append(os.path.abspath(resource_dir))
                    search_dirs += base_paths
                    candidates = []
                    for base_dir in search_dirs:
                        if not os.path.isdir(base_dir):
                            continue
                        candidates += glob.glob(os.path.join(base_dir, '**', 'hand_landmarker*.task'), recursive=True)
                        candidates += glob.glob(os.path.join(base_dir, '**', 'hand_landmarker*.tflite'), recursive=True)
                    if candidates:
                        model_path = os.path.abspath(candidates[0])
                except Exception:
                    model_path = None

                if model_path is None:
                    print("[Screen] No encontré un modelo hand_landmarker; la Tasks API necesita un archivo .task/.tflite. Busca 'hand_landmarker.task' o instala una versión de mediapipe que incluya modelos.")
                else:
                    options = vision.HandLandmarkerOptions(
                        base_options=BaseOptions(model_asset_path=model_path),
                        running_mode=vision.RunningMode.VIDEO,
                        num_hands=2,
                        min_hand_detection_confidence=0.6,
                    )
                    try:
                        hand_detector = vision.HandLandmarker.create_from_options(options)
                        tasks_backend = vision
                        print(f"[Screen] Usando HandLandmarker Tasks model: {model_path}")
                    except Exception as exc:
                        print(f"[Screen] No pude inicializar HandLandmarker Tasks: {exc}")
            except Exception as exc:
                print(f"[Screen] Tasks API no disponible o falló: {exc}")
    except Exception as exc:
        print(f"[Screen] Error al inicializar backend de manos: {exc}")
        _modo_gestos_activo = False
        return

    if hand_detector is None:
        print("[Screen] No hay backend de detección de manos disponible.")
        _modo_gestos_activo = False
        return

    while _modo_gestos_activo:
        if _cam_gestos is None or not _cam_gestos.isOpened():
            break

        ok, frame = _cam_gestos.read()
        if not ok or frame is None:
            time.sleep(0.03)
            continue

        # optional frame skipping to reduce CPU
        if _GESTOS_FRAME_SKIP and (_GESTOS_FRAME_SKIP > 0):
            _GESTOS_FRAME_SKIP_COUNTER = getattr(_hilo_gestos, '_skip_ctr', 0) + 1
            setattr(_hilo_gestos, '_skip_ctr', _GESTOS_FRAME_SKIP_COUNTER)
            if _GESTOS_FRAME_SKIP_COUNTER % (_GESTOS_FRAME_SKIP + 1) != 0:
                time.sleep(0.01)
                continue

        try:
            if use_solutions:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                res = hand_detector.process(rgb)
                multi_hand_landmarks = getattr(res, 'multi_hand_landmarks', None)
                hands_list = multi_hand_landmarks or []
                puntos = []
                for mano in hands_list:
                    coords = [(int(lm.x * frame.shape[1]), int(lm.y * frame.shape[0])) for lm in mano.landmark]
                    puntos.append(coords)
            else:
                # Tasks API: create Image and call detect_for_video
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                img = image_lib.Image(image_lib.ImageFormat.SRGB, rgb)
                ts = int(time.time() * 1000)
                try:
                    task_result = hand_detector.detect_for_video(img, ts)
                except Exception as exc:
                    try:
                        task_result = hand_detector.detect(img)
                    except Exception as exc2:
                        print(f"[Screen] HandLandmarker detect failed: {exc} / {exc2}")
                        task_result = None
                puntos = []
                if task_result is not None:
                    hand_landmarks = getattr(task_result, 'hand_landmarks', None) or []
                    # hand_landmarks is a list of lists of normalized landmarks
                    for hand in hand_landmarks:
                        coords = []
                        for lm in hand:
                            try:
                                x = int(lm.x * frame.shape[1])
                                y = int(lm.y * frame.shape[0])
                            except Exception:
                                x = int(getattr(lm, 'x', 0) * frame.shape[1])
                                y = int(getattr(lm, 'y', 0) * frame.shape[0])
                            coords.append((x, y))
                        puntos.append(coords)

            if puntos:
                _gestos_log('DETECTED_POINTS', len(puntos))
                if len(puntos) >= 2:
                    candidates = sorted(puntos, key=lambda coords: _calcular_distancia(coords[0], coords[9]), reverse=True)[:2]
                    a, b = candidates[0], candidates[1]
                    if _hand_open(a) and _hand_open(b):
                        dist = _calcular_distancia(a[8], b[8])
                        if _gestos_last_zoom is not None:
                            diff = dist - _gestos_last_zoom
                            ahora = time.monotonic()
                            if abs(diff) > 35 and (ahora - _gestos_last_zoom_ts) > 0.5:
                                if diff > 0:
                                    try: pyautogui.hotkey('ctrl', '+')
                                    except Exception: pass
                                else:
                                    try: pyautogui.hotkey('ctrl', '-')
                                    except Exception: pass
                                _gestos_last_zoom_ts = ahora
                        _gestos_last_zoom = dist
                    else:
                        _gestos_last_zoom = None

                mano_principal = max(puntos, key=lambda coords: _calcular_distancia(coords[0], coords[9])) if puntos else None
                if mano_principal is not None:
                    index_tip = mano_principal[8]
                    middle_tip = mano_principal[12]
                    thumb_tip = mano_principal[4]
                    # adaptive pinch threshold relative to frame diagonal or calibrated absolute
                    diag = math.hypot(frame.shape[1], frame.shape[0])
                    index_len = _calcular_distancia(mano_principal[5], index_tip)
                    middle_len = _calcular_distancia(mano_principal[9], middle_tip)
                    thumb_index_dist = _calcular_distancia(thumb_tip, index_tip)
                    thumb_middle_dist = _calcular_distancia(thumb_tip, middle_tip)
                    if _GESTOS_MIN_PINCH_PIX is not None:
                        pinch_threshold = max(8, min(_GESTOS_MIN_PINCH_PIX, min(index_len, middle_len) * 0.45))
                    else:
                        pinch_threshold = max(12, diag * _GESTOS_PINCH_SCALE)
                    left_pinch = thumb_index_dist < pinch_threshold and thumb_index_dist < thumb_middle_dist
                    right_pinch = thumb_middle_dist < pinch_threshold and thumb_middle_dist < thumb_index_dist
                    any_pinch = left_pinch or right_pinch

                    palm_x = int(sum(mano_principal[i][0] for i in (0, 5, 9, 13, 17)) / 5)
                    palm_y = int(sum(mano_principal[i][1] for i in (0, 5, 9, 13, 17)) / 5)
                    x = max(0, min(frame.shape[1] - 1, palm_x))
                    y = max(0, min(frame.shape[0] - 1, palm_y))
                    alpha = float(max(0.1, min(0.95, _GESTOS_SMOOTH_ALPHA)))
                    _gestos_pointer["x"] = _gestos_pointer.get("x", x) * (1.0 - alpha) + x * alpha
                    _gestos_pointer["y"] = _gestos_pointer.get("y", y) * (1.0 - alpha) + y * alpha

                    screen_w, screen_h = pyautogui.size()
                    screen_x = _mirror_x(_gestos_pointer["x"], frame.shape[1], screen_w)
                    screen_y = int(_gestos_pointer["y"] * screen_h / float(frame.shape[0]))
                    screen_x = max(0, min(screen_w - 1, screen_x))
                    screen_y = max(0, min(screen_h - 1, screen_y))
                    try:
                        pyautogui.moveTo(screen_x, screen_y, duration=_GESTOS_MOVE_DURATION)
                    except Exception:
                        pass
                    # Finger counting to map gestures to commands
                    finger_count = _count_extended_fingers(mano_principal)
                    thumb_index_scroll = _is_thumb_index_scroll(mano_principal)
                    index_middle_scroll = _is_index_middle_scroll(mano_principal)
                    _gestos_log('MAIN_HAND_SAMPLE', {'first5': mano_principal[:5], 'finger_count': finger_count, 'left_pinch': left_pinch, 'right_pinch': right_pinch, 'thumb_index_scroll': thumb_index_scroll, 'index_middle_scroll': index_middle_scroll})
                    now = time.monotonic()
                    # Priority: pinch/drag takes precedence
                    if any_pinch:
                        if not _gestos_pinch_active:
                            if _gestos_pinch_candidate_started <= 0.0 or _gestos_pinch_type is None:
                                _gestos_pinch_candidate_started = now
                                _gestos_pinch_type = 'left' if left_pinch and not right_pinch else 'right' if right_pinch and not left_pinch else 'left' if left_pinch else 'right'
                            if _gestos_pinch_type is not None and now - _gestos_pinch_candidate_started >= _GESTOS_MIX_PINCH_HOLD:
                                _gestos_pinch_active = True
                                _gestos_pinch_started = _gestos_pinch_candidate_started
                        _gestos_pinch_last_seen = now
                    elif _gestos_pinch_active and (now - _gestos_pinch_last_seen) <= _GESTOS_PINCH_LOSS_GRACE:
                        # keep dragging through short tracking gaps
                        pass
                    elif _gestos_pinch_active:
                        duracion = now - _gestos_pinch_started
                        if duracion >= 0.08:
                            try:
                                if _gestos_pinch_type == 'right':
                                    pyautogui.click(button='right')
                                    _gestos_log('ACTION', 'click', 'right_pinch')
                                else:
                                    if duracion < 0.35:
                                        pyautogui.click()
                                        _gestos_log('ACTION', 'click', 'short_pinch')
                                    else:
                                        pyautogui.mouseUp(button='left')
                                        _gestos_log('ACTION', 'mouseUp', 'end_drag')
                            except Exception:
                                _gestos_log('ACTION_FAIL', 'click')
                        _gestos_pinch_active = False
                        _gestos_drag_active = False
                        _gestos_pinch_type = None
                        _gestos_pinch_candidate_started = 0.0
                    elif _gestos_pinch_candidate_started > 0.0 and not _gestos_pinch_active:
                        # quick pinch and release: register click even if not held long enough to enter drag mode
                        duracion = now - _gestos_pinch_candidate_started
                        if duracion >= 0.05 and duracion < _GESTOS_MIX_PINCH_HOLD:
                            try:
                                if _gestos_pinch_type == 'right':
                                    pyautogui.click(button='right')
                                    _gestos_log('ACTION', 'click', 'quick_right_pinch')
                                else:
                                    pyautogui.click()
                                    _gestos_log('ACTION', 'click', 'quick_left_pinch')
                            except Exception:
                                _gestos_log('ACTION_FAIL', 'click')
                        _gestos_pinch_candidate_started = 0.0
                        _gestos_pinch_type = None
                    if _gestos_pinch_active and _gestos_pinch_type == 'left':
                        duracion = now - _gestos_pinch_started
                        if duracion >= 0.24 and not _gestos_drag_active:
                            try:
                                pyautogui.mouseDown(button='left')
                                _gestos_log('ACTION', 'mouseDown', 'start_drag')
                            except Exception:
                                _gestos_log('ACTION_FAIL', 'mouseDown')
                            _gestos_drag_active = True
                        if _gestos_drag_active:
                            try:
                                pyautogui.moveTo(screen_x, screen_y, duration=0)
                            except Exception:
                                _gestos_log('ACTION_FAIL', 'drag_move')
                    elif not _gestos_pinch_active and now - _GESTOS_LAST_ACTION_TS > _GESTOS_ACTION_DEBOUNCE:
                        if thumb_index_scroll:
                            try:
                                pyautogui.scroll(_GESTOS_SCROLL_AMOUNT)
                                _gestos_log('ACTION', 'scroll', {'direction': 'up', 'amount': _GESTOS_SCROLL_AMOUNT})
                                _GESTOS_LAST_ACTION_TS = now
                            except Exception:
                                _gestos_log('ACTION_FAIL', 'scroll_up')
                        elif index_middle_scroll:
                            try:
                                pyautogui.scroll(-_GESTOS_SCROLL_AMOUNT)
                                _gestos_log('ACTION', 'scroll', {'direction': 'down', 'amount': -_GESTOS_SCROLL_AMOUNT})
                                _GESTOS_LAST_ACTION_TS = now
                            except Exception:
                                _gestos_log('ACTION_FAIL', 'scroll_down')
                        # No discrete click action for finger counts now; thumb+middle pinch is right click

            else:
                if _gestos_drag_active:
                    try: pyautogui.mouseUp(button='left')
                    except Exception: pass
                    _gestos_drag_active = False
                _gestos_pinch_active = False
                _gestos_last_zoom = None

        except Exception as exc:
            print(f"[Screen] Error durante bucle de gestos: {exc}")

        time.sleep(0.01)

    # Cleanup
    try:
        if use_solutions and hand_detector is not None:
            hand_detector.close()
    except Exception:
        pass
    try:
        if tasks_backend and hand_detector is not None:
            hand_detector.close()
    except Exception:
        pass
    if _cam_gestos is not None:
        try:
            _cam_gestos.release()
        except Exception:
            pass
        _cam_gestos = None
    _ultimo_distancia_manos = None
    _gestos_pointer = {"x": 0, "y": 0}
    _gestos_drag_active = False
    _gestos_pinch_active = False
    _gestos_last_zoom = None
    _gestos_last_zoom_ts = 0.0
    _gestos_pinch_started = 0.0


def _toggle_clap_listener():
    global _clap_thread, _clap_count, _ultimo_clap
    if not HAS_SOUNDDEVICE or not HAS_NUMPY:
        return
    if _clap_thread is not None and _clap_thread.is_alive():
        return

    def _escuchar_claps():
        global _clap_count, _ultimo_clap, _modo_gestos_activo
        def _audio_callback(indata, frames, time_info, status):
            global _clap_count, _ultimo_clap, _modo_gestos_activo
            if status:
                print(f"[Screen] Audio status: {status}")
            audio = np.squeeze(indata)
            rms = float(np.sqrt(np.mean(np.square(audio)))) if audio.size else 0.0
            ahora = time.monotonic()
            if rms > 0.18 and (ahora - _ultimo_clap) > 0.55:
                _ultimo_clap = ahora
                _clap_count += 1
                if _clap_count == 1 and not _modo_gestos_activo:
                    activar_modo_gestos()
                elif _clap_count == 2 and _modo_gestos_activo:
                    desactivar_modo_gestos()
                elif _clap_count >= 2:
                    _clap_count = 0
            elif rms < 0.04 and ahora - _ultimo_clap > 0.8:
                _clap_count = 0

        try:
            with sd.InputStream(samplerate=16000, channels=1, callback=_audio_callback, dtype='float32'):
                while _modo_gestos_activo:
                    time.sleep(0.1)
        except Exception as exc:
            print(f"[Screen] Escucha de aplausos falló: {exc}")

    _clap_thread = threading.Thread(target=_escuchar_claps, daemon=True, name="JarvisClaps")
    _clap_thread.start()


def calibrar_gestos(duracion: int = 6, chat_widget=None):
    """Calibracion simple: recoge distancias pulgar-indice y calcula un umbral absoluto.
    duracion: segundos a muestrear (recomendado 4..10)
    """
    global _GESTOS_MIN_PINCH_PIX
    if not HAS_CV2 or not HAS_NUMPY:
        _say("Para calibrar necesitas instalar opencv y numpy.", chat_widget)
        return None
    _say("Calibración de gestos: coloca la mano abierta frente a la cámara, luego realiza un pellizco varias veces.", chat_widget)
    try:
        cap = None
        for idx in range(0, 4):
            try:
                c = cv2.VideoCapture(idx)
                if c is not None and c.isOpened():
                    cap = c
                    break
                else:
                    try: c.release()
                    except Exception: pass
            except Exception:
                continue
        if cap is None:
            _say("No pude abrir la cámara para calibrar.", chat_widget)
            return None
        inicio = time.time()
        dists = []
        while time.time() - inicio < max(2, int(duracion)):
            ok, frame = cap.read()
            if not ok or frame is None:
                time.sleep(0.05)
                continue
            try:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                # try solutions or tasks lightweight detection
                pts = []
                if hasattr(mp, 'solutions') and hasattr(mp.solutions, 'hands'):
                    with mp.solutions.hands.Hands(static_image_mode=False, max_num_hands=1) as hd:
                        res = hd.process(rgb)
                        if getattr(res, 'multi_hand_landmarks', None):
                            mano = res.multi_hand_landmarks[0]
                            lm = mano.landmark[4]
                            lm2 = mano.landmark[8]
                            d = math.hypot((lm.x - lm2.x) * frame.shape[1], (lm.y - lm2.y) * frame.shape[0])
                            dists.append(d)
                else:
                    # Tasks API attempt (fast path)
                    try:
                        from mediapipe.tasks.python.vision.core import image as image_lib
                        img = image_lib.Image(image_lib.ImageFormat.SRGB, rgb)
                        # attempt to use existing hand_landmarker model file
                        # reuse existing model detection if available in this module
                        # fallback: just skip
                        pass
                    except Exception:
                        pass
            except Exception:
                pass
            time.sleep(0.02)
        try:
            cap.release()
        except Exception:
            pass
        if not dists:
            _say("No detecté manos durante la calibración.", chat_widget)
            return None
        dists_sorted = sorted(dists)
        mn = float(dists_sorted[0])
        med = float(dists_sorted[len(dists_sorted)//2])
        threshold = max(4.0, (mn + med) / 2.0)
        _GESTOS_MIN_PINCH_PIX = threshold
        _gestos_log('CALIBRATION', {'min': mn, 'median': med, 'threshold': threshold})
        _say(f"Calibración completa. Umbral pinch ~ {int(threshold)} pixeles.", chat_widget)
        return threshold
    except Exception as exc:
        print(f"[Screen] Calibración falló: {exc}")
        return None


def activar_modo_gestos(chat_widget=None):
    global _modo_gestos_activo
    if not _require_control(chat_widget):
        return False
    if not _modo_gestos_activo:
        _modo_gestos_activo = True
    if not _manejar_gestos_por_camara(chat_widget):
        # _manejar_gestos_por_camara already explica la causa.
        return False
    _toggle_clap_listener()
    _say("Modo de gestos activado con cámara y control por mano.", chat_widget)
    return True


def desactivar_modo_gestos(chat_widget=None):
    global _modo_gestos_activo, _clap_count, _ultimo_clap, _gestos_thread, _clap_thread, _cam_gestos, _gestos_drag_active, _gestos_pinch_active, _gestos_pointer, _gestos_last_zoom, _gestos_last_zoom_ts, _gestos_pinch_started
    if _modo_gestos_activo:
        _modo_gestos_activo = False
    _clap_count = 0
    _ultimo_clap = 0.0
    _gestos_drag_active = False
    _gestos_pinch_active = False
    _gestos_pointer = {"x": 0, "y": 0}
    _gestos_last_zoom = None
    _gestos_last_zoom_ts = 0.0
    _gestos_pinch_started = 0.0
    try:
        pyautogui.mouseUp(button='left')
    except Exception:
        pass
    if _gestos_thread is not None and _gestos_thread.is_alive():
        _gestos_thread.join(timeout=0.5)
    _gestos_thread = None
    if _cam_gestos is not None:
        try:
            _cam_gestos.release()
        except Exception:
            pass
        _cam_gestos = None
    if _clap_thread is not None and _clap_thread.is_alive():
        _clap_thread.join(timeout=0.2)
    _clap_thread = None
    _say("Modo de gestos desactivado.", chat_widget)
    _notify("Modo gestos apagado")
    return True


def ejecutar(accion: str, params: dict, chat_widget=None):
    """Ejecuta una accion de pantalla sin guardar imagenes."""
    params = params if isinstance(params, dict) else {}
    if accion == "ver_pantalla":
        _notify("Visor de pantalla en tiempo real solicitado")
        _say("Estoy abriendo el visor de pantalla en tiempo real.", chat_widget)
        return
    if accion == "analizar_pantalla":
        analizar = _ctx.get("analizar_pantalla")
        if callable(analizar):
            analizar(chat_widget, str(params.get("pregunta") or "").strip())
        return
    if accion == "activar_gestos":
        return activar_modo_gestos(chat_widget)
    if accion == "desactivar_gestos":
        return desactivar_modo_gestos(chat_widget)
    if accion == "calibrar_gestos":
        return calibrar_gestos(int(params.get('duracion', 6)), chat_widget)
    if accion == "hacer_click":
        return hacer_click(
            params.get("x"), params.get("y"), params.get("boton", "left"),
            params.get("clicks", 1), params.get("objetivo"), chat_widget
        )
    if accion == "escribir":
        return escribir(params.get("texto", ""), params.get("intervalo", 0.02), chat_widget)
    if accion == "pulsar_tecla":
        return pulsar_tecla(params.get("tecla", ""), chat_widget)
    if accion == "desplazarse":
        return desplazarse(params.get("cantidad", -3), params.get("x"), params.get("y"), chat_widget)
    if accion == "hacer_zoom":
        return hacer_zoom(params.get("cantidad", 120), chat_widget)
    _say("No reconozco esa accion de pantalla.", chat_widget)
    return None
