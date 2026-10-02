# 发布 GitHub Release（含自动更新所需的 latest.json 与签名包）
#
# 用法：
#   $env:GITHUB_TOKEN = "ghp_xxx"      # 需要 repo 权限的 Personal Access Token
#   .\scripts\publish-release.ps1 -Version 4.1.0 -Tag v4.1.0
#
# 说明：
# - 资源目录默认为 D:\SubAI-Translator\release，其中应包含：
#     安装包、最新版绿色版 zip、latest.json、以及 nsis.zip 与其 .sig（自动更新用）
# - 先建 release（已存在则复用），再逐个上传资源
param(
  [string]$Version = "4.1.0",
  [string]$Tag = "v4.1.0",
  [string]$Repo = "1553752035-beep/SubAI-Translator",
  [string]$AssetsDir = "D:\SubAI-Translator\release",
  [string]$Notes = ""
)

$ErrorActionPreference = "Stop"
if (-not $env:GITHUB_TOKEN) { throw "请先设置 `$env:GITHUB_TOKEN（需要 repo 权限的 GitHub Token）" }
if (-not (Test-Path -LiteralPath $AssetsDir)) { throw "资源目录不存在: $AssetsDir" }

$headers = @{
  Authorization = "Bearer $env:GITHUB_TOKEN"
  Accept        = "application/vnd.github+json"
  "User-Agent"  = "SubAI-Translator-Release"
}

# 1) 建 release（422 = 已存在）
$body = @{ tag_name = $Tag; name = $Tag; body = $Notes; draft = $false; prerelease = $false } | ConvertTo-Json
try {
  $rel = Invoke-RestMethod -Method Post -Uri "https://api.github.com/repos/$Repo/releases" `
    -Headers $headers -ContentType "application/json" -Body $body
  Write-Host ("已创建 Release: " + $rel.tag_name)
} catch {
  Write-Host "创建失败（可能已存在），尝试复用既有 Release..."
  $rel = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases/tags/$Tag" -Headers $headers
  Write-Host ("复用 Release: " + $rel.tag_name)
}

# 2) 上传资源（已存在的同名资源跳过）
$existing = @()
if ($rel.assets) { $existing = $rel.assets | ForEach-Object { $_.name } }
Get-ChildItem -LiteralPath $AssetsDir -File | Where-Object { $_.Name -match "\.(exe|zip|sig|json)$" } | ForEach-Object {
  $name = $_.Name
  if ($existing -contains $name) { Write-Host ("跳过（已存在）: " + $name); return }
  $sizeMb = [math]::Round($_.Length / 1MB, 1)
  Write-Host ("上传中: " + $name + "  " + $sizeMb + " MB")
  $uri = "https://uploads.github.com/repos/$Repo/releases/" + $rel.id + "/assets?name=" + [uri]::EscapeDataString($name)
  Invoke-RestMethod -Method Post -Uri $uri -Headers $headers `
    -ContentType "application/octet-stream" -InFile $_.FullName | Out-Null
}

Write-Host "完成。请确认 Release 页面包含 latest.json 与 nsis.zip/.sig（自动更新依赖它们）。"
