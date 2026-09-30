<#
SubAI Translator —— 构建"可选 GPU 包"（不联网下载）
=====================================================
从已安装的 nvidia-* 运行库生成可选的 cuda_dlls 目录。主程序会自动从
<安装目录>/cuda_dlls 识别，所以主包体积不变。

两种模式：
  -Mode Copy  复制 DLL（默认，约 2.0 GB；可随U盘/压缩包转移）
  -Mode Link  只创建目录联接（**零磁盘占用**，仅当来源会长期留在原处时可用，
              适合开发机快速验证）

用法：
  powershell -ExecutionPolicy Bypass -File tools\build_gpu_pack.ps1
  powershell -ExecutionPolicy Bypass -File tools\build_gpu_pack.ps1 -Mode Link
  powershell -ExecutionPolicy Bypass -File tools\build_gpu_pack.ps1 -Source "C:\path\to\nvidia" -OutDir "D:\packs"
#>
param(
    [ValidateSet('Copy', 'Link')]
    [string]$Mode = 'Copy',
    [string]$Source = '',
    [string]$OutDir = ''
)
$ErrorActionPreference = 'Stop'

$installRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if (-not $OutDir) { $OutDir = Join-Path $installRoot 'dist-gpu-pack' }
if (-not $Source) {
    $Source = Join-Path $PSScriptRoot '..\.venv\Lib\site-packages\nvidia'
}
if (-not (Test-Path -LiteralPath $Source)) {
    Write-Host "找不到来源目录: $Source"
    Write-Host "请先安装 nvidia-cublas-cu12 与 nvidia-cudnn-cu12，或用 -Source 指定已有的 nvidia 目录。"
    exit 2
}
$Source = (Resolve-Path -LiteralPath $Source).Path
Write-Host "模式: $Mode"
Write-Host "来源: $Source"
Write-Host "输出: $OutDir"

$subs = @('cublas', 'cudnn', 'cuda_nvrtc', 'cuda_runtime')
$dstRoot = Join-Path $OutDir 'cuda_dlls'
New-Item -ItemType Directory -Force -Path $dstRoot | Out-Null

$totalBytes = 0
$totalFiles = 0
foreach ($sub in $subs) {
    $srcSub = Join-Path $Source $sub
    if (-not (Test-Path -LiteralPath $srcSub)) { continue }
    $dstSub = Join-Path $dstRoot $sub

    if (Test-Path -LiteralPath $dstSub) {
        Write-Host ("  " + $sub.PadRight(14) + " -> 已存在，跳过")
        continue
    }

    if ($Mode -eq 'Link') {
        cmd /c mklink /J "$dstSub" "$srcSub" | Out-Null
        Write-Host ("  " + $sub.PadRight(14) + " -> 目录联接（零占用）")
        continue
    }

    $srcBin = Join-Path $srcSub 'bin'
    if (-not (Test-Path -LiteralPath $srcBin)) { continue }
    $dstBin = Join-Path $dstSub 'bin'
    New-Item -ItemType Directory -Force -Path $dstBin | Out-Null
    $files = Get-ChildItem -LiteralPath $srcBin -File -Filter '*.dll'
    foreach ($f in $files) {
        Copy-Item -LiteralPath $f.FullName -Destination $dstBin -Force
        $totalBytes += $f.Length
        $totalFiles += 1
    }
    Write-Host ("  " + $sub.PadRight(14) + " -> " + $files.Count + " 个 DLL")
}

$readme = @()
$readme += "SubAI Translator —— 可选 GPU 包（模式: $Mode）"
$readme += ""
$readme += "把本目录下的 cuda_dlls 整个复制到 SubAI-Translator.exe 同级目录，然后重启后端。"
$readme += "程序会自动识别并由 CPU 切换为 GPU（见 设置 -> 语音识别设备，或 subai-backend.exe --check）。"
@($readme) | Set-Content -Path (Join-Path $OutDir 'README.txt') -Encoding UTF8

if ($Mode -eq 'Copy') {
    $mb = [math]::Round($totalBytes / 1MB, 1)
    Write-Host ""
    Write-Host "完成: $totalFiles 个 DLL,共 $mb MB  ->  $dstRoot"
} else {
    Write-Host ""
    Write-Host "完成: 目录联接已创建 ->  $dstRoot（未复制任何文件）"
}
