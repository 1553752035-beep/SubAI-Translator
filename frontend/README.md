# SubAI Translator - Desktop Application

AI-powered video subtitle translation tool built with React + Tauri.

## Features

- ✅ Video upload (drag & drop)
- ✅ Task progress tracking
- ✅ Subtitle editor (double-click to edit)
- ✅ Terminology management
- ✅ Dark theme UI
- ✅ Tauri backend integration

## Prerequisites

- Node.js 18+
- Rust 1.77+
- Windows 10/11 (or macOS / Linux)

## Quick Start

### 1. Install Dependencies

```bash
npm install
```

### 2. Run in Development Mode

```bash
npm run tauri:dev
```

### 3. Build Production Version

```bash
npm run tauri:build
```

## Project Structure

```
frontend/
├── src/                    # React source code
│   ├── api/               # API calls (Tauri commands)
│   ├── components/        # React components
│   ├── hooks/             # Custom hooks
│   ├── styles/            # CSS styles
│   ├── App.tsx            # Main app component
│   └── main.tsx           # Entry point
├── src-tauri/             # Tauri backend (Rust)
│   ├── src/
│   │   ├── main.rs        # Rust main process
│   │   └── commands.rs    # Tauri command handlers
│   ├── Cargo.toml         # Rust dependencies
│   ├── tauri.conf.json    # Tauri configuration
│   └── build.rs           # Build script
├── scripts/               # Helper scripts
│   ├── dev.ps1           # Development mode launcher
│   ├── build-setup.ps1   # Production build script
│   └── test-env.ps1      # Environment check
└── package.json           # NPM configuration
```

## Available Scripts

- `npm run dev` - Start Vite dev server (web preview)
- `npm run build` - Build for production (web)
- `npm run tauri` - Run Tauri CLI
- `npm run tauri:dev` - Run in Tauri development mode
- `npm run tauri:build` - Build Tauri application
- `npm run tauri:build:debug` - Build Tauri application (debug mode)

## Tauri Commands

The application supports the following Tauri commands:

- `check_backend_health` - Check backend service status
- `start_backend` - Start backend service
- `stop_backend` - Stop backend service
- `get_task_list` - Get task list
- `upload_video` - Upload video file
- `start_translation` - Start translation task
- `cancel_translation` - Cancel translation task

## Building & Packaging

### Windows

The build command generates:
- `src-tauri/target/release/bundle/nsis/SubAI Translator_2.0.0_x64-setup.exe` - NSIS installer
- `src-tauri/target/release/bundle/msi/SubAI Translator_2.0.0_x64.msi` - MSI installer

### Code Signing (Optional)

To sign the installer, configure in `tauri.conf.json`:

```json
{
  "windows": {
    "certificateFile": "path/to/certificate.pfx",
    "password": "certificate_password",
    "digestAlgorithm": "sha256"
  }
}
```

## Troubleshooting

### Q: Rust compilation fails

Make sure Rust is installed:
```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
```

### Q: Tauri dev server won't start

Make sure port 5173 is not occupied, or modify `devUrl` in `tauri.conf.json`.

### Q: Built app won't run

Check that `frontendDist` path in `src-tauri/tauri.conf.json` is correct.

## Documentation

- [Tauri Setup Guide](./README-TAURI.md) - Detailed Tauri documentation
- [Rust Installation](./INSTALL-RUST.md) - How to install Rust

## License

MIT License
