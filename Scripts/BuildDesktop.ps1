# 构建前端、准备独立 Python 运行环境、执行桌面测试并打包 Electron 应用（dir 免安装目录 / win 安装包并同步安装包到 Dest）。
param(
    [ValidateSet('dir', 'win')]
    [string]$Target = 'dir',
    [switch]$SkipTest,
    [switch]$CleanBundle
)
$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..')
$desktopDir = Join-Path $root 'Desktop'
$releaseDir = Join-Path $desktopDir 'release'
$destDir = Join-Path $root 'Dest'
$venvPython = Join-Path $root 'Backend\.venv\Scripts\python.exe'
$python = if (Test-Path $venvPython) { $venvPython } else { 'python' }

Set-Location (Join-Path $root 'Template')
pnpm build
if ($LASTEXITCODE -ne 0) { throw "前端构建失败" }

Set-Location $desktopDir
if (-not $SkipTest) {
    pnpm test
    if ($LASTEXITCODE -ne 0) { throw "桌面端测试失败" }
}

$prepareArgs = @(Join-Path $desktopDir 'Scripts\PrepareBundle.py')
if ($CleanBundle -or $Target -eq 'win') {
    $prepareArgs += '--clean'
    if (Test-Path $releaseDir) {
        Remove-Item -Path $releaseDir -Recurse -Force
    }
}
& $python @prepareArgs
if ($LASTEXITCODE -ne 0) { throw "准备独立运行环境失败" }

Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
if ($Target -eq 'win') {
    pnpm run build
    if ($LASTEXITCODE -ne 0) { throw "桌面端编译失败" }
    pnpm exec electron-builder --win
} else {
    pnpm run build
    if ($LASTEXITCODE -ne 0) { throw "桌面端编译失败" }
    pnpm exec electron-builder --dir
}
if ($LASTEXITCODE -ne 0) { throw "桌面端打包失败" }

$unpackedDir = Join-Path $releaseDir 'win-unpacked'
$unpackedExe = Join-Path $unpackedDir '酷狗统筹面板.exe'
$bundledPython = Join-Path $unpackedDir 'resources\python\python.exe'
$bundledBackend = Join-Path $unpackedDir 'resources\backend'
$bundledFrontend = Join-Path $unpackedDir 'resources\frontend\index.html'

if (-not (Test-Path $unpackedExe)) { throw "未生成免安装可执行文件: $unpackedExe" }
if (-not (Test-Path $bundledPython)) { throw "打包产物缺少独立 Python 运行时: $bundledPython" }
if (-not (Test-Path $bundledFrontend)) { throw "打包产物缺少前端页面: $bundledFrontend" }
$dirtyFiles = @(Get-ChildItem -Path $bundledBackend -Recurse -Force | Where-Object {
    $_.Name -in @('__pycache__', 'Tests', 'Data', '.venv', 'RequirementsDev.txt') -or
    $_.Extension -in @('.pyc', '.pyo', '.log', '.db')
})
if ($dirtyFiles.Count -gt 0) {
    throw "打包后端目录包含非运行时残留: $($dirtyFiles[0].FullName)"
}
$dirtyPython = @(Get-ChildItem -Path (Join-Path $unpackedDir 'resources\python') -Recurse -Force | Where-Object {
    $_.Name -in @('__pycache__', '.bundle-stamp.json') -or $_.Extension -in @('.pyc', '.pyo', '.pdb')
})
if ($dirtyPython.Count -gt 0) {
    throw "打包 Python 目录包含缓存或调试文件: $($dirtyPython[0].FullName)"
}
$dirtySiteDirs = @(Get-ChildItem -Path (Join-Path $unpackedDir 'resources\python\Lib\site-packages') -Recurse -Directory -Force | Where-Object {
    $_.Name.ToLowerInvariant() -in @('test', 'tests', 'demos', 'doc', 'docs', 'include', 'scripts')
})
if ($dirtySiteDirs.Count -gt 0) {
    throw "打包 site-packages 包含非运行时开发目录: $($dirtySiteDirs[0].FullName)"
}
foreach ($forbiddenPath in @(
    'resources\python\Lib\site-packages\comtypes\gen',
    'resources\python\Lib\site-packages\win32com\gen_py',
    'resources\python\Lib\site-packages\pywinauto\tests'
)) {
    if (Test-Path (Join-Path $unpackedDir $forbiddenPath)) {
        throw "打包 Python 目录包含非预期路径: $forbiddenPath"
    }
}

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

Write-Host "免安装版可执行文件: $unpackedExe"
if ($Target -eq 'win') {
    Write-Host "已同步安装包到: $destDir"
}
