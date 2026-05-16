@echo off
REM Garage Meeting Copilot - Python Desktop Agent Launcher
setlocal enabledelayedexpansion

REM Get session details from command line or generate defaults
set SESSION_ID=%1
set TOKEN=%2
set GATEWAY_URL=%3
set FRONTEND_URL=%4

if "!FRONTEND_URL!"=="" set FRONTEND_URL=http://localhost:1420
if "!GATEWAY_URL!"=="" set GATEWAY_URL=ws://localhost:8000/ws/copilot

REM If no session_id provided, show usage
if "!SESSION_ID!"=="" (
    echo Usage: launch_desktop_agent.bat SESSION_ID TOKEN [GATEWAY_URL] [FRONTEND_URL]
    echo.
    echo Example:
    echo   launch_desktop_agent.bat abc123 eyJ0eXAiOiJKV1QiLCJhbGc... ws://localhost:8000/ws/copilot http://localhost:1420
    exit /b 1
)

REM Activate venv and run desktop agent
cd /d "%~dp0"
call venv\Scripts\activate.bat

REM Launch desktop agent with URL parameters
python desktop_agent.py "!FRONTEND_URL!/#token=!TOKEN!&session_id=!SESSION_ID!&gateway_url=!GATEWAY_URL!"

pause
