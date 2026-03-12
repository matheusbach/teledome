@echo off
setlocal EnableExtensions EnableDelayedExpansion
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

cd /d "%ROOT%"
set PYTHONUNBUFFERED=1

rem ============================
rem Load environment variables from .env
rem ============================
if exist "%ROOT%\.env" (
  for /f "usebackq delims=" %%A in ("%ROOT%\.env") do (
    set "LINE=%%A"
    if not "!LINE!"=="" if not "!LINE:~0,1!"=="#" (
      for /f "tokens=1* delims==" %%K in ("!LINE!") do (
        set "KEY=%%K"
        set "VAL=%%L"
        for /f "tokens=* delims= " %%k in ("!KEY!") do set "KEY=%%k"
        for /f "tokens=* delims= " %%v in ("!VAL!") do set "VAL=%%v"
        if /i "!KEY:~0,7!"=="export " set "KEY=!KEY:~7!"
        if defined KEY set "!KEY!=!VAL!"
      )
    )
  )
)

if not defined API_ID (
  echo Error: API_ID is not set. Create a .env com API_ID=... e API_HASH=...
  exit /b 1
)
if not defined API_HASH (
  echo Error: API_HASH is not set. Create uma .env com API_ID=... e API_HASH=...
  exit /b 1
)

rem ============================
rem Install uv if missing
rem ============================
where uv >nul 2>nul
if errorlevel 1 (
  echo uv not found. Attempting installation...
  where pwsh >nul 2>nul
  if not errorlevel 1 (
    pwsh -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
  ) else (
    where powershell >nul 2>nul
    if not errorlevel 1 (
      powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    ) else (
      echo Error: PowerShell not found.
      exit /b 1
    )
  )
)

where uv >nul 2>nul
if errorlevel 1 (
  echo uv installation failed.
  echo Install manually: https://github.com/astral-sh/uv
  exit /b 1
)

echo uv ready.
uv --version
echo.

rem ============================
rem Virtual environment
rem ============================
set "VENV=%ROOT%\.venv"
set "PYTHON_VERSION=3.12"

if not exist "%VENV%" (
  echo Creating virtual environment...
  uv venv --python "%PYTHON_VERSION%" "%VENV%"
  if errorlevel 1 exit /b 1
)

call "%VENV%\Scripts\activate.bat"

for /f "usebackq delims=" %%P in (`
  python -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"
`) do set "VENV_PY=%%P"

if not "%VENV_PY%"=="%PYTHON_VERSION%" (
  echo Recreating venv with correct Python version...
  call "%VENV%\Scripts\deactivate.bat" >nul 2>nul
  rmdir /s /q "%VENV%"
  uv venv --python "%PYTHON_VERSION%" "%VENV%"
  call "%VENV%\Scripts\activate.bat"
)

echo Installing dependencies...
uv pip install -r "%ROOT%\requirements.txt"

echo Running main script...
python -m src.main %*

endlocal
pause
