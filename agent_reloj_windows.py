"""Automatización de las alarmas de la app Reloj de Windows.

Windows no expone una API pública para crear alarmas de Reloj. Este módulo
usa controles UI Automation publicados por Microsoft y confirma el guardado.
"""

from __future__ import annotations

import subprocess
import re
import time
import unicodedata
from typing import Any


class ClockAutomationError(RuntimeError):
    """Reloj no pudo automatizarse de forma segura."""


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFD", str(texto or "").casefold())
    return "".join(char for char in texto if unicodedata.category(char) != "Mn")


def _info(wrapper):
    try:
        return wrapper.element_info
    except Exception:
        return None


def _window():
    try:
        from pywinauto import Desktop
    except ImportError as exc:
        raise ClockAutomationError("Falta instalar el componente de automatización de Reloj.") from exc

    subprocess.Popen(
        ["explorer.exe", "ms-clock:"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    desktop = Desktop(backend="uia")
    deadline = time.monotonic() + 8
    last_error = None
    mejor_ventana = None
    while time.monotonic() < deadline:
        try:
            for win in desktop.windows():
                title = _normalizar(win.window_text())
                if any(term in title for term in ("clock", "reloj", "alarma")):
                    mejor_ventana = win
                ids = {
                    (getattr(_info(item), "automation_id", "") or "").casefold()
                    for item in win.descendants()
                }
                if ids.intersection({"alarmpivotitem", "alarmbutton", "addalarmbutton", "alarmname"}):
                    return win
        except Exception as exc:
            last_error = exc
        time.sleep(0.4)
    if mejor_ventana is not None:
        return mejor_ventana
    raise ClockAutomationError("No encontré la ventana de Reloj de Windows.") from last_error


def _find_named(win, names: tuple[str, ...], control_types: tuple[str, ...] = ()):
    wanted = tuple(_normalizar(name) for name in names)
    try:
        descendants = win.descendants()
    except Exception:
        descendants = []
    for item in descendants:
        info = _info(item)
        if info is None:
            continue
        control_type = getattr(info, "control_type", "") or ""
        if control_types and control_type not in control_types:
            continue
        name = _normalizar(getattr(info, "name", "") or "")
        if any(name == value or (len(value) > 3 and value in name) for value in wanted):
            return item
    return None


def _control(win, automation_id: str, names: tuple[str, ...] = (), control_types: tuple[str, ...] = (),
             allow_unique_edit: bool = False):
    try:
        control = win.child_window(auto_id=automation_id)
        if control.exists(timeout=0.25):
            return control.wrapper_object()
    except Exception:
        pass
    if names:
        item = _find_named(win, names, control_types)
        if item is not None:
            return item
        if allow_unique_edit and ("Edit" in control_types or "TextBox" in control_types):
            try:
                edits = [item for item in win.descendants()
                         if getattr(_info(item), "control_type", "") in {"Edit", "TextBox"}]
                if len(edits) == 1:
                    return edits[0]
            except Exception:
                pass
    raise ClockAutomationError(f"Reloj no mostró el control esperado ({automation_id}).")


def _diagnostico_controles(win) -> str:
    """Resumen inocuo para corregir versiones/localizaciones distintas."""
    try:
        descendants = win.descendants()
    except Exception:
        return ""
    result = []
    for item in descendants:
        info = _info(item)
        if info is None:
            continue
        kind = getattr(info, "control_type", "") or ""
        automation_id = getattr(info, "automation_id", "") or ""
        if kind not in {"Button", "TabItem", "CheckBox", "RadioButton", "ComboBox", "Edit", "Custom", "Spinner"}:
            continue
        name = getattr(info, "name", "") or ""
        # Nunca registra nombres de alarmas existentes ni el texto introducido.
        if kind in {"Edit", "Custom", "Spinner", "ComboBox"}:
            name = ""
        label = f"{kind}:{automation_id}:{name}".strip(":")
        if label and label not in result:
            result.append(label[:100])
        if len(result) >= 50:
            break
    return " | ".join(result)


def dias_repeticion(repetir: str | None, dia_semanal: int | None = None) -> set[int] | None:
    """Mapea expresiones en español/inglés a weekdays de Python (lunes=0)."""
    texto = _normalizar(repetir or "")
    if not texto:
        return None
    if any(token in texto for token in ("diaria", "diario", "cada dia", "todos los dias", "daily", "every day")):
        return set(range(7))
    if any(token in texto for token in ("lunes-viernes", "lunes a viernes", "entre semana", "dias laborales", "weekdays")):
        return {0, 1, 2, 3, 4}
    if any(token in texto for token in ("fin de semana", "weekends")):
        return {5, 6}
    if "semanal" in texto or "weekly" in texto:
        return {dia_semanal} if dia_semanal is not None else None

    aliases = {
        0: ("lunes", "lun", "monday", "mon"),
        1: ("martes", "mar", "tuesday", "tue"),
        2: ("miercoles", "mie", "wednesday", "wed"),
        3: ("jueves", "jue", "thursday", "thu"),
        4: ("viernes", "vie", "friday", "fri"),
        5: ("sabado", "sab", "saturday", "sat"),
        6: ("domingo", "dom", "sunday", "sun"),
    }
    days = set()
    for day, names in aliases.items():
        if any(re.search(rf"(?<![a-z]){re.escape(name)}(?![a-z])", texto) for name in names):
            days.add(day)
    return days or None


def _estado_toggle(control):
    try:
        return bool(control.get_toggle_state())
    except Exception:
        pass
    try:
        return bool(control.is_selected())
    except Exception:
        return None


def _activar_toggle(control) -> bool:
    estado = _estado_toggle(control)
    if estado is True:
        return True
    try:
        control.click_input()
        return _estado_toggle(control) is not False
    except Exception:
        return False


def _configurar_repeticion(win, repetir: str) -> bool:
    dias = dias_repeticion(repetir)
    if not dias:
        return False

    # Activa el control de repetición si este diseño lo separa de los días.
    repeat = _find_named(
        win,
        ("Repeat alarm", "Repeat", "Repetir alarma", "Repetir"),
        ("CheckBox", "Button", "RadioButton", "ToggleButton", "ComboBox"),
    )
    if repeat is not None:
        try:
            repeat.click_input()
        except Exception:
            return False

        texto = _normalizar(repetir)
        presets = []
        if dias == set(range(7)):
            presets = ["Every day", "Daily", "Todos los días", "Todos los dias", "Diariamente", "Cada día", "Cada dia"]
        elif dias == {0, 1, 2, 3, 4}:
            presets = ["Weekdays", "Monday to Friday", "Monday-Friday", "Lunes a viernes", "Entre semana"]
        elif dias == {5, 6}:
            presets = ["Weekends", "Saturday and Sunday", "Sábado y domingo", "Sabado y domingo", "Fin de semana"]
        preset = _find_named(win, tuple(presets), ("ComboBoxItem", "ListItem", "MenuItem", "RadioButton")) if presets else None
        if preset is not None:
            try:
                preset.click_input()
                return True
            except Exception:
                return False

    aliases = {
        0: ("Monday", "Mon", "lunes", "lun"),
        1: ("Tuesday", "Tue", "martes", "mar"),
        2: ("Wednesday", "Wed", "miércoles", "miercoles", "mie"),
        3: ("Thursday", "Thu", "jueves", "jue"),
        4: ("Friday", "Fri", "viernes", "vie"),
        5: ("Saturday", "Sat", "sábado", "sabado", "sab"),
        6: ("Sunday", "Sun", "domingo", "dom"),
    }
    for day in sorted(dias):
        control = _find_named(
            win,
            aliases[day],
            ("CheckBox", "Button", "RadioButton", "ToggleButton"),
        )
        if control is None or not _activar_toggle(control):
            return False
    return True


def _click_first_id(win, automation_ids: tuple[str, ...], names: tuple[str, ...] = ()) -> bool:
    for automation_id in automation_ids:
        try:
            _control(win, automation_id).click_input()
            return True
        except Exception:
            continue
    if names:
        item = _find_named(win, names, ("Button", "TabItem", "RadioButton"))
        if item is not None:
            try:
                item.click_input()
                return True
            except Exception:
                pass
    return False


def _abrir_vista_alarmas(win) -> bool:
    """Abre la sección Alarmas en versiones antiguas y nuevas de Clock."""
    alarm_names = (
        "Alarms", "Alarm", "Alarmas", "Alarma", "Alarm clock",
        "Despertador", "Alarmas y reloj",
    )
    alarm_types = (
        "Button", "TabItem", "RadioButton", "ListItem", "TreeItem",
        "Custom", "MenuItem",
    )
    if _click_first_id(win, ("AlarmPivotItem", "AlarmButton", "AlarmsButton"), alarm_names):
        time.sleep(0.35)
        return True

    # La versión actual puede esconder las páginas dentro del panel lateral.
    # Primero despliega el panel; después intenta los nombres localizados.
    for nav_id in (
        "TogglePaneButton", "PaneToggleButton", "NavViewToggleButton",
        "NavigationViewTogglePaneButton",
    ):
        try:
            _control(win, nav_id).click_input()
            time.sleep(0.25)
        except Exception:
            continue
        item = _find_named(win, alarm_names, alarm_types)
        if item is not None:
            try:
                item.click_input()
                time.sleep(0.35)
                return True
            except Exception:
                pass

    # Algunas versiones no publican el botón del panel en el árbol UIA, pero
    # sí lo incluyen en el orden de tabulación. Avanza solo el foco (sin
    # activar controles) y selecciona Alarmas cuando ese elemento recibe foco.
    try:
        for _ in range(24):
            win.type_keys("{TAB}", set_foreground=True)
            time.sleep(0.06)
            focused = next(
                (
                    item for item in win.descendants()
                    if bool(getattr(_info(item), "has_keyboard_focus", False))
                    and any(
                        _normalizar(alias) in _normalizar(getattr(_info(item), "name", "") or "")
                        for alias in alarm_names
                    )
                ),
                None,
            )
            if focused is not None:
                focused.click_input()
                time.sleep(0.35)
                return True
    except Exception:
        pass
    return False


def _click_named_child(parent, name: str) -> bool:
    try:
        candidates = parent.descendants()
    except Exception:
        candidates = []
    for candidate in candidates:
        try:
            if (candidate.window_text() or "").strip() == name:
                candidate.click_input()
                return True
        except Exception:
            continue
    return False


def _set_wheel(win, automation_id: str, value: str, names: tuple[str, ...] = ()) -> bool:
    try:
        wheel = _control(win, automation_id, names, ("Custom", "Group", "Spinner", "SpinButton", "ComboBox", "Edit"))
        if _click_named_child(wheel, value):
            return True
        # Algunas versiones de Clock exponen cada unidad como un selector
        # editable individual en vez de una rueda.
        if hasattr(wheel, "set_edit_text"):
            wheel.set_edit_text(value)
            return True
        return False
    except Exception:
        return False


def _select_period(win, period: str) -> bool | None:
    synonyms = {
        "AM": ("AM", "a. m.", "a. m", "a.m."),
        "PM": ("PM", "p. m.", "p. m", "p.m."),
    }[period]
    found_selector = False
    for automation_id in ("AmPmLoopingSelector", "AmPmSelector", "PeriodLoopingSelector"):
        try:
            selector = _control(win, automation_id)
            found_selector = True
            for label in synonyms:
                if _click_named_child(selector, label):
                    return True
        except Exception:
            continue
    if found_selector:
        return False
    # Selector IDs varían entre versiones. Detecta etiquetas localizadas en
    # el formulario de alarma sin tocar controles fuera de esa ventana.
    try:
        descendants = win.descendants()
    except Exception:
        descendants = []
    wanted = {value.casefold() for value in synonyms}
    period_controls = [
        item for item in descendants
        if (item.window_text() or "").strip().casefold() in wanted
    ]
    if period_controls:
        try:
            period_controls[0].click_input()
            return True
        except Exception:
            return False
    return None


def _entry_confirma_hora(texto: str, hora: int, minuto: int) -> bool:
    """Comprueba la hora mostrada, tolerando formato de 12 o 24 horas."""
    texto = str(texto or "")
    coincidencias = re.findall(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)", texto)
    if not coincidencias:
        return False
    normalizado = texto.casefold()
    es_pm = bool(re.search(r"\bpm\b|p\s*\.\s*m\.?", normalizado))
    es_am = bool(re.search(r"\bam\b|a\s*\.\s*m\.?", normalizado))
    for hora_texto, minuto_texto in coincidencias:
        h, m = int(hora_texto), int(minuto_texto)
        if m != minuto:
            continue
        if es_pm:
            if (h % 12) + 12 == hora:
                return True
        elif es_am:
            if (h % 12) == hora % 12 and hora < 12:
                return True
        elif h == hora:
            return True
    return False


def crear_alarma(hora: int, minuto: int, nombre: str, repetir: str | None = None) -> dict[str, Any]:
    """Crea y verifica una alarma; saved distingue un guardado incierto."""
    if not (0 <= hora <= 23 and 0 <= minuto <= 59):
        return {"ok": False, "saved": False, "error": "La hora no es válida."}

    saved_clicked = False
    try:
        win = _window()
        win.set_focus()
        if not _abrir_vista_alarmas(win):
            raise ClockAutomationError("No pude abrir la vista de alarmas de Reloj.")
        _control(
            win,
            "AddAlarmButton",
            ("Add alarm", "Add new alarm", "New alarm", "Agregar alarma", "Nueva alarma", "Crear alarma"),
            ("Button",),
        ).click_input()

        name_box = _control(
            win,
            "AlarmNameTextBox",
            ("Alarm name", "Name", "Nombre de alarma", "Nombre"),
            ("Edit", "TextBox"),
            allow_unique_edit=True,
        )
        try:
            name_box.set_edit_text(nombre)
        except Exception:
            name_box.click_input()
            name_box.type_keys("^a{BACKSPACE}")
            name_box.type_keys(nombre, with_spaces=True)

        hora_12h = 12 if hora in (0, 12) else (hora - 12 if hora > 12 else hora)
        horas = tuple(dict.fromkeys((str(hora), f"{hora:02d}", str(hora_12h), f"{hora_12h:02d}")))
        if not any(_set_wheel(win, "HourLoopingSelector", value, ("Hour", "Hora")) for value in horas):
            raise ClockAutomationError("No pude seleccionar la hora en Reloj.")
        minutos = (f"{minuto:02d}", str(minuto))
        if not any(_set_wheel(win, "MinuteLoopingSelector", value, ("Minute", "Minutes", "Minuto", "Minutos")) for value in minutos):
            raise ClockAutomationError("No pude seleccionar los minutos en Reloj.")

        # Los controles AM/PM solo existen cuando Windows usa formato de 12 h.
        periodo = _select_period(win, "PM" if hora >= 12 else "AM")
        if periodo is False:
            raise ClockAutomationError("No pude confirmar AM/PM en Reloj.")

        if repetir and not _configurar_repeticion(win, repetir):
            raise ClockAutomationError(f"No pude seleccionar los días de repetición ({repetir}).")

        _control(win, "AlarmSaveButton", ("Save", "Guardar"), ("Button",)).click_input()
        saved_clicked = True
        time.sleep(1.2)
        expected = nombre.casefold()
        entries = win.descendants(control_type="ListItem")
        match = next((entry for entry in entries
                      if expected in (entry.window_text() or "").casefold()), None)
        if match is None:
            return {"ok": False, "saved": True, "error": "Reloj aceptó guardar, pero no pude confirmar la alarma en la lista."}
        if not _entry_confirma_hora(match.window_text(), hora, minuto):
            return {"ok": False, "saved": True, "error": "Reloj muestra la alarma, pero no pude confirmar su hora."}
        return {"ok": True, "saved": True, "error": ""}
    except Exception as exc:
        if not saved_clicked:
            try:
                win = locals().get("win")
                if win:
                    for cancel_id in ("CancelButton", "AlarmCancelButton"):
                        try:
                            _control(win, cancel_id).click_input()
                            break
                        except Exception:
                            continue
            except Exception:
                pass
        error = str(exc) or "Falló la automatización de Reloj."
        diagnostic_win = locals().get("win")
        if diagnostic_win is not None:
            controls = _diagnostico_controles(diagnostic_win)
            if controls:
                print(f"[Reloj Windows UIA] {controls}")
        return {"ok": False, "saved": saved_clicked, "error": error}


def eliminar_alarma(nombre: str) -> dict[str, Any]:
    """Elimina solo una alarma cuya etiqueta contiene el identificador único."""
    try:
        win = _window()
        win.set_focus()
        _abrir_vista_alarmas(win)
        entry = next((item for item in win.descendants(control_type="ListItem")
                      if nombre.casefold() in (item.window_text() or "").casefold()), None)
        if entry is None:
            return {"ok": False, "error": "No encontré esa alarma dentro de Reloj."}

        deleted = False
        try:
            entry.click_input()
            time.sleep(0.3)
        except Exception:
            pass
        for automation_id in ("AlarmDeleteButton", "DeleteAlarmButton"):
            try:
                _control(win, automation_id).click_input()
                deleted = True
                break
            except Exception:
                continue
        if not deleted:
            entry.click_input(button="right")
            for label in ("Delete", "Eliminar"):
                try:
                    item = win.child_window(title=label, control_type="MenuItem")
                    if item.exists(timeout=1):
                        item.click_input()
                        deleted = True
                        break
                except Exception:
                    continue
        if not deleted:
            return {"ok": False, "error": "Reloj no mostró la opción para eliminar."}

        time.sleep(0.5)
        remains = any(nombre.casefold() in (item.window_text() or "").casefold()
                      for item in win.descendants(control_type="ListItem"))
        if remains:
            return {"ok": False, "error": "No pude confirmar que Reloj eliminara la alarma."}
        return {"ok": True, "error": ""}
    except Exception as exc:
        return {"ok": False, "error": str(exc) or "Falló la automatización de Reloj."}
