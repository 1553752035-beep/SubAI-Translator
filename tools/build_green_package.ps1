<#
SubAI Translator —— 组装可分发的绿色版
=========================================
把已构建的两个 exe、FFmpeg 与 ASR 模型组装成一个自包含目录：
目录内的所有路径都由"exe 所在位置"推导，可整体拷贝到其他机器运行。

用法（在源码目录下执行）：
  powershell -ExecutionPolicy Bypass -File tools\build_green_package.ps1
  powershell -ExecutionPolicy Bypass -File tools\build_green_package.ps1 -OutDir D:\SubAI-Green

前置条件：
  - 后端已构建：dist\subai-backend.exe
  - 桌面端已构建：frontend\src-tauri\target\release\subai-translator.exe
  - FFmpeg 与模型：默认取安装根（源码目录的上一级）下的 bin\ 与 models\
#>
param(
    [string]$RepoRoot = '',
    [string]$OutDir = '',
    [string]$FfmpegDir = '',
    [string]$ModelsDir = ''
)
$ErrorActionPreference = 'Stop'

if (-not $RepoRoot) { $RepoRoot = Split-Path $PSScriptRoot -Parent }
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
$installRoot = Split-Path $RepoRoot -Parent

if (-not $OutDir) { $OutDir = Join-Path $installRoot 'dist-green' }
if (-not $FfmpegDir) { $FfmpegDir = Join-Path $installRoot 'bin' }
if (-not $ModelsDir) { $ModelsDir = Join-Path $installRoot 'models' }

$backendExe = Join-Path $RepoRoot 'dist\subai-backend.exe'
$desktopExe = Join-Path $RepoRoot 'frontend\src-tauri\target\release\subai-translator.exe'
$license    = Join-Path $RepoRoot 'LICENSE'

foreach ($f in @($backendExe, $desktopExe)) {
    if (-not (Test-Path -LiteralPath $f)) {
        Write-Host "缺少构建产物: $f"
        Write-Host "请先构建："
        Write-Host "  .venv\Scripts\python.exe -m PyInstaller --noconfirm subai_backend.spec"
        Write-Host "  cd frontend; npm run tauri:build -- --no-bundle"
        exit 2
    }
}
if (-not (Test-Path -LiteralPath (Join-Path $ModelsDir 'faster-whisper-small'))) {
    Write-Host "找不到 ASR 模型目录: $(Join-Path $ModelsDir 'faster-whisper-small')"
    Write-Host "可用 -ModelsDir 指定模型所在目录。"
    exit 2
}

Write-Host "源码根  : $RepoRoot"
Write-Host "输出目录: $OutDir"

if (Test-Path -LiteralPath $OutDir) {
    Write-Host "输出目录已存在，先清空（只清理该目录本身）..."
    Remove-Item -LiteralPath $OutDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $OutDir 'data') | Out-Null

Copy-Item -LiteralPath $desktopExe -Destination (Join-Path $OutDir 'SubAI-Translator.exe') -Force
Copy-Item -LiteralPath $backendExe -Destination (Join-Path $OutDir 'subai-backend.exe') -Force
if (Test-Path -LiteralPath $license) { Copy-Item -LiteralPath $license -Destination $OutDir -Force }

if (Test-Path -LiteralPath $FfmpegDir) {
    robocopy $FfmpegDir (Join-Path $OutDir 'bin') /E /NFL /NDL /NJH /NJS /NP | Out-Null
    Write-Host "  bin\      <- $FfmpegDir"
} else {
    Write-Host "  警告: 未找到 FFmpeg 目录 $FfmpegDir（抽音轨与压制将不可用）"
}

robocopy $ModelsDir (Join-Path $OutDir 'models') /E /NFL /NDL /NJH /NJS /NP | Out-Null
Write-Host "  models\   <- $ModelsDir"

$readme = @()
$readme += "SubAI Translator 绿色版"
$readme += ""
$readme += "1) 双击 SubAI-Translator.exe 启动（会自动拉起同目录的 subai-backend.exe）"
$readme += "2) 首次使用前可先自检：  subai-backend.exe --check"
$readme += "3) 翻译需要本地或云端翻译服务（默认 http://127.0.0.1:5001/v1/chat/completions），"
$readme += "   也可在 设置 页切换为云端模式"
$readme += "4) 需要 GPU 加速语音识别时，见 README 的「GPU 加速（可选）」"
$readme += ""
$readme += "全部路径均由本目录推导，可整体拷贝到其他机器使用。"
@($readme) | Set-Content -Path (Join-Path $OutDir '使用说明.txt') -Encoding UTF8

$size = (Get-ChildItem $OutDir -Recurse -File | Measure-Object -Property Length -Sum).Sum
Write-Host ""
Write-Host ("完成: " + $OutDir + "  共 " + [math]::Round($size/1GB, 2) + " GB")
