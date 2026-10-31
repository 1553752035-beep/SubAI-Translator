<#
SubAI Translator —— 本地测试入口
=================================
CI 跑在 GitHub Actions 上，而本项目的主用机常常连不上 GitHub，
于是"质量闸门"实际只在本机人工跑。这个脚本给出一条固定命令：

  powershell -ExecutionPolicy Bypass -File tools\run_tests.ps1           # 后端 + 前端
  powershell -ExecutionPolicy Bypass -File tools\run_tests.ps1 -BackendOnly
  powershell -ExecutionPolicy Bypass -File tools\run_tests.ps1 -FrontendOnly

退出码：0 全绿 / 1 有失败。可直接挂到 pre-push 或打包脚本前面。
#>
param(
    [switch]$BackendOnly,
    [switch]$FrontendOnly,
    [string]$RepoRoot = ''
)
$ErrorActionPreference = 'Stop'
if (-not $RepoRoot) { $RepoRoot = Split-Path $PSScriptRoot -Parent }

# 中文输出不乱码（控制台与管道都设）
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
$env:RUN_API_TESTS = '1'

# NO_PROXY 里的 IPv6 如果写成 [::1]（带方括号），httpx 会把它当 URL 解析并抛
# `Invalid URL: Invalid port`，导致一批依赖本地 mock 服务的用例集体失败。
# tests/conftest.py 已有归一化，这里再收一次，保证用本脚本跑时不受宿主环境影响。
foreach ($k in @('NO_PROXY', 'no_proxy')) {
    $v = [Environment]::GetEnvironmentVariable($k)
    if ($v) {
        $fixed = ($v -split ',' | Where-Object { $_.Trim() } | ForEach-Object {
            $p = $_.Trim()
            if ($p -match '^\[(.+)\]$') { $matches[1] } else { $p }
        }) -join ','
        Set-Item -Path "env:$k" -Value $fixed
    }
}

$failed = @()

if (-not $FrontendOnly) {
    Write-Host '=== 后端 pytest ==='
    Push-Location $RepoRoot
    try {
        & python -m pytest tests -q
        if ($LASTEXITCODE -ne 0) { $failed += 'backend' }
    } finally { Pop-Location }
}

if (-not $BackendOnly) {
    $fe = Join-Path $RepoRoot 'frontend'
    if (Test-Path -LiteralPath (Join-Path $fe 'node_modules')) {
        Write-Host '=== 前端 vitest ==='
        Push-Location $fe
        try {
            & npm test
            if ($LASTEXITCODE -ne 0) { $failed += 'frontend' }
        } finally { Pop-Location }
    } else {
        Write-Host '前端 node_modules 不存在，跳过（先 cd frontend; npm install）'
    }
}

Write-Host ''
if ($failed.Count -eq 0) {
    Write-Host '全部通过'
    exit 0
}
Write-Host ("失败: " + ($failed -join ', '))
exit 1
