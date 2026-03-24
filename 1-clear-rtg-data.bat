@echo off
setlocal
cd /d "%~dp0"

echo [RTG-1] Stopping existing local service...
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do (
    taskkill /f /pid %%P >nul 2>nul
)
timeout /t 1 /nobreak >nul

echo [RTG-1] Clearing database files...
if exist "data\esimdb.sqlite3" del /f /q "data\esimdb.sqlite3"
if exist "data\esimdb.sqlite3-shm" del /f /q "data\esimdb.sqlite3-shm"
if exist "data\esimdb.sqlite3-wal" del /f /q "data\esimdb.sqlite3-wal"

echo [RTG-1] Database cleared.
endlocal
exit /b 0
