# 同一 Windows 桌面启动控制服务，再启动 Docker 网页；容器不能直接控制宿主机窗口。
param(
    [ValidateRange(1, 65535)][int]$BackendPort = 8081,
    [ValidateSet('kugou', 'mock')][string]$Controller = 'kugou',
    [switch]$NoBuild
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$backend = Join-Path $root 'Backend'
$data = Join-Path $backend 'Data'
New-Item -ItemType Directory -Path $data -Force | Out-Null
$localUrl = "http://127.0.0.1:$BackendPort"
$listener = Get-NetTCPConnection -State Listen -LocalPort $BackendPort -ErrorAction SilentlyContinue
if ($listener) {
    try { $existing = Invoke-RestMethod "$localUrl/api/connection" -TimeoutSec 5 }
    catch { throw "端口 $BackendPort 已被其他程序占用。请关闭冲突程序，或用 -BackendPort 指定空闲端口；不会终止其他程序。" }
    if ($existing.mode -ne 'local' -or -not $existing.backend_connected) {
        throw "端口 $BackendPort 不是可用的本地控制服务，请检查后端配置。"
    }
    Write-Host "复用 Windows 控制服务：$localUrl"
} else {
    $python = if (Test-Path (Join-Path $backend '.venv\Scripts\python.exe')) {
        Join-Path $backend '.venv\Scripts\python.exe'
    } else { (Get-Command python -ErrorAction Stop).Source }
    $savedUpstream = $env:API_UPSTREAM
    $savedController = $env:PLAYER_CONTROLLER
    $savedFrontend = $env:FRONTEND_DIST
    try {
        $env:API_UPSTREAM = ''
        $env:PLAYER_CONTROLLER = $Controller
        $env:FRONTEND_DIST = ''
        $worker = Start-Process -FilePath $python -ArgumentList @('-X', 'utf8', '-m', 'uvicorn', 'Main:app', '--app-dir', "`"$backend`"", '--host', '0.0.0.0', '--port', "$BackendPort", '--workers', '1') `
            -WorkingDirectory $backend -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput (Join-Path $data 'dockerbackend.stdout.log') `
            -RedirectStandardError (Join-Path $data 'dockerbackend.stderr.log')
        @{ pid = $worker.Id; port = $BackendPort; backend = $backend } | ConvertTo-Json | Set-Content (Join-Path $data 'dockerbackend.json') -Encoding UTF8
    } finally {
        $env:API_UPSTREAM = $savedUpstream
        $env:PLAYER_CONTROLLER = $savedController
        $env:FRONTEND_DIST = $savedFrontend
    }
    $ready = $false
    $deadline = (Get-Date).AddSeconds(30)
    while ((Get-Date) -lt $deadline) {
        $worker.Refresh()
        if ($worker.HasExited) { throw "Windows 后端启动失败，请查看 $data\dockerbackend.stderr.log" }
        try {
            $state = Invoke-RestMethod "$localUrl/api/connection" -TimeoutSec 2
            if ($state.mode -eq 'local' -and $state.backend_connected) { $ready = $true; break }
        } catch { }
        Start-Sleep -Milliseconds 300
    }
    if (-not $ready) { throw "Windows 后端尚未就绪，请查看 $data\dockerbackend.stderr.log" }
    Write-Host "Windows 控制服务已启动：$localUrl（PID $($worker.Id)）"
}
$savedUpstream = $env:API_UPSTREAM
try {
    # 此值只提供给本次 Compose，不把 Windows 后端自身启动成代理。
    $env:API_UPSTREAM = "http://host.docker.internal:$BackendPort"
    Push-Location $root
    try {
        if ($NoBuild) { docker compose up -d } else { docker compose up -d --build }
        if ($LASTEXITCODE -ne 0) { throw 'Docker 启动失败；Windows 后端日志位于 Backend/Data。' }
        $ready = $false
        $deadline = (Get-Date).AddSeconds(30)
        while ((Get-Date) -lt $deadline) {
            try {
                $connection = Invoke-RestMethod 'http://127.0.0.1:8080/api/connection' -TimeoutSec 5
                if ($connection.backend_connected) { $ready = $true; break }
            } catch { }
            Start-Sleep -Milliseconds 300
        }
        if (-not $ready) {
            throw "容器仍连不上 $($connection.upstream)。Windows 后端须监听 0.0.0.0:$BackendPort；请检查上游地址。"
        }
    } finally { Pop-Location }
} finally { $env:API_UPSTREAM = $savedUpstream }
Write-Host '网页已就绪：http://127.0.0.1:8080；停止请运行 .\Scripts\StopDocker.ps1。'
