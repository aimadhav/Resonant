$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
& "$PSScriptRoot/.venv/Scripts/python.exe" "$PSScriptRoot/live_server.py" --port 5097
