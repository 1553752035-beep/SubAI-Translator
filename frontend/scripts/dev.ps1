# SubAI Translator - 开发模式启动脚本
# 用于在开发模式下运行 Tauri 应用

Write-Host "===================================" -ForegroundColor Cyan
Write-Host "SubAI Translator - 开发模式" -ForegroundColor Cyan
Write-Host "===================================" -ForegroundColor Cyan
Write-Host ""

# 检查是否在项目根目录
if (-not (Test-Path "src-tauri\Cargo.toml")) {
    Write-Host "错误：请在 frontend 目录下运行此脚本" -ForegroundColor Red
    exit 1
}

# 启动 Tauri 开发模式
Write-Host "启动 Tauri 开发服务器..." -ForegroundColor Yellow
npx tauri dev