#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod commands;

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            commands::check_backend_health,
            commands::start_backend,
            commands::stop_backend,
            commands::get_backend_status,
            commands::get_task_list,
            commands::upload_video,
            commands::start_translation,
            commands::cancel_translation,
            commands::get_task_status,
            commands::get_system_info,
            commands::get_app_config,
            commands::update_app_config,
            commands::get_terminology_list,
            commands::add_terminology,
            commands::get_help_info,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}