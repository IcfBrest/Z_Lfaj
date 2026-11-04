# 端到端冒烟一键运行：起桩服务 + uvicorn（sqlite），跑 smoke_e2e.py，最后清理进程与临时库。
# 用法（在 backend 目录）：pwsh -File tools/smoke_run.ps1
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw "缺少虚拟环境：$python" }

$env:DATABASE_URL = 'sqlite:///./data/smoke-e2e.db'
$env:SECRET_KEY = 'smoke-secret-key'
$env:ENCRYPTION_KEY = 'smoke-encryption-key'
# 本机回环不走系统代理（litellm/httpx 只认环境变量，注册表代理会让请求打到 29290 拿到 502）
$env:NO_PROXY = '127.0.0.1,localhost'
$env:no_proxy = '127.0.0.1,localhost'
Remove-Item -Force -ErrorAction SilentlyContinue '.\data\smoke-e2e.db'

Write-Output '[..] 初始化数据库（alembic upgrade head）'
& $python -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw 'alembic upgrade head 失败' }

Write-Output '[..] 启动桩服务 :8099'
$stub = Start-Process -FilePath $python -ArgumentList 'tools\smoke_llm_stub.py' -PassThru -WindowStyle Hidden
Write-Output '[..] 启动 uvicorn :8098'
$apiLog = Join-Path $root 'data\smoke-api.log'
$api = Start-Process -FilePath $python -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8098' -PassThru -WindowStyle Hidden -RedirectStandardError $apiLog -RedirectStandardOutput (Join-Path $root 'data\smoke-api.out.log')

try {
    $ready = $false
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 500
        try {
            $resp = Invoke-WebRequest -Uri 'http://127.0.0.1:8098/healthz' -UseBasicParsing -NoProxy -TimeoutSec 2
            if ($resp.StatusCode -eq 200) { $ready = $true; break }
        } catch { }
    }
    if (-not $ready) {
        if (Test-Path $apiLog) { Get-Content $apiLog -Tail 20 | ForEach-Object { Write-Output "  api| $_" } }
        throw '后端 20 秒内未就绪'
    }

    & $python tools\smoke_e2e.py
    $code = $LASTEXITCODE
} finally {
    foreach ($proc in @($api, $stub)) {
        if ($proc -and -not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
    }
    Start-Sleep -Milliseconds 300
    Remove-Item -Force -ErrorAction SilentlyContinue '.\data\smoke-e2e.db'
}

if ($code -ne 0) { throw "冒烟失败，退出码 $code" }
Write-Output '[ok] 冒烟通过'
