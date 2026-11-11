# 启动后端（开发模式，带热重载）。用法：.\Scripts\StartBackend.ps1 [-Port 8000]
param([int]$Port = 8000)
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..\Backend')
$python = if (Test-Path '.venv\Scripts\python.exe') { '.venv\Scripts\python.exe' } else { 'python' }
& $python -m uvicorn Main:app --host 127.0.0.1 --port $Port --reload
