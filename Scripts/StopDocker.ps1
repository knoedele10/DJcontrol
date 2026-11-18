# 只停止本项目记录并核对过的 Windows 后端，不关闭酷狗、Office 或其他 Python 程序。
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Push-Location $root
try {
    docker compose stop
    if ($LASTEXITCODE -ne 0) { throw '停止 Docker 网页失败' }
} finally { Pop-Location }
$record = Join-Path $root 'Backend\Data\dockerbackend.json'
if (Test-Path -LiteralPath $record) {
    $saved = Get-Content -LiteralPath $record -Raw -Encoding UTF8 | ConvertFrom-Json
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $([int]$saved.pid)" -ErrorAction SilentlyContinue
    if ($process -and $process.CommandLine -match '-m uvicorn Main:app' -and
        $process.CommandLine -match "--port $([int]$saved.port)(\s|$)" -and
        $process.CommandLine.IndexOf([string]$saved.backend, [StringComparison]::OrdinalIgnoreCase) -ge 0 -and
        $saved.backend -eq (Join-Path $root 'Backend')) {
        Stop-Process -Id ([int]$saved.pid) -ErrorAction Stop
        Remove-Item -LiteralPath $record
        Write-Host '已停止本项目的 Windows 控制服务。'
    } elseif ($process) {
        Write-Warning '记录的 PID 已不再属于本项目后端，未终止该进程。'
    } else { Remove-Item -LiteralPath $record }
}
