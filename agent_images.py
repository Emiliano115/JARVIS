# =============================================================================
# agent_images.py — Agente de Búsqueda y Generación de Imágenes
# =============================================================================
# Responsabilidades:
#   · Categorización inteligente del término de búsqueda
#   · Búsqueda multi-fuente: Unsplash, Pexels, Google Custom Search,
#     Wikimedia/Wikipedia, iNaturalist
#   · Filtrado de IP protegida (Marvel, Disney, videojuegos, etc.)
#   · Generación por IA (placeholder hasta conectar API)
#   · HTML galería para QTextBrowser
#   · Descarga de imágenes al disco si se solicita
#
# Interfaz pública:
#   ejecutar(accion, params, chat_widget) -> bool
#   buscar_imagenes(termino, max_imgs) -> list[str]
#   generar_imagen(prompt, chat_widget) -> bool   ← placeholder, sin API aún
#   html_galeria(termino, urls) -> str
#
# Acciones del dispatcher:
#   "buscar"   → params: {termino, max_imgs?}
#   "galeria"  → params: {termino, urls}
#   "generar"  → params: {prompt}               ← sin API aún, avisa al usuario
#
# Dependencias inyectadas via init(ctx):
#   hablar, cola_voz, bridge, html_burbuja,
#   UNSPLASH_ACCESS_KEY, PEXELS_API_KEY,
#   GOOGLE_SEARCH_API_KEY, GOOGLE_SEARCH_CX,
#
# Nota: NO necesita Groq, Gemini ni historial.
#       Es un agente puramente de recuperación/generación visual.
# =============================================================================

from __future__ import annotations

import re
import random
import threading
from urllib.parse import quote as _url_quote

import requests

# =============================================================================
# CONTEXTO INYECTADO
# =============================================================================

_ctx: dict = {}


def init(ctx: dict):
    """
    Inyecta el contexto compartido.
    Llamar UNA VEZ desde main.py antes de usar cualquier función.

    Ejemplo:
        import agent_images
        agent_images.init({
            "hablar":              hablar,
            "cola_voz":            _cola_voz,
            "bridge":              _bridge,
            "html_burbuja":        _html_burbuja,
            "UNSPLASH_ACCESS_KEY": lambda: UNSPLASH_ACCESS_KEY,
            "PEXELS_API_KEY":      lambda: PEXELS_API_KEY,
            "GOOGLE_SEARCH_API_KEY": lambda: GOOGLE_SEARCH_API_KEY,
            "GOOGLE_SEARCH_CX":    lambda: GOOGLE_SEARCH_CX,
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


# =============================================================================
# 1. CATEGORÍAS Y DATOS DE BÚSQUEDA
# =============================================================================

# Términos que activan iNaturalist + Unsplash con orientación naturaleza
_TEMAS_NATURALEZA: set = {
    "oso", "oso polar", "oso pardo", "oso negro", "panda", "koala",
    "tigre", "leon", "léon", "leopardo", "guepardo", "jaguar", "puma", "lince",
    "lobo", "zorro", "elefante", "rinoceronte", "hipopotamo", "hipopótamo",
    "jirafa", "cebra", "gorila", "chimpance", "orangutan", "canguro",
    "ballena", "delfin", "delfín", "tiburon", "tiburón", "orca",
    "pulpo", "calamar", "medusa", "cangrejo", "langosta", "estrella de mar",
    "foca", "morsa", "lobo marino", "manatí", "narval", "mantarraya",
    "dragon de mar", "dragón de mar", "caballito de mar",
    "aguila", "águila", "condor", "cóndor", "colibri", "colibrí",
    "flamenco", "tucan", "tucán", "loro", "pinguino", "pingüino",
    "pelicano", "pelícano", "albatros", "buho", "búho", "halcon", "halcón",
    "cuervo", "serpiente", "cocodrilo", "iguana", "tortuga", "camaleon",
    "rana", "mariposa", "abeja", "araña", "escorpion", "escorpión",
    "coral", "arrecife", "selva", "bosque", "sabana", "tundra",
    "rosa", "orquidea", "orquídea", "girasol", "cactus", "bambu", "bambú",
    "perro", "gato", "caballo", "conejo", "hamster",
    "golden retriever", "labrador", "pastor aleman", "pastor alemán",
    "bulldog", "poodle", "chihuahua", "husky", "dalmata", "dálmata",
    "beagle", "boxer", "schnauzer", "doberman", "rottweiler", "samoyedo",
    "animal", "planta", "flora", "fauna", "mamifero", "mamífero",
    "reptil", "anfibio", "ave", "pez", "insecto",
}

# Traducción español → inglés para iNaturalist/Unsplash
_NAT_ES_EN: list = [
    ("oso polar",           "polar bear arctic"),
    ("oso pardo",           "brown bear grizzly"),
    ("oso negro",           "black bear"),
    ("oso",                 "bear animal"),
    ("panda gigante",       "giant panda"),
    ("panda rojo",          "red panda"),
    ("panda",               "giant panda"),
    ("tigre blanco",        "white tiger"),
    ("tigre de bengala",    "bengal tiger"),
    ("tigre",               "tiger animal"),
    ("leon",                "lion animal"),
    ("léon",                "lion animal"),
    ("leopardo de las nieves", "snow leopard"),
    ("leopardo",            "leopard animal"),
    ("guepardo",            "cheetah animal"),
    ("jaguar",              "jaguar animal"),
    ("puma",                "mountain lion puma"),
    ("lince",               "lynx animal"),
    ("elefante africano",   "african elephant"),
    ("elefante",            "elephant"),
    ("jirafa",              "giraffe"),
    ("cebra",               "zebra"),
    ("rinoceronte",         "rhinoceros"),
    ("hipopotamo",          "hippopotamus"),
    ("hipopótamo",          "hippopotamus"),
    ("gorila",              "gorilla animal"),
    ("chimpance",           "chimpanzee"),
    ("orangutan",           "orangutan"),
    ("canguro",             "kangaroo australia"),
    ("lobo",                "wolf animal"),
    ("zorro",               "fox animal"),
    ("koala",               "koala australia"),
    ("nutria",              "otter"),
    ("castor",              "beaver"),
    ("foca",                "seal animal"),
    ("morsa",               "walrus"),
    ("lobo marino",         "sea lion"),
    ("narval",              "narwhal"),
    ("mantarraya",          "manta ray ocean"),
    ("tiburon blanco",      "great white shark ocean"),
    ("tiburon ballena",     "whale shark ocean"),
    ("tiburon",             "shark ocean"),
    ("tiburón",             "shark ocean"),
    ("ballena azul",        "blue whale ocean"),
    ("ballena",             "whale ocean"),
    ("delfin",              "dolphin ocean"),
    ("delfín",              "dolphin ocean"),
    ("orca",                "orca killer whale"),
    ("pulpo",               "octopus ocean"),
    ("calamar",             "squid ocean"),
    ("medusa",              "jellyfish ocean"),
    ("cangrejo",            "crab ocean"),
    ("langosta",            "lobster ocean"),
    ("estrella de mar",     "starfish ocean"),
    ("aguila calva",        "bald eagle"),
    ("aguila",              "eagle bird"),
    ("águila",              "eagle bird"),
    ("condor",              "condor bird"),
    ("cóndor",              "condor bird"),
    ("colibri",             "hummingbird"),
    ("colibrí",             "hummingbird"),
    ("flamenco",            "flamingo bird"),
    ("tucan",               "toucan bird"),
    ("tucán",               "toucan bird"),
    ("loro",                "parrot"),
    ("pinguino",            "penguin"),
    ("pingüino",            "penguin"),
    ("pelicano",            "pelican"),
    ("pelícano",            "pelican"),
    ("albatros",            "albatross"),
    ("buho",                "owl bird"),
    ("búho",                "owl bird"),
    ("halcon peregrino",    "peregrine falcon"),
    ("halcon",              "falcon bird"),
    ("halcón",              "falcon bird"),
    ("serpiente",           "snake"),
    ("cocodrilo",           "crocodile"),
    ("iguana",              "iguana lizard"),
    ("tortuga marina",      "sea turtle"),
    ("tortuga",             "turtle"),
    ("camaleon",            "chameleon"),
    ("camaleón",            "chameleon"),
    ("rana",                "frog"),
    ("mariposa",            "butterfly"),
    ("abeja",               "bee"),
    ("golden retriever",    "golden retriever dog"),
    ("labrador",            "labrador retriever dog"),
    ("pastor aleman",       "german shepherd dog"),
    ("pastor alemán",       "german shepherd dog"),
    ("husky",               "siberian husky dog"),
    ("dalmata",             "dalmatian dog"),
    ("dálmata",             "dalmatian dog"),
    ("bulldog",             "bulldog dog"),
    ("poodle",              "poodle dog"),
    ("chihuahua",           "chihuahua dog"),
    ("beagle",              "beagle dog"),
    ("boxer",               "boxer dog"),
    ("schnauzer",           "schnauzer dog"),
    ("doberman",            "doberman dog"),
    ("rottweiler",          "rottweiler dog"),
    ("samoyedo",            "samoyed dog"),
    ("perro",               "dog"),
    ("gato",                "cat"),
    ("conejo",              "rabbit"),
    ("caballo",             "horse"),
    ("hamster",             "hamster"),
    ("rosa",                "rose flower"),
    ("orquidea",            "orchid flower"),
    ("orquídea",            "orchid flower"),
    ("girasol",             "sunflower"),
    ("cactus",              "cactus plant"),
    ("bambu",               "bamboo"),
    ("bambú",               "bamboo"),
    ("selva amazonica",     "amazon rainforest"),
    ("selva",               "jungle rainforest"),
    ("bosque",              "forest nature"),
    ("montaña",             "mountain landscape"),
]

# Términos de laboratorio → query en inglés
_TEMAS_LAB: dict = {
    "beaker":                 "beaker laboratory glassware",
    "vaso de precipitados":   "beaker laboratory glassware",
    "matraz":                 "erlenmeyer flask laboratory",
    "matraz erlenmeyer":      "erlenmeyer flask laboratory",
    "matraz aforado":         "volumetric flask laboratory",
    "probeta":                "graduated cylinder laboratory",
    "pipeta":                 "pipette laboratory",
    "bureta":                 "burette laboratory titration",
    "microscopio":            "microscope laboratory",
    "microscopio optico":     "optical microscope laboratory",
    "microscopio electronico":"electron microscope",
    "centrifuga":             "centrifuge laboratory",
    "espectrofotometro":      "spectrophotometer laboratory",
    "balanza analitica":      "analytical balance laboratory",
    "mechero bunsen":         "bunsen burner laboratory",
    "placa petri":            "petri dish laboratory",
    "tubo de ensayo":         "test tube laboratory",
    "mortero":                "mortar pestle laboratory",
    "embudo separador":       "separatory funnel laboratory",
    "campana extractora":     "fume hood laboratory",
    "autoclave":              "autoclave laboratory sterilization",
    "tabla periodica":        "periodic table elements",
    "atomo":                  "atom model structure",
    "molecula":               "molecule model 3d",
    "reaccion quimica":       "chemical reaction laboratory",
}

# Términos científicos / matemáticos → query en inglés
_TEMAS_CIENCIA: dict = {
    "plano cartesiano":        "cartesian plane coordinate system graph",
    "funcion cuadratica":      "quadratic function parabola graph",
    "parabola":                "parabola graph mathematics",
    "parábola":                "parabola graph mathematics",
    "funcion lineal":          "linear function graph slope",
    "hiperbola":               "hyperbola graph mathematics",
    "elipse":                  "ellipse graph mathematics",
    "funcion seno":            "sine wave function graph",
    "onda seno":               "sine wave oscillation graph",
    "funcion coseno":          "cosine wave function graph",
    "funcion tangente":        "tangent function graph",
    "transformada de fourier": "fourier transform frequency spectrum",
    "derivada":                "derivative function graph tangent line",
    "integral":                "integral area under curve graph",
    "fractal":                 "fractal mathematics visualization",
    "mandelbrot":              "mandelbrot set fractal",
    "triangulo rectangulo":    "right triangle trigonometry",
    "teorema de pitagoras":    "pythagorean theorem right triangle",
    "vector":                  "vector arrow mathematics physics",
    "matriz":                  "matrix mathematics linear algebra",
    "onda mecanica":           "mechanical wave propagation",
    "onda electromagnetica":   "electromagnetic wave spectrum",
    "espectro electromagnetico":"electromagnetic spectrum wavelength",
    "campo electrico":         "electric field lines charges",
    "campo magnetico":         "magnetic field lines bar magnet",
    "circuito electrico":      "electric circuit diagram",
    "adn":                     "DNA double helix structure",
    "arn":                     "RNA structure molecule",
    "celula animal":           "animal cell diagram labeled",
    "celula vegetal":          "plant cell diagram labeled",
    "mitosis":                 "mitosis cell division diagram",
    "fotosintesis":            "photosynthesis diagram chloroplast",
    "agujero negro":           "black hole event horizon",
}

# Personas conocidas → búsqueda en Wikipedia + portrait
_PERSONAS_CONOCIDAS: set = {
    "einstein", "newton", "darwin", "tesla", "curie", "hawking", "feynman",
    "shakespeare", "beethoven", "mozart", "da vinci", "picasso", "frida kahlo",
    "gabriel garcia marquez", "gabriel garcia márquez", "pablo escobar",
    "simon bolivar", "simón bolívar", "jorge isaacs",
    "elon musk", "bill gates", "steve jobs", "jeff bezos", "mark zuckerberg",
    "barack obama", "donald trump", "joe biden", "angela merkel",
    "ronaldo", "messi", "neymar", "mbappé", "james rodriguez", "james rodríguez",
    "shakira", "maluma", "j balvin", "bad bunny", "karol g",
    "taylor swift", "beyonce", "rihanna", "drake", "eminem", "michael jackson",
}

# Lugares conocidos → query directa en inglés
_LUGARES_CONOCIDOS: dict = {
    "torre eiffel":           "Eiffel Tower Paris France",
    "machu picchu":           "Machu Picchu Peru",
    "ciudad de roma":         "Rome Italy colosseum",
    "coliseo":                "Colosseum Rome Italy",
    "gran muralla china":     "Great Wall of China",
    "taj mahal":              "Taj Mahal India",
    "sagrada familia":        "Sagrada Familia Barcelona Spain",
    "cristo redentor":        "Christ the Redeemer Rio de Janeiro",
    "estatua de la libertad": "Statue of Liberty New York",
    "stonehenge":             "Stonehenge England UK",
    "petra":                  "Petra Jordan ancient city",
    "chichen itza":           "Chichen Itza Mexico",
    "angkor wat":             "Angkor Wat Cambodia",
    "cartagena":              "Cartagena Colombia old city",
    "medellin":               "Medellín Colombia city",
    "bogota":                 "Bogotá Colombia city",
    "bogotá":                 "Bogotá Colombia city",
    "mit":                    "MIT Massachusetts Institute Technology campus",
    "harvard":                "Harvard University campus",
    "oxford":                 "Oxford University England",
    "cambridge":              "Cambridge University England",
}

# IP protegida — nunca buscar imágenes de esto
_IP_PROTEGIDA: list = [
    "spider-man", "spiderman", "iron man", "ironman", "captain america",
    "black widow", "batman", "superman", "wonder woman", "disney", "pixar",
    "star wars", "harry potter", "hobbit", "lord of the rings",
    "pokemon", "pikachu", "zelda", "mario", "call of duty", "fortnite",
    "minecraft", "gta", "transformers", "godzilla", "king kong",
]


# =============================================================================
# 2. HELPERS DE BÚSQUEDA
# =============================================================================

def _normalizar(texto: str) -> str:
    """Quita tildes y pasa a minúsculas para comparaciones."""
    reemplazos = [
        ('á','a'),('à','a'),('ä','a'),('â','a'),
        ('é','e'),('è','e'),('ë','e'),('ê','e'),
        ('í','i'),('ì','i'),('ï','i'),('î','i'),
        ('ó','o'),('ò','o'),('ö','o'),('ô','o'),
        ('ú','u'),('ù','u'),('ü','u'),('û','u'),
        ('ñ','n'),
    ]
    t = texto.lower().strip()
    for origen, dest in reemplazos:
        t = t.replace(origen, dest)
    return t


def _geocode_place(termino: str) -> dict | None:
    """
    Intenta detectar si el término es un lugar (ciudad/país/POI) usando
    la geocodificación gratuita de Open-Meteo. Devuelve diccionario con
    'name', 'country', 'latitude', 'longitude' o None si no se encuentra.
    """
    try:
        q = _url_quote(termino)
        r = requests.get(
            f"https://geocoding-api.open-meteo.com/v1/search?name={q}&count=1&language=es&format=json",
            timeout=6,
            headers={"User-Agent": "Mozilla/5.0 Jarvis/1.0"},
        )
        if r.status_code != 200:
            return None
        j = r.json()
        results = j.get("results") or j.get("results", [])
        if not results:
            return None
        top = results[0]
        return {
            "name": top.get("name"),
            "country": top.get("country" , ""),
            "latitude": top.get("latitude"),
            "longitude": top.get("longitude"),
        }
    except Exception:
        return None


def _categorizar_termino(termino: str) -> tuple[str, str]:
    """
    Detecta la categoría del término y construye la query en inglés.
    Retorna (categoria, query_en_ingles).
    Categorías: 'persona', 'lugar', 'lab', 'ciencia', 'naturaleza', 'generico'
    """
    t       = termino.lower().strip()
    t_clean = _normalizar(t)

    # 1. Persona famosa conocida
    if t_clean in _PERSONAS_CONOCIDAS or t in _PERSONAS_CONOCIDAS:
        return ('persona', f"{termino} portrait photograph")

    # 2. Dos o más palabras con mayúsculas → probablemente persona
    palabras = termino.strip().split()
    if len(palabras) >= 2 and all(p[0].isupper() for p in palabras if len(p) > 2):
        return ('persona', f"{termino} portrait photograph")

    # 3. Lugar conocido
    if t_clean in _LUGARES_CONOCIDOS:
        return ('lugar', _LUGARES_CONOCIDOS[t_clean])
    if t in _LUGARES_CONOCIDOS:
        return ('lugar', _LUGARES_CONOCIDOS[t])

    # 4. Laboratorio
    if t_clean in _TEMAS_LAB:
        return ('lab', _TEMAS_LAB[t_clean])
    if t in _TEMAS_LAB:
        return ('lab', _TEMAS_LAB[t])

    # 5. Ciencia / matemáticas
    if t_clean in _TEMAS_CIENCIA:
        return ('ciencia', _TEMAS_CIENCIA[t_clean])
    if t in _TEMAS_CIENCIA:
        return ('ciencia', _TEMAS_CIENCIA[t])

    # 6. Naturaleza — búsqueda de subcadena (cubre compuestos como "oso pardo")
    if any(nat in t for nat in _TEMAS_NATURALEZA):
        mejor, mejor_t = "", termino
        for es, en in _NAT_ES_EN:
            if es in t and len(es) > len(mejor):
                mejor, mejor_t = es, en
        return ('naturaleza', mejor_t)

    return ('generico', termino)


def _es_relevante_url(url: str) -> bool:
    """Descarta SVGs, GIFs, thumbnails pequeños y logos."""
    url_l = url.lower().split("?")[0]
    if url_l.endswith('.svg') or url_l.endswith('.gif'):
        return False
    m_px = re.search(r'/(\d+)px-', url_l)
    if m_px and int(m_px.group(1)) < 200:
        return False
    _descartados = (
        "logo", "icon", "favicon", "placeholder", "noimage",
        "default.", "blank.", "spacer.", "badge", "shield",
    )
    if any(d in url_l.split("/")[-1] for d in _descartados):
        return False
    return True


def _buscar_img_wikimedia(nombre: str) -> list[str]:
    """
    Busca imagen principal en Wikipedia (thumbnail de alta resolución).
    Intenta primero por título exacto, luego por búsqueda de texto.
    """
    import urllib.parse as _up
    urls    = []
    headers = {"User-Agent": "Mozilla/5.0 Jarvis/1.0"}

    # Intento 1: thumbnail directo por título
    try:
        r = requests.get(
            f"https://en.wikipedia.org/w/api.php"
            f"?action=query&titles={_up.quote(nombre)}"
            f"&prop=pageimages&format=json&pithumbsize=800",
            timeout=6, headers=headers
        )
        if r.status_code == 200:
            for page in r.json().get("query", {}).get("pages", {}).values():
                thumb = page.get("thumbnail", {}).get("source", "")
                if thumb:
                    urls.append(re.sub(r'/\d+px-', '/800px-', thumb))
    except Exception as e:
        print(f"[Imgs-Wiki] thumbnail: {e}")

    # Intento 2: búsqueda de texto si no encontramos nada
    if not urls:
        try:
            r2 = requests.get(
                f"https://en.wikipedia.org/w/api.php"
                f"?action=query&list=search&srsearch={_url_quote(nombre)}"
                f"&format=json&srlimit=1",
                timeout=6, headers=headers
            )
            if r2.status_code == 200:
                results = r2.json().get("query", {}).get("search", [])
                if results:
                    page_title = results[0]["title"]
                    r3 = requests.get(
                        f"https://en.wikipedia.org/w/api.php"
                        f"?action=query&titles={_url_quote(page_title)}"
                        f"&prop=pageimages&format=json&pithumbsize=800",
                        timeout=6, headers=headers
                    )
                    if r3.status_code == 200:
                        for page in r3.json().get("query", {}).get("pages", {}).values():
                            thumb = page.get("thumbnail", {}).get("source", "")
                            if thumb:
                                urls.append(re.sub(r'/\d+px-', '/800px-', thumb))
        except Exception as e:
            print(f"[Imgs-Wiki] search: {e}")

    return urls


# =============================================================================
# 3. BÚSQUEDA MULTI-FUENTE
# =============================================================================

def buscar_imagenes(termino: str, max_imgs: int = 3) -> list[str]:
    """
    Sistema multi-fuente de imágenes.
    1. Verifica que el término no sea IP protegida.
    2. Categoriza y construye query en inglés.
    3. Busca en las APIs apropiadas según categoría.
    4. Filtra y devuelve hasta max_imgs URLs válidas.
    """
    import urllib.parse as _up

    if not termino:
        return []

    # Bloquear IP protegida
    if any(ip in termino.lower() for ip in _IP_PROTEGIDA):
        print(f"[Imgs] IP protegida — omitiendo '{termino}'")
        return []

    # Intentar geocodificar el término: si es un lugar, forzar categoría 'lugar'
    geo = _geocode_place(termino)
    if geo:
        categoria = 'lugar'
        # Construir una query más específica para lugares (skyline / aerial / city)
        if geo.get('country'):
            query_en = f"{geo.get('name')} {geo.get('country')} city skyline"
        else:
            query_en = f"{geo.get('name')} city skyline"
        print(f"[Imgs] Geocodificado '{termino}' → {geo.get('name')}, {geo.get('country')}")
    else:
        categoria, query_en = _categorizar_termino(termino)
    print(f"[Imgs] '{termino}' → cat={categoria}, query='{query_en}'")

    urls:         list[str] = []
    headers_base: dict      = {"User-Agent": "Mozilla/5.0 Jarvis/1.0"}
    unsplash_key  = _ctx.get("UNSPLASH_ACCESS_KEY", lambda: "")()
    pexels_key    = _ctx.get("PEXELS_API_KEY",      lambda: "")()
    gsearch_key   = _ctx.get("GOOGLE_SEARCH_API_KEY", lambda: "")()
    gsearch_cx    = _ctx.get("GOOGLE_SEARCH_CX",    lambda: "")()

    def _agregar(url: str):
        if url and url not in urls and url.startswith("http") and _es_relevante_url(url):
            urls.append(url)

    def _unsplash(query: str, orientation: str = "landscape"):
        if not unsplash_key or len(urls) >= max_imgs:
            return
        try:
            r = requests.get(
                f"https://api.unsplash.com/search/photos"
                f"?query={_up.quote(query)}&per_page={max_imgs + 2}"
                f"&page={random.randint(1, 2)}&orientation={orientation}&content_filter=high",
                timeout=8,
                headers={**headers_base, "Authorization": f"Client-ID {unsplash_key}"},
            )
            if r.status_code == 200:
                for item in r.json().get("results", []):
                    _agregar(item.get("urls", {}).get("regular", ""))
                    if len(urls) >= max_imgs:
                        break
        except Exception as e:
            print(f"[Imgs-Unsplash] {e}")

    def _pexels(query: str, orientation: str = "landscape"):
        if not pexels_key or len(urls) >= max_imgs:
            return
        try:
            r = requests.get(
                f"https://api.pexels.com/v1/search"
                f"?query={_up.quote(query)}&per_page={max_imgs + 2}&orientation={orientation}",
                timeout=8,
                headers={**headers_base, "Authorization": pexels_key},
            )
            if r.status_code == 200:
                for foto in r.json().get("photos", []):
                    _agregar(
                        foto.get("src", {}).get("large2x", "")
                        or foto.get("src", {}).get("large", "")
                    )
                    if len(urls) >= max_imgs:
                        break
        except Exception as e:
            print(f"[Imgs-Pexels] {e}")

    def _google_custom(query: str):
        if not gsearch_key or not gsearch_cx or len(urls) >= max_imgs:
            return
        try:
            r = requests.get(
                f"https://www.googleapis.com/customsearch/v1"
                f"?key={gsearch_key}&cx={gsearch_cx}"
                f"&q={_up.quote(query)}&searchType=image"
                f"&num={max_imgs + 2}&safe=active&imgSize=large&imgType=photo",
                timeout=8,
                headers=headers_base,
            )
            if r.status_code == 200:
                for item in r.json().get("items", []):
                    w = item.get("image", {}).get("width",  999)
                    h = item.get("image", {}).get("height", 999)
                    if w >= 200 and h >= 150:
                        _agregar(item.get("link", ""))
                    if len(urls) >= max_imgs:
                        break
        except Exception as e:
            print(f"[Imgs-Google] {e}")

    def _inaturalist(query: str):
        """Fotos de biodiversidad desde iNaturalist."""
        if len(urls) >= max_imgs:
            return
        try:
            r = requests.get(
                f"https://api.inaturalist.org/v1/taxa"
                f"?q={_url_quote(query)}&per_page=1&order_by=observations_count",
                timeout=6,
                headers=headers_base,
            )
            if r.status_code != 200 or not r.json().get("results"):
                return
            taxon = r.json()["results"][0]
            foto  = taxon.get("default_photo", {})
            main  = foto.get("medium_url", "")
            if main:
                _agregar(main.replace("medium", "large"))
            tid = taxon.get("id")
            if tid and len(urls) < max_imgs:
                ro = requests.get(
                    f"https://api.inaturalist.org/v1/observations"
                    f"?taxon_id={tid}&per_page=8"
                    f"&order_by={random.choice(['votes','faves','id'])}&photos=true",
                    timeout=6,
                    headers=headers_base,
                )
                if ro.status_code == 200:
                    for obs in ro.json().get("results", []):
                        for ph in obs.get("photos", [])[:1]:
                            _agregar(ph.get("url", "").replace("square", "large"))
                        if len(urls) >= max_imgs:
                            break
        except Exception as e:
            print(f"[Imgs-iNat] {e}")

    # ── Estrategia por categoría ─────────────────────────────────────────────

    if categoria == 'persona':
        nombre_wiki = query_en.replace(" portrait photograph", "").strip()
        for u in _buscar_img_wikimedia(nombre_wiki):
            _agregar(u)
        _unsplash(query_en, orientation="portrait")
        _pexels(query_en,   orientation="portrait")

    elif categoria == 'lugar':
        for u in _buscar_img_wikimedia(query_en):
            _agregar(u)
        _google_custom(query_en)
        _unsplash(query_en)

    elif categoria == 'naturaleza':
        _inaturalist(query_en)
        _unsplash(query_en)
        if len(urls) < max_imgs:
            _pexels(query_en)

    elif categoria in ('lab', 'ciencia'):
        for u in _buscar_img_wikimedia(query_en):
            _agregar(u)
        _unsplash(query_en)
        if len(urls) < max_imgs:
            _pexels(query_en)

    else:  # genérico
        _unsplash(query_en)
        _pexels(query_en)
        _google_custom(query_en)

    # Fallback final — Wikimedia
    if not urls:
        for u in _buscar_img_wikimedia(query_en):
            _agregar(u)

    print(f"[Imgs] TOTAL '{termino}': {len(urls)} urls")
    return urls[:max_imgs]


# =============================================================================
# 4. GALERÍA HTML
# =============================================================================

def html_galeria(termino: str, urls: list[str]) -> str:
    """
    Genera HTML de galería horizontal para QTextBrowser.
    Máximo 4 imágenes. Cada imagen es un enlace img: para vista ampliada.
    """
    if not urls:
        return (
            f'<p style="color:#445566;font-size:12px;font-style:italic;">'
            f'No encontré imágenes de {termino}</p>'
        )
    n     = min(len(urls), 4)
    shown = urls[:n]
    w     = max(100, (640 - (n - 1) * 6) // n)
    html  = (
        f'<p style="color:#4db8ff;font-size:12px;font-weight:bold;margin:4px 0 6px 0;">'
        f'🖼 {termino}</p>'
        f'<table cellspacing="6" cellpadding="0"><tr>'
    )
    for url in shown:
        html += (
            f'<td><a href="img:{url}">'
            f'<img src="{url}" width="{w}" height="{w}" '
            f'style="border-radius:6px;object-fit:cover;"/>'
            f'</a></td>'
        )
    html += '</tr></table>'
    return html


# =============================================================================
# 5. GENERACIÓN POR IA (placeholder)
# =============================================================================

def generar_imagen(prompt: str, chat_widget=None) -> bool:
    """
    Genera una imagen a partir de un prompt usando IA.

    ESTADO ACTUAL: Pendiente de conectar API de generación de imágenes.
    Opciones planeadas:
      - Stability AI (Stable Diffusion XL)
      - DALL·E 3 (OpenAI)
      - Ideogram / Flux

    Por ahora avisa al usuario y devuelve False.
    """
    _hablar(
        "La generación de imágenes por IA todavía no está conectada. "
        "Pronto lo tendrás disponible.",
        chat_widget,
    )
    aviso = (
        '<p style="color:#ffaa44;font-size:13px;">'
        '⚙️ <b>Generación de imágenes</b>: módulo pendiente de conectar.<br>'
        '<span style="color:#8899bb;font-size:12px;">'
        f'Prompt recibido: <i>"{prompt}"</i><br>'
        'Cuando agregues la API (Stability AI / DALL·E / Flux), '
        'este agente la usará automáticamente.'
        '</span></p>'
    )
    _bridge_html(_burbuja(aviso))
    _bridge_scroll()
    return False


# =============================================================================
# FUNCIÓN PRINCIPAL DEL AGENTE
# =============================================================================

def ejecutar(accion: str, params: dict, chat_widget=None) -> bool:
    """
    Punto de entrada único desde dispatcher.py.

    Acciones soportadas:
      "buscar"  → params: {termino, max_imgs?}
                  Busca imágenes en APIs y muestra galería.
      "galeria" → params: {termino, urls}
                  Muestra una galería con URLs ya obtenidas.
      "generar" → params: {prompt}
                  Genera imagen por IA (pendiente de API).

    Devuelve True si procesó la acción.
    """
    if accion == "buscar":
        termino = params.get("termino", "").strip()
        if not termino:
            return False
        try:
            max_i = max(1, min(10, int(params.get("max_imgs", 3))))
        except (TypeError, ValueError):
            max_i = 3

        def _worker():
            urls = buscar_imagenes(termino, max_imgs=max_i)
            if urls:
                _bridge_html(_burbuja(html_galeria(termino, urls)))
                _bridge_scroll()
            else:
                sin_imgs = (
                    f'<p style="color:#445566;font-size:12px;font-style:italic;">'
                    f'No encontré imágenes de <b>{termino}</b></p>'
                )
                _bridge_html(_burbuja(sin_imgs))
                _bridge_scroll()

        threading.Thread(target=_worker, daemon=True).start()
        return True

    if accion == "galeria":
        termino = params.get("termino", "")
        urls    = params.get("urls", [])
        if urls:
            _bridge_html(_burbuja(html_galeria(termino, urls)))
            _bridge_scroll()
        return True

    if accion == "generar":
        prompt = params.get("prompt", "").strip()
        if not prompt:
            return False
        return generar_imagen(prompt, chat_widget)

    print(f"[agent_images] Acción desconocida: '{accion}'")
    return False
