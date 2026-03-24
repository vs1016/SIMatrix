@echo off
setlocal
cd /d "%~dp0"

call "%~dp00-ensure-rtg-env.bat"
if errorlevel 1 (
    echo [RTG-123] Failed while preparing the local runtime environment.
    pause
    exit /b 1
)

call "%~dp01-clear-rtg-data.bat"
if errorlevel 1 (
    echo [RTG-123] Failed while clearing local data.
    pause
    exit /b 1
)

call "%~dp02-start-rtg-service.bat" --skip-env-check
set "EXIT_CODE=%ERRORLEVEL%"

endlocal & exit /b %EXIT_CODE%
