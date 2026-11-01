@echo off
REM Starts the backend (port 8000) and frontend (port 3000), then opens the browser.
setlocal
cd /d "%~dp0"

if not exist backend\.venv\Scripts\python.exe (
  echo Backend is not set up yet. Run setup.bat first.
  pause & exit /b 1
)
if not exist frontend\node_modules (
  echo Frontend is not set up yet. Run setup.bat first.
  pause & exit /b 1
)

start "Exoplanet Explorer - backend" /D "%~dp0backend" cmd /k ".venv\Scripts\python.exe -m uvicorn app.main:app --port 8000"
start "Exoplanet Explorer - frontend" /D "%~dp0frontend" cmd /k "npm run dev"

echo Waiting for the servers to start...
timeout /t 12 /nobreak >nul
start "" http://localhost:3000
echo.
echo The app is running. Close the two "Exoplanet Explorer" windows to stop it.
