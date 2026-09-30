<#
SubAI Translator —— 构建"可选 GPU 包"（不联网下载）
=====================================================
从已安装的 nvidia-* 运行库复制 CUDA DLL，生成可选的 cuda_dlls 目录。
主程序已支持从 <安装目录>/cuda_dlls 自动识别；主包不含这些库，故体积不变。

用法：
  powershell -ExecutionPolicy Bypass -File tools\build_gpu_pack.ps1
  powershell -ExecutionPolicy Bypass -File tools\build_gpu_pack.ps1 -Source "C:\path\to\nvidia" -OutDir "D:\SubAI-Translator\dist-gpu-pack"
#>
param(
    [string]$Source = '',
    [string]$OutDir = 'D:\SubAI-Translator\dist-gpu-pack'
)
$ErrorActionPreference = 'Stop'

if (-not $Source) {
    $Source = Join-Path $PSScriptRoot '..\.venv\Lib\site-packages\nvidia'
}
if (-not (Test-Path -LiteralPath $Source)) {
    Write-Host "找不到来源目录: $Source"
    Write-Host "请先安装 nvidia-cublas-cu12 与 nvidia-cudnn-cu12，或用 -Source 指定已有的 nvidia 目录。"
    exit 2
}
$Source = (Resolve-Path -LiteralPath $Source).Path
Write-Host "来源: $Source"
Write-Host "输出: $OutDir"

$subs = @('cublas', 'cudnn', 'cuda_nvrtc', 'cuda_runtime')
$totalBytes = 0
$totalFiles = 0
foreach ($sub in $subs) {
    $srcBin = Join-Path $Source "$sub\bin"
    if (-not (Test-Path -LiteralPath $srcBin)) { continue }
    $dstBin = Join-Path $OutDir "cuda_dlls\$sub\bin"
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
$readme += "SubAI Translator —— 可选 GPU 包"
$readme += ""
$readme += "把本目录下的 cuda_dlls 整个复制到 SubAI-Translator.exe 同级目录，然后重启后端。"
$readme += "程序会自动识别并由 CPU 切换为 GPU（见 设置 -> 语音识别设备，或 GET /api/system/asr-device）。"
@($readme) | Set-Content -Path (Join-Path $OutDir 'README.txt') -Encoding UTF8

$mb = [math]::Round($totalBytes / 1MB, 1)
Write-Host ""
Write-Host "完成: $totalFiles 个 DLL,共 $mb MB  ->  $OutDir\cuda_dlls"
