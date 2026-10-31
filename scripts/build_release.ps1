# SubAI Translator 发布打包门禁（2026-10-17 新增）
#
# 目的：把「打包铁律」变成一条命令，避免再次产出「新前端 + 旧后端」的混搭包。
# 背景：Tauri 的 externalBin 打包的是副本
#         frontend/src-tauri/binaries/subai-backend-x86_64-pc-windows-msvc.exe
#       而 PyInstaller 的输出在 源码/dist/subai-backend.exe；两者不同步时，
#       安装包里就是新前端 + 旧后端（v5.0.0 即如此，10-03 的接口全 404）。
#
# 用法（在 源码 目录下执行）：
#   powershell -ExecutionPolicy Bypass -File scripts/build_release.ps1
#   可选开关：-Lite 精简版(不含模型) / -Sign 完整版+签名 / -SkipTests / -NoSync / -SkipBackend

param(
    [switch]$Lite,
    [switch]$Sign,
    [switch]$SkipTests,
    [switch]$NoSync,
    [switch]$SkipBackend
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$frontend = Join-Path $root 'frontend'
$distExe = Join-Path $root 'dist/subai-backend.exe'
$binCopy = Join-Path $frontend 'src-tauri/binaries/subai-backend-x86_64-pc-windows-msvc.exe'

function Step($n, $t) { Write-Host ''; Write-Host ('[{0}] {1}' -f $n, $t) -ForegroundColor Cyan }
function Ok($m)   { Write-Host ('  OK  ' + $m) -ForegroundColor Green }
function Bad($m)  { Write-Host ('  ERR ' + $m) -ForegroundColor Red }
function Warn($m) { Write-Host ('  !!  ' + $m) -ForegroundColor Yellow }

$ver = (Select-String -Path (Join-Path $root 'src/__init__.py') -Pattern '__version__\s*=\s*"([^"]+)"' |
        Select-Object -First 1).Matches[0].Groups[1].Value
if (-not $ver) { Bad '读不到 src/__init__.py 的 __version__'; exit 1 }
Write-Host ('SubAI Translator 打包门禁  v{0}   {1}' -f $ver, (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')) -ForegroundColor White

# ---- 铁律①：语法/导入自检（PyInstaller 遇语法错误会静默产出残 exe）----
Step 1 '导入自检'
& python -c "import src.api.server"
if ($LASTEXITCODE -ne 0) { Bad 'import src.api.server 失败 —— 这是真语法/导入错误，不是环境问题'; exit 1 }
Ok 'src.api.server 可导入'

# ---- 铁律③：测试门禁 ----
if (-not $SkipTests) {
    Step 2 '后端测试'
    Push-Location $root
    $env:RUN_API_TESTS = '1'
    & python -m pytest tests -q
    $code = $LASTEXITCODE
    Pop-Location
    if ($code -ne 0) { Bad '后端测试未通过'; exit 1 }
    Ok '后端测试通过'

    Step 3 '前端测试'
    Push-Location $frontend
    & npx vitest run --silent 2>&1 | Select-Object -Last 4
    $code = $LASTEXITCODE
    Pop-Location
    if ($code -ne 0) { Bad '前端测试未通过'; exit 1 }
    Ok '前端测试通过'
} else { Warn '已跳过测试（-SkipTests）' }

# ---- 后端 exe 重建（可选）----
if (-not $SkipBackend) {
    Step 4 '重建后端 exe（PyInstaller，约 2 分钟）'
    Push-Location $root
    # 坑：PyInstaller 把 INFO 写到 stderr，PowerShell 5.1 在 ErrorActionPreference=Stop 下
    # 会把 native 命令的 stderr 当成 terminating error。这里临时放宽，用 $LASTEXITCODE 判定成败。
    $prevEA = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & python -m PyInstaller subai_backend.spec --noconfirm 2>&1 | Select-Object -Last 3
    $code = $LASTEXITCODE
    $ErrorActionPreference = $prevEA
    Pop-Location
    if ($code -ne 0 -or -not (Test-Path $distExe)) { Bad 'PyInstaller 失败'; exit 1 }
    Ok ('dist/subai-backend.exe  {0:N0} bytes' -f (Get-Item $distExe).Length)
} else {
    if (-not (Test-Path $distExe)) { Bad '找不到 dist/subai-backend.exe，请先构建或去掉 -SkipBackend'; exit 1 }
    Warn '已跳过后端重建（沿用现有 dist 产物）'
}

# ---- 铁律⑤（新增）：打包副本必须与 dist 完全一致 ----
Step 5 '同步打包副本（防「新前端 + 旧后端」）'
if (-not (Test-Path $binCopy)) { Bad "缺少打包副本：$binCopy"; exit 1 }
$h1 = (Get-FileHash $distExe -Algorithm SHA256).Hash
$h2 = (Get-FileHash $binCopy -Algorithm SHA256).Hash
if ($h1 -eq $h2) {
    Ok 'binaries 副本与 dist 一致'
} elseif ($NoSync) {
    Bad 'binaries 副本与 dist 不一致（-NoSync 下不自动修）'; exit 1
} else {
    Warn 'binaries 副本与 dist 不一致 —— 自动同步'
    Copy-Item $distExe $binCopy -Force
    Ok '已同步'
}

# ---- 误打包断言：models 不能是 junction（否则会把临时模型打进安装包）----
Step 5.5 '模型目录检查'
$mdl = Join-Path (Split-Path $root -Parent) 'models/faster-whisper-small'
if (Test-Path $mdl) {
    $it = Get-Item $mdl -Force
    if ($it.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        Bad "models/faster-whisper-small 是 junction/符号链接 —— 打包会把它指向的模型整包打进去。"
        Bad "请先恢复真实目录（或改用 SUBAI_ASR_MODEL_DIR 指向外部模型）后再打包。"
        exit 1
    }
    Ok 'models/faster-whisper-small 是真实目录'
} else { Warn '未找到 models/faster-whisper-small（安装包将不含 ASR 模型）' }

# ---- 打包 ----
Step 6 '打安装包（NSIS）'
Push-Location $frontend
$buildArgs = @('run', 'tauri:build', '--', '--bundles', 'nsis')
if ($Lite) { $buildArgs += @('--config', 'src-tauri/tauri.lite.conf.json') }
if ($Sign) {
    if (-not $env:TAURI_SIGNING_PRIVATE_KEY) {
        $keyFile = Join-Path $env:USERPROFILE '.tauri/subai-updater.key'
        if (-not (Test-Path $keyFile)) { Bad "找不到签名私钥：$keyFile"; exit 1 }
        $env:TAURI_SIGNING_PRIVATE_KEY = Get-Content $keyFile -Raw
    }
    $buildArgs += @('--config', 'src-tauri/tauri.release.conf.json')
    Warn '签名会停在 Password 提示 —— 必须在前台终端运行并直接回车（后台运行会永久挂起）'
}
$prevEA = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
& npm @buildArgs 2>&1 | Select-Object -Last 6
$code = $LASTEXITCODE
$ErrorActionPreference = $prevEA
Pop-Location
if ($code -ne 0) { Bad 'tauri build 失败'; exit 1 }

# ---- 产物校验 ----
Step 7 '产物校验'
$nsis = Join-Path $frontend 'src-tauri/target/release/bundle/nsis'
$setup = Get-ChildItem $nsis -Filter '*_x64-setup.exe' -ErrorAction SilentlyContinue |
         Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $setup) { Bad "找不到安装包：$nsis"; exit 1 }
$sizeMB = [math]::Round($setup.Length / 1MB, 0)
Ok ('安装包：{0}  {1:N0} MB' -f $setup.Name, $sizeMB)
$minimum = if ($Lite) { 200 } else { 550 }
if ($sizeMB -lt $minimum) { Bad ('体积仅 {0} MB，低于预期（{1} MB）—— 可能漏了模型或后端' -f $sizeMB, $minimum); exit 1 }
Ok ('SHA256: ' + (Get-FileHash $setup.FullName -Algorithm SHA256).Hash)
$sig = "$($setup.FullName).sig"
if ($Sign -and (Test-Path $sig)) { Ok ('签名文件：' + (Split-Path -Leaf $sig)) }
elseif ($Sign) { Warn '期待 .sig 但没找到（签名配置可能未生效）' }

Write-Host ''
Write-Host ('打包完成：v{0}  {1}' -f $ver, $setup.FullName) -ForegroundColor Green

# ---- 分发安全检查（P1-3）：安装包本身不含 .env，但手工分发绿色版目录会带 ----------
Step 8 '分发安全检查'
$installRoot = Split-Path $root -Parent
$envFile = Join-Path $installRoot '.env'
if (Test-Path $envFile) {
    if ((Get-Content $envFile -Raw) -match 'API_KEY=\S+') {
        Warn "安装根 $envFile 含 API Key —— 手工分发绿色版目录前请先删掉它（安装包不受影响）"
    } else { Ok '.env 存在但未见 Key' }
} else { Ok '安装根无 .env' }

Write-Host '人工验收：① 安装 ② 启动后左下角「后端服务运行中」 ③ 跑短视频出字幕草稿 ④ 改一句 ⑤ 生成视频' -ForegroundColor Yellow