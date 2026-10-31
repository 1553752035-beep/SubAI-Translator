<#
SubAI Translator —— 生成 updater 的 latest.json
=================================================
Tauri 自动更新靠两样东西：安装包旁的 .sig（构建时用私钥生成）与远端 latest.json。
历史问题：仓库里 latest.json 一直停在 4.1.0，而应用内 updater 指向 releases/latest，
于是「检查更新」永远拿不到 5.x —— 用户侧表现为"已是最新"或直接失败。

发布时一条命令：

  powershell -ExecutionPolicy Bypass -File tools\make_latest_json.ps1 -Version 5.0.1 -SetupExe ..\release\SubAI-Translator-Setup-5.0.1-lite.exe -DownloadUrl https://github.com/<owner>/<repo>/releases/download/v5.0.1/SubAI-Translator-Setup-5.0.1-lite.exe -Notes "修复两段式与打包混搭"

前置条件：安装包同级存在同名 .sig 文件（tauri build 自动生成）。
签名缺失时脚本报错退出，绝不生成"看起来正常"的 latest.json。
#>
param(
    [Parameter(Mandatory = $true)][string]$Version,
    [Parameter(Mandatory = $true)][string]$SetupExe,
    [Parameter(Mandatory = $true)][string]$DownloadUrl,
    [string]$Notes = '',
    [string]$OutFile = '',
    [string]$RepoRoot = ''
)
$ErrorActionPreference = 'Stop'

if (-not $RepoRoot) { $RepoRoot = Split-Path $PSScriptRoot -Parent }
$installRoot = Split-Path $RepoRoot -Parent
if (-not $OutFile) { $OutFile = Join-Path $installRoot 'release\latest.json' }

if ($Version -notmatch '^\d+\.\d+\.\d+') {
    Write-Host "版本号格式不对: $Version（应形如 5.0.1）"
    exit 2
}
if (-not (Test-Path -LiteralPath $SetupExe)) {
    Write-Host "找不到安装包: $SetupExe"
    exit 2
}
$sigFile = "$SetupExe.sig"
if (-not (Test-Path -LiteralPath $sigFile)) {
    Write-Host "找不到签名文件: $sigFile"
    Write-Host '自动更新包必须由 tauri build 产出（会同时生成 .sig）。'
    Write-Host '手工改名/搬移安装包会导致签名丢失 —— 这与 v5.0.0 出现「新前端+旧后端混搭」是同源问题。'
    exit 2
}

$signature = (Get-Content -LiteralPath $sigFile -Raw).Trim()
if (-not $signature) {
    Write-Host "签名文件为空: $sigFile"
    exit 2
}

$payload = [ordered]@{
    version  = $Version
    notes    = $Notes
    pub_date = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    platforms = [ordered]@{
        'windows-x86_64' = [ordered]@{
            signature = $signature
            url       = $DownloadUrl
        }
    }
}

$json = $payload | ConvertTo-Json -Depth 6
$dir = Split-Path $OutFile -Parent
if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
# JSON 用无 BOM UTF-8：带 BOM 会让部分解析器报错
[System.IO.File]::WriteAllText($OutFile, $json, (New-Object System.Text.UTF8Encoding($false)))

Write-Host "已生成: $OutFile"
Write-Host "  version : $Version"
Write-Host "  url     : $DownloadUrl"
Write-Host "  签名长度: $($signature.Length)"
Write-Host ''
Write-Host '发布检查清单：'
Write-Host '  1) 该 latest.json 必须上传到 releases/latest/download/latest.json（updater 指向的固定地址）'
Write-Host '  2) 安装包本体也要上传到 url 指向的位置，否则客户端下载 404'
Write-Host '  3) 上传后用旧版客户端点一次「检查更新」真实验证'
