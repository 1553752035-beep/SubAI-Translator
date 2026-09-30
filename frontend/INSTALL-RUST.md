# SubAI Translator - Rust 安装指南

## 在 Windows 上安装 Rust

### 方法 1: 使用 rustup（推荐）

1. **下载 rustup-installer**
   - 访问: https://rustup.rs/
   - 下载 `rustup-init.exe`

2. **运行安装程序**
   ```powershell
   # 在 PowerShell 中运行
   .\rustup-init.exe
   ```

3. **选择默认选项**
   - 输入 `1` 使用默认设置（推荐）

4. **验证安装**
   ```powershell
   rustc --version
   cargo --version
   ```

### 方法 2: 使用 Winget

```powershell
winget install Rustlang.Rustup
```

### 方法 3: 使用 Chocolatey

```powershell
choco install rustup
```

## 在 macOS 上安装 Rust

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
```

## 在 Linux 上安装 Rust

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
```

## 验证安装

安装完成后，运行：

```powershell
rustc --version
cargo --version
```

应该显示类似：
```
rustc 1.77.0 (aedd173a2 2024-03-17)
cargo 1.77.0
```

## 常见问题

### Q: 安装后命令不可用

重启终端或运行：
```powershell
# PowerShell
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
```

### Q: Visual Studio Build Tools 依赖

某些 Tauri 功能需要 Visual Studio Build Tools：
1. 运行 Visual Studio Installer
2. 安装 "Desktop development with C++" 工作负载

## 下一步

安装 Rust 后，运行：

```powershell
cd <安装目录>/源码/frontend
npm install
npm run tauri:dev
```