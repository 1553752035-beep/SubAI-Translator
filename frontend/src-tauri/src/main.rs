#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

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
        ])
        .on_window_event(|_window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                commands::cleanup_backend_on_exit();
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}