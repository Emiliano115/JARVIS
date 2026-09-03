$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python no esta disponible en PATH. Instala Python 3.12 y vuelve a intentarlo."
}

if (-not (Test-Path ".venv_build\Scripts\python.exe")) {
    python -m venv .venv_build
    if ($LASTEXITCODE -ne 0) { throw "No se pudo crear el entorno virtual de build." }
}

$pythonBuild = Join-Path $PSScriptRoot ".venv_build\Scripts\python.exe"
& $pythonBuild -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "No se pudo actualizar pip." }
& $pythonBuild -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "No se pudieron instalar las dependencias." }
& $pythonBuild -m pip install --upgrade pyinstaller
if ($LASTEXITCODE -ne 0) { throw "No se pudo instalar PyInstaller." }
& $pythonBuild -m PyInstaller --clean --noconfirm Jarvis.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller no pudo generar la aplicacion." }

Write-Host "Build listo en: $PSScriptRoot\dist\Jarvis"
Write-Host "Prueba con: $PSScriptRoot\dist\Jarvis\Jarvis.exe"
