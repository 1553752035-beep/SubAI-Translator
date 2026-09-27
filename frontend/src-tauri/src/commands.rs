use serde::{Deserialize, Serialize};
use std::fs;
use std::path::Path;
use std::process::Command;
use tokio::sync::Mutex as TokioMutex;

// --------------------------------------------------------------------------- //
// 数据类型定义
// --------------------------------------------------------------------------- //

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct TaskInfo {
    pub id: String,
    pub name: String,
    pub status: String,
    pub progress: f64,
    pub stages: Vec<StageInfo>,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct StageInfo {
    pub name: String,
    pub status: String, // "done", "active", "wait"
    pub description: String,
}

#[derive(Serialize, Deserialize, Debug)]
pub struct BackendStatus {
    pub running: bool,
    pub pid: Option<u32>,
    pub url: String,
}

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
    tasks: Vec<TaskInfo>,
}

lazy_static::lazy_static! {
    static ref APP_STATE: TokioMutex<AppState> = TokioMutex::new(AppState {
        backend_pid: None,
        backend_url: "http://localhost:8000".to_string(),
        tasks: Vec::new(),
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
            let child = Command::new(&sidecar)
                .current_dir(&dir)
                .spawn()
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
            let child = Command::new("python")
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

    // 4) 项目标准路径兜底
    let candidates = [
        PathBuf::from(r"D:\SubAI-Translator"),
        PathBuf::from(r"C:\SubAI-Translator"),
    ];
    for c in candidates {
        if c.join("src/api/server.py").exists() {
            return Some(c);
        }
    }
    None
}

#[tauri::command]
pub async fn stop_backend() -> Result<String, String> {
    let mut state = APP_STATE.lock().await;
    
    let pid = match state.backend_pid {
        Some(p) => p,
        None => return Ok("后端服务未运行".to_string())
    };
    
    // Windows 上终止进程
    #[cfg(target_os = "windows")]
    {
        Command::new("taskkill")
            .args(&["/F", "/PID", &pid.to_string()])
            .output()
            .map_err(|e| format!("终止进程失败: {}", e))?;
    }
    
    #[cfg(not(target_os = "windows"))]
    {
        use nix::sys::signal::{self, Signal};
        use nix::unistd::Pid;
        
        signal::kill(Pid::from_raw(pid as i32), Signal::SIGTERM)
            .map_err(|e| format!("终止进程失败: {}", e))?;
    }
    
    state.backend_pid = None;
    Ok("后端服务已停止".to_string())
}

#[tauri::command]
pub async fn get_backend_status() -> Result<BackendStatus, String> {
    let state = APP_STATE.lock().await;
    
    Ok(BackendStatus {
        running: state.backend_pid.is_some(),
        pid: state.backend_pid,
        url: state.backend_url.clone(),
    })
}

// --------------------------------------------------------------------------- //
// 视频上传处理
// --------------------------------------------------------------------------- //

#[tauri::command]
pub async fn upload_video(file_path: String) -> Result<String, String> {
    let state = APP_STATE.lock().await;
    let backend_url = state.backend_url.clone();
    drop(state);

    // 验证文件是否存在
    if !Path::new(&file_path).exists() {
        return Err(format!("视频文件不存在: {}", file_path));
    }

    // 获取文件大小
    let metadata = fs::metadata(&file_path)
        .map_err(|e| format!("获取文件信息失败: {}", e))?;
    let file_size_mb = metadata.len() as f64 / (1024.0 * 1024.0);

    // 检查文件大小（限制 2GB）
    if file_size_mb > 2048.0 {
        return Err(format!("文件大小超过限制 ({} MB > 2048 MB)", file_size_mb as u64));
    }

    // 通过 HTTP API 上传到后端
    use reqwest::Client;
    let client = Client::new();

    // 调用后端 API 提交任务
    let response = client.post(format!("{}/api/transcode", backend_url))
        .json(&serde_json::json!({
            "video_path": file_path,
            "mode": "asr",
            "target_lang": "en",
            "output_format": "srt"
        }))
        .send()
        .await
        .map_err(|e| format!("上传失败: {}", e))?;

    if !response.status().is_success() {
        let status = response.status();
        let body = response.text().await.unwrap_or_default();
        return Err(format!("后端拒绝上传 (HTTP {}): {}", status, body));
    }

    let result: serde_json::Value = response.json()
        .await
        .map_err(|e| format!("解析响应失败: {}", e))?;

    let task_id = result["task_id"].as_str().unwrap_or("unknown").to_string();
    let file_name = std::path::Path::new(&file_path)
        .file_name().unwrap_or_default().to_string_lossy().to_string();

    // 把新任务写入前端缓存，供 get_task_list 返回
    let mut state = APP_STATE.lock().await;
    state.tasks.push(TaskInfo {
        id: task_id.clone(),
        name: file_name.clone(),
        status: "pending".to_string(),
        progress: 0.0,
        stages: vec![
            StageInfo { name: "ASR".to_string(), status: "wait".to_string(), description: "语音识别".to_string() },
            StageInfo { name: "翻译".to_string(), status: "wait".to_string(), description: "翻译字幕".to_string() },
            StageInfo { name: "输出".to_string(), status: "wait".to_string(), description: "生成字幕文件".to_string() },
        ],
    });
    drop(state);

    Ok(format!("视频上传成功: {} (任务ID: {}, 大小: {:.1} MB)",
               file_name, task_id, file_size_mb))
}

// --------------------------------------------------------------------------- //
// 翻译任务管理
// --------------------------------------------------------------------------- //

#[tauri::command]
pub async fn get_task_list() -> Result<Vec<TaskInfo>, String> {
    use reqwest::Client;

    let backend_url = {
        let state = APP_STATE.lock().await;
        state.backend_url.clone()
    };

    // 从后端拉取历史任务，刷新前端缓存
    let client = Client::new();
    let response = match client
        .get(format!("{}/api/history", backend_url))
        .query(&[("limit", "50")])
        .send()
        .await
    {
        Ok(r) => r,
        Err(e) => {
            // 后端未启动或网络不通——返回前端缓存，不算错误
            let state = APP_STATE.lock().await;
            return Ok(state.tasks.clone());
        }
    };

    if !response.status().is_success() {
        let state = APP_STATE.lock().await;
        return Ok(state.tasks.clone());
    }

    let body: serde_json::Value = response.json()
        .await
        .map_err(|e| format!("解析历史响应失败: {}", e))?;

    // 期望结构：{"tasks": [{"task_id": ..., "status": ..., "progress": ..., "video_path": ...}], "total": N}
    let arr = body["tasks"].as_array().cloned().unwrap_or_default();

    let mut converted: Vec<TaskInfo> = Vec::with_capacity(arr.len());
    for raw in arr {
        let task_id = raw["task_id"].as_str().unwrap_or("").to_string();
        if task_id.is_empty() {
            continue;
        }
        let video_path = raw["video_path"].as_str().unwrap_or("");
        let name = std::path::Path::new(video_path)
            .file_name()
            .map(|s| s.to_string_lossy().to_string())
            .unwrap_or_else(|| task_id.clone());
        let status = raw["status"].as_str().unwrap_or("pending").to_string();
        let progress = raw["progress"].as_f64().unwrap_or(0.0);
        let message = raw["message"].as_str().unwrap_or("");

        // 根据 status 推导阶段
        let (asr_st, tr_st, out_st) = match status.as_str() {
            "pending" => ("wait", "wait", "wait"),
            "processing" if progress < 0.3 => ("active", "wait", "wait"),
            "processing" if progress < 0.6 => ("done", "active", "wait"),
            "processing" if progress < 0.95 => ("done", "active", "wait"),
            "completed" => ("done", "done", "done"),
            "failed" => ("done", "wait", "wait"),
            _ => ("wait", "wait", "wait"),
        };

        converted.push(TaskInfo {
            id: task_id,
            name,
            status,
            progress,
            stages: vec![
                StageInfo {
                    name: "ASR".to_string(),
                    status: asr_st.to_string(),
                    description: if message.is_empty() { "语音识别".to_string() } else { message.to_string() },
                },
                StageInfo { name: "翻译".to_string(), status: tr_st.to_string(), description: "翻译字幕".to_string() },
                StageInfo { name: "输出".to_string(), status: out_st.to_string(), description: "生成字幕文件".to_string() },
            ],
        });
    }

    // 同步回写到前端缓存（保持一致）
    {
        let mut state = APP_STATE.lock().await;
        state.tasks = converted.clone();
    }

    Ok(converted)
}

#[tauri::command]
pub async fn start_translation(task_id: String) -> Result<String, String> {
    let state = APP_STATE.lock().await;
    let backend_url = state.backend_url.clone();
    drop(state);

    // 调用后端 API 查询任务状态
    use reqwest::Client;
    let client = Client::new();

    let response = client.get(format!("{}/api/task/{}", backend_url, task_id))
        .send()
        .await
        .map_err(|e| format!("查询任务失败: {}", e))?;

    let task_data: serde_json::Value = response.json()
        .await
        .map_err(|e| format!("解析响应失败: {}", e))?;

    let status = task_data["status"].as_str().unwrap_or("unknown");

    Ok(format!("任务 {} 当前状态: {}", task_id, status))
}

#[tauri::command]
pub async fn cancel_translation(task_id: String) -> Result<String, String> {
    use reqwest::Client;

    let backend_url = {
        let state = APP_STATE.lock().await;
        state.backend_url.clone()
    };

    let client = Client::new();
    let response = client
        .delete(format!("{}/api/task/{}", backend_url, task_id))
        .send()
        .await
        .map_err(|e| format!("取消请求失败: {}", e))?;

    if !response.status().is_success() {
        // 即使后端没接 DELETE 路由，也别让前端死——降级返回状态文本
        let status = response.status();
        return Ok(format!("后端未实现取消接口（HTTP {}），但任务 {} 已在前端标记", status, task_id));
    }

    let body: serde_json::Value = response.json().await.unwrap_or(serde_json::json!({}));
    let msg = body["message"].as_str().unwrap_or("已取消");
    Ok(format!("任务 {}：{}", task_id, msg))
}

#[tauri::command]
pub async fn get_task_status(task_id: String) -> Result<String, String> {
    let state = APP_STATE.lock().await;
    let backend_url = state.backend_url.clone();
    drop(state);
    
    use reqwest::Client;
    let client = Client::new();
    
    let response = client.get(format!("{}/api/task/{}", backend_url, task_id))
        .send()
        .await
        .map_err(|e| format!("查询任务失败: {}", e))?;
    
    let task_data: serde_json::Value = response.json()
        .await
        .map_err(|e| format!("解析响应失败: {}", e))?;
    
    Ok(serde_json::to_string_pretty(&task_data)
        .map_err(|e| format!("序列化失败: {}", e))?)
}

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
        GlobalMemoryStatusEx(&mut mem_info);
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
        let output = Command::new("nvidia-smi")
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

#[tauri::command]
pub async fn get_app_config() -> Result<serde_json::Value, String> {
    // 优先读用户配置文件，没有就用默认值
    if let Ok(path) = resolve_app_config_path() {
        if path.exists() {
            if let Ok(content) = fs::read_to_string(&path) {
                if let Ok(val) = serde_json::from_str::<serde_json::Value>(&content) {
                    return Ok(val);
                }
            }
        }
    }
    Ok(serde_json::json!({
        "backend_url": "http://localhost:8000",
        "max_concurrent": 2,
        "auto_start_backend": true,
        "output_format": "srt"
    }))
}

#[tauri::command]
pub async fn update_app_config(config: serde_json::Value) -> Result<String, String> {
    // 持久化到 app data 目录的 config.json
    let config_path = resolve_app_config_path()?;
    fs::create_dir_all(config_path.parent().unwrap())
        .map_err(|e| format!("创建配置目录失败: {}", e))?;
    let pretty = serde_json::to_string_pretty(&config)
        .map_err(|e| format!("序列化配置失败: {}", e))?;
    fs::write(&config_path, pretty)
        .map_err(|e| format!("写入配置文件失败: {}", e))?;
    Ok(format!("配置已保存到 {}", config_path.display()))
}

/// 解析用户级配置文件路径
fn resolve_app_config_path() -> Result<std::path::PathBuf, String> {
    if cfg!(target_os = "windows") {
        let appdata = std::env::var("APPDATA")
            .map_err(|e| format!("获取 APPDATA 环境变量失败: {}", e))?;
        Ok(std::path::PathBuf::from(appdata)
            .join("SubAI-Translator")
            .join("config.json"))
    } else {
        let home = std::env::var("HOME")
            .map_err(|e| format!("获取 HOME 环境变量失败: {}", e))?;
        Ok(std::path::PathBuf::from(home)
            .join(".config")
            .join("subai-translator")
            .join("config.json"))
    }
}

// --------------------------------------------------------------------------- //
// 术语库管理
// --------------------------------------------------------------------------- //

#[tauri::command]
pub async fn get_terminology_list() -> Result<String, String> {
    let state = APP_STATE.lock().await;
    let backend_url = state.backend_url.clone();
    drop(state);
    
    use reqwest::Client;
    let client = Client::new();
    
    let response = client.get(format!("{}/api/terminology", backend_url))
        .send()
        .await
        .map_err(|e| format!("查询失败: {}", e))?;
    
    let terms: serde_json::Value = response.json()
        .await
        .map_err(|e| format!("解析失败: {}", e))?;
    
    Ok(serde_json::to_string_pretty(&terms)
        .map_err(|e| format!("序列化失败: {}", e))?)
}

#[tauri::command]
pub async fn add_terminology(source_text: String, translation: String, priority: String) -> Result<String, String> {
    let state = APP_STATE.lock().await;
    let backend_url = state.backend_url.clone();
    drop(state);
    
    use reqwest::Client;
    let client = Client::new();
    
    let response = client.post(format!("{}/api/terminology", backend_url))
        .json(&serde_json::json!({
            "source_text": source_text,
            "translation": translation,
            "priority": priority
        }))
        .send()
        .await
        .map_err(|e| format!("添加失败: {}", e))?;
    
    let result: serde_json::Value = response.json()
        .await
        .map_err(|e| format!("解析失败: {}", e))?;
    
    Ok(result["message"].as_str().unwrap_or("术语已添加").to_string())
}

// --------------------------------------------------------------------------- //
// 帮助信息
// --------------------------------------------------------------------------- //

#[tauri::command]
pub async fn get_help_info() -> Result<serde_json::Value, String> {
    Ok(serde_json::json!({
        "version": "2.0.0",
        "features": [
            "视频字幕识别 (ASR)",
            "硬字幕 OCR 识别",
            "多格式输出 (SRT/VTT/ASS/JSON)",
            "术语库管理",
            "实时进度显示"
        ],
        "shortcuts": {
            "upload": "拖拽视频文件到上传区域",
            "start": "点击'开始翻译'按钮",
            "cancel": "点击'取消'按钮"
        }
    }))
}