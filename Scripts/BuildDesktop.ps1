# 构建前端、执行桌面测试并打包 Electron 应用（dir 免安装目录 / win 安装包并同步安装包到 Dest）。
param(
    [ValidateSet('dir', 'win')]
    [string]$Target = 'dir',
    [switch]$SkipTest
)
$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..')
$desktopDir = Join-Path $root 'Desktop'
$releaseDir = Join-Path $desktopDir 'release'
$destDir = Join-Path $root 'Dest'

Set-Location (Join-Path $root 'Template')
pnpm build
if ($LASTEXITCODE -ne 0) { throw "前端构建失败" }

Set-Location $desktopDir
if (-not $SkipTest) {
    pnpm test
    if ($LASTEXITCODE -ne 0) { throw "桌面端测试失败" }
}

Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
if ($Target -eq 'win') {
    pnpm run dist
} else {
    pnpm run pack
}
if ($LASTEXITCODE -ne 0) { throw "桌面端打包失败" }

if ($Target -eq 'win') {
    $installers = @(Get-ChildItem -Path $releaseDir -Filter '*Setup*.exe' -File)
    if ($installers.Count -eq 0) {
        throw "未在 $releaseDir 中找到安装包 .exe"
    }
    New-Item -ItemType Directory -Path $destDir -Force | Out-Null
    Get-ChildItem -Path $destDir -Filter '*Setup*.exe' -File -ErrorAction SilentlyContinue | Remove-Item -Force
    foreach ($installer in $installers) {
        Copy-Item -Path $installer.FullName -Destination (Join-Path $destDir $installer.Name) -Force
    }
}

$unpackedExe = Join-Path $releaseDir 'win-unpacked\酷狗统筹面板.exe'
if (Test-Path $unpackedExe) {
    Write-Host "免安装版可执行文件: $unpackedExe"
}
if ($Target -eq 'win') {
    Write-Host "已同步安装包到: $destDir"
}
