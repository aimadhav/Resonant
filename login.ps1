$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (!(Test-Path './.venv/Scripts/kaggle.exe')) { throw 'Run ./start.ps1 first to install the app dependencies.' }
if (!$env:KAGGLE_CONFIG_DIR) { $env:KAGGLE_CONFIG_DIR = Join-Path $PSScriptRoot '.kaggle' }
New-Item -ItemType Directory -Force -Path $env:KAGGLE_CONFIG_DIR | Out-Null
& './.venv/Scripts/kaggle.exe' auth login
