# 启动后端（开发模式，带热重载）。用法：.\Scripts\StartBackend.ps1 [-Port 8000]
param([int]$Port = 8000, [switch]$Docker)
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..\Backend')
$python = if (Test-Path '.venv\Scripts\python.exe') { '.venv\Scripts\python.exe' } else { 'python' }
if ($Docker -and -not $PSBoundParameters.ContainsKey('Port')) { $Port = 8081 }
$bindAddress = if ($Docker) { '0.0.0.0' } else { '127.0.0.1' }
if (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue) {
    throw "端口 $Port 已被占用（酷狗可能占用 8000）；Docker 模式请使用 .\Scripts\StartDocker.ps1。"
}
$env:API_UPSTREAM = ''
& $python -m uvicorn Main:app --host $bindAddress --port $Port --reload
