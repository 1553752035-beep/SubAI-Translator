# SubAI Translator - Environment Check
Write-Host "===================================" -ForegroundColor Cyan
Write-Host "SubAI Translator - Environment Check" -ForegroundColor Cyan
Write-Host "===================================" -ForegroundColor Cyan
Write-Host ""

# Check Node.js
Write-Host "[1/4] Checking Node.js..." -ForegroundColor Yellow
try {
    $nodeVersion = node --version
    Write-Host "  [OK] Node.js installed: $nodeVersion" -ForegroundColor Green
} catch {
    Write-Host "  [ERROR] Node.js not installed" -ForegroundColor Red
}

# Check npm
Write-Host "[2/4] Checking npm..." -ForegroundColor Yellow
try {
    $npmVersion = npm --version
    Write-Host "  [OK] npm installed: v$npmVersion" -ForegroundColor Green
} catch {
    Write-Host "  [ERROR] npm not installed" -ForegroundColor Red
}

# Check Rust
Write-Host "[3/4] Checking Rust..." -ForegroundColor Yellow
try {
    $rustVersion = rustc --version
    Write-Host "  [OK] Rust installed: $rustVersion" -ForegroundColor Green
} catch {
    Write-Host "  [ERROR] Rust not installed" -ForegroundColor Red
}

# Check Cargo
Write-Host "[4/4] Checking Cargo..." -ForegroundColor Yellow
try {
    $cargoVersion = cargo --version
    Write-Host "  [OK] Cargo installed: $cargoVersion" -ForegroundColor Green
} catch {
    Write-Host "  [ERROR] Cargo not installed" -ForegroundColor Red
}

Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "1. Install dependencies: npm install" -ForegroundColor White
Write-Host "2. Run dev mode: npm run tauri:dev" -ForegroundColor White
Write-Host "3. Build production: npm run tauri:build" -ForegroundColor White
Write-Host ""