#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri::Manager;   // 五期：get_webview_window 需要这个 trait

mod commands;

fn main() {
    tauri::Builder::default()
        // 四期深化：自动更新与重启（前端用 @tauri-apps/plugin-updater 调用）
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .invoke_handler(tauri::generate_handler![
            commands::check_backend_health,
            commands::start_backend,
            commands::get_system_info,
            commands::get_help_info,
            commands::get_local_token,
            commands::open_in_explorer,
            commands::open_external,
        ])
        // 五期：把本机令牌注入网页（window.__SUBAI_LOCAL_TOKEN__）。
        // 不走 invoke：invoke 在某些环境会挂住，页面上就永远"正在连接"。
        .setup(|app| {
            let handle = app.handle().clone();
            std::thread::spawn(move || {
                for _ in 0..120 {
                    if let Some(token) = commands::read_local_token_file() {
                        if let Some(win) = handle.get_webview_window("main") {
                            let js = format!("window.__SUBAI_LOCAL_TOKEN__ = {:?};", token);
                            let _ = win.eval(&js);
                        }
                        return;
                    }
                    std::thread::sleep(std::time::Duration::from_millis(500));
                }
            });
            Ok(())
        })
        .on_window_event(|_window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                commands::cleanup_backend_on_exit();
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}