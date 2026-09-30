#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod commands;

fn main() {
    tauri::Builder::default()
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