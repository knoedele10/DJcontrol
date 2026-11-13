# 构建前端产物（可用 -SkipBuild 跳过）并启动 Electron 桌面应用。
param([switch]$SkipBuild)
$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..')

if (-not $SkipBuild) {
    Set-Location (Join-Path $root 'Template')
    pnpm build
    if ($LASTEXITCODE -ne 0) { throw "前端构建失败" }
}

Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
Set-Location (Join-Path $root 'Desktop')
pnpm start
if ($LASTEXITCODE -ne 0) { throw "桌面端启动失败" }
