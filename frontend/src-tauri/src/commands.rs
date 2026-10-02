use serde::{Deserialize, Serialize};
use std::path::Path;
use std::process::Command;
use tokio::sync::Mutex as TokioMutex;

// --------------------------------------------------------------------------- //
// 数据类型定义
// --------------------------------------------------------------------------- //

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct SystemInfo {
    pub memory_used_gb: f64,
    pub memory_total_gb: f64,
    pub gpu_used_gb: f64,
    pub gpu_total_gb: f64,
    pub gpu_utilization: f64,
}

// --------------------------------------------------------------------------- //
// 全局状态管理
// --------------------------------------------------------------------------- //

struct AppState {
    backend_pid: Option<u32>,
    backend_url: String,
}

lazy_static::lazy_static! {
    static ref APP_STATE: TokioMutex<AppState> = TokioMutex::new(AppState {
        backend_pid: None,
        backend_url: "http://localhost:8000".to_string(),
    });
}

/// 调试日志：写入 exe 同级目录的 tauri_debug.log，用于排查启动链路
fn debug_log(msg: &str) {
    use std::io::Write;
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            let path = dir.join("tauri_debug.log");
            let line = format!("{}\n", msg);
            if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(&path) {
                let _ = f.write_all(line.as_bytes());
            }
        }
    }
}

// --------------------------------------------------------------------------- //
// 后端服务管理
// --------------------------------------------------------------------------- //

#[tauri::command]
pub async fn check_backend_health() -> Result<bool, String> {
    use reqwest::Client;
    
    let state = APP_STATE.lock().await;
    let url = format!("{}/api/health", state.backend_url);
    drop(state);
    
    debug_log(&format!("check_backend_health -> {}", url));
    let client = Client::new();
    match client.get(&url).send().await {
        Ok(resp) => {
            let ok = resp.status().is_success();
            debug_log(&format!("check_backend_health result={}", ok));
            Ok(ok)
        }
        Err(e) => {
            debug_log(&format!("check_backend_health err={}", e));
            Ok(false)
        }
    }
}

#[tauri::command]
pub async fn start_backend() -> Result<String, String> {
    debug_log("start_backend invoked");
    let mut state = APP_STATE.lock().await;

    // 如果已经在运行，直接返回
    if state.backend_pid.is_some() {
        debug_log(&format!("backend already running pid={:?}", state.backend_pid));
        return Ok(format!("后端服务已在运行 (PID: {:?})", state.backend_pid));
    }

    // 优先启动打包后的 sidecar，不存在则回退到 python 开发模式
    let (child, origin) = match resolve_sidecar_path() {
        Some(sidecar) => {
            debug_log(&format!("sidecar resolved: {}", sidecar.display()));
            let dir = sidecar.parent().map(|p| p.to_path_buf()).unwrap_or_else(|| Path::new(".").to_path_buf());
            let child = spawn_sidecar(&sidecar, &dir)
                .map_err(|e| {
                    debug_log(&format!("sidecar spawn FAILED: {}", e));
                    format!("启动后端失败: {}", e)
                })?;
            debug_log(&format!("sidecar spawned pid={}", child.id()));
            (child, format!("sidecar: {}", sidecar.display()))
        }
        None => {
            debug_log("sidecar not found, fallback to python dev mode");
            let project_root = resolve_project_root()
                .ok_or_else(|| "无法定位后端，请设置 SUBAI_ROOT 环境变量".to_string())?;
            let child = hidden_command("python")
                .args(&["-m", "uvicorn", "src.api.server:app", "--host", "0.0.0.0", "--port", "8000"])
                .current_dir(&project_root)
                .spawn()
                .map_err(|e| format!("启动后端失败（请确认 python 在 PATH 中）: {}", e))?;
            (child, format!("python (开发模式, 根目录: {})", project_root.display()))
        }
    };

    let pid = child.id();
    state.backend_pid = Some(pid);
    drop(state);

    // 等待后端就绪
    tokio::time::sleep(tokio::time::Duration::from_secs(3)).await;

    Ok(format!("后端服务已启动 (PID: {}, 来源: {})", pid, origin))
}

/// 创建一个在 Windows 下隐藏控制台窗口的命令。
/// 主程序是 GUI 子系统，直接 Command::new 启动控制台程序（nvidia-smi/taskkill/python）
/// 会触发系统为其临时分配一个控制台窗口，造成周期性闪屏，因此统一加上 CREATE_NO_WINDOW。
fn hidden_command(program: &str) -> Command {
    let mut cmd = Command::new(program);
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    cmd
}

/// 启动 sidecar：Windows 下用 CREATE_NO_WINDOW 隐藏控制台黑框
#[cfg(target_os = "windows")]
fn spawn_sidecar(sidecar: &Path, dir: &Path) -> std::io::Result<std::process::Child> {
    use std::os::windows::process::CommandExt;
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    Command::new(sidecar)
        .current_dir(dir)
        .creation_flags(CREATE_NO_WINDOW)
        .spawn()
}

#[cfg(not(target_os = "windows"))]
fn spawn_sidecar(sidecar: &Path, dir: &Path) -> std::io::Result<std::process::Child> {
    Command::new(sidecar).current_dir(dir).spawn()
}

/// 定位打包后的 sidecar 后端 exe（与主程序同目录，带 target triple 后缀）
fn resolve_sidecar_path() -> Option<std::path::PathBuf> {
    let exe_dir = std::env::current_exe().ok()?.parent()?.to_path_buf();

    #[cfg(target_os = "windows")]
    let exact = exe_dir.join("subai-backend.exe");
    #[cfg(not(target_os = "windows"))]
    let exact = exe_dir.join("subai-backend");

    if exact.exists() {
        return Some(exact);
    }

    // 兜底：枚举目录下 subai-backend 开头的可执行文件
    if let Ok(entries) = std::fs::read_dir(&exe_dir) {
        for entry in entries.flatten() {
            let name = entry.file_name().to_string_lossy().to_string();
            if name.starts_with("subai-backend") {
                return Some(entry.path());
            }
        }
    }

    None
}

/// 解析后端项目根目录（多种策略兜底）
fn resolve_project_root() -> Option<std::path::PathBuf> {
    use std::path::PathBuf;

    // 1) 环境变量
    if let Ok(p) = std::env::var("SUBAI_ROOT") {
        let p = PathBuf::from(p);
        if p.join("src/api/server.py").exists() {
            return Some(p);
        }
    }

    // 2) 从 exe 所在目录向上找 src/api/server.py（最多回溯 5 层）
    if let Ok(exe_path) = std::env::current_exe() {
        let mut cur = exe_path.parent().map(|p| p.to_path_buf());
        for _ in 0..5 {
            if let Some(dir) = &cur {
                if dir.join("src/api/server.py").exists() {
                    return Some(dir.clone());
                }
                cur = dir.parent().map(|p| p.to_path_buf());
            } else {
                break;
            }
        }
    }

    // 3) 当前工作目录 + parent（开发模式）
    if let Ok(cwd) = std::env::current_dir() {
        if let Some(parent) = cwd.parent() {
            if parent.join("src/api/server.py").exists() {
                return Some(parent.to_path_buf());
            }
        }
        if cwd.join("src/api/server.py").exists() {
            return Some(cwd);
        }
    }

    // 这里刻意**不写死任何绝对路径**：写死会把开发机的路径编进发布产物。
    // 上面的 SUBAI_ROOT / 从 exe 逐级向上查找 / 当前工作目录 三种策略，
    // 已覆盖源码方式运行的全部常见情形。
    None
}

/// 同步终止后端进程（taskkill /F /T 连带终止整个子进程树，避免孤儿进程）
fn kill_backend_process(pid: u32) {
    #[cfg(target_os = "windows")]
    {
        let _ = hidden_command("taskkill")
            .args(&["/F", "/T", "/PID", &pid.to_string()])
            .output();
    }

    #[cfg(not(target_os = "windows"))]
    {
        use nix::sys::signal::{self, Signal};
        use nix::unistd::Pid;
        let _ = signal::kill(Pid::from_raw(pid as i32), Signal::SIGTERM);
    }
}

/// 应用退出时清理后端进程（由 main.rs 的窗口销毁事件调用）
pub fn cleanup_backend_on_exit() {
    if let Ok(mut state) = APP_STATE.try_lock() {
        if let Some(pid) = state.backend_pid.take() {
            debug_log(&format!("cleanup_backend_on_exit killing pid={}", pid));
            kill_backend_process(pid);
        }
    }
}

// --------------------------------------------------------------------------- //
// 视频上传处理
// --------------------------------------------------------------------------- //

// --------------------------------------------------------------------------- //
// 翻译任务管理
// --------------------------------------------------------------------------- //

// --------------------------------------------------------------------------- //
// 系统信息监控
// --------------------------------------------------------------------------- //

#[tauri::command]
pub async fn get_system_info() -> Result<SystemInfo, String> {
    // 获取内存信息
    let mem_info = get_memory_info()
        .map_err(|e| format!("获取内存信息失败: {}", e))?;
    
    // 获取 GPU 信息（Windows 使用 nvidia-smi）
    let gpu_info = get_gpu_info()
        .unwrap_or((0.0, 0.0, 0.0));
    
    Ok(SystemInfo {
        memory_used_gb: mem_info.used_gb,
        memory_total_gb: mem_info.total_gb,
        gpu_used_gb: gpu_info.0,
        gpu_total_gb: gpu_info.1,
        gpu_utilization: gpu_info.2,
    })
}

struct MemoryInfo {
    used_gb: f64,
    total_gb: f64,
}

#[cfg(target_os = "windows")]
fn get_memory_info() -> Result<MemoryInfo, String> {
    use std::mem;
    use windows::Win32::System::SystemInformation::{GlobalMemoryStatusEx, MEMORYSTATUSEX};

    let mut mem_info = MEMORYSTATUSEX {
        dwLength: mem::size_of::<MEMORYSTATUSEX>() as u32,
        dwMemoryLoad: 0,
        ullTotalPhys: 0,
        ullAvailPhys: 0,
        ullTotalPageFile: 0,
        ullAvailPageFile: 0,
        ullTotalVirtual: 0,
        ullAvailVirtual: 0,
        ullAvailExtendedVirtual: 0,
        ..unsafe { mem::zeroed() }
    };
    
    unsafe {
        let _ = GlobalMemoryStatusEx(&mut mem_info);
    }
    
    let total_gb = mem_info.ullTotalPhys as f64 / (1024.0_f64).powi(3);
    let used_gb = (mem_info.ullTotalPhys - mem_info.ullAvailPhys) as f64 / (1024.0_f64).powi(3);
    
    Ok(MemoryInfo { used_gb, total_gb })
}

#[cfg(not(target_os = "windows"))]
fn get_memory_info() -> Result<MemoryInfo, String> {
    // Linux/macOS 实现
    Ok(MemoryInfo {
        used_gb: 0.0,
        total_gb: 0.0,
    })
}

fn get_gpu_info() -> Result<(f64, f64, f64), String> {
    #[cfg(target_os = "windows")]
    {
        // 使用 nvidia-smi 获取 GPU 信息
        let output = hidden_command("nvidia-smi")
            .args(&["--query-gpu=memory.used,memory.total,utilization.gpu", "--format=csv,noheader,nounits"])
            .output();
        
        match output {
            Ok(out) => {
                let stdout = String::from_utf8_lossy(&out.stdout);
                let lines: Vec<&str> = stdout.lines().collect();
                
                if let Some(first_line) = lines.first() {
                    let parts: Vec<f64> = first_line
                        .split(',')
                        .map(|s| s.trim().parse::<f64>().unwrap_or(0.0))
                        .collect();
                    
                    if parts.len() == 3 {
                        return Ok((parts[0], parts[1], parts[2]));
                    }
                }
            }
            Err(_) => {}
        }
    }
    
    // 默认返回 0
    Ok((0.0, 0.0, 0.0))
}

// --------------------------------------------------------------------------- //
// 配置管理
// --------------------------------------------------------------------------- //

// --------------------------------------------------------------------------- //
// 术语库管理
// --------------------------------------------------------------------------- //

// --------------------------------------------------------------------------- //
// 帮助信息
// --------------------------------------------------------------------------- //

#[tauri::command]
pub async fn get_help_info() -> Result<serde_json::Value, String> {
    Ok(serde_json::json!({
        "version": "4.1.0",
        "features": [
            "视频字幕识别 (ASR)",
            "硬字幕 OCR 识别",
            "多语言支持（72 种语言，可自动检测）",
            "术语库管理（强制锁定 / 软提示）",
            "多格式输出 (SRT/VTT/ASS/JSON)",
            "视频压制与配音（硬字幕 / 软字幕 / 时间轴对齐配音）",
            "插件系统（翻译 / OCR / TTS 能力可替换，可禁用）",
            "开放平台（API 密钥、限流、Webhook 回调、Python/JS SDK）",
            "数据分析与报表导出（Excel / PDF / HTML）",
            "任务取消与实时进度"
        ],
        "shortcuts": {
            "upload": "拖拽视频文件到上传区域",
            "start": "点击'开始翻译'按钮",
            "cancel": "点击'取消'按钮",
            "plugins": "在插件页启用或禁用翻译、OCR、TTS 能力",
            "openapi": "在开放平台页创建 API 密钥与 Webhook"
        }
    }))
}