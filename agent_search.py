# =============================================================================
# agent_search.py — Agente de Búsqueda de Información
# =============================================================================
# Responsabilidades:
#   · Búsqueda web con Gemini + Google Search grounding
#   · Respuestas de conocimiento general con Groq (Llama 3.3 70B)
#   · Noticias (NewsAPI + Google News RSS)
#   · Clima (Open-Meteo, gratuito sin API key)
#   · Cálculo matemático (eval seguro + Claude API para física avanzada)
#   · Apertura de Google Maps para rutas/lugares
#
# Interfaz pública:
#   ejecutar(accion, params, chat_widget) -> bool
#   buscar_web(pregunta, termino_imagen, chat_widget) -> bool
#   obtener_noticias(tema, categoria, chat_widget)
#   obtener_clima(ciudad, chat_widget)
#   calcular_expresion(comando, chat_widget) -> bool
#
# Dependencias inyectadas via init(ctx):
#   hablar, cola_voz, bridge, html_burbuja, html_burbuja_jarvis,
#   markdown_a_html, latex_a_html, limpiar_html,
#   KEYS_LISTAS, groq_keys, groq_key_activa, groq_rotar_key,
#   gemini_key_activa, GROQ_BASE_URL, GROQ_MODEL,
#   NEWS_API_KEY, GOOGLE_SEARCH_API_KEY, GOOGLE_SEARCH_CX,
#   ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL, ANTHROPIC_MODEL,
#   historial, agregar_historial, formatear_historial,
#   groq_tokens, guardar_tokens, memoria_usuario, guardar_memoria,
#   patrones, config,
#
# NOTA: Las imágenes se movieron a agent_images.py
# =============================================================================

from __future__ import annotations

import html
import html as _html
import json
import os
import re
import time
import webbrowser
from urllib.parse import quote as _url_quote, urlparse

import requests
import idiomas

# =============================================================================
# CONTEXTO INYECTADO
# =============================================================================

_ctx: dict = {}


def init(ctx: dict):
    """
    Inyecta el contexto compartido del monolito principal.
    Llamar UNA VEZ desde main.py antes de usar cualquier función.

    Ejemplo:
        import agent_search
        agent_search.init({
            "hablar":              hablar,
            "cola_voz":            _cola_voz,
            "bridge":              _bridge,
            "html_burbuja":        _html_burbuja,
            "html_burbuja_jarvis": _html_burbuja_jarvis,
            "markdown_a_html":     _markdown_a_html,
            "latex_a_html":        _latex_a_html,
            "limpiar_html":        _limpiar_html,
            "KEYS_LISTAS":         _KEYS_LISTAS,
            "groq_keys":           lambda: _groq_keys,
            "groq_key_activa":     _groq_key_activa,
            "groq_rotar_key":      _groq_rotar_key,
            "gemini_key_activa":   _gemini_key_activa,
            "gemini_rotar_key":    _gemini_rotar_key,
            "GROQ_BASE_URL":       GROQ_BASE_URL,
            "GROQ_MODEL":          GROQ_MODEL,
            "GROQ_MODELOS_FALLBACK": GROQ_MODELOS_FALLBACK,
            "groq_tokens":         _groq_tokens,
            "guardar_tokens":      _guardar_tokens,
            "historial":           lambda: _historial,
            "agregar_historial":   _agregar_historial,
            "formatear_historial": _formatear_historial,
            "memoria_usuario":     memoria_usuario,
            "guardar_memoria":     _guardar_memoria,
            "patrones":            _patrones,
            "config":              config,
            "NEWS_API_KEY":        lambda: NEWS_API_KEY,
            "GOOGLE_SEARCH_API_KEY": lambda: GOOGLE_SEARCH_API_KEY,
            "GOOGLE_SEARCH_CX":    lambda: GOOGLE_SEARCH_CX,
            "ANTHROPIC_API_KEY":   lambda: ANTHROPIC_API_KEY,
            "ANTHROPIC_BASE_URL":  ANTHROPIC_BASE_URL,
            "ANTHROPIC_MODEL":     ANTHROPIC_MODEL,
        })
    """
    global _ctx
    _ctx = ctx


# =============================================================================
# HELPERS DE ACCESO AL CONTEXTO
# =============================================================================

def _debe_incluir_fuentes_apa(pregunta: str) -> bool:
    texto = re.sub(r'\s+', ' ', str(pregunta or '').lower()).strip()
    return any(k in texto for k in ["apa 7", "apa7", "apa", "fuentes", "referencias", "bibliografía", "bibliografia", "citar", "citas", "cita"])


def _extraer_urls(texto: str) -> list[str]:
    if not texto:
        return []
    urls = []
    for match in re.finditer(r'https?://[^\s<>"]+', texto):
        url = match.group(0).rstrip(').,;:')
        if url not in urls:
            urls.append(url)
    return urls


def _extraer_titulo_desde_url(url: str) -> str:
    try:
        resp = requests.get(url, timeout=8, headers={"User-Agent": "Jarvis/5.4"})
        if resp.status_code != 200:
            raise Exception
        text = resp.text
        for pat in [
            r'<title[^>]*>(.*?)</title>',
            r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\'](.*?)["\']',
            r'<meta[^>]+name=["\']title["\'][^>]+content=["\'](.*?)["\']',
        ]:
            m = re.search(pat, text, re.IGNORECASE | re.DOTALL)
            if m:
                title = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', m.group(1))).strip()
                if title:
                    return title
    except Exception:
        pass
    parsed = urlparse(url)
    host = parsed.netloc.replace("www.", "")
    path = parsed.path.rstrip("/")
    slug = os.path.basename(path)
    if slug and slug.lower() not in {"index", "home", "main", "default"}:
        title = re.sub(r'[-_]+', ' ', slug).strip()
        return " ".join(part.capitalize() for part in title.split()) if title else host
    return host.split(".")[0].replace("-", " ").title() if host else "Sitio web"


def _formatear_referencias_apa7(texto: str, pregunta: str) -> str:
    urls = _extraer_urls(texto)
    if not _debe_incluir_fuentes_apa(pregunta):
        return ""
    # Si no hay URLs, devolver ejemplos provisionales en formato APA 7 para orientar al usuario
    if not urls:
        examples = [
            "Autor, A. A. (Año). Título del artículo. Nombre de la revista o sitio. https://ejemplo.org/ejemplo",
            "Institución X. (Año). Informe sobre la especie. https://ejemplo.org/informe",
            "Autor, B. B. (Año). Título del recurso en línea. https://ejemplo.org/recurso",
        ]
        items = [f"<li>{html.escape(e)}</li>" for e in examples]
        return (
            "<p><b>Referencias APA 7 (provisionales):</b></p>"
            f"<ol>{''.join(items)}</ol>"
            "<p style='color:#8fb8e0;font-size:11px;'>Si compartes el título, el autor y el año exacto de cada fuente, las convierto a referencias APA 7 más precisas.</p>"
        )
    items = []
    for url in urls[:6]:
        parsed = urlparse(url)
        host = parsed.netloc.replace("www.", "")
        title = _extraer_titulo_desde_url(url)
        sitio = host.split(".")[0].replace("-", " ").title() if host else "Sitio web"
        items.append(f"<li>{html.escape(sitio)}. (s. f.). {html.escape(title)}. {html.escape(url)}</li>")
    if not items:
        return ""
    return (
        "<p><b>Referencias APA 7 (provisionales):</b></p>"
        f"<ol>{''.join(items)}</ol>"
        "<p style='color:#8fb8e0;font-size:11px;'>Si compartes el título, el autor y el año exacto de cada fuente, las convierto a referencias APA 7 más precisas.</p>"
    )


def _postprocesar_respuesta_investigacion(html_respuesta: str, pregunta: str) -> str:
    if not html_respuesta:
        return html_respuesta
    texto = html_respuesta.strip()
    if _debe_incluir_fuentes_apa(pregunta):
        if re.search(r'no (puedo|soy capaz|puedo dar|puedo proporcionar|puedo ofrecer).*(citar|cita|fuentes|referencias|bibliograf)', texto, re.IGNORECASE):
            texto = re.sub(r'<p[^>]*>.*?(?:no (?:puedo|soy capaz|puedo dar|puedo proporcionar|puedo ofrecer).*(?:citar|cita|fuentes|referencias|bibliograf))[^<]*</p>', '', texto, flags=re.IGNORECASE | re.DOTALL)
            texto = texto.strip()
            if not texto:
                texto = "<p>Puedo ayudarte a construir referencias APA 7 con un formato claro y usable.</p>"
        refs_html = _formatear_referencias_apa7(texto, pregunta)
        if refs_html:
            if re.search(r'<(p|ol|ul|table)\b', texto, re.IGNORECASE):
                texto = f"{texto}<br>{refs_html}"
            else:
                texto = f"<p>{texto}</p><br>{refs_html}"
        elif re.search(r'no (puedo|soy capaz|puedo dar|puedo proporcionar|puedo ofrecer).*(citar|cita|fuentes|referencias|bibliograf)', texto, re.IGNORECASE):
            texto = f"{texto}<p><b>Formato APA 7 base:</b> Autor, A. A. (Año). <i>Título</i>. Editorial o sitio web.</p>"
    return texto


def _hablar(texto, chat_widget=None):
    _ctx["hablar"](texto, chat_widget)

def _bridge_html(html):
    _ctx["bridge"].append_html.emit(html)

def _bridge_scroll():
    _ctx["bridge"].scroll_down.emit()

def _burbuja(html):
    return _ctx["html_burbuja"](html)

def _burbuja_jarvis(html):
    return _ctx["html_burbuja_jarvis"](html)

def _markdown(txt):
    return _ctx["markdown_a_html"](txt)

def _latex(txt):
    return _ctx["latex_a_html"](txt)

def _limpiar(txt):
    return _ctx["limpiar_html"](txt)

def _detectar_idioma(texto: str) -> tuple[str, str]:
    """Detect language using langid's broad offline model; retain a short-text fallback."""
    plano = re.sub(r"<[^>]+>|https?://\S+|\[[^\]]*\]\([^)]*\)", " ", str(texto or ""))
    code = idiomas.detect_language(plano, fallback="")
    return code, idiomas.language_name(code) if code else "idioma del usuario"

def _asegurar_respuesta_idioma(texto: str, pregunta: str = "", idioma_destino: str = "") -> str:
    """Translate a response when it misses the selected or detected reply language."""
    if not texto:
        return texto
    setting = idioma_destino or _ctx.get("idioma_respuesta")
    destino = setting() if callable(setting) else setting
    if destino in {None, "", "auto"}:
        destino, destino_label = _detectar_idioma(pregunta)
    else:
        destino = idiomas.normalize_language(destino)
        destino_label = idiomas.language_name(destino)
    origen, _ = _detectar_idioma(texto)
    if not destino or not origen or destino == origen:
        return texto
    original = texto

    protegidos = {}
    def proteger(valor: str) -> str:
        clave = f"JARVISKEEP{len(protegidos)}TOKEN"
        protegidos[clave] = valor
        return clave

    # Mantener intactos enlaces Markdown, HTML y direcciones web.
    texto = re.sub(r"\[[^\]]*\]\(https?://[^)]+\)", lambda m: proteger(m.group(0)), texto)
    texto = re.sub(r"https?://\S+", lambda m: proteger(m.group(0)), texto)
    texto = re.sub(r"</?[a-zA-Z][^>]*>", lambda m: proteger(m.group(0)), texto)

    # Mantener títulos propios que aparezcan en la pregunta aunque tengan dos puntos en la respuesta.
    titulos = re.findall(r"\b[A-ZÁÉÍÓÚÑ][\w’'-]*(?:\s+[A-ZÁÉÍÓÚÑ][\w’'-]*)+", str(pregunta or ""))
    for titulo in sorted(titulos, key=len, reverse=True):
        partes = re.findall(r"[\w]+(?:-[\w]+)*", titulo)
        if len(partes) < 2:
            continue
        patron = r"(?i)\b" + r"[\s:–—-]+".join(re.escape(p) for p in partes) + r"\b"
        texto = re.sub(patron, lambda m: proteger(m.group(0)), texto)

    traducido = _traducir_con_google(texto, destino)
    if not traducido:
        traducido = _traducir_con_groq(texto, "detectado automáticamente", destino_label)
    if not traducido:
        traducir_modelo = _ctx.get("traducir_respuesta_modelo")
        if callable(traducir_modelo):
            try:
                traducido = traducir_modelo(texto, destino_label)
            except Exception as exc:
                print(f"[BuscarWeb] Traducción con el modelo local/remoto falló: {exc}")
    if not traducido:
        print(f"[BuscarWeb] No se pudo traducir la respuesta al idioma detectado ({destino_label}).")
        return original
    # Restaurar al revés por si un marcador (como una URL) quedó dentro de una etiqueta HTML protegida.
    for clave, valor in reversed(list(protegidos.items())):
        traducido = traducido.replace(clave, valor)
    return traducido

def _groq_key():
    return _ctx["groq_key_activa"]()

def _rotar_groq(motivo=""):
    _ctx["groq_rotar_key"](motivo)

def _gemini_key():
    return _ctx["gemini_key_activa"]()

def _memoria():
    return _ctx["memoria_usuario"]

def _historial_actual():
    return _ctx["historial"]()

def _fmt_historial(pregunta=""):
    return _ctx["formatear_historial"](pregunta)

def _cola_voz():
    return _ctx["cola_voz"]

def _log_historial_jarvis(texto: str):
    """Registra la respuesta de Jarvis en el historial para memoria conversacional."""
    fn = _ctx.get("agregar_historial")
    if fn and texto:
        try:
            limpio = re.sub(r'<[^>]+>', ' ', texto).strip()
            fn("jarvis", limpio[:300])
        except Exception:
            pass


# =============================================================================
# 1. MÓDULO DE NOTICIAS
# =============================================================================

_CATEGORIAS_NEWS = {
    "tecnologia": "technology", "tecnología": "technology",
    "deportes": "sports",       "deporte": "sports",
    "ciencia": "science",
    "salud": "health",
    "negocios": "business",     "economia": "business", "economía": "business",
    "entretenimiento": "entertainment",
    "politica": "general",      "política": "general",
}


def _noticias_rss(tema: str = "", idioma: str = "es", pais: str = "co") -> list:
    """Noticias via Google News RSS (sin API key)."""
    try:
        import xml.etree.ElementTree as _ET
        if tema:
            url = (
                f"https://news.google.com/rss/search"
                f"?q={_url_quote(tema)}&hl={idioma}&gl={pais.upper()}&ceid={pais.upper()}:{idioma}"
            )
        else:
            url = (
                f"https://news.google.com/rss"
                f"?hl={idioma}&gl={pais.upper()}&ceid={pais.upper()}:{idioma}"
            )
        r = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return []
        root  = _ET.fromstring(r.content)
        items = root.findall(".//item")[:6]
        noticias = []
        for item in items:
            titulo = item.findtext("title", "").strip()
            link   = item.findtext("link",  "").strip()
            fecha  = item.findtext("pubDate", "").strip()
            if " - " in titulo:
                titulo, fuente = titulo.rsplit(" - ", 1)
            else:
                fuente = ""
            noticias.append({
                "titulo": titulo.strip(),
                "fuente": fuente.strip(),
                "url":    link,
                "fecha":  fecha,
            })
        return noticias
    except Exception as e:
        print(f"[Noticias RSS] {e}")
        return []


def _noticias_api(tema: str = "", categoria: str = "", pais: str = "co") -> list:
    """Noticias via NewsAPI (requiere NEWS_API_KEY)."""
    key = _ctx["NEWS_API_KEY"]()
    if not key:
        return []
    try:
        if tema:
            url = (
                f"https://newsapi.org/v2/everything"
                f"?q={_url_quote(tema)}&language=es&sortBy=publishedAt&pageSize=6&apiKey={key}"
            )
        else:
            cat = _CATEGORIAS_NEWS.get(categoria.lower(), "general") if categoria else "general"
            url = (
                f"https://newsapi.org/v2/top-headlines"
                f"?country={pais}&category={cat}&pageSize=6&apiKey={key}"
            )
        r = requests.get(url, timeout=8)
        if r.status_code != 200:
            return []
        noticias = []
        for art in r.json().get("articles", [])[:6]:
            noticias.append({
                "titulo": art.get("title", "").split(" - ")[0].strip(),
                "fuente": art.get("source", {}).get("name", ""),
                "url":    art.get("url", ""),
                "fecha":  art.get("publishedAt", "")[:10],
            })
        return noticias
    except Exception as e:
        print(f"[Noticias API] {e}")
        return []


def obtener_noticias(tema: str = "", categoria: str = "", chat_widget=None):
    """Muestra noticias en el chat. Usa NewsAPI si hay key, sino RSS."""
    _hablar("Buscando noticias...", chat_widget)
    key = _ctx["NEWS_API_KEY"]()
    if key:
        noticias = _noticias_api(tema, categoria)
        if not noticias:
            noticias = _noticias_rss(tema)
    else:
        noticias = _noticias_rss(tema)

    if not noticias:
        _hablar("No pude obtener noticias en este momento.", chat_widget)
        return

    etiqueta     = f"sobre '{tema}'" if tema else (f"de {categoria}" if categoria else "más recientes")
    fuente_label = "Google News RSS + NewsAPI" if key else "Google News RSS"
    filas = ""
    for n in noticias:
        url_safe     = n["url"].replace('"', '%22')
        fuente_fecha = n["fuente"] + (" · " + n["fecha"] if n["fecha"] else "")
        filas += (
            f'<tr><td style="padding:6px 0;border-bottom:1px solid #1e2d45;vertical-align:top;">'
            f'<a href="{url_safe}" style="color:#4db8ff;text-decoration:none;font-size:14px;">'
            f'{n["titulo"]}</a>'
            f'<br><span style="color:#8899bb;font-size:12px;">{fuente_fecha}</span>'
            f'</td></tr>'
        )
    html = (
        f'<b>📰 Noticias {etiqueta}:</b><br><br>'
        f'<table width="100%" cellspacing="0" cellpadding="0">{filas}</table>'
        f'<br><span style="color:#556677;font-size:11px;">Fuente: {fuente_label}</span>'
    )
    _bridge_html(_burbuja(html))
    _bridge_scroll()
    titulos_voz = ". ".join(n["titulo"] for n in noticias[:2])
    _cola_voz().put(f"Noticias {etiqueta}: {titulos_voz}")
    _log_historial_jarvis("Noticias " + etiqueta + ": " + "; ".join(n["titulo"] for n in noticias[:4]))


# =============================================================================
# 2. MÓDULO DE CLIMA
# =============================================================================

def obtener_clima(ciudad: str = "Bogotá", chat_widget=None, dia: str = "hoy"):
    """
    Clima usando Open-Meteo (geocodificación + forecast).
    Completamente gratuito, sin API key.
    """
    _hablar(f"Consultando el clima en {ciudad}...", chat_widget)
    try:
        # Paso 1: geocodificar ciudad
        geo_url = (
            f"https://geocoding-api.open-meteo.com/v1/search"
            f"?name={_url_quote(ciudad)}&count=1&language=es&format=json"
        )
        geo_r = requests.get(geo_url, timeout=8)
        if geo_r.status_code != 200 or not geo_r.json().get("results"):
            _hablar(f"No encontré la ciudad {ciudad}.", chat_widget)
            return

        lugar  = geo_r.json()["results"][0]
        lat    = lugar["latitude"]
        lon    = lugar["longitude"]
        nombre = lugar.get("name", ciudad)
        pais   = lugar.get("country", "")

        # Reutilizar OAuth de Google; no hace falta configurar una clave
        # independiente para Weather. Para "hoy" se consulta condiciones
        # actuales, no el tramo diurno del pronóstico (que puede diferir del móvil).
        weather_credentials_getter = _ctx.get("GOOGLE_WEATHER_CREDENTIALS")
        weather_credentials = weather_credentials_getter() if callable(weather_credentials_getter) else None
        if weather_credentials and weather_credentials.token:
            try:
                es_manana = str(dia).lower().startswith(("mañ", "man"))
                if not es_manana:
                    actual_r = requests.get(
                        "https://weather.googleapis.com/v1/currentConditions:lookup",
                        params={
                            "location.latitude": lat,
                            "location.longitude": lon,
                            "unitsSystem": "METRIC",
                            "languageCode": "es",
                        },
                        headers={"Authorization": f"Bearer {weather_credentials.token}"},
                        timeout=12,
                    )
                    if actual_r.status_code == 200:
                        actual = actual_r.json()
                        condicion_actual = actual.get("weatherCondition", {}).get("description", {}).get("text", "Sin descripción")
                        temperatura = actual.get("temperature", {}).get("degrees", "?")
                        sensacion = actual.get("feelsLikeTemperature", {}).get("degrees", "?")
                        humedad_actual = actual.get("relativeHumidity", "?")
                        viento_actual = actual.get("wind", {}).get("speed", {}).get("value", "?")
                        lluvia_actual = actual.get("precipitation", {}).get("probability", {}).get("percent", "?")
                        hora_actual = actual.get("currentTime", "")
                        html_actual = (
                            f'<b>🌡 Clima actual en { _html.escape(nombre)}, { _html.escape(pais)}</b><br><br>'
                            f'<table cellspacing="0" cellpadding="0" style="border-collapse:collapse;">'
                            f'<tr><td style="padding:4px 12px 4px 0;color:#8899bb;">Condición</td><td style="color:#dde6f5;">{_html.escape(str(condicion_actual))}</td></tr>'
                            f'<tr><td style="padding:4px 12px 4px 0;color:#8899bb;">Temperatura</td><td style="color:#dde6f5;"><b>{temperatura} °C</b> · sensación {sensacion} °C</td></tr>'
                            f'<tr><td style="padding:4px 12px 4px 0;color:#8899bb;">Humedad</td><td style="color:#dde6f5;">{humedad_actual}%</td></tr>'
                            f'<tr><td style="padding:4px 12px 4px 0;color:#8899bb;">Viento</td><td style="color:#dde6f5;">{viento_actual} km/h</td></tr>'
                            f'<tr><td style="padding:4px 12px 4px 0;color:#8899bb;">Prob. lluvia</td><td style="color:#dde6f5;">{lluvia_actual}%</td></tr>'
                            f'</table><br><span style="color:#556677;font-size:11px;">📡 Google Weather · actualizado { _html.escape(str(hora_actual))}</span>'
                        )
                        _bridge_html(_burbuja(html_actual))
                        _bridge_scroll()
                        _hablar(f"El clima actual en {nombre}: {condicion_actual}, {temperatura} grados, sensación de {sensacion}, humedad del {humedad_actual} por ciento.", chat_widget)
                        _log_historial_jarvis(f"Clima actual Google Weather en {nombre}, {pais}: {condicion_actual}, {temperatura}°C.")
                        return
                    print(f"[Google Weather actual] HTTP {actual_r.status_code}: {actual_r.text[:220]}; usaré el pronóstico")

                google_r = requests.get(
                    "https://weather.googleapis.com/v1/forecast/days:lookup",
                    params={
                        "location.latitude": lat,
                        "location.longitude": lon,
                        "days": 2,
                        "languageCode": "es",
                    },
                    headers={"Authorization": f"Bearer {weather_credentials.token}"},
                    timeout=12,
                )
                if google_r.status_code == 200:
                    dias = google_r.json().get("forecastDays", [])
                    indice_google = 1 if es_manana else 0
                    if len(dias) > indice_google:
                        prediccion = dias[indice_google]
                        tramo = prediccion.get("daytimeForecast", {})
                        condicion = tramo.get("weatherCondition", {}).get("description", {}).get("text", "Sin descripción")
                        maximo = prediccion.get("maxTemperature", {}).get("degrees", "?")
                        minimo = prediccion.get("minTemperature", {}).get("degrees", "?")
                        humedad_google = tramo.get("relativeHumidity", "?")
                        lluvia_google = tramo.get("precipitation", {}).get("probability", {}).get("percent", "?")
                        viento_google = tramo.get("wind", {}).get("speed", {}).get("value", "?")
                        dia_texto_google = "mañana" if indice_google else "hoy"
                        html_google = (
                            f'<b>🌡 Pronóstico para {dia_texto_google} en {nombre}, {pais}</b><br><br>'
                            f'<table cellspacing="0" cellpadding="0" style="border-collapse:collapse;">'
                            f'<tr><td style="padding:4px 12px 4px 0;color:#8899bb;">Condición</td><td style="color:#dde6f5;">{_html.escape(str(condicion))}</td></tr>'
                            f'<tr><td style="padding:4px 12px 4px 0;color:#8899bb;">Temperatura</td><td style="color:#dde6f5;"><b>{maximo}°C máx.</b> · {minimo}°C mín.</td></tr>'
                            f'<tr><td style="padding:4px 12px 4px 0;color:#8899bb;">Humedad</td><td style="color:#dde6f5;">{humedad_google}%</td></tr>'
                            f'<tr><td style="padding:4px 12px 4px 0;color:#8899bb;">Viento</td><td style="color:#dde6f5;">{viento_google} km/h</td></tr>'
                            f'<tr><td style="padding:4px 12px 4px 0;color:#8899bb;">Prob. lluvia</td><td style="color:#dde6f5;">{lluvia_google}%</td></tr>'
                            f'</table><br><span style="color:#556677;font-size:11px;">📡 Google Weather</span>'
                        )
                        _bridge_html(_burbuja(html_google))
                        _bridge_scroll()
                        _hablar(f"El pronóstico de Google Weather para {dia_texto_google} en {nombre}: {condicion}, máxima de {maximo} y mínima de {minimo} grados.", chat_widget)
                        _log_historial_jarvis(f"Clima de Google Weather en {nombre}, {pais}: {condicion}, máxima {maximo}°C y mínima {minimo}°C.")
                        return
                else:
                    print(f"[Google Weather] HTTP {google_r.status_code}: {google_r.text[:220]}; usaré respaldo")
            except Exception as google_exc:
                print(f"[Google Weather] {google_exc}; usaré respaldo")

        # Paso 2: pronóstico actual
        meteo_url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,relative_humidity_2m,weathercode,windspeed_10m"
            f"&daily=weathercode,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
            f"&timezone=auto&forecast_days=2"
        )
        met_r = requests.get(meteo_url, timeout=8)
        if met_r.status_code != 200:
            _hablar("No pude obtener el clima en este momento.", chat_widget)
            return

        data    = met_r.json()
        current = data.get("current", {})
        daily   = data.get("daily", {})

        indice_dia = 1 if str(dia).lower().startswith("mañ") else 0
        dia_texto = "mañana" if indice_dia else "hoy"
        temp    = current.get("temperature_2m", "?") if indice_dia == 0 else "—"
        humedad = current.get("relative_humidity_2m", "?")
        viento  = current.get("windspeed_10m", "?")
        wcode   = current.get("weathercode", 0)
        t_max   = daily.get("temperature_2m_max", ["?", "?"])[indice_dia]
        t_min   = daily.get("temperature_2m_min", ["?", "?"])[indice_dia]
        lluvia  = daily.get("precipitation_probability_max", [0, 0])[indice_dia]

        _WCODE = {
            0: "Despejado ☀️",             1: "Principalmente despejado 🌤",
            2: "Parcialmente nublado ⛅",   3: "Nublado ☁️",
            45: "Niebla 🌫",               48: "Niebla helada 🌫",
            51: "Llovizna leve 🌦",         53: "Llovizna moderada 🌧",
            55: "Llovizna intensa 🌧",      61: "Lluvia leve 🌧",
            63: "Lluvia moderada 🌧",       65: "Lluvia intensa 🌧",
            71: "Nieve leve 🌨",            73: "Nieve moderada 🌨",
            75: "Nieve intensa 🌨",         80: "Chubascos 🌦",
            81: "Chubascos moderados 🌦",   82: "Chubascos fuertes 🌦",
            95: "Tormenta ⛈",              96: "Tormenta con granizo ⛈",
        }
        wcode_dia = daily.get("weathercode", [wcode, wcode])
        codigo_dia = wcode_dia[indice_dia] if len(wcode_dia) > indice_dia else wcode
        descripcion = _WCODE.get(codigo_dia, f"Código {codigo_dia}")

        html = (
            f'<b>🌡 Pronóstico para {dia_texto} en {nombre}, {pais}</b><br><br>'
            f'<table cellspacing="0" cellpadding="0" style="border-collapse:collapse;">'
            f'<tr><td style="padding:4px 12px 4px 0;color:#8899bb;">Condición</td>'
            f'<td style="color:#dde6f5;">{descripcion}</td></tr>'
            f'<tr><td style="padding:4px 12px 4px 0;color:#8899bb;">Temperatura</td>'
            f'<td style="color:#dde6f5;"><b>{temp}°C</b> (máx {t_max}° · mín {t_min}°)</td></tr>'
            f'<tr><td style="padding:4px 12px 4px 0;color:#8899bb;">Humedad</td>'
            f'<td style="color:#dde6f5;">{humedad}%</td></tr>'
            f'<tr><td style="padding:4px 12px 4px 0;color:#8899bb;">Viento</td>'
            f'<td style="color:#dde6f5;">{viento} km/h</td></tr>'
            f'<tr><td style="padding:4px 12px 4px 0;color:#8899bb;">Prob. lluvia</td>'
            f'<td style="color:#dde6f5;">{lluvia}%</td></tr>'
            f'</table>'
            f'<br><span style="color:#556677;font-size:11px;">📡 Open-Meteo</span>'
        )
        _bridge_html(_burbuja(html))
        _bridge_scroll()

        consejo = " Lleva paraguas." if lluvia and int(lluvia) >= 60 else ""
        _hablar(f"El pronóstico para {dia_texto} en {nombre}: {descripcion.split()[0]}, máxima de {t_max} y mínima de {t_min} grados.{consejo}", chat_widget)
        _log_historial_jarvis(f"Clima en {nombre}, {pais}: {descripcion}, {temp}°C, humedad {humedad}%.")

    except Exception as e:
        print(f"[Clima] {e}")
        _hablar("No pude obtener el clima. Revisa tu conexión.", chat_widget)


# =============================================================================
# 3. CÁLCULO MATEMÁTICO
# =============================================================================

def _llamar_claude_api(system_prompt: str, user_message: str, max_tokens: int = 2048) -> str:
    """Llama a la API de Anthropic directamente."""
    key = _ctx["ANTHROPIC_API_KEY"]()
    if not key:
        return ""
    try:
        resp = requests.post(
            _ctx["ANTHROPIC_BASE_URL"],
            json={
                "model":      _ctx["ANTHROPIC_MODEL"],
                "max_tokens": max_tokens,
                "system":     system_prompt,
                "messages":   [{"role": "user", "content": user_message}],
            },
            headers={
                "x-api-key":         key,
                "anthropic-version": "2023-06-01",
                "content-type":      "application/json",
            },
            timeout=30,
        )
        if resp.status_code == 200:
            return resp.json()["content"][0]["text"].strip()
        print(f"[Claude API] Error {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        print(f"[Claude API] {e}")
    return ""


def _calcular_con_claude(comando: str, chat_widget=None) -> bool:
    """Física / matemática avanzada vía Claude API con LaTeX."""
    _hablar("Calculando...", chat_widget)
    system = (
        "Eres un experto en física analítica y matemática universitaria. "
        "Resuelve el ejercicio con rigor total, paso a paso y responde en el mismo idioma de la petición. "
        "Usa LaTeX para TODAS las expresiones matemáticas: "
        "inline con \\(...\\) y en bloque con \\[...\\]. "
        "Responde en el mismo idioma del mensaje del usuario. Sé conciso pero completo. "
        "NUNCA cometas errores matemáticos. Verifica cada paso antes de escribirlo. "
        "Usa HTML para estructura: <h4> para secciones, <p> para texto, <b> para énfasis. "
        "NO uses markdown. Solo HTML + LaTeX."
    )
    respuesta = _llamar_claude_api(system, comando, max_tokens=3000)
    if respuesta:
        html_final = _latex(respuesta)
        _bridge_html(_burbuja(html_final))
        _bridge_scroll()
        texto_voz = re.sub(r'<[^>]+>', ' ', respuesta)
        texto_voz = re.sub(r'\\\(.*?\\\)', '', texto_voz, flags=re.DOTALL)
        texto_voz = re.sub(r'\\\[.*?\\\]', '', texto_voz, flags=re.DOTALL)
        texto_voz = re.sub(r'\s+', ' ', texto_voz).strip()
        if texto_voz:
            _cola_voz().put(texto_voz[:400])
        return True
    _hablar("No pude calcular eso. Intenta reformular la pregunta.", chat_widget)
    return True


def calcular_expresion(comando: str, chat_widget=None) -> bool:
    """
    Interpreta cálculos matemáticos y estimaciones de viaje.
    Cálculos simples → eval Python seguro.
    Física/matemática avanzada → Claude API.
    Devuelve True si procesó la petición, False si no aplica.
    """
    import math as _math  # noqa: F401

    _KEYWORDS_AVANZADO = [
        'lagrangian', 'lagrangiano', 'hamiltoniano', 'euler-lagrange',
        'energia cinetica', 'energía cinética', 'energía potencial',
        'momento angular', 'momento lineal', 'torque', 'tension',
        'ecuacion de movimiento', 'ecuación de movimiento',
        'doble pendulo', 'doble péndulo', 'péndulo', 'pendulo',
        'masa-resorte', 'oscilador', 'derivada', 'integral',
        'diferencial', 'gradiente', 'divergencia', 'rotacional', 'laplaciano',
        'transformada', 'fourier', 'laplace', 'vector', 'matriz', 'determinante',
        'autovalor', 'eigenvalor', 'tensor', 'campo electrico', 'campo magnético',
        'campo eléctrico', 'ley de newton', 'segunda ley', 'conservacion',
        'conservación', 'principio', 'teorema', 'demostra', 'demuestra',
        'prueba que', 'simplifica', 'expande', 'factoriza',
        'resuelve la ecuacion', 'resuelve el sistema',
        'theta', 'phi', 'psi', 'omega', 'alpha', 'beta', 'gamma', 'lambda',
    ]
    if any(k in comando.lower() for k in _KEYWORDS_AVANZADO):
        return _calcular_con_claude(comando, chat_widget)

    # Cálculo simple con eval seguro
    m = re.search(
        r'(?:cu[aá]nto\s+(?:es|da|son)|calcula?|resuelve?|cuanto\s+es)\s+(.+)',
        comando, re.IGNORECASE
    )
    if m:
        expr = m.group(1).strip().lower()
        reemplazos = [
            (r'\bpor\b', '*'),           (r'\bentre\b', '/'),
            (r'\bsobre\b', '/'),         (r'\b(\d+)\s+medios?\b', r'(\1/2)'),
            (r'\b(\d+)\s+tercios?\b', r'(\1/3)'),
            (r'\b(\d+)\s+cuartos?\b', r'(\1/4)'),
            (r'\bcuadrado\s+de\s+(\d+)', r'(\1**2)'),
            (r'\bpartido\s+(?:entre|por|en)\b', '/'),
            (r'\belevado\s+a\s+(\d+)', r'**\1'),
            (r'\bdividido\s+(?:entre|por)\b', '/'),
            (r'\bdividido\b', '/'),      (r'\bmenos\b', '-'),
            (r'\bm[aá]s\b', '+'),        (r'\bal\s+cuadrado\b', '**2'),
            (r'\bal\s+cubo\b', '**3'),   (r'\bel\s+cuadrado\s+de\s+(\d+)', r'(\1**2)'),
            (r'\bra[ií]z\s+(?:cuadrada\s+)?de\s+(\d+)', r'_M.sqrt(\1)'),
            (r'\bseno\s+de\s+(\d+)',     r'_M.sin(_M.radians(\1))'),
            (r'\bcoseno\s+de\s+(\d+)',   r'_M.cos(_M.radians(\1))'),
            (r'\btangente\s+de\s+(\d+)', r'_M.tan(_M.radians(\1))'),
            (r'\bpi\b', str(_math.pi)),
            (r'\bfactorial\s+de\s+(\d+)', r'_M.factorial(\1)'),
            (r'(\d+)\s*%\s*de\s*(\d+)', r'(\1/100*\2)'),
        ]
        for pat, rep in reemplazos:
            expr = re.sub(pat, rep, expr)

        _fn_map = {}
        def _protect_fn(m2):
            key2 = f'__F{len(_fn_map)}__'
            _fn_map[key2] = m2.group(0).replace('_M.', '_math.')
            return key2
        expr_p = re.sub(r'_M\.\w+\([^)]*\)', _protect_fn, expr)
        safe   = re.sub(r'[^0-9\.\+\-\*/\(\)F_]', '', expr_p)
        for k, v in _fn_map.items():
            safe = safe.replace(k, v)
        safe = re.sub(r'__F\d+__', '0', safe)
        safe += ')' * max(0, safe.count('(') - safe.count(')'))
        try:
            resultado = eval(safe, {'_math': _math, '__builtins__': {}})
            def _fmt(n):
                if isinstance(n, float):
                    if n.is_integer():
                        n = int(n)
                    else:
                        return f'{n:.4f}'.rstrip('0').rstrip('.')
                s = str(abs(int(n)))
                groups = []
                while s:
                    groups.append(s[-3:]); s = s[:-3]
                return ('-' if int(n) < 0 else '') + '.'.join(reversed(groups))
            _hablar(_fmt(resultado), chat_widget)
            return True
        except Exception as e:
            print(f'[Calc] fallo eval: {e} | expr: {safe}')
            return _calcular_con_claude(comando, chat_widget)

    # Tiempo de viaje → Google Maps
    m_viaje = re.search(
        r'(?:cu[aá]nto\s+(?:tarda?|demora?|se\s+tarda?|tiempo)|tiempo\s+(?:en|para)'
        r'|en\s+cu[aá]nto\s+tiempo)',
        comando, re.IGNORECASE
    )
    if m_viaje and re.search(
        r'(?:ir\s+a|llegar\s+a|viajar\s+a|de\s+aqu[ií]\s+a|hasta)',
        comando, re.IGNORECASE
    ):
        dest_m  = re.search(
            r'(?:ir\s+a|llegar\s+a|hasta|al?)\s+([A-ZÁÉÍÓÚÑa-záéíóúñ][^,.?!]{1,50})',
            comando, re.IGNORECASE
        )
        medio_m = re.search(
            r'\ben\s+(carro|coche|auto|bus|moto|bicicleta|caminando)\b',
            comando, re.IGNORECASE
        )
        destino  = dest_m.group(1).strip().title() if dest_m else comando
        medio    = (medio_m.group(1) if medio_m else 'carro').lower()
        base     = _memoria().get('ciudad') or 'Bogotá'
        modo_map = {
            'carro': 'driving', 'coche': 'driving', 'auto': 'driving',
            'bus': 'transit', 'moto': 'driving',
            'bicicleta': 'bicycling', 'caminando': 'walking',
        }.get(medio, 'driving')
        webbrowser.open(
            f'https://www.google.com/maps/dir/{_url_quote(base)}/{_url_quote(destino)}'
            f'/?travelmode={modo_map}&departure_time=now'
        )
        _hablar(f'Abriendo Maps. Ruta a {destino} en {medio}.', chat_widget)
        return True

    return False


# =============================================================================
# 4. BÚSQUEDA WEB (Gemini + Groq)
# =============================================================================

_KEYWORDS_CONOCIMIENTO = [
    "que es", "qué es", "quien es", "quién es", "como es", "cómo es",
    "que son", "qué son", "que fue", "qué fue", "quien fue", "quién fue",
    "que significa", "qué significa", "que hay", "qué hay",
    "cuentame", "cuéntame", "describeme", "descríbeme",
    "explica", "explicame", "explícame", "informacion", "información",
    "como funciona", "cómo funciona", "para que sirve", "para qué sirve",
    "como se hace", "cómo se hace", "en que consiste", "en qué consiste",
    "donde vive", "dónde vive", "donde habita", "que come", "qué come",
    "donde queda", "dónde queda", "donde está", "dónde está",
    "cuando fue", "cuándo fue", "cuando nació", "cuándo nació",
    "historia de", "origen de", "caracteristicas", "características",
    "noticias", "que paso", "qué pasó", "que sucedió",
    "cual es", "cuál es", "cuantos", "cuántos",
    "investiga", "busca información", "busca sobre",
]


def buscar_web(pregunta: str, termino_imagen: str = None, chat_widget=None) -> bool:
    """
    Búsqueda web con Google Gemini + grounding.
    Fallback a Groq si Gemini no está disponible.
    Devuelve True si respondió, False si falló completamente.

    Si termino_imagen se pasa, el agente de imágenes se encarga de buscarlo
    (se llama desde el dispatcher, no desde aquí).
    """
    import urllib.request as _ur
    import urllib.error   as _ue

    _keywords_lugares = [
        "restaurante", "restaurantes", "donde comer", "dónde comer",
        "donde ir", "dónde ir", "lugares para", "sitios en",
        "bares en", "cafes en", "cafés en", "donde tomar", "dónde tomar",
        "que hay en", "qué hay en", "lugares en", "parques en", "hoteles en",
    ]
    _keywords_mapas = [
        "mapa", "mapas", "dirección", "direcciones", "ubicación", "ubicaciones",
        "cómo llegar", "como llegar", "ruta", "rutas", "lugar", "sitio",
    ]

    # Evitamos abrir Google Maps automáticamente desde la búsqueda general porque
    # el dispatcher ya puede lanzar la acción de mapa interactivo. Esto previene
    # ventanas dobles cuando el modelo combina "buscar_web" + "mostrar_mapa".
    if _ctx["config"].get("google_maps", True):
        # Solo dejamos el camino de mapas explícito a la ruta dedicada de "mostrar_mapa".
        # La búsqueda general debe responder con contexto, no abrir ventanas extra.
        pass

    gemini_key = _gemini_key()
    if not gemini_key:
        return _buscar_con_groq(pregunta, chat_widget)

    if not _ctx["KEYS_LISTAS"].is_set():
        _ctx["KEYS_LISTAS"].wait(timeout=60)

    _hablar("Buscando...", chat_widget)

    system = (
        "Eres Jarvis, asistente de IA personal. Hablas de forma formal, precisa y profesional, como Jarvis de Iron Man. "
        "Evita modismos, expresiones de la calle y palabras como 'parce'. "
        f"Responde únicamente en {idiomas.language_name((_ctx.get('idioma_respuesta')() if callable(_ctx.get('idioma_respuesta')) else _ctx.get('idioma_respuesta')) or _detectar_idioma(pregunta)[0])}, "
        "aunque las fuentes estén en otro idioma. No dejes que el historial cambie esta elección. "
        "Máximo 3-4 oraciones, o una tabla, o 4 bullets MUY cortos — elige el formato que mejor represente el dato. "
        "NUNCA uses títulos, subtítulos ni secciones (nada de 'Características:', 'Hábitat:', etc). "
        "Para animales/personas/lugares/películas/series: di lo más interesante de forma fluida en un párrafo. "
        "Para CALENDARIOS, horarios, fechas de eventos o carreras, comparativas, o cualquier dato con varias columnas: "
        "usa SIEMPRE una tabla HTML <table><tr><th>...</th></tr><tr><td>...</td></tr></table>. Nunca uses bullets ni texto plano para esto. "
        "Para datos técnicos sueltos sin columnas: máximo 4 bullets de una línea cada uno, usando <ul><li> real. "
        "Usa solo <p>, <b>, <ul><li> y <table> para estructurar. "
        "PROHIBIDO escribir '*' o '-' como viñeta de texto plano: si necesitas una lista, debe ser HTML real <ul><li>, "
        "porque un asterisco suelto se lee en voz alta como 'asterisco'. "
        "NUNCA markdown. NUNCA inventes. Si el dato es reciente, dilo al final en una línea."
    )

    modelos     = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.0-flash-lite"]
    _gk_raw     = _ctx.get("gemini_keys", [])
    gemini_keys = _gk_raw() if callable(_gk_raw) else _gk_raw
    if not gemini_keys and gemini_key:
        gemini_keys = [gemini_key]
    if not gemini_keys:
        return _buscar_con_groq(pregunta, chat_widget)
    n_keys      = len(gemini_keys)
    combos      = [(ki, m) for m in modelos for ki in range(n_keys)]

    html_respuesta = ""
    for ki, modelo in combos:
        key_i = gemini_keys[ki % len(gemini_keys)]
        url   = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{modelo}:generateContent?key={key_i}"
        )
        payload = json.dumps({
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"parts": [{"text": pregunta}]}],
            "tools": [{"google_search": {}}],
            "generationConfig": {
                "temperature":     0.4,
                "maxOutputTokens": 2000,
                "candidateCount":  1,
            },
        }).encode("utf-8")

        req = _ur.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with _ur.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read())
            candidatos = data.get("candidates", [])
            if not candidatos:
                continue
            partes = candidatos[0].get("content", {}).get("parts", [])
            html_respuesta = "".join(
                p.get("text", "") for p in partes if "text" in p
            ).strip()
            if html_respuesta:
                break
        except _ue.HTTPError as e:
            if e.code == 429:
                time.sleep(1)
                continue
            if e.code in (401, 403, 404):
                continue
        except Exception as e:
            print(f"[BuscarWeb] {type(e).__name__}: {e}")
            continue

    if not html_respuesta:
        return _buscar_con_groq(pregunta, chat_widget)

    html_respuesta = _asegurar_respuesta_idioma(html_respuesta, pregunta)

    if _debe_incluir_fuentes_apa(pregunta):
        html_respuesta = _postprocesar_respuesta_investigacion(html_respuesta, pregunta)

    # Limpiar aperturas genéricas de IA
    for pat in [
        r"^[Cc]laro[!,.]?\s*", r"^[Ee]ntendido[!,.]?\s*",
        r"^[Pp]or supuesto[!,.]?\s*", r"^[Ss]eguro[!,.]?\s*",
    ]:
        html_respuesta = re.sub(pat, "", html_respuesta, flags=re.IGNORECASE)

    # Markdown → HTML si Gemini respondió con markdown (no tocar si ya hay HTML estructural real)
    if not re.search(r'<(p|h\d|table|ul|ol)\b', html_respuesta, re.IGNORECASE):
        html_respuesta = _markdown(html_respuesta)

    _bridge_html(_burbuja_jarvis(html_respuesta))
    _bridge_scroll()
    _log_historial_jarvis(html_respuesta)

    # TTS
    texto_voz = _limpiar(html_respuesta)
    texto_voz = re.sub(
        r'📌\s*Fuentes?:?.*', '', texto_voz, flags=re.DOTALL | re.IGNORECASE
    ).strip()
    texto_voz = re.sub(r'https?://\S+', '', texto_voz)
    if texto_voz:
        _cola_voz().put(texto_voz)

    return True


def _buscar_con_groq(pregunta: str, chat_widget=None) -> bool:
    """Búsqueda web con Browser Search de Groq y respaldo entre modelos activos."""
    if not _ctx["KEYS_LISTAS"].is_set():
        _ctx["KEYS_LISTAS"].wait(timeout=60)

    groq_keys = _ctx["groq_keys"]()
    if not groq_keys:
        _hablar("No hay keys de IA disponibles en este momento.", chat_widget)
        return False

    system = (
        "Eres Jarvis, asistente de IA personal. Habla como una persona, directo y natural. "
        "Usa la búsqueda web para comprobar la respuesta y prioriza fuentes oficiales o primarias. "
        f"Responde únicamente en {idiomas.language_name((_ctx.get('idioma_respuesta')() if callable(_ctx.get('idioma_respuesta')) else _ctx.get('idioma_respuesta')) or _detectar_idioma(pregunta)[0])}, "
        "aunque las fuentes estén en otro idioma. No dejes que el historial cambie esta elección. "
        "Incluye enlaces/citas de las fuentes consultadas cuando estén disponibles; no inventes fuentes. "
        "Máximo 3 oraciones, o una tabla HTML <table> si el dato es tabular (fechas, calendarios, comparativas), "
        "o 4 bullets cortos con <ul><li>. "
        "NUNCA uses títulos ni secciones. Sin markdown. Nunca uses '*' ni '-' como viñeta de texto plano "
        "(se leería en voz alta como 'asterisco'). Solo <p>, <b>, <ul><li>, <table>. "
        "Si no sabes algo, dilo en una sola línea."
    )

    modelos_configurados = _ctx.get("GROQ_MODELOS_FALLBACK", [])
    if callable(modelos_configurados):
        modelos_configurados = modelos_configurados()
    modelos = []
    for modelo in [
        _ctx.get("GROQ_MODEL", "openai/gpt-oss-120b"),
        *(modelos_configurados or []),
        "openai/gpt-oss-20b",
    ]:
        if modelo and modelo not in modelos:
            modelos.append(modelo)

    ultimo_error = ""
    for modelo in modelos:
        for _intento in range(max(1, len(groq_keys) * 2)):
            headers = {
                "Authorization": f"Bearer {_groq_key()}",
                "Content-Type":  "application/json",
            }
            payload = {
                "model": modelo,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": pregunta},
                ],
                "temperature": 1,
                "max_completion_tokens": 1200,
                "reasoning_effort": "low",
                "tool_choice": "required",
                "tools": [{"type": "browser_search"}],
            }
            try:
                resp = requests.post(
                    _ctx["GROQ_BASE_URL"], json=payload, headers=headers, timeout=60
                )
            except requests.exceptions.ConnectionError:
                time.sleep(2)
                continue
            except requests.exceptions.RequestException as exc:
                ultimo_error = f"Error de conexión: {type(exc).__name__}"
                print(f"[Groq search] {ultimo_error}")
                break

            if resp.status_code == 429:
                ultimo_error = "HTTP 429: se alcanzó el límite temporal de solicitudes."
                _rotar_groq("429")
                time.sleep(1)
                continue
            if resp.status_code == 401:
                ultimo_error = "HTTP 401: Groq rechazó la clave API."
                _rotar_groq("401")
                continue
            if resp.status_code in (400, 403, 404, 413, 422):
                try:
                    error_data = resp.json().get("error", {})
                    detalle = error_data.get("message") or error_data.get("failed_generation") or ""
                except (ValueError, AttributeError, TypeError):
                    detalle = ""
                detalle = re.sub(r"(?i)(bearer\s+)[^\s,;]+", r"\1[oculto]", str(detalle))
                detalle = re.sub(r"https?://\S+", "[enlace omitido]", detalle).strip()[:360]
                explicaciones = {
                    400: "Groq rechazó los parámetros o la herramienta de búsqueda.",
                    403: "Groq denegó el acceso al modelo o a la herramienta con esta clave/proyecto.",
                    404: "El modelo o la ruta solicitada no está disponible.",
                    413: "La solicitud es demasiado grande para el proveedor.",
                    422: "Groq no pudo procesar los parámetros de la búsqueda.",
                }
                ultimo_error = f"HTTP {resp.status_code}: {explicaciones.get(resp.status_code, 'Groq rechazó esta solicitud.')}"
                if detalle:
                    ultimo_error += f" Detalle: {detalle}"
                print(f"[Groq search] Modelo/herramienta {modelo} HTTP {resp.status_code}: {resp.text[:300]}")
                break
            if resp.status_code != 200:
                ultimo_error = f"HTTP {resp.status_code}: respuesta inesperada del proveedor."
                print(f"[Groq search] {ultimo_error} {resp.text[:300]}")
                break

            try:
                texto = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            except (ValueError, IndexError, AttributeError, TypeError) as exc:
                ultimo_error = f"Respuesta inesperada: {type(exc).__name__}."
                print(f"[Groq search] {ultimo_error}")
                break
            if not texto:
                ultimo_error = "HTTP 200: Groq aceptó la solicitud, pero devolvió una respuesta vacía."
                break

            texto = _asegurar_respuesta_idioma(texto, pregunta)

            html = _markdown(texto)
            _bridge_html(_burbuja_jarvis(html))
            _bridge_scroll()
            _log_historial_jarvis(html)

            texto_voz = _limpiar(html)
            if texto_voz:
                _cola_voz().put(texto_voz)
            return True

    mensaje_error = "No pude completar la búsqueda web con Groq."
    if ultimo_error:
        mensaje_error += f" {ultimo_error}"
    else:
        mensaje_error += " Comprueba la conexión y que el proyecto tenga habilitado un modelo compatible con búsqueda web."
    _bridge_html(_burbuja_jarvis(_html.escape(mensaje_error)))
    _bridge_scroll()
    _hablar(mensaje_error, chat_widget)
    return False


def _normalizar_idioma_traduccion(idioma: str) -> str:
    """Convierte nombres de idioma a códigos ISO reconocibles por el modelo."""
    texto = str(idioma or "inglés").strip().lower()
    if not texto:
        return "en"
    if re.fullmatch(r"[a-z]{2,3}", texto):
        return texto

    mapa = {
        "inglés": "en", "english": "en", "ingles": "en",
        "español": "es", "spanish": "es", "espanol": "es",
        "francés": "fr", "frances": "fr", "french": "fr", "francais": "fr",
        "alemán": "de", "aleman": "de", "german": "de",
        "italiano": "it", "italian": "it",
        "portugués": "pt", "portugues": "pt", "portuguese": "pt",
        "ruso": "ru", "russian": "ru",
        "turco": "tr", "turko": "tr", "turkish": "tr",
        "japonés": "ja", "japones": "ja", "japanese": "ja",
        "coreano": "ko", "korean": "ko",
        "chino": "zh", "mandarín": "zh", "mandarin": "zh",
        "árabe": "ar", "arabe": "ar", "arabic": "ar",
        "holandés": "nl", "holandes": "nl", "dutch": "nl",
        "sueco": "sv", "suéco": "sv", "swedish": "sv",
        "polaco": "pl", "polish": "pl",
        "hindi": "hi", "indio": "hi",
        "noruego": "no", "danés": "da", "danish": "da", "dano": "da",
        "finés": "fi", "fines": "fi", "finnish": "fi",
        "griego": "el", "greek": "el",
        "ucraniano": "uk", "ukrainian": "uk",
        "vietnamita": "vi", "vietnamese": "vi",
        "tailandés": "th", "tailandes": "th",
        "indonesio": "id", "indonesian": "id",
        "hebreo": "he", "hebrew": "he",
    }
    return mapa.get(texto, "en")


def _traducir_con_google(texto: str, idioma_destino: str) -> str:
    """Fallback determinista usando el endpoint público de Google Translate."""
    if not texto or not idioma_destino:
        return ""
    try:
        encoded = _url_quote(texto)
        url = (
            "https://translate.googleapis.com/translate_a/single"
            f"?client=gtx&sl=auto&tl={idioma_destino}&dt=t&q={encoded}"
        )
        resp = requests.get(url, timeout=20)
        if resp.status_code != 200:
            print(f"[Google Translate] HTTP {resp.status_code}")
            return ""
        data = resp.json()
        if not isinstance(data, list) or len(data) < 2 or not isinstance(data[0], list):
            return ""
        partes = []
        for item in data[0]:
            if isinstance(item, list) and item and isinstance(item[0], str):
                partes.append(item[0])
        return "".join(partes).strip()
    except Exception as exc:
        print(f"[Google Translate] Error: {exc}")
        return ""


def _traducir_con_groq(texto: str, origen: str, destino: str) -> str:
    """Último respaldo de traducción cuando los endpoints de traducción limitan peticiones."""
    keys_fn = _ctx.get("groq_keys")
    keys = keys_fn() if callable(keys_fn) else []
    if not keys:
        return ""
    for intento in range(min(2, len(keys) * 2)):
        key_fn = _ctx.get("groq_key_activa")
        key = key_fn() if callable(key_fn) else keys[intento % len(keys)]
        try:
            resp = requests.post(
                _ctx.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1/chat/completions"),
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": _ctx.get("GROQ_MODEL", "openai/gpt-oss-20b"),
                    "messages": [
                        {"role": "system", "content": f"Traduce fielmente del idioma {origen or 'detectado automáticamente'} al idioma {destino}. Conserva el formato. Responde únicamente con la traducción, sin explicaciones."},
                        {"role": "user", "content": texto[:10000]},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 2000,
                }, timeout=25,
            )
            if resp.status_code in (401, 429):
                rotate = _ctx.get("groq_rotar_key")
                if callable(rotate):
                    rotate(f"traducción {resp.status_code}")
                continue
            if resp.status_code == 200:
                return resp.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            print(f"[Groq Translation] HTTP {resp.status_code}: {resp.text[:200]}")
        except requests.RequestException as exc:
            print(f"[Groq Translation] Error: {exc}")
    return ""


def traducir_texto(texto: str, idioma_destino: str = "inglés", idioma_origen: str = "", chat_widget=None) -> bool:
    """Traduce texto mediante NVIDIA si funciona; si no, usa Google Translate como fallback fiable."""
    texto = str(texto or "").strip()
    destino_label = str(idioma_destino or "inglés").strip() or "inglés"
    destino = _normalizar_idioma_traduccion(destino_label)
    origen = str(idioma_origen or "").strip()
    origen_label = origen if origen else "auto-detect"
    if not texto:
        _hablar("Necesito el texto que quieres traducir.", chat_widget)
        return False

    keys_fn = _ctx.get("nvidia_keys")
    key_fn = _ctx.get("nvidia_key_activa")
    rotate_fn = _ctx.get("nvidia_rotar_key")
    keys = keys_fn() if callable(keys_fn) else []
    key = key_fn() if callable(key_fn) else ""

    instrucciones = (
        f"Traduce el siguiente texto del idioma {origen_label} al idioma {destino_label} ({destino}). "
        f"Conserva el significado, el tono y el formato. Devuelve únicamente la traducción, sin explicaciones."
    )
    if origen:
        instrucciones += f" El idioma de origen es {origen}."

    if keys and key:
        modelos = [
            _ctx.get("NVIDIA_MODELO_TRADUCCION", "nvidia/riva-translate-4b-instruct-v2"),
            "openai/gpt-oss-20b",
            "z-ai/glm-5.3-flash",
            "mistralai/mistral-nemotron",
        ]
        base_url = _ctx.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1/chat/completions")

        for modelo_actual in dict.fromkeys(modelos):
            payload = {
                "model": modelo_actual,
                "messages": [
                    {"role": "system", "content": instrucciones},
                    {"role": "user", "content": texto[:12000]},
                ],
                "temperature": 0.1,
                "max_tokens": 2000,
            }
            if modelo_actual != _ctx.get("NVIDIA_MODELO_TRADUCCION", "nvidia/riva-translate-4b-instruct-v2"):
                payload["messages"] = [
                    {"role": "user", "content": f"Translate exactly this text from {origen_label} to {destino_label}. Return only the translated text and nothing else.\n\nTexto: {texto[:12000]}"}
                ]
            try:
                respuesta = requests.post(
                    base_url,
                    json=payload,
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    timeout=30,
                )
                if respuesta.status_code in (401, 403, 429):
                    if callable(rotate_fn):
                        rotate_fn(f"traduccion {respuesta.status_code}")
                    if modelo_actual == modelos[-1]:
                        break
                    continue
                if respuesta.status_code != 200:
                    print(f"[NVIDIA Translation] HTTP {respuesta.status_code}: {respuesta.text[:300]}")
                    if modelo_actual == modelos[-1]:
                        break
                    continue
                traduccion = respuesta.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                if not traduccion:
                    if modelo_actual == modelos[-1]:
                        break
                    continue
                if destino != "en" and traduccion.lower().strip() == texto.lower().strip():
                    if modelo_actual != modelos[-1]:
                        continue
                html_resultado = "<p><b>Traducción:</b></p><p>" + html.escape(traduccion).replace("\n", "<br>") + "</p>"
                _bridge_html(_burbuja_jarvis(html_resultado))
                _bridge_scroll()
                _cola_voz().put(_limpiar(traduccion)[:800])
                return True
            except requests.RequestException as exc:
                print(f"[NVIDIA Translation] Error de red: {exc}")
                if modelo_actual == modelos[-1]:
                    break
                continue

    traduccion_google = _traducir_con_google(texto, destino)
    if not traduccion_google:
        traduccion_google = _traducir_con_groq(texto, origen_label, destino_label)
    if traduccion_google:
        html_resultado = "<p><b>Traducción:</b></p><p>" + html.escape(traduccion_google).replace("\n", "<br>") + "</p>"
        _bridge_html(_burbuja_jarvis(html_resultado))
        _bridge_scroll()
        _cola_voz().put(_limpiar(traduccion_google)[:800])
        return True

    _hablar("No pude traducir el texto en este momento.", chat_widget)
    return False


# =============================================================================
# FUNCIÓN PRINCIPAL DEL AGENTE
# =============================================================================

def ejecutar(accion: str, params: dict, chat_widget=None) -> bool:
    """
    Punto de entrada único desde dispatcher.py.

    Acciones soportadas:
      buscar_web  → params: {pregunta, termino_imagen?}
            traducir    → params: {texto, idioma_destino?, idioma_origen?}
      noticias    → params: {tema?, categoria?}
      clima       → params: {ciudad?}
      calcular    → params: {expresion}

    Devuelve True si procesó la acción.
    """
    params = params if isinstance(params, dict) else {}
    if accion == "buscar_web":
        return buscar_web(
            str(params.get("pregunta") or ""),
            str(params.get("termino_imagen") or "") or None,
            chat_widget,
        )
    if accion == "noticias":
        obtener_noticias(
            str(params.get("tema") or ""),
            str(params.get("categoria") or ""),
            chat_widget,
        )
        return True
    if accion == "clima":
        obtener_clima(str(params.get("ciudad") or "Bogotá"), chat_widget, str(params.get("dia") or "hoy"))
        return True
    if accion == "calcular":
        return calcular_expresion(str(params.get("expresion") or ""), chat_widget)
    if accion == "traducir":
        return traducir_texto(
            str(params.get("texto") or ""),
            str(params.get("idioma_destino") or "inglés"),
            str(params.get("idioma_origen") or ""),
            chat_widget,
        )

    print(f"[agent_search] Acción desconocida: '{accion}'")
    return False
