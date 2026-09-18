# Hoja de ruta de JARVIS v7

## Propósito

Convertir Jarvis en un asistente confiable para personas que necesitan controlar el PC, recordar tareas y recibir ayuda sin perder privacidad ni control.

## Principios

- Cada función debe resolver una necesidad concreta.
- Las acciones peligrosas requieren confirmación explícita.
- Si falla internet o una API, las funciones locales deben seguir disponibles.
- La memoria debe poder consultarse, corregirse y borrarse.
- Cada fase termina con una prueba observable.

## Fase 0: Base confiable - completada

**Personas beneficiadas:** usuarios nuevos y personas con conexión inestable.

**Trabajo realizado:**

- Se añadió `edge-tts` a las dependencias.
- Se corrigió el fallback Edge TTS -> SAPI5.
- Se incluyó Edge TTS en el empaquetado de PyInstaller.
- Se limpian los MP3 temporales cuando la reproducción termina o falla.
- Se valida la configuración al iniciar Jarvis.

**Criterio de éxito:** una configuración dañada no detiene el arranque y una respuesta puede hablar aunque un proveedor de voz no responda.

## Fase 1: Asistente accesible y seguro - completada

**Personas beneficiadas:** personas con baja visión, movilidad reducida o que usan Jarvis por voz.

**Pasos:**

1. Mostrar un estado visible de "procesando" y "listo". **Completado:** V5 cambia el indicador y la ventana nativa cambia su título; el estado vuelve a `LISTO` aunque el comando falle.
2. Añadir perfiles de texto: breve, estándar y detallado. **Completado:** los perfiles limitan caracteres y líneas en OCR y análisis visual antes de mostrar o leer la respuesta.
3. Pedir confirmación antes de apagar, cerrar aplicaciones, borrar memoria o enviar mensajes. **Completado:** las acciones sensibles requieren una confirmación explícita y caducan después de 60 segundos.
4. Añadir atajos de teclado y etiquetas accesibles a los controles. **Completado:** etiquetas ARIA y atajos `Esc`, `Ctrl+L` y `Ctrl+Shift+M`.

**Criterio de éxito:** el usuario sabe si Jarvis está trabajando y ninguna acción irreversible ocurre con una orden ambigua.

## Fase 2: Memoria privada y útil - completada

**Personas beneficiadas:** estudiantes, trabajadores remotos y personas con citas o tratamientos recurrentes.

**Pasos:**

1. Clasificar recuerdos mediante categoría y origen.
2. Añadir `memoria buscar <texto>` y `memoria olvidar <texto>`.
3. Mostrar el origen y la fecha de cada recuerdo.
4. Añadir exportación y borrado total. El borrado total requiere confirmación y no elimina las notas.

**Implementado:** migración SQLite compatible, memoria categorizada, búsqueda, olvido selectivo, exportación JSON y borrado del perfil personal junto con la memoria de sesión.

**Criterio de éxito:** encontrar o eliminar un dato guardado toma menos de 30 segundos.

## Fase 3: Rutinas de productividad - completada

**Personas beneficiadas:** usuarios que repiten cada día las mismas aplicaciones y documentos.

**Pasos:**

1. Crear rutinas con nombre, por ejemplo `modo estudio`. **Completado:** se guardan en SQLite.
2. Previsualizar las acciones antes de ejecutarlas. **Completado:** solo se aceptan acciones no destructivas.
3. Permitir programar, pausar y reanudar una rutina. **Completado:** el monitor local ejecuta las programadas.
4. Registrar qué acciones se ejecutaron y cuándo. **Completado:** historial por acción en `rutinas_log`.

**Criterio de éxito:** preparar una sesión de estudio o trabajo requiere una orden y puede deshacerse de forma segura.

## Integración adicional: avisos de Google Calendar

**Personas beneficiadas:** usuarios con reuniones, clases o citas que necesitan un aviso hablado sin depender solo de la notificación visual de Google.

- Jarvis revisa Calendar cada 30 segundos cuando Google Calendar está autorizado y conectado.
- Avisa por voz y chat cuando un evento empieza aproximadamente en 15 minutos.
- Cada evento se anuncia una sola vez durante la sesión.
- Se puede desactivar desde Configuración con `Avisar 15 minutos antes de eventos`.
- No inicia OAuth en segundo plano si no existe un token reutilizable.

## Fase 4: Diagnóstico y modo offline - completada

**Personas beneficiadas:** usuarios sin internet estable y quienes necesitan resolver fallos sin conocimientos técnicos.

**Pasos:**

1. Crear un diagnóstico de micrófono, audio, Edge TTS, SAPI5, red y APIs. **Completado:** comando directo `diagnóstico de Jarvis`.
2. Registrar errores localmente sin claves ni textos privados. **Completado:** `jarvis.log` rotativo con redacción de claves, tokens y correos.
3. Mantener comandos locales como volumen, apps, archivos y recordatorios. **Completado:** estos comandos se procesan antes de solicitar IA.
4. Mostrar una solución concreta para cada fallo detectado. **Completado:** el diagnóstico muestra estado, causa y recomendación por componente.

**Criterio de éxito:** Jarvis indica qué componente falló y continúa con las funciones que sí están disponibles. El diagnóstico no consume cuotas de IA ni inicia OAuth inesperadamente.

**Corrección posterior:** la creación local de recordatorios y la búsqueda local de archivos reconocen frases comunes sin IA. Los recordatorios se revisan al iniciar el monitor y cada 5 segundos; la búsqueda escanea el perfil local y no requiere internet.

## Fase 5: Calidad y mantenimiento - completada

**Personas beneficiadas:** todos los usuarios, especialmente quienes actualizan Jarvis con frecuencia o usan Windows con archivos bloqueados.

- **Autoprueba local:** el comando `autoprueba de Jarvis` verifica configuración, log, SQLite, Edge TTS y tablas de funciones offline sin usar red, OAuth ni IA.
- **Pruebas automatizadas:** `test_jarvis_local.py` cubre recordatorios, memoria categorizada y ejecución de rutinas.
- **SQLite robusto:** las conexiones ahora hacen `commit`, `rollback` y `close` siempre, evitando bloqueos de `jarvis_notas.db` en Windows.

**Criterio de éxito:** una actualización puede comprobar las funciones críticas con un comando y las regresiones locales se detectan antes de distribuir el ejecutable.

## Auditoría integral posterior

- Se eliminó la inserción directa de HTML no confiable en V5 mediante sanitización de etiquetas, atributos, enlaces y estilos.
- Se eliminó `shell=True` de la apertura de rutas aprendidas y se conservaron `os.startfile` y `Popen` con argumentos separados.
- Se evitaron alarmas duplicadas y bloqueos de SQLite al ejecutar rutinas programadas.
- Se garantizó la liberación de `Ctrl` cuando falla el zoom.
- Se validaron entradas de imágenes y fechas de Calendar.
- Se mejoró el foco de teclado y la adaptación de la interfaz a pantallas pequeñas.
- Se corrigió la resolución de rutas del spec de PyInstaller y se hizo opcional el modelo de gestos ausente.

**Riesgos pendientes conscientes:** OAuth sigue usando un token local protegido por los permisos del usuario; reducir los scopes de Google requiere una migración de autorización. Leaflet continúa cargándose desde CDN y necesita una decisión separada para incorporar una copia local.

## Fase 6: Distribución estable - en progreso

**Personas beneficiadas:** usuarios que quieren instalar Jarvis sin preparar Python ni el entorno de desarrollo.

- `Jarvis.spec` usa rutas estables y hooks estándar, sin recolectar módulos opcionales innecesarios.
- El modelo de gestos se incluye solo cuando existe y puede descargarse en tiempo de ejecución.
- [BUILD_WINDOWS.md](BUILD_WINDOWS.md) documenta instalación, compilación, comprobaciones y primera ejecución.
- El ejecutable debe validarse con `Autoprueba de Jarvis` y `Diagnóstico de Jarvis` antes de distribuirlo.

**Completado en este equipo:** se generó `dist\Jarvis\Jarvis.exe` y se verificaron `V5.html`, `jarvis_logo.svg`, PySide6, pygame, Edge TTS, Google API y MediaPipe dentro de `dist\Jarvis\_internal`. **Pendiente:** probarlo en una instalación limpia y ejecutar la autoprueba desde el `.exe`.

## Orden de ejecución

1. Completar la Fase 1 con estado visual y confirmaciones.
2. Añadir pruebas automatizadas para configuración, TTS y acciones destructivas.
3. Completar la Fase 2 antes de agregar nuevas integraciones externas.
4. Construir rutinas sobre permisos y registros ya probados.
5. Crear el diagnóstico offline como cierre de la versión v7.

## Ideas descartadas por ahora

- Integrar muchas redes sociales antes de tener permisos y auditoría.
- Guardar toda la conversación indefinidamente.
- Ejecutar apagados, borrados o envíos basándose solo en una coincidencia de voz.
- Añadir una interfaz decorativa sin mejorar una tarea concreta.
