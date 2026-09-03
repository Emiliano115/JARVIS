# Distribuir Jarvis en Windows

## Preparar el repositorio

Publica solo codigo y recursos necesarios. No subas `token.json`, `.env`, `jarvis_config.json`, memorias, bases de datos, claves API ni `.venv_gestos`.

El `gitignore` ya excluye los datos sensibles. Como el token de Google fue expuesto durante las pruebas, revocalo y genera uno nuevo antes de publicar.

## Construir

El build fija versiones compatibles de NumPy y OpenCV para evitar errores de extensiones C al iniciar el ejecutable empaquetado.

En PowerShell, desde la carpeta del proyecto:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\build_release.ps1
```

El resultado queda en `dist\Jarvis`. Distribuye la carpeta completa, no solo el `.exe`.

## Datos del usuario

La aplicacion guarda configuracion, memoria, caches, tokens y logs en `%LOCALAPPDATA%\Jarvis`.

Los recursos de solo lectura (`V5.html` y `hand_landmarker.task`) viajan dentro de la distribucion.

## GitHub Releases

1. Crea un repositorio sin datos personales.
2. Sube el codigo fuente y los archivos de build.
3. Comprime `dist\Jarvis` como `Jarvis-Windows-x64.zip`.
4. Crea un GitHub Release y adjunta el ZIP.
5. Publica el hash SHA-256:

```powershell
Get-FileHash .\Jarvis-Windows-x64.zip -Algorithm SHA256
```

## Reducir falsos positivos de Defender

No existe garantia de deteccion cero. Para reducir falsos positivos:

- Firma el ejecutable y el instalador con un certificado de firma de codigo.
- Publica hashes y codigo fuente.
- No empaquetes tokens, claves ni scripts ofuscados.
- Usa `onedir` y un instalador normal en vez de un ejecutable autoextraible.
- No desactives Defender ni pidas administrador sin necesidad.
- Explica los permisos de microfono, pantalla, teclado y archivos.
- Reporta una build firmada como falso positivo a Microsoft Security Intelligence si fuera necesario.

## Primer arranque

Jarvis pedira permisos locales por capacidad. Google se autoriza por OAuth y el token queda en la carpeta de datos del usuario, nunca en GitHub ni dentro del paquete.

## Actualizaciones

Jarvis comprueba en segundo plano si existe un GitHub Release posterior. Si encuentra uno, descarga el ZIP en `%LOCALAPPDATA%\Jarvis\updates`, pide confirmacion y reinicia para reemplazar la carpeta del programa. No tienes que buscar ni descargar el ZIP manualmente. La configuracion, memoria y tokens se conservan en `%LOCALAPPDATA%\Jarvis`.

Antes de extraer una actualizacion, Jarvis comprueba:

- El digest SHA-256 publicado por GitHub cuando el release lo incluye.
- Que el ZIP sea valido y contenga `Jarvis.exe`.
- Que ningun archivo del ZIP intente salir de la carpeta de actualizaciones.

## Prueba con usuarios

Realiza cada prueba con consentimiento y sin datos reales:

1. Usuario con movilidad reducida: activar gestos, usar clic y desplazamiento, y recuperar con "recalibra el modo gestos".
2. Usuario con baja vision: cambiar el perfil de accesibilidad y usar "lee la pantalla" en una pagina con dos columnas.
3. Usuario sin experiencia tecnica: dictar un correo de prueba y confirmar que Jarvis pide confirmacion antes de enviarlo.
4. En cada prueba registrar tarea, errores, tiempo aproximado, ayuda necesaria y sugerencia del usuario.
5. No guardar capturas, audio ni datos personales de las sesiones sin permiso explicito.

La firma digital del ejecutable y del instalador requiere un certificado de firma de codigo emitido para el responsable de la distribucion. No debe sustituirse por un certificado de prueba.
