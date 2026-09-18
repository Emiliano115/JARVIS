# Compilar JARVIS en Windows

## Preparación

Ejecuta PowerShell desde la carpeta del proyecto:

```powershell
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
.\.venv\Scripts\python.exe -m pip install "pyinstaller>=6,<7"
```

## Compilación

```powershell
Remove-Item .\build\Jarvis, .\dist\Jarvis -Recurse -Force -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm .\Jarvis.spec
```

El resultado esperado es:

```text
dist\Jarvis\Jarvis.exe
```

## Comprobaciones antes de distribuir

```powershell
Test-Path .\dist\Jarvis\Jarvis.exe
Test-Path .\dist\Jarvis\_internal\V5.html
Test-Path .\dist\Jarvis\_internal\jarvis_logo.svg
```

No copies `token.json`, `.env`, `jarvis_config.json`, `jarvis_memoria.json` ni `jarvis_notas.db` dentro de un paquete público. El usuario debe autorizar Google en su propio equipo.

## Primera ejecución

1. Abre `dist\Jarvis\Jarvis.exe`.
2. Ejecuta `Autoprueba de Jarvis`.
3. Ejecuta `Diagnóstico de Jarvis`.
4. Autoriza Google solo si necesitas Calendar, Gmail, Drive o Tasks.
5. Comprueba Edge TTS, recordatorios, búsqueda local de archivos y rutinas.

## Nota sobre gestos

El modelo `models\hand_landmarker.task` es opcional en el paquete. Si no existe, Jarvis intentará descargarlo cuando se activen los gestos; sin internet los gestos no estarán disponibles, pero el resto del asistente debe continuar funcionando.