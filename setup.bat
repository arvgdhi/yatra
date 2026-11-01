@echo off
REM One-time setup: creates a Python virtual environment and installs backend + frontend dependencies.
REM Uses Python 3.13, 3.12 or 3.11 (batman-package has no prebuilt Windows wheel for 3.14 yet).
setlocal
cd /d "%~dp0"

set PY=
for %%V in (3.13 3.12 3.11) do (
  if not defined PY (
    py -%%V -c "import sys" >nul 2>nul && set PY=py -%%V
  )
)
if not defined PY (
  echo [ERROR] Python 3.13, 3.12 or 3.11 was not found.
  echo         Install Python 3.13 from https://www.python.org/downloads/windows/ ^(you can keep 3.14 installed alongside it^),
  echo         tick "Add Python to PATH" / install the py launcher, then run this script again.
  pause & exit /b 1
)
echo Using: %PY%

where node >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Node.js 18+ was not found. Install the LTS version from https://nodejs.org/
  pause & exit /b 1
)

REM A venv left over from a failed run with another Python version must be rebuilt.
if exist backend\.venv (
  backend\.venv\Scripts\python.exe -c "import sys; sys.exit(0 if sys.version_info[:2] in ((3,11),(3,12),(3,13)) else 1)" >nul 2>nul
  if errorlevel 1 (
    echo Removing old virtual environment built with an unsupported Python version...
    rmdir /s /q backend\.venv
  )
)

echo === Backend: creating virtual environment ===
if not exist backend\.venv (
  %PY% -m venv backend\.venv
  if errorlevel 1 ( echo [ERROR] Could not create the virtual environment. & pause & exit /b 1 )
)
echo === Backend: installing packages (a few minutes) ===
backend\.venv\Scripts\python.exe -m pip install --upgrade pip
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
if errorlevel 1 (
  echo [ERROR] Backend install failed. Scroll up for the first error line.
  pause & exit /b 1
)

echo === Frontend: installing packages ===
pushd frontend
call npm install
if errorlevel 1 ( popd & echo [ERROR] npm install failed. & pause & exit /b 1 )
popd

echo.
echo Setup finished. Double-click start.bat to run the app.
pause
