@echo off
setlocal
cd /d "%~dp0"

if /I not "%~1"=="--skip-env-check" (
    call "%~dp00-ensure-rtg-env.bat"
    if errorlevel 1 (
        echo [RTG] Failed while preparing the local runtime environment.
        pause
        exit /b 1
    )
)

set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
    echo [RTG] The local python executable is missing.
    pause
    exit /b 1
)

echo [RTG] Starting local server...
"%PYTHON_EXE%" launcher.py
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo.
    echo [RTG] Server stopped. Exit code: %EXIT_CODE%
    pause
    exit /b %EXIT_CODE%
)

endlocal
