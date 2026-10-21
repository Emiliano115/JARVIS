# J.A.R.V.I.S.

**Asistente de escritorio para Windows, en español.** Jarvis combina IA, voz y herramientas para ayudarte a controlar el PC, organizar tareas y consultar información desde una sola aplicación.

[Descargar la última versión](https://github.com/Emiliano115/JARVIS/releases/latest) · [Ver el código](https://github.com/Emiliano115/JARVIS) · [Reportar un problema](https://github.com/Emiliano115/JARVIS/issues)

![Windows](https://img.shields.io/badge/Windows-10%20%7C%2011-blue) ![Python](https://img.shields.io/badge/Python-3.12-blue) ![Idioma](https://img.shields.io/badge/idioma-espa%C3%B1ol-orange)

## Qué puedes hacer

- **Hablar con Jarvis** por texto o voz y elegir entre proveedores de IA compatibles.
- **Controlar el PC:** abrir y administrar aplicaciones, ajustar volumen y brillo, buscar archivos y manejar teclado, ratón y pantalla.
- **Organizarte:** crear notas, alarmas, recordatorios, rutinas y recuerdos locales.
- **Usar Google:** consultar Gmail, buscar y preparar correos, gestionar Calendar y Tasks, buscar contactos y archivos de Drive.
- **Consultar información:** buscar en la web, ver noticias y clima, calcular, traducir y consultar mapas.
- **Usar la pantalla y los gestos:** leer texto con OCR, pedir análisis visual y controlar el equipo con gestos si tienes cámara.

> Algunas funciones requieren claves de servicios externos, autorización de Google, conexión a Internet o permisos de Windows. La generación de imágenes con IA todavía no está conectada.

## Pruébalo

Ejemplos de instrucciones:

- “Jarvis, abre Spotify y baja el volumen”.
- “Busca los correos que me envió la NASA sobre Space Apps Challenge”.
- “Crea un recordatorio para llamar a mamá mañana”.
- “Lee el texto de la pantalla”.
- “Busca información sobre el clima en Bogotá”.

## Descargar

La forma más sencilla es descargar el ZIP de Windows desde [Releases](https://github.com/Emiliano115/JARVIS/releases/latest), extraerlo y abrir `Jarvis.exe`. Mantén juntos el ejecutable y los archivos que vienen en la carpeta del paquete.

Si no hay una versión publicada, puedes instalar Jarvis desde el código fuente siguiendo los pasos de abajo.

## Instalar desde el código

**Necesitas:** Windows 10 u 11 de 64 bits y Python 3.12. Un micrófono es opcional. Tesseract OCR es opcional y se necesita para localizar texto en pantalla mediante OCR.

Abre PowerShell y ejecuta:

```powershell
git clone https://github.com/Emiliano115/JARVIS.git
cd JARVIS
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe Jarvis_main.py
```

## Configurar la IA

1. Abre **Configuración** en Jarvis.
2. En **Modelo de IA**, agrega una clave API de un proveedor compatible y elige un modelo.
3. Guarda los cambios y prueba un mensaje.

La disponibilidad, los límites y los posibles cobros dependen del proveedor y de tu cuenta. No publiques ni compartas tus claves API.

## Conectar Google

Gmail, Calendar, Tasks, Contacts y Drive requieren una aplicación OAuth de Google:

1. Crea un proyecto en [Google Cloud Console](https://console.cloud.google.com/) y habilita las APIs que quieras usar.
2. Crea credenciales OAuth para una aplicación de escritorio.
3. Guarda el archivo de credenciales como `credentials.json` en la carpeta de Jarvis.
4. Activa la integración desde **Extensiones** y completa la autorización en el navegador.

`credentials.json` y `token.json` contienen información sensible. No los subas al repositorio ni los compartas.

## Privacidad

- Jarvis guarda localmente notas, configuración, memoria e historial.
- Al conversar, el texto se envía al proveedor de IA seleccionado para generar la respuesta.
- La transcripción de voz y el análisis visual pueden enviar audio o una captura al servicio de IA correspondiente cuando usas esas funciones.
- El video de la cámara para gestos se procesa para reconocer movimientos; Jarvis no necesita grabarlo para esa función.
- Puedes administrar permisos y borrar recuerdos desde la aplicación. Consulta también [la política de privacidad del proyecto](Jarvis-sitio-web/privacy.html).

## Estado y limitaciones

- Jarvis está diseñado actualmente para **Windows 10 y 11**. Linux y macOS no están soportados todavía.
- Las funciones de voz, pantalla, gestos, Google y búsqueda dependen de los dispositivos, permisos, claves o servicios configurados.
- La generación de imágenes por IA está pendiente de integración.

## Contribuir

¿Encontraste un error o tienes una idea? [Abre un issue](https://github.com/Emiliano115/JARVIS/issues) con los pasos para reproducirlo, lo que esperabas y lo que ocurrió. No incluyas claves API, tokens, correos privados ni capturas con información sensible.

Antes de aceptar contribuciones o permitir la reutilización del código, el proyecto necesita publicar una licencia. La visibilidad pública del repositorio, por sí sola, no concede una licencia de uso.

