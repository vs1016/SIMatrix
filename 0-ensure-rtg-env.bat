@echo off
setlocal
cd /d "%~dp0"

set "BOOTSTRAP_PYTHON=%~dp0python\python.exe"
set "BOOTSTRAP_PYTHON_ARGS="
set "VENV_DIR=%~dp0.venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
set "REQ_FILE=%~dp0requirements.txt"
set "REQ_HASH_FILE=%VENV_DIR%\.requirements.sha256"
set "WHEELHOUSE_DIR=%~dp0wheelhouse"

if exist "%BOOTSTRAP_PYTHON%" goto python_ready

py -3 -c "import sys" >nul 2>nul
if not errorlevel 1 (
    set "BOOTSTRAP_PYTHON=py"
    set "BOOTSTRAP_PYTHON_ARGS=-3"
    goto python_ready
)

python -c "import sys" >nul 2>nul
if not errorlevel 1 (
    set "BOOTSTRAP_PYTHON=python"
    goto python_ready
)

echo [RTG-0] Python runtime was not found.
echo [RTG-0] Please keep the bundled python folder or install Python 3 first.
pause
exit /b 1

:python_ready
if not exist "%PYTHON_EXE%" (
    echo [RTG-0] Creating local runtime environment...
    "%BOOTSTRAP_PYTHON%" %BOOTSTRAP_PYTHON_ARGS% -m ensurepip --upgrade >nul 2>nul
    "%BOOTSTRAP_PYTHON%" %BOOTSTRAP_PYTHON_ARGS% -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [RTG-0] Failed to create the local runtime environment.
        pause
        exit /b 1
    )
)

if not exist "%PYTHON_EXE%" (
    echo [RTG-0] The local python executable is missing.
    pause
    exit /b 1
)

set "REQ_HASH="
for /f "tokens=1" %%I in ('certutil -hashfile "%REQ_FILE%" SHA256 ^| findstr /r /i "^[0-9a-f][0-9a-f]*$"') do (
    if not defined REQ_HASH set "REQ_HASH=%%I"
)

if not defined REQ_HASH (
    echo [RTG-0] Failed to calculate the requirements hash.
    pause
    exit /b 1
)

set "INSTALLED_REQ_HASH="
if exist "%REQ_HASH_FILE%" set /p INSTALLED_REQ_HASH=<"%REQ_HASH_FILE%"

if /I not "%REQ_HASH%"=="%INSTALLED_REQ_HASH%" (
    echo [RTG-0] Installing runtime dependencies...
    dir /b /a-d "%WHEELHOUSE_DIR%\*.whl" >nul 2>nul
    if not errorlevel 1 (
        "%PYTHON_EXE%" -m pip install --disable-pip-version-check --no-index --find-links "%WHEELHOUSE_DIR%" -r "%REQ_FILE%"
    ) else (
        "%PYTHON_EXE%" -m pip install --disable-pip-version-check -r "%REQ_FILE%"
    )
    if errorlevel 1 (
        echo [RTG-0] Failed to install runtime dependencies.
        pause
        exit /b 1
    )
    >"%REQ_HASH_FILE%" echo %REQ_HASH%
) else (
    echo [RTG-0] Runtime dependencies already up to date.
)

endlocal
exit /b 0
