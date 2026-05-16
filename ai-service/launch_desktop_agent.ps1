#!/usr/bin/env pwsh
<#
.SYNOPSIS
Garage Meeting Copilot - Python Desktop Agent Launcher

.DESCRIPTION
Launches the Python desktop overlay with proper environment setup.

.PARAMETER SessionID
The Garage session ID (required)

.PARAMETER Token
JWT authentication token (required)

.PARAMETER GatewayUrl
WebSocket gateway URL (default: ws://localhost:8000/ws/copilot)

.PARAMETER FrontendUrl
Frontend URL (default: http://localhost:1420)

.EXAMPLE
.\launch_desktop_agent.ps1 -SessionID abc123 -Token eyJ0eXAiOiJKV1QiLCJhbGc...
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$SessionID,
    
    [Parameter(Mandatory=$true)]
    [string]$Token,
    
    [string]$GatewayUrl = "ws://localhost:8000/ws/copilot",
    [string]$FrontendUrl = "http://localhost:1420"
)

# Get script directory
$ScriptDir = Split-Path -Parent -Path $MyInvocation.MyCommand.Definition

# Activate venv
& "$ScriptDir\venv\Scripts\Activate.ps1"

# Build the URL with parameters
$DesktopUrl = "$FrontendUrl/#token=$Token&session_id=$SessionID&gateway_url=$([System.Net.WebUtility]::UrlEncode($GatewayUrl))"

Write-Host "Launching Garage Meeting Copilot..." -ForegroundColor Green
Write-Host "Session: $SessionID" -ForegroundColor Cyan
Write-Host "Gateway: $GatewayUrl" -ForegroundColor Cyan
Write-Host ""

# Launch desktop agent
python "$ScriptDir\desktop_agent.py" $DesktopUrl
