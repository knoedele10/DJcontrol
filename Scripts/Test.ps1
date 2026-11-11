# 运行全部自动化测试：后端 unittest + 前端 PPT 测试。
$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..')
Set-Location (Join-Path $root 'Backend')
$python = if (Test-Path '.venv\Scripts\python.exe') { '.venv\Scripts\python.exe' } else { 'python' }
& $python -m unittest discover -s Tests -t . -p 'Test*.py'
if ($LASTEXITCODE -ne 0) { throw "后端测试失败" }
Set-Location (Join-Path $root 'Template')
pnpm test
if ($LASTEXITCODE -ne 0) { throw "前端测试失败" }
