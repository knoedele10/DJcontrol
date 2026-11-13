# 开发环境：拉起 Vite 开发服务器（5173）并启动 Electron（自动拉起或复用 8000 端口后端）。
$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..')
$viteProc = $null

function Test-PortOpen([int]$Port) {
    try {
        $client = [System.Net.Sockets.TcpClient]::new('127.0.0.1', $Port)
        $client.Close()
        return $true
    } catch {
        return $false
    }
}

try {
    if (-not (Test-PortOpen 5173)) {
        $templateDir = Join-Path $root 'Template'
        $pnpmCmd = (Get-Command pnpm.cmd -ErrorAction SilentlyContinue).Source
        if (-not $pnpmCmd) { $pnpmCmd = 'pnpm' }
        $viteProc = Start-Process -FilePath $pnpmCmd -ArgumentList 'dev', '--host', '127.0.0.1' -WorkingDirectory $templateDir -PassThru -WindowStyle Minimized
    }

    Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
    Set-Location (Join-Path $root 'Desktop')
    pnpm dev
    if ($LASTEXITCODE -ne 0) { throw "桌面开发端启动失败" }
} finally {
    if ($viteProc -and -not $viteProc.HasExited) {
        & taskkill /pid $viteProc.Id /T /F 2>$null | Out-Null
    }
}
