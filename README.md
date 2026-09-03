# J.A.R.V.I.S. — Asistente de IA Personal para Windows

Asistente de escritorio con voz, visión e interfaz gráfica estilo HUD, inspirado en el asistente de Iron Man. Escucha comandos de voz o texto, interpreta la intención con modelos de lenguaje (Groq / Gemini / Claude) y despacha la acción al agente correspondiente: control del PC, búsqueda web, notas y recordatorios, correo y calendario de Google, imágenes, y observación/control de pantalla.

> Proyecto en español (Colombia). Toda la interacción por voz y texto está diseñada para responder en español.

---

## 📑 Tabla de contenidos

- [Descripción general](#-descripción-general)
- [Características principales](#-características-principales)
- [Arquitectura del proyecto](#-arquitectura-del-proyecto)
- [Requisitos](#-requisitos)
- [Instalación (modo desarrollo)](#-instalación-modo-desarrollo)
- [Configuración de claves API](#-configuración-de-claves-api)
- [Integración con Google (OAuth)](#-integración-con-google-oauth)
- [Permisos de Windows](#-permisos-de-windows)
- [Uso](#-uso)
- [Compilar el ejecutable (PyInstaller)](#-compilar-el-ejecutable-pyinstaller)
- [Datos y almacenamiento local](#-datos-y-almacenamiento-local)
- [Solución de problemas](#-solución-de-problemas)
- [Privacidad y advertencias de seguridad](#-privacidad-y-advertencias-de-seguridad)
- [Licencia](#-licencia)

---

## 🧠 Descripción general

Jarvis es una aplicación de escritorio (PySide6 + Qt WebEngine) que combina:

- Un **cerebro de IA** que recibe una instrucción en lenguaje natural y devuelve un arreglo JSON de acciones a ejecutar (`Jarvis_main.py`), usando **Groq (Llama 3.3 70B)** como motor principal y **Google Gemini** como apoyo para búsquedas/análisis, con **Anthropic Claude** como respaldo para matemáticas y física avanzada.
- Un conjunto de **agentes especializados**, cada uno en su propio módulo, que reciben las acciones ya decodificadas y las ejecutan.
- Una **interfaz gráfica** tipo HUD (`V5.html`, renderizada en un `QWebEngineView`) con animaciones en canvas, consola de chat, mapa interactivo (Leaflet + OpenStreetMap) y un overlay flotante para control de pantalla.
- Un **motor de voz** con detección de palabra de activación ("Jarvis"), transcripción con Groq Whisper y síntesis de voz con fallback en cadena (ElevenLabs → Edge TTS → SAPI5 de Windows).

El proyecto está pensado **exclusivamente para Windows**, ya que depende de APIs nativas (`win32gui`, `win32con`, WMI, `pycaw`, `winsound`, `winreg`, `SAPI5`, etc.).

---

## ✨ Características principales

### 🎙️ Voz e interacción
- Escucha continua con palabra de activación "Jarvis" (y variantes fonéticas) usando `sounddevice` + **Groq Whisper** (`whisper-large-v3-turbo`) para transcripción.
- Grabación manual desde el botón de micrófono de la interfaz, con detección de silencio para cortar la grabación.
- Síntesis de voz en cadena de respaldo: **ElevenLabs** (si hay API key) → **Edge TTS** (voz neuronal gratuita) → **SAPI5** (Windows, último recurso).
- Modo de asistencia para dictar correos: Jarvis muestra destinatario y asunto, solicita confirmación explícita y permite cancelar antes de enviar.
- Lectura inteligente de pantalla: el comando "lee la pantalla" extrae texto visible mediante OCR local, sin guardar capturas ni consumir tokens de IA.
- Perfiles personalizados de accesibilidad: Estándar, Lectura breve y Lectura detallada, seleccionables desde Configuración.
- Comandos configurables para accesibilidad y gestos: puedes asignar frases propias a leer pantalla, activar, desactivar o calibrar gestos.
- Recuperación del modo gestos: "recalibra el modo gestos" lo detiene, reajusta el pellizco y lo vuelve a activar automáticamente.
- Memoria conversacional: historial de sesión, resolución de referencias pronominales ("eso", "ábrelo", "el anterior"), detección de solicitudes de "extiéndeme la respuesta" y aprendizaje pasivo de datos del usuario (nombre, ciudad, trabajo, preferencias).

### 🖥️ Interfaz visual (`V5.html`)
- HUD animado en canvas con anillos, fondo de hexágonos tipo "plexus" y consola neuronal de chat.
- Mapa interactivo integrado (Leaflet + tiles oscuros de CARTO + puntos de interés vía Overpass API de OpenStreetMap), con geocodificación por Nominatim y Open-Meteo.
- Overlay flotante ("HUD" de pantalla) con botones de chat rápido, configuración, comandos, extensiones, micrófono y visor de pantalla.
- Diálogos de **Configuración**, **Comandos** y **Extensiones** (activar/desactivar cada integración de forma independiente).

### 📝 Notas, alarmas y recordatorios (`agent_notas.py`)
- Notas con título automático, búsqueda, edición y eliminación (SQLite local: `jarvis_notas.db`).
- Alarmas únicas o recurrentes (diaria/semanal) con aviso sonoro (`winsound`).
- Recordatorios con fecha/hora que Jarvis anuncia por voz.
- Memoria de sesión (clave → valor) y un resumen inteligente de "todo lo que Jarvis recuerda hoy".
- Un hilo de fondo revisa cada 30 segundos si hay alarmas o recordatorios que disparar.

### 🔍 Búsqueda, noticias y clima (`agent_search.py`)
- Búsqueda web con **Gemini + Google Search grounding**, con respaldo en **Groq** si Gemini falla.
- Noticias vía **NewsAPI** (si hay clave) o **Google News RSS** (sin clave).
- Clima actual y pronóstico del día vía **Open-Meteo** (gratuito, sin API key).
- Cálculo matemático: expresiones simples resueltas con `eval` seguro; física/matemática avanzada (derivadas, integrales, mecánica lagrangiana, etc.) resuelta con la **API de Anthropic Claude**, renderizando LaTeX.
- Apertura de rutas en Google Maps para consultas de tiempo de viaje.

### 🖼️ Imágenes (`agent_images.py`)
- Búsqueda multi-fuente categorizada automáticamente (personas, lugares, laboratorio, ciencia/matemáticas, naturaleza, genérico): **Unsplash**, **Pexels**, **Google Custom Search**, **Wikimedia/Wikipedia**, **iNaturalist**.
- Filtro de propiedad intelectual protegida (Marvel, Disney, videojuegos, etc.) para no mostrar ese contenido.
- Galería HTML integrada en el chat con vista previa ampliada.
- Generación de imágenes por IA: **placeholder** — el módulo está preparado pero aún no está conectado a una API de generación (Stability AI / DALL·E / Flux); actualmente solo informa al usuario.

### 💻 Control del PC (`agent_pc.py`)
- Abrir, cerrar, minimizar y maximizar aplicaciones (con puntuación difusa de coincidencia de nombres vía `thefuzz`).
- Control de volumen absoluto y relativo (`pycaw`, con respaldo por teclas multimedia) y de brillo de pantalla (WMI).
- Apagar, reiniciar, bloquear, suspender e hibernar el equipo.
- "Modos de trabajo" configurables que abren varias apps a la vez (por defecto: `estudio`, `gaming`, `programacion`).
- Búsqueda de archivos en disco con filtrado por extensión y coincidencia difusa; aprendizaje de rutas de apps y archivos usados.

### 🖱️ Pantalla y gestos (`agent_screen.py`)
- Captura de pantalla efímera (nunca se guarda en disco) para análisis visual bajo demanda.
- Lectura local de texto visible mediante OCR con el comando "lee la pantalla"; requiere Tesseract OCR y los idiomas español e inglés.
- Análisis de pantalla con modelos multimodales: **Groq Llama-4 Maverick/Scout** o **Gemini**, describiendo en lenguaje natural lo que se ve.
- Control explícito de mouse y teclado: clic (por coordenadas, cursor actual u objetivo detectado por OCR con `pytesseract`), escritura de texto, teclas permitidas, scroll y zoom.
- Modo de **control por gestos** vía cámara (OpenCV + MediaPipe): mover el cursor con la palma, "pellizco" pulgar-índice para clic/arrastre, pulgar-medio para clic derecho, gestos de dos dedos para scroll, y zoom con dos manos abiertas.
- Activación/desactivación del modo de gestos mediante aplausos detectados con `sounddevice`.

### 📧 Integración con Google (`agent_google.py`)
- **Gmail**: leer bandeja de entrada, buscar correos, preparar correos con dictado y enviarlos solo tras confirmación explícita, además de moverlos a la papelera.
- **Google Calendar**: ver, crear, editar y eliminar eventos.
- **Google Tasks**: ver, crear, editar y eliminar tareas.
- **Google Contacts**: búsqueda de contactos (nombre, correo, teléfono).
- **Google Drive**: búsqueda de archivos con enlace directo.

Jarvis es una herramienta de asistencia tecnológica. No es un dispositivo médico ni sustituye a un cuidador o a un profesional.

---

## 🏗️ Arquitectura del proyecto

```
.
├── Jarvis_main.py          # Orquestador central: UI, voz, cerebro IA, dispatcher de acciones
├── agent_notas.py          # Notas, alarmas, recordatorios y memoria de sesión (SQLite)
├── agent_images.py         # Búsqueda y (futura) generación de imágenes
├── agent_screen.py         # Observación de pantalla, control de mouse/teclado y gestos
├── agent_search.py         # Búsqueda web, noticias, clima y cálculos
├── agent_pc.py             # Apps, volumen, brillo, energía y archivos
├── agent_google.py         # Gmail, Calendar, Tasks, Contacts, Drive
├── V5.html                 # Interfaz gráfica (HUD) renderizada en QWebEngineView
├── requirements.txt        # Dependencias de Python
├── build_release.ps1       # Script de compilación con PyInstaller
└── README_DISTRIBUCION.md  # Notas internas de distribución/empaquetado
```

Cada agente expone una función `init(ctx)` para recibir el contexto compartido (funciones de voz, bridge de la UI, claves, memoria, etc.) y una función `ejecutar(accion, params, chat_widget)` que actúa como punto de entrada único invocado desde el *dispatcher* en `Jarvis_main.py`.

---

## ⚙️ Requisitos

### Sistema operativo
- **Windows 10/11 (64-bit)**. El proyecto usa APIs específicas de Windows (`pywin32`, WMI, SAPI5, `winsound`, `winreg`) y **no es multiplataforma**.

### Software
- **Python 3.12** (recomendado; usado en el script de build).
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) instalado y disponible en el `PATH`, con los paquetes de idioma **español e inglés** (`spa` + `eng`), necesario para que `agent_screen.py` pueda ubicar objetivos de clic por texto en pantalla.
- Una cámara web (opcional) para el control por gestos.
- Un micrófono (opcional pero recomendado) para el uso por voz.

### Dependencias de Python
Instaladas desde `requirements.txt`:

```
PySide6, requests, numpy, Pillow, sounddevice, pywin32, keyboard,
pyttsx3, pygame, word2number-es, thefuzz, python-Levenshtein,
pyautogui, opencv-python, mediapipe, google-auth,
google-api-python-client, google-auth-httplib2, google-auth-oauthlib,
comtypes, pycaw, pytesseract
```

### Dependencias opcionales (no incluidas en `requirements.txt`)
Algunas funciones se degradan de forma segura si faltan, pero para tener todo el comportamiento descrito instala también:

```powershell
pip install edge-tts wmi pyperclip pygetwindow
```

| Paquete | Para qué se usa |
|---|---|
| `edge-tts` | Voz neuronal gratuita (segundo eslabón del TTS, antes de caer a SAPI5) |
| `wmi` | Control de brillo de pantalla |
| `pyperclip` | Copiar al portapapeles en la función de mapas mentales / integración con Eraser |
| `pygetwindow` | Enfocar ventanas del navegador al automatizar el pegado en Eraser |

> Nota: la generación de mapas mentales usa un servidor MCP externo (`app.eraser.io`) como parte del flujo experimental incluido en el código; es opcional y no bloquea el resto de funciones si no está disponible.

---

## 🚀 Instalación (modo desarrollo)

```powershell
# 1. Clonar el repositorio
git clone https://github.com/Emiliano115/JARVIS.git
cd JARVIS

# 2. Crear un entorno virtual
python -m venv .venv
.venv\Scripts\activate

# 3. Instalar dependencias
pip install -r requirements.txt
pip install edge-tts wmi pyperclip pygetwindow   # opcionales recomendados

# 4. Instalar Tesseract OCR y agregarlo al PATH (necesario para clic por texto en pantalla)

# 5. Configurar las claves API (ver siguiente sección)

# 6. Ejecutar
python Jarvis_main.py
```

En el primer arranque, Jarvis:
1. Pregunta si quieres escanear aplicaciones en modo **Normal** (solo menú inicio, rápido) o **Power** (incluye Microsoft Store, más lento).
2. Solicita permisos locales para escaneo de apps, micrófono, pantalla y control de teclado/ratón (ver [Permisos de Windows](#-permisos-de-windows)).
3. Abre la interfaz en pantalla completa y saluda por voz.

---

## 🔑 Configuración de claves API

Jarvis busca sus claves en dos lugares, en este orden:

1. Un **servidor remoto de configuración** (`_cargar_keys_desde_servidor`), apuntando por defecto a la infraestructura propia del autor del proyecto. **Para un uso propio/autoalojado se recomienda ignorar este mecanismo** y depender solo del archivo `.env` local.
2. Un archivo **`.env`** ubicado en la carpeta de datos de usuario (`%LOCALAPPDATA%\Jarvis` en la versión compilada, o la carpeta del proyecto en modo desarrollo).

Crea un archivo `.env` con las claves que necesites (todas son opcionales; cada función se desactiva o usa un modo gratuito si falta su clave):

```env
# Motor de IA principal (obligatorio para el cerebro de acciones)
GROQ_API_KEY=tu_clave_groq
GROQ_API_KEY_2=clave_groq_adicional_opcional

# Búsqueda web con grounding y respaldo del cerebro
GEMINI_API_KEY=tu_clave_gemini
GEMINI_API_KEY_2=clave_gemini_adicional_opcional

# Matemática/física avanzada con LaTeX
ANTHROPIC_API_KEY=tu_clave_anthropic

# Noticias (si falta, se usa Google News RSS sin clave)
NEWS_API_KEY=tu_clave_newsapi

# Búsqueda de imágenes
UNSPLASH_ACCESS_KEY=tu_clave_unsplash
PEXELS_API_KEY=tu_clave_pexels
GOOGLE_SEARCH_API_KEY=tu_clave_google_custom_search
GOOGLE_SEARCH_CX=tu_id_de_motor_de_busqueda_personalizado

# Voz de alta calidad (opcional; si falta, se usa Edge TTS o SAPI5)
ELEVENLABS_API_KEY=tu_clave_elevenlabs
```

| Función | Clave requerida | Comportamiento sin clave |
|---|---|---|
| Interpretar comandos (cerebro) | `GROQ_API_KEY` | Sin esta clave (o `GEMINI_API_KEY`), Jarvis no puede procesar comandos por IA |
| Búsqueda web / análisis | `GEMINI_API_KEY` | Cae a Groq como motor de búsqueda |
| Transcripción de voz | `GROQ_API_KEY` | La escucha por voz queda desactivada |
| Matemática avanzada | `ANTHROPIC_API_KEY` | Solo funcionan cálculos simples con `eval` seguro |
| Noticias | `NEWS_API_KEY` | Usa Google News RSS (gratis, sin clave) |
| Clima | *(ninguna)* | Siempre funciona vía Open-Meteo |
| Imágenes | `UNSPLASH_ACCESS_KEY` / `PEXELS_API_KEY` / `GOOGLE_SEARCH_*` | Se omite esa fuente; se intenta igual con Wikimedia/iNaturalist |
| Voz ElevenLabs | `ELEVENLABS_API_KEY` | Usa Edge TTS o SAPI5 automáticamente |

---

## 🔐 Integración con Google (OAuth)

Las funciones de Gmail, Calendar, Tasks, Contacts y Drive requieren autorización **OAuth 2.0** de Google con los siguientes *scopes* (definidos en `Jarvis_main.py`):

```
https://www.googleapis.com/auth/calendar
https://www.googleapis.com/auth/tasks
https://mail.google.com/
https://www.googleapis.com/auth/drive
https://www.googleapis.com/auth/contacts
```

El código incluido delega el intercambio del código OAuth a un servidor propio del autor (`SERVIDOR_AUTH`) que actúa como *relay*. **Para tu propio despliegue necesitas:**

1. Crear un proyecto en [Google Cloud Console](https://console.cloud.google.com/) y habilitar las APIs de Calendar, Tasks, Gmail, Drive y People.
2. Generar credenciales OAuth (tipo aplicación de escritorio o web, según tu flujo).
3. Adaptar `agent_google._flujo_oauth_propio()` para usar tus propias credenciales, o implementar tu propio servidor de intercambio de tokens.

El token resultante se guarda localmente en `token.json` dentro de la carpeta de datos de usuario y **nunca debe subirse al repositorio**.

Cada integración de Google se puede activar/desactivar de forma independiente desde el diálogo **Extensiones** de la interfaz (botón 🔌), sin necesidad de tocar el código.

---

## 🛡️ Permisos de Windows

Al primer arranque, Jarvis pide confirmación explícita (con opción de rechazar) para cada una de estas capacidades. Puedes cambiarlas después desde **Configuración → Permisos locales**:

| Permiso | Qué habilita | Módulo afectado |
|---|---|---|
| Escaneo de aplicaciones | Buscar programas instalados y sus rutas para poder abrirlos por nombre | `agent_pc.py` |
| Micrófono | Escuchar comandos de voz (palabra de activación y comandos manuales) | Motor de voz en `Jarvis_main.py` |
| Pantalla | Capturar temporalmente la pantalla para verla o analizarla con IA | `agent_screen.py` |
| Teclado y ratón | Ejecutar clics, escritura, teclas, scroll, zoom y control por gestos | `agent_screen.py` |

Si un permiso está desactivado, la acción correspondiente se rechaza con un aviso hablado, sin necesidad de privilegios de administrador de Windows en ningún caso.

---

## ▶️ Uso

- **Por voz**: di "Jarvis" seguido de tu instrucción (por ejemplo, *"Jarvis, abre Spotify y sube el volumen"*). También puedes decir el comando en la misma frase si Jarvis logra transcribirlo junto a la palabra de activación.
- **Por texto**: escribe en el campo de la consola neuronal (icono de chat en la barra inferior) o en el mini-chat del overlay de pantalla.
- **Comandos combinados**: una sola instrucción puede generar varias acciones a la vez (por ejemplo, buscar información y mostrar un mapa).
- **Catálogo de comandos**: el botón ⌘ de la interfaz abre una guía rápida con ejemplos de frases naturales para cada categoría (apps, pantalla, voz, productividad, web/mapas).
- **Detener el habla de Jarvis**: di "silencio", "para", "basta" o similar para interrumpir la síntesis de voz en curso.
- **Leer pantalla sin IA**: escribe "lee la pantalla". Jarvis mostrará y leerá el texto visible detectado localmente.
- **Recuperar gestos**: di "recalibra el modo gestos", mantén la mano visible y pellizca varias veces durante la calibración.

---

## 📦 Compilar el ejecutable (PyInstaller)

El repositorio incluye `build_release.ps1`, que automatiza la creación de un entorno de compilación aislado y empaqueta la aplicación con PyInstaller usando un archivo de especificación `Jarvis.spec` (debe existir en la raíz del proyecto).

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\build_release.ps1
```

El resultado queda en `dist\Jarvis\Jarvis.exe`. Se distribuye la **carpeta completa**, no solo el ejecutable, ya que incluye recursos de solo lectura como `V5.html` y (si aplica) el modelo `hand_landmarker.task` usado como respaldo de MediaPipe Tasks API para el reconocimiento de manos.

Recomendaciones para reducir falsos positivos de antivirus (detalladas en `README_DISTRIBUCION.md`):
- Firmar el ejecutable con un certificado de firma de código.
- Publicar el código fuente y el hash SHA-256 del paquete.
- Usar empaquetado `onedir` (carpeta) en lugar de un ejecutable autoextraíble.
- No pedir privilegios de administrador innecesarios ni desactivar Windows Defender.

La aplicación también verifica automáticamente si hay una versión más reciente publicada como *release* de GitHub y ofrece descargarla y aplicarla al reiniciar.

---

## 🗂️ Datos y almacenamiento local

Toda la información generada por el uso de Jarvis se guarda **localmente**, en `%LOCALAPPDATA%\Jarvis` (versión compilada) o en la carpeta del proyecto (modo desarrollo):

| Archivo | Contenido |
|---|---|
| `.env` | Claves API (si las configuraste manualmente) |
| `token.json` | Token OAuth de Google |
| `jarvis_config.json` | Preferencias y permisos de la aplicación |
| `jarvis_notas.db` | Notas, alarmas, recordatorios y memoria de sesión (SQLite) |
| `jarvis_memoria.json` | Datos aprendidos del usuario (nombre, ciudad, preferencias, etc.) |
| `jarvis_historial.json` / `memoria_chat.json` | Historial de conversación |
| `memoria_apps.txt` / `memoria_archivos.txt` | Rutas de aplicaciones y archivos aprendidos |
| `memoria_auto_normal.json` / `memoria_auto_power.json` | Caché del escaneo de aplicaciones del sistema |
| `jarvis_tokens.json` | Conteo de tokens de uso de la IA |

Ninguno de estos archivos debe compartirse ni subirse a un repositorio público.

---

## 🧯 Solución de problemas

**"Sin conexión a la IA" / "El servidor de keys no respondió"**
El servidor remoto de configuración puede tardar hasta 2 minutos en responder (arranque en frío). Espera y reintenta, o crea tu propio archivo `.env` local con al menos `GROQ_API_KEY` o `GEMINI_API_KEY`.

**Groq o Gemini devuelven error 429**
Es un límite de tasa (*rate limit*). Jarvis rota automáticamente entre varias claves si configuraste más de una (`GROQ_API_KEY_2`, `GEMINI_API_KEY_2`); si solo tienes una, espera un minuto.

**El control por gestos no activa la cámara**
Verifica que el permiso "Teclado y ratón" esté habilitado, que la cámara no esté en uso por otra aplicación y que `opencv-python`, `mediapipe` y `numpy` estén instalados. La consola imprime qué paquete falta si la detección no puede iniciar.

**El brillo de pantalla no cambia**
El control de brillo depende de WMI (`WmiMonitorBrightness`) y solo funciona en monitores/portátiles compatibles con ese estándar (típicamente pantallas internas de laptop).

**El clic por objetivo de texto no encuentra nada en pantalla**
Confirma que Tesseract OCR esté instalado y en el `PATH`, con los datos de idioma español e inglés.

**Las funciones de Google no responden**
Revisa que la extensión correspondiente esté activada en el diálogo **Extensiones** y que hayas completado el flujo OAuth (se abre el navegador la primera vez). Si cambiaste de credenciales, elimina `token.json` para forzar una nueva autorización.

**Falsos positivos de un antivirus con el `.exe` compilado**
Es un comportamiento conocido de ejecutables generados con PyInstaller sin firmar. Revisa la sección de compilación para mitigarlo, o ejecuta el proyecto en modo desarrollo con Python en lugar de usar el binario.

---

## 🔒 Privacidad y advertencias de seguridad

- **No subas datos sensibles al repositorio**: `.env`, `token.json`, `jarvis_config.json`, archivos de memoria (`jarvis_memoria.json`, `jarvis_historial.json`, `memoria_chat.json`), la base de datos `jarvis_notas.db`, ni cachés de escaneo de apps. Usa un `.gitignore` que los excluya.
- **Revoca cualquier token de Google que se haya expuesto accidentalmente** (por ejemplo, durante pruebas) antes de publicar el proyecto o compartir tu carpeta de datos.
- El código incluye, embebida, la URL de un **servidor propio del autor original** (`jarvis-server-j5ze.onrender.com`) usado para distribuir claves API y para el intercambio OAuth de Google. Si ejecutas este proyecto tal cual, tu aplicación intentará contactar ese servidor de terceros al iniciar. Si te importa la privacidad o quieres un despliegue totalmente propio, **reemplaza ese endpoint** por tu propia infraestructura o depende exclusivamente de tu archivo `.env` local.
- La captura de pantalla para análisis con IA es **efímera**: el código indica explícitamente que el frame capturado nunca se escribe en disco, pero sí se envía en base64 a la API de Groq o Gemini para su análisis (es decir, sale de tu equipo hacia un proveedor externo de IA).
- El control por gestos usa la cámara web; el video no se graba, pero se procesa en tiempo real para detectar manos.
- El asistente aprende y guarda pasivamente datos personales que menciones en conversación (nombre, ciudad, trabajo, preferencias) en `jarvis_memoria.json`. Puedes desactivarlo desde **Configuración → Privacidad de datos**.
- Todas las funciones que envían texto o imágenes a un proveedor de IA (Groq, Gemini, Anthropic, ElevenLabs) están sujetas a las políticas de privacidad de cada proveedor externo.

---

## 📄 Licencia

El código fuente analizado no incluye un archivo de licencia. Si vas a publicar o distribuir este proyecto, añade un archivo `LICENSE` que defina explícitamente los términos de uso, modificación y distribución antes de compartirlo públicamente.
