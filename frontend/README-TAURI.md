# SubAI Translator - Tauri 桌面应用

这是一个使用 React + Tauri 构建的桌面应用程序，用于视频字幕翻译。

## 系统要求

- Node.js 18+ 
- Rust 1.77+
- Windows 10/11 (或 macOS / Linux)

## 快速开始

### 1. 安装依赖

```bash
npm install
```

### 2. 开发模式运行

```bash
npm run tauri:dev
```

或在 PowerShell 中：

```powershell
.\scripts\dev.ps1
```

### 3. 构建生产版本

```bash
npm run tauri:build
```

或在 PowerShell 中：

```powershell
.\scripts\build-setup.ps1
```

## 项目结构

```
frontend/
├── src/                    # React 源代码
│   ├── api/               # API 调用层 (Tauri 命令)
│   ├── components/        # React 组件
│   ├── hooks/             # 自定义 Hooks
│   ├── styles/            # CSS 样式
│   ├── App.tsx            # 主应用组件
│   └── main.tsx           # 入口文件
├── src-tauri/             # Tauri 后端 (Rust)
│   ├── src/
│   │   ├── main.rs        # Rust 主进程
│   │   └── commands.rs    # Tauri 命令处理
│   ├── Cargo.toml         # Rust 依赖配置
│   ├── tauri.conf.json    # Tauri 配置
│   └── build.rs           # 构建脚本
├── scripts/               # 辅助脚本
│   ├── dev.ps1           # 开发模式启动脚本
│   └── build-setup.ps1   # 生产构建脚本
└── package.json           # NPM 配置
```

## 功能特性

### 已实现功能

- ✅ 视频上传界面（拖拽上传）
- ✅ 任务进度显示
- ✅ 字幕编辑器（双击编辑）
- ✅ 术语库管理
- ✅ 暗色主题 UI
- ✅ 与 Tauri 后端通信

### 待实现功能

- ⏳ 实际视频处理（需要后端支持）
- ⏳ 字幕导出（SRT/VTT/ASS）
- ⏳ 自动更新
- ⏳ 系统托盘
- ⏳ 文件关联

## Tauri 命令

应用支持以下 Tauri 命令：

- `check_backend_health` - 检查后端服务状态
- `start_backend` - 启动后端服务
- `stop_backend` - 停止后端服务
- `get_task_list` - 获取任务列表
- `upload_video` - 上传视频文件
- `start_translation` - 开始翻译任务
- `cancel_translation` - 取消翻译任务

## 打包配置

### Windows

构建命令会生成：
- `src-tauri/target/release/bundle/nsis/SubAI Translator_2.0.0_x64-setup.exe` - NSIS 安装包
- `src-tauri/target/release/bundle/msi/SubAI Translator_2.0.0_x64.msi` - MSI 安装包

### 代码签名（可选）

若要签名安装包，需要在 `tauri.conf.json` 中配置：

```json
{
  "windows": {
    "certificateFile": "path/to/certificate.pfx",
    "password": "certificate_password",
    "digestAlgorithm": "sha256"
  }
}
```

## 常见问题

### Q: Rust 编译失败

确保已安装 Rust：
```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
```

### Q: Tauri 开发服务器无法启动

确保端口 5173 未被占用，或修改 `tauri.conf.json` 中的 `devUrl`。

### Q: 打包后应用无法运行

检查 `src-tauri/tauri.conf.json` 中的 `frontendDist` 路径是否正确。

## 开发指南

### 添加新的 Tauri 命令

1. 在 `src-tauri/src/commands.rs` 中添加命令函数
2. 在 `src-tauri/src/main.rs` 中注册命令
3. 在 `src/api/tauri.ts` 中添加前端调用函数

### 修改 UI 样式

所有样式都在 `src/styles/design-system.css` 中定义。

### 添加新页面

1. 在 `src/pages/` 创建新页面组件
2. 在 `App.tsx` 中添加路由和导航项

## 许可证

MIT License

## 联系方式

如有问题，请提交 Issue 或联系开发团队。