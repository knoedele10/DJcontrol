# 生产方式 A：构建前端，由 FastAPI 在同一进程提供界面、接口和 COM 控制（见 Docs/BackendGuide.md §2.5）。
param([int]$Port = 8081)
$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..')
Set-Location (Join-Path $root 'Template')
pnpm build
if ($LASTEXITCODE -ne 0) { throw "前端构建失败" }
Set-Location (Join-Path $root 'Backend')
$env:FRONTEND_DIST = Join-Path $root 'Template\dist'
$python = if (Test-Path '.venv\Scripts\python.exe') { '.venv\Scripts\python.exe' } else { 'python' }
& $python -m uvicorn Main:app --host 127.0.0.1 --port $Port
