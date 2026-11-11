# 开发环境：新窗口启动后端（8000），当前窗口启动前端 Vite（5173，已代理 /api、/ws）。
$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..')
Start-Process powershell -ArgumentList '-NoExit', '-File', (Join-Path $PSScriptRoot 'StartBackend.ps1')
Set-Location (Join-Path $root 'Template')
pnpm dev --host 127.0.0.1
