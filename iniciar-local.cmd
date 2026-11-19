@echo off
setlocal
cd /d "%~dp0"
where uv >nul 2>nul
if errorlevel 1 (
  echo No se ha encontrado uv. Instala uv desde https://docs.astral.sh/uv/getting-started/installation/
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  uv venv .venv --python 3.12
  if errorlevel 1 exit /b 1
)
uv pip install --python ".venv\Scripts\python.exe" -r menu_compra/requirements.txt
if errorlevel 1 (
  pause
  exit /b 1
)
set "MENU_COMPRA_DEV=1"
set "MENU_COMPRA_DATA_DIR=%~dp0datos-locales"
echo.
echo Abre http://127.0.0.1:8099 en tu navegador.
echo Los datos de esta prueba local se guardan en datos-locales, no en Home Assistant.
echo Para detener la aplicacion, pulsa Ctrl+C.
echo.
".venv\Scripts\python.exe" -m uvicorn app.main:app --app-dir menu_compra --host 127.0.0.1 --port 8099 --no-proxy-headers
if errorlevel 1 pause
