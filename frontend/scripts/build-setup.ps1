# SubAI Translator - Windows 打包脚本
# 用于构建和打包 Tauri 应用为 .exe 安装包

Write-Host "===================================" -ForegroundColor Cyan
Write-Host "SubAI Translator - 构建安装包" -ForegroundColor Cyan
Write-Host "===================================" -ForegroundColor Cyan
Write-Host ""

# 检查是否在项目根目录
if (-not (Test-Path "src-tauri\Cargo.toml")) {
    Write-Host "错误：请在 frontend 目录下运行此脚本" -ForegroundColor Red
    exit 1
}

# 步骤 1: 安装前端依赖
Write-Host "[1/4] 检查前端依赖..." -ForegroundColor Yellow
npm ci --production=false
if ($LASTEXITCODE -ne 0) {
    Write-Host "错误：前端依赖安装失败" -ForegroundColor Red
    exit 1
}

# 步骤 2: 构建前端
Write-Host "[2/4] 构建前端..." -ForegroundColor Yellow
npm run build
if ($LASTEXITCODE -ne 0) {
    Write-Host "错误：前端构建失败" -ForegroundColor Red
    exit 1
}

# 步骤 3: 安装 Rust（如果未安装）
Write-Host "[3/4] 检查 Rust 环境..." -ForegroundColor Yellow
$rustc = Get-Command rustc -ErrorAction SilentlyContinue
if (-not $rustc) {
    Write-Host "未检测到 Rust，请先安装 Rust: https://rustup.rs/" -ForegroundColor Red
    Write-Host "运行以下命令安装：" -ForegroundColor Yellow
    Write-Host "   curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh" -ForegroundColor White
    exit 1
}

# 步骤 4: 构建 Tauri 应用
Write-Host "[4/4] 构建 Tauri 应用..." -ForegroundColor Yellow
npx tauri build
if ($LASTEXITCODE -ne 0) {
    Write-Host "错误：Tauri 构建失败" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "===================================" -ForegroundColor Green
Write-Host "构建完成！" -ForegroundColor Green
Write-Host "===================================" -ForegroundColor Green
Write-Host ""
Write-Host "安装包位置：" -ForegroundColor Cyan
Write-Host "   src-tauri\src-tauri-{version}_x64-setup.exe" -ForegroundColor White
Write-Host ""
Write-Host "运行模式开发调试：" -ForegroundColor Cyan
Write-Host "   npm run tauri dev" -ForegroundColor White
Write-Host ""