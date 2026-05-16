@echo off
REM Garage Meeting Copilot - Python Desktop Agent Launcher
REM Starts Vite dev server and Python overlay application

setlocal enabledelayedexpansion

echo Launching Garage Meeting Copilot Desktop Agent...

REM Start Vite dev server in background
echo Starting Vite dev server on port 1420...
start "Vite Dev Server" cmd /k "npm run dev"

REM Wait for Vite to start
timeout /t 5 /nobreak

REM Install Python dependencies if needed
if not exist "venv" (
    echo Creating Python virtual environment...
    python -m venv venv
)

REM Activate venv and install/upgrade dependencies
echo Activating virtual environment...
call venv\Scripts\activate.bat

echo Installing Python dependencies...
pip install -q -r requirements-desktop.txt

REM Launch Python desktop agent
echo Starting Python desktop agent...
python python_desktop_agent.py "http://localhost:1420/#token=test_token&session_id=test_session&gateway_url=ws://localhost:8000/ws/copilot"

pause
