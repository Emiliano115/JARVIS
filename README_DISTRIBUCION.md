# Distribuir Jarvis en Windows

## Preparar el repositorio

Publica solo codigo y recursos necesarios. No subas `token.json`, `.env`, `jarvis_config.json`, memorias, bases de datos, claves API ni `.venv_gestos`.

El `gitignore` ya excluye los datos sensibles. Como el token de Google fue expuesto durante las pruebas, revocalo y genera uno nuevo antes de publicar.

## Construir

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

Jarvis comprueba en segundo plano si existe un GitHub Release posterior y muestra un enlace. La actualización no reemplaza el `.exe` automáticamente: cierra Jarvis, descarga el ZIP nuevo desde Releases, extrae la carpeta completa y reemplaza la instalación anterior. La configuración y memoria se conservan en `%LOCALAPPDATA%\Jarvis`.
